"""
TECHCAREER - NEXT.JS DATA API
=============================

techcareer.net is a Next.js site, which means two things worth knowing.

First, there IS a JSON endpoint, it just never shows up in DevTools on a fresh
page load: Next.js server-renders the first view and only calls
`/_next/data/<buildId>/<locale>/<route>.json` on client-side navigation. Same
trap as kariyer.net, different framework.

Second, `buildId` changes with every deployment, so it cannot be hardcoded.
The spider loads `/jobs` once, reads the id out of the `__NEXT_DATA__` script
tag, and builds every later URL from it.

The board is small - 194 postings, 94 of them in Istanbul - so the whole index
is cheap to walk. That matters, because the site's own working-type filter is
not trustworthy on its own:

    typeOfWork=2,4 (yarı zamanlı + stajyer)  ->  9635 (Muğla), 9589
    title scan over all 194 postings         ->  9612, 9589

"Bilgisayar Mühendisliği Stajyeri" (9612) is a computer-engineering internship
in Istanbul that the site does not tag as one. Exactly the pattern kariyer.net
showed, where 22 of 26 internships were mis-coded by the employer. So both
signals are used and the results merged.

THE CRAWL READS THE LIST AND NOTHING ELSE (since 21.09.2026). Each kept list
record becomes an item on the spot - title, company, logo, location and url
are all on the record - and the description is left as "N/A" for
techcareer_check, which downloads the detail JSON anyway to read
`head.isCompleted` and takes the description from the same payload. A run is
the warm-up plus the list pages, nothing per posting.

The one field that did not survive the move is the site's working type: the
list record has none (docs/sites/techcareer.md, "Record fields"), so the job
type now comes from the title alone - which already outranked the detail's
`typeOfWorks` - and a posting whose title says neither is stored as N/A.
"""

import json

from ..api_spider import BaseApiSpider, dig, logo_url
from ..job_filters import looks_like_internship, looks_like_parttime
from ..loaders import JsonJobLoader


