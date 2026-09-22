# Indeed

**Status:** running, un-parked 30.07.2026.

> **HOW THIS ACTUALLY RUNS, 21.08.2026.** `python main.py` is started by hand
> on a local machine, writing to the remote Postgres. There is no server-side
> crawler and **no proxy**: `.env` carries `PROXY_MODE=off` and no `PROXY_URL`
> or `IPROYAL_*` at all, so every request goes direct from a home connection.
> That connection is residential, which is the property the measurements below
> actually depended on - the proxy was only ever one way of getting one.
>
> Everything below was measured on 28-30.07.2026 through a static residential
> proxy on the server, a setup that no longer exists. The conclusions still
> hold and the mechanisms they explain are all still in the code; the
> addresses and the machine are not. **Re-measure on the machine you actually
> run from** - the one lesson from those three days that survives its own
> environment.

**Status 30.07.2026.** Back in `main.py`'s SPIDERS list. The proving run
happened on the server, through the static residential proxy, with the
exported session: **61 requests, 61 HTTP 200**, no challenges, no handshake
escalations, 335 postings, and all four searches into the page ceiling with
results still arriving.

Three things had to be true at once, and the whole three-day detour came from
each being mistaken for the others: an accepted **handshake**, a residential
**address**, and a **session carried under the browser that made it**. The
last one is new and is the subtlest - see below.

## What 28.07 got wrong

The reading was "our address is refused": direct requests 403, every
residential exit walled, therefore the exit IP. Three of the four conclusions
below say otherwise, and the first one dismantles the original evidence -
**the home connection got the same 403 on 29.07**, having worked the day
before. It was never only about the address.

## 1. The TLS fingerprint had gone stale

`IMPERSONATE` was pinned to `chrome131`, verified 200 on 28.07. Measured
29.07, two rounds each, one address, identical headers:

| Handshake | Result | Handshake | Result |
|---|---|---|---|
| chrome110 | 403 challenge | **chrome124** | **200, 1.19 MB** |
| chrome131 | 403 challenge | **firefox135** | **200, 1.19 MB** |
| chrome136 / 142 / 145 / 146 | 403 challenge | **firefox147** | **200, 1.19 MB** |
| safari260 | 1 of 2 challenged | **safari184** | **200, 1.19 MB** |

Every Chrome token but one is challenged, and it is not a newest-is-best
gradient. Chrome is what nearly all impersonating traffic claims to be, so
that is where the scrutiny goes.

Confirmed independent of the address: through a clean static residential IP,
`chrome131` was still challenged while `firefox147` returned data. Neither
variable rescues the other.

`IMPERSONATE_CANDIDATES` is now a fallback ladder rather than one pinned
value, and `BlockDetectionMiddleware` climbs it. **Re-measure with `python -m
scraper.tls_probe`** rather than reasoning about it - that script
exists because this will go stale again.

It went stale again the next afternoon, which is how fast this moves. Measured
30.07 at 16:28 through the same static residential proxy:

| Handshake | Result | Handshake | Result |
|---|---|---|---|
| firefox147 | 403 challenge | **safari184** | **200, 1.14 MB** |
| firefox135 | 403 challenge | **chrome124** | **200, 1.14 MB** |

Exactly inverted from the table above, and the tokens that carried that
morning's 61/61 run were the ones being refused. The ladder is reordered
`safari184, chrome124, firefox147, firefox135`. Treat the order as weather.

## 2. The Referer was the actual trigger

The spider sent `Referer: https://tr.indeed.com/` with `Sec-Fetch-Site:
same-origin` on a request carrying no Indeed cookies at all - a browser
claiming a journey without the evidence of it. Same IP, same token, minutes
apart:

| Request | Result |
|---|---|
| bare headers | 200, data |
| the spider's headers | **403 challenge** |
| the spider's headers, no Referer | 200, data |
| the spider's headers, after loading the home page first | 200, data |

Fixed by making the claim true: `warmup_url` now points at the home page, so
the run collects real cookies before searching, and pagination refers to the
page it actually came from. **This was invisible from a home connection** -
every combination passed there. It only decided anything from a proxy.

## 3. Page two asks for an account - SETTLED 30.07

`branding=page-two-signin` is named after what it is, and an account genuinely
opens it. The same url that walled anonymously at 13:18 returned job cards
with a session at 13:44, from the same address - so the "is it the account or
is it the address's standing" question is closed in favour of the account.
All four searches then ran to the `MAX_PAGES = 15` ceiling with results still
arriving, which means the ceiling is ours, not Indeed's.

Anonymous runs still stop at page one (`ANONYMOUS_MAX_PAGES`), and that is
still the right ceiling: a control run at 16:30 with no cookies got page one
data and a page two wall.

**Seen once and not reproducible:** at 13:18 `?start=0` itself redirected to
`branding=page-two-signin`, i.e. the wall reached page one. Three hours later
anonymous page one was answering normally again. Do not build on either
reading - if a run reports zero postings anonymously, this is the thing to
re-measure rather than the proxy.

## 4. Refusals cost credit, and we were spending it

Chasing page two anonymously did not just waste requests. The retries carry
`priority+1`, so they overtook searches that had not started, and the burst
of refusals spent enough of the address's standing that their first pages -
which would have worked - were challenged too. Two searches lost to it.

Both a home connection and the static residential IP did the same thing:
serve 1.19 MB pages, get refused in a burst, then challenge everything for
several minutes, then recover on their own. So `DOMAIN_BLOCK_BUDGET` (8) now
stops a run that is being refused instead of grinding through every search
times every identity - sixteen refusals in under a minute is an efficient way
to teach a site to distrust an address, and it damages the *next* run too.

## 5. The session outlives the cookies it was afraid of

The account was created through Google with no "remember me" box, so
`PPID`, `__Secure-PassportAuthProxy-BearerToken` and `-OauthExpires` all fill
up about 55 minutes after export. The browser renews them with
`RefreshToken`; the spider cannot. That is what kept the schedule blocked -
a 03:00 run with a dead session would return zero postings silently.

Measured 30.07 at 16:30 with the file exported at 13:43, nearly three hours
old:

| Cookies sent | Page 1 | Page 2 |
|---|---|---|
| all 32, as exported | 200 data | **200 data** |
| the 6 durable ones only | 200 data | **200 data** |
| none (control) | 200 data | sign-in wall |

So the oauth trio is not what opens page two - `CTK, JSESSIONID, PPID, RF,
SOCK, SHOE` do it on their own, and those are the long-lived ones. Adding a
password to the account to get a "remember me" checkbox is not needed.

**Still unmeasured past three hours.** The first scheduled 03:00 run is the
next data point; if it comes back with nothing, re-export the cookies before
suspecting anything else.

## 6. The session and the handshake are a PAIR - the last mistake

The server had the proxy and the session and still lost a run: 8 of 11
requests refused, block budget spent. The reflex reading was "the ladder has
gone stale again". It had not. Same address, ten minutes apart:

