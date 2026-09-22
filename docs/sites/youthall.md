# Youthall

A Turkish board for students and new graduates: internships, but also
graduate and trainee programmes. No spider yet. The board is for every
student and the crawl keeps internships in Istanbul only (the owner's filters
since 21.09.2026).

## First look - measured 22.09.2026

Two navigations, no account, through a pool address (line 17, FR;
`docs/proxies.md`). Each was a fresh, cookie-less context in a windowed
Chromium launched as `PlaywrightMiddleware` does, 20 s apart. The URLs were
the owner's. Both pages were saved and read again offline.

| URL | Result |
|---|---|
| `https://www.youthall.com/en/jobs/` | 200, 957 kB, served with no account. "giriş yap" is the menu link, not a wall |
| `https://www.youthall.com/tr/tchibo/e-ticaret-stajyeri_124/` | 200, 767 kB, "Tchibo E-Ticaret Stajyeri - Son Başvuru: 14.11.2026" |

**Server-rendered, no JSON API.**
- The pages fetch nothing of their own but analytics, plus one
  `POST /tr/update/stats` on a posting page - its view counter, which any
  visitor also sends.
- There is no `__NEXT_DATA__` and no Nuxt state.

**The posting page carries a schema.org `JobPosting` in `ld+json`**, the whole
posting in one request:

| Field | Tchibo, 22.09.2026 |
|---|---|
| `title`, `hiringOrganization.name` | E-Ticaret Stajyeri, Tchibo |
| `employmentType` | `INTERN` |
| `jobLocation.address.addressLocality` | İstanbul |
| `datePosted` / `validThrough` | 2026-09-15 / 2026-11-14T23:59:59+03:00 |
| `description` | 2,447 characters |
| `hiringOrganization.logo` | an S3 url |

`validThrough` is the application deadline. A posting past it has closed;
that is a date comparison rather than a page to interpret. Not yet seen: what
a posting past its deadline, or taken down, serves.

**The list is NOT all internships.** Every card states a type, and page one
had several:

| Posting | Type on the card |
|---|---|
| Toyota "Uzun Dönem Staj Programı", Akkim "Uzun Dönem Staj Programı" | Internship |
| BİM "Mağaza Yöneticisi Programı", YEO "Young Energy Officer" | Management Trainee |
| Şişecam "Geleceğe İlerleyen Kadınlar Programı" | Project Based |
| TBV "Başlangıç Noktası Akademi 2027" | Volunteer |

A card also shows the deadline and the city ("İstanbul", "Hibrit", ...).

**The site's own landing pages** (links on `/en/jobs/`):
- **by type:** `/en/jobs/internship/`, `management-trainee/`,
  `new-graduate/`, `young-professional/`, `part-time/`, `full-time/`,
  `project-based/`, `volunteer/`, `contract/`, `freelance/`;
- **by city:** `/en/jobs/istanbul/`, `kocaeli/`, `remote/`, `ankara/`, ...
  (12).

**It is small.** The city block counts every listing on the site:

| Istanbul | Kocaeli | Remote | Samsun | Ankara, Antalya, Aydın, Bursa, Eskişehir, Konya, Muğla, Yalova |
|---|---|---|---|---|
| 17 | 4 | 2 | 2 | 1 each |

About 33 in all, 17 of them in Istanbul, every type included. `/en/jobs/`
showed 21 distinct postings on page one, with a `?page=2`. So the Istanbul
page is most likely one page. That is not yet requested.

**What a run would cost:** one request for the Istanbul list, plus one posting
page per new internship for the description.

## The Istanbul list, and the spiders - 22.09.2026

**One request to `/en/jobs/istanbul/`** (pool line 7, GB): 200, 905 kB, 17
cards, no link to a page 2. Every card is a `div.jobs`:

- the title is in `.jobs-content-title h5`;
- the company is the alt of `img.jobs-content-logo` ("Tchibo logo"), and that
  image is the logo;
- three `.jobs-tag`s give the type, the deadline and the city ("İstanbul +"
  for several).

The type is not always right. The 17:

| Type on the card | Count | Title reads as internship |
|---|---|---|
| Internship | 12 | 12 |
| Part-Time Jobs | 2 | 1 - Hyundai's "HGenius Long Term Internship Program" |
| Full Time | 1 | 0 - "Hukuk Asistanı / Adalet MYO Mezunu" |
| Management Trainee | 2 | 0 - BİM, YEO |

**The owner's rule, 22.09.2026: internships only.** A card is kept when its
type says Internship OR its title reads as one: 13 of 17.

**`youthall_cards` and `youthall_check`, first run the same day**, through the
pool:

- **The crawl:** one request from line 4 (DE). 17 cards, 13 kept, 4 dropped,
  13 logos.
- **The check:** a dry run of 2 postings from line 5 (FR). Both 200, both
  open, both with a description from the JobPosting.
- **The verdict** is a date comparison on `validThrough`: past it is CLOSED,
  ahead of it OPEN, a page without a JobPosting is UNKNOWN.
