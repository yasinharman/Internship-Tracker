"""
Which checkers run, and when they are allowed to start.

Two things `main.py --spider kariyernet_cards` used to get wrong, and both
matter to a site that refuses this crawl around its 35th request:

  * it ran ALL FOUR checkers, so three uncrawled sites were probed for
    nothing
  * kariyernet_check started moments after kariyernet_cards, with none of
    the hour-and-a-half gap a full run provides by accident

Nothing here runs a spider or sleeps: run_spider and the wait are replaced.
"""

import time

import pytest

import main


@pytest.fixture(autouse=True)
def no_pool(monkeypatch):
    """The pool is off unless a test turns it on - whatever .env says."""
    monkeypatch.delenv("PROXY_POOL_SPIDERS", raising=False)


@pytest.fixture
def ran(monkeypatch):
    """Record which spiders run_checks would start, without starting any."""
    started = []

    def fake_run_spider(name, timeout=None):
        started.append(name)
        return True, {"items": 1}

    monkeypatch.setattr(main, "run_spider", fake_run_spider)
    return started


@pytest.fixture
def waits(monkeypatch):
    """
    Every cooldown actually waited out, in seconds, without waiting.

    The clock has to move with the sleeps. _wait_out_site_cooldown loops
    until monotonic() passes a deadline, so a fake sleep that does nothing
    while monotonic() stands still spins forever - which is exactly what the
    first version of this fixture did, and it hung the suite.
    """
    slept = []
    clock = {"now": time.monotonic()}

    def fake_sleep(seconds):
        slept.append(seconds)
        clock["now"] += seconds

    monkeypatch.setattr(main.time, "sleep", fake_sleep)
    monkeypatch.setattr(main.time, "monotonic", lambda: clock["now"])
    return slept


def test_a_full_run_checks_every_site_that_is_not_parked(ran, waits):
    main.run_checks()
    assert ran == [
        checker for crawl, checker in main.CHECKER_FOR.items()
        if crawl not in main.PARKED_SPIDERS
    ]


def test_one_spider_checks_only_its_own_site(ran, waits):
    main.run_checks(["kariyernet_cards"])
    assert ran == ["kariyernet_check"], (
        "crawling one site must not send three other sites a probe"
    )


def test_an_unknown_spider_name_is_skipped_rather_than_crashing(ran, waits):
    main.run_checks(["something_that_has_no_checker"])
    assert ran == []


###############################################################
# THE GAP BETWEEN A SITE'S CRAWL AND ITS OWN CHECK            #
###############################################################
def test_a_crawl_that_just_finished_holds_its_checker_back(ran, waits,
                                                           monkeypatch):
    monkeypatch.setitem(main._CRAWL_FINISHED_AT, "kariyernet_cards",
                        time.monotonic())
    main.run_checks(["kariyernet_cards"])

    assert waits, "the checker should have been made to wait"
    assert sum(waits) > main.SITE_COOLDOWN_S["kariyernet_cards"] * 0.9
    assert ran == ["kariyernet_check"], "and then run, not be skipped"


def test_a_gap_that_is_already_there_costs_nothing(ran, waits, monkeypatch):
    # What a full run looks like: the other three crawls happened in between.
    long_ago = time.monotonic() - main.SITE_COOLDOWN_S["kariyernet_cards"] - 60
    monkeypatch.setitem(main._CRAWL_FINISHED_AT, "kariyernet_cards", long_ago)
    main.run_checks(["kariyernet_cards"])

    assert waits == [], "no wait when the gap is already bigger"
    assert ran == ["kariyernet_check"]


def test_sites_with_no_cooldown_never_wait(ran, waits, monkeypatch):
    # Absent from SITE_COOLDOWN_S rather than set to zero: adding one is a
    # deliberate act, and the other three have never shown the problem.
    monkeypatch.setitem(main._CRAWL_FINISHED_AT, "indeed_cards",
                        time.monotonic())
    main.run_checks(["indeed_cards"])

    assert waits == []
    assert ran == ["indeed_check"]
    assert "indeed_cards" not in main.SITE_COOLDOWN_S


def test_a_refused_crawl_still_starts_the_clock(monkeypatch):
    """
    run_spider records the finish time whatever the outcome. A crawl that got
    as far as being refused has spent the address's credit just as
    thoroughly, and that is exactly when its checker must not follow it in.
    """
    assert "_CRAWL_FINISHED_AT[spider_name] = time.monotonic()" in (
        open("main.py").read()
    )


def test_a_parked_site_is_not_checked_in_a_full_run(ran, waits, monkeypatch):
    # 16.09.2026: parking a crawl spider alone left its checker in every
    # full run - LinkedIn's, visiting a restricted account's job pages.
    monkeypatch.setattr(main, "PARKED_SPIDERS", ["indeed_cards"])
    main.run_checks()
    assert "indeed_check" not in ran
    assert "kariyernet_check" in ran


def test_a_parked_site_named_by_hand_is_still_checked(ran, waits, monkeypatch):
    monkeypatch.setattr(main, "PARKED_SPIDERS", ["indeed_cards"])
    main.run_checks(["indeed_cards"])
    assert ran == ["indeed_check"]


def test_linkedin_is_out_of_the_flow_entirely():
    # 16.09.2026: two burner accounts restricted from this address. Not
    # parked - parked spiders stay runnable with --spider.
    assert "linkedin_cards" not in main.SPIDERS
    assert "linkedin_cards" not in main.PARKED_SPIDERS
    assert "linkedin_cards" not in main.CHECKER_FOR
    assert "linkedin_check" not in main.CHECK_SPIDERS


###############################################################
# NO WAIT WHEN THE CRAWL AND THE CHECK LEAVE FROM THE POOL    #
###############################################################
# 22.09.2026: each pooled spider picks the address its site has used least
# recently, so the check does not come from the crawl's address and the gap
# the wait buys is already there. The owner's call the same day.

def test_a_site_whose_crawl_and_check_are_both_pooled_does_not_wait(
        ran, waits, monkeypatch):
    monkeypatch.setenv("PROXY_POOL_SPIDERS", "kariyernet_cards, kariyernet_check")
    monkeypatch.setitem(main._CRAWL_FINISHED_AT, "kariyernet_cards",
                        time.monotonic())
    main.run_checks(["kariyernet_cards"])
    assert waits == []
    assert ran == ["kariyernet_check"]


def test_a_pool_that_covers_only_the_crawl_still_waits(ran, waits, monkeypatch):
    # The check would leave from home - the address the wait protects.
    monkeypatch.setenv("PROXY_POOL_SPIDERS", "kariyernet_cards")
    monkeypatch.setitem(main._CRAWL_FINISHED_AT, "kariyernet_cards",
                        time.monotonic())
    main.run_checks(["kariyernet_cards"])
    assert sum(waits) > main.SITE_COOLDOWN_S["kariyernet_cards"] * 0.9
