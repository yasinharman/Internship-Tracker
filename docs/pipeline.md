# After the crawl

What happens to a posting once it is in `job_posts`. `main.py` runs these in
order and the order is load-bearing - see `run_post_crawl()` there.

    crawl  ->  dedupe  ->  notify  ->  check  ->  classify

| Step | Code | What it decides |
|---|---|---|
| dedupe | `pipeline/dedupe_jobs.py` | is this the same job as one on another board? |
| notify | `pipeline/notify_watchlist.py` | does a watched company appear? (no measurements to record - the rule is a case-insensitive substring match, see `config/watched_companies.yml`) |
| check | `scraper/spiders/*_check.py` | is it still on offer? (and, since 09.09.2026, what does it say? the description is in the same response) |
| classify | `pipeline/classify_jobs.py` | is this our field? |

**check moved ahead of classify on 09.09.2026** and this line did not follow
it until 10.09. `run_post_crawl()` is the authority; when the two disagree,
the code is right and this table is stale.

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
| `scraper/classifier.py` | Schema, prompt, the call to the local model |
| `tools/eval_classifier.py` | Measures a model against frozen labels, writes nothing |
| `pipeline/classify_jobs.py` | Reads `job_category IS NULL`, writes results |
| `tools/migrate.py` | Adds the three columns (idempotent) |

Runs from `main.py` after the crawl, and **last of the four post-crawl steps
since 09.09.2026** - after the `*_check` spiders rather than before them. Two
consequences, both intended:

- A posting the checks just found closed is not classified at all
  (`closed_at IS NULL` in `load_unclassified`). It stays NULL forever and
  shows as `sınıflandırılmadı` behind the "Kapananlar" toggle. That is the
  price of not paying for a dead posting; one `UPDATE` puts it back in the
  queue.
- **A posting with no description yet WAITS** - added 12.09.2026, and it is
  the other half of moving the checks first. A row whose description had not
  arrived was being classified from its title, and `job_category` is written
  once, so the guess outlived the description that turned up the next night.
  On kariyer.net's first night that was roughly 16 of 40 postings. The row is visible while
  it waits, just unsorted, and `report_waiting()` prints the pile per site on
  every run - a handful is the overnight lag, a number that grows week on week
  means a site has stopped giving up its descriptions.
- The checks write `job_description` on their way past, so the classifier
  reads the posting's own text instead of guessing from the title. See the
  reversal in `main.py run_post_crawl()`.

A failure there does **not** fail the scheduled task: the postings are already
stored. They stay off the dashboard until a later run sorts them - since
16.09.2026 unclassified rows are hidden (`api/queries.py`, `CLASSIFIED`) - and
the dashboard shows how many are waiting.

### Choosing the model

> **The premise under this section changed on 09.09.2026 and the numbers have
> not been re-measured.** Both of `gpt-5.4-nano`'s disqualifying errors below
> are title-reading errors, and the comparison was run on input that was
> almost entirely title-only: measured the same day, 32 of 993 rows carried a
> real description. Now that the checks collect descriptions, `--compare`
> should be run again on rows that have one before this table is trusted to
> still be the answer. **A first look on 17 rows, and the decision to wait for
> every site before the real comparison, are at the end of this section.**

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

#### First look with descriptions - 14.09.2026, 17 rows

The re-measurement the note at the top of this section asks for, on the first
rows that had one: 17 kariyer.net postings from the second night's crawl,
every one with a description, before they were written.

    gpt-5.4-nano   it: 6   general_program: 3   other: 8
    gpt-5.4-mini   it: 8   general_program: 2   other: 7
    agreed on 15 of 17

Both disagreements went mini's way, judged by reading the postings:

| Posting | nano | mini | What the description says |
|---|---|---|---|
| BT İş Analist Stajyeri (Enterprise) | `general_program` | `it` | "Bilgi Teknolojileri ekibimize", "yazılım geliştirme ve test süreçlerinde" |
| Bilgi Teknolojileri Lise Stajyeri (MSC) | **`other`** | `it` | "Meslek Lisesi Bilgisayar, yazılım ve türevi bölümler" |

**This weakens the hope rather than confirming it.** Neither is a
title-reading error - both titles say IT outright, and nano had the
description - and the second one HIDES an IT posting, on the reasoning that a
high-school internship is not in the field.

