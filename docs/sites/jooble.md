# Jooble - OUT OF SCOPE

Dropped 27.07.2026, for two independent reasons.

**It is an aggregator.** Its postings are collected from kariyer.net and
similar boards, so they arrive under a jooble url - a second row for a job we
already hold, since the upsert key is the url. Duplicates in the dashboard,
nothing new in them.

**It is behind Cloudflare.** A plain request from a residential IP returns
**403** with a `challenges.cloudflare.com` interstitial; the old spider only
got through by paying for ScrapeOps. From the server's datacenter IP it would
be worse. So it would cost metered residential bandwidth and a challenge
solver to re-fetch what we already have.

This also removes the most fragile piece of the pipeline: `jooble` wrote
`urller.jsonl` and `detail_worker` read it back, a file handoff where one
spider failing left the other working from stale data.

**Open question, unresolved:** aggregators sometimes carry boards we do not
scrape ourselves - company career pages, smaller Turkish sites. The Cloudflare
block stopped that from being measured. If coverage ever looks thin, this is
worth revisiting, but the cost of getting in is high.

**Consequence worth remembering:** with jooble and LinkedIn out, and
techcareer.net being owned by kariyer.net and syndicating the same postings,
**Indeed is the only genuinely independent source left**. It is also the
hardest to scrape. That raises the stakes on getting it right.

`spiders/jooble.py` and its `detail_worker` companion have been deleted.

---

