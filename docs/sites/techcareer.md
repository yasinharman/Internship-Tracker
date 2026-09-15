# TechCareer

**Status:** migrated - `spiders/techcareer_api.py`. The old
The old Playwright-based spider has been deleted, and with it Playwright
itself: ~500MB and the slowest step of the Docker build are gone.

**Investigated 27.07.2026.** Owned by kariyer.net - job logos are served from
`cdn.kariyer.net` and postings are syndicated between the two sites, so
expect duplicates across `source_site`.

## Next.js, and where the endpoint hides

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

## Filters

| Param | Meaning |
|---|---|
| `jobs[filters][typeOfWork]` | `2` = yarı zamanlı, `4` = stajyer. Verified against `/jobs/yari-zamanli` and `/jobs/stajyer`, one posting each. |
| `jobs[isCompleted]` | `false` = still open |
| `jobs[page]` | page number, `pageSize` 20 |

**A single value returns HTTP 500** (re-checked 14.09.2026, `typeOfWork=4`) -
the endpoint wants a comma-separated list, so always send `2,4`. Slug pages also exist: `/jobs/stajyer`,
`/jobs/yari-zamanli`, `/jobs/tam-zamanli`, `/jobs/uzaktan`, `/jobs/hibrit`,
`/jobs/freelance`, `/jobs/sozlesmeli`, `/jobs/deneyimli`, `/jobs/deneyimsiz`.

There is no location parameter in use; `location` is a plain string on each
record ("İstanbul / Türkiye", "İstanbul(Asya) / Türkiye"), so Istanbul is
filtered with a substring test in the spider.

## Why the spider makes two passes

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

**On 14.09.2026 it was the other way round.** The run's discovery report read
`typed found 2, sole finder of 1 | scan found 1, sole finder of 0`. The posting
only `typed` could reach was 9830 *Assistant Product Manager*, tagged
`Yarı Zamanlı` by the site, with no part-time word anywhere in its title. Each
pass has now been the sole finder once, so neither one is redundant.

## Is it thin because of our URL? No - measured 14.09.2026

A run returning 2 postings raised the obvious question: are the filters or the
url losing postings, or is the board really this empty? Twelve requests,
2.5 s apart, all 200 except the deliberate single-value arm. The spider's own
urls were compared with the pages a visitor lands on:

| Arm | `pagination.total` |
|---|---|
| `GET /jobs`, the HTML a visitor gets (`__NEXT_DATA__`) | **139** |
| `_next/data` `isCompleted=false`, what the scan sends | 139 - 7 pages, 139 unique ids |
| `_next/data` without `isCompleted` | 139 - "open only" hides nothing |
| `GET /jobs/stajyer`, the site's own internship page | **1**, the whole country |
| `_next/data` `typeOfWork=2,4`, what `typed` sends | 3, all three also in the scan |
| `_next/data` `typeOfWork=4` | HTTP 500, still |

Every one of the 139 titles was then read, in any city, and not only for the
Istanbul records the spider keeps. `is_wanted()` matched exactly one
(9664 *IT Stajyeri*, already stored). A looser pass for *yeni mezun / junior /
program / akademi / talent / trainee / öğrenci* found no internship either,
only a robot programmer and the part-time 9830. The board is 77 Istanbul
postings out of 139, and nearly all of them are full-time roles.

So the url is not the problem: **the board has one internship and three
internship-or-part-time postings in all of Turkey**, and the spider collects
every one of them that is in Istanbul.

Dropping the filters and searching `stajyer` alone was considered and
rejected on these numbers. It would have returned 1 posting, which is also a
kariyer.net duplicate that dedupe hides. It would have lost 9830, and it would
have removed the scan, the only route that ever found 9612. The field decision
(IT or general programme) was already the classifier's, not the spider's.

## Working type is NOT guessed here

Unlike kariyer.net, no override is needed: the detail endpoint reports
`head.typeOfWorks: ["Stajyer"]` accurately, and detail is fetched for the
handful of survivors anyway. `normalize_job_type` maps it straight through.

## Record fields

List: `id`, `title`, `slug`, `jobTitle`, `jobTitleEn`, `location`,
`workPlaces`, `owner.name`, `owner.logo`. **No working-type field** - which is
why the full scan has to match on the title.

Detail: `head.title`, `head.company.name`, **`head.company.logo`**,
`head.location`, `head.typeOfWorks`, `head.startDate`/`endDate`,
`head.workPlaces`, `content.description` (HTML), `content.skills`.

**The logo is in both payloads, and the detail one is enough - dumped
09.09.2026.** `owner.logo` on the list record and `head.company.logo` on the
detail record hold the same url, so the spider reads the detail and
`parse_list` keeps forwarding nothing but the slug. Both are empty for a
posting whose employer is hidden - exactly when `head.company.name` is empty
and the spider falls back to `hiddenCompanyInfo` - and a hidden employer has
no logo to recover from the list side either.

**The url is `http://`, and it has to stay that way.** It points at
`cdn1.kariyer.net`, which serves the image over plain http (200) but has no
working certificate: `curl` on the `https://` form fails with exit 60. So
`logo_url()` leaves an absolute `http://` alone rather than upgrading the
scheme, and a board served over https would have these blocked as mixed
content. Note that this is a DIFFERENT host from the one kariyer.net's own
cards point at (`img-kariyer.mncdn.com`, https, fine) even though the two
sites share an owner.

## The description is read twice, on purpose

`parse_detail` takes it during the crawl and `techcareer_check.description()`
takes it again from the same `_next/data` payload when the posting is checked.
Measured 09.09.2026: `pageProps.jobDetail.content.description`, HTML, needs
`strip_html`. The second read costs no request - the checker downloads that
payload anyway to read `head.isCompleted` - and it is what keeps a stored
description current without re-crawling.

## Yield

**2 postings**, both internships in Istanbul, one of them findable only by the
full scan. `workPlaces` across the board: 169 on-site, 23 hybrid, 2 remote.

**14.09.2026, `main.py --spider techcareer_api`:** 11 requests, all 200, 21 s,
**2 postings** from a board of 139.

- 9664 *Uzun Dönem Üniversite Stajyeri - IT Stajyeri* - dedupe hid it as a
  copy of kariyer.net id=784.
- 9830 *Assistant Product Manager* (part-time) - stored with company `N/A`
  and no logo. That is correct: the payload has `isCompanyHidden: true` and
  both `company.name` and `hiddenCompanyInfo` are empty, even though the
  description names the employer in its text.

---