class TechCareerApiSpider(BaseApiSpider):
    name = "techcareer_api"

    site_name = "techcareer.net"
    origin = "https://www.techcareer.net"
    allowed_domains = ["techcareer.net"]

    # Loaded first so `buildId` can be read from it.
    warmup_url = "https://www.techcareer.net/jobs"

    # Only postings in these locations are kept. The field is a plain string
    # like "İstanbul / Türkiye" or "İstanbul(Asya) / Türkiye", so a substring
    # test covers both sides of the city.
    WANTED_LOCATIONS = ("İstanbul",)

    # The site's own working-type filter: 2 = yarı zamanlı, 4 = stajyer,
    # verified against /jobs/yari-zamanli and /jobs/stajyer, which return one
    # posting each. Single values make the endpoint return HTTP 500 - it wants
    # a comma-separated list - so this is always sent as a pair.
    TYPE_OF_WORK_FILTER = "2,4"

    results_path = "pageProps.initialJobList.jobListItems"

    custom_settings = {
        **BaseApiSpider.custom_settings,
        "CONCURRENT_REQUESTS": 2,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 2,
        "DOWNLOAD_DELAY": 1.5,
        "RANDOMIZE_DOWNLOAD_DELAY": True,
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.build_id = None
        # Slugs already yielded this run - see parse_list.
        self._yielded = set()

    ##########################################################
    # WARM-UP: READ buildId OUT OF THE SERVER-RENDERED PAGE  #
    ##########################################################
    def on_warmup(self, response):
        raw = response.css("script#__NEXT_DATA__::text").get()
        if not raw:
            self.logger.error(
                "No __NEXT_DATA__ on %s - the site is no longer Next.js, or we "
                "were served something other than the jobs page.", response.url,
            )
            return

        try:
            self.build_id = json.loads(raw).get("buildId")
        except json.JSONDecodeError as error:
            self.logger.error("__NEXT_DATA__ is not valid JSON: %s", error)
            return

        self.logger.info("Next.js buildId for this run: %s", self.build_id)

    #########################
    # URL BUILDERS          #
    #########################
    def _data_url(self, route, **params):
        query = "&".join(f"{key}={value}" for key, value in params.items())
        return f"{self.origin}/_next/data/{self.build_id}/tr/{route}.json?{query}"

    def _list_url(self, page, type_of_work=None):
        params = {
            "jobs%5BisCompleted%5D": "false",
            "jobs%5Bpage%5D": page,
        }
        if type_of_work:
            params["jobs%5Bfilters%5D%5BtypeOfWork%5D"] = type_of_work
        return self._data_url("jobs", **params)

    ###############################################
    # TWO PASSES OVER THE INDEX                   #
    ###############################################
    def api_requests(self):
        if not self.build_id:
            self.logger.error("No buildId - cannot build any API url, stopping.")
            return

        # "typed"  - what the site itself calls part-time or internship.
        # "scan"   - every posting, filtered on the title here. Catches the
        #            internships the site has tagged as something else.
        yield self._list_request("typed", page=1)
        yield self._list_request("scan", page=1)

    def _list_request(self, search_key, page):
        url = self._list_url(
            page,
            type_of_work=self.TYPE_OF_WORK_FILTER if search_key == "typed" else None,
        )
        return self.api_request(
            url,
            callback=self.parse_list,
            referer=f"{self.origin}/jobs",
            headers={"x-nextjs-data": "1"},
            meta={"page": page, "search_key": search_key},
            dont_filter=True,
        )

    ###########################################
    # PICK THE CANDIDATES, YIELD THE ITEMS    #
    ###########################################
    def parse_list(self, response):
        payload = self.parse_json(response)
        if payload is None:
            return

        records = self.extract_records(payload)
        page = response.meta["page"]
        search_key = response.meta["search_key"]

        kept = 0
        for record in records:
            location = record.get("location") or ""
            if not any(city in location for city in self.WANTED_LOCATIONS):
                continue

            # INTERNSHIPS ONLY SINCE 22.09.2026 - the owner dropped part-time on
            # every site. The list records carry no working-type field, so the
            # title is all there is to go by.
            #
            # "typed" cannot ask the site for internships alone: typeOfWork=4
            # on its own is HTTP 500 (docs/sites/techcareer.md, re-checked
            # 14.09), so it sends 2,4 and part-time comes back too. There a
            # title that says part-time and not internship goes, and one that
            # says neither stays - the site filed it under one of the two, and
            # employers mis-code internships (22 of 26 on 10.09).
            #
            # "scan" walks the whole index, so its title has to say internship.
            title, job_title = record.get("title"), record.get("jobTitle")
            if search_key == "typed":
                if looks_like_parttime(title, job_title) and not looks_like_internship(title, job_title):
                    continue
            elif not looks_like_internship(title, job_title):
                continue

            slug = record.get("slug")
            if not slug:
                self.logger.warning("Record %s has no slug", record.get("id"))
                self.crawler.stats.inc_value("items/skipped_no_url")
                continue

            # Which route found it - see BaseApiSpider.note_discovery. If
            # "scan" ever becomes the sole finder of postings, the site's own
            # typeOfWork filter is leaking.
            self.note_discovery(slug, search_key)
            kept += 1

            # Both passes can return the same posting - 9664 was in both on
            # 14.09.2026 - and an item built from the record alone would be the
            # same upsert twice. The detail request this replaced was dropped
            # the same way, by Scrapy's dupefilter; here it has to be explicit.
            if slug in self._yielded:
                continue
            self._yielded.add(slug)

            yield self._item_from_record(record, slug)

        self.logger.info(
            "[%s] page %s: %s posting(s), %s candidate(s)",
            search_key, page, len(records), kept,
        )
        self.crawler.stats.inc_value("jobs/seen", len(records))

        ##############
        # PAGINATION #
        ##############
        # The payload states how many pages there are, so trust it rather than
        # walking until something looks empty.
        page_count = dig(payload, "pageProps.initialJobList.pagination.pageCount") or 1
        if page < page_count and self.next_page_allowed(page, records, search_key):
            yield self._list_request(search_key, page + 1)

    #########################################################
    # THE ITEM, FROM THE LIST RECORD ALONE                  #
    #########################################################
    def _item_from_record(self, record, slug):
        """
        One list record -> one item, with no request of its own.

        Until 21.09.2026 this was parse_detail, fed by one
        /_next/data/.../jobs/detail/<slug>.json request per kept record. Every
        field it read except the description and the working type is on the
        list record as well - the inventory in docs/sites/techcareer.md
        (27.07.2026) lists `title`, `jobTitle`, `location`, `slug`,
        `owner.name`, `owner.logo` - so the request bought exactly one thing
        the crawl still needs, and the checker already fetches that payload.
        """
        loader = JsonJobLoader()
        loader.add_value("job_title", record.get("title"))
        loader.add_value("job_title", record.get("jobTitle"))
        loader.add_value("job_title", self.DEFAULT_VALUE)

        # `owner.name` rather than the detail's head.company.name. There is no
        # list-side counterpart to the detail's hiddenCompanyInfo in the
        # inventory, so a posting with a hidden employer falls straight to
        # N/A - which is what the one such posting stored anyway (9830 on
        # 14.09.2026: company.name and hiddenCompanyInfo both empty).
        loader.add_value("company", dig(record, "owner.name"))
        loader.add_value("company", self.DEFAULT_VALUE)

        # `owner.logo` - dumped 09.09.2026, the same url the detail carries as
        # head.company.logo. Empty exactly when the employer is hidden, and a
        # hidden employer has no logo to show anyway.
        #
        # The url is absolute and on cdn1.kariyer.net over plain http; that
        # host has no working certificate, so logo_url() leaves the scheme
        # alone rather than upgrading it into a dead link.
        logo = logo_url(dig(record, "owner.logo"), base=self.origin)
        loader.add_value("company_logo_url", logo)
        self.crawler.stats.inc_value("logo/found" if logo else "logo/missing")

        loader.add_value("location", record.get("location"))
        loader.add_value("location", self.DEFAULT_VALUE)

        # THE TITLE IS ALL THERE IS. The list record carries no working-type
        # field, so the detail's `typeOfWorks` went with the detail request.
        #
        # Less of a loss than it sounds: the title already outranked it,
        # because employers select the wrong type - "Bilgisayar Mühendisliği
        # Stajyeri" came back from the detail typed as Contract. jobTitle is
        # read too, for the same reason the scan's is_wanted() reads it: a
        # posting kept on its jobTitle must not then be typed as nothing.
        #
        # What IS lost is a posting whose title says neither. The typed pass
        # knows it is 2 or 4 - part-time OR internship - but not which, and
        # picking one would call a part-time job an internship or the other
        # way round. So it goes in as N/A and pipelines.py stores "Other".
        # 9830 *Assistant Product Manager* was exactly this on 14.09.2026. The
        # payload that says which is the one techcareer_check downloads.
        title = record.get("title") or ""
        job_title = record.get("jobTitle") or ""
        if looks_like_internship(title, job_title):
            job_type = "Stajyer"
        elif looks_like_parttime(title, job_title):
            job_type = "Yarı Zamanlı"
        else:
            job_type = None
            self.crawler.stats.inc_value("job_type/untyped")
        loader.add_value("job_type", job_type)
        loader.add_value("job_type", self.DEFAULT_VALUE)

        # "N/A" on purpose: pipelines.py only overwrites a stored description
        # with one that is truthy and not "N/A", so this cannot erase what
        # techcareer_check wrote.
        loader.add_value("job_description", self.DEFAULT_VALUE)

        # The same url parse_detail built, so every stored row still matches
        # on the upsert key.
        loader.add_value("url", f"{self.origin}/jobs/detail/{slug}")
        loader.add_value("source_site", self.site_name)

        return loader.load_item()