| Run | Handshake | Result |
|---|---|---|
| `tls_probe --both`, no cookies | safari184, chrome124 | 200, data |
| `tls_probe --both`, no cookies | firefox147, firefox135 | 403 challenge |
| spider, session attached | safari184 | 0 of 2 answered |
| spider, session attached | chrome124 | 0 of 4 answered |
| spider, session attached | firefox147 | 3 of 3 answered |
| spider, `INDEED_IMPERSONATE=firefox147` | firefox147 | **61 of 61 answered** |

The session was exported from Firefox. Presented under Safari's or Chrome's
handshake it is a session being used by something other than what created it
- and that is cheaper to spot than any fingerprint, which is what
`session_cookies.py` had been saying all along in prose.

So the probe and the spider measure different things, and the probe's verdict
only applies to an anonymous crawl. `_prefer_the_session_s_browser` puts the
session's browser at the head of the ladder whenever cookies are loaded,
leaving the measured order alone when they are not.
`INDEED_SESSION_BROWSER` changes it if the session is ever made elsewhere.

**But do not carry the pairing further than the measurement goes.** Two hours
after the server run, the same Firefox session was carried from the HOME
machine through the same proxy: `safari184` answered 200 with data (twice,
an hour apart) and `firefox147` was refused. That is the server's result
inverted, with the exit address, the session and the hour all held constant.
The remaining difference is the client itself - curl_cffi on Windows/Python
3.14 here against Linux/Python 3.12 there.

So the honest statement is narrower than "a session must wear its own
browser": the accepted combination is (client × handshake × session), it is
not stable across machines, and the ladder exists precisely because none of
it stays decided. Leading with the session's browser is what measured right
on the server, which is where it ran at the time. Re-measure wherever you
actually run it - the same lesson that cost 28.07, and again on 30.07. As of
21.08.2026 that is a local machine, so the "server" in this paragraph is no
longer the place to measure.

## Why it stayed parked so long

Not because it failed - because the server did not have what the measurements
were made on. The static address and the session lived in a local `.env`
while Coolify had the rotating pool that never worked.

That was resolved by setting both on the server, and the spider was un-parked.
**Since 21.08.2026 the arrangement is simpler and the proxy is out of it
entirely:** the crawl runs by hand from a local machine whose own connection
is residential, with `INDEED_COOKIES_B64` for the session and
`PROXY_MODE=off`. `PROXY_URL` is not set anywhere.

`INDEED_COOKIES` must be an **absolute** path: `main.py:137` runs the spider
with `cwd=scraper`, so a bare filename resolves in the wrong
directory. That mistake cost a run and eight refusals on 30.07 before anyone
read the first log line; `load_cookies` now raises instead of quietly
crawling anonymously.

On the panel, use **`INDEED_COOKIES_B64`** instead - base64 of the same
header. The raw header is ~5 KB with double quotes inside its values, which
is why a file was used locally in the first place, and a file on a hosting
panel means a mount plus a copy plus a second place the account lives. Base64
has nothing in it that any environment-variable box will mangle, and it wins
over `INDEED_COOKIES` when both are set.

The first attempt on the server failed anyway - `binascii.Error: Only base64
data is allowed` - so the decoder now cleans what a clipboard and a text box
do to a value before judging it: whitespace, real newlines, `\n` written out
literally, surrounding quotes, url-safe alphabet, missing padding. Anything
left that is not base64 is named in the error rather than described as
invalid.

**A truncated value is the dangerous one**, because it decodes and parses and
yields a plausible pile of cookies that just happens not to include the
sign-in. `IndeedCardsSpider.SIGNED_IN_COOKIES` refuses a session without
`SOCK` and `SHOE` for that reason - measured, those two are what carry it. A
cut after them costs only the oauth cookies, which do not matter, so that
session is allowed to run.

`python main.py --spider indeed_cards` runs it by hand meanwhile.

**What parking costs us:** techcareer.net belongs to kariyer.net, so the two
remaining spiders are one company's data and the two-independent-routes rule
above does not hold across sites.

**Worth knowing:** the sign-in wall was invisible at first. Status 200, no
anti-bot fingerprint, and Indeed's search page is HTML by design so
`expect_json` never applied - the crawl reported "3/3 spiders succeeded" with
Indeed contributing nothing. `BlockDetectionMiddleware.LOGIN_URL_SIGNATURES`
now catches it, reading the requested url from `meta["redirect_urls"]` because
RedirectMiddleware has already rewritten `request.url` by then. Cloudflare's
own `cf-mitigated` header is read directly now too.

Everything below describes the spider as built.

## Still challenged, and two bugs were hiding behind it - 27.08.2026

The first full run after the database was wiped got **0 postings in 18.6
minutes**. Three responses out of twelve requests: the warm-up 200, two
searches 403 with `cf-mitigated=challenge`, and nine
`playwright/navigation_timeout`. That reads as "the site has locked us out",
and it was two separate faults on top of a real one.

**The nine timeouts were not Indeed.** They were the reused-page wedge found
on LinkedIn the same day (see `linkedin.md`, "CURED 27.08.2026"): the
middleware handed one `page` object to every navigation for the whole crawl,
and a renderer that stops answering protocol calls blocks them forever. With a
fresh page per navigation the timeouts disappeared entirely and every
navigation completed in 0.1s.

**The searches were running backwards.** Scrapy's default queue is LIFO, so
the dict order that the note above SEARCHES carefully argues for was inverted
in practice. On a challenged domain that is not a tidiness problem:

    warm-up                     200
    yari-zamanli  (last listed)  200  -> 15 postings, 6 kept
    the other eight              403  cf-mitigated=challenge

The first request after the warm-up goes through on the warm-up's credit and
Cloudflare challenges what follows, so the order decided the ONE search that
ran - and it was running the least valuable one. `_search_priority()` fixes it.

**What that leaves.** With both fixed, an unrestricted run:

| | before | after |
|---|---|---|
| postings | 0 | **25** |
| wall clock | 18.6 min | **70s** |
| 200 / 403 | 1 / 2 | 4 / 8 |
| navigation timeouts | 9 | **0** |

and the three searches that got through were `yazilim-stajyer` (9),
`bilgisayar-muhendisligi-stajyer` (7) and `software-intern` (9) - the three the
ordering note wanted protected.

**The challenge itself is unchanged and is still the real constraint.**
Cloudflare starts refusing after three or four searches and the block budget
ends the run. `PROXY_MODE=off`, so every request leaves from a home
connection; the fix for this is the residential proxy this file has always
said it needs, not more code. What changed is that the crawl now takes real
value out of the window it gets, instead of spending it on the wrong terms and
then burning sixteen minutes on wedged navigations.

## IT WAS THE BROWSER'S OWN FINGERPRINT - measured 28.08.2026

Everything below this section is a record of chasing the wrong thing. The
challenge was never about the address, the cadence, the session or the count.
It was that the browser announced itself, and the question that found it was a
good one: *if I browse this by hand I am not blocked - why can't we do exactly
what I do?*

Asked the page who it thought we were, with the middleware's own settings:

    navigator.userAgent   Macintosh; Intel Mac OS X ... Safari/605.1.15
    navigator.platform    Linux x86_64
    navigator.webdriver   true
    WebGL renderer        SwiftShader
    navigator.plugins     0

