# Site notes

One file per job board. Every site is scraped differently, and the ids in the
spiders (`FIELD_FILTER = ["25"]`) are meaningless without a record of what they
mean and where they came from. That record is these files.

| Site | Status | Spider | Notes |
|---|---|---|---|
| [kariyer.net](kariyernet.md) · [flow](kariyernet-flow.md) | running | `kariyernet_cards` | server-rendered cards, read by a windowed browser |
| [techcareer.net](techcareer.md) | running | `techcareer_api` | belongs to kariyer.net, carries the same ads |
| [Indeed](indeed.md) | running, un-parked 30.07.2026 | `indeed_cards` | the hard one: TLS fingerprint, sign-in wall, Playwright |
| [LinkedIn](linkedin.md) | **out of the flow since 16.09.2026** - two burner accounts restricted, the second before any request | `linkedin_cards` | burner-account session, no anonymous mode at all |
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

---

## How to work on a spider without wrecking the address - 10.09.2026

Written the day kariyer.net cost an afternoon and ended with the OWNER'S OWN
BROWSER being shown a robot check. Every item here is a mistake that was
actually made, in order, and they generalise to every site in this folder.

### 1. The control must differ from the spider in exactly ONE way

The expensive one. For four hours the evidence read:

| | listing | posting |
|---|---|---|
| plain `google-chrome`, nothing attached | served | **served** |
| Playwright → Chrome / Chromium / Firefox | served | refused |
| CDP attached to an ordinary Chrome | served | refused |

...and the obvious conclusion, "PerimeterX detects browser automation", was
drawn and half-believed. It was wrong. Every automated probe loaded the
LISTING first, because that is where the urls are; the plain-Chrome control
went straight to a posting. **Automation and "arrived carrying a cookie the
listing had set" changed together in every single row.** Separated, the
answer was the cookie: a context carrying a `_px3` earned elsewhere is
refused, a context carrying nothing is served, and the browser being driven
never mattered at all.

Before running a control, write down what it does step by step and diff it
against what the spider does. Anything on that diff that is not the variable
under test is a confound - and a control that is "obviously equivalent" is
exactly where one hides.

### 2. A negative result measured on a tired address means nothing

The first four browser probes of the day ALL failed, and nearly closed the
question of whether a window helped. They ran seconds after a curl_cffi 403
had put the address into a penalty window; the same four configurations
passed cleanly twenty minutes later. Rule: **interleave the arms** - A, B, A,
B in the same minute - so a recovery in the middle cannot be read as a
verdict. That is what eventually settled headless vs windowed, and it is
cheap.

### 3. Measuring is not free, and a refusal costs the same as a success

Roughly a hundred refused requests over one afternoon - four-variant probe
grids, a 14-request walk, two crawls - moved this address far enough down
PerimeterX's scale that **the user's own browsing hit the press-and-hold
challenge**. That is the real budget being spent, and nothing in the tooling
warns about it.

Count probes like requests. Space them. When the same question needs a fifth
round trip, stop and think instead of measuring again - and never leave a
crawl running against a site you are also probing by hand.

### 4. After a per-request fix, ask what a hundred of them look like

"One fresh browser context per request" is invisible for one request and
correct for the mechanism. At volume it is **34 brand-new visitors from one
address in five minutes**, which is its own pattern, and the run was refused
again after the 34th. Fixing the per-request signal traded it for a
per-session one.

### 5. If you cannot measure a benefit, do not add it

A persistent browser profile was added the same morning on the theory that a
returning visitor should look like one, with its own comment admitting it was
not the fix. By the afternoon it was the one thing carrying a poisoned
PerimeterX visitor id from run to run, and it had to be removed. "It should
help" is how state nobody understands accumulates in a crawler.

### 6. Operational traps that each cost time today

* **`pgrep -f <pattern>` matches its own shell.** A wait loop built on it
  never exits. `PLAN-*.md` warned about this and it still happened twice.
  Watch the log file, not the process list.
* **`... | tail -20` on a long-running probe hides everything until it
  exits.** Write to a file and read the file.
* **A persistent Playwright context dies with its last page.** Closing
  `ctx.pages[0]` takes the whole browser down: "Target page, context or
  browser has been closed" on the next call.
* **Kill by PID, never `pkill -f`.** Same self-match problem, with worse
  consequences - it has taken down a dev server here before.

### The checklist for the next spider

1. Write down the exact sequence the spider performs. The control performs
   the same sequence, changing one thing.
2. Interleave arms. Never draw a conclusion from a block of consecutive
   failures.
3. Budget the probes before starting, and stop when it is spent - the answer
   will still be there tomorrow, on a rested address.
4. Nothing is added to the transport unless a measurement says it helps.
5. When it works per request, work out what it looks like per hour.
