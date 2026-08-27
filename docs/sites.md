# Site notes

One section per job board. Every site is scraped differently, and the ids in
the spiders (`FIELD_FILTER = ["25"]`) are meaningless without a record of what
they mean and where they came from. That record is this file.

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

## Indeed search terms - measured 30.07.2026

Five field terms were added on top of the four broad ones, because depth was
not the constraint: pages 10-15 of `intern` returned the same six postings
repeatedly. First page of each new term, measured before adding them:

| Term | Records | Passed the filter |
|---|---|---|
| `yazılım stajyer` | 9 | 8 |
| `bilgisayar mühendisliği stajyer` | 3 | 3 |
| `software intern` | 15 | 8 |
| `developer intern` | 13 | 3 |
| `IT intern` | 15 | 14 |

46 unique postings across the five, 8 of them found by more than one term -
and they surface what the broad terms do not: *Yazılım Stajyeri*, *Long-Term
Full Stack Developer Intern*, *Working Student (Software Development
Engineer)*, *Cybersecurity Pre-Sales Stajyeri*. The run that used only broad
terms found 157 postings of which the classifier kept 14 as IT.

The small record counts also bound the cost: a narrow term runs out of
results long before `MAX_PAGES`, so nine searches do not mean nine times the
requests. Field terms are queued first - `DOMAIN_BLOCK_BUDGET` ends a run
partway through, and whatever is last is what gets lost.

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

## kariyer.net

**Status:** migrated - `spiders/kariyernet_cards.py`. The old DOM spider has
been deleted; it is in git history if ever needed.

**Investigated 27.07.2026:**

| | |
|---|---|
| Frontend | Nuxt.js, server-side rendered |
| Anti-bot | **PerimeterX** (`_pxhd` cookie set on every response) |
| Anonymous access | Yes - `GET /is-ilanlari?cp=2` with no cookies returns HTTP 200 and the full listing |
| Listings per page | 16 |
| Structured data | `application/ld+json` is only a BreadcrumbList - useless. Job data lives in `window.__NUXT__` as `positionName` / `positionId` |

### There is probably no JSON listing endpoint

Pagination links are plain anchors - `<a href="/is-ilanlari?cp=2">`, going up
to `cp=100`. The listing is server-rendered and paging is ordinary page
navigation, so no XHR carries the job data. A DevTools Network capture on this
site is dominated by GTM / Google Analytics / DoubleClick / Taboola and
PerimeterX sensor posts (263 requests on one page load); the job data is not
among them.

**Consequence: the filters live in the page URL**, not in an API call. To
learn a filter's parameter name, apply it in the UI and read the address bar.

### Working type taxonomy - CONFIRMED

Each ad card carries `workTypeId` / `workTypeText`. Codes verified against a
live page (38 `F`, 11 `P`, 1 `D`):

| Code | Meaning | Wanted |
|---|---|---|
| `F` | Tam zamanlı (full-time) | |
| `P` | Yarı zamanlı (part-time) | **yes** |
| `S` | Staj (internship) | **yes** |
| `D` | Dönemsel (seasonal) | |
| `R` | Serbest (freelance) | |
| `G` | Gönüllü (volunteer) | |

### Filter panel taxonomies

Three separate axes in the sidebar, from the filter markup
(`k-filter-checkbox-*`): **Departman**, **Pozisyon**, **Pozisyon Seviyesi**.
"Departman" is the field-level one we want for software/IT. Ad cards also
carry `sectorId` and `positionId`.

### Internships may live on a different host

The main menu links to **`ilkisim.kariyer.net`** ("İlk İşim ve Staj"). No
`workTypeId="S"` ad appeared on the sampled listing page, so internships are
either rare in the main index or served entirely from that subdomain. Needs
checking - internships are half the target.

**HTML page parameters** (known from the existing spider):

| Param | Meaning |
|---|---|
| `kw` | keyword |
| `ct` | city plate number (34 = Istanbul) |
| `cp` | current page |

### Ad card structure - CONFIRMED against a live page

Each posting is a `<div data-test="ad-card">` with the data as attributes.
**Attribute names must be matched in lowercase** - HTML parsers normalise
`workTypeId` to `worktypeid`, and the CamelCase form matches nothing silently.