It does not settle anything either. Seventeen rows is two disagreements, and
kariyer.net titles are the plain ones: the case descriptions should rescue is
LinkedIn's bare "Intern", which is where nano failed on 28.07.2026 and which
this sample does not contain.

#### DECIDED 14.09.2026: compare again once every site is back

The comparison waits until all four spiders are producing clean rows. On
14.09 the table was cut down to kariyer.net's 41 rows - the other 774 came
from a single run on the morning of 10.09 with the old spiders and were
deleted (`backups/job_posts-20260914-100439.csv` holds them) - so there is
nothing else to measure on yet, and 41 plain-titled rows would test nano on
the easiest exam there is.

How to run it when the time comes, so the answer means something:

1. **One variable.** Hold `DESCRIPTION_CHARS` where it is for the model
   comparison. Raising it is a separate question, asked afterwards - it
   truncated 14 of 24 kariyer.net descriptions, and LinkedIn's average was
   3 383 characters, but it also raises every call's input tokens, so it
   pulls against a cheaper model and the two cannot be read apart if they
   move together.
2. **Rows that have a description**, from every site, and enough of them -
   130 was the size of the 28.07 study.
3. **Judge the disagreements by reading them**, as above, rather than trusting
   either model as the reference.
4. **Count wrongly hidden postings separately.** `it` -> `general_program`
   still shows on the board; `it` -> `other` does not. The rule at the top of
   this section is that a wrong exclusion costs a real opportunity, so the
   decision rule is: **switch to nano only if it wrongly hides roughly none.**

**One change is needed first.** `--compare` reads `load_unclassified()`, so it
sees only rows nobody has classified - and by then every row with a
description will have been. It needs a read-only mode that runs over
already-classified rows, writes nothing and touches no label. Clearing
`job_category` to make rows comparable would throw away the stored verdicts.
Built 21.09.2026 as `tools/eval_classifier.py`, below.

#### A local model on the 70 labelled rows - 21.09.2026

Classification is moving to a model on this machine (the drawing is
`docs/mimari-yerel-llm.html`). The switch is small: the local server speaks
OpenAI's API, so the same SDK call works, and the request also has to carry
the two settings below. So the open question is which model, and this is
where it is measured.

`tools/eval_classifier.py` freezes the labelled rows into
`backups/eval-labelled.json` once, runs one model over them and compares with
the stored `job_category`. It writes nothing to the database, and it only
talks to a server on this machine: `.env` holds the real OpenAI key, and a
measurement must not be able to become a bill.

**Held the same for every model:**

- **Server and card:** Ollama 0.34.2 on the RTX 4070 Ti (12 GB). The model is
  100% on the GPU, context is 4096, and requests go one at a time.
- **Prompt and cut:** the prompt and `DESCRIPTION_CHARS = 1500` are imported
  from `scraper/classifier.py`, not copied. Every result file records the
  prompt's hash (`c6960530ee25c081`).
- **`temperature=0` and `reasoning_effort="none"`, sent to every model.** Left
  unset, each model uses its own defaults, and Qwen3.5 and Gemma 4 reason
  before answering. That would be two variables hidden behind the model name.
  Reasoning was measured off: 0 characters of it came back.
- **The model's other shipped defaults are left alone.** qwen3.5 ships
  `presence_penalty 1.5`, Qwen's own setting for non-reasoning use. gemma4
  ships none. Their `top_k` and `top_p` do nothing at temperature 0.
- **Both models are at the same quantization,** Q4_K_M.
- **The reference** is `gpt-5.4-mini`'s stored verdicts from 12.09-16.09. The
  70 rows split 41 kariyer.net, 28 Indeed and 1 techcareer, and 25 `it`, 5
  `general_program`, 40 `other`. Every row has its description.

| Model | Download / in VRAM | it | general_program | other | Agreed | Wrongly hidden | Newly shown | it <-> program | Per posting | 70 rows |
|---|---|---|---|---|---|---|---|---|---|---|
| `qwen3.5:9b` | 6.6 / 5.5 GB | 19 | 14 | 37 | 57/70 | 3, **0 on reading** | 6 | 4 | 1.0 s median, 1.3 s p95 | 71 s |
| **`gemma4:12b`** | 7.6 / 8.1 GB | 26 | 7 | 37 | **61/70** | 3, **0 on reading** | 6 | **0** | 1.2 s median, 1.6-1.7 s p95 | 88-92 s |

