# Proxies: the bought static IP pool

Measurements about the transport rather than about any one board. What a
board does with a request belongs in `docs/sites/<site>.md`; this file is
about the addresses the requests leave from.

## The pool - bought 22.09.2026

Webshare **Static Residential**: 20 addresses, 250 GB a month, $6 a month,
paid monthly. Ten of the twenty can be swapped for new addresses at any
time. That allowance is kept for an address that burns for good, rather than
spent up front.

The list lives in `proxies/webshare.txt`, one `ip:port:user:password` per
line. It is mode 600 and ignored by git (`proxies/` in `.gitignore`); every
line is a working login to a paid proxy. Addresses are referred to here by
their line number, never by credentials.

## Every address checked - 22.09.2026

One request per address to ipinfo.io. No job board was contacted.

- **20 of 20 answered.** Each exit address equals the listed one, so they
  really are static, and all 20 are distinct.
- **Countries:** US 10, GB 4, DE 2, FR 2, IT 2. **No Turkey.** Webshare's
  own pages do not list Turkey for this product. Nothing in this repository
  ever recorded a problem with a non-Turkish exit: `IPROYAL_COUNTRY=tr` was a
  default chosen as "least surprising", not a measurement.
- **Networks:** mostly consumer ISPs (RCN, Charter, Comcast, Wave, Orange,
  Free, 1&1 Versatel, Glide Student & Residential). Five sit on
  carrier or business networks: GTT (AS3257), Verizon Business (AS5650),
  Telecom Italia Sparkle (AS6762, two addresses) and Vorboss. That split was
  judged from the network names alone and is not measured. They are the
  first candidates for the ten swaps, if the boards treat them worse.
- **Latency to ipinfo:** European addresses about 0.5 s, US ones 0.7-1.3 s.

## A foreign address on every board - measured 22.09.2026

Line 17 (FR, Orange, AS5511) was used for one request per board, 11:16-11:17.
Nothing left the home address. The requests were spaced 5-20 s apart. The
browser identity was the one the spiders use: `safari184` through curl_cffi,
and for kariyer.net a windowed bundled Chromium launched exactly as
`PlaywrightMiddleware` launches it (`--disable-blink-features=AutomationControlled`,
`tr-TR`, 1280x800). The proxy was the only difference.

| # | Request | Result |
|---|---|---|
| 1 | techcareer `/jobs` | 200, 426 kB, `buildId` present |
| 2 | Indeed search page 1 (`tls_probe.probe`, `stajyer`, İstanbul) | 200, 921 kB, **job cards** - no Cloudflare challenge |
| 3 | Indeed `/viewjob?jk=`, **no session at all** | 200, 383 kB, `sanitizedJobDescription` and `isJobExpired` both present, no `cf-mitigated`, no redirect to sign-in |
| 4 | kariyer.net internship listing, windowed Chromium | 200, 1.19 MB, **39 cards**, no PerimeterX block page |

What this settles, and what it does not:

- **A European static residential address is served like a Turkish one**, on
  all three boards, at one request each. The country was not the problem it
  was assumed to be.
