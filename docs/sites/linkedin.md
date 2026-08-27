# LinkedIn - was OUT OF SCOPE, running again since 26.08.2026

**The original entry, kept because it was not wrong** (27.07.2026): deliberately
excluded. Its JSON API (Voyager) only answers authenticated requests, and
pointing the bot at a personal account risks a permanent ban for very little
extra coverage. Checked by hand instead. `spiders/linkedIn.py` was deleted.

**What changed on 26.08.2026 is one word: whose.** The account is now a burner,
opened for this and holding nothing. Every risk above still stands - guest
access was re-tested that day and is genuinely gone, so there is no anonymous
mode to fall back to, and LinkedIn still closes accounts it catches
automating. This is an exception bought with an account we can afford to lose,
not a refutation. If it is ever pointed at a personal profile, the 27.07 entry
becomes correct again.

**Status:** running - `spiders/linkedin_cards.py`, `spiders/linkedin_check.py`.

## Everything below was measured on 26.08.2026, through the burner session

Headless Chromium, one navigation each, ~20 requests over ~40 minutes: HTTP
200 throughout, no authwall, no challenge.

## The location filter does not work by name

A search for `stajyer` with `location=İstanbul, Türkiye` as text returned
**4,446 results including Konya and İzmir**. The place name is decoration; the
filter binds through `geoId` and nothing else. The value was read off
LinkedIn's own typeahead by driving it rather than guessed:

| Suggestion | Used |
|---|---|
| **Greater Istanbul** | `geoId=90010422` <- what the spider sends |
| Istanbul, Türkiye | (narrower, not used) |
| Istanbul, Istanbul, Türkiye | (narrower, not used) |

Greater Istanbul on purpose: it keeps the district-level postings (Sarıyer,
Nişantaşı, Şişli) that a tighter id would drop. Country-wide **remote**
postings still leak in as "Türkiye (Remote)" - kept deliberately, since remote
work is reachable from Istanbul, and it is the opposite of the problem the
Indeed section worries about, where a city filter hides remote roles.

## Filter ids, read out of the filter panel's own inputs

Not guessed and not copied from a blog post - the "All filters" panel was
opened and its `<input>` values and labels were enumerated:

| Parameter | Values |
|---|---|
| `f_E` experience | 1=Internship 2=Entry level 3=Associate 4=Mid-Senior 5=Director 6=Executive |
| `f_JT` job type | I=Internship P=Part-time F=Full-time C=Contract T=Temporary V=Volunteer O=Other |
| `f_TPR` date posted | r86400=24h r604800=week r2592000=month |
| `f_WT` workplace | 1=On-site 2=Remote 3=Hybrid |
| `f_F` job function | it=Information Technology eng=Engineering (plus sale, mrkt, fin, ...) |

`sortBy=DD` is most-recent-first, `sortBy=R` is relevance. The spider sends
`DD`: a crawl that runs every couple of days wants what is new on page one.

## THE CARDS ARE NOT ALL ON THE PAGE - the expensive one

The result list is virtualised. Measured on one page, read twice:

| When | `li[data-occludable-job-id]` | rendered cards |
|---|---|---|
| 0.2s after the first card appears | 7 | 7 |
| after polling 20s | 25 | 7 |
| after scrolling the list to the end | 25 | **25** |

Both of the first two readings are correct and neither is the whole page. A
spider that calls `page.content()` on load stores **7 of every 25 postings and
reports a clean run** - this project's most expensive shape of bug.

So `PlaywrightMiddleware` grew a `page_actions` hook (opt-in, Indeed does not
define one) and `linkedin_cards.page_actions` scrolls until several
consecutive steps add nothing. It does NOT scroll to a target count: there is
no number to trust, because the `<li>` shells are appended as you approach
them too.

The element that scrolls has a build-hashed class
(`GEKTuqWiIyqOShwESkHQRbcfLJlXGyMrOloAXU`), so it is found by SHAPE - walk up
from a card to the first ancestor that overflows - and no LinkedIn class name
appears in that javascript.

## Navigation headers broke the page, invisibly

`BrowserSession.document_headers()` describes a NAVIGATION. Playwright's
`set_extra_http_headers` applies them to **every** request the page makes,
including the application's own API calls - so the XHR fetching the job list
went out as `Accept: text/html` with `Sec-Fetch-Dest: document`. Measured, one
url, three variants, same session, minutes apart:

