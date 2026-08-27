"""
WHICH BROWSER HANDSHAKES IS THIS SITE ACCEPTING TODAY?
======================================================

    python -m scraper.tls_probe                # from here, direct
    python -m scraper.tls_probe --proxy        # through IPRoyal
    python -m scraper.tls_probe --both         # and the comparison

Cloudflare scores the TLS ClientHello, so the browser curl_cffi replays for
us decides whether a request is answered or challenged - and that decision is
made by a model on their side that changes without notice. On 28.07.2026
`chrome131` returned job cards. On 29.07 the same token, same machine, same
address, returned `Security Check - Indeed.com` with `cf-mitigated:
challenge`, and every Chrome token but one did the same while Firefox and
Safari sailed through.

That day cost hours, most of them spent on the exit IP because a blocked
crawl looks identical whatever the cause. This script is the cheap version of
that afternoon: one request per candidate, a table at the end, run it before
theorising. It is also the only honest way to tell the two failures apart -

    datacenter address  -> Cloudflare challenge, HTTP 403
    untrusted address   -> 307 to secure.indeed.com/auth, HTTP 200

both of which arrive as "no postings" and mean completely different things.

Run it WHERE THE CRAWL RUNS. Today that is a laptop, so a home connection is
the thing to measure; while this was hosted it was the server, and a verdict
measured at home said nothing about what the server saw. That confusion is
exactly how `indeed_cards` ended up parked.

Nothing here touches the database or the spiders - it is a diagnostic, safe
to run at any time. It does spend a little residential bandwidth with
--proxy, one request per candidate.
"""

import argparse
import sys
import time
from urllib.parse import urlencode

from curl_cffi import requests

from .browser_session import profile_for_impersonate
from .proxy import ProxyConfig, new_session_id

# The list the spider actually falls through, kept in one place.
from .spiders.indeed_cards import IndeedCardsSpider

DEFAULT_URL = "https://tr.indeed.com/jobs?" + urlencode(
    {"q": "stajyer", "l": "İstanbul", "start": 0}
)
# Present in a real search page, absent from every interstitial.
DEFAULT_MARKER = "mosaic-provider-jobcards"


########################################
# ONE REQUEST, ONE VERDICT             #
########################################
def probe(url, token, marker, proxy_url=None, timeout=45, send_headers=True):
    """
    Fetch `url` pretending to be `token`. Returns a row for the table.

    Headers are sent the way the spider sends them - matched to the token -
    so a pass here means the spider will pass too. `--bare-headers` drops
    them to isolate the handshake from everything else.
    """
    profile = profile_for_impersonate(token)
    headers = {"Accept-Language": profile.accept_language}
    if send_headers:
        headers["User-Agent"] = profile.user_agent
        if profile.is_chromium:
            headers["sec-ch-ua"] = profile.sec_ch_ua
            headers["sec-ch-ua-mobile"] = profile.sec_ch_ua_mobile
            headers["sec-ch-ua-platform"] = profile.sec_ch_ua_platform

    proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else None

    started = time.monotonic()
    try:
        response = requests.get(
            url, impersonate=token, headers=headers, proxies=proxies,
            timeout=timeout, allow_redirects=True,
        )
    except Exception as error:
        return {
            "token": token, "status": "---", "bytes": 0,
            "verdict": f"ERROR {type(error).__name__}",
            "detail": str(error)[:70], "seconds": time.monotonic() - started,
        }

    body = response.content or b""
    text = response.text if body else ""
    final_url = str(response.url)

    if marker in text:
        verdict, detail = "DATA", f"identity={profile.name}"
    elif "/auth" in final_url or "secure." in final_url:
        verdict, detail = "SIGN-IN WALL", final_url[:70]
    elif response.headers.get("cf-mitigated"):
        verdict = "CF " + response.headers["cf-mitigated"].upper()
        detail = "cloudflare acted on this request"
    else:
        verdict, detail = "NO DATA", f"marker {marker!r} absent"

    return {
        "token": token, "status": response.status_code, "bytes": len(body),
        "verdict": verdict, "detail": detail,
        "seconds": time.monotonic() - started,
    }


def run_round(label, url, tokens, marker, proxy_url, delay, send_headers):
    print(f"\n--- {label} " + "-" * max(0, 58 - len(label)))
    print(f"{'handshake':14} {'HTTP':>4} {'bytes':>9} {'s':>5}  verdict")

    rows = []
    for index, token in enumerate(tokens):
        row = probe(url, token, marker, proxy_url, send_headers=send_headers)
        rows.append(row)
        print(
            f"{row['token']:14} {str(row['status']):>4} {row['bytes']:>9} "
            f"{row['seconds']:>5.1f}  {row['verdict']}  {row['detail']}"
        )
        if index < len(tokens) - 1:
            time.sleep(delay)
    return rows


def main():
    sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--expect", default=DEFAULT_MARKER,
                        help="string that only a real page contains")
    parser.add_argument("--tokens", default="",
                        help="comma-separated; default = the spider's list")
    parser.add_argument("--proxy", action="store_true",
                        help="go through IPRoyal instead of direct")
    parser.add_argument("--both", action="store_true",
                        help="direct and proxy, for comparison")
    parser.add_argument("--bare-headers", action="store_true",
                        help="send no User-Agent, to isolate the handshake")
    parser.add_argument("--delay", type=float, default=3.0)
    args = parser.parse_args()

    tokens = (
        [t.strip() for t in args.tokens.split(",") if t.strip()]
        or list(IndeedCardsSpider.IMPERSONATE_CANDIDATES)
    )

    print(f"target : {args.url}")
    print(f"expect : {args.expect!r} in the body")

    proxy_url = None
    if args.proxy or args.both:
        config = ProxyConfig.from_env()
        if not config.is_configured:
            print(
                "\nIPRoyal credentials missing - set IPROYAL_USERNAME and "
                "IPROYAL_PASSWORD (see .env.example). Running direct only."
            )
        else:
            session_id = new_session_id()
            proxy_url = config.build_url(session_id)
            print(f"proxy  : {config.describe(session_id)}")

    rounds = []
    if args.both or not proxy_url:
        rounds.append(("DIRECT (this machine's own address)", None))
    if proxy_url:
        rounds.append(("PROXY (IPRoyal residential)", proxy_url))

    results = {}
    for label, proxy in rounds:
        results[label] = run_round(
            label, args.url, tokens, args.expect, proxy, args.delay,
            send_headers=not args.bare_headers,
        )

    ###############################################
    # WHAT TO DO WITH WHAT WE JUST MEASURED       #
    ###############################################
    print("\n=== verdict " + "=" * 57)
    for label, rows in results.items():
        working = [r["token"] for r in rows if r["verdict"] == "DATA"]
        if working:
            print(f"{label}\n  works: {', '.join(working)}")
        else:
            reasons = sorted({r["verdict"] for r in rows})
            print(f"{label}\n  NOTHING WORKED - {', '.join(reasons)}")

    every_row = [r for rows in results.values() for r in rows]
    winners = [r["token"] for r in every_row if r["verdict"] == "DATA"]
    if winners:
        print(
            "\nPut what passed at the front of IMPERSONATE_CANDIDATES in "
            "spiders/indeed_cards.py - keep the losers in the list, they are "
            "the fallback ladder, and today's loser is next month's winner."
        )
    else:
        print(
            "\nNothing got through. If this ran on the server, try --proxy "
            "before touching the spider: a sign-in wall on every candidate is "
            "an address problem, a Cloudflare challenge on every candidate is "
            "a handshake problem."
        )
    return 0 if winners else 1


if __name__ == "__main__":
    sys.exit(main())
