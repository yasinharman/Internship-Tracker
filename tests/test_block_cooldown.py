"""
What a spider does when a site stops answering it.

MEASURED 10.09.2026 (docs/sites/kariyernet.md): kariyer.net served ten pages
through a windowed browser and then refused every request after that, in one
step, for the rest of the run. A refusal there is a state rather than a coin
flip, so retrying it immediately collects another refusal and spends
DOMAIN_BLOCK_BUDGET on nothing. The answer is to wait.

These lock down when the waiting happens and when it stops. Nothing here
sleeps: `sleep_out_loud` is replaced with a recorder, which is also how the
tests check the wait was actually asked for.
"""

from collections import defaultdict

import pytest
import scrapy

from scraper import api_middlewares
from scraper.api_middlewares import BlockDetectionMiddleware
from scraper.spiders.kariyernet_cards import KariyerNetCardsSpider


DOMAIN = "www.kariyer.net"
URL = f"https://{DOMAIN}/is-ilani/bir-firma-stajyer-123"


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


class _Spider:
    """Only the attributes _cool_off reads."""

    def __init__(self, seconds=600, after=2, allowed=3):
        self.name = "test_spider"
        if seconds:
            self.BLOCK_COOLDOWN_S = seconds
            self.BLOCK_COOLDOWN_AFTER = after
            self.BLOCK_COOLDOWNS_ALLOWED = allowed


@pytest.fixture
def waits(monkeypatch):
    """Every wait the middleware asks for, in seconds, in order."""
    recorded = []
    monkeypatch.setattr(
        api_middlewares, "sleep_out_loud",
        lambda seconds, what, **kwargs: recorded.append(seconds),
    )
    return recorded


@pytest.fixture
def middleware():
    instance = object.__new__(BlockDetectionMiddleware)
    instance.crawler = _Crawler()
    instance.blocks_by_domain = defaultdict(int)
    instance.blocks_in_a_row = defaultdict(int)
    instance.cooldowns_taken = 0
    instance.budget = 8
    instance.gave_up_on = set()
    return instance


def _refuse(middleware, spider, times):
    """Hand the middleware `times` refusals in a row, return what it gave back."""
    answers = []
    for _ in range(times):
        middleware.blocks_in_a_row[DOMAIN] += 1
        answers.append(middleware._cool_off(
            scrapy.Request(URL), spider, DOMAIN, "403 Forbidden"))
    return answers


def test_one_refusal_is_just_a_retry(middleware, waits):
    # A blip should not cost ten minutes. BLOCK_COOLDOWN_AFTER is 2.
    assert _refuse(middleware, _Spider(), 1) == [None]
    assert waits == []


def test_two_in_a_row_buys_a_pause(middleware, waits):
    answers = _refuse(middleware, _Spider(seconds=600, after=2), 2)
    assert answers[0] is None
    assert answers[1] is not None, "the second refusal should hand back a retry"
    assert waits == [600]
    assert answers[1].url == URL
    assert answers[1].dont_filter is True


def test_the_pause_clears_the_budget_it_would_have_spent(middleware, waits):
    # Otherwise the wait buys time and nothing else: the refusals collected
    # before it would still be sitting against DOMAIN_BLOCK_BUDGET.
    middleware.blocks_by_domain[DOMAIN] = 5
    _refuse(middleware, _Spider(), 2)
    assert middleware.blocks_by_domain[DOMAIN] == 0
    assert middleware.blocks_in_a_row[DOMAIN] == 0


def test_a_served_page_ends_the_streak(middleware, waits):
    spider = _Spider()
    _refuse(middleware, spider, 1)
    middleware.blocks_in_a_row[DOMAIN] = 0        # what process_response does
    assert _refuse(middleware, spider, 1) == [None]
    assert waits == [], "a single refusal either side of a good page is not a run"


def test_the_pauses_run_out(middleware, waits):
    spider = _Spider(seconds=60, after=1, allowed=2)
    for _ in range(4):
        _refuse(middleware, spider, 1)
    assert waits == [60, 60], "only two pauses were allowed"
    assert middleware.cooldowns_taken == 2


def test_a_spider_that_has_not_asked_never_waits(middleware, waits):
    # Indeed and LinkedIn still fail fast: they have a ladder to climb and a
    # session that may simply have expired, neither of which a pause fixes.
    assert _refuse(middleware, _Spider(seconds=0), 5) == [None] * 5
    assert waits == []


def test_kariyernet_asks_for_it_and_main_gives_it_the_room():
    """
    The ceiling has to clear the WORST case, not the expected one.

    A run killed while it is doing exactly what it was told - waiting out a
    refusal, or drawing the long end of a randomised delay fifty times - is
    reported as a failure and throws away what it had collected. The first
    attempt at this ceiling was four hours and would have done that: the
    worst case works out at 4h50m, which nothing would have noticed until a
    run died at four in the morning.

    So the arithmetic lives here rather than only in a comment. Raise
    DOWNLOAD_DELAY, BLOCK_COOLDOWN_S or BLOCK_COOLDOWNS_ALLOWED and this
    fails until the ceiling follows.
    """
    import main

    spider = KariyerNetCardsSpider
    # The whole result set is 46 postings plus a handful of listing pages.
    requests = 55
    # RANDOMIZE_DOWNLOAD_DELAY spreads uniformly over 0.5x - 1.5x, so every
    # request landing on the upper bound is the honest worst case.
    slowest_delay = spider.custom_settings["DOWNLOAD_DELAY"] * 1.5
    # goto plus the dwell plus the scroll, generously.
    per_page = spider.POSTING_DWELL_S + 6
    waiting = spider.BLOCK_COOLDOWN_S * spider.BLOCK_COOLDOWNS_ALLOWED

    worst_case = requests * (slowest_delay + per_page) + waiting

    for name in ("kariyernet_cards", "kariyernet_check"):
        assert main.SPIDER_TIMEOUTS[name] > worst_case, (
            f"{name} can legitimately take {worst_case / 3600:.1f}h but is "
            f"killed at {main.SPIDER_TIMEOUTS[name] / 3600:.1f}h"
        )
