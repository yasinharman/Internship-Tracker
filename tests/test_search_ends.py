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


#############################################################
# THE END A SITE REACHES BY ITS OWN CONDITION - 05.10.2026   #
#############################################################
# The first full run from an empty database recorded three of five sites
# "incomplete" over this: they stop paging by their own test and never reach
# next_page_allowed, so nothing recorded that the search was finished. Their
# scans would never have counted, and the run-counting rule would never have
# applied to them - the exact failure it exists to avoid.
#
# Each test here calls the real branch, because what broke was the branch and
# not the counter.

def _bare(spider_class, **attributes):
    """A spider with paging state and nothing else. Opens no socket."""
    from collections import defaultdict

    made = object.__new__(spider_class)
    made.crawler = SimpleNamespace(stats=_Stats())
    made._search_end = {}
    made._lost_pages = defaultdict(int)
    made._seen_keys = defaultdict(set)
    made._repeated_pages = defaultdict(int)
    for name, value in attributes.items():
        setattr(made, name, value)
    return made


def test_techcareer_records_the_site_s_own_last_page():
    import json

    from scrapy.http import Request, TextResponse
    from scraper.spiders.techcareer_api import TechCareerApiSpider

    spider = _bare(TechCareerApiSpider, debug_dump=False)
    payload = {"pageProps": {"initialJobList": {"items": [],
                                                "pagination": {"pageCount": 7}}}}
    url = "https://www.techcareer.net/_next/data/x/tr/jobs.json?page=7"
    request = Request(url, meta={"page": 7, "search_key": "scan"})
    response = TextResponse(url, body=json.dumps(payload).encode(), request=request,
                            encoding="utf-8")

    list(spider.parse_list(response) or [])
    assert spider._search_end["scan"] == "last_page"


def test_linkedin_records_the_total_it_was_told():
    from scraper.spiders.linkedin_cards import LinkedinCardsSpider

    spider = _bare(LinkedinCardsSpider, _totals={"stajyer": 70})
    # 60 on the search page + one batch of 10 is the whole of it.
    assert spider.next_page_allowed(2, [_record(1)], "stajyer") is False
    assert spider._search_end["stajyer"] == "reached_total"


def test_youthall_records_a_list_that_is_one_page_long():
    from scrapy.http import HtmlResponse, Request
    from scraper.spiders.youthall_cards import YouthallCardsSpider

    spider = _bare(YouthallCardsSpider)
    # A card that is not an internship: it counts as a record the page
    # returned, and nothing else in parse_list runs for it.
    body = (b'<div class="jobs"><a href="/en/jobs/muhendis_12345">'
            b'<div class="jobs-content-title"><h5>Muhendis</h5></div>'
            b'<span class="jobs-tag">Full Time</span></a></div>')
    url = "https://www.youthall.com/en/jobs/istanbul/"
    response = HtmlResponse(url, body=body, request=Request(url, meta={"page": 1}),
                            encoding="utf-8")

    asked = list(spider.parse_list(response) or [])
    assert asked == []                                  # no page 2 to ask for
    assert spider._search_end["istanbul"] == "exhausted"


def test_a_page_that_links_to_the_next_one_keeps_youthall_going():
    from scrapy.http import HtmlResponse, Request
    from scraper.spiders.youthall_cards import YouthallCardsSpider

    # Asking for page 2 builds a real request, which is where the browser
    # headers come from.
    spider = _bare(
        YouthallCardsSpider,
        session=SimpleNamespace(document_headers=lambda referer=None: {"User-Agent": "Firefox"}),
        impersonate_candidates=["firefox135"],
        origin="https://www.youthall.com",
        warmup_url="https://www.youthall.com/",
    )
    body = (b'<div class="jobs"><a href="/en/jobs/muhendis_12345">'
            b'<div class="jobs-content-title"><h5>Muhendis</h5></div>'
            b'<span class="jobs-tag">Full Time</span></a></div>'
            b'<a class="next" href="/en/jobs/istanbul/?page=2">next</a>')
    url = "https://www.youthall.com/en/jobs/istanbul/"
    response = HtmlResponse(url, body=body, request=Request(url, meta={"page": 1}),
                            encoding="utf-8")

    asked = list(spider.parse_list(response) or [])
    assert len(asked) == 1 and "page=2" in asked[0].url
    assert "istanbul" not in spider._search_end     # still open
