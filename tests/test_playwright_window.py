"""
The guard that keeps kariyer.net from being crawled headless.

MEASURED 10.09.2026 (docs/sites/kariyernet.md): headless is answered with a
9 495-byte PerimeterX press-and-hold page carrying zero cards, while the same
browser with a window gets 621 kB and 36 of them. That failure is silent - the
run exits 0 having found nothing, which looks exactly like a selector that has
rotted - so the spider declares NEEDS_A_WINDOW and the middleware refuses
rather than obliges.

These lock down the refusal, not the browser: nothing here starts Chromium.
"""

import pytest

from scraper.playwright_middleware import PlaywrightMiddleware
from scraper.spiders.kariyernet_cards import KariyerNetCardsSpider
from scraper.spiders.indeed_cards import IndeedCardsSpider


class _Spider:
    def __init__(self, name, needs_window):
        self.name = name
        self.NEEDS_A_WINDOW = needs_window


@pytest.fixture
def middleware():
    """
    Built without __init__, which wants a crawler and its settings. Every
    attribute _resolve_headless touches is set here; nothing else is needed
    to ask it the one question these tests ask.
    """
    instance = object.__new__(PlaywrightMiddleware)
    instance.headless = None
    return instance


def test_a_spider_that_needs_a_window_gets_one(middleware, monkeypatch):
    monkeypatch.delenv("PLAYWRIGHT_HEADLESS", raising=False)
    monkeypatch.setenv("DISPLAY", ":0")
    middleware._resolve_headless(_Spider("kariyernet_cards", True))
    assert middleware.headless is False


def test_everyone_else_still_defaults_to_headless(middleware, monkeypatch):
    monkeypatch.delenv("PLAYWRIGHT_HEADLESS", raising=False)
    middleware._resolve_headless(_Spider("indeed_cards", False))
    assert middleware.headless is True


def test_the_env_var_can_still_show_a_window(middleware, monkeypatch):
    # The reason it stays overridable: watching a run is how most of the
    # measurements in docs/sites/ were taken.
    monkeypatch.setenv("PLAYWRIGHT_HEADLESS", "0")
    monkeypatch.setenv("DISPLAY", ":0")
    middleware._resolve_headless(_Spider("indeed_cards", False))
    assert middleware.headless is False


def test_the_env_var_cannot_take_the_window_away(middleware, monkeypatch):
    monkeypatch.setenv("PLAYWRIGHT_HEADLESS", "1")
    monkeypatch.setenv("DISPLAY", ":0")
    with pytest.raises(RuntimeError, match="NEEDS_A_WINDOW"):
        middleware._resolve_headless(_Spider("kariyernet_cards", True))


def test_no_display_says_what_to_install(middleware, monkeypatch):
    monkeypatch.delenv("PLAYWRIGHT_HEADLESS", raising=False)
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    with pytest.raises(RuntimeError, match="xvfb"):
        middleware._resolve_headless(_Spider("kariyernet_cards", True))


def test_wayland_alone_is_a_display(middleware, monkeypatch):
    monkeypatch.delenv("PLAYWRIGHT_HEADLESS", raising=False)
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    middleware._resolve_headless(_Spider("kariyernet_cards", True))
    assert middleware.headless is False


###############################################################
# THE SPIDERS THEMSELVES, SO A REVERT CANNOT PASS QUIETLY     #
###############################################################
def test_kariyernet_declares_that_it_needs_a_window():
    assert KariyerNetCardsSpider.NEEDS_A_WINDOW is True
    assert KariyerNetCardsSpider.USE_PLAYWRIGHT is True


def test_kariyernet_does_not_borrow_indeeds_session():
    # The middleware's fallback is INDEED_STORAGE_STATE, and honouring it
    # here would load a signed-in Indeed session - Google SSO cookies and all
    # - into a browser whose next navigation is to kariyer.net.
    assert KariyerNetCardsSpider.STORAGE_STATE_ENV == "KARIYERNET_STORAGE_STATE"
    assert IndeedCardsSpider.STORAGE_STATE_ENV == "INDEED_STORAGE_STATE"
    assert (KariyerNetCardsSpider.STORAGE_STATE_ENV
            != IndeedCardsSpider.STORAGE_STATE_ENV)


###############################################################
# EVERY POSTING PAGE ARRIVES AS A NEW VISITOR                 #
###############################################################
"""
    MEASURED 10.09.2026: kariyer.net serves a posting page to a browser
    carrying no cookies and refuses one carrying a `_px3` earned on the
    listing. One context managed exactly one posting; a new context per
    posting managed five of five. The flag is the whole mechanism, and it is
    a single dict key that a refactor could drop without anything failing -
    the crawl would just collect one description and then stop.
"""


def test_the_checker_probes_from_a_fresh_context():
    from scraper.spiders.kariyernet_check import KariyerNetCheckSpider
    from scraper.browser_session import BrowserSession, pick_profile

    spider = object.__new__(KariyerNetCheckSpider)
    spider.session = BrowserSession(
        profile=pick_profile("chrome-151-linux"),
        origin=KariyerNetCheckSpider.origin,
    )
    request = spider.probe_request(
        {"id": 1, "url": "https://www.kariyer.net/is-ilani/x-stajyer-1",
         "job_title": "x"}
    )
    assert request.meta["fresh_context"] is True
    # What the parent put there has to survive the override.
    assert request.meta["posting_id"] == 1
    assert request.dont_filter is True
