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

Shared title vocabulary lives in `MultiwebsiteScraper/job_filters.py`; add new
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

## Indeed - PARKED, and now only deployment is left

**Status 30.07.2026.** Still out of `main.py`'s SPIDERS list, for one reason
and it is not about whether the spider works: the server does not yet have the
proxy and the session this was measured on. The authenticated run happened -
**61 requests, 61 HTTP 200**, no escalations, 367 items, 93 new postings and 68
updated.

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
MultiwebsiteScraper.tls_probe`** rather than reasoning about it - that script
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

### Why it is still parked

Not because it fails - only because the server is not set up for it. The
static residential address and the session file both live in a local `.env`,
while Coolify still has the rotating pool that never worked here. Un-park it
once the server has `PROXY_URL` and `INDEED_COOKIES`, and measure there with
`tls_probe --both` first.

`INDEED_COOKIES` must be an **absolute** path: `main.py:137` runs the spider
with `cwd=MultiwebsiteScraper`, so a bare filename resolves in the wrong
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
spider pays ScrapeOps for JS rendering that may not be needed. The datacenter
case should be covered by the residential proxy in `api_middlewares`.

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

## LinkedIn - OUT OF SCOPE

Deliberately excluded (decided 27.07.2026). Its JSON API (Voyager) only
answers authenticated requests, and pointing the bot at a personal account
risks a permanent ban for very little extra coverage. Checked by hand instead.
`spiders/linkedIn.py` has been deleted. Do not add LinkedIn back.

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
| `MultiwebsiteScraper/classifier.py` | Schema, prompt, one call per provider |
| `classify_jobs.py` | Reads `job_category IS NULL`, writes results |
| `migrate.py` | Adds the three columns (idempotent) |

Runs from `main.py` after the crawl. A failure there does **not** fail the
scheduled task: the postings are already stored, and unclassified rows stay
visible on the dashboard.

### Choosing the model

Decided by measurement, not by price list. `classify_jobs.py --compare` runs
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
visible in the Coolify logs without a query. To audit:

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

`dedupe_jobs.py`, from `main.py` **before** the classifier: a duplicate is
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