A user agent claiming macOS Safari, on a headless Linux Chromium, with the
automation flag on. Five contradictions inside the first fifty milliseconds of
any fingerprinting script.

**Where the UA came from, and why it was wrong here.** `browser_session.py`
pairs each impersonation token with the User-Agent that matches its TLS
handshake, and that table is right - for curl_cffi, which really does replay
the handshake it is told to. Playwright brings its own engine and its own
handshake, so the label was being borrowed without the thing it labels. The
middleware set it on the context AND `document_headers()` sent it as a header,
so both layers lied and the JS environment told the truth.

**The other half is nastier.** `tools/save_session.py` has always launched
with `--disable-blink-features=AutomationControlled`, and the middleware never
did. The browser that CREATED the session was harder to spot than the one that
replayed it.

### What changed

    the UA override                removed - Chromium reports itself
    User-Agent, sec-ch-ua*         no longer sent as extra headers
    --disable-blink-features=...   added; navigator.webdriver is false
    headless shell -> full Chromium (channel)   navigator.plugins 0 -> 5
    "HeadlessChrome/151" -> "Chrome/151"        one word, read off the browser

The last one deserves a note: the UA is taken from the browser itself and
edited by a single word, so version, platform and engine stay true. We are not
claiming to be a different browser, only declining to announce the mode.

### The result

| | before | after |
|---|---|---|
| responses | 12 | **124** |
| 200 | 4 | **121** |
| 403 `cf-mitigated=challenge` | 8 | **0** |
| 429 (plain rate limit) | 0 | 3 |
| items | 30 | **737** |
| unique postings | ~25 | **138** |
| routes that ran | 3 of 9 | **8 of 9** |
| block budget | spent | never touched |

The 403 challenge is gone entirely. What is left is three 429s - honest rate
limiting, a different mechanism and a much softer one - and five searches that
reached `MAX_PAGES = 15` with results still arriving, a ceiling this spider
had never got near.

**So the earlier conclusions in this file are superseded**, and they are kept
because the reasoning was sound and only the premise was missing: the count
really did stop at three, the rate really did not matter, and the address
really was fine. All three were downstream of a browser that had already
identified itself before the first search loaded.

The one tell still standing is the WebGL renderer: SwiftShader is the software
rasteriser, and no headless browser has a GPU. Fixing it needs
`PLAYWRIGHT_HEADLESS=0` and a visible window. It has not been needed.

## The block is a COUNT, not a rate - measured 28.08.2026

The obvious lever was cadence: four requests in thirty seconds looked like a
rate trigger, so `DOWNLOAD_DELAY` went 6 -> 20 and the same crawl was run
again. It is not a rate trigger.

    27.08, delay 6, 20 min after the previous run
      16:00:01  warm-up                  200
      16:00:07  yazilim stajyer          200
      16:00:15  bilgisayar muh. stajyer  200
      16:00:24  software intern          200
      16:00:31  developer intern         403   <- 4th request, 30s in

    28.08, delay 20, TWENTY HOURS after the previous run
      12:15:13  warm-up                  200
      12:15:30  yazilim stajyer          200
      12:15:50  bilgisayar muh. stajyer  200
      12:16:18  software intern          200
      12:16:37  developer intern         403   <- 4th request, 84s in

Same place, both times. Spreading the requests over nearly three times as long
moved nothing, and neither did a rested address: `blocks/detected: 8`,
`200: 4`, `403: 8` in both runs.

So Indeed serves three search pages per session and challenges the fourth.
Three things are ruled out by this:

  * **Rate.** 30s and 84s produce the same result.
  * **Accumulated address reputation.** Twenty hours of rest changed nothing,
    and a burned address would not answer the warm-up either - this one always
    does, on every run, including the ones where every search is refused.
  * **A residential proxy as the fix.** The crawl already leaves from a
    residential connection. What a rotating pool would buy is a NEW session
    per address, which is the thing that looks like it matters - not the
    address type.

**What is left to test, in order.** The session is the obvious next suspect
and the cheapest to check, because it has been announcing itself since
05.08.2026 on every single run:

    WARNING: Session has no SOCK/SHOE (native login) but does have
    __Secure-PassportAuthProxy-RefreshToken/JSESSIONID (Google/OAuth login) -
    proceeding as an unmeasured experiment.

Re-capture it with a native email+password login rather than Google
(`python -m tools.save_session indeed`) and see whether the count moves off
three. After that, whether a fresh browser CONTEXT resets the count is worth
one run: the middleware now opens a fresh page per navigation but keeps the
context, so the cookie jar is continuous across all nine searches.

**The delay stays at 20 anyway.** It buys nothing against the block, and that
is written down here so nobody re-derives it - but nothing in this project is
on a schedule, an hour-long run is acceptable, and a gentler cadence is the
cheaper side to err on. `throttle.py` now prints a line every ten seconds
while it waits, so the quiet stretches are legible rather than alarming.

## Out of TIME, not out of welcome - measured 15.09.2026

One unmodified run, `python main.py --spider indeed_cards`, started 13:03 from
the home connection. Log: `backups/indeed-baseline-20260915.log`. Nothing else
touched the site that day.

**Indeed did not refuse it.** Crawl and checker together: 130 HTTP 200, four
429s (retried and answered), no 403, no sign-in wall past page one, block
budget untouched. The 28.08 fingerprint fix still holds, and so does the
Google-login session from 05.08 - six weeks old and still opening page two
despite the SOCK/SHOE warning it prints.

**Both halves were killed by main.py's clock instead.**

| | ran for | got through | killed with |
|---|---|---|---|
| `indeed_cards` | 1800s (SPIDER_TIMEOUT) | 69 pages, 215 unique postings | the four broad searches on page 2-3, still finding 13-15 new a page |
| `indeed_check` | 1200s (CHECK_TIMEOUT) | 61 of 214 postings | 23 verdicts and descriptions in memory, never written |

**Corrected 21.09.2026:** the log holds 87 search pages for `indeed_cards`,
not 69, and 4 429s: the 75 field-search pages the table below counts, and
3 for each broad search.

The checker's loss is worse than it looks: the description only arrives
through it (see the 09.09 section), so **189 postings went unclassified** and
the database held a real description for 22 of 215 Indeed rows.

### Where the crawl's time went: past the last page

`start=` beyond the last result is not an empty page. Indeed serves the last
page again - `developer-intern` pages 2-15 were page 1 verbatim. New postings
per page, per search:

| Search | New postings per page |
|---|---|
| yazilim-stajyer | 11 11 12 7 12 12 11 15 6 **0 0 0 0 0 0** |
| bilgisayar-muhendisligi-stajyer | 13 10 11 6 7 13 13 12 7 12 10 12 7 **0 0** |
| IT-intern | 15 13 4 **0 x12** |
| software-intern | 11 6 **0 x13** |
| developer-intern | 5 **0 x14** |
| stajyer / intern / part-time / yari-zamanli | 15 13 / 15 15 / 9 5 4 / 8 10 - cut off |

47 of 75 field-search pages brought nothing, about twenty minutes. **No page
with a new posting ever followed a page without one** - not after two, not
after one. Not quite "the last page again" every time, though: page 10 of
yazilim-stajyer had nothing new without being a copy of page 9.

