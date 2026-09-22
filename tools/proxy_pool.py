"""
LOOK AFTER THE BOUGHT IP POOL
=============================

    python -m tools.proxy_pool check     one request per address to ipinfo.io,
                                         writes proxies/meta.json
    python -m tools.proxy_pool status    which tier each address is in, and per
                                         site: requests, refusals, rests

`check` contacts no job board. It is what places each address in its tier
(scraper/proxy_pool.py): the pool reads country and network from meta.json,
and an address missing from it waits in reserve. Run it once after buying,
and again after swapping an address in the Webshare panel.

Credentials are never printed.
"""

import json
import sys
import time

import httpx

from scraper.proxy_pool import (
    PROXY_DIR, TIER_NAMES, PoolState, load_addresses, utcnow,
)

LIST = PROXY_DIR / "webshare.txt"
META = PROXY_DIR / "meta.json"
STATE = PROXY_DIR / "state.json"


def check():
    addresses = load_addresses(LIST)
    meta = {}
    for address in addresses:
        try:
            with httpx.Client(proxy=address.url, timeout=20) as client:
                data = client.get("https://ipinfo.io/json").json()
        except Exception as error:
            print(f"#{address.line:>2} {address.ip:<16} FAILED {type(error).__name__}")
            continue
        exit_ip = data.get("ip")
        meta[address.ip] = {
            "country": data.get("country", ""),
            "city": data.get("city", ""),
            "org": data.get("org", ""),
            "checked": utcnow().isoformat(timespec="seconds"),
        }
        same = "" if exit_ip == address.ip else f"  EXIT IS {exit_ip}"
        print(f"#{address.line:>2} {address.ip:<16} {data.get('country', '?'):<3} "
              f"{data.get('org', '?')}{same}")
        time.sleep(0.5)

    META.write_text(json.dumps(meta, indent=1, sort_keys=True), encoding="utf-8")
    print(f"\n{len(meta)} of {len(addresses)} written to {META}")


def status():
    addresses = load_addresses(LIST, META)
    state = PoolState(STATE)
    now = utcnow()

    for tier, name in TIER_NAMES.items():
        members = [a.label for a in addresses if a.tier == tier]
        print(f"{name:<26} {len(members):>2}  {', '.join(members)}")

    for site, entries in sorted(state.sites.items()):
        print(f"\n{site}")
        for address in addresses:
            entry = entries.get(address.ip)
            if not entry:
                continue
            until = state.resting_until(site, address.ip, now)
            rest = f"RESTING until {until:%d.%m %H:%M} UTC" if until else ""
            print(f"  {address.label:<24} requests {entry['requests']:>4}  "
                  f"refusals {entry['refusals']:>2}  last used {entry['last_used'] or '-'}  {rest}")


if __name__ == "__main__":
    commands = {"check": check, "status": status}
    if len(sys.argv) != 2 or sys.argv[1] not in commands:
        sys.exit("usage: python -m tools.proxy_pool check|status")
    commands[sys.argv[1]]()