| Field | Source |
|---|---|
| job_title | `[data-test="ad-card-title"]::text`, fallback `positionname` attr |
| company | `img[data-test="company-image"]::attr(alt)` (full name; the visible subtitle can be ellipsised) |
| location | `[data-test="location"]::text` - **not** the `cityname` attribute, see below |
| job_type | `worktypetext` attr, normalised by `pipelines.normalize_job_type` |
| url | `a[data-test="ad-card-item"]::attr(href)`, needs `urljoin` |
| work model | `workmodeltext` attr ("İş Yerinde" / remote) |

Other attributes present: `positionid`, `companyid`, `jobcode`, `sectorid`,
`sectorname`, `cityid`, `countryid`, `time`, `sponsor`, `jobstatus`.

**Multi-city trap:** a nationwide posting has
`locations="[object Object],[object Object],..."` and `cityname` holds only the
first entry, so an ad covering all 81 provinces reports `cityname="Adana"`.
The rendered text is honest - "İstanbul(Asya) +80 il daha" - so read the text
and keep the attribute only as a fallback. For single-city ads the two agree.

**Page size:** 50 cards per listing page.

### Filter by DEPARTMENT, not sector - the single biggest correction

Sector (`cs`) describes what the **company** does; department (`wa`) describes
what the **role** is. The first attempt filtered on sector = Bilişim and
produced mostly sales and office jobs at IT companies, while missing every
developer role at a bank, a hospital or a factory.

Switching axes changed the result completely:

| Filter | Postings kept | What they were |
|---|---|---|
| sector = Bilişim | 7 | 4 of them sales/office roles at IT firms |
| department list | 28 | includes Software Engineering Intern (GE), Bilgisayar Mühendisliği Stajyeri, Bilgi İşlem Stajyeri, Bilgi Teknolojileri Stajyeri |

### Search URLs - CONFIRMED

```
parttime: /is-ilanlari/istanbul-part+time?ct=34,82&wa=2,5,22,54,55,60,63,78,87&tpst=4
staj:     /is-ilanlari/stajyer?ct=34,82&wa=2,5,22,54,55,60,63,78,87
```

| Param | Meaning |
|---|---|
| `ct` | city plate numbers. **Istanbul is two codes** - 34 (European) and 82 (Asian). Using only 34 loses half the city. |
| `wa` | department list, chosen in the UI |
| `tpst` | working type; `4` = part-time |
| `cs` | sector code - **no longer used**. Mapped onto the `sectorid` card attribute. |
| `cp` | page number, added by the spider |

**`tpst` is coupled to the URL slug.** `/is-ilanlari?...&tpst=4` without the
matching `istanbul-part+time` slug returns zero cards, while the same query
with the slug returns 6. So the part-time URL is copied verbatim from the
address bar rather than assembled in code. To change the filters, redo the
search on the site and paste the new address.

`/istanbul-bilisim` is an SEO slug. Adding `cp=2` makes the site **301** to
`/istanbul-bilisim-2?...&cp=2`; Scrapy follows it, so there is no need to build
the slug. URL-encoding the comma (`ct=34%2C82`) works identically to the raw
form - both verified against the live site.

**Listings shift between requests:** consecutive fetches of page 1 and page 2
shared 5 of 53 postings, and they were not sponsored. Ordering simply moves as
new ads arrive. Harmless - the upsert is keyed on url - and `next_page_allowed`
still sees 48 new records, so pagination detection is unaffected.

### Employers mis-code internships - IMPORTANT

`worktypeid` alone is not a reliable internship filter. On the sampled page:

| | |
|---|---|
| `[P]` E-Ticaret Stajyeri | coded part-time |
| `[F]` Grafik Tasarım Stajyeri | coded **full-time** |

Half the internships on that page were coded `F`, because a full-time
internship really is full-time hours. So the spider keeps a card when
`worktypeid in {P,S}` **or** the title/positionname matches
`\b(staj\w*|intern(?:ship)?s?)\b` - the word boundary stops it firing on
"International".

Rescued postings also get `job_type` overridden to "Staj". Otherwise the
site's "Tam zamanlı" would normalise to Full-Time and the dashboard - which
defaults to Internship + Part-Time - would hide the very posting we went out
of our way to keep.

### Spider

`spiders/kariyernet_cards.py`. Pages the filtered search, applies the filter
above, and requests the detail page only for the survivors - so only the few
percent of postings we want cost a second request.

