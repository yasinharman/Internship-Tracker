"""
CARRYING A REAL BROWSER SESSION
===============================

Some boards show an anonymous visitor one page of results and ask everyone
else to sign in. Indeed is one: page two answers with
`307 -> secure.indeed.com/auth?...&branding=page-two-signin`.

The way past it is not to imitate a session but to carry a real one - the
cookies from a browser that is actually signed in, exported by hand and
handed to the spider through the environment.

    INDEED_COOKIES="CTK=abc...; SESSION_ID=def...; PPID=ghi..."
    INDEED_COOKIES=/run/secrets/indeed_cookies.json   (a path works too)
    INDEED_COOKIES_B64=Q1RLPWFiYy4uLg==               (and so does base64)

THE BASE64 FORM IS FOR PANELS
-----------------------------
A real Indeed session is about 5 KB and contains double quotes inside its
values (RF=, SOCK=, SHOE=, PREF=). Locally that ruled out putting it in .env
- no quoting style survived it - and a file was used instead. On a hosting
panel a file is worse: it means a mount, a copy, and a second place the
account lives.

Base64 has no quotes, no semicolons and no newlines, so it survives any
environment-variable box, and it is decoded here rather than being something
the deployment has to get right. `_B64` wins when both are set.

WHY IT IS NOT AUTOMATED
-----------------------
Signing in is a one-off manual step on purpose. Indeed's sign-in sends a code
to an email address, so scripting it means scripting a mailbox - more moving
parts than the crawl itself, and every one of them a new way for a scheduled
run to fail at 03:00. Logging in by hand every few weeks is a minute of work.

WHAT TO DO WHEN THEY EXPIRE
---------------------------
Sign in again in the browser, copy the Cookie header again, replace the
value. The spider says so explicitly when it happens - see
IndeedCardsSpider's handling of the sign-in wall - rather than letting an
expired session look like an address that has been blocked. Telling those two
apart by hand cost an afternoon once already.

MATCH THE BROWSER YOU SIGNED IN WITH
------------------------------------
A session created in Chrome and then used under a Firefox User-Agent is a
session being used by something other than what created it, which is a
cheaper signal to spot than any of the ones we spent today measuring. Sign in
with the browser whose handshake the spider replays.

Today that means FIREFOX: Cloudflare currently challenges every Chrome
fingerprint curl_cffi can produce and waves Firefox through (see
IMPERSONATE_CANDIDATES in spiders/indeed_cards.py). Set INDEED_IMPERSONATE
and the User-Agent to match whatever browser you actually used.

THESE ARE CREDENTIALS
---------------------
A session cookie is the account. It goes in .env (gitignored) or a Coolify
secret, never in the repo, and nothing here ever logs its value - see
describe(), which is what the logs get.
"""

import base64
import binascii
import json
import os
import re


def _parse_header_string(raw):
    """
    Turn a copied `Cookie:` header into a dict.

        "CTK=abc; SESSION_ID=def"  ->  {"CTK": "abc", "SESSION_ID": "def"}

    Written for the value you get from DevTools -> Network -> any request ->
    Request Headers -> Cookie, because that is the copy-paste a person can
    actually do without installing an extension. A leading "Cookie:" is
    tolerated; so is the whitespace that comes with copying out of a browser.
    """
    raw = raw.strip()
    if raw.lower().startswith("cookie:"):
        raw = raw.split(":", 1)[1].strip()

    cookies = {}
    for pair in raw.split(";"):
        pair = pair.strip()
        if not pair or "=" not in pair:
            continue
        name, value = pair.split("=", 1)
        name = name.strip()
        if name:
            cookies[name] = value.strip()
    return cookies


def _parse_json(text):
    """
    Accept what cookie-exporting extensions produce.

    Either a plain object, or the list-of-objects shape every
    "Export cookies" extension uses:

        {"CTK": "abc"}
        [{"name": "CTK", "value": "abc", "domain": ".indeed.com", ...}]
    """
    data = json.loads(text)

    if isinstance(data, dict):
        return {str(k): str(v) for k, v in data.items()}

    cookies = {}
    for entry in data:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if name:
            cookies[str(name)] = str(entry.get("value", ""))
    return cookies


