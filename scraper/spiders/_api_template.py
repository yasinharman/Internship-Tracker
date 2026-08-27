"""
TEMPLATE FOR A JSON-API SPIDER  --  COPY THIS FILE, DO NOT EDIT IT
=================================================================

How to fill it in, per site:

 1. Open the job board in Chrome, DevTools -> Network -> Fetch/XHR, then run
    a search and page through the results.
 2. Find the request that carries the postings. Right-click -> Copy -> Copy as
    cURL. That gives you the URL, the method, the body and every header.
 3. Drop the boilerplate headers (accept-encoding, sec-fetch-*, user-agent,
    cookie...) - BaseApiSpider already sends those, consistently. Keep only
    the site-specific ones (x-api-key, authorization, x-build-id, ...) and put
    them in `api_headers`.
 4. Look at the JSON response. `results_path` is the dotted path to the array
    of postings; `field_map` maps our columns onto each record.
 5. Run it with dumps on while iterating:
        API_DEBUG_DUMP=1 scrapy crawl <name> -s CLOSESPIDER_ITEMCOUNT=5
    Raw bodies land in debug/<name>/ so you can inspect the real shape.

This template is not registered in main.py's SPIDERS list, so it never runs
in production.
"""

from urllib.parse import urlencode

from ..api_spider import BaseApiSpider, dig