### Actual yield - the whole result set, crawled

All 8 pages fetched and run through the spider (not extrapolated):

| | |
|---|---|
| Cards read | 351 across 8 pages (page 7 partial, page 8 empty) |
| Unique postings | 316 - the site claims 334; the index shifts between requests |
| `F` full-time | 308 |
| `P` part-time | 5 |
| `D` / `R` | 2 / 1 |
| **`S` internship** | **0 - none at all** |
| **Spider keeps** | **6** (2 Internship + 4 Part-Time after relabelling) |

So the realistic daily yield for this search is a handful of postings, not
dozens. The site's own part-time filter shows roughly the same 5-6; the
spider's addition is the `F`-coded internships that no site filter reveals.

### `ilkisim.kariyer.net` is not a separate site - RESOLVED

It is a landing page with no ad cards, linking to `/is-ilanlari/stajyer` on
the main site. Internship listings are ordinary kariyer.net postings.

That slug takes the same parameters, so
`/is-ilanlari/stajyer?ct=34,82&cs=001000000` gives the IT internships in
Istanbul - 3 at the time of writing:

| Code | Title |
|---|---|
| `F` | Grafik Tasarım Stajyeri |
| `P` | E-Ticaret Stajyeri |
| `P` | Startpoint - Uzun Dönem Staj Programı |

**The decisive detail: none of them is coded `S`.** kariyer.net's own
internship search is a slug search over titles, not a working-type filter, and
no employer uses the `S` code - zero across 316 sampled postings. With the
department filter that search returns 26 internships, coded **D (19), P (4),
F (3)** - so a working-type filter of any kind is the wrong instrument.

### Trust the search, not the title

`INTERNSHIP_TITLE_RE` is a good signal but not sufficient: "Career Experıence
Drıve - IT (Servıce&Operatıons)" is a real internship with neither "staj" nor
"intern" in its title, and the regex would drop it.

So `INTERNSHIP_SEARCHES = {"staj"}`: everything the site's own internship
search returns is kept and labelled Internship, no questions asked. The site
classifies its own postings better than a regex can guess. The regex stays as
the fallback for the part-time search, where a P-coded "E-Ticaret Stajyeri"
should still come out as an internship.

### Yield - both searches, verified

**28 unique postings: 26 Internship + 2 Part-Time**, one page each, no
pagination needed. 22 of the internships were coded D or F by the employer -
i.e. the work-type code would have hidden them.

Real matches now surfacing that the sector filter had hidden: Software
Engineering Intern (GE Marmara Technology Center), Bilgisayar Mühendisliği
Stajyeri, Bilgi İşlem Stajyeri (Alliance Healthcare), Bilgi Teknolojileri
Stajyeri (TK Asansör), Career Experience Drive - IT (Eczacıbaşı).

Some noise comes with it - Hukuk Destek Stajyeri, PepsiCo's finance and
marketing interns - because the department selection is deliberately wide. At
this volume that is the right trade: a stray listing costs a glance, a missed
internship costs an opportunity.

### Bug found by crawling the full set

`next_page_allowed()` stopped at page 5 claiming the index was repeating,
while page 5 was entirely new postings. `BaseApiSpider.record_key()` fell back
to `repr()` for non-dict records, and parsel truncates a Selector's repr to
~40 characters, so unrelated cards collapsed onto the same key. A real crawl
would have silently lost pages 6-8.

Fixed in two places: the base class now serialises Selector-like objects
properly instead of using `repr()`, and the spider overrides `record_key()` to
use the posting link, which is a card's real identity.

**Still to capture:**
- [ ] Whether internships are on `ilkisim.kariyer.net` and what that site's structure is
- [ ] Date parameter (for the daily delta run)

**Extraction plan:** parse the server-rendered HTML. This is not a step
backwards from the JSON plan - the ad cards expose `data-test` attributes and
`workTypeId` / `sectorId` / `positionId`, which are far more stable than CSS
classes. The `window.__NUXT__` payload holds the same data if the markup ever
proves insufficient, but it is a minified IIFE rather than plain JSON, so it
needs a JS engine or a careful extractor.

---

## TechCareer

**Status:** migrated - `spiders/techcareer_api.py`. The old
The old Playwright-based spider has been deleted, and with it Playwright
itself: ~500MB and the slowest step of the Docker build are gone.

