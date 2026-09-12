# kariyer.net

**Status:** migrated - `spiders/kariyernet_cards.py`. The old DOM spider has
been deleted; it is in git history if ever needed. **Transport since
10.09.2026: a real Chromium, with a real window, opening every page from a
browser context that has never been to the site.** Both halves of that are
load bearing and neither is obvious - "Two gates, not one" below is the
section to read if the crawl ever comes back empty.

**Verified on a rested address 12.09.2026**: 36 consecutive requests, 24
postings stored, every one with a description. Then the wall, which is a
COUNT rather than a rate and which waiting does not clear - see "The limit is
a count, not a rate" below for what that changed.

**Investigated 27.07.2026:**

| | |
|---|---|
| Frontend | Nuxt.js, server-side rendered |
| Anti-bot | **PerimeterX** (`_pxhd` cookie set on every response), app id `PXqzR3QUY9` |
| Anonymous access | Yes, no account needed - but **not from any HTTP client**. Was "`GET /is-ilanlari?cp=2` with no cookies returns HTTP 200"; that stopped being true by 09.09.2026, when every request from curl_cffi was answered 403 whatever handshake it replayed |
| Listings per page | 16 |
| Structured data | `application/ld+json` is only a BreadcrumbList - useless. Job data lives in `window.__NUXT__` as `positionName` / `positionId` |


## Two gates, not one - and the second one is the cookie

**Read this before the two sections below it**, both of which were written
earlier the same day and each of which states its mechanism with more
confidence than it had earned.

kariyer.net has **two separate routes with different policies**, and it took
most of 10.09.2026 to see that:

| | `/is-ilanlari/*` listing | `/is-ilani/*` posting |
|---|---|---|
| headless browser | refused | refused |
| windowed browser, no cookies | **served** | **served** |
| windowed browser carrying a `_px3` from another page | served (mostly) | **refused** |
| curl_cffi, any handshake | refused | refused |

So there are two gates and both are real:

1. **A window.** Measured by interleaving headless and headed launches in the
   same minute - 9 495 bytes and zero cards against 621 kB and 36 of them,
   twice each. This gate is on both routes and the section below has it right.

2. **An unused cookie jar.** The posting route refuses a request carrying a
   `_px3` earned somewhere else, and serves one carrying nothing. One context
   managed exactly one posting; a new context per posting managed five of
   five, description container in every one. Nothing about automation is
   involved - Chrome, Chromium and Firefox were refused identically while
   carrying a cookie, and a plain un-driven Chrome was refused the same way
   once it had one.

### What the earlier sections get wrong

**"PerimeterX refuses a browser with no window"** describes gate 1 and reads
as if it were the whole answer. It is not - it explains the listing route and
misses the posting route entirely, which is why the first live run collected
seven descriptions and then nothing.

**"A page has to live long enough to be read"** proposes that a page torn
down 300ms after DOMContentLoaded never lets the PerimeterX sensor post, so
`_px3` goes stale. Good theory, and it died: a later probe gave posting pages
a four-second dwell, counted TEN sensor requests on each, and every one was
still refused. The dwell is kept because every passing measurement used it,
not because it is the mechanism.

### How the spider is shaped by this

`default_meta()` puts `fresh_context: True` on **every** request, listing
pages included. It was on detail requests alone for one run, on the grounds
that listings had never been refused while sharing a context - and that run
had its SECOND listing page refused. One rule instead of two, and there is no
second rule to forget when a new kind of request is added.

### Answered on 12.09.2026, on a rested address

This section used to ask whether any of it held once the address had
recovered, because everything above was measured on one that had taken a
hundred refusals that afternoon. It does: 45 hours later the same code got
**36 consecutive requests and 24 postings, every one with a description.**

What it also settled is that there is a wall and no delay reaches past it -
see "The limit is a count, not a rate" below, which is the section that
matters now.

## PerimeterX refuses a browser with no window - MEASURED 10.09.2026

This is the section to read before changing anything about how this spider
reaches the site, because two days were spent answering a question the site
was not asking.

**The symptom.** From 09.09 the crawl returned 403 on every request for about
two hours, climbing the whole curl_cffi handshake ladder (firefox147 ->
safari184 -> chrome124 -> firefox135) and failing on all four rungs. The next
morning the first probe of the day was refused as well:

