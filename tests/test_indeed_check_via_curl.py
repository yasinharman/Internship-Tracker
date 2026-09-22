"""
INDEED_CHECK_VIA_CURL - indeed_check as the client the pool was served with
on 22.09.2026: curl_cffi, no warm-up, no session. See indeed_check, "FROM THE
POOL".
"""

import pytest

from scraper.spiders.indeed_check import IndeedCheckSpider


@pytest.fixture(autouse=True)
def no_session(monkeypatch):
    for name in ("INDEED_COOKIES", "INDEED_IMPERSONATE", "INDEED_CHECK_VIA_CURL"):
        monkeypatch.delenv(name, raising=False)


def test_off_by_default_the_browser_and_the_warm_up_stay():
    spider = IndeedCheckSpider()
    assert spider.USE_PLAYWRIGHT is True
    assert not getattr(spider, "IMPERSONATE_WITH_CURL", False)
    assert spider.warmup_url == "https://tr.indeed.com/"


def test_on_it_is_curl_with_no_warm_up(monkeypatch):
    monkeypatch.setenv("INDEED_CHECK_VIA_CURL", "1")
    monkeypatch.setenv("INDEED_IMPERSONATE", "safari184")
    spider = IndeedCheckSpider()
    assert spider.USE_PLAYWRIGHT is False
    assert spider.IMPERSONATE_WITH_CURL is True
    assert spider.warmup_url is None
    # The origin was worked out from the warm-up url before it was dropped.
    assert spider.origin == "https://tr.indeed.com"
    # The class is untouched - indeed_cards and other instances keep the browser.
    assert IndeedCheckSpider.USE_PLAYWRIGHT is True


def test_a_posting_request_is_a_bare_navigation(monkeypatch):
    monkeypatch.setenv("INDEED_CHECK_VIA_CURL", "1")
    monkeypatch.setenv("INDEED_IMPERSONATE", "safari184")
    spider = IndeedCheckSpider()
    request = spider.probe_request({"id": 1, "url": "https://tr.indeed.com/viewjob?jk=abc"})
    assert request.meta["impersonate"] == "safari184"
    assert b"Referer" not in request.headers
    assert request.headers[b"Sec-Fetch-Site"] == b"none"
    assert b"Cookie" not in request.headers


def test_no_verdict_says_why(caplog):
    from scrapy.http import HtmlResponse, Request
    from scraper.openings import UNKNOWN

    spider = IndeedCheckSpider()
    url = "https://tr.indeed.com/viewjob?jk=abc"
    body = b'<script>x = "{\\"isJobExpired\\":false}";</script>'
    response = HtmlResponse(url, body=body, request=Request(url))
    with caplog.at_level("INFO"):
        assert spider.verdict(response) == UNKNOWN
    assert "appears 1 time(s), 0 read as true, 0 as false" in caplog.text
    assert 'isJobExpired\\\\":false' in caplog.text
