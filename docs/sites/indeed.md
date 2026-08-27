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

**Careful with the fallback pattern here:** `JsonJobLoader.job_description_out`
is `Join(' ')`, so a second `add_value` is APPENDED, not ignored. Using the
usual `add_value(x); add_value(DEFAULT_VALUE)` idiom left every description
ending in a stray "N/A". Set that field in one call.

### Yield

**72 unique postings** from the `stajyer` route alone, all fields populated.

---

