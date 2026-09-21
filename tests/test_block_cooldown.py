"""
What a spider does when a site stops answering it.

The mechanism is opt-in per spider and these lock down when it fires and
when it stops. Nothing here sleeps: `sleep_out_loud` is replaced with a
recorder, which is also how the tests check the wait was asked for.

WORTH KNOWING BEFORE YOU READ THE REST: kariyer.net, the site this was
written for, no longer uses it. Waiting was measured twice against that site
and bought nothing (see the last three tests). The machinery stays because it
is opt-in and a site whose refusals really do expire would want it - but no
spider asks for it today, so treat it as untested against a live site.
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


def test_main_gives_kariyernet_room_for_its_slowest_legitimate_run():
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
    # Since 21.09.2026 the crawl is the listing pages alone (~4), so this is
    # the checker's worst case - one probe per posting - and it covers both.
    requests = 55
    # RANDOMIZE_DOWNLOAD_DELAY spreads uniformly over 0.5x - 1.5x, so every
    # request landing on the upper bound is the honest worst case.
    slowest_delay = spider.custom_settings["DOWNLOAD_DELAY"] * 1.5
    # goto plus the dwell plus the scroll, generously.
    per_page = spider.POSTING_DWELL_S + 6
    waiting = spider.BLOCK_COOLDOWN_S * spider.BLOCK_COOLDOWNS_ALLOWED

    worst_case = requests * (slowest_delay + per_page) + waiting

    # Against the time it is CLOSED at, not the kill behind it - see
    # CLOSE_GRACE_S in main.py.
    for name in ("kariyernet_cards", "kariyernet_check"):
        closes_at = main.soft_close_after(main.SPIDER_TIMEOUTS[name])
        assert closes_at > worst_case, (
            f"{name} can legitimately take {worst_case / 3600:.1f}h but is "
            f"closed at {closes_at / 3600:.1f}h"
        )


###############################################################
# kariyer.net DOES NOT ASK FOR THE PAUSE - MEASURED TWICE     #
###############################################################
def test_kariyernet_stops_at_the_wall_instead_of_waiting():
    """
    The pause was added for this site on 10.09.2026 and taken away on 12.09,
    because it was measured not to work HERE:

        10.09  after each 10-minute pause, exactly ONE request got through
        12.09  after the first 10-minute pause, ZERO did

    Six pauses is an hour of waiting for nothing, and each one ends with two
    more refused requests finding that out. The run stops at the wall and
    keeps what it collected; the postings it did not reach are fetched
    tomorrow, because a posting stored without a description is fetched
    again. (That queue was the crawl's until 21.09.2026 and is
    kariyernet_check's since - never-checked rows first. See
    KariyerNetCardsSpider, "THE POSTING PAGE IS NOT THE CRAWL'S TO OPEN".)

    If this ever goes back above zero it should be because someone measured
    a pause working, not because six looked tidier than none.
    """
    assert KariyerNetCardsSpider.BLOCK_COOLDOWNS_ALLOWED == 0


def test_the_wall_is_not_knocked_on_eight_times():
    """
    Once it starts refusing it does not stop, so the shared budget of eight
    - and three retries per url on top - is five refusals spent finding out
    what the first three already said.
    """
    settings = KariyerNetCardsSpider.custom_settings
    assert settings["DOMAIN_BLOCK_BUDGET"] == 3
    assert settings["RETRY_TIMES"] == 1


def test_slowing_down_is_not_the_lever():
    """
    8s bought 34 consecutive requests, 20s bought 36. The limit is a count,
    not a rate, so the delay is set by the nightly budget (see
    docs/sites/kariyernet.md) rather than by chasing the wall. This locks
    the number in so that raising it "to be safe" is a deliberate act with a
    test to argue with.
    """
    assert KariyerNetCardsSpider.custom_settings["DOWNLOAD_DELAY"] == 20
