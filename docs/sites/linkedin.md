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

**Status:** OUT OF THE SCRAPING FLOW since 16.09.2026. Two burner accounts were restricted that day, the second before any request, and further requests from this address put the owner's own account at risk (see the last sections). `spiders/linkedin_cards.py` and `spiders/linkedin_check.py` are kept but refuse to start without `LINKEDIN_ENABLED=1`, and `main.py` does not know them.

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
| company_logo_url | `.artdeco-entity-lockup__image img::attr(src)` - the lockup's image slot, sibling of the two above |
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

## The logo IS on the card, and it costs nothing - 09.09.2026

Measured on one search page, after `page_actions` finishes scrolling: **25 of
25 cards rendered, and every rendered card carries the employer's logo
server-rendered in the html we already have.** Nesting:

```
.job-card-list__entity-lockup            (the lockup)
  .job-card-list__logo                   (== .artdeco-entity-lockup__image)
    .ivm-image-view-model
      .ivm-view-attr__img-wrapper
        <img src="https://media.licdn.com/dms/image/v2/.../company-logo_100_100/...">
```

Worth knowing before trusting it: the `<img>` says `loading="lazy"` and
carries a `lazy-image` class, which normally means the src is a placeholder
and the real url is in `data-delayed-url`. **It is not** - the src is a real
`media.licdn.com` url, and neither `data-delayed-url` nor a `ghost-` class
appears anywhere in the card. The asset is `company-logo_100_100`, i.e. 100px,
displayed at 56.

This is the one field the "no detail page" rule (below) does not cost us
anything on: it is on the card, so reading it adds no request to the account
we are least able to replace. An employer with no logo gets a ghost element
instead of an `<img>`, so the selector returns nothing and the column stays
NULL - `scraper/api_spider.logo_url()` has the rest of the rejection rules.

## The description IS reachable - from the CHECKER, not the crawl - 09.09.2026

The section below still stands for the crawl and is not being reversed: a
description costs one extra request per posting there, and doubling the
traffic on a burner account for it is not worth it.

But `linkedin_check` already fetches `jobs/view/<id>/` for every posting on
the board, to ask whether it is still open. The description is in that
response, so reading it there adds nothing:

```
[data-testid="expandable-text-box"]
```

which is not a new anchor - `linkedin_check.DETAIL_MARKERS` already gates the
render on this exact selector, so a page that rendered enough to answer the
verdict rendered enough to answer this too.

Measured over two postings: **1462 and 3652 characters** of real text. Three
class-based selectors were tried alongside it and matched **nothing**:

| Selector | Result |
|---|---|
| `[data-testid="expandable-text-box"]` | 1462 / 3652 chars |
| `.jobs-description__content` | no match |
| `.jobs-box__html-content` | no match |
| `#job-details` | no match |

That is this file's own warning holding up: LinkedIn hashes its class names
per build, and `data-testid` is one of the two anchors that survive.

**Coverage is 23 of 40, and the missing 17 are not a failure to render.** A
real run over 40 postings returned 40 OPEN verdicts, zero
`linkedin/detail_never_rendered`, zero `linkedin/unreadable_detail` - and 17
pages with no `[data-testid="expandable-text-box"]` in them at all. So the
pages arrived intact and simply do not all carry that element.

Not measured yet, and worth one run before anyone writes a fallback: the
likeliest reason is that the box is the *expandable* wrapper, and a
description short enough not to need expanding is rendered without it. If that
is right the fallback is whatever plain container holds the short ones, and it
is cheap. If it is wrong, guessing at a second selector is how a wrong one
gets shipped.

**Length: mean 3383 characters over the 23.** `classifier.DESCRIPTION_CHARS`
is 1500, so more than half of a typical LinkedIn description never reaches the
model. That number was chosen when descriptions were rare and short; it is now
the binding constraint on the input this whole change exists to provide.

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

### CURED 27.08.2026 - it was the page being reused, not the javascript

The theory above named `page.evaluate()` and `locator.count()`. It was the
right family and the wrong call. Reproduced with per-phase logging on
`linkedin_check`:

    15:19:33  worker dequeued .../jobs/view/4452210240/
    15:26:15  Received SIGTERM              <- an external timeout, 7 min later
    15:26:35  worker dequeued (the next one)

