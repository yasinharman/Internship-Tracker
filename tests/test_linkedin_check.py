"""
Is a LinkedIn posting still open - read as a guest.

Measured 22.09.2026 on two postings with no account (docs/sites/linkedin.md):
an open one carries the apply link (`public_jobs_apply-link-onsite`), a closed
one carries `closed-job__flavor--closed` and "Artık başvuru kabul etmiyor"
and no apply link. Both carry the description in
`div.show-more-less-html__markup`.

The asymmetry every checker keeps: CLOSED only when the page says so, OPEN
only with the apply link, anything else UNKNOWN - a wall must never remove a
real posting from the board.

Nothing here opens a browser or sends a request.
"""

import pytest
from scrapy import Request
from scrapy.http import HtmlResponse

from scraper.openings import CLOSED, OPEN, UNKNOWN
from scraper.spiders.linkedin_check import LinkedinCheckSpider

URL = "https://www.linkedin.com/jobs/view/4439226311/"
DESCRIPTION = (
    '<div class="show-more-less-html__markup"><strong>About the Role</strong>'
    "<p>We are looking for an intern.</p></div>"
)


class _Stats:
    def __init__(self):
        self.values = {}

    def inc_value(self, key, count=1, start=0):
        self.values[key] = self.values.get(key, start) + count


@pytest.fixture
def spider(monkeypatch):
    monkeypatch.setenv("PROXY_POOL_SPIDERS", "linkedin_cards,linkedin_check")
    instance = LinkedinCheckSpider()
    instance.crawler = type("C", (), {"stats": _Stats()})()
    return instance


def _page(body):
    return HtmlResponse(URL, body=f"<html><body>{body}</body></html>", encoding="utf-8",
                        request=Request(URL))


OPEN_PAGE = (
    '<h1 class="top-card-layout__title">Forward Deployed AI Engineer</h1>'
    '<a data-tracking-control-name="public_jobs_apply-link-onsite">Başvur</a>' + DESCRIPTION
)
CLOSED_PAGE = (
    '<h1 class="top-card-layout__title">Software Engineer</h1>'
    '<figure class="closed-job"><span class="closed-job__flavor--closed">'
    "Artık başvuru kabul etmiyor</span></figure>" + DESCRIPTION
)


def test_an_apply_link_means_open(spider):
    assert spider.verdict(_page(OPEN_PAGE)) == OPEN


def test_the_closed_notice_means_closed(spider):
    assert spider.verdict(_page(CLOSED_PAGE)) == CLOSED


def test_a_page_that_says_neither_is_unknown(spider):
    # A sign-in wall, a challenge, a page that never rendered.
    assert spider.verdict(_page("<h1>Oturum açın</h1>")) == UNKNOWN
    assert spider.crawler.stats.values["linkedin/unreadable_posting"] == 1


def test_the_description_is_read_from_the_same_page(spider):
    assert spider.description(_page(OPEN_PAGE)) == "About the Role We are looking for an intern."
    assert spider.description(_page("<h1>Oturum açın</h1>")) is None


def test_every_posting_is_opened_as_a_new_visitor(spider):
    request = spider.probe_request({"id": 7, "url": URL})
    assert request.url == URL
    assert request.meta["fresh_context"] is True
    assert request.meta["posting_id"] == 7