| Headers sent | Result |
|---|---|
| none | 25 cards, 1 second |
| full document headers | **0 cards, body 0 bytes, the application never booted** |
| identity only (UA, sec-ch-ua, Accept-Language) | 25 cards, 1 second |

It arrived looking like "the search returned nothing". `_navigate` now drops
`Accept`, `Upgrade-Insecure-Requests` and the four `Sec-Fetch-*` headers, and
sends identity only.

### That change cannot have affected Indeed, and here is the measurement

The obvious fear is that it does: `indeed_cards.py` records that Indeed wants
the Referer and `Sec-Fetch-Site: same-origin` and the cookies *together*, and
dropping Sec-Fetch looks exactly like breaking that. Indeed did start
challenging every search page the same afternoon, which made it look settled.

It is not what happened. Measured against a local server that printed the
headers it actually received:

| What the code did | What the server saw |
|---|---|
| `set_extra_http_headers({... Sec-Fetch-Site: same-origin ...})` | `Sec-Fetch-Site: none`, and Chromium's own full `Accept`, not ours |
| nothing set at all | byte for byte the same |
| a route handler forcing them on the navigation | `Sec-Fetch-Site: none` again; only `Accept` survives that path |

`Sec-Fetch-*` is browser-controlled and cannot be forged from Playwright.
**So that request has always gone out as `Sec-Fetch-Site: none`** - before
this change and after it. Indeed's own measurement was taken through
curl_cffi, which really does send what it is told; the Playwright transport
never reproduced it.

Which means these headers only ever affected SUBRESOURCES, where they were
doing nothing but harm. A route handler was written to scope them to the
navigation, measured to be useless by the table above, and deleted.

**Indeed's challenges that afternoon are unexplained by this and remain
unexplained.** The address had spent its block budget twice earlier the same
day (see the block-budget note in api_middlewares.py, which says a burst of
refusals leaves the address worse off for the next run), so the reputation
bucket is the first place to look - not this diff. Re-measure Indeed from a
rested address before concluding anything.

## The card fields

| Field | Where |
|---|---|
| id | `li[data-occludable-job-id]` |
| title | `a.job-card-list__title--link` **`aria-label`** |
| company | `.artdeco-entity-lockup__subtitle` |
| location | first `li` of `.artdeco-entity-lockup__caption` |
| url | rebuilt as `/jobs/view/<id>/` |

Read the whole element's text, never `::text`. Ember writes its bindings as
`<span><!---->Guess Europe Sagl<!----></span>`, so the first text node is the
whitespace before the comment - every company and location came back "N/A"
until this was fixed (`node_text()` in the spider).

**The title is in the `<strong>`, not in the `aria-label`.** aria-label was the
obvious source and is wrong for half the board: LinkedIn appends its
verified-poster badge to the accessible name, so a verified company's posting
reads `aria-label="Web & Mobile Design Intern with verification"` while the
element text is the clean title. Measured on the first real crawl: **103 of
230 stored titles carried " with verification"**.

That was not cosmetic. `pipeline/dedupe_jobs.py` pairs postings across boards on
normalised title AND company, so the badge silently disabled duplicate
detection for those rows - stripping it opened **25 previously invisible
cross-board duplicates** (Siemens, PepsiCo, PVH, AstraZeneca, TikTok postings
that were sitting on the board twice).

The url is REBUILT rather than taken from the card's href: the href carries
`refId`/`trackingId`/`eBP` parameters that change every crawl, and `url` is
the UNIQUE upsert key, so using it would store every posting again under a new
url on every run.

## First classification, 26.08.2026

207 postings (230 minus the 25 duplicates) through `pipeline/classify_jobs.py`:
**it 36, general_program 32, other 139**. The 67% "other" rate is in line with
Indeed's own (112 of 157 on a sampled run) - a general job board filtered only
by internship/part-time is mostly not software work, on every site so far.

Worth watching: this ran on TITLES ALONE, because LinkedIn cards carry no
description. `general_program` is therefore doing more work than it does for
other sites - it is where the prompt sends anything it cannot place, and that
is the safe direction (those rows stay visible). If that pile stops being
useful, fetching descriptions is the lever - see below.

Net effect on the board: LinkedIn contributes **68 visible postings**, more
than Indeed's 38 on the same day.

## No description, on purpose

A card carries a title, a company and a location and nothing else. Reading
descriptions means one request per posting, which doubles the traffic on the
account we are least able to replace, so `job_description` is `N/A` and the
classifier decides on the title. Revisit if the `general_program` pile grows
useless - and measure it then.

