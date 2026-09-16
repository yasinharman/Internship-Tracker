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


class TestTheLastPage:
    """15.09.2026: page 9 had 10 cards and page 10 was fetched anyway."""

    def test_a_short_page_ends_the_route(self, spider):
        list(spider.parse_search(search_page(range(1, 11), page=9)))
        assert spider.next_requests == []
        assert spider.crawler.stats.values["linkedin/short_last_page"] == 1

    def test_a_full_page_asks_for_the_next(self, spider):
        list(spider.parse_search(search_page(range(1, 26), page=8)))
        assert spider.next_requests == [("filter-parttime", 9)]
        assert "linkedin/short_last_page" not in spider.crawler.stats.values

    def test_unrendered_shells_still_count_as_cards(self, spider):
        # A page whose cards did not render is not an ending.
        body = "<ul>" + "".join(
            f'<li data-occludable-job-id="{i}"></li>' for i in range(1, 26)
        ) + "</ul>"
        url = "https://www.linkedin.com/jobs/search/?start=0"
        response = HtmlResponse(url=url, body=body.encode(), encoding="utf-8",
                                request=Request(url, meta={"route": "filter-staj", "page": 1}))
        list(spider.parse_search(response))
        assert spider.next_requests == [("filter-staj", 2)]


class TestASessionLinkedInNoLongerAccepts:
    """
    16.09.2026: the feed redirected to /uas/login and the run went on to
    three searches that came back as 29 kB pages with no cards. The warm-up is
    where it has to stop - LinkedIn has no anonymous mode.
    """

    def warmup(self, url):
        return HtmlResponse(url=url, body=b"<html></html>", encoding="utf-8")

    def test_landing_on_the_sign_in_page_ends_the_run(self, spider):
        from scrapy.exceptions import CloseSpider

        spider._warned_sign_in_wall = False
        with pytest.raises(CloseSpider):
            spider.on_warmup(self.warmup(
                "https://www.linkedin.com/uas/login?session_redirect=https%3A%2F%2Fwww.linkedin.com%2Ffeed%2F"
            ))
        assert spider.crawler.stats.values["linkedin/session_expired"] is True

    def test_a_wall_the_middleware_already_saw_ends_it_too(self, spider):
        from scrapy.exceptions import CloseSpider

        spider._warned_sign_in_wall = True
        with pytest.raises(CloseSpider):
            spider.on_warmup(self.warmup("https://www.linkedin.com/feed/"))

    def test_the_feed_itself_lets_the_run_go_on(self, spider):
        spider._warned_sign_in_wall = False
        assert spider.on_warmup(self.warmup("https://www.linkedin.com/feed/")) is None
        assert "linkedin/session_expired" not in spider.crawler.stats.values

    def test_no_search_is_asked_for_after_a_walled_warm_up(self, spider):
        from scrapy.exceptions import CloseSpider

        spider._warned_sign_in_wall = False
        after = spider._after_warmup(self.warmup("https://www.linkedin.com/uas/login"))
        with pytest.raises(CloseSpider):
            next(after)
        assert spider.next_requests == []


class TestOutOfTheFlow:
    """16.09.2026: the spiders refuse to start unless LinkedIn is switched on."""

    @pytest.mark.parametrize("value", [None, "", "0", "true"])
    def test_they_refuse_without_the_switch(self, monkeypatch, value):
        from scraper.spiders.linkedin_check import LinkedinCheckSpider

        if value is None:
            monkeypatch.delenv("LINKEDIN_ENABLED", raising=False)
        else:
            monkeypatch.setenv("LINKEDIN_ENABLED", value)
        for spider_class in (LinkedinCardsSpider, LinkedinCheckSpider):
            with pytest.raises(ValueError, match="out of the scraping flow"):
                spider_class()

    def test_the_switch_gets_past_the_refusal(self, monkeypatch):
        # Past it, the next guard is the session check - which is the proof
        # that the switch was the only thing standing in the way.
        monkeypatch.setenv("LINKEDIN_ENABLED", "1")
        monkeypatch.setenv("LINKEDIN_STORAGE_STATE", "")
        monkeypatch.setenv("LINKEDIN_COOKIES", "")
        monkeypatch.delenv("LINKEDIN_COOKIES_B64", raising=False)
        with pytest.raises(ValueError) as refused:
            LinkedinCardsSpider()
        assert "out of the scraping flow" not in str(refused.value)
