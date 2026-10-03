"""
AN ADDRESS'S FIRST REQUEST TO A SITE IS ITS HOME PAGE, NOT A POSTING.

MEASURED 03.10.2026: indeed_check asked two addresses for a posting page as
their first contact with Indeed, carrying no cookies at all, and both were
refused on that first request - one of them an address that had served 30
Indeed requests the week before. A cookie jar cannot help on the request that
happens before the jar exists, so the curl path now fetches the site root
first, once per (site, address).

Nothing here opens a socket: curl_cffi's get() is replaced.
"""

from types import SimpleNamespace

import pytest
from scrapy.http import Request

from scraper import api_middlewares, cookie_jars


class _Reply:
    def __init__(self, status=200, cookies=()):
        self.status_code = status
        self._cookies = list(cookies)
        self.url = "https://tr.indeed.com/"
        self.content = b"<html>home</html>"

    @property
    def headers(self):
        parent = self

        class _Headers:
            def multi_items(self):
                return [("Set-Cookie", line) for line in parent._cookies]

        return _Headers()


@pytest.fixture
def jars(tmp_path, monkeypatch):
    monkeypatch.setattr(cookie_jars, "JAR_DIR", tmp_path / "jars")
    return cookie_jars


@pytest.fixture
def curl(monkeypatch):
    """Stands in for curl_cffi. Records what the front door was asked for."""
    asked = []

    def get(url, **kwargs):
        asked.append((url, kwargs))
        return _Reply(cookies=["CTK=abc; Path=/", "SOCK=xyz; Domain=.indeed.com"])

    monkeypatch.setattr(api_middlewares.curl_requests, "get", get)
    return asked


@pytest.fixture
def middleware():
    made = object.__new__(api_middlewares.CurlImpersonateMiddleware)
    made.timeout = 30
    made.throttle = SimpleNamespace(wait_turn=lambda request: None)
    return made


def _request(url="https://tr.indeed.com/viewjob?jk=1"):
    return Request(url, meta={"cookie_jar": ("tr.indeed.com", "198.51.100.1"),
                              "proxy": "http://u:p@198.51.100.1:5001"})


HEADERS = {"User-Agent": "Safari", "Referer": "https://tr.indeed.com/",
           "Cookie": "stale=1"}
PROXIES = {"http": "http://u:p@198.51.100.1:5001",
           "https": "http://u:p@198.51.100.1:5001"}


def _spider():
    return SimpleNamespace(logger=SimpleNamespace(info=lambda *a, **k: None))


def test_an_address_new_to_the_site_calls_at_the_front_door(middleware, curl, jars):
    request = _request()
    middleware._arrive_at_the_front_door(request, HEADERS, "safari184", PROXIES, _spider())

    url, kwargs = curl[0]
    assert url == "https://tr.indeed.com/"
    assert kwargs["impersonate"] == "safari184"
    assert kwargs["proxies"] == PROXIES


def test_what_the_front_door_sets_is_kept_and_sent(middleware, curl, jars):
    request = _request()
    middleware._arrive_at_the_front_door(request, HEADERS, "safari184", PROXIES, _spider())

    stored = jars.load("tr.indeed.com", "198.51.100.1")
    assert {c["name"] for c in stored["cookies"]} == {"CTK", "SOCK"}
    assert request.headers[b"Cookie"] == b"CTK=abc; SOCK=xyz"


def test_the_front_door_is_not_sent_a_referer_or_a_stale_cookie(middleware, curl, jars):
    # A visitor arriving at a home page came from nowhere, and the Cookie
    # header the pool put on the real request is what we are replacing.
    middleware._arrive_at_the_front_door(_request(), HEADERS, "safari184", PROXIES, _spider())
    _, kwargs = curl[0]
    assert "Referer" not in kwargs["headers"]
    assert "Cookie" not in kwargs["headers"]


def test_an_address_that_has_been_here_before_goes_straight_in(middleware, curl, jars):
    jars.save("tr.indeed.com", "198.51.100.1",
              {"cookies": [{"name": "CTK", "value": "old", "domain": "tr.indeed.com"}]})
    middleware._arrive_at_the_front_door(_request(), HEADERS, "safari184", PROXIES, _spider())
    assert curl == []


def test_without_the_jars_nothing_happens(middleware, curl, jars):
    # No cookie_jar in meta means the pool middleware did not put one there,
    # which is what COOKIE_JARS=0 looks like from here.
    request = Request("https://tr.indeed.com/viewjob?jk=1", meta={"proxy": "x"})
    middleware._arrive_at_the_front_door(request, HEADERS, "safari184", PROXIES, _spider())
    assert curl == []


def test_a_request_that_is_not_on_the_pool_is_left_alone(middleware, curl, jars):
    request = Request("https://tr.indeed.com/viewjob?jk=1",
                      meta={"cookie_jar": ("tr.indeed.com", "198.51.100.1")})
    middleware._arrive_at_the_front_door(request, HEADERS, "safari184", None, _spider())
    assert curl == []


def test_a_failed_front_door_does_not_stop_the_real_request(middleware, monkeypatch, jars):
    # The real request follows and is judged on its own.
    def boom(url, **kwargs):
        raise RuntimeError("connection reset")

    monkeypatch.setattr(api_middlewares.curl_requests, "get", boom)
    request = _request()
    middleware._arrive_at_the_front_door(request, HEADERS, "safari184", PROXIES, _spider())
    assert jars.load("tr.indeed.com", "198.51.100.1") is None


def test_a_front_door_that_sets_nothing_writes_no_jar(middleware, monkeypatch, jars):
    monkeypatch.setattr(api_middlewares.curl_requests, "get",
                        lambda url, **kwargs: _Reply(cookies=[]))
    middleware._arrive_at_the_front_door(_request(), HEADERS, "safari184", PROXIES, _spider())
    # Nothing kept means the next run tries the front door again, which is
    # right: an address with no cookies has no history to carry.
    assert jars.load("tr.indeed.com", "198.51.100.1") is None