`BaseApiSpider` stops on a repeated page already, and never fired here:
`record_key()` knows `id`, `url` and the like but not `jobkey`, so it keyed on
the whole record, which differs between two requests for the same posting.
The log said "15 new of 15" for page 2 of developer-intern.

**Changed:** `record_key` returns `jobkey`, and a search ends after
`REPEATED_PAGES_BEFORE_STOP = 2` pages with nothing new. Two rather than one
buys insurance against the single reshuffled page for one request per search.
It judges all 15 records, not just the ones `is_wanted` keeps, so it can only
stop later than the counts above, never earlier. **Unmeasured on the broad
searches**, which never reached their end - that is the next run's question.

### Do the field searches overlap?

Postings found only by that search, of 215 (filter-kept, pre-classifier):

| Search | Found | Only here |
|---|---|---|
| bilgisayar-muhendisligi-stajyer | 133 | 48 |
| yazilim-stajyer | 97 | 13 |
| yari-zamanli | 18 | 10 |
| IT-intern | 32 | 9 |
| part-time | 18 | 8 |
| intern | 30 | 6 (2 pages) |
| stajyer | 28 | 3 (2 pages) |
| software-intern | 17 | 1 |
| developer-intern | 5 | **0** |

yazilim and bilgisayar share 82, and each still finds its own. Only
developer-intern found nothing new, on one page - dropping it saves one
request now the repeats stop, so it stays until another run agrees.

### What the clock does now

- `SPIDER_TIMEOUTS` gives `indeed_cards` 5400s and `indeed_check` 7200s, with
  the sums next to them in `main.py`.
- Every spider is also handed `CLOSESPIDER_TIMEOUT`, `CLOSE_GRACE_S` (300s)
  before the kill. Scrapy then closes the spider properly: the checker
  flushes, the stats file is written, and the summary says "sure siniri
  doldu" instead of "Calismadi". Checked against a local spider that blocks
  the reactor for 3s per request, as the throttle does: CLOSESPIDER_TIMEOUT=10
  closed it at 12.2s with `closed()` run. The kill stays as the backstop.

### The "no SOCK/SHOE" warning was about cookies nobody sent

Every run since 05.08 has printed *Session has no SOCK/SHOE (native login)
... proceeding as an unmeasured experiment*, and the 28.08 section above named
the session its next suspect because of it. The warning read
`INDEED_COOKIES_B64` - a 10-cookie export. The browser never sends that:
`PlaywrightMiddleware._seed_cookies` skips it whenever `INDEED_STORAGE_STATE`
is set, and it has been since 05.08. The file the browser does load holds 32
Indeed cookies, **SOCK and SHOE among them, expiring 01.02.2027**.

Read off that file on 15.09, without a request:

| Cookie | Expires |
|---|---|
| `__cf_bm`, `__cflb`, `SURF`, `google_n` | 05-12.08.2026 - gone, and Cloudflare's are reissued every run |
| `rememberMe` | **03.11.2026** - the nearest date; unmeasured whether it matters |
| SOCK, SHOE, PPID, CTK, the PassportAuthProxy family, Google's | 01.02.2027 |

The file is never written back, so every run starts from the 05.08 jar and
Indeed has accepted that for six weeks. `_require_a_whole_session` now checks
the storage-state file when one is set and names which source it checked.

**Still coupled:** the spider decides whether it is signed in -
`ANONYMOUS_MAX_PAGES` - from `INDEED_COOKIES_B64` being non-empty. Unset that
and the crawl stops at page one with a perfectly good session in the file.

## Refused on the detail pages, 145 requests in - measured 16.09.2026

The same command, `python main.py --spider indeed_cards`, with the 15.09 fixes
in and an empty Indeed board. The 215 Indeed rows were deleted first: the
whole table was backed up to `backups/job_posts-20260916-101145.csv`, and in
the same transaction 17 LinkedIn rows that pointed at Indeed rows as their
original were unlinked. Started 10:12, about twenty hours after the 15.09 run.
Log: `backups/indeed-fullrun-20260916.log`.

| Step | Ran | Result |
|---|---|---|
| `indeed_cards` | 10:12-10:42, 1846s, `finished` | 93 requests: 90 x 200, 3 x 429 retried and answered. **314 unique postings** (215 on 15.09), 1302 records seen |
| dedupe | 68s | 22 newly marked. 17 of the new Indeed rows are now the copies behind those unlinked LinkedIn rows, which are older; 1 is behind a kariyer.net row |
| notify | 24s | 309 rows, no watched company |
| `indeed_check` | 10:44-11:03, 1174s, `finished` | 296 to check: **51 open with a description**, 0 closed, then eight 403s and the block budget - **245 never asked** |
| classify | 17s | 51 rows: it 9, general_program 1, other 41 |

The board now holds 314 Indeed rows, 296 of them visible, and **245 of the
visible ones still have no description and no category**. Because dedupe
keeps the older row, the 17 jobs Indeed shares with LinkedIn now get their
description from `linkedin_check`, not from this checker.

### The clock was not what stopped it

Both halves were given their new limits (`CLOSESPIDER_TIMEOUT` 5100 and 6900
in the log). Neither came near them: the crawl ended on its own at 31 minutes,
and the checker stopped at 20 minutes because Cloudflare refused it.

### The repeated-page stop, on its first run

New postings per page. The pages with nothing new are the ones the stop
counts, and they log no count of their own:

| Search | Pages | New per page | Ended by |
|---|---|---|---|
| software-intern | 4 | 15 9 **0 0** | two pages with nothing new |
| developer-intern | 4 | 15 6 **0 0** | two pages with nothing new |
| it-intern | 5 | 15 15 11 **0 0** | two pages with nothing new |
| intern | 6 | 15 13 14 10 **0 0** | two pages with nothing new |
| yazilim-stajyer | 10 | 15 15 10 15 14 15 15 12 **0 0** | two pages with nothing new |
| bilgisayar-muhendisligi-stajyer | 15 | 15 14 11 15 14 15 15 14 15 15 15 15 8 **0 0** | two pages with nothing new, on page 15 |
| stajyer | 15 | 12-15 on every page | **MAX_PAGES, page 15 still full** |
| yari-zamanli | 15 | 14-15 on every page | **MAX_PAGES, page 15 still full** |
| part-time | 15 | 13-15 on every page | **MAX_PAGES, page 15 still full** |

The stop did what 15.09 said it would: 89 pages instead of the 135 that nine
searches to MAX_PAGES would cost. This also answers the question 15.09 left
open about the broad searches. **They do not run dry within 15 pages**, and
nothing yet says how deep they go. They took 45 of the 89 pages.

Postings found, and found only by that search, of 314:

| Search | Found | Only here |
|---|---|---|
| stajyer | 192 | 48 |
| bilgisayar-muhendisligi-stajyer | 133 | 6 |
| yazilim-stajyer | 90 | 1 |
| yari-zamanli | 65 | 37 |
| intern | 45 | 12 |
| part-time | 44 | 14 |
| it-intern | 29 | 1 |
| software-intern | 15 | 0 |
| developer-intern | 9 | 0 |

