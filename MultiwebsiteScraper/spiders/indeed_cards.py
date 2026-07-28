"""
INDEED - EMBEDDED JSON FROM THE SEARCH PAGE
===========================================

There is no XHR to intercept on Indeed: the search page is server-rendered.
But the data is not scattered through the DOM either - it sits in the page as
plain JSON:

    window.mosaic.providerData["mosaic-provider-jobcards"]
      -> metaData.mosaicProviderJobCardsModel.results

15 records per page, each with jobkey, title, company, formattedLocation,
taxonomyAttributes and an HTML snippet. Parsing that is far steadier than
walking `div.job_seen_beacon`.

A plain request from a residential IP returns HTTP 200 with the full page -
no Cloudflare challenge, despite Indeed sitting behind Cloudflare. Worth
noting because the old spider pays ScrapeOps for JS rendering that may not be
needed; the residential proxy in api_middlewares should cover the datacenter
case on its own.

WHY THE SEARCH IS BY KEYWORD, NOT BY JOB TYPE
---------------------------------------------
Indeed has its own job-type filter, and it is not usable. Across 120 real
Istanbul internship postings the `job-types` taxonomy said:

    Staj                54        Tam zamanlı        28   <- still internships
    Yarı zamanlı        13        (empty)             5
    ...plus 20 in mixed combinations

28 postings whose only type is "Tam zamanlı" are internships with full-time
hours, and 5 declare nothing at all. Filtering on the type would have dropped
a quarter of them. Searching the WORD instead catches them regardless of how
the employer classified the post.

WHY THERE IS NO FIELD FILTER
----------------------------
Turkish companies routinely advertise one internship for the whole company
and allocate people to departments afterwards - "Intern" at UPS, "Stajyer" at
FarklıFikir Bilişim. There is no field to filter on, and guessing would throw
them away.

The field is not decided here at all. This spider keeps every internship and
part-time posting it finds in Istanbul; `classifier.py` reads each one
afterwards and marks the ones that belong to another line of work. A word
list used to do it at this point and could not be made complete - see
job_filters for the evidence.
"""

import json

from ..api_spider import BaseApiSpider, strip_html
from ..job_filters import is_wanted, looks_like_internship, looks_like_parttime
from ..loaders import JsonJobLoader

PROVIDER_KEY = "mosaic-provider-jobcards"


def extract_provider_json(text, key=PROVIDER_KEY):
    """
    Pull one `providerData["<key>"]={...}` object out of the page.

    Scanned brace by brace rather than matched with a regex: the blob is
    ~120 kB of nested JSON containing escaped quotes and braces inside string
    values, which no regex handles correctly.
    """
    marker = f'providerData["{key}"]='
    start = text.find(marker)
    if start < 0:
        return None

    start = text.find("{", start)
    if start < 0:
        return None

    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == '"':
            in_string = not in_string
        elif not in_string:
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return text[start:index + 1]
    return None


