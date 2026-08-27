# After the crawl

What happens to a posting once it is in `job_posts`. `main.py` runs these in
order and the order is load-bearing - see `run_post_crawl()` there.

    crawl  ->  dedupe  ->  notify  ->  classify  ->  check

| Step | Code | What it decides |
|---|---|---|
| dedupe | `pipeline/dedupe_jobs.py` | is this the same job as one on another board? |
| notify | `pipeline/notify_watchlist.py` | does a watched company appear? (no measurements to record - the rule is a case-insensitive substring match, see `config/watched_companies.yml`) |
| classify | `pipeline/classify_jobs.py` | is this our field? |
| check | `scraper/spiders/*_check.py` | is it still on offer? |

Three of the four write a column of their own and none of them deletes a row,
so every verdict here is one UPDATE away from reversal. `scraper/models.py`
says which column belongs to which writer and why they are kept apart.

---

## The same job on two boards

Added 28.07.2026. techcareer.net **belongs to kariyer.net** and carries the
same ads, so one opening arrives under two urls. `url` is UNIQUE and correctly
so - the two pages really are different resources - which means two rows, and
the job appeared twice on the dashboard.

Measured on 146 real postings: **3 pairs**, and notably one of them was
kariyer.net + Indeed rather than the sister site, so this is not only a
techcareer artefact.

| Duplicate | Kept | Job |
|---|---|---|
| techcareer.net | kariyer.net | Bilgisayar Mühendisliği Stajyeri (THOTH) |
| techcareer.net | kariyer.net | Dijital Sistem Mimarı (Öznur & Partners) |
| indeed.com | kariyer.net | Supply Chain Finance Intern (PepsiCo) |

### The rule

Same normalised title **and** same normalised company **and different source
sites**. Normalisation is `pipelines.canonical` - the Turkish-aware
lowercasing that already exists because `"YARI ZAMANLI".lower()` produces a
dotless i.

The cross-site condition is the conservative half and it is deliberate. Two
ads with the same title from the same company on **one** board are usually two
real openings or that board's own repost, and the rule of this project is
never to lose a posting. There were zero same-site collisions in the measured
data, so the restriction costs nothing today and rules out a class of wrong
merges. Company names that differ between boards ("X A.Ş." vs "X") will not
match and the job stays listed twice - the safe direction to fail.

### How it is recorded

`job_posts.duplicate_of` points at the row this one duplicates; NULL means
"show this one". The oldest row wins, which is stable across runs.

It is **not** folded into `is_active`. That flag belongs to the classifier,
and a second writer would resurrect or hide rows behind its back - exactly the
bug that made `pipelines` bring excluded postings back to life. Two hides,
two owners, no interaction.

Nothing is deleted or merged. Both rows keep their own url, so no application
link is lost.

### Where it runs

`pipeline/dedupe_jobs.py`, from `main.py` **before** the classifier: a duplicate is
never sent to the LLM, which saves a call and removes the chance of the two
copies coming back with different verdicts. Re-runnable - a pairing that no
longer holds is cleared. `--dry-run` shows what would change.

To see the pairs:

```sql
select d.id, d.source_site, k.id as kept_id, k.source_site, d.job_title
from job_posts d join job_posts k on k.id = d.duplicate_of;
```

To undo one, clear the link - the next run re-evaluates it:

```sql
update job_posts set duplicate_of = null where id = <id>;
```

---

---

## LLM field classification

Added 28.07.2026. The spiders collect every Istanbul internship and part-time
posting; this layer decides which ones are worth showing.

### Why it is not a word list

The old `job_filters.is_other_field()` matched a 60-term regex and could not be
finished. Turkish inflection beats it: the list held `temizlik`, the posting
said **"Parttime Ofis Temizliği"**, and the possessive suffix turns *k* into
*ğ*, so the match is lost. The list was widened by hand twice and still leaked
9 out of 9 on a real 130-row database - Oyun Ablası, Bulaşıkçısı, Cam Silimi,
Diş Hekimi Asistanı, Gıda Mühendisi among them.

Adding more words fixes only the postings you have already seen. The LLM reads
the posting instead.

### The three categories

| Category | Meaning | Shown? |
|---|---|---|
| `it` | Software, IT, data, security, QA, DevOps, systems | yes |
| `general_program` | Company-wide internship, department not named yet | yes |
| `other` | Names a different line of work | no (`is_active=False`) |

`general_program` exists because "Intern" at UPS could still be software - the
employer has not said. The prompt's decisive rule: **when torn between `it` and
`general_program`, choose `general_program`.** A wrong exclusion costs a real
opportunity; a wrong inclusion costs one row of noise.

Nothing is deleted. `other` sets `is_active = False` and the row stays with the
model's reason beside it, visible in the dashboard's "Neden" column.

### Where it lives

| File | Role |
|---|---|
| `scraper/classifier.py` | Schema, prompt, one call per provider |
| `pipeline/classify_jobs.py` | Reads `job_category IS NULL`, writes results |
| `tools/migrate.py` | Adds the three columns (idempotent) |

Runs from `main.py` after the crawl. A failure there does **not** fail the
scheduled task: the postings are already stored, and unclassified rows stay
visible on the dashboard.

### Choosing the model

Decided by measurement, not by price list. `pipeline/classify_jobs.py --compare` runs
the same postings through several models and prints only the disagreements.
Result on the 130 real rows (28.07.2026):

