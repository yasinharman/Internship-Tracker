"""
LINKEDIN - EVERY INTERNSHIP IN GREATER ISTANBUL, AS A GUEST
============================================================

    python -m scrapy crawl linkedin_cards        (only from the pool - see below)

NO ACCOUNT, SINCE 22.09.2026
----------------------------
Until 16.09.2026 this spider drove a burner account's signed-in search. Two
burners were restricted that day, the second before it made a request, and
LinkedIn left the flow (docs/sites/linkedin.md). The owner's line since
21.09: no burner accounts, on any site. That code is in git history.

What brought LinkedIn back is a measurement, 22.09.2026, made with no account
through the bought IP pool:

  * `/jobs/search/?keywords=stajyer&geoId=90010422` is served to a guest -
    "(531 Açık Pozisyon)", 60 cards, 60 of 60 internship titles;
  * the guest endpoint the page scrolls with,
    `/jobs-guest/jobs/api/seeMoreJobPostings/search?...&start=N`, answers a
    guest with 10 cards - start=60 brought 10 new ones;
  * a posting page, `/jobs/view/<id>/`, is served whole to a guest -
    description, company, criteria (linkedin_check reads it).

And one thing that does NOT work for a guest: `f_E=1`, the experience
filter. With it and no keyword the page was "3,000+" results and 0 of 60
internships. So the search is a keyword, like Indeed's, and the title filter
below still has the last word.

THE RULES THIS FILE KEEPS
-------------------------
  * No session, ever: STORAGE_STATE_ENV = None, and no cookie export is
    read. There is nothing for a restriction to land on.
  * Only from the pool. The spider refuses to start unless it is listed in
    PROXY_POOL_SPIDERS, so no LinkedIn request leaves the home address - the
    address two restricted accounts were tied to.
  * The pace is the burner era's: one request at a time, 8 s apart.

WHAT A RUN IS
-------------
    1 page      the search page, 60 cards, and the total ("531")
    N batches   the guest endpoint from start=60, 10 cards each, until the
                total is reached, a batch comes back empty or repeated, or
                MAX_PAGES

"stajyer" at 531 is 1 + 47 requests. The description is not on a card; it is
linkedin_check's job, one posting page per posting.
"""

import re
from urllib.parse import urlencode

from ..api_middlewares import pool_spiders
from ..api_spider import BaseApiSpider, logo_url
from ..job_filters import looks_like_internship
from ..loaders import JsonJobLoader

# The total on the search page's header, "531" or "3.000+".
TOTAL = re.compile(r"(\d[\d.]*)")