```
python -m scraper.tls_probe --url "<the staj search>" --expect "ad-card"
  firefox147   403   5 065 bytes   marker absent
```

Meanwhile the same address, in a browser, opened any page on the site
instantly. **So the address was fine and the client was not.**

**Working down from "a real browser" to "our real browser."** One variable at
a time, all of it from this machine on 10.09:

| What was driving Chrome | Result |
|---|---|
| nothing - plain `google-chrome <url>`, brand-new profile | **cards** |
| the same ordinary Chrome, attached to over CDP afterwards | **cards** |
| Playwright, `--enable-automation` left in, `navigator.webdriver === true` | **cards** |
| the same, headless | block page |

The CDP-free row was read back out of Chrome's own History database rather
than through any automation, so it says what a person's browser sees.

**Then interleaved**, so a cooling-off effect could not be mistaken for a
verdict. Same binary, same profile shape, same minute:

| | bytes | cards | title |
|---|---|---|---|
| headless #1 | 9 495 | 0 | Access to this page has been denied |
| headed #1 | 621 239 | **36** | İstanbul Staj İlanları ... |
| headless #2 | 9 495 | 0 | Access to this page has been denied |
| headed #2 | 621 665 | **36** | İstanbul Staj İlanları ... |

**PerimeterX here is not reading `navigator.webdriver`, and it is not reading
the debugging protocol. It is refusing a browser with no window.** The block
page is app `PXqzR3QUY9`'s press-and-hold challenge - "İnsan olduğunuzu
doğrulamak için Basılı Tutun" - which no amount of waiting resolves.

### What that means for the spider

`USE_PLAYWRIGHT = True` and `NEEDS_A_WINDOW = True`. The second one makes
`PlaywrightMiddleware` refuse to start headless for this spider rather than
honour a stray `PLAYWRIGHT_HEADLESS=1`, because **headless does not fail
loudly here**: it returns 9 kB, zero cards, and a run that exits 0 having
found nothing, which is indistinguishable from a selector that has rotted.
The same trap catches the checker harder - a block page carries neither an
apply button nor a description container, which is `verdict()`'s exact
definition of UNKNOWN, so a headless check run would mark the whole board
unverifiable instead of blocked.

### Running it unattended

A window needs a display. A desktop session has one. Otherwise:

```
sudo apt install xvfb
xvfb-run -a .venv/bin/python main.py --spider kariyernet_cards
```

That is a real window painted into a virtual screen, not a headless browser -
which is the entire distinction the site is drawing. The middleware prints
this command if it is asked for a window and finds neither `DISPLAY` nor
`WAYLAND_DISPLAY`.

### ~~The browser keeps its profile~~ - REVERSED THE SAME DAY

A persistent profile at `~/.cache/internship-tracker/browser-profiles/`
was added here on the theory that a returning visitor should look like one.
The section admitted in its own words that it was "not load bearing", which
should have been enough reason not to add it.

By the afternoon it was actively wrong. The whole mechanism turned out to be
**arriving with no cookies at all** (see "Two gates" above), so a profile
that carries state between runs is the opposite of what the posting route
wants - and the one profile that HAD accumulated state had accumulated a
hundred refusals with it, giving every run a poisoned `_pxvid` to start from.

