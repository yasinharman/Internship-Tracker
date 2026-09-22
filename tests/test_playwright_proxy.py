"""
The browser uses the proxy it is given - and leaves the session behind.

Until 22.09.2026 PlaywrightMiddleware ignored request.meta["proxy"], so every
page a browser opened left from the home address whatever PROXY_MODE said:
all of kariyer.net, and every Indeed request that went through a browser
(docs/proxies.md). A page for a proxied request now opens in a context bound
to that proxy.

Two things are locked down here. The proxy must reach the context, in the
form Playwright takes. And a proxied context must not carry the signed-in
session: the account stays on the address it was made from until the owner
decides otherwise.

Nothing here starts Chromium - the browser is a recorder.
"""

from types import SimpleNamespace

import pytest

from scraper.playwright_middleware import PlaywrightMiddleware, playwright_proxy


class _Stats:
    def __init__(self):
        self.values = {}

    def inc_value(self, key, count=1, start=0):
        self.values[key] = self.values.get(key, start) + count


class _Request:
    def __init__(self, url="https://example.test/x", **meta):
        self.url = url
        self.meta = meta


class _Context:
    def __init__(self, kwargs):
        self.kwargs = kwargs
        self.pages = 0
        self.closed = False

    def new_page(self):
        self.pages += 1
        return object()

    def close(self):
        self.closed = True


class _Browser:
    def __init__(self):
        self.contexts = []

    def new_context(self, **kwargs):
        context = _Context(kwargs)
        self.contexts.append(context)
        return context


@pytest.fixture
def middleware():
    """Built without __init__; only what _page_for touches is set."""
    instance = object.__new__(PlaywrightMiddleware)
    instance.crawler = SimpleNamespace(stats=_Stats())
    instance._browser = _Browser()
    instance._context_kwargs = {"locale": "tr-TR", "viewport": {"width": 1280, "height": 800}}
    instance._proxied_contexts = {}
    return instance


PROXY = "http://user:p%40ss@203.0.113.7:6000"


def test_the_proxy_url_is_split_the_way_playwright_wants_it():
    assert playwright_proxy(PROXY) == {
        "server": "http://203.0.113.7:6000",
        "username": "user",
        "password": "p@ss",           # percent-decoded, as build_url encodes it
    }


def test_no_proxy_means_none():
    assert playwright_proxy(None) is None
    assert playwright_proxy("") is None


def test_a_fresh_visitor_on_a_proxy_gets_a_throwaway_context_on_it(middleware):
    session = _Context({})
    page, visitor = middleware._page_for(_Request(proxy=PROXY, fresh_context=True), session)

    assert visitor is middleware._browser.contexts[0]
    assert visitor.kwargs["proxy"]["server"] == "http://203.0.113.7:6000"
    assert session.pages == 0


def test_a_shared_proxied_request_never_gets_the_session(middleware):
    session = _Context({"storage_state": "/secret/indeed.json"})
    middleware._page_for(_Request(proxy=PROXY), session)

    (proxied,) = middleware._browser.contexts
    assert "storage_state" not in proxied.kwargs
    assert proxied.kwargs["proxy"]["server"] == "http://203.0.113.7:6000"
    assert session.pages == 0


def test_one_shared_context_per_proxy_address(middleware):
    session = _Context({})
    middleware._page_for(_Request(proxy=PROXY), session)
    middleware._page_for(_Request(proxy=PROXY), session)
    middleware._page_for(_Request(proxy="http://user:x@198.51.100.2:7000"), session)

    servers = [c.kwargs["proxy"]["server"] for c in middleware._browser.contexts]
    assert servers == ["http://203.0.113.7:6000", "http://198.51.100.2:7000"]


def test_a_direct_request_is_unchanged(middleware):
    session = _Context({"storage_state": "/secret/indeed.json"})
    page, visitor = middleware._page_for(_Request(), session)

    assert visitor is None
    assert session.pages == 1
    assert middleware._browser.contexts == []


def test_proxied_contexts_are_closed_at_the_end(middleware):
    middleware._page_for(_Request(proxy=PROXY), _Context({}))
    (proxied,) = middleware._browser.contexts
    middleware._close_proxied_contexts()

    assert proxied.closed
    assert middleware._proxied_contexts == {}