No `headers done` line was ever printed, so the wedge was in
`page.set_extra_http_headers()` - before the navigation had even started - and
it did not end on its own. It ended when SIGTERM broke the driver connection.

That call takes no timeout. Neither do `content()` or `evaluate()`, and
`set_default_timeout` does not help: Playwright applies it only to "methods
accepting a timeout option", which none of these are. So any page whose
renderer has stopped servicing protocol calls blocks every one of them
forever, and since the worker is a single OS thread, every request behind it
waits forever too.

The cause was that the middleware opened ONE page at start-up and handed the
same object to every navigation for the whole crawl. LinkedIn's job pages
leave enough running to get a renderer into that state within two or three
visits. `_run_job_loop` now opens a fresh page per navigation and closes it
afterwards, keeping the context - the cookies and storage state are the
expensive part. A page costs about 10ms.

Measured on the same 8 postings, before and after:

| | navigations completed | verdicts | wall clock |
|---|---|---|---|
| one page, reused | 2 of 9 | — (killed) | 20 min, then SIGTERM |
| a page per navigation | 9 of 9 | 8 | 79s |

Then over 25 postings: **25 open, 0 closed, 0 inconclusive, 0 unanswered** in
212s, `playwright/navigation_timeout` absent from the stats entirely.

Indeed's 9 navigation timeouts in the 27.08 run are unexplained by anything
else and are very likely the same bug; that has not been confirmed, because
Indeed was being challenged that day and never got far enough to test it.

## Is the posting still open - MEASURED 27.08.2026

`spiders/linkedin_check.py` exists and is deliberately written around not
knowing the answer yet: on 26.08.2026 the database held no LinkedIn posting
old enough to have closed, so there was no closed page to read a marker off.
CLOSED requires the page to say so in words; anything else is UNKNOWN and
writes nothing. Expect "N open, 0 closed, M inconclusive" until the first real
closure - that is the correct result, not a broken one.

When `linkedin/closed_marker_seen` first appears in a run's stats, that is the
measurement. Record the id and the date here, and this section joins the other
three.

### The marker, at last

The first real closure came through on 27.08.2026, on the second full run of
the day - the same day the section below fixed the checker enough to reach the
whole board.

| | |
|---|---|
| posting | id=59, "Machine Learning Analyst (Remote)" |
| url | `https://www.linkedin.com/jobs/view/4459636725/` |
| stat | `linkedin/closed_marker_seen: 1` |
| run | 77 postings: **76 open, 1 closed, 0 inconclusive, 0 unanswered** |

Fetched directly afterwards to see which of the four guessed phrases actually
matched, and how the page renders it:

    <... aria-label="Error"> No longer accepting applications

So `"no longer accepting applications"` is confirmed, verbatim. Two things
worth keeping:

  * **The string is English even under `locale="tr-TR"`.** The three Turkish
    phrases in `CLOSED_MARKERS` remain guesses and have never been observed;
    they cost nothing and are left in place against an interface that changes
    its mind.
  * **The closed page carries no apply affordance at all** - no
    `Easy Apply to this job`, no `Apply on company website`, no
    `Save the job`. The two halves of the verdict agree, which is what the
    OPEN/CLOSED/UNKNOWN split was built to rely on.

`aria-label="Error"` looks like a sturdier anchor than the sentence and may
well be one. It has been seen exactly once, so it is written down here rather
than put in the code.

### THERE ARE THREE APPLY AFFORDANCES, NOT TWO - measured 27.08.2026

The checker knew about `Easy Apply to this job` and `Apply to this job`. A
posting that applies on the employer's own site says neither:

    aria-label="Easy Apply to this job"      apply inside LinkedIn
    aria-label="Apply on company website"    apply elsewhere - just as open

Missing the third form cost half the board. On a dry run over eight postings
the result was 4 open, 4 inconclusive, and the phase log gave it away before
the pages did: the four that resolved matched the apply selector in 0.0s, the
four that did not spent 0.9s falling through to the description box. Fetching
three of them directly confirmed it - `Apply on company website` and
`Save the job` on the inconclusive ones, `Easy Apply to this job` on an open
one, and not a word about being closed on any of them.