**Investigated 27.07.2026.** Owned by kariyer.net - job logos are served from
`cdn.kariyer.net` and postings are syndicated between the two sites, so
expect duplicates across `source_site`.

### Next.js, and where the endpoint hides

The site is Next.js (`__NEXT_DATA__`, served behind Google Frontend). There IS
a JSON endpoint, it just never appears in DevTools on a fresh page load: the
first view is server-rendered and
`/_next/data/<buildId>/tr/<route>.json` is only called on client-side
navigation. Same trap as kariyer.net, different framework.

```
list:   /_next/data/<buildId>/tr/jobs.json?jobs%5BisCompleted%5D=false&jobs%5Bpage%5D=1
detail: /_next/data/<buildId>/tr/jobs/detail/<slug>.json
```

Anonymous, no cookies, `application/json`. 22 kB filtered vs 58 kB for the
HTML page.

**`buildId` changes on every deployment** and cannot be hardcoded. The spider
loads `/jobs` once and reads it out of the `__NEXT_DATA__` script tag - this
is what `BaseApiSpider`'s warm-up hook is for.

### Filters

| Param | Meaning |
|---|---|
| `jobs[filters][typeOfWork]` | `2` = yarı zamanlı, `4` = stajyer. Verified against `/jobs/yari-zamanli` and `/jobs/stajyer`, one posting each. |
| `jobs[isCompleted]` | `false` = still open |
| `jobs[page]` | page number, `pageSize` 20 |

**A single value returns HTTP 500** - the endpoint wants a comma-separated
list, so always send `2,4`. Slug pages also exist: `/jobs/stajyer`,
`/jobs/yari-zamanli`, `/jobs/tam-zamanli`, `/jobs/uzaktan`, `/jobs/hibrit`,
`/jobs/freelance`, `/jobs/sozlesmeli`, `/jobs/deneyimli`, `/jobs/deneyimsiz`.

There is no location parameter in use; `location` is a plain string on each
record ("İstanbul / Türkiye", "İstanbul(Asya) / Türkiye"), so Istanbul is
filtered with a substring test in the spider.

### Why the spider makes two passes

The board is small - **194 postings, 94 in Istanbul, 10 pages** - so scanning
all of it is cheap. That matters, because the site's own filter is not enough:

| Source | Finds |
|---|---|
| `typeOfWork=2,4` | 9635 *Bilişim Teknolojileri Öğretmeni* (Muğla), 9589 |
| title scan over all 194 | **9612 *Bilgisayar Mühendisliği Stajyeri***, 9589 |

9612 is a computer-engineering internship in Istanbul that the site does not
tag as an internship - the same mis-tagging that hid 22 of 26 internships on
kariyer.net. And the one posting the site's filter adds is in Muğla. So both
passes run and the results merge; the pipeline upserts on url.

### Working type is NOT guessed here

Unlike kariyer.net, no override is needed: the detail endpoint reports
`head.typeOfWorks: ["Stajyer"]` accurately, and detail is fetched for the
handful of survivors anyway. `normalize_job_type` maps it straight through.

### Record fields

List: `id`, `title`, `slug`, `jobTitle`, `jobTitleEn`, `location`,
`workPlaces`, `owner.name`, `owner.logo`. **No working-type field** - which is
why the full scan has to match on the title.

Detail: `head.title`, `head.company.name`, `head.location`,
`head.typeOfWorks`, `head.startDate`/`endDate`, `head.workPlaces`,
`content.description` (HTML), `content.skills`.

### Yield

**2 postings**, both internships in Istanbul, one of them findable only by the
full scan. `workPlaces` across the board: 169 on-site, 23 hybrid, 2 remote.

---

## Indeed - RUNNING, un-parked 30.07.2026

> **HOW THIS ACTUALLY RUNS, 21.08.2026.** `python main.py` is started by hand
> on a local machine, writing to the remote Postgres. There is no server-side
> crawler and **no proxy**: `.env` carries `PROXY_MODE=off` and no `PROXY_URL`
> or `IPROYAL_*` at all, so every request goes direct from a home connection.
> That connection is residential, which is the property the measurements below
> actually depended on - the proxy was only ever one way of getting one.
>
> Everything below was measured on 28-30.07.2026 through a static residential
> proxy on the server, a setup that no longer exists. The conclusions still
> hold and the mechanisms they explain are all still in the code; the
> addresses and the machine are not. **Re-measure on the machine you actually
> run from** - the one lesson from those three days that survives its own
> environment.

