# The dashboard

Two pieces, one container:

- `api/` — FastAPI. Reads `job_posts` through `MultiwebsiteScraper/models.py`,
  which stays the only description of the schema. Writes nothing.
- `web/` — React (Vite, TypeScript, Tailwind v4). Builds to static files that
  FastAPI serves, so the browser talks to one origin and there is no CORS
  configuration between here and a host.

Neither piece is deployed anywhere: `./dev.sh` on a laptop is how it is
served, and the Coolify application was deleted on 17.08.2026 — only the
Postgres it reads stayed on the server (see `main.py`).

It replaced a Streamlit script (`app.py`, in git history) that connected to
Postgres from the page itself. A React front end cannot do that, which is why
the reading half became an HTTP API.

## Running it locally

Two processes, because Vite serves the front end in development and proxies
`/api` to uvicorn (see `web/vite.config.ts`):

```bash
uvicorn api.main:app --reload --port 8000    # reads DATABASE_URL from .env
cd web && npm install && npm run dev         # http://localhost:5173
```

Production is one process — `docker compose up --build dashboard`, or the
image's own `dashboard` build stage, both on port 8501.

## The rules the API enforces

These came from `app.py` and each one is load-bearing. They live in
`api/queries.py` with their reasoning; the short version:

1. Every query filters `is_active AND duplicate_of IS NULL`, and
   `closed_at IS NULL` unless `closed=1` was asked for. Three separate soft
   deletes with three separate owners (the classifier, dedupe, and the
   `*_check` spiders). None of them removes a row.
2. **`job_category IS NULL` rows are shown no matter what the field filter
   says.** If the LLM step fails, the postings are still real. A silently
   empty board is a worse failure than a few unsorted rows.
3. Default job types are Internship + Part-Time, but every type stays
   selectable — postings vanish from the sites within weeks and cannot be
   re-fetched, so the data is kept and the view is narrowed.
4. Default fields are `it` + `general_program`.
5. `category_reason` is shown to the reader. A classifier's verdict should be
   arguable, not silent.
6. `DATABASE_URL` is required with no fallback, and the error names `.env`,
   Coolify and the URL format.
7. A posting the checks found gone is hidden by default and revealed by
   `closed=1` — and **only** those. The classifier's `other` pile stays hidden
   either way. "Kapandı" and "başka alan" are different things to a reader,
   and one button that opened both would bury the handful of jobs that closed
   under two hundred that were never relevant.

## Endpoints

All of them accept `range` (`24h|7d|30d|all`), `sources`, `types`,
`categories` (comma-separated), `q`, and `closed` (`1` to include postings
that closed at their source; absent means the default board). The KPIs and the
chart follow `closed` too — a job that closed is not part of "Aktif İlan".

| Path | Returns |
|---|---|
| `/api/health` | never raises; distinguishes unconfigured from unreachable |
| `/api/meta` | filter options with counts, defaults, unclassified count, **closed count**, last posting |
| `/api/stats` | KPIs with period-over-period deltas, daily series, source split |
| `/api/jobs` | paginated postings |
| `/api/companies` | per-company totals, sources, watchlist flag |
| `/api/sources` | per-site health (ignores the source filter, on purpose) |
| `/api/watchlist` | `watched_companies.yml` and what each entry caught |

`/api/docs` serves the generated OpenAPI page.

## Where the design comes from

`docs/dashboard.html`, the "API Monitor" block (lines 430–811); the region
that matters is marked in `docs/Screenshot_20260819_203031.png`.

Read it before changing the visual language, and know that **it does not
render as its classes say**. Two `<style>` blocks after the Tailwind CDN
rewrite the page:

- `border-radius: 0 !important` on everything (line 18). Every card, badge,
  progress bar and status dot is a sharp rectangle. `web/src/index.css` gets
  the same result by zeroing Tailwind's radius scale.
- Every blue and emerald becomes a warm neutral (line 226 onward) — `#e7e5e4`
  for fills, `#cfc9c2` for accent text. Amber `#fbbf24` and red `#f87171` are
  untouched and are the only real hues in the markup.

The chart is the exception: it is a canvas, which CSS cannot reach into, so
its translucent blue bars and dashed purple line survive exactly as Chart.js
drew them. That is why `DailyFlowChart.tsx` keeps those colours rather than
matching the neutral palette.

## Postings that closed at their source

`MultiwebsiteScraper/openings.py` and the three `*_check` spiders decide this;
`docs/sites.md` has the per-site signal and the measurements behind it. What
matters on this side is the shape:

| Column | Owner | Meaning |
|---|---|---|
| `closed_at` | the `*_check` spiders | NULL = still on offer |
| `checked_at` | the `*_check` spiders | last CONCLUSIVE answer; NULL after a blocked probe, on purpose |
| `last_seen_at` | `pipelines.py` | the url was in a search result at this moment |

It is **not** `is_active`. That column already has two writers — the
classifier sets it False for another field, and `pipelines.py` sets it back to
True on every re-crawl — so a posting closed there would come back to life on
the next crawl. Same reasoning that kept `duplicate_of` separate.

On the board it is one toggle in the filter bar, "Kapananlar", carrying
`meta.closed_count` so the button says what it would reveal before it is
pressed. Closed rows appear mixed in with the open ones rather than in a
section of their own, so each carries a `kapandı` badge and a dimmed title.