With the third marker added, 25 of 25 resolve.

**The detail page used to stall far more often than the search page**, and
that is fixed - see "CURED 27.08.2026" above. The first dry run, before the
fix, answered 1 posting in 5 (`playwright/navigation_timeout: 4`).

The detail page is a DIFFERENT design system from the search page: search
cards still use semantic classes (`job-card-container`), while the job page
has build-hashed ones (`_59162b76`, `b424a163`). The stable anchors there are
the apply `aria-label`s above and `[data-testid="expandable-text-box"]`.

---


## 15.09.2026 - the checker is the bottleneck now, and three things it got wrong

Since 12.09.2026 `pipeline/classify_jobs.py` does not classify a row until it
has a description (kept on purpose - the model should read the posting, not
guess from its title). On LinkedIn the description arrives from ONE place,
`linkedin_check`, so from that date the checker decides when a LinkedIn
posting gets sorted. Read with that in mind, three faults that no run had
flagged:

### 1. The time limit covered a sixth of the board

`linkedin_check` ran under the shared `CHECK_TIMEOUT`, 1200s. At the measured
8.2s a posting (28.08.2026: 83 in 680s) that is ~140 postings, against **760
open LinkedIn rows** in the 09.09.2026 backup. The rest waited days for a
description, and so for a category.

Decided the same day: while LinkedIn is answering, the ceiling must not be
what stops the checker - a refusal should, and `DOMAIN_BLOCK_BUDGET` already
does that. `SPIDER_TIMEOUTS["linkedin_check"]` is now 5 hours
(`LINKEDIN_CHECK_TIMEOUT`), sized for a board of 1000 at a worst rate of 14s
a posting (the throttle's 1.5x bound on `DOWNLOAD_DELAY` 8, plus a ~1.7s
fetch). If the set to check outgrows that, the checker says so in its first
lines instead of being found cut short. Test: `tests/test_linkedin_check.py`.

The cost of that decision, said plainly: one full check is one detail-page
view per open posting on the burner account - several hundred in a sitting.
Nothing has measured how LinkedIn treats that volume on one account.

### 2. The wait never learned the third apply control

`DETAIL_MARKERS` was a hand-written copy of the apply markers and said
`[aria-label*="Apply to this job"]` - which covers "Easy Apply to this job" as
a substring and not **"Apply on company website"**, the form measured on
27.08.2026. The verdict learned it; the wait did not. A company-website
posting whose page had no description box therefore sat out the whole 15s
and was counted as `linkedin/detail_never_rendered`. The selector is now
built from `APPLY_MARKERS`, and a test fails if they drift apart.

### 3. The wait ended on the button, not on the description

`DETAIL_MARKERS` is "any of these", so the wait ends when the apply button
appears. That gives a second explanation for the 17-of-40 pages without a
description box, next to the one written down on 09.09.2026:

  1. a short description is rendered without the expandable wrapper, or
  2. the box was still coming when `content()` was taken.

Rather than pick one, the checker now waits up to 5s more for the box
whenever the first marker was not the box, and counts the outcome - no extra
request, and on most pages no extra time either, because the throttle's delay
runs from the START of the previous fetch:

| Stat | Means |
|---|---|
| `linkedin/description_box_late` | it came - explanation 2, and the wait is the fix |
| `linkedin/description_box_absent` | it never came - explanation 1, a second container is needed |

Pages that stay without a box are kept for reading by hand when
`LINKEDIN_DUMP_DIR` is set (open pages only, `LINKEDIN_DUMP_MAX`, default 10).

Also added, counted and not acted on: `linkedin/closed_marker_beside_apply`,
for a page that carries "No longer accepting applications" AND an apply
control. The marker is searched for in the whole body, which also holds other
postings; 3 of 12 closures were hand-checked on 28.08.2026 and none had an
apply control, so this has not been seen - the stat is there so a false close
would name its page.

### 4. Verdicts waited for dozens of pages before being read

