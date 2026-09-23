"""
ONE COOKIE JAR PER SITE PER ADDRESS
===================================

Every request the pool sends today arrives as a first-time visitor: no
cookies, no history, nothing the site handed us last time. A real visitor
comes back carrying what the site gave them - including, on a Cloudflare
site, the clearance cookie that says "this browser has already passed the
check". We throw that away after every request and pay for the check again,
which is the shape of what Indeed did to us on 22-23.09.2026: the first
contact from an address was served, later ones were challenged.

Harman, 23.09.2026: "çerezleri kullanarak tarayıcı kimliği oluşturma işini
her site ve IP adresi için yapalım".

WHAT THIS IS, AND WHAT IT IS NOT
--------------------------------
It is a jar per (site, address). The address that visited kariyer.net keeps
kariyer.net's cookies and sends them the next time it visits kariyer.net,
from that same address. Nothing else changes: the browser identity stays the
single measured one (scraper/browser_session.py), the pace stays the same,
and no account is involved anywhere.

It is NOT a different identity per address. A run that presents seven
addresses as seven different browsers is claiming to be seven people, and
that is the thing that was declined on 21.09.2026. One browser, one profile,
each address carrying its own history - which is what we actually are.

A jar belongs to ONE address on purpose. A cookie set for one IP and replayed
from another is the one pattern a site reads as a shared session, and it
would make things worse rather than better.

WHERE THEY LIVE
---------------
`proxies/jars/<site>__<ip>.json`, in Playwright's own storage_state shape
(cookies plus localStorage). proxies/ is git-ignored, and the directory is
created 0700: a clearance cookie is not a password, but it is a key to a
session and nothing else on this machine needs to read it.
"""

import json
import logging
import os
import re
import time
from pathlib import Path

logger = logging.getLogger(__name__)

JAR_DIR = Path(os.getenv("COOKIE_JAR_DIR") or Path(__file__).resolve().parent.parent / "proxies" / "jars")

# How old a jar may be before it is thrown away. A session cookie that has sat
# unused for days is not what a returning visitor carries, and a stale
# clearance cookie is refused anyway - the point is to arrive as a visitor the
# site remembers, not to hoard what it handed us a week ago.
MAX_AGE_DAYS = float(os.getenv("COOKIE_JAR_MAX_AGE_DAYS", "7"))


def _safe(text):
    """
    A file name that cannot escape the directory it belongs in.

    Site names and addresses both come from our own config rather than from a
    site, so this is a seatbelt: a separator becomes an underscore and a run
    of dots collapses, which leaves nothing that reads as a parent directory.
    """
    return re.sub(r"\.{2,}", ".", re.sub(r"[^A-Za-z0-9._-]", "_", text or ""))


def jar_path(site, ip):
    return JAR_DIR / f"{_safe(site)}__{_safe(ip)}.json"


def load(site, ip, max_age_days=None):
    """
    The stored state for this pair, as a dict, or None.

    None means "this address has never been to this site", which is the
    signal to warm up before asking for anything.
    """
    path = jar_path(site, ip)
    if not path.is_file():
        return None

    age_days = (time.time() - path.stat().st_mtime) / 86400
    limit = MAX_AGE_DAYS if max_age_days is None else max_age_days
    if limit and age_days > limit:
        logger.info("%s from %s: jar is %.1f days old - starting fresh",
                    site, ip, age_days)
        forget(site, ip)
        return None

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        logger.warning("%s from %s: unreadable jar (%s) - starting fresh",
                       site, ip, error)
        forget(site, ip)
        return None


def save(site, ip, state):
    """
    Write the state back. Returns the path, or None when there was nothing
    worth keeping - a state with no cookies at all is a visit that left no
    trace, and writing it would only make `load` claim the address has been
    here before.
    """
    if not state or not state.get("cookies"):
        return None

    JAR_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = jar_path(site, ip)
    # Written whole and moved into place: a run killed mid-write would
    # otherwise leave a truncated jar that the next run has to throw away.
    temporary = path.with_suffix(".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(state, handle)
    os.replace(temporary, path)
    logger.debug("%s from %s: %s cookie(s) kept", site, ip, len(state["cookies"]))
    return path


def forget(site, ip):
    """Throw the jar away - a refusal that survives a retry, or a stale file."""
    try:
        jar_path(site, ip).unlink()
        return True
    except FileNotFoundError:
        return False


def cookie_header(state, url_host):
    """
    The Cookie header for a host, out of a stored state.

    For the transports that are not the browser. Note what it cannot do: a
    Cloudflare clearance cookie is issued to the browser that passed the
    check and is refused when it arrives under another TLS fingerprint or
    User-Agent, so replaying one from curl buys nothing. It is here for the
    ordinary cookies - a site's own session id, its locale, its consent flag.
    """
    if not state:
        return ""
    wanted = []
    for cookie in state.get("cookies", []):
        domain = (cookie.get("domain") or "").lstrip(".")
        if domain and (url_host == domain or url_host.endswith("." + domain)):
            wanted.append(f"{cookie.get('name')}={cookie.get('value')}")
    return "; ".join(wanted)
