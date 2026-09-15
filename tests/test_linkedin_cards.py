"""
linkedin_cards: what a search page is counted as, and the field-filter trial.

15.09.2026. The first full run on an empty board classified 83% of LinkedIn
`other`, and the part-time route - no field filter, 9% visible - filled its
15 pages. Before narrowing it, one run puts a field-filtered route beside it
and reports how much of the known `it` it keeps (docs/sites/linkedin.md).

Nothing here touches the network or the database: the stored rows and the
next-page request are stand-ins.
"""

from collections import defaultdict
from urllib.parse import parse_qs, urlparse

import pytest
from scrapy.http import HtmlResponse, Request

from scraper.spiders.linkedin_cards import LinkedinCardsSpider

CARD = """
<li data-occludable-job-id="{id}">
  <div class="job-card-container">
    <a class="job-card-list__title--link" aria-label="Stajyer with verification">
      <strong>Stajyer {id}</strong></a>
    <div class="artdeco-entity-lockup__subtitle"><span><!---->Bir Firma<!----></span></div>
    <div class="artdeco-entity-lockup__caption">
      <ul class="job-card-container__metadata-wrapper"><li>Istanbul, Türkiye (On-site)</li></ul>
    </div>
  </div>
</li>
"""


def search_page(ids, route="filter-parttime", page=1):
    body = "<ul>" + "".join(CARD.format(id=i) for i in ids) + "</ul>"
    url = f"https://www.linkedin.com/jobs/search/?start={(page - 1) * 25}"
    return HtmlResponse(
        url=url, body=body.encode(), encoding="utf-8",
        request=Request(url, meta={"route": route, "page": page}),
    )


def url_of(job_id):
    return f"https://www.linkedin.com/jobs/view/{job_id}/"


@pytest.fixture
def spider(make_checker, monkeypatch):
    spider = make_checker(LinkedinCardsSpider)
    spider._discovery = defaultdict(set)
    spider._seen_keys = defaultdict(set)
    spider._stored = {}
    spider.next_requests = []
    monkeypatch.setattr(
        spider, "_search_request",
        lambda route, page, referer=None: spider.next_requests.append((route, page)) or "next",
    )
    return spider


class TestTheRoutes:

    def test_every_route_says_what_the_site_classified_it_as(self):
        # A route missing here would silently switch on the title filter.
        assert set(LinkedinCardsSpider.ROUTES) == set(LinkedinCardsSpider.SITE_CLASSIFIED_ROUTES)

    def test_the_trial_names_two_real_routes(self):
        narrow, wide = LinkedinCardsSpider.FIELD_FILTER_TRIAL
        assert narrow in LinkedinCardsSpider.ROUTES and wide in LinkedinCardsSpider.ROUTES

    def test_the_narrow_route_is_the_wide_one_plus_a_field(self):
        narrow, wide = LinkedinCardsSpider.FIELD_FILTER_TRIAL
        extra = dict(LinkedinCardsSpider.ROUTES[narrow])
        assert extra.pop("f_F") == "it,eng"
        assert extra == LinkedinCardsSpider.ROUTES[wide]

    def test_the_field_goes_out_as_one_comma_separated_parameter(self, make_checker, monkeypatch):
        spider = make_checker(LinkedinCardsSpider)
        sent = {}
        monkeypatch.setattr(
            spider, "document_request",
            lambda url, **kwargs: sent.setdefault("url", url),
        )
        spider._search_request("filter-parttime-it", page=2)
        query = parse_qs(urlparse(sent["url"]).query)
        assert query["f_F"] == ["it,eng"]
        assert query["f_JT"] == ["P"]
        assert query["start"] == ["25"]

    def test_the_wide_route_runs_last(self):
        # DOMAIN_BLOCK_BUDGET cuts from the end; the trial arm must not be
        # what gets lost.
        assert list(LinkedinCardsSpider.ROUTES)[-1] == "filter-parttime"


class TestAlreadyStored:

    def test_a_page_counts_the_postings_an_earlier_run_stored(self, spider, caplog):
        spider._stored = {url_of(1): "other", url_of(2): None}
        with caplog.at_level("INFO"):
            items = [x for x in spider.parse_search(search_page(range(1, 26))) if x != "next"]
        assert len(items) == 25
        assert spider.crawler.stats.values["linkedin/cards_already_stored"] == 2
        assert "25 kept, 2 already stored" in caplog.text

    def test_the_stored_rows_are_read_before_the_page_yields_anything(self, spider):
        reads = []
        spider._stored = None

        def read():
            reads.append(len(reads))
            spider._stored = {}
            return spider._stored

        spider._stored_categories = read
        pages = spider.parse_search(search_page(range(1, 26)))
        next(pages)
        assert reads, "the first item went out before the board was read"


class TestTheTrialReport:

    def _found(self, spider, **routes_by_id):
        for job_id, routes in routes_by_id.items():
            spider._discovery[job_id.lstrip("_")] = set(routes)

    def test_it_counts_the_known_it_the_narrow_route_kept(self, spider):
        spider._stored = {
            url_of(1): "it", url_of(2): "it", url_of(3): "other",
            url_of(4): "other", url_of(5): None,
        }
        self._found(
            spider,
            _1={"filter-parttime", "filter-parttime-it"},
            _2={"filter-parttime"},
            _3={"filter-parttime", "filter-parttime-it"},
            _4={"filter-parttime"},
            _5={"filter-parttime", "filter-parttime-it"},   # not classified yet
            _6={"filter-staj"},
        )
        spider._report_field_filter_trial()
        stats = spider.crawler.stats.values
        assert (stats["linkedin/trial/it/narrow"], stats["linkedin/trial/it/wide"]) == (1, 2)
        assert (stats["linkedin/trial/other/narrow"], stats["linkedin/trial/other/wide"]) == (1, 2)
        assert stats["linkedin/trial/only_narrow"] == 0

    def test_a_posting_only_the_narrow_route_found_is_counted(self, spider):
        self._found(spider, _9={"filter-parttime-it"})
        spider._report_field_filter_trial()
        assert spider.crawler.stats.values["linkedin/trial/only_narrow"] == 1

    def test_a_run_without_the_narrow_route_says_nothing(self, spider):
        self._found(spider, _1={"filter-parttime"})
        spider._report_field_filter_trial()
        assert not any(k.startswith("linkedin/trial") for k in spider.crawler.stats.values)