Found during the 15.09.2026 full run, from the log rather than a stat: 57 job
pages had been downloaded before `parse_check` ran once, and the first 22
verdicts then arrived in one burst, seven minutes in, with nothing yet
written. `openings.WRITE_EVERY` (25) exists so a run cut short keeps what it
paid for; here it could only act on whatever burst happened to arrive. The
28.08.2026 log shows the same shape - its last 13 verdicts all printed in the
same second as the close.

The mechanism, reproduced with a toy spider and no network: requests yielded
from a callback (the checker yields its probes from the warm-up's callback)
while a downloader middleware blocks the reactor (PlaywrightMiddleware does,
on purpose). Scrapy stops fetching to run callbacks only when the responses
waiting for them add up to `SCRAPER_SLOT_MAX_ACTIVE_SIZE`, 5 MB by default.

| 60 requests from a callback | first callback after | then |
|---|---|---|
| 5 MB, 380 kB pages | 14 fetches | 12 at a time |
| 5 MB, 10 kB pages | **all 60** | - |
| 1 byte, either size | 2 fetches | one per fetch |

`linkedin_check` now sets it to 1: each page is read before the next is
fetched. With `CONCURRENT_REQUESTS` 1 and a serial middleware this costs no
throughput, and the process holds one page instead of dozens. The run below
still had the 5 MB default - it had started before this was found.

Not applied to any other spider. Indeed's checker shows bursts of 3-12 in its
15.09.2026 log, so it has the same shape at a smaller size; that is for the
Indeed session to decide.

### The full run, 15.09.2026 - what the four changes above did

`python main.py --spider linkedin_cards` on an empty LinkedIn board (the table
was reset on 14.09), with 1-3 in place and 4 not yet. Log:
`backups/linkedin-fullrun-20260915.log`. Session from 26.08, still valid.

| Step | Result |
|---|---|
| crawl | 365s, 26 requests, all 200; 585 items / 555 unique; `filter-staj` 210 (ended on page 9 with 10 cards), `filter-parttime` 375 (**hit MAX_PAGES 15**, page still full) |
| dedupe | 20 LinkedIn rows linked to Indeed/kariyer.net copies |
| check | **535 postings in 4244s (7.9s each)**, 536 responses all 200, no wall, no block: 534 open, 0 closed, 1 inconclusive |
| descriptions | **533 of 535** - against 23 of 40 on 09.09.2026 |
| classify | 145s, 533 rows: **it 67, general_program 22, other 444** |

The description question is settled: `linkedin/description_box_late` 532,
`linkedin/description_box_absent` 2. **Explanation 2 was the right one** - the
box was on its way on essentially every page, 0.3-1.0s after the apply button,
and the old wait read the page before it arrived. There is no second
container to find. The one open page kept without a box
(`jobs/view/4456638271`) is 79 kB against the usual several hundred and is
still to be read.

`linkedin/closed_marker_beside_apply` never fired. Nothing closed, which is
what a board crawled an hour earlier should say.

**What the run says next, in order:** 444 of 533 (83%) classified `other` -
the two routes filter by internship / part-time and Greater Istanbul and by
nothing else, and one employer ("Fengkai Group Co., Limited", remote "PHD Peer
Review Need – …" postings) is 145 rows on its own. 101 rows are region-wide
remote ("EMEA", "Middle East"), not Türkiye. That, and `filter-parttime`
running out of pages, are the same question and come first.

## Is the search too wide? - set up 15.09.2026, measured on the next run

Harman's question after the run above: "çok fazla ilan geliyor, arama
filtresini çok geniş koyuyor olabiliriz". Counted from the database, no
request to the site:

| Stored as | Rows | it | general_program | other | Visible |
|---|---|---|---|---|---|
| internship (`f_E=1`) | 167 | 35 | 21 | 111 | 34% |
| part-time (`f_JT=P`) | 366 | 32 | 1 | 333 | **9%** |

| Where the noise comes from | Rows | of which `it` |
|---|---|---|
| "Fengkai Group Co., Limited" - remote "PHD Peer Review Need – ..." | 145 | 3 |
| MANGO - "VENDEDOR/A", "CAJERO/A" | 35 | 0 |
| region-wide remote: "EMEA", "Middle East", "MENA" | 101 | 7 |

Neither route filters by FIELD - the first axis `docs/sites/README.md` asks
every site to apply at the source. The part-time route is where it costs:
almost no company-wide programmes (1) to protect, and a 91% `other` rate.

### What breadth actually costs, and what it does not

Less than it looks. An `other` row is set `is_active=False` and
`pipelines.py` does not reactivate it when a later crawl sees it again, so
`linkedin_check` visits it once and never again. The repeated cost is per
NEW posting: a card read, one detail page on the burner account, one
classifier call. And `MAX_PAGES` on a most-recent-first search crawled daily
only loses postings when more than 15 pages of them are new in a day - the 15.09
run hit it because the board was empty. Both claims are measured on the next
run rather than trusted:

  * every search page now logs `N card(s), K kept, S already stored`
    (`linkedin/cards_already_stored`), read against the rows that existed
    before the run. Pages that come back fully stored are depth paying for
    postings we have.
  * `filter-parttime-it` (`f_JT=P&f_F=it,eng`) runs BESIDE `filter-parttime`
    for that run. At close the spider logs, over postings an earlier run had
    already classified, how many of the wide route's `it` and `other` the
    narrow route also found (`linkedin/trial/*`).

**How to read it.** Narrow keeps nearly all the known `it` and drops most of
the `other`: the wide route goes, and the question of depth mostly goes with
it. Narrow misses real `it` postings: LinkedIn's job function is employer
free-text like every other filter this project has measured, and the narrow
route goes instead. The internship route is not part of the trial - 21 of its
56 visible rows are company-wide programmes whose job function says nothing
about software.

**Decisions left to Harman, not taken in code:** whether region-wide remote
postings ("EMEA", "Middle East") belong on an Istanbul board at all - the
26.08 entry kept "Türkiye (Remote)" on purpose but never saw these - and
whether one employer posting 145 near-identical remote reviews is noise to
drop by name. Both piles may shrink on their own under a field filter; the
trial run will say.

## A short page is the last page - 15.09.2026

`filter-staj` returned 8 pages of exactly 25 cards, then page 9 with 10 - and
asked for page 10 anyway, which came back empty after `page_actions` had
waited its full 15s for cards (`linkedin/no_cards_after_wait: 1`,
`linkedin/no_cards: 1`). Every page with results on it in that run - 8 of one
route, 15 of the other - had exactly 25.

A page with fewer than `PAGE_SIZE` cards now ends its route
(`linkedin/short_last_page`). The count is of `li[data-occludable-job-id]`
shells, not rendered cards, so a page that failed to render still counts 25 and
is not mistaken for an ending. Saves one request and ~15s per route that runs
out before `MAX_PAGES`.

## The two pages the 15.09 check could not finish - read by hand the same day

Both from the saved run, no request.

**id=1510, "Sales Manager", SolutionMall, MENA (Remote) - open, no
description.** Kept as `backups/linkedin-pages-20260915/1510-no-description.html`
(79 kB, where a described page is several hundred). The header had rendered -
title, "Remote · Part-time", `Easy Apply to this job` - and the lower column
had not: no "About the job", no `expandable-text-box`, and the only
`data-testid` near it is `lazy-column`. `actions=5.2s` in the phase log is the
extra wait running out. So it is a slow render, not a second container, and at
1 page in 535 not worth a longer wait for every posting. The row is active and
unclassified, so the next check visits it again.

**id=1042, "Beta Tester - Turkiye", AppTestify, Türkiye (Remote) - the one
inconclusive verdict.** Its description DID arrive (1666 characters, classified
`it`), so the page rendered; it carried none of the three apply labels and no
closing words. That is most likely a fourth way LinkedIn lets you apply. The
page was not kept - the dump only took open pages then - so no selector is
written for it. `LINKEDIN_DUMP_DIR` now also keeps a rendered page that comes
back neither open nor closed, as `<id>-unknown.html`, and the row's
`checked_at` is still empty, so it is first in line on the next run.

## 16.09.2026 - the session was refused, and the run did not stop

The verification run for the 15.09 changes was started at 12:40 and got no
further than its first request: the feed redirected to
`/uas/login?session_redirect=…/feed/`. Log: `backups/linkedin-run-20260916.log`.

What is known, and nothing more:

  * `linkedin-storage-state.json` (saved 26.08.2026) still dates `li_at` to
    22.02.2027, so the cookie did not run out - LinkedIn stopped accepting it.
  * The day before, the same session made ~560 requests without a single
    refusal: 26 search pages, then **535 job pages in 71 minutes**. That is
    the largest volume this account has carried, and the first run after it
    was refused. It is the obvious suspect and it is not proven - an expired
    session and a restricted account look identical from here, and nobody
    has looked at the account yet.
  * Whether the account still signs in is the next thing to find out, by
    hand, in a browser - not by the crawler.

**The run carried on after the wall**, and that part is a fault of ours. The
middleware recognised the redirect as a sign-in wall and the spider said so -
then asked for all three searches, which came back HTTP 200, 29 kB, no cards,
and were not counted as walls because LinkedIn served them in place. The run
was stopped by hand after 4 requests. Left alone, `main.py` would have
started `linkedin_check`, which would have asked the same way for every
stored posting.

`LinkedinCardsSpider.on_warmup` now closes the spider
(`linkedin_session_refused`) when the warm-up lands on a sign-in page or the
middleware has already seen one. LinkedIn has no anonymous mode, so nothing
after that can succeed. `linkedin_check` inherits it: a dead session now
costs each spider one request. Checked without the network - a toy crawl
whose warm-up callback raises `CloseSpider` fetched the warm-up and nothing
else, `finish_reason` = `linkedin_session_refused`.

**Before the next run, if the account still works:** the check volume is a
question of its own. 535 detail pages in one sitting was set by the
15.09 decision that the time limit must not stop the checker while LinkedIn
answers. If that volume is what got the session refused, a cap
(`OPENINGS_MAX_PER_SITE`) or a slower `DOWNLOAD_DELAY` for the checker is the
lever. That is a decision for Harman, and one run is not evidence either way.

### 16.09.2026, later - the account is restricted

Harman opened the burner account by hand. The password was accepted, and
LinkedIn showed **"Hesabınızın erişimi geçici olarak kısıtlanmıştır"**: access
restricted for "potential unauthorized access or other activities that do not
follow our policies", to be restored only after a government-issued ID is
submitted. So the refusal at 12:40 was not an expired session. It was this.

The timeline, as far as this project can see it:

| Date | LinkedIn traffic on this account | Outcome |
|---|---|---|
| 26.08 - 10.09 | crawls of ~30 search pages; checks held to at most ~140 job pages by the 1200s limit (83 on 28.08) | never refused |
| 15.09 | 26 search pages, then **535 job pages in 71 minutes** | every response 200 |
| 16.09 12:40 | first request of the next run | sign-in wall; account restricted |

One day, one account and one step change in volume do not prove the cause.
But they are the only change on record, and they match what the 27.07.2026
entry at the top of this file warned about. The size of that change was
decided on 15.09 ("the ceiling must not stop the checker while LinkedIn is
answering"). That decision was sound for Indeed and kariyer.net, where a
refusal costs an address a few hours. On LinkedIn a refusal costs the
account, and it arrived a day later, not as a 429 during the run. The
checker never saw a refusal it could stop on.

**What that means for any next account:** DOMAIN_BLOCK_BUDGET cannot protect
it, because the penalty is not delivered during the run. The volume has to be
capped in advance: `OPENINGS_MAX_PER_SITE` for the checker, and a daily
number of job pages written down before the first run, not discovered after
the last one.

### Parked, and what the next account needs first - 16.09.2026

`linkedin_cards` is in `PARKED_SPIDERS`, and `run_checks()` now skips a
parked site's checker in a full run as well. Parking the crawl alone would
still have started `linkedin_check` on every full run. Harman is opening a
new burner account.

**Before its first run, in this order:**

1. `python -m tools.save_session linkedin` with the new account.
2. **Decide a daily job-page budget**, and set it
   (`OPENINGS_MAX_PER_SITE`). The old account ran seven active days at up to
   ~140 job pages without trouble and was restricted after one day of 535.
   Nothing better than that is known.
3. First run by name (`python main.py --spider linkedin_cards`), with the
   15.09 checklist: the f_F trial, `short_last_page`,
   `SCRAPER_SLOT_MAX_ACTIVE_SIZE=1`, `<id>-unknown.html`.
4. Un-park only after that run.

**Two ideas raised the same day to cut the job pages themselves.** Neither is
measured - there was no account left to measure with:

* **The description from the search page.** A search page shows the
  selected posting's description in its right-hand pane, so at least one is
  in the DOM. Whether all 25 are there has not been checked - 26.08 recorded
  the card as title/company/location only. A 25-card page averaged 1.68 MB
  on 15.09 against 1.39 MB for a page with no cards; that difference fits
  both answers. First thing to look at with the new account: save one search
  page and grep it for a description known from the database.
* **"Still open" without opening the posting.** Checked against the
  09.09.2026 backup, no request: none of the 33 postings the checker closed
  was ever seen in a search again, so a closed posting does drop out of
  search. The converse is unproven: 33 postings checked open on 02.09 were
  absent from the 09.09 crawl, and a route stopped at MAX_PAGES cannot tell
  "closed" from "deeper than we looked". If it is used at all, absence may
  only count on a route that reached its real last page
  (`short_last_page`), in two consecutive runs, while a small daily sample
  of job pages keeps measuring the rule against the checker.

### 16.09.2026, afternoon - the second burner was restricted on creation

Harman opened a new burner account the same afternoon. It showed the same
"Access to your account has been temporarily restricted … submit a
government-issued ID" page **as soon as it was opened, before this project
had sent it a single request**. `linkedin-storage-state.json` was still the
26.08 file, and no crawl or `save_session` was running.

That changes what the first restriction can be blamed on:

* **The 15.09 volume is no longer the only suspect.** The second account
  did no automated work at all. Whatever flagged it came from the account's
  creation or from its surroundings: the same home address and the same
  machine as an account restricted a few hours earlier. That is the obvious
  connection. LinkedIn does not say, so it stays a suspicion.
* It does not clear the checker either. The first account could have been
  flagged for its volume, and the second for its link to the first.

**What this project does about it: nothing more against LinkedIn.** A third
account made to get past the restriction would be working around LinkedIn's
enforcement, not around a technical fault. On this address the evidence says
it would be caught just as fast. The owner's own account may already be
associated with this address. LinkedIn stays parked, and the 27.07.2026 entry
at the top of this file is, in effect, back in force.

If LinkedIn postings are wanted on the board later, the candidate that needs
no burner is LinkedIn's own job-alert email: a saved search on a real
account, delivered to a real inbox, read from there. Not measured and not
designed yet - a note, not a plan.

## Out of the flow - 16.09.2026

Harman's decision the same day: LinkedIn leaves the scraping flow, because
it puts his own account at risk. This is stronger than parking, which keeps a
spider runnable with `--spider`:

| Where | What changed |
|---|---|
| `main.py` | `linkedin_cards` is in none of `SPIDERS`, `PARKED_SPIDERS`, `CHECKER_FOR`, `SITE_LABELS`; `--spider linkedin_cards` is an unknown spider |
| `LinkedinCardsSpider.__init__` (and so `linkedin_check`) | raises before anything is sent unless `LINKEDIN_ENABLED=1` - the door `scrapy crawl linkedin_check` from an old note would otherwise still open |
| `run_checks()` | a parked site's checker is skipped in a full run (general, kept from the parking step) |

Kept on purpose: the two spiders, their tests, `SPIDER_TIMEOUTS["linkedin_check"]`
and this file. Every measurement here is still true of LinkedIn's pages, and
the job-alert idea above, if it is ever pursued, would reuse the card and
description knowledge.

**The 555 LinkedIn rows already in the database were deleted the same
day** (Harman's call - no checker would ever look at them again, so the 89 on
the board would have stayed listed after they closed). Before that, a full
export: `backups/job_posts-20260916-151233.csv`, 912 rows, the only remaining
copy of those postings.

One side effect: 17 Indeed rows were marked as duplicates of LinkedIn rows.
Their `duplicate_of` was cleared in the same transaction, before the delete.
They are unclassified and have no description, so the board keeps them
hidden until `indeed_check` reaches them - they joined Indeed's queue (262
rows). `pipeline.dedupe_jobs --dry-run` afterwards: 0 newly marked, 0 cleared.