## Two routes

| Route | Query | Why |
|---|---|---|
| `filter-staj` | `f_E=1` | what LinkedIn itself files as an internship |
| `filter-parttime` | `f_JT=P` | ditto, part-time |
| `scan-*` | free-text keywords | the postings whose employer ticked the wrong box |

Title matching (`is_wanted`) is applied to the scan routes only. On the filter
routes the SITE has already said what the posting is, and the ones whose
titles say nothing - "Career Experience Drive - IT" - are the entire reason
that route exists.

First full run, 26.08.2026, six routes, five pages each, 295 seconds, **286
postings / 230 unique**:

| Route | Found | Sole finder of |
|---|---|---|
| `filter-parttime` | 125 | **107** |
| `filter-staj` | 120 | **90** |
| `scan-intern` | 13 | 0 |
| `scan-part-time` | 9 | 1 |
| `scan-stajyer` | 7 | 0 |
| `scan-yazilim` | 7 | 0 |

Read that honestly: **the two filter routes are the crawl.** The four scan
routes cost 20 requests between them and contributed ONE posting nobody else
found. That is the opposite of every other board here, where the site's own
filter was the thing that leaked - LinkedIn's `f_E`/`f_JT` are evidently
filled in properly, and a keyword search matched on description brings back
mostly noise (`scan-stajyer` kept 1 of 25 cards on its first page).

Do not delete the scan routes on one run's evidence - that is the rule this
project already wrote down, and one of them did find something. But the next
tuning decision is clear and is NOT "add more keywords": **all six routes hit
`MAX_PAGES = 5` with results still arriving**, and `filter-staj` was still
keeping 25 of 25 on page five. Depth is productive here in a way it explicitly
was not on Indeed, where pages 10-15 repeated the same six postings. Spend the
budget on deeper filter pages before spending it on more scans.

The MAX_PAGES ERROR fired six times in that run. It is the circuit breaker
doing its job, not a fault.

Request order is set with `priority=` rather than by the order of the dict:
Scrapy's default queue is LIFO, so yielding six searches in order runs them
backwards. See the note under `_route_priority` - and note that
`indeed_cards.SEARCHES` has the same problem and has NOT been fixed.

## The intermittent stall

Roughly one run in two, one navigation sits inside `_navigate` for minutes -
five, in the worst case measured - while `page.goto`'s own 45s timeout never
fires. It is not in `goto`: `page.evaluate()` and `locator.count()` run
javascript in the page and neither takes a timeout, so when LinkedIn's scripts
wedge the renderer they wait for it forever.

Two containments, neither of which is a cure:

  * `ACTIONS_BUDGET_S` puts a wall clock over the scroll loop, so the loop
    cannot add to a stall.
  * The middleware's own budget now raises a sentence explaining itself
    instead of a `concurrent.futures.TimeoutError` with an empty message,
    which is what made this take an hour to find.

While one navigation is wedged the browser thread cannot take the next one, so
the requests behind it wait. A run with a few of these is a slow site, not a
broken crawler.

## Is the posting still open - UNMEASURED

`spiders/linkedin_check.py` exists and is deliberately written around not
knowing the answer yet: on 26.08.2026 the database held no LinkedIn posting
old enough to have closed, so there was no closed page to read a marker off.
CLOSED requires the page to say so in words; anything else is UNKNOWN and
writes nothing. Expect "N open, 0 closed, M inconclusive" until the first real
closure - that is the correct result, not a broken one.

When `linkedin/closed_marker_seen` first appears in a run's stats, that is the
measurement. Record the id and the date here, and this section joins the other
three.

**The detail page stalls far more often than the search page.** First dry run,
five postings, `OPENINGS_MAX_PER_SITE=5`: **1 open, 0 closed, 0 inconclusive,
4 unanswered** - four of five navigations spent the whole Playwright budget
(`playwright/navigation_timeout: 4`). Nothing was written for those four,
which is the design working, but a checker that answers one posting in five is
not yet worth running over the whole board. Before turning it loose, the thing
to try is blocking images/fonts/analytics on this transport so the page has
less to wedge on - not a longer timeout.

The detail page is a DIFFERENT design system from the search page: search
cards still use semantic classes (`job-card-container`), while the job page
has build-hashed ones (`_59162b76`, `b424a163`). The stable anchors there are
`aria-label="Easy Apply to this job"` and the `<h2>` headings.

---

