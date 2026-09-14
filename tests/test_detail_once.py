"""
kariyer.net opens a posting page once, not every night.

MEASURED 10.09.2026: the site refuses this crawl somewhere around its 35th
request, and ~46 of them were being spent re-reading descriptions already
stored. A description does not change, so the posting page is worth a request
the first time and nothing after it.

The three cases below are the whole rule, and the third is the one a
url-only check would have got wrong: twelve postings that day were refused
and stored with "N/A", and "skip anything already in the database" would have
left them without a description forever.

Nothing here touches the network or the database - `described_urls` is
replaced with the answer it would have returned.
"""

from collections import defaultdict

import pytest
from scrapy.http import HtmlResponse, Request

from scraper.spiders.kariyernet_cards import KariyerNetCardsSpider


CARD = """
<div data-test="ad-card" worktypeid="P" positionname="Stajyer"
     cityname="İstanbul(Avr.)" worktypetext="Yarı zamanlı">
  <a data-test="ad-card-item" href="/is-ilani/bir-firma-stajyer-{n}"></a>
  <span data-test="ad-card-title">Yazılım Stajyeri {n}</span>
  <img data-test="company-image" alt="Bir Firma"
       src="https://img-kariyer.mncdn.com/logo{n}.png">
  <span data-test="location">İstanbul(Avr.)</span>
  <span data-test="subtitle">Bir Firma</span>
</div>
"""

SEARCH_URL = "https://www.kariyer.net/is-ilanlari/stajyer?ct=34,82"


class _Stats:
    def __init__(self):
        self.values = {}

    def inc_value(self, key, count=1, start=0):
        self.values[key] = self.values.get(key, start) + count

    def set_value(self, key, value):
        self.values[key] = value


class _Crawler:
    def __init__(self):
        self.stats = _Stats()


def _spider(described):
    """
    The spider with just enough of BaseApiSpider.__init__ done by hand.

    Built with object.__new__ because the real constructor opens a
    BrowserSession, and none of that is involved in deciding whether a
    posting page is worth fetching.
    """
    from scraper.browser_session import BrowserSession, pick_profile

    spider = object.__new__(KariyerNetCardsSpider)
    spider.crawler = _Crawler()
    spider._seen_keys = defaultdict(set)
    spider._discovery = defaultdict(set)
    spider._described_urls = set(described)
    # document_request builds its headers from this. Constructing one touches
    # nothing outside the process.
    spider.session = BrowserSession(
        profile=pick_profile("chrome-151-linux"),
        origin=KariyerNetCardsSpider.origin,
    )
    return spider


def _listing(how_many=2):
    body = "<html><body>" + "".join(
        CARD.format(n=n) for n in range(1, how_many + 1)
    ) + "</body></html>"
    request = Request(SEARCH_URL, meta={"page": 1, "search_key": "staj"})
    return HtmlResponse(SEARCH_URL, body=body, encoding="utf-8",
                        request=request)


def _split(spider, response):
    """What parse_listing produced, sorted into items and requests."""
    items, requests = [], []
    for out in spider.parse_listing(response):
        (requests if isinstance(out, Request) else items).append(out)
    # The pagination request is not a posting page; drop it.
    requests = [r for r in requests if "/is-ilani/" in r.url]
    return items, requests


def test_a_posting_with_no_description_yet_is_fetched():
    spider = _spider(described=[])
    items, requests = _split(spider, _listing(2))

    assert len(requests) == 2, "both postings are new, both should be opened"
    assert spider.crawler.stats.values.get("detail/fetched") == 2
    # And stored from the card at the same time - see the next test.
    assert len(items) == 2


def test_a_posting_that_already_has_one_is_not_opened_again():
    described = ["https://www.kariyer.net/is-ilani/bir-firma-stajyer-1"]
    spider = _spider(described=described)
    items, requests = _split(spider, _listing(2))

    assert len(requests) == 1, "only the posting without a description"
    assert requests[0].url.endswith("stajyer-2")
    assert spider.crawler.stats.values.get("detail/already_described") == 1


def test_every_card_is_stored_whatever_happens_to_its_posting_page():
    """
    MEASURED 12.09.2026: 46 cards were kept and 24 rows were written, because
    parse_detail was the only place an item was yielded and the rest of the
    posting pages were refused. A title, a company, a city, a work type, a logo and a link
    - all of it already collected from the card - were thrown away because
    one field was missing.

    So the card goes in from parse_listing, always, and the description
    catches up whenever the posting page answers. This is also what keeps
    pipelines.py stamping last_seen_at, which is the evidence that a posting
    is still on the board.
    """
    described = ["https://www.kariyer.net/is-ilani/bir-firma-stajyer-1"]
    spider = _spider(described=described)
    items, requests = _split(spider, _listing(2))

    assert len(items) == 2, "both cards stored: one described, one waiting"
    assert {i["url"] for i in items} == {
        "https://www.kariyer.net/is-ilani/bir-firma-stajyer-1",
        "https://www.kariyer.net/is-ilani/bir-firma-stajyer-2",
    }
    # ...and only the undescribed one costs a request.
    assert len(requests) == 1
    assert requests[0].url.endswith("stajyer-2")


def test_the_detail_request_gets_its_own_copy_of_the_item():
    """
    The item above has already gone to the pipeline by then. parse_detail adds
    the description to what it is handed and yields it again, so handing it
    the same object would be mutating a row mid-flight.
    """
    spider = _spider(described=[])
    items, requests = _split(spider, _listing(1))

    assert requests[0].meta["partial_item"] is not items[0]
    assert requests[0].meta["partial_item"]["url"] == items[0]["url"]


def test_the_skipped_item_says_nothing_about_the_description():
    """
    Absent, not "N/A". pipelines.py would ignore either, but only one of them
    is true: this item has nothing to say about that column.
    """
    described = ["https://www.kariyer.net/is-ilani/bir-firma-stajyer-1"]
    spider = _spider(described=described)
    items, _ = _split(spider, _listing(1))

    assert "job_description" not in items[0]


def test_a_database_that_cannot_be_read_fetches_everything():
    """
    The safe direction to fail in. Skipping fetches on a failed query would
    quietly collect nothing while every spider still exited 0.
    """
    spider = object.__new__(KariyerNetCardsSpider)
    spider.crawler = _Crawler()
    spider._described_urls = None

    def explode():
        raise RuntimeError("no database here")

    import scraper.models

    original = scraper.models.db_connect
    scraper.models.db_connect = lambda: explode()
    try:
        assert spider.described_urls() == set()
    finally:
        scraper.models.db_connect = original
