"""
kariyer.net's crawl reads listing pages and nothing else - since 21.09.2026.

The owner's shape for every crawl spider: request the filtered search pages,
yield the postings on their cards, open no posting page. The description is
read afterwards by kariyernet_check, which opens every posting page anyway for
its verdict.

What that replaced, and why it is safe, is in docs/sites/kariyernet.md ("The
crawl stops opening posting pages"). In short: from 12.09.2026 the crawl opened
a posting page once per posting for its description (this file was
tests/test_detail_once.py then), and every one of those pages was opened again
the same night by the checker.

Nothing here touches the network or the database.
"""

from collections import defaultdict

import pytest
from scrapy.http import HtmlResponse, Request

from scraper.spiders.kariyernet_cards import KariyerNetCardsSpider
from scraper.spiders.kariyernet_check import KariyerNetCheckSpider


CARD = """
<div data-test="ad-card" worktypeid="{code}" positionname="{title}"
     cityname="İstanbul(Avr.)" worktypetext="{text}">
  <a data-test="ad-card-item" href="/is-ilani/bir-firma-stajyer-{n}"></a>
  <span data-test="ad-card-title">{title} {n}</span>
  <img data-test="company-image" alt="Bir Firma A.Ş."
       src="https://img-kariyer.mncdn.com/logo{n}.png">
  <span data-test="location">İstanbul(Avr.)</span>
  <span data-test="subtitle">Bir Firma...</span>
</div>
"""

SEARCH_URL = "https://www.kariyer.net/is-ilanlari/stajyer?ct=34,82&cp=1"


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


def _with_session(spider_class):
    """
    The spider with just enough of BaseApiSpider.__init__ done by hand.

    Built with object.__new__ because the real constructor opens a
    BrowserSession, and none of that is involved in reading a card.
    """
    from scraper.browser_session import BrowserSession, pick_profile

    spider = object.__new__(spider_class)
    spider.crawler = _Crawler()
    spider._seen_keys = defaultdict(set)
    spider._discovery = defaultdict(set)
    # document_request builds its headers from this. Constructing one touches
    # nothing outside the process.
    spider.session = BrowserSession(
        profile=pick_profile("chrome-151-linux"),
        origin=spider_class.origin,
    )
    return spider


def _listing(how_many=2, search_key="staj", code="D", text="Dönemsel",
             title="Yazılım Stajyeri"):
    body = "<html><body>" + "".join(
        CARD.format(n=n, code=code, text=text, title=title)
        for n in range(1, how_many + 1)
    ) + "</body></html>"
    request = Request(SEARCH_URL, meta={"page": 1, "search_key": search_key})
    return HtmlResponse(SEARCH_URL, body=body, encoding="utf-8",
                        request=request)


def _split(spider, response):
    """What parse_listing produced, sorted into items and requests."""
    items, requests = [], []
    for out in spider.parse_listing(response):
        (requests if isinstance(out, Request) else items).append(out)
    return items, requests


###############################################################
# THE CRAWL OPENS NO POSTING PAGE                             #
###############################################################
def test_a_listing_page_asks_for_nothing_but_the_next_listing_page():
    spider = _with_session(KariyerNetCardsSpider)
    items, requests = _split(spider, _listing(2))

    assert len(items) == 2
    assert len(requests) == 1, "the next page of the same search, nothing else"
    nxt = requests[0]
    assert "/is-ilanlari/" in nxt.url and "/is-ilani/" not in nxt.url
    assert "cp=2" in nxt.url
    assert nxt.meta["search_key"] == "staj"
    assert nxt.meta["page"] == 2
    assert nxt.callback == spider.parse_listing


def test_the_last_page_of_a_search_asks_for_nothing_at_all():
    spider = _with_session(KariyerNetCardsSpider)
    items, requests = _split(spider, _listing(0))

    assert items == [] and requests == []


def test_every_request_the_crawl_makes_is_read_as_a_listing():
    """
    page_actions picks the listing branch on `search_key`. Every crawl request
    carries it, so the crawl never takes the posting branch - that branch, and
    its 4-second dwell, belong to kariyernet_check now.
    """
    spider = _with_session(KariyerNetCardsSpider)
    first = list(spider.api_requests())
    _, following = _split(spider, _listing(2))

    assert [r.meta["search_key"] for r in first] == list(spider.SEARCHES)
    assert all(r.meta.get("search_key") for r in first + following)
    # One context per page, listing pages included - see default_meta().
    assert all(r.meta.get("fresh_context") is True for r in first + following)


def test_the_crawl_does_not_read_the_database(monkeypatch):
    """
    From 12.09 to 21.09.2026 the crawl read which postings already had a
    description, to decide which posting pages to open. There is nothing left
    to decide, so a database that cannot be reached changes nothing.
    """
    import scraper.models

    def explode():
        raise RuntimeError("no database here")

    monkeypatch.setattr(scraper.models, "db_connect", explode)
    spider = _with_session(KariyerNetCardsSpider)
    items, _ = _split(spider, _listing(2))

    assert len(items) == 2


