# kariyer.net - what happens, in order

A walk through one run, from `main.py` to a classified row. This file answers
"what does it do"; [kariyernet.md](kariyernet.md) answers "why does it do it
that way", and it is the one to read when something breaks - every number
here came from a measurement written up there.

Written 12.09.2026, against `spiders/kariyernet_cards.py` and
`spiders/kariyernet_check.py`.

---

## The shape of it

```
main.py
  │
  ├─ kariyernet_cards ──────────────── ~25 min, 4 + 46 requests
  │    2 listing pages  → cards → items
  │    46 posting pages → descriptions
  │
  ├─ dedupe · notify                   (seconds)
  │
  ├─ 30 min site cool-off              SITE_COOLDOWN_S
  │
  ├─ kariyernet_check ──────────────── ~23 min, 1 request per open posting
  │    still open?  +  description
  │
  └─ classify                          rows that have a description
```

Every request in both spiders goes out through **a real Chromium with a real
window, in a browser context that has never been to the site.** Both halves
are load bearing; see "Two gates, not one" in kariyernet.md.

---

## 1. Starting up

| Step | Where |
|---|---|
| `main.py` runs the spider as its own subprocess, with a 2-hour ceiling | `SPIDER_TIMEOUTS` |
| The spider picks the browser identity that describes THIS machine | `browser_profile_name = "chrome-151-linux"` |
| `PlaywrightMiddleware` launches a windowed Chromium - and refuses to launch a headless one | `NEEDS_A_WINDOW = True` |
| No warm-up navigation: the listing page is the first thing a visitor loads anyway | `warmup_url = None` |

If there is no `DISPLAY` and no `WAYLAND_DISPLAY`, the run stops here with the
`xvfb-run` command it needs. It does not fall back to headless, because
headless returns a 9 kB block page and zero cards - a failure shaped exactly
like a dead selector.

## 2. Asking for the listings

`api_requests()` yields page 1 of **two searches**:

```
parttime  /is-ilanlari/istanbul-part+time?ct=34,82&wa=...&tpst=4
staj      /is-ilanlari/stajyer?ct=34,82&wa=...
```

Two rather than one because the site classifies its own postings badly in two
different directions - see "two routes, never one" in [README.md](README.md).
`_url_for_page()` adds `&cp=N` for pagination without disturbing the filters.

Every request carries `fresh_context: True` from `default_meta()`, so this
applies to listing pages too.

## 3. Fetching one page

For each request, in order:

1. **Block budget** - `BlockDetectionMiddleware.process_request` drops the
   request outright if this domain has already refused 3 times this run
2. **Throttle** - `SlotThrottle` waits out `DOWNLOAD_DELAY` (20s, randomised
   to 10-30s). This lives in the middleware because a transport that answers
   from `process_request` never reaches the downloader's slot, so Scrapy's own
   delay silently stops applying
3. **A new browser context** - its own cookie jar, thrown away afterwards
4. **A new page**, then `goto(url, wait_until="domcontentloaded")`
5. **Challenge check** - a PerimeterX press-and-hold page is recognised and
   not waited on, because it never clears itself
6. **`page_actions`** - the spider's hook, see below
7. **`content()`** - the HTML, handed back to Scrapy as a normal Response
8. **Page and context closed.** Closing the context is the point: the cookies
   it just earned must not reach the next request

`ResidentialProxyMiddleware` and `CurlImpersonateMiddleware` are both in the
settings and neither runs here - the first self-disables on `PROXY_MODE=off`,
and the second is only reached by spiders that ask for it.

### `page_actions` - two different pages, two different readings

| Page | What happens | Why |
|---|---|---|
| listing (`search_key` in meta) | scroll to the bottom in 900px steps, then back to the top | the logos are lazily loaded; without this 25 of 40 cards carry a 1x1 transparent SVG instead of a logo |
| posting | wait 4 seconds | see kariyernet.md - this was added for a reason that turned out to be wrong and is kept because every passing measurement used it |

The scroll stops when the page has been at the bottom twice, or at
`SCROLL_BUDGET_S` (20s), which it says out loud.

## 4. Reading the cards

`parse_listing()` walks every `<div data-test="ad-card">`. The card carries
its data as HTML attributes - **matched in lowercase**, because parsers
normalise `workTypeId` to `worktypeid` and the CamelCase form matches nothing
silently.

**Kept if any of these:**

- `worktypeid` is `P` (part-time) or `S` (internship), or
- the title or `positionname` matches the internship vocabulary in
  `job_filters.looks_like_internship()`, or
- the card came from the `staj` search, whose every result is an internship
  by definition

A card with no link is skipped and counted: `url` is the upsert key, so a
posting without one cannot be stored at all.

`note_discovery()` records which of the two searches found each posting. The
spider prints the tally when it closes, and the number that matters is **sole
finder**: how many postings would have been lost without that route.

## 5. One card becomes one row

`_item_from_card()` builds the item from the attributes and the rendered text:

| Field | Source | Note |
|---|---|---|
| `job_title` | `[data-test="ad-card-title"]` text | falls back to the `positionname` attribute, which is more generic |
| `company` | the logo `<img>`'s `alt` | the visible subtitle is sometimes ellipsised |
| `company_logo_url` | the same `<img>`'s `src` | `logo_url()` drops the lazy-load placeholder; no `N/A` fallback, so a missing logo is an absent field |
| `location` | `[data-test="location"]` text | **not** the `cityname` attribute, which reports "Adana" for a nationwide posting |
| `job_type` | `worktypetext` | overridden to `Staj` for anything the internship search found, whatever the employer coded |
| `url` | `a[data-test="ad-card-item"]` href | the upsert key |