| Model | it | general_program | other | agreed with flagship |
|---|---|---|---|---|
| gpt-5.4-nano | 24 | 17 | 89 | 118/130 |
| **gpt-5.4-mini** | 27 | 12 | 91 | **122/130** |
| gpt-5.6-sol (ceiling) | 27 | 10 | 93 | - |

`gpt-5.4-nano` is cheaper and was rejected anyway: it put
**"Career Experıence Drıve - IT (Servıce&Operatıon)"** - an internship with IT
in its title - into `other`, and did the same to **"Intern" at UPS**, which is
written into its own system prompt as the canonical `general_program` example.
That is an instruction-following ceiling, not a prompt gap; no extra rule fixes
it reliably.

Verdicts are not deterministic. The same model on the same rows produced
27/12/91 in the comparison run and 29/13/88 when writing. Borderline postings
move between runs; the stored decision is what counts.

### When a decision looks wrong

Every `other` verdict is logged at INFO with title and reason, so a bad call is
visible in the run's output without a query. To audit:

```sql
select job_title, company, category_reason
from job_posts where job_category = 'other' order by created_at desc limit 30;
```

To undo an exclusion, clear the decision - the next run reclassifies it:

```sql
update job_posts set is_active = true, job_category = null where id = <id>;
```

If a whole class of postings is being misjudged, fix the examples in
`SYSTEM_PROMPT` rather than adding special cases, then re-run `--compare`
against the previous model to see what moved.

---

---

## Is the posting still open? - measured 21.08.2026

Nothing used to mark a posting as gone, so the board was an archive pretending
to be a noticeboard: three weeks of crawling piled up and the only way to find
out whether a job was still open was to click it. `*_check` spiders now ask
each site, once per crawl. See `scraper/openings.py`.

**Only the board is checked, not the table.** On 21.08.2026 the database held
297 postings but only **79** were visible (60 Indeed, 14 kariyer.net, 5
techcareer.net) - the other 211 are the classifier's `other` pile, hidden
either way. Checking those too would have quadrupled the cost to re-confirm
postings nobody will ever see.

### The signal, per site

Every one of these is the site's own answer, not a marker that happens to
correlate.

| Site | Signal | Measured on |
|---|---|---|
| kariyer.net | `[data-test="apply-button"]` is absent | 2 live (4487444 Eczacıbaşı, 4502891 BASF) had one each; 2 closed (4469047 PepsiCo, 4498903 TK Asansör) had none, and grew a "Benzer İlanlar" block instead |
| techcareer.net | `head.isCompleted` in the detail JSON | true + `endDate 2026-08-15` (past) vs false + `endDate 2026-08-26` (future). The list endpoint filters on the same field (`jobs[isCompleted]=false`) |
| Indeed | `"isJobExpired":true` in `window._initialData` | 12 stored postings: 9 false, 3 true, none ambiguous |

### Three things that look like signals and are not

1. **HTTP status.** kariyer.net returns **200 for a closed posting**. So does
   Indeed. A status-code check finds nothing at all.
2. **The words "expired" / "no longer" on an Indeed page.** They are on every
   page, expired or not - localisation entries in the bundle ("This job has
   expired on Indeed" -> "Indeed'de bu iş ilanının süresi doldu"), not state.
   `expiredJobMetadataModel` was `null` on all 12, live and expired alike.
3. **Absence from a search result.** Only 14 of 36 stored kariyer.net postings
   appeared in the live searches that day. The searches are narrow (İstanbul,
   nine departments) and the site's own ordering shifts between requests, so
   absence proves nothing. Presence proves the posting is open - which is the
   one direction `last_seen_at` is used in.

### Failing in the safe direction

`CLOSED` is written only on a positive signal from a page we recognise as a
real posting page. A block, a redirect, a timeout or an unfamiliar shape is
`UNKNOWN` and writes **nothing** - not even `checked_at`, because stamping it
would hide a site that has started refusing us behind a fresh timestamp.

This was tested by accident on 21.08.2026: kariyer.net began answering 403
mid-development, the block ladder walked all four handshakes, the domain block
budget stopped the run - and the checker reported `0 open, 0 closed, 0
inconclusive, 14 unanswered`. Not one posting was closed on the strength of a
blocked run.

A wrong verdict is self-healing. `pipelines.py` stamps `last_seen_at` on every
upsert, and the next check clears `closed_at` on any row whose `last_seen_at`
is newer than it - the crawl saw the posting in a search result after we
declared it gone, so we were wrong.

To undo one by hand, or to force a re-check:

```sql
update job_posts set closed_at = null, checked_at = null where id = <id>;
```

### The throttle bug this uncovered

Two middlewares fetch requests themselves and return the Response from
`process_request`: `CurlImpersonateMiddleware` (kariyer.net) and
`PlaywrightMiddleware` (Indeed). That short-circuits the downloader entirely -
`Downloader._enqueue_request` owns the per-domain slot and is never reached -
so **`DOWNLOAD_DELAY`, `CONCURRENT_REQUESTS_PER_DOMAIN` and AutoThrottle
silently stopped applying to those two spiders.**

Measured on `kariyernet_check`: 14 requests in 3.3s against a configured delay
of 4, which should have taken 56. The giveaway is in the stats -
`downloader/request_count` is missing entirely while
`downloader/response_count` is 14, because the counter lives in the method
that was skipped.

It hid because the crawl spiders make few requests. The checkers make one per
posting - 60 against Indeed, the site most likely to refuse us - which is
where it stopped being a technicality. `scraper/throttle.py` now
keeps the delay for both.
