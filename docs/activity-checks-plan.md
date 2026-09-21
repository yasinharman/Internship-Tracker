# Activity checks - the plan

`pipeline.md` records how the still-open check works **today**. This file is
the plan for what it should become, written 20.09.2026 after the Indeed run of
16.09 was refused halfway through its check queue.

It is a plan, not a measurement. Every number in it is quoted from a
measurement that lives somewhere else - `docs/sites/*.md`, `pipeline.md`, or
the database on the date given. Where a layer depends on something not yet
measured, the measurement that would settle it is named.

**Status: not built.** The decision of 20.09.2026 was to start with a simple
seven-day horizon instead (see "What is being done first"), and to come back
to these layers afterwards.

---

## What the check costs today

One request per posting, per run, for every row the board could show
(`scraper/openings.py:145-171`: `is_active`, not a duplicate, `closed_at`
empty). There is no cap: `OPENINGS_MAX_PER_SITE` is 0.

Measured walls, per site:

| Site | What happened | Date |
|---|---|---|
| Indeed | 403 after 145 requests in 49.5 min; 8 refusals in 2m15s spent the block budget; of 296 rows to check, 51 answered and **245 were never asked** | 16.09.2026, `docs/sites/indeed.md:539-618` |
| Indeed | previous run ended at 134 requests, killed by the clock rather than refused | 15.09.2026 |
| kariyer.net | the wall arrives at 34 requests at an 8s delay, 36 at 20s - two and a half times the spacing bought two requests | 10.09 and 12.09.2026, `kariyernet_cards.py:388-391` |
| LinkedIn | 535 job pages answered 200 with no wall; the account was restricted at the **next** run's first request | 15-16.09.2026, `docs/sites/linkedin.md:728-730` |

The LinkedIn row is the one that shapes the design: the penalty was not
delivered during the run, so an in-run block budget could not have caught it.
A request budget has to be decided before the run, not discovered during it.

Database on 20.09.2026, for scale:

| | |
|---|---|
| rows the checker would take | 278 |
| rows actually visible on the board | 30 |
| rows whose description is still the `N/A` placeholder | 249 (all Indeed) |
| rows classified so far | 70, of which 40 (57%) are `other` |

So more than eight out of ten checked postings are postings nobody will be
shown. That is the gap the layers below close.

---

## Layer 0 - a posting seen in the crawl needs no check

**Costs nothing. Ready to build.**

Presence in a search result proves the posting is open. Absence proves
nothing - measured 21.08.2026, only 14 of 36 stored kariyer.net postings
appeared in that day's searches (`pipeline.md:341-345`). The crawl already
stamps `last_seen_at` on every upsert.

`indeed_check.probe_query` (`indeed_check.py:50-71`, 16.09.2026) already skips
rows seen in a search in the last 12 hours. `kariyernet_check`,
`techcareer_check` and `linkedin_check` do not override `probe_query` at all
and take the whole open board every run. Giving them the same filter is the
cheapest change in this file.

## Layer 1 - where the listing is the site's own verdict, read it there

**Costs nothing. techcareer only.**

techcareer's list endpoint filters on `jobs[isCompleted]=false`, the same
field the detail JSON exposes as `head.isCompleted` and the same field the
verdict reads (`pipeline.md:320-330`). A posting in that list is open by the
site's own definition, and the payload states its page count, so the crawl can
enumerate the whole filtered set rather than guessing where it ends.

For this site - and only this site - "absent from two consecutive complete
scans" is close to the site's own answer, at zero request cost.

Checked on 20.09.2026 and **not available elsewhere**: kariyer.net's ad cards
carry `worktypeid`, `positionname`, `cityname`, `worktypetext` and no date or
status field; Indeed's `isJobExpired` lives in the `/viewjob` body, which is
the expensive request itself.

## Layer 2 - check the board, not the table

**The largest saving. Depends on classification being free.**

The rule until 09.09.2026 was "only the board is checked, not the table"
(`pipeline.md:283-287`). It was given up when the checks moved ahead of
classify, for a good reason: the description arrives on the same response as
the verdict, so a row has to be fetched before it can be classified and
hidden.

A local model removes that reason. Classification stops being something to
ration, so a posting can be classified from its card - title, company,
location - before any request is spent on it. The evidence that this works is
already in the repo: the 28.07.2026 model comparison ran on input that was
almost entirely title-only (32 of 993 rows carried a real description) and
`gpt-5.4-mini` still agreed with the flagship on 122 of 130
(`pipeline.md:163-180`).

The queue then has three tiers:

1. **No description, and the card classifies as `it` or `general_program`.**
   The request does double duty - description and verdict from one response
   (`openings.py:264-292`). Highest priority.
2. **On the board, description already stored.** Verification only.
3. **Classified `other` from the card.** Never queued. They are hidden from
   the board either way.

A card-only verdict must never *delete* or *close* a posting - it only orders
the queue. A wrong `other` then costs a delay, not a loss, and the posting is
classified again properly once its description arrives.

## Layer 3 - spend what is left by age, and retire rather than delete

**Bounds the recurring load, which is the only cost that grows.**