class IndeedCardsSpider(BaseApiSpider):
    name = "indeed_cards"

    site_name = "indeed.com"
    origin = "https://tr.indeed.com"
    allowed_domains = ["indeed.com"]
    warmup_url = None

    LOCATION = "İstanbul"
    PAGE_SIZE = 10          # Indeed's `start` offset step, not the record count

    # One search per term, merged afterwards. Indeed has no category taxonomy,
    # only free-text search, so a single query would miss whatever it does not
    # literally match - "stajyer" does not find "Long Term Intern".
    SEARCHES = {
        "stajyer": "stajyer",
        "intern": "intern",
        "part-time": "part time",
        "yari-zamanli": "yarı zamanlı",
    }

    # Indeed keeps serving pages well past the useful results. Stop when a page
    # brings nothing new - next_page_allowed() handles that - but cap it too.
    MAX_PAGES = 15

    custom_settings = {
        **BaseApiSpider.custom_settings,
        # The most protected of the sites and the only independent source left,
        # so it gets the gentlest treatment.
        "CONCURRENT_REQUESTS": 1,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 1,
        "DOWNLOAD_DELAY": 4,
        "RANDOMIZE_DOWNLOAD_DELAY": True,

        ###################################################################
        # TLS FINGERPRINT - THE REASON THIS SITE NEEDS SPECIAL TREATMENT  #
        ###################################################################
        '''
            Cloudflare fingerprints the TLS handshake itself (JA3/JA4), not
            just the IP and headers. Measured from one machine, one address,
            one moment, with identical headers:

                curl              -> 200
                python requests   -> 403
                Scrapy            -> 403 on every request

            Python's OpenSSL stack has a different ClientHello from a
            browser's, and Indeed rejects it before a single header is read.

            The residential proxy does NOT help here. It tunnels with CONNECT,
            so our own ClientHello still goes to the server - the address
            changes, the fingerprint does not.

            scrapy-impersonate swaps the transport for curl_cffi, which
            replays a real Chrome handshake. Verified: `chrome124` and
            `chrome131` both return 200 with 16 job cards, while the plain
            `chrome` alias still gets 403 - so the version must be pinned.

            Only this spider needs it; kariyer.net and techcareer.net are fine
            with Scrapy's own downloader.
        '''
        "DOWNLOAD_HANDLERS": {
            "http": "scrapy_impersonate.ImpersonateDownloadHandler",
            "https": "scrapy_impersonate.ImpersonateDownloadHandler",
        },
        "TWISTED_REACTOR": "twisted.internet.asyncioreactor.AsyncioSelectorReactor",

        # Impersonation gets almost everything through, but not quite all: one
        # request in a live run still came back 403, and because it was the
        # FIRST page of the "stajyer" search that single response killed the
        # whole route - no page 1, no pagination, no postings. 403 is not in
        # Scrapy's default retry list, so it is added here.
        "RETRY_HTTP_CODES": [403, 408, 429, 500, 502, 503, 504, 522, 524],
        "RETRY_TIMES": 3,
    }

    # Passed through request.meta by _search_request. Pin the version.
    IMPERSONATE = "chrome131"

    ###########################################
    # ONE SEARCH PER KEYWORD                  #
    ###########################################
    def api_requests(self):
        for search_key in self.SEARCHES:
            yield self._search_request(search_key, page=1)

    def _search_request(self, search_key, page):
        from urllib.parse import urlencode

        params = {
            "q": self.SEARCHES[search_key],
            "l": self.LOCATION,
            "start": (page - 1) * self.PAGE_SIZE,
        }
        url = f"{self.origin}/jobs?{urlencode(params)}"

        # A document request, not api_request: the response is HTML with JSON
        # inside it, so `expect_json` would make BlockDetectionMiddleware treat
        # every good page as a block.
        return self.document_request(
            url,
            callback=self.parse_search,
            referer=f"{self.origin}/",
            meta={
                "page": page,
                "search_key": search_key,
                # Tells scrapy-impersonate which browser handshake to replay.
                "impersonate": self.IMPERSONATE,
            },
            dont_filter=True,
        )

    ###########################################
    # PARSE THE EMBEDDED JSON                 #
    ###########################################
    def parse_search(self, response):
        blob = extract_provider_json(response.text)
        if not blob:
            self.logger.error(
                "No %s blob at %s (HTTP %s, %s bytes) - either the page shape "
                "changed or we were served an interstitial.",
                PROVIDER_KEY, response.url, response.status, len(response.body),
            )
            self.crawler.stats.inc_value("indeed/no_provider_data")
            return

        try:
            payload = json.loads(blob)
        except json.JSONDecodeError as error:
            self.logger.error("providerData blob is not valid JSON: %s", error)
            return

        records = (
            payload.get("metaData", {})
            .get("mosaicProviderJobCardsModel", {})
            .get("results", [])
        )

        page = response.meta["page"]
        search_key = response.meta["search_key"]
        kept = 0

        for record in records:
            title = record.get("displayTitle") or record.get("title") or ""

            # The keyword search matches the description too, so postings that
            # are neither an internship nor part-time come back as well.
            if not is_wanted(title):
                continue

            jobkey = record.get("jobkey")
            if not jobkey:
                self.crawler.stats.inc_value("items/skipped_no_url")
                continue

            self.note_discovery(jobkey, search_key)
            kept += 1
            yield self._item_from_record(record, jobkey)

        self.logger.info(
            "[%s] page %s: %s posting(s), %s kept", search_key, page,
            len(records), kept,
        )
        self.crawler.stats.inc_value("jobs/seen", len(records))

        if self.next_page_allowed(page, records, search_key):
            yield self._search_request(search_key, page + 1)

    ###########################################
    # RECORD -> ITEM                          #
    ###########################################
    def _item_from_record(self, record, jobkey):
        loader = JsonJobLoader()

        loader.add_value("job_title", record.get("displayTitle"))
        loader.add_value("job_title", record.get("title"))
        loader.add_value("job_title", self.DEFAULT_VALUE)

        loader.add_value("company", record.get("company"))
        loader.add_value("company", self.DEFAULT_VALUE)

        loader.add_value("location", record.get("formattedLocation"))
        loader.add_value("location", record.get("jobLocationCity"))
        loader.add_value("location", self.DEFAULT_VALUE)

        # taxonomyAttributes -> [{"label": "job-types", "attributes": [...]}]
        job_types = []
        for group in record.get("taxonomyAttributes") or []:
            if group.get("label") == "job-types":
                job_types = [a.get("label") for a in group.get("attributes") or []]
                break

        # An internship whose employer only ticked "Tam zamanlı" would
        # normalise to Full-Time and then be hidden by the dashboard, which
        # defaults to Internship + Part-Time. That was 19 of 72 postings on a
        # sampled run - "STAJYER DANISMA", "Finance Intern" and the like, all
        # found BY the internship search. A full-time internship is still an
        # internship, so the title's verdict is put first and
        # normalize_job_type ranks Internship above Full-Time.
        title = record.get("displayTitle") or record.get("title") or ""
        if looks_like_internship(title):
            job_types = ["Staj"] + [t for t in job_types if t != "Staj"]
        elif looks_like_parttime(title):
            job_types = ["Yarı zamanlı"] + [
                t for t in job_types if t != "Yarı zamanlı"
            ]

        loader.add_value("job_type", ", ".join(t for t in job_types if t) or None)
        loader.add_value("job_type", self.DEFAULT_VALUE)

        # `snippet` is an excerpt, not the full text. Enough for the dashboard
        # to be readable, and it costs no extra request - which matters on the
        # site most likely to block us, and the only independent source we have
        # left. Fetch /viewjob?jk=<key> per posting if the full text is ever
        # needed, at roughly 75 extra requests a day.
        #
        # Set in one go rather than with a fallback add_value: this field's
        # output processor is Join(' '), so a second value is APPENDED rather
        # than ignored, and the fallback would leave "...18:00 ). N/A".
        loader.add_value(
            "job_description",
            strip_html(record.get("snippet")) or self.DEFAULT_VALUE,
        )

        loader.add_value("url", f"{self.origin}/viewjob?jk={jobkey}")
        loader.add_value("source_site", self.site_name)

        return loader.load_item()