part-time kept 44 postings out of 225 records over 15 pages, and its page 15
kept none. Whether the broad searches' postings are worth their pages is a
question for classify. Its 51 verdicts are too few to split by search, but 41
of them were `other`: the hidden ones are house-help and babysitting ads.

### The refusal

- **What:** from 11:01:33, `/viewjob` pages answered 403 with
  `cf-mitigated=challenge`. Eight arrived in 2m15s, and nothing in between
  was answered. `DOMAIN_BLOCK_BUDGET` (8) then stopped the
  checker cleanly and dropped the other 243 requests.
- **Not the account:** no sign-in wall on any page, and no redirect to a
  login or lock page. It was Cloudflare's challenge.
- **When:** before the first 403, the address had sent 145 requests to
  tr.indeed.com in 49.5 minutes (142 x 200, 3 x 429). The 15.09 run ended at
  134 (130 x 200, 4 x 429) in about 50 minutes, killed by the clock. So both
  days stopped at about the same place, one by the clock and one by
  Cloudflare. **One run each does not make that a count**, and the two differ
  in more than one thing: this one had the rest of the night before it and a
  longer crawl in front of the checker.
- **Corrected 21.09.2026:** the 15.09 log holds 153 responses (149 x 200,
  4 x 429), not 134. So 15.09 went past 145 without a refusal. See "Checked
  against the listing-only crawl".
- **Not a refusal:** one detail page (`jk=cb132657b5eece7c`, 10:53) timed out
  in `page.goto` and was logged as an error.

### What is next

- **The 245 rows:** they wait for the checker, and unchecked rows go first, so
  the next checker run starts on exactly them.
- **The question the refusal raises:** is the limit the day's total, or
  something about detail pages? A checker run on a rested address without
  the crawl in front of it differs from today's in that one respect.
  `OPENINGS_MAX_PER_SITE` can cap it if a smaller first step is wanted.
- **The broad searches:** 45 pages and still full. Raising MAX_PAGES would
  spend more of the same budget the checker needs.

### Changed the same day: a posting page is opened when there is something to learn

The refused rows were never at risk. A probe that gets no answer does not
stamp `checked_at`, and unchecked rows go first, so the next run starts on
them. That is half of what kariyer.net does. The other half is "a posting page
is worth a request only when there is something to learn from it"
(`kariyernet_cards`, 10.09.2026), and this checker did not have it. It opened
every open posting every night. Once the backlog is gone that is about 300
pages a night, against a wall measured once, at the 51st - so the wall would
be hit every night, and every night would add eight refusals to the address.

`indeed_check.probe_query` now decides:

| Row | Opened? |
|---|---|
| no description yet (`NULL`, `N/A`, `""` - what classify waits on) | yes, **first** |
| description, and in a search result in the last `SEEN_RECENTLY_H` (12) hours | **no** |
| description, not seen lately, or never | yes, after the above |

- **The skip:** it rests on the rule `openings.py` is built on. A posting in
  a search result is open, and `last_seen_at` is that evidence. The checker
  still opens the posting that has dropped out of the searches, which is the
  one that may have closed.
- **The cost:** a posting that closes while Indeed still lists it in search
  is caught only once it drops out.
- **The order:** a row without a description goes first even ahead of a row
  never checked. Among equals, the older row goes first, so rows a refusal
  left behind go ahead of that night's new cards.

The same query was run read-only against the database on 16.09, after the
run, with no request sent. The queue is **exactly the 245**. 10 described rows are skipped,
and 41 more never enter it, because classify marked them `other` and the
checker only looks at rows the board can show. Tests:
`tests/test_indeed_check_queue.py`.

Once the backlog is gone, a night should cost the crawl plus the new postings
plus the ones that dropped out of the searches. That is unmeasured.

Also from 16.09: **the dashboard no longer shows a posting that has not been
classified** (`api/queries.py`, `CLASSIFIED`). For Indeed that means a posting
appears the night its description arrives, not the night it was found.

## Are the broad searches worth their pages? - measured 16.09.2026

The four broad searches - `stajyer`, `intern`, `part-time`, `yari-zamanli` -
took 51 of the 89 pages of the 16.09 run. Their results looked mostly
irrelevant, so this measures them. No request was sent.

**Method.**
- **Which search found which posting:** the 16.09 log has a `Scraped from
  <search page>` line with the item under it, 727 of them. They map every one
  of the 314 postings to the searches that found it, and they reproduce the
  run's own discovery report exactly.
- **What each posting is:** classify's verdict where there is one (51 rows),
  and for a duplicate, the verdict on the row it points at. The 65 rows below
  that are still waiting were **read by title**, against the classifier's own
  rules. That is a weaker signal than classify with a description, and it is
  marked as such.
- **What counts:** only the postings a search finds **alone**, because those
  are the ones removing it would lose.

| Search | Pages | Found | Only here | Of those, relevant | Of those, noise |
|---|---|---|---|---|---|
| yari-zamanli | 15, ceiling | 65 | 37 | **0** | 37. **33 are enuygunbakıcı** babysitting, cleaning and house-help ads; the rest a physiotherapist, a steward, a host and a warehouse job |
| part-time | 15, ceiling | 44 | 14 | **2, both software**, both waiting (read by title): *QA Tester - Part Time* (Splash Software), *Part Time Telecommunications Engineer (SW Product)* (P.I. Works) | 12: waiter, barista, vet, social media, front desk, a sales role at Mango that LinkedIn also has |
| stajyer | 15, ceiling | 192 | 48 | **6**: Baykar *Web Yazılım Geliştirme*; three more Baykar tracks classify called `it` (weapon systems, engine analysis, flight sciences - engineering, arguably); Baykar *Veri ve Analiz* (waiting, read as `it`); Vodafone *Genel Stajyer-Engelli* (`general_program`) | 42: 28 more Baykar tracks in other fields, and 14 others - vet, architect, teacher, make-up, accounting and the like |
| intern | 6 | 45 | 12 | **3** `general_program` by title: pladis *Intern*, Marriott *University Intern-MEA* and *Intern - JW Marriott* | 9. 5 of them are also on LinkedIn; the rest are HR, allocator, logistics and sales |

A further 30 postings were found by two or more broad searches and by no field
search. All of them are noise except two whose titles name no field: *stajyer*
(HOSFINDER) and Apple's *Uzman: Dönemsel, Yarı Zamanlı*. 21 of the 30 were
found by `part-time` and `yari-zamanli` together and by nothing else. Remove
`yari-zamanli` and `part-time` still finds them. Remove both and they are
gone, Apple's included.

**The cost is not only pages.** On Indeed a description arrives only through
the checker, so every noise posting costs a `/viewjob` request before classify
can call it `other`.
- **The backlog:** of the 245 rows waiting after the run, 90 were found only
  by the broad searches, and 14 only by `yari-zamanli`.
- **The address:** those requests come out of the same budget that refused
  the checker at its 51st request.

**What it says, per search:**
- **yari-zamanli:** nothing relevant, and a third of its results come from
  one household-help site.
- **part-time:** mostly noise, but it is the only route to the two
  part-time software jobs, because every field search asks for an
  internship.