## 6. The description, at most once

```
every card                        → yielded here, always
  ... description already stored  → and no posting-page request
  ... description NULL or "N/A"   → and the posting page is fetched
```

`described_urls()` reads, once per run, which of this site's urls already hold
a real description. A database it cannot read returns an empty set, so every
posting looks new and every page is fetched - the old behaviour, and the safe
direction to fail in.

The card is stored **whatever happens to the posting page**. When the page is
refused, the posting is still on the board with its title, company, city, work
type, logo and link; only the description is late. `parse_detail()` adds it
and yields the item again, and `pipelines.py` only overwrites the column with
a real value, so the late arrival wins and nothing blanks it in between.

## 7. Pagination

`next_page_allowed()` asks for the next page unless:

- the page came back empty - the search is exhausted (the normal ending), or
- every posting on it was already seen this run - the index has started
  repeating itself, which is how a paginated site answers an out-of-range
  page, or
- `MAX_PAGES` (200) - a circuit breaker that logs an ERROR, not a target

Card identity for that comparison is the posting link, via `record_key()`.

## 8. When it is refused

Once this site starts refusing, it does not stop, and no delay reaches past it
- the limit is a count rather than a rate. So:

| Setting | Value | Effect |
|---|---|---|
| `RETRY_TIMES` | 1 | one retry covers a blip, and stops |
| `DOMAIN_BLOCK_BUDGET` | 3 | the run ends after three refusals |
| `BLOCK_COOLDOWNS_ALLOWED` | 0 | no waiting - it was measured twice and bought nothing |

The run ends early and **keeps everything it collected**. That is survivable
because the crawl drains its own queue over a few nights:

| Night | Requests | Outcome |
|---|---|---|
| 1 | 4 listing + 46 detail | ~36 get through, ~24 with a description |
| 2 | 4 listing + ~22 detail | ~26 requests - under the wall |
| 3+ | 4 listing + that day's new postings | ~8 requests |

## 9. Closing

`closed()` prints the discovery report and writes one JSON line to
`SPIDER_STATS_FILE` - items, requests, response statuses, routes, and whether
a block cut the run short. `main.py` reads that instead of grepping the log,
because a blocked spider exits 0 and the exit code cannot tell the difference.

## 10. The checker, half an hour later

`kariyernet_check` subclasses the crawl spider, so the window, the fresh
context per request and the delay all come along. Only the urls and the
question differ.

| Step | Detail |
|---|---|
| `main.py` waits out `SITE_COOLDOWN_S` | 30 min since the crawl finished. Zero wait in a full run, where the other three crawls already provide the gap |
| `load_open_postings()` | this site's rows that are active, not duplicates, not already closed - ordered `checked_at ASC NULLS FIRST` |
| `probe_request()` | one navigation per posting, `fresh_context: True` |
| `verdict()` | an apply button means OPEN; a description container with no apply button means CLOSED; anything else is UNKNOWN and writes nothing - not even `checked_at`, so a site that has started refusing us cannot hide behind a fresh timestamp |
| `description()` | read from the same container the verdict already selected, so it costs no extra request |
| writes | every 25 verdicts (`WRITE_EVERY`), because a checker killed by its timeout would otherwise lose everything it had paid for |

`--spider kariyernet_cards` runs **only** this checker, not all four.

## 11. Classify, last

`classify_jobs` reads rows with `job_category IS NULL`, skipping duplicates,
closed postings, **and rows with no description** - those wait rather than
being judged by their title, because `job_category` is written once and a
title-only guess would outlive the description arriving the next night. They
are visible on the dashboard the whole time, just unsorted, and
`report_waiting()` prints the pile per site every run.

---

## Reading a run's log

| Line | Means |
|---|---|
| `Starting Playwright (headless=False, ...)` | the window is there. `headless=True` here for this spider is a bug, not a setting |
| `N posting(s) already have a description and will not be re-opened tonight` | `described_urls()` loaded; N should grow over the first few nights |
| `[staj] page 1: 35 card(s), 35 part-time/internship` | cards seen / cards kept |
| `throttle: waiting Ns more` | the 20s delay, saying so |
| `Served a press-and-hold block page` | the wall. Check the window first if this is on request one |
| `www.kariyer.net has refused N requests in a row` | only appears if `BLOCK_COOLDOWNS_ALLOWED` is raised - it is 0 |
| `www.kariyer.net has refused N requests this run - stopping` | the budget, working as intended |
| `Discovery report - N unique posting(s) via 2 route(s)` | the closing tally; read the "sole finder" numbers |

## Counters worth watching

| Stat | Healthy |
|---|---|
| `cards/seen`, `cards/wanted` | ~46 kept of ~46 on both searches |
| `detail/fetched` vs `detail/already_described` | the first shrinks over the first few nights, the second grows |
| `logo/found` vs `logo/missing` | 41 of 46 on 12.09.2026, up from 14 of 40 before the scroll |
| `detail/no_description` | 0. Anything else is a selector question, not a block |
| `blocks/detected` | 0 on a short night; 3 means the run stopped at the wall and kept what it had |
| `playwright/fresh_contexts` | one per request. If this is far below the request count, the flag has been dropped somewhere |
