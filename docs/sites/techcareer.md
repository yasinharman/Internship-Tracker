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

**A single value returns HTTP 500** - the endpoint wants a comma-separated
list, so always send `2,4`. Slug pages also exist: `/jobs/stajyer`,
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

## Working type is NOT guessed here

Unlike kariyer.net, no override is needed: the detail endpoint reports
`head.typeOfWorks: ["Stajyer"]` accurately, and detail is fetched for the
handful of survivors anyway. `normalize_job_type` maps it straight through.

## Record fields

List: `id`, `title`, `slug`, `jobTitle`, `jobTitleEn`, `location`,
`workPlaces`, `owner.name`, `owner.logo`. **No working-type field** - which is
why the full scan has to match on the title.

Detail: `head.title`, `head.company.name`, `head.location`,
`head.typeOfWorks`, `head.startDate`/`endDate`, `head.workPlaces`,
`content.description` (HTML), `content.skills`.

## Yield

**2 postings**, both internships in Istanbul, one of them findable only by the
full scan. `workPlaces` across the board: 169 on-site, 23 hybrid, 2 remote.

---