- **stajyer:** mostly noise, and mostly Baykar. It is the only route to
  Baykar's software and data tracks and to Vodafone's general programme.
- **intern:** cheap, at 6 pages, and brings three company-wide programmes.

**The caveats:** this is one run, and 65 of the verdicts come from reading
titles. The field searches cannot be compared yet: of their 173 postings, only
8 are classified.

**Decided the same day (Harman): `yari-zamanli` is dropped.**
- **The saving:** 15 pages a crawl, and nothing relevant is lost.
- **Kept:** `part-time`, `stajyer` and `intern`.
- **To watch on the next run:**
  - Does `part-time` stay the sole finder of software postings?
  - Do the 21 postings it shared with `yari-zamanli` still arrive?
  - Does the crawl end sooner?

**Its rows were deleted the same day (Harman, 16.09.2026 15:34).** The 37
postings only `yari-zamanli` had found were removed from the database, so the
checker does not spend a `/viewjob` request on any of them. With the search
gone, nothing will bring them back. They were 33 enuygunbakıcı ads plus a
physiotherapist, a steward, a host and a warehouse job. 23 were already
classified `other`; 14 were still in the checker's queue.
- **Backup first:** `backups/job_posts-20260916-153408.csv`.
- **Found:** by mapping the `Scraped from` lines of
  `backups/indeed-fullrun-20260916.log` to urls. Nothing pointed at the 37 as
  a duplicate.
- **Not deleted:** the 28 postings `yari-zamanli` shared with other searches
  (21 of them with `part-time`). `part-time` and `stajyer` would insert them
  again as new rows on the next crawl, and the checker would visit them
  anyway.
- **The queue after the deletion:** 248 active Indeed rows without a
  description.

**`software-intern` and `developer-intern` dropped the same day (Harman).**
Each search was checked on its own and the two were checked together,
because together they could lose a posting that each alone would not.

| Run | software-intern: found / only here | developer-intern: found / only here | Lost if both go |
|---|---|---|---|
| 15.09, broad searches cut off at page 2-3 | 17 / 1 | 5 / 0 | 1: *Programme Support & Communications Intern*, United Nations |
| 16.09, full run | 15 / 0 | 9 / 0 | **0** |

- **Who else finds their postings:** on 16.09, `intern` found 13 of
  software-intern's 15 and all 9 of developer-intern's. `it-intern` found 10
  and 8.
- **The saving:** 8 pages a crawl on 16.09's numbers, on top of
  `yari-zamanli`'s 15.
- **No rows deleted:** every posting the pair found is also found by a search
  that stays.
- **Six searches now:** `yazilim-stajyer`, `bilgisayar-muhendisligi-stajyer`,
  `it-intern`, `stajyer`, `intern`, `part-time`.

**What it changes:**
- **Little for `intern`.** Of the 16 postings the pair found on 16.09, the
  five remaining searches still find 15, mostly through `it-intern`. The one
  left to `intern` alone is a marketing internship. So the order stays as it
  is.
- **Still two runs of evidence.** The 30.07 run found every term to be the
  sole finder of something. Watch the next discovery report for a software
  posting that no search finds any more.

**`intern` was checked too, and stays (Harman).** With the six searches it is
the only finder of more than before. None of its finds is a software posting.

| Run | Only `intern` finds | Of those, company-wide programmes (by title) |
|---|---|---|
| 15.09 | 7 | 2: pladis *Intern*, Marriott *University Intern-MEA* |
| 16.09 | 13 | 3: pladis *Intern*, Marriott *University Intern-MEA* and *Intern - JW Marriott* |

- **The rest on 16.09:** TikTok x3, Roche legal, AstraZeneca corporate
  affairs, Cummins logistics and sales, PVH, pladis HR, Kenvue marketing.
- **LinkedIn's deletion:** five of those were duplicates of LinkedIn rows, and
  LinkedIn's rows are now deleted.
