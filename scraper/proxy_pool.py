"""
THE BOUGHT STATIC IP POOL
=========================

Twenty Webshare Static Residential addresses, bought 22.09.2026
(docs/proxies.md). One address per site at a time; when a site refuses the
address, that address rests FOR THAT SITE ONLY and the run moves to the next.

The owner's rules, 22.09.2026:

  * European addresses first. US addresses are reserve, and so are the five
    on carrier or business networks - used only once every European
    address is resting for that site.
  * Every address is judged per site. Indeed refusing an address says
    nothing about kariyer.net, so the rest is recorded per (site, address).
  * A refused address rests 24 hours for the site that refused it.
  * At most 3 switches per site per run, so one bad night cannot burn the
    whole pool on one site.
  * No address carries a site's whole run: after PROXY_POOL_ROTATE_AFTER
    requests (30) it hands over to the next, without resting. The owner, the
    same day: "1 IP'den 500 tane ilana istek atamayız". A full check queue
    is spread over the pool instead of waiting for one address to be
    refused. 30 sits under kariyer.net's measured wall of 34-43.
  * The pace does not change. A pool spreads the requests; it is not a
    licence to send more of them (memory: probing-a-site-costs-the-address).

WHICH SPIDERS
-------------
Opt-in, by name, in PROXY_POOL_SPIDERS - see ProxyPoolMiddleware. A spider
that carries a signed-in session is NOT meant to be listed: a proxied
browser context carries no session (playwright_middleware.py, THE PROXY), so
a session spider on the pool would quietly crawl signed out.

FILES, ALL IN proxies/ (GIT-IGNORED)
------------------------------------
    webshare.txt  the list, one ip:port:user:password per line
    meta.json     country and network per address, written by
                  `python -m tools.proxy_pool check` - one request per
                  address to ipinfo.io, no job board. An address missing
                  from it counts as reserve until it has been checked.
    state.json    per site and address: last used, requests, refusals, and
                  when a rest ends. It is what makes a 24-hour rest outlive
                  the run that caused it.

    PROXY_POOL_FILE / PROXY_POOL_META / PROXY_POOL_STATE override the paths.
    PROXY_POOL_REST_HOURS (24), PROXY_POOL_MAX_SWITCHES (3) and
    PROXY_POOL_ROTATE_AFTER (30) the rules.
"""

import json
import logging
import os
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, urlsplit

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
PROXY_DIR = ROOT / "proxies"

# Countries that count as "European" for the priority rule.
EUROPE = {
    "AT", "BE", "BG", "CH", "CY", "CZ", "DE", "DK", "EE", "ES", "FI", "FR",
    "GB", "GR", "HR", "HU", "IE", "IS", "IT", "LT", "LU", "LV", "MT", "NL",
    "NO", "PL", "PT", "RO", "SE", "SI", "SK",
}

# Networks that are carriers or business lines rather than households -
# judged by name on 22.09.2026 (docs/proxies.md), not measured. Reserve.
CARRIER_ASNS = {"AS3257", "AS5650", "AS6762", "AS50056"}

TIER_NAMES = {0: "europe", 1: "reserve (outside Europe)", 2: "reserve (carrier network)"}


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def site_of(url):
    """The key a rest is recorded under: the host, without a leading www."""
    host = urlsplit(url).hostname or ""
    return host.removeprefix("www.")


#####################################################
# ONE ADDRESS                                       #
#####################################################
@dataclass(frozen=True)
class Address:
    line: int
    ip: str
    port: str
    user: str
    password: str
    country: str = ""
    org: str = ""

    @property
    def url(self):
        user = quote(self.user, safe="")
        password = quote(self.password, safe="")
        return f"http://{user}:{password}@{self.ip}:{self.port}"

    @property
    def tier(self):
        """0 is used first. Unchecked addresses wait in reserve."""
        if self.org.split(" ", 1)[0] in CARRIER_ASNS:
            return 2
        if self.country in EUROPE:
            return 0
        return 1

    @property
    def label(self):
        """Safe to log: never the credentials."""
        return f"#{self.line} {self.ip} {self.country or '??'}"


