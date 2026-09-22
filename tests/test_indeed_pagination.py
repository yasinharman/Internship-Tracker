"""
When an Indeed search stops asking for pages.

MEASURED 15.09.2026 (docs/sites/indeed.md): past its last page Indeed serves
the last page again rather than an empty one, and the repeat detection in
BaseApiSpider never noticed because it did not know `jobkey`. Five searches
spent 47 pages on repeats and the run hit SPIDER_TIMEOUT before the broad
searches were done.

Every record here carries a field that changes per page, as Indeed's do, so a
key taken from the whole record would read every page as new.
"""

import logging
from collections import defaultdict
from unittest.mock import MagicMock

from scraper.spiders.indeed_cards import TOTAL_JOB_COUNT, IndeedCardsSpider


def _pages_requested(pages, total=None):
    """Feed pages of jobkeys in order; return how many were asked for."""
    spider = IndeedCardsSpider.__new__(IndeedCardsSpider)
    spider._seen_keys = defaultdict(set)
    spider._repeated_pages = defaultdict(int)
    spider._total_jobs = {} if total is None else {"search": total}
    spider.session_cookies = ["signed in"]
    spider.crawler = MagicMock()
    spider.__dict__["logger"] = logging.getLogger("test")

    for number, keys in enumerate(pages, start=1):
        records = [{"jobkey": key, "impression": number} for key in keys]
        if not spider.next_page_allowed(number, records, "search"):
            return number
    return len(pages)


def test_the_last_page_served_again_ends_the_search_after_two_repeats():
    # developer-intern on 15.09: page 1 and then page 1 again, fourteen times.
    assert _pages_requested([["a", "b", "c"]] * 15) == 3


def test_a_single_page_with_nothing_new_does_not_end_the_search():
    pages = [["a", "b"], ["a", "b"], ["c", "d"], ["e"], ["e"], ["e"]]
    assert _pages_requested(pages) == 6


def test_the_repeat_count_restarts_after_a_page_with_something_new():
    pages = [["a"], ["a"], ["b"], ["b"], ["c"], ["c"], ["c"]]
    assert _pages_requested(pages) == 7


def test_max_pages_still_ends_a_search_that_keeps_finding_postings():
    # With no totalJobCount to go by, the circuit breaker is all there is.
    pages = [[f"{n}a", f"{n}b"] for n in range(IndeedCardsSpider.MAX_PAGES + 5)]
    assert _pages_requested(pages) == IndeedCardsSpider.MAX_PAGES


#####################################################################
# EACH SEARCH STOPS AT ITS OWN totalJobCount - 22.09.2026           #
#####################################################################
# Page one says how big the whole result set is. `start` steps by 10 while a
# page shows about 15 cards, so the last page is 1 + ceil((total - 15) / 10).

def test_the_page_count_follows_from_the_total():
    spider = IndeedCardsSpider.__new__(IndeedCardsSpider)
    spider._total_jobs = {"stajyer": 339, "staj": 283, "intern": 76, "small": 15, "tiny": 3}
    assert spider._last_page("stajyer") == 34      # measured 22.09
    assert spider._last_page("staj") == 28
    assert spider._last_page("intern") == 8
    assert spider._last_page("small") == 1
    assert spider._last_page("tiny") == 1
    assert spider._last_page("never-counted") is None


def test_a_search_stops_at_the_page_its_total_needs():
    pages = [[f"{n}a", f"{n}b"] for n in range(20)]
    assert _pages_requested(pages, total=76) == 8


def test_the_total_is_read_from_the_page_text():
    text = '...,"timestamp":1790070788578,"totalJobCount":339,"x":1'
    assert int(TOTAL_JOB_COUNT.search(text).group(1)) == 339
