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

from scraper.spiders.indeed_cards import IndeedCardsSpider


def _pages_requested(pages):
    """Feed pages of jobkeys in order; return how many were asked for."""
    spider = IndeedCardsSpider.__new__(IndeedCardsSpider)
    spider._seen_keys = defaultdict(set)
    spider._repeated_pages = defaultdict(int)
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
    pages = [[f"{n}a", f"{n}b"] for n in range(20)]
    assert _pages_requested(pages) == IndeedCardsSpider.MAX_PAGES