Removed. It is in git history. The lesson generalises and is written up in
[README.md](README.md#how-to-work-on-a-spider-without-wrecking-the-address---10092026).

### What was removed

The four-token handshake ladder, `KARIYERNET_IMPERSONATE`, and this spider's
use of `CurlImpersonateMiddleware`. All of it is in git history along with the
31.07.2026 numbers that justified it at the time. The middleware itself stays
- Indeed may still want it - but as of 10.09.2026 **no spider uses it**, so
treat it as untested against a live site.


## A page has to live long enough to be read - MEASURED 10.09.2026

The window got the crawl in. It did not keep it in, and the reason is the
second thing to know about this site.

`PlaywrightMiddleware` opens a page, navigates, hands it to the spider's
`page_actions` and closes it. With no actions defined for posting pages, a
posting therefore existed for the length of `goto` and no longer - between
0.1 and 0.6 seconds. The first live run came out like this:

| | page was open for | result |
|---|---|---|
| listing page 1 | 2.6s (scrolling) | 200 |
| 7 posting pages | ~0.3s each | 200 |
| listing page 2 | 1.7s (scrolling) | 200 |
| **every request after that** | ~0.3s | **403, press-and-hold** |

The two pages that lived for seconds were served. The pages that lived for a
fraction of one were served seven times and then never again.

**The likely mechanism.** PerimeterX's sensor is javascript on the page: it
collects, POSTs to its collector, and the response re-issues `_px3` with a
score. Counted directly with a `page.on("request")` handler on a listing page
given a four-second dwell: **four sensor requests**. A page torn down 300ms
after DOMContentLoaded has made none of them, so the crawl was spending the
one good `_px3` the first page earned and never refreshing it. When it went
stale, everything was refused.

So `POSTING_DWELL_S = 4` - the spider leaves a posting page open for as long
as reading its first screen would take. Four because that is where the sensor
calls were counted, not because four was tuned down to a minimum; at thirty
postings a run it costs two minutes overnight, and every attempt to measure a
smaller number costs this address some credit with the site.

Listing pages need no separate dwell: the scroll that loads the logos already
takes 1.7-2.6s, and neither listing page has ever been refused.


## The posting page is opened once, not every night - 12.09.2026

The site refuses this crawl somewhere around its 35th request, and ~46 of
them were being spent re-reading descriptions already stored. A description
does not change, so the posting page is worth a request the first time and
nothing after it.

```
every card                        -> stored from parse_listing, always
  ... description is real         -> and no posting-page request
  ... description is NULL or N/A  -> and the posting page is fetched
```

**The card is stored whatever happens to the posting page**, added 12.09.2026
after the run above wrote 24 rows for 46 kept cards. `parse_detail` was the
only place an item was yielded, so a title, a company, a city, a work type, a
logo and a link - all already collected - were thrown away for the 22
postings whose pages were refused. Now they are stored immediately and the
description catches up tonight or tomorrow.

Those rows are **visible but unsorted** while they wait:
`classify_jobs.load_unclassified()` skips a row with no description rather
than judging it by its title, because `job_category` is written once and a
title-only guess would outlive the description that arrives the next night.
`report_waiting()` prints how many are waiting, per site, on every run.

**The third line is the one that matters**, and a url-only check would have
got it wrong. On 10.09 twelve of forty-six postings were refused and stored
with `"N/A"`; under "skip anything already stored" they would never be opened
again and would sit there without a description forever. This way a refused
posting rejoins the queue tomorrow, and the queue shrinks as descriptions
land - so the load on the site falls as it succeeds rather than staying flat.

### What it costs the site, per night

| | before | after the first night |
|---|---|---|
| `kariyernet_cards` | 4 listing + 46 detail | 4 listing + however many are new |
| `kariyernet_check` | 46 | 46 |
| **total** | **~96** | **~55** |

At `DOWNLOAD_DELAY = 20` that is the difference between ~55 minutes and ~28
for this site, which is what brings the whole nightly run back under four
hours (see `../pipeline.md`).

**The first run is unchanged** - an empty `job_posts` means every posting is
new - so the saving starts on the second night.

### Two things this does NOT change

**Whether a posting is still open.** Nothing in `parse_detail` ever answered
that. `last_seen_at` is stamped by `pipelines.py` for any item the crawl
yields, and its evidence is the card appearing in a search result, not the
posting page opening; `kariyernet_check` still visits every posting for the
verdict, which is its whole job.

**The stored description.** A skipped item carries no `job_description` field
at all - deliberately, not `"N/A"`. `pipelines.py` only overwrites when the
incoming value is truthy and not `"N/A"`, so either would be safe, but an
absent field says "nothing to say about this column" and that is the true
one.

### The trap it nearly walked into

`parse_detail` used to be **the only place this spider yielded an item**.
Skipping the fetch without yielding from `parse_listing` would have stopped
`last_seen_at` being stamped, and every known posting would have looked like
it had left the board - `_reopen_seen_again` would have had nothing to work
with and the checker's closes would have stood unchallenged. Covered by
`tests/test_detail_once.py`.

A database that cannot be read returns an empty set, so every posting looks
new and every detail page is fetched: the old behaviour, and the safe
direction to fail in.

## The limit is a count, not a rate - MEASURED 12.09.2026 on a rested address

The first clean measurement this site has had: 45 hours since the last
request, against the 10.09 numbers taken on an address that had absorbed a
hundred refusals that afternoon.

| | delay | consecutive requests before the wall | elapsed |
|---|---|---|---|
| 10.09.2026 | 8s | 34 | ~5 min |
| **12.09.2026** | **20s** | **36** | **~10.5 min** |

**Two and a half times the spacing bought two more requests.** Whatever this
site counts, it is not a rate, so there is no delay that gets a 50-request
crawl through and no point looking for one. The delay is now set by the
nightly budget instead (see `../pipeline.md`), not by chasing the wall.

That run stored **24 postings, every one of them with a description**, and 21
with a logo, before the wall - which is what the crawl is for.

### Waiting does not clear it either

A ten-minute cool-off was added on 10.09 on the strength of
`docs/sites/indeed.md`, where a home address recovered on its own in about
eight minutes. Measured against this site:

| | what the pause bought |
|---|---|
| 10.09 | after each 10-minute pause, exactly **one** request got through |
| 12.09 | after the first 10-minute pause, **zero** did |

Six pauses is an hour of waiting for nothing, and each one ends with two more
refused requests finding that out. So `BLOCK_COOLDOWNS_ALLOWED = 0`, and with
it `RETRY_TIMES = 1` and `DOMAIN_BLOCK_BUDGET = 3`: once the wall is up, the
run stops and keeps what it collected instead of spending another twenty
refusals confirming it.

The cool-off machinery stays in `BlockDetectionMiddleware` - it is opt-in and
a site whose refusals really do expire would want it - but no spider asks for
it now.

### Why hitting the wall is survivable

Because the crawl drains its own queue over a few nights. A posting stored
without a description is fetched again next time ("The posting page is opened
once", above), so:

| night | requests | outcome |
|---|---|---|
| 1 | 4 listing + 46 detail | ~36 get through, ~24 stored with a description |
| 2 | 4 listing + ~22 detail | **~26 requests - under the wall** |
| 3+ | 4 listing + that day's new postings | ~8 requests |

The first night is the only one that hits the wall, and hitting it costs
nothing but the postings that wait until tomorrow. The steady state is
comfortably inside whatever the limit is.

**If the wall ever moves down** far enough that night 2 cannot finish, the
next lever is still request count and not time: a per-site
`OPENINGS_MAX_PER_SITE` halves the checker's share. The checker is the half
that should give, because the crawl is what discovers new postings at all.

## ~~When it refuses, wait~~ - SUPERSEDED 12.09.2026, see the section above

The same run says the other thing worth knowing: the refusals did not trickle
in, they arrived all at once and never stopped. There is nothing for the
escalation ladder to change - no proxy configured, no handshake left to swap -
so eight immediate retries just collect eight more refusals and spend
`DOMAIN_BLOCK_BUDGET`, ending the run with two thirds of the postings
uncollected. Which is exactly what happened.

Quiet is the only thing documented to clear it: `docs/sites/indeed.md`
measured a home address recovering on its own in about eight minutes after
the same treatment. So the spider sets

```python
BLOCK_COOLDOWN_S = 600          # ten minutes of doing nothing
BLOCK_COOLDOWN_AFTER = 2        # ... after two refusals IN A ROW, not one
BLOCK_COOLDOWNS_ALLOWED = 6     # ... at most six times in a run
```

and `BlockDetectionMiddleware._cool_off` waits, resets the budget the burst
would have spent, and re-queues the request. Opt-in per spider, so Indeed and
LinkedIn still fail fast - a pause does not fix an expired session.

`main.py`'s `SPIDER_TIMEOUTS` gives this spider and its checker a two-hour
ceiling to match. Without it a run would be killed mid-pause and reported as
a failure for doing exactly what it was told.

**Not yet measured:** whether a run that has been cooled off comes back
clean. The unit tests in `tests/test_block_cooldown.py` cover when the pause
fires and when it stops; only a live run that actually gets refused can say
whether ten minutes is the right number.

## There is probably no JSON listing endpoint

Pagination links are plain anchors - `<a href="/is-ilanlari?cp=2">`, going up
to `cp=100`. The listing is server-rendered and paging is ordinary page
navigation, so no XHR carries the job data. A DevTools Network capture on this
site is dominated by GTM / Google Analytics / DoubleClick / Taboola and
PerimeterX sensor posts (263 requests on one page load); the job data is not
among them.

**Consequence: the filters live in the page URL**, not in an API call. To
learn a filter's parameter name, apply it in the UI and read the address bar.

## Working type taxonomy - CONFIRMED

Each ad card carries `workTypeId` / `workTypeText`. Codes verified against a
live page (38 `F`, 11 `P`, 1 `D`):

| Code | Meaning | Wanted |
|---|---|---|
| `F` | Tam zamanlı (full-time) | |
| `P` | Yarı zamanlı (part-time) | **yes** |
| `S` | Staj (internship) | **yes** |
| `D` | Dönemsel (seasonal) | |
| `R` | Serbest (freelance) | |
| `G` | Gönüllü (volunteer) | |

## Filter panel taxonomies

Three separate axes in the sidebar, from the filter markup
(`k-filter-checkbox-*`): **Departman**, **Pozisyon**, **Pozisyon Seviyesi**.
"Departman" is the field-level one we want for software/IT. Ad cards also
carry `sectorId` and `positionId`.

## Internships may live on a different host

The main menu links to **`ilkisim.kariyer.net`** ("İlk İşim ve Staj"). No
`workTypeId="S"` ad appeared on the sampled listing page, so internships are
either rare in the main index or served entirely from that subdomain. Needs
checking - internships are half the target.

**HTML page parameters** (known from the existing spider):

| Param | Meaning |
|---|---|
| `kw` | keyword |
| `ct` | city plate number (34 = Istanbul) |
| `cp` | current page |

## Ad card structure - CONFIRMED against a live page

Each posting is a `<div data-test="ad-card">` with the data as attributes.
**Attribute names must be matched in lowercase** - HTML parsers normalise
`workTypeId` to `worktypeid`, and the CamelCase form matches nothing silently.

| Field | Source |
|---|---|
| job_title | `[data-test="ad-card-title"]::text`, fallback `positionname` attr |
| company | `img[data-test="company-image"]::attr(alt)` (full name; the visible subtitle can be ellipsised) |
| location | `[data-test="location"]::text` - **not** the `cityname` attribute, see below |
| job_type | `worktypetext` attr, normalised by `pipelines.normalize_job_type` |
| url | `a[data-test="ad-card-item"]::attr(href)`, needs `urljoin` |
| company_logo_url | `img[data-test="company-image"]::attr(src)` - the same tag as `company`. **Mostly a placeholder, see below** |
| work model | `workmodeltext` attr ("İş Yerinde" / remote) |

Other attributes present: `positionid`, `companyid`, `jobcode`, `sectorid`,
`sectorname`, `cityid`, `countryid`, `time`, `sponsor`, `jobstatus`.

**The logo is lazily loaded, and the placeholder looks like a logo - measured
09.09.2026.** Over 40 cards on one listing page:

| src shape | Cards |
|---|---|
| `data:image/svg+xml` 1x1 transparent | **25** |
| absolute `https://img-kariyer.mncdn.com/mnresize/150/150/...` | 12 |
| protocol-relative `//img-kariyer.mncdn.com/UploadFiles/...` | 2 |
| no `img` in the card at all | 1 |

The placeholder is a real `<img>` with the company name still in `alt`, so a
`src`-only read returns something for every card and roughly two thirds of it
is an invisible 1x1. `api_spider.logo_url()` drops `data:` for that reason;
stored, it would paint nothing where the board would otherwise draw the
company's initials. The protocol-relative ones are pinned to `https`, which
the host answers (200).

The detail page carries the logo server-rendered, and this spider already
fetches it for the postings it keeps - so a fallback there is available if the
`logo/found` counter says the listing is not good enough. Not done yet: the
detail page has dozens of images (header art, award badges, recommended
employers) and picking the right one needs its own measurement.

**The check spider reads the description too - 09.09.2026.**
`kariyernet_check.verdict()` already selects
`[data-test="qualifications-and-job-description"], [data-test="job-description"]`
to prove it is on a posting page, so `description()` reads the text out of the
same container with the selectors copied verbatim from
`kariyernet_cards.py:449-461`. Note the consequence: on a CLOSED posting that
container is exactly the branch that fired, so a closed posting still yields a
description - which is what a reader wants behind the "Kapananlar" toggle.

**Multi-city trap:** a nationwide posting has
`locations="[object Object],[object Object],..."` and `cityname` holds only the
first entry, so an ad covering all 81 provinces reports `cityname="Adana"`.
The rendered text is honest - "İstanbul(Asya) +80 il daha" - so read the text
and keep the attribute only as a fallback. For single-city ads the two agree.

**Page size:** 50 cards per listing page.

## Filter by DEPARTMENT, not sector - the single biggest correction

Sector (`cs`) describes what the **company** does; department (`wa`) describes
what the **role** is. The first attempt filtered on sector = Bilişim and
produced mostly sales and office jobs at IT companies, while missing every
developer role at a bank, a hospital or a factory.

Switching axes changed the result completely:

| Filter | Postings kept | What they were |
|---|---|---|
| sector = Bilişim | 7 | 4 of them sales/office roles at IT firms |
| department list | 28 | includes Software Engineering Intern (GE), Bilgisayar Mühendisliği Stajyeri, Bilgi İşlem Stajyeri, Bilgi Teknolojileri Stajyeri |

## Search URLs - CONFIRMED

```
parttime: /is-ilanlari/istanbul-part+time?ct=34,82&wa=2,5,22,54,55,60,63,78,87&tpst=4
staj:     /is-ilanlari/stajyer?ct=34,82&wa=2,5,22,54,55,60,63,78,87
```

| Param | Meaning |
|---|---|
| `ct` | city plate numbers. **Istanbul is two codes** - 34 (European) and 82 (Asian). Using only 34 loses half the city. |
| `wa` | department list, chosen in the UI |
| `tpst` | working type; `4` = part-time |
| `cs` | sector code - **no longer used**. Mapped onto the `sectorid` card attribute. |
| `cp` | page number, added by the spider |

**`tpst` is coupled to the URL slug.** `/is-ilanlari?...&tpst=4` without the
matching `istanbul-part+time` slug returns zero cards, while the same query
with the slug returns 6. So the part-time URL is copied verbatim from the
address bar rather than assembled in code. To change the filters, redo the
search on the site and paste the new address.

`/istanbul-bilisim` is an SEO slug. Adding `cp=2` makes the site **301** to
`/istanbul-bilisim-2?...&cp=2`; Scrapy follows it, so there is no need to build
the slug. URL-encoding the comma (`ct=34%2C82`) works identically to the raw
form - both verified against the live site.

**Listings shift between requests:** consecutive fetches of page 1 and page 2
shared 5 of 53 postings, and they were not sponsored. Ordering simply moves as
new ads arrive. Harmless - the upsert is keyed on url - and `next_page_allowed`
still sees 48 new records, so pagination detection is unaffected.

## Employers mis-code internships - IMPORTANT

`worktypeid` alone is not a reliable internship filter. On the sampled page:

| | |
|---|---|
| `[P]` E-Ticaret Stajyeri | coded part-time |
| `[F]` Grafik Tasarım Stajyeri | coded **full-time** |

Half the internships on that page were coded `F`, because a full-time
internship really is full-time hours. So the spider keeps a card when
`worktypeid in {P,S}` **or** the title/positionname matches
`\b(staj\w*|intern(?:ship)?s?)\b` - the word boundary stops it firing on
"International".

Rescued postings also get `job_type` overridden to "Staj". Otherwise the
site's "Tam zamanlı" would normalise to Full-Time and the dashboard - which
defaults to Internship + Part-Time - would hide the very posting we went out
of our way to keep.

## Spider

`spiders/kariyernet_cards.py`. Pages the filtered search, applies the filter
above, and requests the detail page only for the survivors - so only the few
percent of postings we want cost a second request.

## Actual yield - the whole result set, crawled

All 8 pages fetched and run through the spider (not extrapolated):

| | |
|---|---|
| Cards read | 351 across 8 pages (page 7 partial, page 8 empty) |
| Unique postings | 316 - the site claims 334; the index shifts between requests |
| `F` full-time | 308 |
| `P` part-time | 5 |
| `D` / `R` | 2 / 1 |
| **`S` internship** | **0 - none at all** |
| **Spider keeps** | **6** (2 Internship + 4 Part-Time after relabelling) |

So the realistic daily yield for this search is a handful of postings, not
dozens. The site's own part-time filter shows roughly the same 5-6; the
spider's addition is the `F`-coded internships that no site filter reveals.

## `ilkisim.kariyer.net` is not a separate site - RESOLVED

It is a landing page with no ad cards, linking to `/is-ilanlari/stajyer` on
the main site. Internship listings are ordinary kariyer.net postings.

That slug takes the same parameters, so
`/is-ilanlari/stajyer?ct=34,82&cs=001000000` gives the IT internships in
Istanbul - 3 at the time of writing:

| Code | Title |
|---|---|
| `F` | Grafik Tasarım Stajyeri |
| `P` | E-Ticaret Stajyeri |
| `P` | Startpoint - Uzun Dönem Staj Programı |

**The decisive detail: none of them is coded `S`.** kariyer.net's own
internship search is a slug search over titles, not a working-type filter, and
no employer uses the `S` code - zero across 316 sampled postings. With the
department filter that search returns 26 internships, coded **D (19), P (4),
F (3)** - so a working-type filter of any kind is the wrong instrument.

## Trust the search, not the title

`INTERNSHIP_TITLE_RE` is a good signal but not sufficient: "Career Experıence
Drıve - IT (Servıce&Operatıons)" is a real internship with neither "staj" nor
"intern" in its title, and the regex would drop it.

So `INTERNSHIP_SEARCHES = {"staj"}`: everything the site's own internship
search returns is kept and labelled Internship, no questions asked. The site
classifies its own postings better than a regex can guess. The regex stays as
the fallback for the part-time search, where a P-coded "E-Ticaret Stajyeri"
should still come out as an internship.

## Yield - both searches, verified

**28 unique postings: 26 Internship + 2 Part-Time**, one page each, no
pagination needed. 22 of the internships were coded D or F by the employer -
i.e. the work-type code would have hidden them.

Real matches now surfacing that the sector filter had hidden: Software
Engineering Intern (GE Marmara Technology Center), Bilgisayar Mühendisliği
Stajyeri, Bilgi İşlem Stajyeri (Alliance Healthcare), Bilgi Teknolojileri
Stajyeri (TK Asansör), Career Experience Drive - IT (Eczacıbaşı).

Some noise comes with it - Hukuk Destek Stajyeri, PepsiCo's finance and
marketing interns - because the department selection is deliberately wide. At
this volume that is the right trade: a stray listing costs a glance, a missed
internship costs an opportunity.

## Bug found by crawling the full set

`next_page_allowed()` stopped at page 5 claiming the index was repeating,
while page 5 was entirely new postings. `BaseApiSpider.record_key()` fell back
to `repr()` for non-dict records, and parsel truncates a Selector's repr to
~40 characters, so unrelated cards collapsed onto the same key. A real crawl
would have silently lost pages 6-8.

Fixed in two places: the base class now serialises Selector-like objects
properly instead of using `repr()`, and the spider overrides `record_key()` to
use the posting link, which is a card's real identity.

**Still to capture:**
- [ ] Whether internships are on `ilkisim.kariyer.net` and what that site's structure is
- [ ] Date parameter (for the daily delta run)

**Extraction plan:** parse the server-rendered HTML. This is not a step
backwards from the JSON plan - the ad cards expose `data-test` attributes and
`workTypeId` / `sectorId` / `positionId`, which are far more stable than CSS
classes. The `window.__NUXT__` payload holds the same data if the markup ever
proves insufficient, but it is a minified IIFE rather than plain JSON, so it
needs a JS engine or a careful extractor.

---

