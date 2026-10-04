"""
DID EACH SEARCH SEE ITS OWN END?

Harman's definition of a complete scan, 04.10.2026: "her arama kendi sonuna
ulaştıysa tam sayılır, aradaki bir sayfanın düşmesi tamlığı bozmaz". Two
pieces hold it up, and this file is both of them:

  * the shared paging layer records HOW each search stopped, so
    scraper/scans.py can ask whether any of them was cut short;
  * Indeed's crawl pages PAST a page that never arrived, because otherwise a
    dropped request ends that search silently - measured the same day, when a
    single challenge at 10:49 stopped one search and 81 later requests from
    the same address were served.

Nothing here opens a socket.
"""

from types import SimpleNamespace

import pytest
from scrapy.http import Request
from twisted.python.failure import Failure

from scrapy.exceptions import IgnoreRequest
from scraper.spiders.indeed_cards import IndeedCardsSpider


class _Stats:
    def __init__(self):
        self.values = {}

    def inc_value(self, key, count=1, start=0):
        self.values[key] = self.values.get(key, start) + count

    def set_value(self, key, value):
        self.values[key] = value

    def get_stats(self):
        return self.values


@pytest.fixture
def spider():
    """An Indeed crawl with nothing but its paging state."""
    made = object.__new__(IndeedCardsSpider)
    made.crawler = SimpleNamespace(stats=_Stats())
    made._search_end = {}
    from collections import defaultdict

    made._lost_pages = defaultdict(int)
    made._seen_keys = defaultdict(set)
    made._repeated_pages = defaultdict(int)
    made._total_jobs = {}
    made.session_cookies = {"SOCK": "x", "SHOE": "y"}
    # default_meta() rides on every request this spider builds.
    made.impersonate_candidates = ["safari184"]
    made.session = SimpleNamespace(
        document_headers=lambda referer=None: {"User-Agent": "Safari"},
    )
    made.warmup_url = "https://tr.indeed.com/"
    made.origin = "https://tr.indeed.com"
    # `logger` is a read-only property on a Scrapy spider, derived from its
    # name - which is a class attribute, so it works on this bare instance.
    return made


def _record(n):
    return {"jobkey": f"k{n}", "title": f"Stajyer {n}"}


####################################################
# HOW A SEARCH ENDS                                #
####################################################
def test_an_empty_page_ends_the_search(spider):
    assert spider.next_page_allowed(2, [], "stajyer") is False
    assert spider._search_end["stajyer"] == "exhausted"


def test_a_page_with_nothing_new_ends_the_search(spider):
    spider.next_page_allowed(1, [_record(1)], "stajyer")
    # Same posting again, twice: REPEATED_PAGES_BEFORE_STOP is 2.
    spider.next_page_allowed(2, [_record(1)], "stajyer")
    spider.next_page_allowed(3, [_record(1)], "stajyer")
    assert spider._search_end["stajyer"] == "repeated"


def test_reaching_the_last_page_the_total_needs_ends_the_search(spider):
    spider._total_jobs["stajyer"] = 25      # 1 + ceil((25-15)/10) = 2 pages
    assert spider.next_page_allowed(2, [_record(9)], "stajyer") is False
    assert spider._search_end["stajyer"] == "reached_total"


def test_the_ceiling_cuts_the_search_short(spider):
    spider.MAX_PAGES = 2
    assert spider.next_page_allowed(2, [_record(1)], "stajyer") is False
    assert spider._search_end["stajyer"] == "ceiling"


def test_the_sign_in_wall_cuts_an_anonymous_search_short(spider):
    # Not the end of the search, just the end of what a logged-out visitor is
    # shown (measured 30.07.2026), so the scan it belongs to is not complete.
    spider.session_cookies = {}
    assert spider.next_page_allowed(1, [_record(1)], "stajyer") is False
    assert spider._search_end["stajyer"] == "no_account"


def test_the_counters_the_scan_log_reads(spider):
    spider.next_page_allowed(2, [], "stajyer")              # ended
    spider.MAX_PAGES = 1
    spider.next_page_allowed(1, [_record(2)], "intern")     # cut short
    spider._report_search_ends()

    stats = spider.crawler.stats.values
    assert (stats["searches/started"], stats["searches/ended"],
            stats["searches/cut_short"]) == (2, 1, 1)


def test_a_search_nobody_finished_counts_as_cut_short(spider):
    # What a killed spider looks like from here: pages were parsed and then
    # the run ended with no decision about the search.
    spider.next_page_allowed(1, [_record(1)], "stajyer")
    spider._report_search_ends()
    assert spider.crawler.stats.values["searches/cut_short"] == 1


####################################################
# A LOST PAGE DOES NOT END THE SEARCH              #
####################################################
def _lost(spider, page, search="stajyer"):
    request = Request(f"https://tr.indeed.com/jobs?start={(page - 1) * 10}",
                      meta={"page": page, "search_key": search})
    failure = Failure(IgnoreRequest("tr.indeed.com: pool gave up"))
    failure.request = request
    return list(spider.page_lost(failure) or [])


def test_the_next_page_is_asked_for_after_a_loss(spider):
    asked = _lost(spider, 4)
    assert len(asked) == 1
    assert "start=40" in asked[0].url           # page 5
    assert asked[0].meta["page"] == 5
    assert spider.crawler.stats.values["pagination/page_lost"] == 1
    assert "stajyer" not in spider._search_end  # the search is still open


def test_three_losses_in_a_row_stop_the_search(spider):
    for page in (4, 5, 6):
        asked = _lost(spider, page)
    assert asked == []
    assert spider._search_end["stajyer"] == "lost_pages"


def test_a_page_that_arrives_resets_the_run_of_losses(spider):
    _lost(spider, 4)
    _lost(spider, 5)
    spider.next_page_allowed(6, [_record(1)], "stajyer")    # one got through
    assert spider._lost_pages["stajyer"] == 0
    assert _lost(spider, 7) != []                           # not the third


def test_a_loss_on_the_last_page_ends_the_search_properly(spider):
    spider._total_jobs["stajyer"] = 25          # two pages
    assert _lost(spider, 2) == []
    assert spider._search_end["stajyer"] == "reached_total"


def test_a_loss_at_the_ceiling_is_cut_short(spider):
    spider.MAX_PAGES = 3
    assert _lost(spider, 3) == []
    assert spider._search_end["stajyer"] == "ceiling"


def test_every_search_page_carries_the_errback():
    # Without it a dropped page is simply the end of that search: the next
    # page is only ever asked for by the callback of the page before it.
    spider = object.__new__(IndeedCardsSpider)
    assert IndeedCardsSpider.page_lost == type(spider).page_lost
