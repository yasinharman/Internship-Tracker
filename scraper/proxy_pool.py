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


def parse_pinned(raw):
    """
    "tr.indeed.com:13+16+19, kariyer.net:4" ->
        {"tr.indeed.com": (13, 16, 19), "kariyer.net": (4,)}

    A site may name SEVERAL lines, separated by "+", and each one needs its
    own signed-in session file - Harman, 05.10.2026: "diğer iplerden de
    indeed'e giriş yapalım, Indeed'in kendi havuzunu yaratalım". They are
    tried in the order written, so the order is a preference.

    Anything unparseable is dropped with a warning rather than guessed at: the
    wrong line here would send a signed-in session out from an address nobody
    chose.
    """
    pinned = {}
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        site, _, lines = part.rpartition(":")
        wanted = [piece.strip() for piece in lines.split("+") if piece.strip()]
        if site and wanted and all(piece.isdigit() for piece in wanted):
            # dict.fromkeys: a line written twice is one address, in the order
            # it was first named.
            pinned[site.strip()] = tuple(dict.fromkeys(int(p) for p in wanted))
        else:
            logger.warning("PROXY_POOL_PINNED: cannot read %r - ignored", part)
    return pinned


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

    def refusals(self, site, ip):
        """How many times this site has refused this address, ever."""
        return self.sites.get(site, {}).get(ip, {}).get("refusals", 0)

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
    def __init__(self, addresses, state, rest_hours=24, max_switches=6,
                 pinned_lines=None, pinned_refusals_allowed=3,
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
        # site -> the line a signed-in session leaves from. See pinned_for().
        self.pinned_lines = dict(pinned_lines or {})
        # site -> refusals IN A ROW on that pinned address. Harman, 05.10.2026:
        # "sabit adres arka arkaya red yerse dinlenmeye alalım". Scattered
        # refusals are what a working run looks like - 14 of 226 requests on
        # 04.10, and the run read 211 descriptions through them - so a single
        # one costs that page and nothing else. Three in a row is something
        # else: at the 6% rate measured that day, chance produces a run of
        # three about once every twenty runs, and a run of two about once per
        # run, which is why the threshold is not two.
        # (site, ip) -> refusals in a row on THAT pair. Per pair since
        # 05.10.2026: with several signed-in addresses, one address's run of
        # refusals says nothing about the next one's.
        self.pinned_refusals = defaultdict(int)
        self.pinned_refusals_allowed = pinned_refusals_allowed

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
            # 3 -> 6 on 23.09.2026, Harman's call after the measurement.
            # A refused address is refused on its FIRST request and a clean
            # one carries 30, so a switch costs one request, not thirty. Three
            # was enough when a site's queue was 60 postings; Indeed's was 168
            # that afternoon and the run ended 78 short with two of its three
            # switches spent on addresses the site had flagged the day before.
            max_switches=int(os.getenv("PROXY_POOL_MAX_SWITCHES", "6")),
            rotate_after=int(os.getenv("PROXY_POOL_ROTATE_AFTER", "30")),
            pinned_lines=parse_pinned(os.getenv("PROXY_POOL_PINNED", "")),
            pinned_refusals_allowed=int(
                os.getenv("PROXY_POOL_PINNED_REFUSALS", "3")),
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
        reserved = set(self.pinned_lines.get(site) or ())
        free = [
            a for a in self.addresses
            if not self.state.resting_until(site, a.ip, now)
            and (site, a.ip) not in self.full
            # The address carrying this site's session does that and nothing
            # else - see pinned_for().
            and a.line not in reserved
        ]
        if not free:
            return None
        # A SITE THAT HAS REFUSED AN ADDRESS ONCE KEEPS REFUSING IT - measured
        # 23.09.2026. Indeed challenged line 10 two hours after its refusal
        # and line 17 twenty hours after, while line 18, which it had never
        # refused, carried 30 requests in a row the same afternoon. So a rest
        # running out does not make an address clean again, and least-recently
        # used would send exactly the flagged ones first - they are the ones
        # that have not been used since they were refused. Refusals come
        # before recency, and an address the site has never refused always
        # goes ahead of one it has.
        # A CLEAN RESERVE BEATS A FLAGGED EUROPEAN ONE - measured the same
        # afternoon. The rule is Europe first, and it still is among the
        # addresses a site has never refused. But lines 6 and 7, which Indeed
        # had flagged the day before, came free and went ahead of untouched US
        # reserves purely for being European - and were refused on their first
        # request each, which spent two of the run's three switches and ended
        # it 78 postings short. Whether a site has refused an address is the
        # stronger signal; where the address lives decides between equals.
        return min(free, key=lambda a: (self.state.refusals(site, a.ip), a.tier,
                                        self.state.last_used(site, a.ip), a.line))

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

    ###################################################################
    # ONE ADDRESS THAT NEVER MOVES - 03.10.2026                       #
    ###################################################################
    def pinned_for(self, site):
        """
        The address this site's SIGNED-IN requests leave from now, or None.

        Set as PROXY_POOL_PINNED="tr.indeed.com:13+16+19": one or more lines,
        each with its own signed-in session file, tried in the order written.
        The anonymous traffic never uses any of them (see _choose) - an
        address that carries an account does that and nothing else, so the
        account is not also the source of a few hundred logged-out requests
        an hour.

        The first one that is not resting is the answer, and a pair rests only
        after refusing pinned_refusals_allowed requests IN A ROW. None means
        every signed-in address this site has is resting, which ends the
        site's run: there is no anonymous fallback for a page that needs the
        account.

        Why several, from 05.10.2026: one address carried both the crawl and
        the check and Indeed closed the door at about 130 requests, leaving
        177 of 251 postings without a description. Each address is a whole
        new allowance - and because each carries a session made on it, no
        session is ever presented from an address that did not earn it.
        """
        for line in self.pinned_lines.get(site) or ():
            address = self.pinned(line)
            if not self.state.resting_until(site, address.ip, self.clock()):
                return address
        return None

    def pinned_lines_for(self, site):
        """Every line this site may send its account from, in preference order."""
        return tuple(self.pinned_lines.get(site) or ())

    def pinned(self, line):
        """
        The address on this line, whatever the rotation would have chosen.

        For the one path that cannot be rotated: a signed-in session. Harman
        decided on 03.10.2026 that his Indeed account's crawl leaves from the
        pool rather than from his home address - and if an account's requests
        arrive from a different country every thirty requests, that is the
        pattern a platform reads as a shared password. Pinned, Indeed sees one
        location change and then a machine that stays put.

        It is still the pool, so the request is still counted and a refusal
        still rests the address. What it does NOT do is move: the rotation
        after 30 requests and the switch on refusal are both about finding
        another address, and there is no other address this session can use.
        The crawl it serves is 32 search pages, well inside one address's
        share; the 242 posting pages that need rotation are the anonymous
        ones (docs/sites/indeed.md).
        """
        for address in self.addresses:
            if address.line == line:
                return address
        raise RuntimeError(
            f"PROXY_POOL pinned address {line} is not in the list "
            f"({len(self.addresses)} addresses)"
        )

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

    def note_answer(self, site, ip=None):
        """A response from this site that was not a refusal."""
        self.answered[site] += 1
        # One page served ends that address's run of refusals: it is
        # answering, whatever it said three requests ago.
        if ip is not None:
            self.pinned_refusals[(site, ip)] = 0

    def note_pinned_refusal(self, site, ip):
        """
        One refusal on a signed-in address. Returns how many in a row on it.

        The caller rests THAT pair when this reaches pinned_refusals_allowed
        and hands over to the next one; before then only the page is dropped.
        """
        self.pinned_refusals[(site, ip)] += 1
        return self.pinned_refusals[(site, ip)]

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

    def give_up(self, site, why):
        """End a site's run from outside - see BlockDetectionMiddleware."""
        self._give_up(site, why)

    def _give_up(self, site, why):
        if site not in self.given_up:
            self.given_up[site] = why
            logger.error("%s: no more requests this run - %s", site, why)

    def close(self):
        self.state.save()