A per-site cap, below the measured wall, with the rotation `pipeline.md`
already describes (`LIMIT n`, `checked_at ASC NULLS FIRST`): with 100 rows and
a cap of 25 every row is still checked, just once every four runs. Note the
cap is read once at module import and applied to every site
(`openings.py:79`); it has to become per-site first -
`KARIYERNET_MAX_PER_SITE` falling back to `OPENINGS_MAX_PER_SITE` - exactly as
`pipeline.md:545-552` says.

On top of the rotation, a horizon by age:

| Age | Treatment |
|---|---|
| 0-7 days | Layer 0 is enough; do not spend a request |
| 7-21 days | in the rotation |
| 21+ days | asked once more, then **retired** from the rotation |

Retired means the row stops being queued and is shown as unverified (or moved
behind the board's "Kapananlar" toggle). It does not mean deleted.
`pipeline.md:488-500` gives the reason: `job_posts.url` is the upsert key, so
a deleted posting that the site lists again is inserted as new and **pays for
the expensive detail fetch and the classification a second time**. Deleting
does not save requests here, it spends them.

`closed_at` stays reversible whatever writes it: `pipelines.py` stamps
`last_seen_at` on every upsert and the next check clears `closed_at` on any
row seen more recently than it was closed (`pipeline.md:359-363`).

---

## The rule none of the layers may break

A blocked, redirected or unrecognised response writes **nothing** - not even
`checked_at` (`pipeline.md:347-357`). Stamping it would hide a site that has
started refusing us behind a fresh timestamp, and any layer that infers
"closed" from silence would turn one refused night into an empty board.

---

## What has to be measured before each layer is trusted

1. **Is absence a usable signal, per site?** After the next card crawl, take
   20 rows the crawl did not see and spend real check requests on them. 0-2
   open means the signal is usable behind a two-crawl threshold; 8 open means
   it is dead. 20 requests, inside any daily budget.
   Contradictory readings so far: 14 of 36 seen on 21.08.2026 with the old
   searches, against **24 of 24** kariyer.net postings from 12.09 reappearing
   in the 14.09 crawl (measured in the database on 20.09.2026). The searches
   were rewritten in between, so the old reading may simply be stale.
2. **Does a rested address recover in 12 hours?** Hold the per-run budget
   fixed and vary only the interval. Indeed's ceiling is ~145 requests in a
   day; the question is whether two runs of 50, twelve hours apart, are seen
   as one day's traffic or two.
3. **How often does a card-only verdict say `other` about a posting that
   belongs on the board?** Measurable for free against the 70 rows already
   classified with their descriptions. The threshold is the one already
   written down: switch only if it wrongly hides roughly none
   (`pipeline.md:244`).

---

## What is being done first, and why this file waits

Decided and built 20.09.2026: a seven-day horizon, with the layers above left
for later. The crawl moves to every three days and classification runs every
24 hours.

**It writes nothing.** No column, no flag, no migration, no new step. The rule
is `scraper/models.py:UNLISTED_AFTER_DAYS = 7` read in exactly two places:

| Where | Effect |
|---|---|
| `scraper/openings.py` `load_open_postings()` | a posting not seen for seven days is not queued, which is where the requests are saved |
| `api/queries.py` `listed()`, applied in `conditions()` | the same posting drops off the board, so the checker is not skipping a row a reader can still see |

Three decisions inside it, each one a way it could have gone wrong quietly:

* **A NULL `last_seen_at` does not hide anything.** It means the row predates
  the column, not that the posting is gone. Hiding on missing evidence is the
  direction `openings.py` refuses to fail in.
* **The horizon is applied with `OPEN`, not with `VISIBLE`.** Closed postings
  are old by definition, so a horizon over them would empty the "Kapananlar"
  toggle a week after every closure.
* **A posting that is neither closed nor still listed is in neither view.**
  That is the crude part, and it is what the layers above replace.

Reversing it is deleting two filters. A posting the crawl finds again gets a
fresh `last_seen_at` from `pipelines.py` and returns on its own - same row,
same id, no second payment for its description or its classification.

Guarded by `tests/test_seven_day_horizon.py` (6 tests).

### What it does to the live data

Measured 20.09.2026, the day it was written:

| Site | In the queue today | Under the rule | On the board today | Under the rule | Last seen |
|---|---|---|---|---|---|
| indeed.com | 258 | 258 | 10 | 10 | 16.09 |
| kariyernet.com | 19 | 19 | 19 | 19 | 14.09 |
| techcareer.net | 1 | 1 | 1 | 1 | 14.09 |

Nothing moves on the day it ships. It bites on **21.09.2026**: kariyer.net and
techcareer were last seen on the 14th, so unless a crawl runs first, the board
goes from 30 postings to 10 and the queue loses 20. That is the rule working,
not a bug - but it is a reason to crawl before then.

### Still open

Nothing schedules anything today. `main.py` is started by hand
(`README.md:97`), and the `--schedule` path that `docker-compose.yml` uses
runs `run_spiders` only - no dedupe, notify, checks or classify
(`main.py:800-819`). A three-day crawl and a daily classify are two schedules,
and neither exists yet.