**The category is nearly stable; the wording of the reason is not.** Each
model was run twice for the table, and 0 of 70 categories changed.

gemma4 then ran five more times over the same rows: the concurrency test
twice, and the production path three times. In the last two, borderline
postings moved:

| Posting | Categories seen | On the board |
|---|---|---|
| Data & Adops Intern | `it`, `general_program` | shown either way |
| Metot Stajyeri | `other` in five runs, `general_program` in two | hidden or shown |

So temperature 0 does not make the local model fully repeatable. It keeps
the moves to one or two postings in 70, where `gpt-5.4-mini` moved several.
No run hid a posting that another run called `it`.

The reason sentence moves more: across the two table runs, 37 of 70 were
word-for-word identical for gemma4, and 65 of 70 for qwen3.5. The likely cause
is tiny numerical differences in how the server reuses a cached prompt; that
is not verified. Only the stored verdict counts, as before, and a posting is
classified once.

**The three "wrongly hidden" are the reference's mistakes, read one by one.**
Both models hid the same three, each on its own. All three are Baykar's 2027
spring internships, and each names another engineering field outright:

| Posting | What the text the model saw says |
|---|---|
| Silah Sistemleri - Tasarım, Test, Malzeme | mechanical, structural and hydraulic design teams |
| Motor Teknolojileri - Analiz | CFD, FEA, thermal and fatigue analysis of gas-turbine engines |
| Uçuş Bilimleri | asks for Uçak, Uzay, Makine, Kontrol ve Otomasyon or Mekatronik students |

`gpt-5.4-mini` called them `it` on "simulation and modelling". The prompt says
`other` is for a posting that names another line of work, and these do.

So neither model wrongly hides anything, and both pass the decision rule.
What separates them is the noise and the `it` / `general_program` line.

**The two models split on 11 postings** (`--diff`). Read one by one:

