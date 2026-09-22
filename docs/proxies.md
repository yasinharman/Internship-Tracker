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
