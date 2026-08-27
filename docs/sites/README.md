# Site notes

One file per job board. Every site is scraped differently, and the ids in the
spiders (`FIELD_FILTER = ["25"]`) are meaningless without a record of what they
mean and where they came from. That record is these files.

| Site | Status | Spider | Notes |
|---|---|---|---|
| [kariyer.net](kariyernet.md) | running | `kariyernet_cards` | the JSON listing behind the card grid |
| [techcareer.net](techcareer.md) | running | `techcareer_api` | belongs to kariyer.net, carries the same ads |
| [Indeed](indeed.md) | running, un-parked 30.07.2026 | `indeed_cards` | the hard one: TLS fingerprint, sign-in wall, Playwright |
| [LinkedIn](linkedin.md) | running since 26.08.2026 | `linkedin_cards` | burner-account session, no anonymous mode at all |
| [Jooble](jooble.md) | out of scope | — | an aggregator: its postings arrive as duplicates |

What happens to a posting after it is stored - dedupe, notify, classify and
the still-open check - is in [../pipeline.md](../pipeline.md).

---

## The rule every spider follows: two routes, never one

Both sites migrated so far classify their own postings badly, in different
ways. Filtering once, precisely, loses postings every time:

| Failure | Real example |
|---|---|
| Employer mis-tags the posting | 22 of 26 kariyer.net internships coded `D`/`F`, never `S` |
| The site's own filter is incomplete | "Bilgisayar Mühendisliği Stajyeri" absent from techcareer's `typeOfWork=2,4` |
| Our vocabulary has gaps | "Career Experıence Drıve - IT" is an internship with neither "staj" nor "intern" in the title |
| Wrong filter axis | sector = Bilişim hid every developer role at a bank or hospital |
| The index reorders between requests | "E-Ticaret Stajyeri" dropped out of one full crawl |

No single filter survives all five. So: **every posting must be reachable by
at least two independent routes**, typically the site's own category or
search page plus a broader scan matched on the title. One route's blind spot
is the other's ordinary result. Overlap is free - the pipeline upserts on url.

Shared title vocabulary lives in `scraper/job_filters.py`; add new
phrasings there and every spider gets them.

### Measuring the leak

`BaseApiSpider.note_discovery()` records which route found each posting, and
the spider logs a report when it closes. The number that matters is **sole
finder**: how many postings would have been lost without that route.

Real output:

```
kariyer.net   28 unique via 2 routes
  staj        found  26  |  sole finder of 22
  parttime    found   6  |  sole finder of 2

techcareer     2 unique via 2 routes
  scan        found   2  |  sole finder of 1
  typed       found   1  |  sole finder of 0
```

One run of this says what took two manual audits to discover. Read it as:

* **sole finder > 0** - that route is carrying the crawl and the others are
  leaking. Never drop it.
* **sole finder = 0 for weeks** - that route is redundant and is costing
  requests for nothing.

Because the crawl runs daily and never deletes, a posting missed today is
picked up tomorrow. Index instability delays discovery; it does not lose it.

---

## The search we are reproducing on every site

Three axes, all applied at the source so we download only what is wanted:

| Axis | Value | Notes |
|---|---|---|
| **Field** | software / IT | Use the site's own category, not a keyword search. A keyword misses adjacent stacks and also matches description text. Include neighbouring categories if the board splits software from data / devops / QA. |
| **Employment type** | internship + part-time | |
| **Location** | Istanbul only | Decided 27.07.2026. Excludes remote roles filed under another city - boards tag remote inconsistently, so widening this is the first thing to try if results look thin. |

Then paginate to exhaustion (`next_page_allowed()` in `api_spider.py` handles
the stop conditions). The intersection of these three is small enough that
there is no need for a page limit.

Fill in a section as each site is migrated.

---