class LinkedinCardsSpider(BaseApiSpider):
    name = "linkedin_cards"

    site_name = "linkedin.com"
    origin = "https://www.linkedin.com"
    allowed_domains = ["linkedin.com"]

    # The search page IS the first navigation - a guest has no feed to warm
    # up on, and the page is what a visitor would open first.
    warmup_url = None

    # No account can ever be loaded - see playwright_middleware.py.
    STORAGE_STATE_ENV = None

    # A real browser, windowed: the measurement was taken that way, and a
    # changed transport would be a second variable.
    USE_PLAYWRIGHT = True
    NEEDS_A_WINDOW = True

    # "Greater Istanbul" - a place name in `location=` does not filter
    # (docs/sites/linkedin.md, "The location filter does not work by name").
    GEO_ID = "90010422"
    SEARCHES = {"stajyer": "stajyer"}

    FIRST_PAGE_CARDS = 60     # the search page, measured 22.09.2026
    BATCH_SIZE = 10           # the guest endpoint, measured 22.09.2026

    # A circuit breaker, not the depth: the total on page one is the depth.
    # 531 postings are 48 requests; 100 leaves room without running on.
    MAX_PAGES = 100

    custom_settings = {
        **BaseApiSpider.custom_settings,
        "CONCURRENT_REQUESTS": 1,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 1,
        "DOWNLOAD_DELAY": 8,
        "RANDOMIZE_DOWNLOAD_DELAY": True,
        "TWISTED_REACTOR": "twisted.internet.asyncioreactor.AsyncioSelectorReactor",
        "DOWNLOAD_TIMEOUT": 45,
        # 429 is how LinkedIn asks for less; the pool answers it by resting
        # the address (BlockDetectionMiddleware sees it before a retry would).
        "RETRY_HTTP_CODES": [403, 408, 429, 500, 502, 503, 504, 522, 524],
        "RETRY_TIMES": 2,
    }

    def __init__(self, *args, **kwargs):
        if self.name not in pool_spiders():
            raise RuntimeError(
                f"{self.name} only runs from the bought IP pool - add it to "
                f"PROXY_POOL_SPIDERS. LinkedIn is never asked from the home "
                f"address (docs/sites/linkedin.md)."
            )
        super().__init__(*args, **kwargs)
        # search -> the total its search page announced.
        self._totals = {}

    ###################################################################
    # THE REQUESTS                                                    #
    ###################################################################
    def api_requests(self):
        for search in self.SEARCHES:
            yield self._search_page(search)

    def _search_url(self, search):
        return f"{self.origin}/jobs/search/?" + urlencode(
            {"keywords": self.SEARCHES[search], "geoId": self.GEO_ID}
        )

    def _search_page(self, search):
        return self.document_request(
            self._search_url(search), callback=self.parse_cards,
            meta={"search_key": search, "page": 1},
        )

    def _batch(self, search, page):
        start = self.FIRST_PAGE_CARDS + (page - 2) * self.BATCH_SIZE
        url = f"{self.origin}/jobs-guest/jobs/api/seeMoreJobPostings/search?" + urlencode(
            {"keywords": self.SEARCHES[search], "geoId": self.GEO_ID, "start": start}
        )
        # Referred by the search page, as the page's own script is.
        return self.document_request(
            url, callback=self.parse_cards, referer=self._search_url(search),
            meta={"search_key": search, "page": page, "start": start},
        )

    def page_actions(self, page, request):
        """
        Wait for the cards rather than read the page on DOMContentLoaded.
        A batch that is genuinely empty ends the search in next_page_allowed;
        this only stops a slow page from reading as an empty one.
        """
        try:
            page.wait_for_selector("div.base-search-card, div.base-card", timeout=15000)
        except Exception:
            self.crawler.stats.inc_value("linkedin/no_cards_rendered")

    ###################################################################
    # THE CARDS                                                       #
    ###################################################################
    def record_key(self, record):
        return record.get("id") or super().record_key(record)

    def parse_cards(self, response):
        search = response.meta["search_key"]
        page = response.meta["page"]

        if page == 1:
            header = response.css(".results-context-header__job-count::text").get() or ""
            found = TOTAL.search(header)
            if found and "+" not in header:
                self._totals[search] = int(found.group(1).replace(".", ""))
            self.logger.info("[%s] %s result(s) in all", search, header.strip() or "?")

        records = []
        kept = 0
        for card in response.css("div.base-search-card, div.base-card"):
            urn = card.attrib.get("data-entity-urn", "")
            job_id = urn.rsplit(":", 1)[-1] if urn else None
            if not job_id:
                self.crawler.stats.inc_value("items/skipped_no_url")
                continue
            title = (card.css("h3.base-search-card__title::text").get() or "").strip()
            records.append({"id": job_id})
            # The keyword also matches descriptions; the title decides.
            if not looks_like_internship(title):
                continue
            kept += 1
            self.note_discovery(job_id, search)
            yield self._item(card, job_id, title)

        self.logger.info("[%s] page %s: %s card(s), %s kept", search, page, len(records), kept)
        self.crawler.stats.inc_value("jobs/seen", len(records))

        if self.next_page_allowed(page, records, search):
            yield self._batch(search, page + 1)

    def next_page_allowed(self, page, records, search_key="default"):
        if not super().next_page_allowed(page, records, search_key):
            return False
        total = self._totals.get(search_key)
        reached = self.FIRST_PAGE_CARDS + (page - 1) * self.BATCH_SIZE
        if total is not None and reached >= total:
            self.logger.info(
                "[%s] %s of %s reached - stopping", search_key, min(reached, total), total,
            )
            self.crawler.stats.inc_value("pagination/reached_total")
            return False
        return True

    def _posting_url(self, job_id):
        """The canonical url - the upsert key, and what linkedin_check opens."""
        return f"{self.origin}/jobs/view/{job_id}/"

    def _item(self, card, job_id, title):
        loader = JsonJobLoader()
        loader.add_value("job_title", title or self.DEFAULT_VALUE)

        company = (
            card.css("h4.base-search-card__subtitle a::text").get()
            or card.css("h4.base-search-card__subtitle::text").get() or ""
        ).strip()
        loader.add_value("company", company or self.DEFAULT_VALUE)

        # On the search page the logo is in `src` once lazy-loaded; in a
        # guest batch it waits in `data-delayed-url`. Both measured 22.09.
        # An employer with no logo gets LinkedIn's grey placeholder, served
        # from static.licdn.com/aero-v1/sc/h/ - not a logo, so not stored.
        image = card.css("img.artdeco-entity-image")
        source = None
        if image:
            source = image.attrib.get("src") or image.attrib.get("data-delayed-url")
        if source and "/aero-v1/sc/h/" in source:
            source = None
        logo = logo_url(source, base=self.origin)
        loader.add_value("company_logo_url", logo)
        self.crawler.stats.inc_value("logo/found" if logo else "logo/missing")

        location = (card.css("span.job-search-card__location::text").get() or "").strip()
        loader.add_value("location", location or self.DEFAULT_VALUE)

        loader.add_value("job_type", "Staj")
        # Set once: job_description_out joins, so a fallback value would be
        # appended. The description is linkedin_check's.
        loader.add_value("job_description", self.DEFAULT_VALUE)
        loader.add_value("url", self._posting_url(job_id))
        loader.add_value("source_site", self.site_name)
        return loader.load_item()
