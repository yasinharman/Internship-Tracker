"""
What the Indeed crawl asks for, and what it stores as a description.

The crawl requests the home page once and then search result pages, and
nothing else. The description arrives later, from indeed_check's /viewjob
request - so a card item carries "N/A", which is what pipelines.py and
indeed_check.lacks_description() both read as "not described yet".

MEASURED 16.09.2026 (docs/sites/indeed.md, "Refused on the detail pages"):
the crawl and the checker together had sent 145 requests to tr.indeed.com
when Cloudflare refused the next one. The crawl alone must stay well inside
that.

Nothing here opens a browser or sends a request: a search page is built in
memory and handed to parse_search.
"""

import json
import logging
from collections import defaultdict
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlparse

from scrapy import Request
from scrapy.http import HtmlResponse

import scraper.settings as project_settings
from scraper.spiders.indeed_cards import PROVIDER_KEY, IndeedCardsSpider

SEARCH_URL = (
    "https://tr.indeed.com/jobs?q=yaz%C4%B1l%C4%B1m+stajyer"
    "&l=%C4%B0stanbul&start=0"
)

# The lowest count at which Indeed has refused this address in one night.
# One observation (16.09.2026); on 15.09 the address got to 153 responses
# without a refusal, so this is where a refusal has been seen, not a wall.
REFUSED_AFTER = 145


def _spider(signed_in=True):
    spider = IndeedCardsSpider.__new__(IndeedCardsSpider)
    spider.session_cookies = {"SOCK": "x"} if signed_in else {}
    spider.impersonate_candidates = ["firefox147"]
    spider.session = MagicMock()
    spider.session.document_headers.return_value = {}
    spider._seen_keys = defaultdict(set)
    spider._repeated_pages = defaultdict(int)
    spider._discovery = defaultdict(set)
    spider.crawler = MagicMock()
    spider.__dict__["logger"] = logging.getLogger("indeed-listing-test")
    return spider


def _search_page(records, page=1, search_key="yazilim-stajyer"):
    payload = {"metaData": {"mosaicProviderJobCardsModel": {"results": records}}}
    body = (
        "<html><script>window.mosaic.providerData"
        f'["{PROVIDER_KEY}"]={json.dumps(payload)};</script></html>'
    )
    request = Request(SEARCH_URL, meta={"page": page, "search_key": search_key})
    return HtmlResponse(SEARCH_URL, body=body, encoding="utf-8", request=request)


def _card(jobkey, title="Yazılım Stajyeri", snippet="<ul><li>Python bilen</li></ul>"):
    return {
        "jobkey": jobkey,
        "displayTitle": title,
        "company": "Bir Firma",
        "formattedLocation": "İstanbul",
        "taxonomyAttributes": [
            {"label": "job-types", "attributes": [{"label": "Staj"}]},
        ],
        "snippet": snippet,
    }


def _parse(spider, records, page=1):
    output = list(spider.parse_search(_search_page(records, page)))
    items = [o for o in output if not isinstance(o, Request)]
    requests = [o for o in output if isinstance(o, Request)]
    return items, requests


class TestTheDescription:

    def test_a_card_stores_na_even_when_it_carries_a_snippet(self):
        # A snippet stored here would be written over the checker's full text
        # on every re-crawl, and would read as "described" to indeed_check.
        items, _ = _parse(_spider(), [_card("a1"), _card("b2", snippet="")])
        assert [item["job_description"] for item in items] == ["N/A", "N/A"]

    def test_the_stored_url_is_the_posting_page_the_checker_opens(self):
        items, _ = _parse(_spider(), [_card("a1")])
        assert items[0]["url"] == "https://tr.indeed.com/viewjob?jk=a1"


class TestWhatTheCrawlRequests:

    def test_a_search_page_asks_only_for_the_next_search_page(self):
        spider = _spider()
        _, requests = _parse(spider, [_card(f"k{n}") for n in range(15)])

        assert len(requests) == 1
        asked = urlparse(requests[0].url)
        assert asked.path == "/jobs"
        assert parse_qs(asked.query)["start"] == ["10"]
        assert parse_qs(asked.query)["q"] == ["yazılım stajyer"]
        # Referred by the page it came from, as a browser would be.
        spider.session.document_headers.assert_called_with(referer=SEARCH_URL)

    def test_no_posting_page_is_requested_during_the_crawl(self):
        _, requests = _parse(_spider(), [_card(f"k{n}") for n in range(15)])
        assert not [r for r in requests if "/viewjob" in r.url]

    def test_an_anonymous_crawl_stops_at_page_one(self):
        _, requests = _parse(_spider(signed_in=False), [_card("a1")])
        assert requests == []

    def test_the_first_pages_are_one_per_search_and_nothing_else(self):
        spider = _spider()
        urls = [request.url for request in spider.api_requests()]

        assert len(urls) == len(IndeedCardsSpider.SEARCHES)
        for url in urls:
            parsed = urlparse(url)
            assert parsed.netloc == "tr.indeed.com"
            assert parsed.path == "/jobs"
            assert parse_qs(parsed.query)["start"] == ["0"]
            assert parse_qs(parsed.query)["l"] == ["İstanbul"]


class TestTheRequestBudget:

    def test_the_crawl_at_its_ceiling_stays_under_the_16_09_refusal(self):
        # warm-up, every search to MAX_PAGES, and every refusal the block
        # budget allows before it ends the run (a 429 counts as one).
        spider = IndeedCardsSpider
        budget = spider.custom_settings.get(
            "DOMAIN_BLOCK_BUDGET", project_settings.DOMAIN_BLOCK_BUDGET,
        )
        ceiling = 1 + len(spider.SEARCHES) * spider.MAX_PAGES + budget
        assert ceiling < REFUSED_AFTER, (
            f"indeed_cards can send {ceiling} requests in one run; Indeed "
            f"refused this address after {REFUSED_AFTER} on 16.09.2026"
        )