- **Indeed's description and liveness can be read without a session.** The
  `/viewjob` page carries both to an anonymous visitor on a pool address.
  So `indeed_check` does not need Harman's account, only the search does:
  page two and later still ask for one (`docs/sites/indeed.md`, "3. Page two
  asks for an account"). That was not re-tested here.
- **It is one address and one request per board.** It says nothing yet about
  how many requests an address takes before it is refused, and nothing about
  the carrier-network addresses. Those come from real runs, with the block
  budget in place.

## Found on the way: the browser does not use the proxy

`scraper/playwright_middleware.py` has no proxy support.
`ResidentialProxyMiddleware` only reaches the requests Scrapy and curl_cffi
make. Every kariyer.net request (`NEEDS_A_WINDOW`) and every Indeed request
that goes through the browser therefore still leaves from the home address,
whatever `PROXY_MODE` says. The probe above passed the proxy to
`chromium.launch()` itself. The pool needs the same in the middleware: one
browser context per address, which Playwright supports.

**Fixed 22.09.2026.** `PlaywrightMiddleware` now opens a proxied request's
page in a context bound to that proxy (`_page_for`):

- a fresh-visitor request gets its throwaway context on the proxy;
- any other proxied request gets one shared context per proxy address.

A proxied context carries **no session**: no storage state and no seeded
cookies. The signed-in session stays in the run's own context, on the
address it was made from. `tests/test_playwright_proxy.py` holds both rules.

Checked end to end the same day, through the real middleware stack, with a
throwaway spider sending three requests to ipinfo.io:

| Request | Exit address |
|---|---|
| no proxy | the home address (TR) |
| proxy, fresh-visitor context | line 17's address (FR) |
| proxy, shared context | line 17's address (FR) |

Chromium on Linux applies a per-context proxy without the browser itself
being launched with one.

## The pool in code - 22.09.2026

`scraper/proxy_pool.py`, wired in by `ProxyPoolMiddleware` (priority 727)
and `BlockDetectionMiddleware`. The rules are the owner's, set the same day:

- **European addresses first.** Addresses outside Europe are reserve, and so
  are the five on carrier or business networks, whatever their country.
  They are used only once every European address is resting for that site.
- **Judged per site.** A refusal rests that address for the site that
  refused it, and nowhere else.
- **A rest lasts 24 hours**, recorded in `proxies/state.json` so it outlives
  the run that caused it.
- **At most 3 switches per site per run.** The fourth refusal ends that
  site's run, so one bad night cannot burn the pool.
- **Among the addresses that are free**, a site takes the one it has used
  least recently. Over several nights the load spreads across all seven
  European addresses.
- **No address carries a site's whole run** (added the same afternoon).
  After `PROXY_POOL_ROTATE_AFTER` requests (30) for one site in one run, an
  address hands over to the next. Nothing rests and no switch is counted. The
  owner's words: "1 IP'den 500 tane ilana istek atamayız". One run can then
  send a site 7 x 30 = 210 requests from European addresses, or 600 with the
  reserve. A bigger first-run queue finishes on the next run. 30 sits under
  kariyer.net's measured wall of 34-43.
- **Two fresh refusals end the site's run** (added 22.09 evening). If a site
  refuses two addresses before it has answered once in the run, the pool
  stops there instead of spending the third and fourth switch. The site is
  refusing the client, not the address; see "`indeed_check` through the
  pool" below. Once a site has answered, refusals count against the address
  again and the three switches apply.
- **The pace is unchanged.** A refused pooled request is retried from the
  next address with the same TLS identity, so the address is the only thing
  that changed. It does not spend the site's block budget; the pool's cap
  replaces it.

The tiers, as `python -m tools.proxy_pool check` placed them on 22.09
(countries and networks from ipinfo.io, written to `proxies/meta.json`):

| Tier | Count | Lines |
|---|---|---|
| Europe (used first) | 7 | 4, 5, 10 (DE, FR), 6, 7, 18 (GB), 17 (FR) |
| Reserve: outside Europe | 8 | 1, 2, 3, 9, 11, 13, 16, 19 (US) |
| Reserve: carrier network | 5 | 8 (GTT), 12 (Verizon Business), 14 and 20 (Telecom Italia Sparkle), 15 (Vorboss) |

**Opt-in, by spider name.** `PROXY_POOL_SPIDERS` lists the spiders that use
the pool; empty means the pool is off. A spider that carries a signed-in
session should not be listed, because a proxied browser context carries no
session.

`python -m tools.proxy_pool status` prints the tiers, and for each site the
requests, refusals and any rest in force per address.

## The first runs through the pool - measured 22.09.2026

Today's filters, pool on for the four kariyer.net and techcareer spiders,
nothing else changed. Logs: `backups/pool-smoke-kariyernet-20260922.log`
and `backups/pool-smoke-techcareer-20260922.log`.

| Step | Address | Result |
|---|---|---|
| `kariyernet_cards` 11:56 | line 4 (DE, 1&1 Versatel) | 4 listing requests, all 200, 49 postings |
| `kariyernet_check` 12:27, first request | line 5 (FR, Free Pro SAS) | **403**: PerimeterX press-and-hold page |
| the pool | 5 rests for kariyer.net until 23.09 09:27 UTC | the same posting retried from line 6 |
| `kariyernet_check`, the rest | line 6 (GB, Glide) | 25 posting pages, all 200, 25 descriptions, no further refusal |
| `techcareer_api` 12:37 | line 4 (DE) | 11 requests, all 200, 4 postings |
| `techcareer_check` 12:39 | line 5 (FR) | 3 requests, all 200, 2 descriptions |

What it shows:

- **The switch works on a live refusal.** It took one of the three switches
  the run allows.
- **A rest is per site.** Line 5, resting for kariyer.net, served techcareer
  its check eleven minutes later.
- **The crawl and the check left from different addresses** (4, then 5 and
  6). That is what made the 30-minute `SITE_COOLDOWN_S` wait unnecessary for
  pooled spiders. The owner dropped it the same day; `main.py` skips it when
  both spiders of a site are pooled.
- **Line 5 was refused on its very first request.** It sits on "Free Pro",
  a business line. One request is not a verdict, but it joins the carrier
  addresses as a candidate for a swap.

## `indeed_check` through the pool: four addresses refused - measured 22.09.2026

The owner, the same afternoon: "indeed check in zaten havuzda olması
gerekiyor 1 ip den 500 tane ilana istek atamayız". A dry run,
`OPENINGS_MAX_PER_SITE=2 scrapy crawl indeed_check -a dry_run=1`, with
`indeed_check` in `PROXY_POOL_SPIDERS`.

| Time (UTC) | Address | Request | Result |
|---|---|---|---|
| 11:09:16 | line 4 (DE) | warm-up `https://tr.indeed.com/`, headless Chromium, no session | **403** |
| 11:09:17 | line 5 (FR) | the same | **403** |
| 11:09:34 | line 6 (GB) | the same | **403** |
| 11:10:02 | line 7 (GB) | the same | **403**, and the pool gave up (3 switches) |

No posting was checked and nothing was written. Lines 4-7 rest for
tr.indeed.com until 23.09 about 11:10 UTC. Lines 10, 17 and 18 are still free
for Indeed.

**It was the client, not the addresses.** Line 4 had served Indeed seven
times that morning (`docs/sites/indeed.md`, "All of Istanbul's internships in
three searches"). Line 17 had served `/viewjob` to an anonymous visitor
("A foreign address on every board", above). Both used **curl_cffi with
`safari184`**, straight to `/jobs` or `/viewjob`. `indeed_check` differs in
two ways:
- the **transport**: headless bundled Chromium, launched as
  `PlaywrightMiddleware` does;
- the **first request**: a warm-up on the home page.

Two variables moved together, so this run cannot say which one Indeed
refused. That breaks the rule the measurements in this repo keep: a control
differs by one thing. The headless browser is the likelier cause.
`indeed_cards` notes it was never measured past headless ("UNMEASURED PAST
HEADLESS"), and on 28.08 Indeed challenged the browser's own fingerprint
(`docs/sites/indeed.md`).

**Changed because of it:**
- The pool now stops a site that refuses two fresh addresses before
  answering once (see the rules above). This run would have cost two
  addresses, not four.
- `indeed_check` stays **out** of `PROXY_POOL_SPIDERS` until a one-variable
  measurement shows how it gets served from a pool address.

**The one-variable measurement, the same day, 11:42 UTC.** The owner
approved one request. `INDEED_CHECK_VIA_CURL=1` makes `indeed_check` the
morning's client: curl_cffi with `safari184`, no warm-up, no session, no
Referer. The run was a dry run of one posting from line 17 only, with
`PROXY_POOL_MAX_SWITCHES=0`, so at worst one address would rest.
Log: `backups/pool-indeed-check-curl-20260922.log`.

| Request | Result |
|---|---|
| `/viewjob?jk=` (posting id=2092) | **200**, 393 kB, no challenge; `sanitizedJobDescription` read |

- **Served.** So the four refusals were the headless browser, the warm-up,
  or both - not the addresses.
- **But no verdict.** The page gave neither a clean `"isJobExpired":true`
  nor a clean `false` to the regexes. The morning probe had only checked
  that the word was on the page. The body was not kept. Since then an
  inconclusive Indeed page logs how the flag appears, so the next request
  says whether it was "both" or "a different spelling".

**The same request again, 13:06 UTC** (owner approved; same address, client
and posting; log `backups/pool-indeed-check-curl-2-20260922.log`): **403,
`cf-mitigated=challenge`**. Line 17 rests for tr.indeed.com until 23.09 13:06
UTC. Lines 10 and 18 are the European addresses still free for Indeed.

Line 17's day on Indeed, all curl_cffi `safari184`, anonymous:

| Time | Request | Result |
|---|---|---|
| morning | search page 1, `/viewjob` | 200, 200 |
| 11:42 UTC | `/viewjob` (id=2092) | 200 |
| 13:06 UTC | `/viewjob` (id=2092) | **challenge** |

- **One request does not judge a client.** Nothing we control changed
  between the last two, and the answer did. Whether a client works from
  the pool is a rate out of many requests, not a single pass or fail.
- **The number the pool is built on is still unmeasured:** how many
  `/viewjob` requests one address carries before Indeed challenges it. On
  line 17 the fourth Indeed request of the day was challenged. Line 4 had
  carried seven search pages that morning without one.