**Status 30.07.2026.** Back in `main.py`'s SPIDERS list. The proving run
happened on the server, through the static residential proxy, with the
exported session: **61 requests, 61 HTTP 200**, no challenges, no handshake
escalations, 335 postings, and all four searches into the page ceiling with
results still arriving.

Three things had to be true at once, and the whole three-day detour came from
each being mistaken for the others: an accepted **handshake**, a residential
**address**, and a **session carried under the browser that made it**. The
last one is new and is the subtlest - see below.

### What 28.07 got wrong

The reading was "our address is refused": direct requests 403, every
residential exit walled, therefore the exit IP. Three of the four conclusions
below say otherwise, and the first one dismantles the original evidence -
**the home connection got the same 403 on 29.07**, having worked the day
before. It was never only about the address.

### 1. The TLS fingerprint had gone stale

`IMPERSONATE` was pinned to `chrome131`, verified 200 on 28.07. Measured
29.07, two rounds each, one address, identical headers:

| Handshake | Result | Handshake | Result |
|---|---|---|---|
| chrome110 | 403 challenge | **chrome124** | **200, 1.19 MB** |
| chrome131 | 403 challenge | **firefox135** | **200, 1.19 MB** |
| chrome136 / 142 / 145 / 146 | 403 challenge | **firefox147** | **200, 1.19 MB** |
| safari260 | 1 of 2 challenged | **safari184** | **200, 1.19 MB** |

Every Chrome token but one is challenged, and it is not a newest-is-best
gradient. Chrome is what nearly all impersonating traffic claims to be, so
that is where the scrutiny goes.

Confirmed independent of the address: through a clean static residential IP,
`chrome131` was still challenged while `firefox147` returned data. Neither
variable rescues the other.

`IMPERSONATE_CANDIDATES` is now a fallback ladder rather than one pinned
value, and `BlockDetectionMiddleware` climbs it. **Re-measure with `python -m
scraper.tls_probe`** rather than reasoning about it - that script
exists because this will go stale again.

It went stale again the next afternoon, which is how fast this moves. Measured
30.07 at 16:28 through the same static residential proxy:

| Handshake | Result | Handshake | Result |
|---|---|---|---|
| firefox147 | 403 challenge | **safari184** | **200, 1.14 MB** |
| firefox135 | 403 challenge | **chrome124** | **200, 1.14 MB** |

Exactly inverted from the table above, and the tokens that carried that
morning's 61/61 run were the ones being refused. The ladder is reordered
`safari184, chrome124, firefox147, firefox135`. Treat the order as weather.

### 2. The Referer was the actual trigger

The spider sent `Referer: https://tr.indeed.com/` with `Sec-Fetch-Site:
same-origin` on a request carrying no Indeed cookies at all - a browser
claiming a journey without the evidence of it. Same IP, same token, minutes
apart:

| Request | Result |
|---|---|
| bare headers | 200, data |
| the spider's headers | **403 challenge** |
| the spider's headers, no Referer | 200, data |
| the spider's headers, after loading the home page first | 200, data |

Fixed by making the claim true: `warmup_url` now points at the home page, so
the run collects real cookies before searching, and pagination refers to the
page it actually came from. **This was invisible from a home connection** -
every combination passed there. It only decided anything from a proxy.

### 3. Page two asks for an account - SETTLED 30.07

`branding=page-two-signin` is named after what it is, and an account genuinely
opens it. The same url that walled anonymously at 13:18 returned job cards
with a session at 13:44, from the same address - so the "is it the account or
is it the address's standing" question is closed in favour of the account.
All four searches then ran to the `MAX_PAGES = 15` ceiling with results still
arriving, which means the ceiling is ours, not Indeed's.

Anonymous runs still stop at page one (`ANONYMOUS_MAX_PAGES`), and that is
still the right ceiling: a control run at 16:30 with no cookies got page one
data and a page two wall.

**Seen once and not reproducible:** at 13:18 `?start=0` itself redirected to
`branding=page-two-signin`, i.e. the wall reached page one. Three hours later
anonymous page one was answering normally again. Do not build on either
reading - if a run reports zero postings anonymously, this is the thing to
re-measure rather than the proxy.