- **Why keep it:**
  - A company-wide programme is exactly what `general_program` exists
    for (pladis *Intern* is the classifier's own UPS example).
  - Its precision is better than `stajyer`'s: 3 in 13, against 6 in 48.
  - It costs 6 pages, against 15.

## Checked against the listing-only crawl - 21.09.2026

The owner decided on 21.09.2026 what a crawl does: it requests listing pages,
yields postings from the cards, and nothing else. The description comes
later, from `indeed_check`, a separate step with its own budget. The spider
was checked against that from the code and the two full-run logs. **No
request was sent.**

**No posting page is requested during the crawl, and none was before.**
- **In the code:** `start_requests` sends the warm-up, `_after_warmup` sends
  page one of each search, and `parse_search` yields items plus at most one
  request, the next page of the same search. Nothing else in
  `indeed_cards.py` builds a request. The `/viewjob?jk=` url on an item is
  stored, not requested.
- **In the logs:** every `Crawled` line of both crawls is the home page or
  `/jobs`. The first `/viewjob` is the checker's, after its own warm-up.

| Crawl | `/` | `/jobs` | 429, retried | `/viewjob` |
|---|---|---|---|---|
| 15.09, `backups/indeed-baseline-20260915.log` | 1 | 87 | 4 | 0 |
| 16.09, `backups/indeed-fullrun-20260916.log` | 1 | 89 | 3 | 0 |

### Changed: a card's description is always `N/A`

`_item_from_record` stored the card's `snippet` and fell back to `N/A`. It
now stores `N/A`.
- **The snippet had stopped arriving.** Every card item in every kept log
  says `'job_description': 'N/A'`: 26 on 27.08, then 173, 470 and 737 on
  28.08, 754 on 15.09 and 727 on 16.09. In the database backups, 7 Indeed
  rows ever held a snippet, all created between 30.07 and 05.08.
- **It would now do harm.** `pipelines.py` writes any incoming description
  that is not `N/A` over the stored one, so a snippet on a re-crawl would
  replace the full text the checker paid a request for. And
  `indeed_check.lacks_description()` would read a snippet row as described:
  the checker would skip it while the searches list it, and classify would
  sort it on one teaser sentence.
- **So the database was already right.** The 249 rows holding `N/A` on
  20.09 are what the code now writes on purpose.

Tests: `tests/test_indeed_cards_listing_only.py`.

### What one crawl requests

The searches and limits are unchanged: six searches, `MAX_PAGES` 15,
`ANONYMOUS_MAX_PAGES` 1, `REPEATED_PAGES_BEFORE_STOP` 2, `DOWNLOAD_DELAY` 20.

    GET https://tr.indeed.com/                                   the warm-up, once
    GET https://tr.indeed.com/jobs?q=<term>&l=%C4%B0stanbul&start=<(page-1)*10>

| Search, in the order it runs | `q=` | Pages on 16.09 |
|---|---|---|
| yazilim-stajyer | `yaz%C4%B1l%C4%B1m+stajyer` | 10 |
| bilgisayar-muhendisligi-stajyer | `bilgisayar+m%C3%BChendisli%C4%9Fi+stajyer` | 15 |
| it-intern | `IT+intern` | 5 |
| stajyer | `stajyer` | 15 |
| intern | `intern` | 6 |
| part-time | `part+time` | 15 |

`start` runs 0, 10, ... 140 at most. Page one of a search is referred by the
home page, and every later page by the page before it.

| Run | Requests |
|---|---|
| anonymous | 1 + 6 x 1 = **7** |
| signed in, expected: 16.09's pages for these six, plus the usual three or four 429s | 1 + 66 + ~3 = **about 70** |
| signed in, ceiling: every search to `MAX_PAGES`, plus the refusals `DOMAIN_BLOCK_BUDGET` (8) allows before it ends the run, a 429 counting as one | 1 + 6 x 15 + 8 = **99** |

- **Each search stops on its own.** The repeated-page stop keeps a seen-set
  per search, so dropping three searches did not change how deep the other
  six go.
- **Not counted above:** a navigation that times out is retried
  (`RETRY_TIMES` 3) and does not count against the block budget. Neither
  crawl had one.
- **The unit:** each navigation is a real browser page load, so Indeed also
  sees the page's own sub-resources. They were there on 15.09 and 16.09 too,
  so the comparison below uses the same unit on both sides.

### Against the refusal of 16.09

- **The crawl alone has never been refused.** It sent 92 requests on 15.09
  and 93 on 16.09. With six searches it should send about 70, and the
  ceiling of 99 is only six past what 16.09 sent.
- **145 is one night, not a wall.** On 16.09 the night's 146th request was
  refused, on a `/viewjob` page. On 15.09 the address sent **153** (149 x 200, 4 x
  429) and was never refused; the clock stopped its checker. The
  "134 (130 x 200, 4 x 429)" in the 16.09 section is a miscount. The 15.09
  log holds 92 crawl responses (the warm-up, 87 search pages and 4 429s,
  not "69 pages") and 61 checker responses (a warm-up and 60 `/viewjob`).
- **"A count, not a rate" no longer stands.** The 28.08 section measured
  three search pages per session. The fingerprint fix overturned it the same
  day, and after that fix the cadence did matter: delay 10 brought back 8
  challenges in 32 responses.
- **The margin:** about 70 is under half of 145. The ceiling of 99 leaves 46.

**The searches do not need to change for the crawl to fit.**

**The rest is outside this spider.** `main.py` still runs `indeed_check`
right after `indeed_cards`: it is in `CHECKER_FOR`, `run_post_crawl` runs it
unless `--skip-classify` is given, and Indeed has no `SITE_COOLDOWN_S`
entry. So a crawl night is still about 70 listing requests followed by the
checker's queue. That is the order that was refused on 16.09. Moving the
check off the crawl night is a change to `main.py`, and it was not made here.

## All of Istanbul's internships in three searches - measured 22.09.2026

The board is for every student from 22.09.2026, and the crawl's only filters
are "internship" and "Istanbul". This measurement asks what that costs on
Indeed. Page ONE of each search, anonymous, through one pool address (line
4, DE; docs/proxies.md), 20 s apart. Seven requests in all, because one was
repeated after a parsing slip. All returned 200 and none was refused.

The page carries the size of the whole result set as `"totalJobCount":N`, in
its config rather than in the jobcards blob:

| Search (l=İstanbul) | totalJobCount | Cards on page 1 | Titles that read as internship |
|---|---|---|---|
| stajyer | **339** | 15 | 15 |
| staj | **283** | 15 | 15 |
| intern | **76** | 15 | 14 |
| stajyer, `sort=date` | 339 | 15 | 11 - newest first, the first five "Az önce yayınlandı" |
| stajyer, `sort=date&fromage=1` | **5** | 5 | 4 |
| stajyer, `sort=date&fromage=3` | **9** | 9 | 7 |

- **"staj" is not "stajyer" to Indeed.** Their first pages shared 7 of 15
  postings. Only "staj" found Baykar's "2027 Bahar Dönemi Staj | ..." family.
- **The software terms were never more than a depth workaround.** "stajyer"
  was cut at `MAX_PAGES = 15`, 225 cards of its 339. That is why "bilgisayar
  mühendisliği stajyer" had 21 sole finds on 21.09.
- **Depth.** `start` steps by 10 while a page shows about 15 cards, so a
  search needs 1 + ceil((total - 15) / 10) pages: stajyer 34, staj 28,
  intern 8. That is about 70 listing pages to see every Istanbul internship.
  The software-leaning crawl of 21.09 spent 68 on a partial view.
- **New postings are few.** "stajyer" gains about 3-5 a day in Istanbul
  (fromage=1: 5, fromage=3: 9). A "last 3 days" query sorted by date fits on
  one page. That is the cheap way to keep up once the table is full; it is
  not built yet.

**Changed the same day (`indeed_cards`):**
- The searches are "stajyer", "staj" and "intern". The three software terms
  and "part time" are gone.
- The title filter reads internship only.
- Each search reads `totalJobCount` from page 1 and stops at the page that
  reaches it (`_last_page`). `MAX_PAGES` went from 15 to 40, a circuit
  breaker now.

## A full run on an empty table: 343 requests, one refusal - measured 21.09.2026

The table had been emptied first (`backups/job_posts-20260921-120942.csv`),
so the checker's queue was every posting the crawl found. The run had no
check cap (`OPENINGS_MAX_PER_SITE=0`, the owner's call) and no proxy
(`PROXY_MODE=off`). The address had rested since the 16.09 refusal. The full
log is `backups/fullrun-20260921.log`.

| Step | When | Requests | Result |
|---|---|---|---|
| `indeed_cards` | 12:17-12:39 | 68: 67 x 200, 1 x 429 | 645 cards over six searches, 274 postings. The 429 at 12:30 was Cloudflare's challenge (`cf-mitigated=challenge`) on `stajyer` page 5; its retry passed. |
| (kariyer.net's check ran in between) | 12:47-13:00 | - | - |
| `indeed_check` | 13:00-14:28 | 275, all 200 | 274 descriptions, 268 verdicts, 2 closed. About 19 s per posting. |

- **343 requests to Indeed in about two hours, and one refusal.** On 16.09,
  the order refused at 145 was the same: listing requests, then the checker.
  So 145 is not a fixed wall. That matches what "Refused on the detail
  pages" already says about 15.09.
- **This is one run, on a rested address.** It does not say what a second
  night in a row looks like.
- **The checker had a 21-minute gap after the crawl**, because kariyer.net's
  check ran in between. Indeed has no `SITE_COOLDOWN_S` of its own.

## The description is on the DETAIL page, and the checker already fetches it - 09.09.2026

"The first investigation > Description" turned down fetching `/viewjob?jk=`
per posting for descriptions, at roughly 75 extra requests a day. **That
refusal still stands for the crawl.** What changed is that `indeed_check`
fetches that url anyway, for every posting the board can show, to read
`isJobExpired` - its own header calls it "the same endpoint for a different
question". So the description costs nothing there.

Measured on one posting: the `/viewjob` body is ~290 kB and
**`sanitizedJobDescription` appears in it exactly once**, holding the full
text.

| Key | Occurrences in one body |
|---|---|
| `sanitizedJobDescription` | **1** |
| `jobDescriptionText` | 1 |
| `jobDescription` | 4 |
| `descriptionHtml` | 0 |

Pulled with a regex rather than by parsing, for the same reason `EXPIRED` is -
the blob is nested JSON with escaped quotes inside string values. The capture
is a JSON string literal and `json.loads` does the unescaping, because the
value arrives full of `\u003Cbr>`.

**The asymmetry with the crawl is the point.** The SEARCH record carries only
`snippet`, an excerpt - which is why every stored Indeed row reads `N/A` or a
fragment. The full text was never on the page the crawl looks at, so this is
not a selector the crawl was missing.

## THERE IS NO COMPANY LOGO IN THE CARD RECORDS - measured 09.09.2026

Looked for one because the board draws each posting as a card built around the
employer's mark, and the other three sites all supply one. Indeed does not.

The record is the object `extract_provider_json()` already parses, so this is
the spider's own input rather than an approximation of it. Over the 15 records
on one search page:

| Probe | Result |
|---|---|
| keys matching `logo\|image\|brand\|icon\|photo\|avatar` | **none of ~110** |
| `companyBrandingAttributes` | **the key does not exist** |
| `"logo"` anywhere in the serialised records | 0 |
| `"image"` anywhere | 0 |
| `.png` / `.jpg` anywhere | 0 / 0 |
| `featuredCompanyAttributes` | `{}` |
| `enhancedAttributesModel` | `{}` |
| every http url in the blob | an `/applystart?jk=...` tracking link |

So it is not a matter of finding the right key. The employer identity Indeed
ships on a card is `company`, `companyIdEncrypted`, `companyRating` and
`companyReviewCount` - a name, an opaque id and review numbers, no artwork.

**What this costs and what it would cost to change.** Indeed rows keep the
company's initials on the board, which is the same thing a reader sees for an
employer that has no logo anywhere. Getting artwork would mean the detail page
(`/viewjob?jk=`), and this file already refuses that for the description at
roughly 75 extra requests a day against the site that blocks hardest - the
reasoning is in `indeed_cards.py` under WHAT THIS SPIDER DOES NOT COLLECT, and
a logo is a weaker reason than a description was.

Re-checking is cheap if Indeed ever adds one: dump `sorted(records[0].keys())`
in `parse_search` for one page and compare against the list above.

## Search terms - measured 30.07.2026

Five field terms were added on top of the four broad ones, because depth was
not the constraint: pages 10-15 of `intern` returned the same six postings
repeatedly. First page of each new term, measured before adding them:

| Term | Records | Passed the filter |
|---|---|---|
| `yazılım stajyer` | 9 | 8 |
| `bilgisayar mühendisliği stajyer` | 3 | 3 |
| `software intern` | 15 | 8 |
| `developer intern` | 13 | 3 |
| `IT intern` | 15 | 14 |

46 unique postings across the five, 8 of them found by more than one term -
and they surface what the broad terms do not: *Yazılım Stajyeri*, *Long-Term
Full Stack Developer Intern*, *Working Student (Software Development
Engineer)*, *Cybersecurity Pre-Sales Stajyeri*. The run that used only broad
terms found 157 postings of which the classifier kept 14 as IT.

The small record counts also bound the cost: a narrow term runs out of
results long before `MAX_PAGES`, so nine searches do not mean nine times the
requests. Field terms are queued first - `DOMAIN_BLOCK_BUDGET` ends a run
partway through, and whatever is last is what gets lost.

---

## The first investigation, 27.07.2026

How the site was read before any of the above was measured. Kept because the
page-shape findings still hold; the conclusions about blocking were overtaken
by the section above.

At the time this was written Indeed was the only genuinely independent source:
techcareer.net belongs to kariyer.net, and jooble and LinkedIn were both out
of scope. LinkedIn has since been un-parked (26.08.2026, see linkedin.md), so
there are two.

### No endpoint, but the data is plain JSON in the page

The search page is server-rendered, so there is no XHR to intercept. The data
is not scattered through the DOM either - it sits in a script as JSON:

```
window.mosaic.providerData["mosaic-provider-jobcards"]
  -> metaData.mosaicProviderJobCardsModel.results     (15 records per page)
```

Extracted by scanning braces, not by regex: the blob is ~120 kB of nested JSON
with escaped quotes and braces inside string values.

**A plain request from a residential IP returns HTTP 200 with the full page** -
no challenge, despite Cloudflare fronting the site. Worth noting: the old
spider pays ScrapeOps for JS rendering that may not be needed.

This is the property the whole arrangement rests on, and as of 21.08.2026 it
comes from the home connection the crawl is run on rather than from a proxy.
`ResidentialProxyMiddleware` is still in the code and still works, but it is
inert while `PROXY_MODE=off`. If the crawl ever moves to a datacenter address
- a VPS, CI, anywhere - it will be refused on every handshake, and turning the
proxy back on is the fix.

Pagination is `start=0,10,20,...`; `l=` accepts `İstanbul`, `ıstanbul` and
`istanbul` interchangeably - all three return identical results, verified.

### The job-type filter is unusable

Across 120 real Istanbul internship postings, `taxonomyAttributes.job-types`
said:

| Value | Count |
|---|---|
| Staj | 54 |
| **Tam zamanlı** (still internships) | **28** |
| Yarı zamanlı | 13 |
| **(empty)** | **5** |
| mixed combinations | 20 |

Filtering on the type would have dropped a quarter of them. On a `q=yazılım`
search it is worse - 11 of 15 postings declared nothing at all. So the search
is by KEYWORD (`stajyer`, `intern`, `part time`, `yarı zamanlı`), one route
each, merged afterwards. Indeed has no category taxonomy, only free-text
search, so a single query would miss whatever it does not literally match.

### No field filter here

Turkish companies routinely advertise one internship for the whole company and
allocate people to departments afterwards: "Intern" at UPS, "Intern - Long
Term" at Volvo, "Stajyer" at FarklıFikir Bilişim. There is no field to filter
on, and guessing throws them away.

The spider therefore keeps every Istanbul internship and part-time posting it
finds. The field is decided afterwards, by the LLM classifier - see the
section at the end of this file.

### Internships tagged full-time

Same trap as kariyer.net: 19 of 72 postings came back typed only "Tam zamanlı"
and would have normalised to Full-Time, which the dashboard hides. The title's
verdict is put first in `job_type` so `normalize_job_type` ranks Internship
above Full-Time. After the fix: 71 Internship + 1 Part-Time, all visible.

### Description

`snippet` is an excerpt, not the full text, and it is used as-is. Fetching
`/viewjob?jk=<key>` per posting would cost ~75 extra requests a day against
the site most likely to block us and the only independent source we have.

**Superseded 21.09.2026:** the card stores `N/A` and the description comes
from `indeed_check`. See "Checked against the listing-only crawl".

**Careful with the fallback pattern here:** `JsonJobLoader.job_description_out`
is `Join(' ')`, so a second `add_value` is APPENDED, not ignored. Using the
usual `add_value(x); add_value(DEFAULT_VALUE)` idiom left every description
ending in a stray "N/A". Set that field in one call.

### Yield

**72 unique postings** from the `stajyer` route alone, all fields populated.

---