def load_addresses(list_path, meta_path=None):
    """
    The list, numbered from 1 in file order - the numbering docs/proxies.md
    uses. Blank lines and # comments are skipped and do not take a number.
    """
    meta = {}
    if meta_path and Path(meta_path).is_file():
        meta = json.loads(Path(meta_path).read_text(encoding="utf-8"))

    addresses = []
    for raw in Path(list_path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        ip, port, user, password = line.split(":", 3)
        info = meta.get(ip, {})
        addresses.append(Address(
            line=len(addresses) + 1, ip=ip, port=port, user=user,
            password=password, country=info.get("country", ""),
            org=info.get("org", ""),
        ))
    return addresses


#####################################################
# WHAT OUTLIVES THE RUN                             #
#####################################################
class PoolState:
    """
    {"sites": {site: {ip: {last_used, rest_until, requests, refusals,
    last_refusal}}}} - timestamps as naive UTC ISO strings.
    """

    def __init__(self, path):
        self.path = Path(path)
        self.sites = {}
        if self.path.is_file():
            self.sites = json.loads(self.path.read_text(encoding="utf-8")).get("sites", {})

    def entry(self, site, ip):
        return self.sites.setdefault(site, {}).setdefault(ip, {
            "last_used": None, "rest_until": None,
            "requests": 0, "refusals": 0, "last_refusal": None,
        })

    def resting_until(self, site, ip, now):
        until = self.sites.get(site, {}).get(ip, {}).get("rest_until")
        if until and datetime.fromisoformat(until) > now:
            return datetime.fromisoformat(until)
        return None

    def last_used(self, site, ip):
        return self.sites.get(site, {}).get(ip, {}).get("last_used") or ""

    def note_request(self, site, ip, now):
        entry = self.entry(site, ip)
        entry["requests"] += 1
        entry["last_used"] = now.isoformat(timespec="seconds")

    def rest(self, site, ip, now, hours, reason):
        entry = self.entry(site, ip)
        entry["refusals"] += 1
        entry["rest_until"] = (now + timedelta(hours=hours)).isoformat(timespec="seconds")
        entry["last_refusal"] = f"{now.isoformat(timespec='seconds')} {reason}"[:200]

    def save(self):
        """Atomic: a crash mid-write must not lose every rest recorded."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".state-")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"sites": self.sites}, handle, indent=1, sort_keys=True)
        os.replace(tmp, self.path)


#####################################################
# ONE RUN'S VIEW OF THE POOL                        #
#####################################################
class ProxyPool:
    def __init__(self, addresses, state, rest_hours=24, max_switches=3,
                 rotate_after=30, clock=utcnow):
        self.addresses = addresses
        self.state = state
        self.rest_hours = rest_hours
        self.max_switches = max_switches
        self.rotate_after = rotate_after
        self.clock = clock
        self.current = {}
        self.switches = defaultdict(int)
        self.given_up = {}
        # (site, ip) -> requests this run, and the pairs that have done their
        # share. A full address is not resting: it is simply not asked again
        # by this site until the next run.
        self.served = defaultdict(int)
        self.full = set()
        # site -> responses it answered this run. See on_refusal.
        self.answered = defaultdict(int)

    @classmethod
    def from_env(cls):
        list_path = os.getenv("PROXY_POOL_FILE") or PROXY_DIR / "webshare.txt"
        if not Path(list_path).is_file():
            raise RuntimeError(
                f"PROXY_POOL_SPIDERS is set but the proxy list {list_path} does "
                f"not exist. Put the Webshare list there (see docs/proxies.md) "
                f"or unset PROXY_POOL_SPIDERS."
            )
        meta_path = os.getenv("PROXY_POOL_META") or PROXY_DIR / "meta.json"
        state_path = os.getenv("PROXY_POOL_STATE") or PROXY_DIR / "state.json"
        pool = cls(
            load_addresses(list_path, meta_path),
            PoolState(state_path),
            rest_hours=float(os.getenv("PROXY_POOL_REST_HOURS", "24")),
            max_switches=int(os.getenv("PROXY_POOL_MAX_SWITCHES", "3")),
            rotate_after=int(os.getenv("PROXY_POOL_ROTATE_AFTER", "30")),
        )
        tiers = defaultdict(int)
        for address in pool.addresses:
            tiers[TIER_NAMES[address.tier]] += 1
        logger.info(
            "Proxy pool: %s addresses - %s", len(pool.addresses),
            ", ".join(f"{count} {name}" for name, count in tiers.items()),
        )
        if not Path(meta_path).is_file():
            logger.warning(
                "No %s - every address counts as reserve until "
                "`python -m tools.proxy_pool check` has placed them.", meta_path,
            )
        return pool

    def _choose(self, site):
        now = self.clock()
        free = [
            a for a in self.addresses
            if not self.state.resting_until(site, a.ip, now) and (site, a.ip) not in self.full
        ]
        if not free:
            return None
        return min(free, key=lambda a: (a.tier, self.state.last_used(site, a.ip), a.line))

    def address_for(self, site):
        """The address this site's requests leave from, or None if none is left."""
        if site in self.given_up:
            return None
        address = self.current.get(site)
        if address is None:
            address = self._choose(site)
            if address is None:
                self._give_up(site, "every address is resting or has done its share this run")
                return None
            self.current[site] = address
            logger.info("%s leaves from %s (%s)", site, address.label, TIER_NAMES[address.tier])
        return address

    def note_request(self, site, address):
        self.state.note_request(site, address.ip, self.clock())
        self.served[(site, address.ip)] += 1
        if self.rotate_after and self.served[(site, address.ip)] >= self.rotate_after:
            # Its share is done: the next request from this site takes the
            # next address. Not a refusal - nothing rests, no switch counted.
            self.full.add((site, address.ip))
            if self.current.get(site) == address:
                self.current.pop(site)
            logger.info(
                "%s: %s has carried %s requests this run - handing over",
                site, address.label, self.served[(site, address.ip)],
            )

    def note_answer(self, site):
        """A response from this site that was not a refusal."""
        self.answered[site] += 1

    def on_refusal(self, site, ip, reason):
        """
        Rest the refused address for this site; return the address to retry
        from, or None when this site is done for the run.

        Two requests in flight on the same address can both come back
        refused. Only the first switches - the second finds the site already
        moved on and is retried from the new address.
        """
        current = self.current.get(site)
        if current is not None and current.ip != ip:
            return current
        self.state.rest(site, ip, self.clock(), self.rest_hours, reason)
        self.state.save()
        self.current.pop(site, None)
        logger.warning(
            "%s refused %s (%s) - resting it %sh for this site only",
            site, ip, reason, f"{self.rest_hours:g}",
        )
        if self.switches[site] >= self.max_switches:
            self._give_up(site, f"{self.max_switches} switches used this run")
            return None
        # TWO FRESH ADDRESSES REFUSED BEFORE ANY ANSWER - 22.09.2026. Then it
        # is not the address the site is refusing but the client, and every
        # further switch only rests another good address. Measured the hard
        # way: indeed_check, headless Chromium with no session, was refused
        # on its first request from four European addresses in a row - one
        # of which had served Indeed seven times that morning through
        # curl_cffi. Stop at the second.
        if self.answered[site] == 0 and self.switches[site] >= 1:
            self._give_up(
                site, "refused on two addresses before answering once - the "
                      "client, not the address; no further address is spent",
            )
            return None
        self.switches[site] += 1
        return self.address_for(site)

    def _give_up(self, site, why):
        if site not in self.given_up:
            self.given_up[site] = why
            logger.error("%s: no more requests this run - %s", site, why)

    def close(self):
        self.state.save()
