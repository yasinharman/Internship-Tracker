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