### 4. Refusals cost credit, and we were spending it

Chasing page two anonymously did not just waste requests. The retries carry
`priority+1`, so they overtook searches that had not started, and the burst
of refusals spent enough of the address's standing that their first pages -
which would have worked - were challenged too. Two searches lost to it.

Both a home connection and the static residential IP did the same thing:
serve 1.19 MB pages, get refused in a burst, then challenge everything for
several minutes, then recover on their own. So `DOMAIN_BLOCK_BUDGET` (8) now
stops a run that is being refused instead of grinding through every search
times every identity - sixteen refusals in under a minute is an efficient way
to teach a site to distrust an address, and it damages the *next* run too.

### 5. The session outlives the cookies it was afraid of

The account was created through Google with no "remember me" box, so
`PPID`, `__Secure-PassportAuthProxy-BearerToken` and `-OauthExpires` all fill
up about 55 minutes after export. The browser renews them with
`RefreshToken`; the spider cannot. That is what kept the schedule blocked -
a 03:00 run with a dead session would return zero postings silently.

Measured 30.07 at 16:30 with the file exported at 13:43, nearly three hours
old:

| Cookies sent | Page 1 | Page 2 |
|---|---|---|
| all 32, as exported | 200 data | **200 data** |
| the 6 durable ones only | 200 data | **200 data** |
| none (control) | 200 data | sign-in wall |

So the oauth trio is not what opens page two - `CTK, JSESSIONID, PPID, RF,
SOCK, SHOE` do it on their own, and those are the long-lived ones. Adding a
password to the account to get a "remember me" checkbox is not needed.

**Still unmeasured past three hours.** The first scheduled 03:00 run is the
next data point; if it comes back with nothing, re-export the cookies before
suspecting anything else.

### 6. The session and the handshake are a PAIR - the last mistake

The server had the proxy and the session and still lost a run: 8 of 11
requests refused, block budget spent. The reflex reading was "the ladder has
gone stale again". It had not. Same address, ten minutes apart:

| Run | Handshake | Result |
|---|---|---|
| `tls_probe --both`, no cookies | safari184, chrome124 | 200, data |
| `tls_probe --both`, no cookies | firefox147, firefox135 | 403 challenge |
| spider, session attached | safari184 | 0 of 2 answered |
| spider, session attached | chrome124 | 0 of 4 answered |
| spider, session attached | firefox147 | 3 of 3 answered |
| spider, `INDEED_IMPERSONATE=firefox147` | firefox147 | **61 of 61 answered** |

The session was exported from Firefox. Presented under Safari's or Chrome's
handshake it is a session being used by something other than what created it
- and that is cheaper to spot than any fingerprint, which is what
`session_cookies.py` had been saying all along in prose.

So the probe and the spider measure different things, and the probe's verdict
only applies to an anonymous crawl. `_prefer_the_session_s_browser` puts the
session's browser at the head of the ladder whenever cookies are loaded,
leaving the measured order alone when they are not.
`INDEED_SESSION_BROWSER` changes it if the session is ever made elsewhere.

**But do not carry the pairing further than the measurement goes.** Two hours
after the server run, the same Firefox session was carried from the HOME
machine through the same proxy: `safari184` answered 200 with data (twice,
an hour apart) and `firefox147` was refused. That is the server's result
inverted, with the exit address, the session and the hour all held constant.
The remaining difference is the client itself - curl_cffi on Windows/Python
3.14 here against Linux/Python 3.12 there.

So the honest statement is narrower than "a session must wear its own
browser": the accepted combination is (client × handshake × session), it is
not stable across machines, and the ladder exists precisely because none of
it stays decided. Leading with the session's browser is what measured right
on the server, which is where it ran at the time. Re-measure wherever you
actually run it - the same lesson that cost 28.07, and again on 30.07. As of
21.08.2026 that is a local machine, so the "server" in this paragraph is no
longer the place to measure.

### Why it stayed parked so long

Not because it failed - because the server did not have what the measurements
were made on. The static address and the session lived in a local `.env`
while Coolify had the rotating pool that never worked.

That was resolved by setting both on the server, and the spider was un-parked.
**Since 21.08.2026 the arrangement is simpler and the proxy is out of it
entirely:** the crawl runs by hand from a local machine whose own connection
is residential, with `INDEED_COOKIES_B64` for the session and
`PROXY_MODE=off`. `PROXY_URL` is not set anywhere.

