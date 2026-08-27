# Internship Tracker

Finding an internship in Istanbul means opening the same four job boards every
day, running the same searches, and scrolling past the same hundred postings
that are not for you. This does that instead: it crawls the boards, keeps only
internships and part-time work, links the copies of a job that is advertised
twice, asks an LLM whether each posting is actually in your field, checks
whether the ones it already has are still open, and puts what survives on one
board you can read in a minute.

Four sources, all measured rather than guessed - the notes in
[`docs/sites/`](docs/sites/) record what each site does, on what date, and what
was tried before the current approach worked.

---

## What runs, and in what order

```
   crawl                dedupe           notify          classify         check
┌───────────┐      ┌───────────┐   ┌───────────┐   ┌───────────┐   ┌───────────┐
│ 4 spiders │ ───▶ │ same job  │──▶│  watched  │──▶│ our field │──▶│   still   │
│           │      │ elsewhere?│   │ employer? │   │  or not?  │   │   open?   │
└───────────┘      └───────────┘   └───────────┘   └───────────┘   └───────────┘
      │                   │              │               │               │
   job_posts        duplicate_of     notified_at    job_category      closed_at
```

`python main.py` runs all five and exits. The order is load-bearing and the
reasoning is in `run_post_crawl()`: linking duplicates before classifying means
the second copy of a job is never sent to the LLM, and checking last means the
set to check is the board rather than the whole archive.

Every step writes its own column and none of them deletes a row, so any verdict
is one `UPDATE` away from being undone. `scraper/models.py` is the only
description of the schema and says which writer owns which column.

## Where things are

| | |
|---|---|
| `main.py` | the entry point. Runs the crawl and everything after it. |
| `dev.sh` | the other entry point: serves the dashboard locally. |
| `scraper/` | the Scrapy project - spiders, the anti-blocking transport, the schema, the classifier. |
| `scraper/spiders/` | two per site: `*_cards` collects postings, `*_check` asks whether a stored one is still open. |
| `pipeline/` | what `main.py` runs after the crawl. Each is also runnable alone with `--dry-run`. |
| `tools/` | run by hand, never by `main.py`: capture a signed-in session, migrate the schema. |
| `api/` | FastAPI. Reads `job_posts`, writes nothing. |
| `web/` | the React dashboard it serves. |
| `config/` | `watched_companies.yml` - the employers worth a Telegram ping. |
| `docs/` | the measurements. Start at [`docs/README.md`](docs/README.md). |
| `tests/` | pure functions only: no site, no database, no session. |

## Running it

Python 3.13+ and Node 22+.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/playwright install chromium      # Indeed and LinkedIn need a browser
cp .env.example .env                        # then fill in DATABASE_URL at least
.venv/bin/python -m tools.migrate           # add any columns the schema gained
```

Then:

```bash
.venv/bin/python main.py                    # crawl everything, then sort it
.venv/bin/python main.py --spider indeed_cards
.venv/bin/python main.py --skip-classify    # crawl only, no LLM spend
./dev.sh                                    # the dashboard on :5173
./dev.sh --demo                             # ...against generated data instead
```

Each post-crawl step runs on its own and every one of them takes `--dry-run`:

```bash
.venv/bin/python -m pipeline.dedupe_jobs --dry-run
.venv/bin/python -m pipeline.notify_watchlist --dry-run
.venv/bin/python -m pipeline.classify_jobs --dry-run
```

Tests:

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```

## Where this actually runs

**Nowhere but a laptop.** `main.py` is started by hand; there is no scheduler
and no deployment. The Coolify application that used to run it was deleted on
17.08.2026 and only the Postgres it writes to stayed on the server, which is
why `DATABASE_URL` points off the machine. A push to `main` builds nothing.

The `Dockerfile` and `docker-compose.yml` still work and describe the target to
go back to - but going back needs a Chromium layer in the image and a
residential proxy first, because two of the four sites will not answer a
datacenter address. The header of `main.py` has the details.

## Two things worth knowing before changing anything

**Sessions are accounts.** `indeed-storage-state.json` and
`linkedin-storage-state.json` are a signed-in browser, not a config file. They
are gitignored and they stay that way. LinkedIn is crawled with a throwaway
account on purpose: automation is against its terms and it closes accounts that
get noticed.

**Measure, then write it down, then write the code.** A number in a spider -
`GEO_ID = "90010422"`, `f_E=1` - is unmaintainable without a record of where it
came from, and this repo is unusually strict about that: every rule in
`docs/sites/` carries the date it was measured and what was tried first.
Reversals are dated rather than deleted, so LinkedIn's file still opens with
the argument for dropping it.