- **gemma4 is right on five:**
  - **HR Wıntern (L'Oréal):** qwen's reason says it is an HR role, but it
    chose `general_program`. The prompt gives "İnsan Kaynakları Stajyeri" as
    an `other` example, so that is an instruction-following miss.
  - **İş Geliştirme and Teknik Müşteri Hizmetleri:** both name another field.
    qwen shows them, gemma4 does not.
  - **Stajyer (FarklıFikir Bilişim):** the description asks for knowledge of
    "Yazılım ve web uygulamaları". gemma4 says `it`, qwen `general_program`.
  - **CED Commercial Excellence:** it accepts Computer Engineering and MIS
    students. gemma4 says `it`, qwen `general_program`.
- **qwen is right on one:** the "Stajyer Mühendis" at COLIN'S asks for
  Endüstri Mühendisliği students. qwen hides it; gemma4 shows it as
  `general_program`.
- **Five are either way:**
  - the two Assistant Product Manager postings: `it` or `general_program`,
    shown both ways;
  - Data & Adops Intern;
  - UI/UX Tasarım, which asks for frontend coding;
  - "Müzik Öğretmeni - Bilişim Öğretmeni" (part-time), which gemma4 shows.

Both lean towards showing. That is the direction the prompt asks for when in
doubt, and it costs a row of noise, not a lost posting. qwen's leaning is the
cruder of the two. It moves four `it` postings to `general_program`, two of
which ask for software knowledge or Computer Engineering students outright.
It also shows postings that name HR, business development or customer
service.

**DECIDED 21.09.2026: `gemma4:12b`, the owner's call.** It is 0.2 s slower
per posting and takes 2.6 GB more VRAM, and neither matters for a nightly
batch. The difference is four or five postings in 70, so it is a lean, not a
verdict. If the local board shows a class of postings being misjudged, the
same tool measures qwen3.5:9b again on the same frozen rows.

**Nightly load:** 1.0-1.2 s per posting, so 300 postings take about 5-6
minutes, inside `CLASSIFY_TIMEOUT = 900`.

**`CLASSIFY_CONCURRENCY` stays at 8.** Ollama runs one request at a time
(`OLLAMA_NUM_PARALLEL = 1`) and queues the rest, so sending 8 at once changes
nothing but the wait. Measured on gemma4:12b, 70 rows:

| Concurrency | Wall time | Per-request wait, median / max | Categories changed |
|---|---|---|---|
| 8 | 91 s | 10.4 s / 12.4 s | 0 |
| 1 | 91 s | 1.3 s / 2.2 s | 0 |

The longest wait is far inside the SDK's own 600 s timeout.

**How it runs.** `scraper/classifier.py` builds its own client for the local
server, `CLASSIFIER_URL` (Ollama's address by default), with a throwaway key.
It does not use `OPENAI_BASE_URL`, which would have sent the real key from an
older `.env` along with every posting. It sends `LOCAL_REQUEST`, the same dict
the measuring tool imports. The model is `CLASSIFIER_MODEL`, and gemma4:12b
when that is unset.

**The OpenAI and Anthropic paths were removed on 21.09.2026, at the owner's
call.** They existed so the provider could be chosen by measurement, and it has
been. The file's own rule is that no seam is kept "in case we switch", so the
code has no `LLM_PROVIDER` any more and needs no API key. git history has both
paths if an API model is to be compared again. Local models are compared with
`tools/eval_classifier.py` against the frozen labels, or with `--compare`.

Checked end to end on 21.09.2026: `classify_all()` from
`pipeline/classify_jobs.py`, with 8 threads and nothing written, sorted all 70
frozen rows in 91-97 s. Three runs, the last two with `.env` pointing at
gemma4:12b: 0, 2 and 1 categories differed from the measured run, all of them
the two borderline postings above.

**If Ollama is not running,** every posting fails with a connection error. It
stays unclassified and off the board, and the next run picks it up again,
the same way a failed API call used to. A scheduled run therefore needs
`ollama.service` up; the install enables it at boot.

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

**That is still true, but the board is now bigger when the checks run
(09.09.2026).** The checks moved ahead of classify, so this crawl's `other`
postings have not been hidden yet and are visited once before they are. The
trade was made knowingly: the checks were already downloading each posting's
page, and the description in that page is worth more to the classifier than
the requests it costs to fetch the not-yet-hidden rows.

**A second question, answered from the same response.** Each checker now also
reads the description off the page it downloaded for the verdict
(`OpeningCheckMixin.description`). It costs no request - `indeed_check.py`
had already noticed it fetches the exact endpoint the description was refused
on, "the same endpoint for a different question". All four sites, measured
09.09.2026, each recorded in its own `docs/sites/` file:

| Site | Where | Note |
|---|---|---|
| techcareer | `pageProps.jobDetail.content.description` | the payload the verdict just parsed |
| kariyer.net | `[data-test="qualifications-and-job-description"]` | the container the verdict already selects |
| LinkedIn | `[data-testid="expandable-text-box"]` | the element `DETAIL_MARKERS` already waits for |
| Indeed | `"sanitizedJobDescription"` in the `/viewjob` body | once in ~290 kB; the crawl's record has only `snippet` |

The description is written whatever the verdict says. Whether a posting is
still open and what the job IS are different questions, and a probe that could
not answer the first may well have answered the second - measured on Indeed
the same day, an `inconclusive` verdict still yielded a full description.

**Verdicts are written in batches, not once at the end.** `main.py` runs each
checker as a subprocess with `CHECK_TIMEOUT` and `subprocess.run(timeout=)`
*kills* it, so `closed()` never ran and a cut-short run silently discarded
every verdict it had paid for. `OPENINGS_WRITE_EVERY` (default 25) bounds the
loss to one batch, and `checked_at ASC NULLS FIRST` means the next run resumes
where this one stopped.

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

---

## Should the flow be per-site? - considered 10.09.2026, mostly already true

**The proposal.** Crawl every site, then run each site's check and classify
as a pair, so the sequence reads:

    kariyernet-crawl, techcareer-crawl, indeed-crawl, linkedin-crawl,
    kariyernet-check, kariyernet-classify,
    techcareer-check, techcareer-classify,
    indeed-check,     indeed-classify,
    linkedin-check,   linkedin-classify

Two reasons were given for it, and **both describe things the pipeline
already does.** Writing that down so nobody spends an afternoon rediscovering
it - the ordering looks like an obvious improvement until you check.

### Reason 1: "don't check a site while it is still warm from being crawled"

Already how it works, and the gap is not small. `run_post_crawl()` runs
**after every crawl spider has finished**, so kariyer.net's check is
separated from kariyer.net's crawl by the techcareer, Indeed and LinkedIn
crawls plus dedupe and notify. Measured durations put that at well over an
hour - Indeed alone is ~41 minutes and LinkedIn ~65.

The proposed order does not lengthen that gap for kariyer.net at all; its
check sits in the same position either way. It lengthens LinkedIn's slightly,
by the three classify runs that would now precede it. That is not worth
restructuring for.

**Where the concern is REAL is `--spider`**, and this is a genuine bug rather
than a matter of taste:

```bash
python main.py --spider kariyernet_cards      # crawls ONE site...
```

...and then calls `run_post_crawl()`, which runs **all four checkers**. So
`kariyernet_check` starts moments after `kariyernet_cards` finished, with no
gap at all - exactly the back-to-back pattern the proposal was trying to
avoid - and three other sites are probed for a crawl that never touched them.
This is also the command `PLAN-*.md` tells you to run when verifying one
site, so it is the path a person actually takes.

**FIXED 12.09.2026**, in two parts, because only the first half is about
`--spider`:

* `CHECKER_FOR` maps each crawl spider to its own checker, and `run_checks()`
  derives the list from the spiders that actually ran. `--spider X` probes X
  and nobody else.
* `SITE_COOLDOWN_S` makes the gap explicit instead of incidental. Before a
  site's checker starts, if that site's own crawl finished less than the
  cooldown ago, `main.py` waits out the remainder. In a full run the wait is
  zero - the other three crawls already provide an hour and a half - so this
  costs nothing there and is the whole thing on a single-site run.
  kariyer.net is the only entry, at 30 minutes, and that number is a guess:
  the site is measured to refuse its crawl around the 35th request, but
  nothing has measured how long it wants between bursts.

The second part is what stops a future reordering of `run_post_crawl()` from
removing the gap silently. Covered by `tests/test_check_scheduling.py`.

For a verification crawl that should trigger none of this, `--skip-classify`
skips the post-crawl steps entirely, checkers included - the flag name
undersells it.

### Reason 2: "don't pay to classify a posting that has closed"

Already true since 09.09.2026. `classify_jobs.load_unclassified()` filters

```python
.filter(JobPost.job_category.is_(None))     # not already sorted
.filter(JobPost.duplicate_of.is_(None))     # not a copy from another board
.filter(JobPost.closed_at.is_(None))        # not found closed by the checks
```

and the checks run before classify precisely so that third line has something
to act on. A posting the checks just found gone is never sent to the LLM
today.

### The part of the proposal that is genuinely new, and why it is not taken

Splitting classify into four per-site runs. It costs:

* **new code that does not exist** - `pipeline/classify_jobs.py` has no
  `--site` and no notion of one
* **efficiency** - the classifier fans out over rows with 8 concurrent calls
  and finishes 150 postings in under a minute. Four smaller batches are four
  process starts and less fan-out for the same per-row price. **The LLM bill
  does not change**: it is charged per posting, not per run.
* **a correctness trap** - the proposed sequence omits `dedupe`. It must stay
  ahead of *every* classify, or the copy of a job that also appeared on
  another board gets classified and paid for. That is what
  `duplicate_of IS NULL` above relies on.

What it buys is that one site's classify failure cannot take the others down,
and that the first site's results land sooner. On a job that runs at midnight,
neither is worth the three costs.

### One part to NOT do: deleting closed postings

The proposal describes "deleting each site's inactive postings from the db"
before classifying. Nothing here deletes rows and nothing should:

* `closed_at` is a **soft** flag. The dashboard shows those postings behind
  the "Kapananlar" toggle - deliberately, see `docs/dashboard.md`.
* A posting that has left a board **can never be fetched again**. The row is
  the only remaining copy, which is why `backups/job_posts-*.csv` is kept
  rather than tidied away.
* `job_posts.url` is the upsert key. Delete a closed posting and, if the site
  lists it again, the next crawl inserts it as new and **pays for classify a
  second time**. Deleting costs money here; it does not save it.

### The real problem underneath all of this

The proposal is circling something true: **a site is visited twice on the
same night** - once by the crawl and once by the checker. On kariyer.net,
which as of 10.09.2026 starts refusing after about ten pages
(`docs/sites/kariyernet.md`), that is ~46 crawl navigations plus one per
stored posting.

Reordering does not reduce that number. The only lever that does is
`OPENINGS_MAX_PER_SITE`, and **it is a worse trade than it looks**, for a
reason that is easy to miss: the checker is not only answering "is this still
open". For half the sites it is the only thing that ever reads the posting.

### WHERE A DESCRIPTION ACTUALLY COMES FROM - measured 10.09.2026

| Site | From the crawl | From the checker |
|---|---|---|
| kariyer.net | **the full text** - it fetches the posting page for every card it keeps; 630-2 537 chars measured | the same container again, so a refresh |
| techcareer.net | **the full text** - it is already in the Next.js payload the listing returns | a refresh |
| Indeed | the `snippet` only - a teaser sentence. `docs/sites/indeed.md` turned down a `/viewjob` per posting at ~75 requests a day | **the full text**, out of the `/viewjob` it fetches anyway |
| LinkedIn | **nothing.** `linkedin_cards` writes the literal `"N/A"` - there is no snippet on a card to take | **the only source there is** |

**UPDATED 21.09.2026 - the "From the crawl" column is history.** No cards
spider opens a posting page any more: kariyer.net's crawl dropped its detail
request and techcareer's builds the item from the list record, so both now
store `"N/A"` like Indeed and LinkedIn (`docs/sites/kariyernet.md`,
`docs/sites/techcareer.md`). The checker is the only source of a description
on every site. The paragraph below about kariyer.net is therefore no longer
true: a cap there now delays descriptions too, not just the freshness of
open/closed. `docs/activity-checks-plan.md` is where the cap is designed
with that in mind.

So a cap does completely different damage per site:

* on **kariyer.net** it is nearly free where descriptions are concerned - the
  crawl already stored the full text and the checker is only refreshing it.
  What a cap costs there is the freshness of open/closed, nothing else.
* on **LinkedIn** it is destructive. Cap the checker and the classifier goes
  back to deciding from the title, which is exactly the failure fixed on
  09.09.2026 - and LinkedIn is the largest set, 487 rows that day.

Descriptions are also what makes a cheaper classifier defensible at all: the
model comparison in "Choosing the model" above was run almost entirely on
titles, and both errors that disqualified `gpt-5.4-nano` were title-reading
errors. Starving the checker undoes the premise of ever re-running it.

**And the knob cannot tell the sites apart.** `MAX_PER_SITE` is read once at
module import in `scraper/openings.py` and applied to every checker, so
"limit kariyer.net but leave LinkedIn alone" is not expressible today. If a
cap is ever genuinely needed, make it per site first - `KARIYERNET_MAX_PER_SITE`
falling back to `OPENINGS_MAX_PER_SITE` - rather than reaching for the global
one and quietly paying for it on LinkedIn.

### What the cap does, for when it is needed

`LIMIT n` on that query, per checker run, ordered `checked_at ASC NULLS
FIRST`: never-checked rows first, then longest-ago. So the cap is fair rather
than arbitrary - with 100 rows and a cap of 25, every row is still checked,
just once every four nights instead of every night. Unset today (0 = no cap).

### Decision

Keep `crawl -> dedupe -> notify -> check -> classify`, with one classify run
for everything. `--spider` now runs only its own checker (done 12.09.2026). **Leave
`OPENINGS_MAX_PER_SITE` at 0** - kariyer.net's block problem is answered by
`BLOCK_COOLDOWN_S` (wait ten minutes, carry on) rather than by checking fewer
postings, and that answer costs no descriptions.

Revisit if any of these change:

* classify grows a `--site` flag for another reason, making the split free
* a site is measured to refuse its checker *because of* its own crawl an hour
  earlier - which would make the gap, not the volume, the thing to lengthen
* a checker still cannot finish after the cool-off - then make the cap per
  site, and cap the site whose crawl already carries the description
* the crawl set grows enough that one classify run stops finishing inside
  `CLASSIFY_TIMEOUT`
