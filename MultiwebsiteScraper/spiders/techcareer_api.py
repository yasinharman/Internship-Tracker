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

Working type is NOT guessed here, unlike the kariyer.net spider: the detail
endpoint reports `typeOfWorks: ["Stajyer"]` accurately, and detail is fetched
for the handful of survivors anyway.
"""

import json

from ..api_spider import BaseApiSpider, dig, strip_html
from ..job_filters import is_wanted, looks_like_internship, looks_like_parttime
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

    ###########################
    # PICK THE CANDIDATES     #
    ###########################
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

            # Everything the site's own filter returns is wanted by definition.
            # On the full scan we have to read the title, because the list
            # records carry no working-type field at all.
            if search_key != "typed":
                if not is_wanted(record.get("title"), record.get("jobTitle")):
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
            yield self.api_request(
                self._data_url(f"jobs/detail/{slug}"),
                callback=self.parse_detail,
                referer=f"{self.origin}/jobs",
                headers={"x-nextjs-data": "1"},
                meta={"slug": slug},
            )

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
    # DETAIL - THE ONLY PLACE WITH A DESCRIPTION            #
    #########################################################
    def parse_detail(self, response):
        payload = self.parse_json(response)
        if payload is None:
            return

        head = dig(payload, "pageProps.jobDetail.head") or {}
        content = dig(payload, "pageProps.jobDetail.content") or {}
        if not head:
            self.logger.warning("No jobDetail.head at %s", response.url)
            return

        loader = JsonJobLoader(response=response)
        loader.add_value("job_title", head.get("title"))
        loader.add_value("job_title", head.get("jobTitle"))
        loader.add_value("job_title", self.DEFAULT_VALUE)

        loader.add_value("company", dig(head, "company.name"))
        loader.add_value("company", head.get("hiddenCompanyInfo"))
        loader.add_value("company", self.DEFAULT_VALUE)

        loader.add_value("location", head.get("location"))
        loader.add_value("location", self.DEFAULT_VALUE)

        # The detail endpoint reports whatever the employer selected, which is
        # not always what the posting is. "Bilgisayar Mühendisliği Stajyeri"
        # came back typed as Contract on a live run - an internship that would
        # then be hidden by the dashboard's Internship + Part-Time default.
        #
        # All three sites turned out to do this, so all three now let the title
        # decide: normalize_job_type ranks Internship and Part-Time above the
        # rest, so putting the title's verdict first is enough.
        type_of_works = [t for t in (head.get("typeOfWorks") or []) if t]
        title = head.get("title") or head.get("jobTitle") or ""
        if looks_like_internship(title):
            type_of_works = ["Stajyer"] + [t for t in type_of_works if t != "Stajyer"]
        elif looks_like_parttime(title):
            type_of_works = ["Yarı Zamanlı"] + [
                t for t in type_of_works if t != "Yarı Zamanlı"
            ]

        loader.add_value("job_type", ", ".join(type_of_works) or None)
        loader.add_value("job_type", self.DEFAULT_VALUE)

        # One value, not a fallback pair: this field's output processor is
        # Join(' '), so a second add_value is APPENDED rather than ignored and
        # every description would end in a stray "N/A".
        loader.add_value(
            "job_description",
            strip_html(content.get("description")) or self.DEFAULT_VALUE,
        )

        loader.add_value(
            "url", f"{self.origin}/jobs/detail/{response.meta['slug']}"
        )
        loader.add_value("source_site", self.site_name)

        yield loader.load_item()