def _decode_base64(encoded, env_var):
    """
    Decode what a panel stored, not what base64 says it should have stored.

    An environment-variable box is a text field with a person and a clipboard
    on one side of it, so the value arrives wrapped in quotes, or broken over
    lines, or with the line breaks turned into a literal backslash-n, or in
    the url-safe alphabet. None of that is the session being wrong, and all
    of it used to arrive as `binascii.Error: Only base64 data is allowed`,
    which says nothing about which of those happened.

    So: clean the things that are known not to be data, then refuse - loudly
    and specifically - if anything is left that cannot be base64.
    """
    cleaned = "".join(encoded.split())          # spaces, tabs, real newlines
    cleaned = cleaned.replace("\\n", "").replace("\\r", "")  # escaped ones
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in "\"'":
        cleaned = cleaned[1:-1]                 # a panel that kept the quotes
    cleaned = cleaned.replace("-", "+").replace("_", "/")    # url-safe alphabet

    stray = sorted(set(re.findall(r"[^A-Za-z0-9+/=]", cleaned)))
    if stray:
        # The first thing this ever went wrong on, on the server, 30.07.2026:
        # the variable held the NAME of the file holding the base64 rather
        # than the base64. Worth naming, because "not valid base64" sends you
        # looking for a mangled paste instead of at the value itself. Only
        # INDEED_COOKIES takes a path; this one takes the contents.
        # Short, and shaped like a name or a path. We are already in the
        # error branch, so nothing that would otherwise have loaded is at
        # risk of being described this way.
        looks_like_a_filename = (
            len(cleaned) < 200 and ("." in cleaned or "/" in cleaned)
        )
        hint = (
            f"That looks like a filename. This variable takes the CONTENTS of "
            f"the file, not its name - {env_var[:-4]} is the one that accepts "
            f"a path."
            if looks_like_a_filename else
            f"The value was probably mangled on its way into the environment "
            f"- re-paste it as a single line with no quotes."
        )
        raise ValueError(
            f"{env_var} holds {len(encoded)} characters that are not base64: "
            f"found {', '.join(repr(c) for c in stray[:8])}. {hint}"
        )

    cleaned += "=" * (-len(cleaned) % 4)        # padding a copy can lose

    try:
        return base64.b64decode(cleaned).decode("utf-8")
    except (binascii.Error, ValueError, UnicodeDecodeError) as error:
        raise ValueError(
            f"{env_var} is base64 but does not decode to text "
            f"({type(error).__name__}); {len(cleaned)} characters received. "
            f"A truncated value does this - panels have length limits. "
            f"Re-encode with: python -c \"import base64,sys; "
            f"print(base64.b64encode(open(sys.argv[1],'rb').read().strip())"
            f".decode())\" indeed-cookies.txt"
        ) from error


def _from_text(text):
    """Header string or JSON - decide by what it starts with."""
    text = text.strip()
    return _parse_json(text) if text.startswith(("{", "[")) else \
        _parse_header_string(text)


def load_cookies(env_var):
    """
    Read a session from the environment. Returns {} when nothing is set,
    which means "crawl anonymously" - the normal, unconfigured case.

    Three shapes, in order: `<VAR>_B64` (base64 of either of the others),
    then `<VAR>` as a path to a file, then `<VAR>` as the cookies themselves.
    A path exists because a session can be mounted as a secret instead of
    sitting in the process environment; base64 exists because a hosting panel
    has a text box and not a filesystem.
    """
    encoded = (os.getenv(f"{env_var}_B64") or "").strip()
    if encoded:
        # Anything wrong here raises rather than falling through to {}: an
        # empty dict means "crawl anonymously", and the log would report that
        # as if it had been the intent. Same reasoning as the path branch.
        cookies = _from_text(_decode_base64(encoded, f"{env_var}_B64"))
        if not cookies:
            raise ValueError(
                f"{env_var}_B64 decoded cleanly but held no cookies. It "
                f"should be base64 of a Cookie header - 'CTK=...; SOCK=...' - "
                f"or of a cookie exporter's JSON."
            )
        return cookies

    raw = (os.getenv(env_var) or "").strip()
    if not raw:
        return {}

    # A path, or the cookies themselves? A cookie header always contains
    # "=", and no sane path does, which separates the two without guessing.
    if "=" not in raw:
        # No "=" means this cannot be a cookie header, so it was meant as a
        # path - and the path is not there. Raising rather than falling through
        # to {}: an empty dict means "crawl anonymously", which on Indeed
        # means one page out of fifteen, and the log would only say
        # "no session cookies (anonymous)" as if that had been the intent.
        #
        # Measured the hard way on 30.07.2026: INDEED_COOKIES was set to a
        # bare filename while main.py runs the spider with
        # cwd=scraper (main.py:137), so it resolved against the
        # wrong directory. The run went out anonymous and spent eight refusals
        # before anyone read the first line of the log. Hence absolute paths,
        # and hence this.
        if not os.path.exists(raw):
            raise ValueError(
                f"{env_var} looks like a path but nothing is there: {raw!r} "
                f"(resolved from cwd {os.getcwd()!r}). Use an absolute path - "
                f"the spider does not run from the project root. Unset "
                f"{env_var} entirely if an anonymous crawl really is what you "
                f"want."
            )
        with open(raw, encoding="utf-8") as handle:
            return _from_text(handle.read())

    return _from_text(raw)


def describe(cookies):
    """
    A log line that proves a session was loaded without leaking it.

    Names only, never values, and never the whole list either: the set of
    cookie names is itself a fingerprint of the account state. Enough to
    answer "did it pick up my session" from a log, and nothing more.
    """
    if not cookies:
        return "no session cookies (anonymous)"
    return f"{len(cookies)} session cookie(s) loaded"