`INDEED_COOKIES` must be an **absolute** path: `main.py:137` runs the spider
with `cwd=scraper`, so a bare filename resolves in the wrong
directory. That mistake cost a run and eight refusals on 30.07 before anyone
read the first log line; `load_cookies` now raises instead of quietly
crawling anonymously.

On the panel, use **`INDEED_COOKIES_B64`** instead - base64 of the same
header. The raw header is ~5 KB with double quotes inside its values, which
is why a file was used locally in the first place, and a file on a hosting
panel means a mount plus a copy plus a second place the account lives. Base64
has nothing in it that any environment-variable box will mangle, and it wins
over `INDEED_COOKIES` when both are set.

The first attempt on the server failed anyway - `binascii.Error: Only base64
data is allowed` - so the decoder now cleans what a clipboard and a text box
do to a value before judging it: whitespace, real newlines, `\n` written out
literally, surrounding quotes, url-safe alphabet, missing padding. Anything
left that is not base64 is named in the error rather than described as
invalid.

**A truncated value is the dangerous one**, because it decodes and parses and
yields a plausible pile of cookies that just happens not to include the
sign-in. `IndeedCardsSpider.SIGNED_IN_COOKIES` refuses a session without
`SOCK` and `SHOE` for that reason - measured, those two are what carry it. A
cut after them costs only the oauth cookies, which do not matter, so that
session is allowed to run.

`python main.py --spider indeed_cards` runs it by hand meanwhile.

**What parking costs us:** techcareer.net belongs to kariyer.net, so the two
remaining spiders are one company's data and the two-independent-routes rule
above does not hold across sites.

**Worth knowing:** the sign-in wall was invisible at first. Status 200, no
anti-bot fingerprint, and Indeed's search page is HTML by design so
`expect_json` never applied - the crawl reported "3/3 spiders succeeded" with
Indeed contributing nothing. `BlockDetectionMiddleware.LOGIN_URL_SIGNATURES`
now catches it, reading the requested url from `meta["redirect_urls"]` because
RedirectMiddleware has already rewritten `request.url` by then. Cloudflare's
own `cf-mitigated` header is read directly now too.

Everything below describes the spider as built.

## Indeed

**Status:** migrated - `spiders/indeed_cards.py`. The old
The old DOM spider has been deleted; it is in git history if ever needed.

The only genuinely independent source left, since techcareer.net belongs to
kariyer.net and jooble and LinkedIn are out of scope.

**Investigated 27.07.2026.**

### No endpoint, but the data is plain JSON in the page

The search page is server-rendered, so there is no XHR to intercept. The data
is not scattered through the DOM either - it sits in a script as JSON:

```
window.mosaic.providerData["mosaic-provider-jobcards"]
  -> metaData.mosaicProviderJobCardsModel.results     (15 records per page)
```

Extracted by scanning braces, not by regex: the blob is ~120 kB of nested JSON
with escaped quotes and braces inside string values.

**A plain request from a residential IP returns HTTP 200 with the full page** -
no challenge, despite Cloudflare fronting the site. Worth noting: the old
spider pays ScrapeOps for JS rendering that may not be needed.

This is the property the whole arrangement rests on, and as of 21.08.2026 it
comes from the home connection the crawl is run on rather than from a proxy.
`ResidentialProxyMiddleware` is still in the code and still works, but it is
inert while `PROXY_MODE=off`. If the crawl ever moves to a datacenter address
- a VPS, CI, anywhere - it will be refused on every handshake, and turning the
proxy back on is the fix.

Pagination is `start=0,10,20,...`; `l=` accepts `İstanbul`, `ıstanbul` and
`istanbul` interchangeably - all three return identical results, verified.

### The job-type filter is unusable

Across 120 real Istanbul internship postings, `taxonomyAttributes.job-types`
said:

| Value | Count |
|---|---|
| Staj | 54 |
| **Tam zamanlı** (still internships) | **28** |
| Yarı zamanlı | 13 |
| **(empty)** | **5** |
| mixed combinations | 20 |

Filtering on the type would have dropped a quarter of them. On a `q=yazılım`
search it is worse - 11 of 15 postings declared nothing at all. So the search
is by KEYWORD (`stajyer`, `intern`, `part time`, `yarı zamanlı`), one route
each, merged afterwards. Indeed has no category taxonomy, only free-text
search, so a single query would miss whatever it does not literally match.

