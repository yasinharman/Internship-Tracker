"""
YOUTHALL - THE INTERNSHIPS ON THE ISTANBUL LIST
===============================================

    python -m scrapy crawl youthall_cards

Added 22.09.2026. Measured the same day before a line of this was written
(docs/sites/youthall.md): server-rendered pages, no JSON API, served whole to
a visitor with no account.

ONE PAGE IS THE WHOLE CITY
--------------------------
The site is small - about 33 open listings, 17 of them in Istanbul - and it
keeps a page per city, `/en/jobs/istanbul/`. On 22.09.2026 that page held all
17 and linked to no page 2. So a run is one request. Pagination is followed
only if the page itself links to the next one.

NOT EVERY CARD IS AN INTERNSHIP
-------------------------------
Youthall also lists graduate and trainee programmes, and each card names a
type. The 17 Istanbul cards on 22.09.2026:

    Internship           12   all with an internship title
    Part-Time Jobs        2   one of them Hyundai's "HGenius Long Term
                              Internship Program" - an internship filed under
                              the wrong type
    Full Time             1   "Hukuk Asistanı / Adalet MYO Mezunu"
    Management Trainee    2   BİM, YEO

The owner's rule is internships only. A card is kept when its type says
Internship OR its title reads as one: 13 of 17, the Hyundai programme
included, the trainee programmes out.

The description is not on the card; youthall_check reads it from the
posting page's schema.org JobPosting.
"""

import re
from urllib.parse import urljoin, urlsplit

from ..api_spider import BaseApiSpider, logo_url
from ..job_filters import looks_like_internship
from ..loaders import JsonJobLoader


class YouthallCardsSpider(BaseApiSpider):
    name = "youthall_cards"

    site_name = "youthall.com"
    origin = "https://www.youthall.com"
    allowed_domains = ["youthall.com"]

    # The list page is the first thing a visitor opens anyway.
    warmup_url = None

    # There is no account to carry.
    STORAGE_STATE_ENV = None

    # The transport the measurement used - a windowed Chromium. A lighter one
    # may well work on a server-rendered site; that would be a second
    # variable, measured on its own.
    USE_PLAYWRIGHT = True
    NEEDS_A_WINDOW = True

    LIST_URL = "https://www.youthall.com/en/jobs/istanbul/"
    MAX_PAGES = 10

    custom_settings = {
        **BaseApiSpider.custom_settings,
        "CONCURRENT_REQUESTS": 1,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 1,
        "DOWNLOAD_DELAY": 8,
        "RANDOMIZE_DOWNLOAD_DELAY": True,
        "TWISTED_REACTOR": "twisted.internet.asyncioreactor.AsyncioSelectorReactor",
        "DOWNLOAD_TIMEOUT": 45,
    }

    def api_requests(self):
        yield self._list_page(1)

    def _list_page(self, page):
        url = self.LIST_URL if page == 1 else f"{self.LIST_URL}?page={page}"
        return self.document_request(
            url, callback=self.parse_list, meta={"page": page, "search_key": "istanbul"},
        )

    def record_key(self, record):
        return record.get("url") or super().record_key(record)

    @staticmethod
    def canonical(href, base):
        """The posting url without query or fragment - the upsert key."""
        parts = urlsplit(urljoin(base, href))
        return f"{parts.scheme}://{parts.netloc}{parts.path}"

    def parse_list(self, response):
        page = response.meta["page"]
        records = []
        kept = 0

        for card in response.css("div.jobs"):
            href = card.css("a::attr(href)").get()
            if not href or not re.search(r"_\d+/?$", href.split("?")[0]):
                continue
            url = self.canonical(href, response.url)
            records.append({"url": url})

            title = (card.css(".jobs-content-title h5::text").get() or "").strip()
            tags = [" ".join(t.split()) for t in card.css(".jobs-tag").xpath("string()").getall()]
            kind = tags[0] if tags else ""
            if kind != "Internship" and not looks_like_internship(title):
                self.crawler.stats.inc_value("cards/not_internship")
                continue

            kept += 1
            self.note_discovery(url, "istanbul")
            yield self._item(card, url, title, tags)

        self.logger.info("[istanbul] page %s: %s card(s), %s kept", page, len(records), kept)
        self.crawler.stats.inc_value("jobs/seen", len(records))

        if (
            self.next_page_allowed(page, records, "istanbul")
            and f"page={page + 1}" in response.text
        ):
            yield self._list_page(page + 1)

    def _item(self, card, url, title, tags):
        loader = JsonJobLoader()
        loader.add_value("job_title", title or self.DEFAULT_VALUE)

        # The company is only on the card as its logo's alt text,
        # "Hyundai Motor Türkiye logo".
        company = (card.css("img.jobs-content-logo::attr(alt)").get() or "").strip()
        company = company.removesuffix(" logo").strip()
        loader.add_value("company", company or self.DEFAULT_VALUE)

        logo = logo_url(card.css("img.jobs-content-logo::attr(src)").get(), base=self.origin)
        loader.add_value("company_logo_url", logo)
        self.crawler.stats.inc_value("logo/found" if logo else "logo/missing")

        # The third tag is the city, "İstanbul" or "İstanbul +" for a posting
        # in several. This is the Istanbul page, so the "+" says nothing new.
        city = tags[2].rstrip(" +").strip() if len(tags) > 2 else ""
        loader.add_value("location", city or "İstanbul")

        loader.add_value("job_type", "Staj")
        # Set once: job_description_out joins. The description is youthall_check's.
        loader.add_value("job_description", self.DEFAULT_VALUE)
        loader.add_value("url", url)
        loader.add_value("source_site", self.site_name)
        return loader.load_item()
