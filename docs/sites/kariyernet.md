# kariyer.net

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

## There is probably no JSON listing endpoint

Pagination links are plain anchors - `<a href="/is-ilanlari?cp=2">`, going up
to `cp=100`. The listing is server-rendered and paging is ordinary page
navigation, so no XHR carries the job data. A DevTools Network capture on this
site is dominated by GTM / Google Analytics / DoubleClick / Taboola and
PerimeterX sensor posts (263 requests on one page load); the job data is not
among them.

**Consequence: the filters live in the page URL**, not in an API call. To
learn a filter's parameter name, apply it in the UI and read the address bar.

## Working type taxonomy - CONFIRMED

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

## Filter panel taxonomies

Three separate axes in the sidebar, from the filter markup
(`k-filter-checkbox-*`): **Departman**, **Pozisyon**, **Pozisyon Seviyesi**.
"Departman" is the field-level one we want for software/IT. Ad cards also
carry `sectorId` and `positionId`.

## Internships may live on a different host

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

## Ad card structure - CONFIRMED against a live page

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

## Filter by DEPARTMENT, not sector - the single biggest correction

Sector (`cs`) describes what the **company** does; department (`wa`) describes
what the **role** is. The first attempt filtered on sector = Bilişim and
produced mostly sales and office jobs at IT companies, while missing every
developer role at a bank, a hospital or a factory.

Switching axes changed the result completely:

| Filter | Postings kept | What they were |
|---|---|---|
| sector = Bilişim | 7 | 4 of them sales/office roles at IT firms |
| department list | 28 | includes Software Engineering Intern (GE), Bilgisayar Mühendisliği Stajyeri, Bilgi İşlem Stajyeri, Bilgi Teknolojileri Stajyeri |

## Search URLs - CONFIRMED

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

## Employers mis-code internships - IMPORTANT

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

## Spider

`spiders/kariyernet_cards.py`. Pages the filtered search, applies the filter
above, and requests the detail page only for the survivors - so only the few
percent of postings we want cost a second request.

## Actual yield - the whole result set, crawled

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

## `ilkisim.kariyer.net` is not a separate site - RESOLVED

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

## Trust the search, not the title

`INTERNSHIP_TITLE_RE` is a good signal but not sufficient: "Career Experıence
Drıve - IT (Servıce&Operatıons)" is a real internship with neither "staj" nor
"intern" in its title, and the regex would drop it.

So `INTERNSHIP_SEARCHES = {"staj"}`: everything the site's own internship
search returns is kept and labelled Internship, no questions asked. The site
classifies its own postings better than a regex can guess. The regex stays as
the fallback for the part-time search, where a P-coded "E-Ticaret Stajyeri"
should still come out as an internship.

## Yield - both searches, verified

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

## Bug found by crawling the full set

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