### No field filter here

Turkish companies routinely advertise one internship for the whole company and
allocate people to departments afterwards: "Intern" at UPS, "Intern - Long
Term" at Volvo, "Stajyer" at FarklıFikir Bilişim. There is no field to filter
on, and guessing throws them away.

The spider therefore keeps every Istanbul internship and part-time posting it
finds. The field is decided afterwards, by the LLM classifier - see the
section at the end of this file.

### Internships tagged full-time

Same trap as kariyer.net: 19 of 72 postings came back typed only "Tam zamanlı"
and would have normalised to Full-Time, which the dashboard hides. The title's
verdict is put first in `job_type` so `normalize_job_type` ranks Internship
above Full-Time. After the fix: 71 Internship + 1 Part-Time, all visible.

### Description

`snippet` is an excerpt, not the full text, and it is used as-is. Fetching
`/viewjob?jk=<key>` per posting would cost ~75 extra requests a day against
the site most likely to block us and the only independent source we have.

**Careful with the fallback pattern here:** `JsonJobLoader.job_description_out`
is `Join(' ')`, so a second `add_value` is APPENDED, not ignored. Using the
usual `add_value(x); add_value(DEFAULT_VALUE)` idiom left every description
ending in a stray "N/A". Set that field in one call.

### Yield

**72 unique postings** from the `stajyer` route alone, all fields populated.

---

## Jooble - OUT OF SCOPE

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

## LinkedIn - was OUT OF SCOPE, running again since 26.08.2026

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

### Everything below was measured on 26.08.2026, through the burner session

Headless Chromium, one navigation each, ~20 requests over ~40 minutes: HTTP
200 throughout, no authwall, no challenge.

### The location filter does not work by name

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

### Filter ids, read out of the filter panel's own inputs

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

### THE CARDS ARE NOT ALL ON THE PAGE - the expensive one

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

### Navigation headers broke the page, invisibly

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

#### That change cannot have affected Indeed, and here is the measurement

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

### The card fields

| Field | Where |
|---|---|
| id | `li[data-occludable-job-id]` |
| title | `a.job-card-list__title--link` **`aria-label`** |
| company | `.artdeco-entity-lockup__subtitle` |
| location | first `li` of `.artdeco-entity-lockup__caption` |
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

### First classification, 26.08.2026

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

### No description, on purpose

A card carries a title, a company and a location and nothing else. Reading
descriptions means one request per posting, which doubles the traffic on the
account we are least able to replace, so `job_description` is `N/A` and the
classifier decides on the title. Revisit if the `general_program` pile grows
useless - and measure it then.

### Two routes

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

### The intermittent stall

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

While one navigation is wedged the browser thread cannot take the next one, so
the requests behind it wait. A run with a few of these is a slow site, not a
broken crawler.

### Is the posting still open - UNMEASURED

`spiders/linkedin_check.py` exists and is deliberately written around not
knowing the answer yet: on 26.08.2026 the database held no LinkedIn posting
old enough to have closed, so there was no closed page to read a marker off.
CLOSED requires the page to say so in words; anything else is UNKNOWN and
writes nothing. Expect "N open, 0 closed, M inconclusive" until the first real
closure - that is the correct result, not a broken one.

When `linkedin/closed_marker_seen` first appears in a run's stats, that is the
measurement. Record the id and the date here, and this section joins the other
three.

**The detail page stalls far more often than the search page.** First dry run,
five postings, `OPENINGS_MAX_PER_SITE=5`: **1 open, 0 closed, 0 inconclusive,
4 unanswered** - four of five navigations spent the whole Playwright budget
(`playwright/navigation_timeout: 4`). Nothing was written for those four,
which is the design working, but a checker that answers one posting in five is
not yet worth running over the whole board. Before turning it loose, the thing
to try is blocking images/fonts/analytics on this transport so the page has
less to wedge on - not a longer timeout.

The detail page is a DIFFERENT design system from the search page: search
cards still use semantic classes (`job-card-container`), while the job page
has build-hashed ones (`_59162b76`, `b424a163`). The stable anchors there are
`aria-label="Easy Apply to this job"` and the `<h2>` headings.

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