class ApiTemplateSpider(BaseApiSpider):
    name = "api_template"

    # ---- identity ----------------------------------------------------------
    site_name = "example.com"                    # goes into job_posts.source_site
    origin = "https://www.example.com"           # Origin / Referer base
    warmup_url = "https://www.example.com/is-ilanlari"   # None to skip warm-up

    allowed_domains = ["example.com"]

    # ---- the endpoint ------------------------------------------------------
    API_URL = "https://www.example.com/api/v1/job-search"

    # Only headers that a generic XHR would NOT have. Copy from DevTools.
    api_headers = {
        # "x-api-key": "...",
        # "x-client-version": "...",
    }

    # ---- response shape ----------------------------------------------------
    results_path = "data.jobs"      # None if the body itself is the array

    field_map = {
        "job_title": "title",
        "company": "company.name",
        "location": "location.city",
        "job_type": "workingType",
        "job_description": "description",        # HTML is stripped for us
        "url": lambda record, response: (
            f"https://www.example.com/ilan/{record.get('id')}"
        ),
        # "source_site" is filled from site_name automatically.
    }

    # ---- crawl scope -------------------------------------------------------
    '''
        Everything below is filtered at the SOURCE, not after downloading.
        Asking the site for exactly what we want means a fraction of the
        bandwidth (residential proxy traffic is metered), far fewer requests to
        be blocked on, and a result set small enough to paginate to the end
        without ever hitting the site's pagination cap.

        Every value here is site-specific and has to be read off DevTools -
        each board invents its own ids ("3", "INTERNSHIP", "staj", 25, ...).
        Record what you find in docs/sites/ so the magic numbers stay
        explainable six months from now.
    '''

    # AXIS 1 - the field. The site's own category id for software/IT roles.
    # Preferred over a keyword search: a keyword misses adjacent stacks and
    # also matches the description text, while the category is the site's own
    # curated classification. Include neighbouring categories if the site
    # splits software from data/devops/QA.
    FIELD_FILTER = ["IT"]

    # AXIS 2 - the employment type we actually want.
    JOB_TYPE_FILTER = ["INTERNSHIP", "PART_TIME"]

    # AXIS 3 - where. Istanbul only. The id is site-specific: kariyer.net uses
    # the licence-plate number (34), others use their own codes.
    #
    # NOTE: this excludes remote roles advertised under another city. Boards
    # tag remote inconsistently, so if the dashboard looks thin, widening this
    # is the first thing to try.
    LOCATION_FILTER = ["34"]      # empty list = country-wide

    PAGE_SIZE = 25

    # MAX_PAGES is inherited from BaseApiSpider as a circuit breaker (200).
    # Do not use it as a page limit: next_page_allowed() decides when to stop,
    # and it stops on an empty page or on a page with nothing new.

    custom_settings = {
        **BaseApiSpider.custom_settings,
        # A JSON endpoint is cheap for the site to serve compared to rendering
        # HTML, but stay polite: this is still their infrastructure.
        "CONCURRENT_REQUESTS": 2,
        "DOWNLOAD_DELAY": 1.5,
        "RANDOMIZE_DOWNLOAD_DELAY": True,
    }

    ##########################################################
    # OPTIONAL: PULL A TOKEN OUT OF THE WARM-UP PAGE'S HTML  #
    ##########################################################
    def on_warmup(self, response):
        """
        Many SPAs embed the API key or a build id in the page. Grab it here and
        it will be attached to every later API call.

            build_id = response.css('script#__NEXT_DATA__::text').re_first(r'"buildId":"(.*?)"')
            if build_id:
                self.api_headers = {**self.api_headers, "x-build-id": build_id}
        """
        return None

    ####################################
    # FIRST PAGE OF EACH SEARCH        #
    ####################################
    def api_requests(self):
        # One search per field category. Job type and location go in as
        # filters on each search rather than as extra loops, so the number of
        # requests stays proportional to the number of categories.
        for field in self.FIELD_FILTER:
            yield self._search_request(field=field, page=1)

    def _search_request(self, field, page):
        # ---- GET with query string -----------------------------------------
        params = {
            "categoryId": field,
            "workingType": ",".join(self.JOB_TYPE_FILTER),
            "page": page,
            "pageSize": self.PAGE_SIZE,
        }
        if self.LOCATION_FILTER:
            params["city"] = ",".join(self.LOCATION_FILTER)

        url = f"{self.API_URL}?{urlencode(params)}"

        # Identifies this search across its pages, so repeated-page detection
        # is per search rather than global.
        search_key = f"field={field}"

        return self.api_request(
            url=url,
            callback=self.parse_search,
            # The page a real user would be on when this fires. Endpoints check it.
            referer=f"{self.origin}/is-ilanlari",
            meta={
                "field": field,
                "page": page,
                "search_key": search_key,
            },
        )

        # ---- POST with a JSON body (comment the GET above and use this) -----
        # return self.api_request(
        #     url=self.API_URL,
        #     callback=self.parse_search,
        #     json_body={
        #         "keyword": keyword,
        #         "filters": {"cityId": city},
        #         "pagination": {"page": page, "size": self.PAGE_SIZE},
        #     },
        #     referer=f"{self.origin}/is-ilanlari",
        #     meta={"keyword": keyword, "city": city, "page": page},
        # )

    #############################
    # PARSE ONE PAGE OF RESULTS #
    #############################
    def parse_search(self, response):
        payload = self.parse_json(response)
        if payload is None:
            return          # parse_json already logged what actually arrived

        records = self.extract_records(payload)
        page = response.meta["page"]
        self.logger.info("page %s -> %s posting(s)", page, len(records))

        for record in records:
            item = self.build_item(record, response)
            if item is None:
                continue    # no url on the record; already logged

            # If the search response has everything we need, yield it now:
            yield item

            # If the description only exists on a detail endpoint, do this
            # instead of the yield above:
            # yield self.api_request(
            #     url=f"{self.API_URL}/{record['id']}",
            #     callback=self.parse_detail,
            #     referer=item["url"],
            #     meta={"partial_item": item},
            # )

        # ---- pagination ----------------------------------------------------
        # No page limit: the search is already narrowed by JOB_TYPE_FILTER, so
        # we take everything it returns. next_page_allowed() ends the loop on
        # an empty page, on a page containing nothing new (an API that answers
        # out-of-range pages with page 1 would otherwise loop forever), or at
        # the MAX_PAGES circuit breaker.
        if self.next_page_allowed(page, records, response.meta["search_key"]):
            yield self._search_request(
                field=response.meta["field"],
                page=page + 1,
            )

    ###############################################
    # OPTIONAL SECOND HOP: THE DETAIL ENDPOINT    #
    ###############################################
    def parse_detail(self, response):
        payload = self.parse_json(response)
        if payload is None:
            return

        item = response.meta["partial_item"]
        item["job_description"] = dig(payload, "data.description") or item.get(
            "job_description"
        )
        yield item