###############################################################
# ONE CARD IS ONE ROW                                          #
###############################################################
def test_every_kept_card_is_stored():
    spider = _with_session(KariyerNetCardsSpider)
    items, _ = _split(spider, _listing(2))

    assert {i["url"] for i in items} == {
        "https://www.kariyer.net/is-ilani/bir-firma-stajyer-1",
        "https://www.kariyer.net/is-ilani/bir-firma-stajyer-2",
    }


def test_the_card_carries_everything_but_the_description():
    spider = _with_session(KariyerNetCardsSpider)
    items, _ = _split(spider, _listing(1))
    item = items[0]

    assert item["job_title"] == "Yazılım Stajyeri 1"
    # The logo's alt, not the ellipsised subtitle.
    assert item["company"] == "Bir Firma A.Ş."
    assert item["location"] == "İstanbul(Avr.)"
    # Coded D by the employer, found by the internship search: labelled Staj.
    assert item["job_type"] == "Staj"
    assert item["company_logo_url"] == "https://img-kariyer.mncdn.com/logo1.png"
    assert item["source_site"] == "kariyernet.com"


def test_the_description_is_unknown_not_absent():
    """
    "N/A", and only once. Reverses the 12.09.2026 choice to leave the field
    out: with no posting page opened, "unknown" is the true statement, and
    pipelines.py never writes "N/A" over a stored description.

    Exactly "N/A", because job_description_out is Join(' ') and a second value
    would be appended - "N/A N/A" is truthy and is not NO_DESCRIPTION, so it
    WOULD overwrite a description the checker had paid for.
    """
    spider = _with_session(KariyerNetCardsSpider)
    items, _ = _split(spider, _listing(2))

    assert [i["job_description"] for i in items] == ["N/A", "N/A"]


def test_the_only_search_is_every_istanbul_internship():
    # 22.09.2026: the board is for every student; the crawl filters on
    # internship and Istanbul only. The part-time search and the department
    # filter (`wa=`) that picked software roles are both gone.
    searches = KariyerNetCardsSpider.SEARCHES
    assert set(searches) == {"staj"} == KariyerNetCardsSpider.INTERNSHIP_SEARCHES
    assert searches["staj"].endswith("/is-ilanlari/stajyer?ct=34,82")
    assert "wa=" not in searches["staj"]
    assert "P" not in KariyerNetCardsSpider.WANTED_WORK_TYPES


###############################################################
# THE CHECKER STILL OPENS THE POSTING PAGE, AND READS IT       #
###############################################################
class _Page:
    """Records what page_actions asked the browser to do."""

    def __init__(self):
        self.waits = []

    def wait_for_timeout(self, ms):
        self.waits.append(ms)

    def evaluate(self, script, *args):
        return True     # already at the bottom: the scroll ends at once


def test_the_checker_still_gets_the_posting_dwell():
    spider = _with_session(KariyerNetCheckSpider)
    probe = spider.probe_request(
        {"id": 1, "url": "https://www.kariyer.net/is-ilani/x-stajyer-1",
         "job_title": "x"}
    )
    page = _Page()
    spider.page_actions(page, probe)

    assert page.waits == [KariyerNetCardsSpider.POSTING_DWELL_S * 1000]


def _posting(body):
    return HtmlResponse("https://www.kariyer.net/is-ilani/x-stajyer-1",
                        body=body.encode("utf-8"), encoding="utf-8")


def test_the_checker_reads_the_description(make_checker):
    """The only place a kariyer.net description is read since 21.09.2026."""
    spider = make_checker(KariyerNetCheckSpider)
    body = (
        '<div data-test="apply-button">Başvur</div>'
        '<div data-test="qualifications-and-job-description">'
        "<h2>Genel Nitelikler</h2><p>  Python bilen  </p><li>stajyer</li>"
        "</div>"
    )
    assert spider.description(_posting(body)) == (
        "Genel Nitelikler Python bilen stajyer"
    )


def test_the_checker_falls_back_to_the_older_container(make_checker):
    spider = make_checker(KariyerNetCheckSpider)
    body = '<div data-test="job-description"><p>Eski sayfa</p></div>'
    assert spider.description(_posting(body)) == "Eski sayfa"


@pytest.mark.parametrize("body", [
    "<title>Access to this page has been denied</title>",
    '<div data-test="ad-card"></div>',
])
def test_a_page_with_no_description_offers_none(make_checker, body):
    # None, not "": openings.py writes a description only when there is one,
    # so a block page leaves the stored value alone.
    spider = make_checker(KariyerNetCheckSpider)
    assert spider.description(_posting(body)) is None
