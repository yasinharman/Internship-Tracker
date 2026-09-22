"""
Youthall: which cards are kept, and when a posting counts as closed.

Measured 22.09.2026 (docs/sites/youthall.md):
  * the Istanbul list is one page of cards, each naming a type - and the type
    is not always right: Hyundai's "HGenius Long Term Internship Program" was
    filed as Part-Time Jobs. A card is kept when its type says Internship OR
    its title reads as one; trainee programmes and full-time jobs are not;
  * a posting page carries a schema.org JobPosting whose validThrough is the
    application deadline. Past it is CLOSED, ahead of it OPEN, and a page
    without one is UNKNOWN - nothing is written on a guess.

Nothing here opens a browser or sends a request.
"""

import json
from datetime import datetime, timezone

import pytest
from scrapy import Request
from scrapy.http import HtmlResponse

from scraper.openings import CLOSED, OPEN, UNKNOWN
from scraper.spiders.youthall_cards import YouthallCardsSpider
from scraper.spiders.youthall_check import YouthallCheckSpider

LIST_URL = "https://www.youthall.com/en/jobs/istanbul/"
POSTING_URL = "https://www.youthall.com/tr/tchibo/e-ticaret-stajyeri_124/"


class _Stats:
    def __init__(self):
        self.values = {}

    def inc_value(self, key, count=1, start=0):
        self.values[key] = self.values.get(key, start) + count


def _crawler():
    return type("C", (), {"stats": _Stats()})()


def _card(href, title, kind, city="İstanbul", company="Tchibo",
          logo="https://s3.eu-central-1.amazonaws.com/stajim/media/images/company/image/1.jpg"):
    return (
        f'<div class="jobs"><a href="{href}"><div class="jobs-body"><div class="jobs-content">'
        f'<div class="jobs-content-header"><img src="{logo}" class="jobs-content-logo" alt="{company} logo">'
        f'<div class="jobs-content-title"><h5>{title}</h5></div></div>'
        f'<div class="jobs-content-bottom">'
        f'<div class="jobs-tag"><i></i> {kind} </div>'
        f'<div class="jobs-tag"><i></i> 30.09.2026 </div>'
        f'<div class="jobs-tag"><i></i> {city} </div>'
        f"</div></div></div></a></div>"
    )


def _list(cards, extra=""):
    body = f"<html><body>{''.join(cards)}{extra}</body></html>"
    return HtmlResponse(LIST_URL, body=body, encoding="utf-8",
                        request=Request(LIST_URL, meta={"page": 1, "search_key": "istanbul"}))


@pytest.fixture
def cards():
    spider = YouthallCardsSpider()
    spider.crawler = _crawler()
    return spider


def _run(spider, response):
    out = list(spider.parse_list(response))
    return [o for o in out if not isinstance(o, Request)], [o for o in out if isinstance(o, Request)]


#####################################################################
# THE LIST                                                          #
#####################################################################
def test_internships_are_kept_by_type_or_by_title(cards):
    items, _ = _run(cards, _list([
        _card("https://www.youthall.com/en/tchibo/e-ticaret-stajyeri_124/", "E-Ticaret Stajyeri", "Internship"),
        _card("https://www.youthall.com/en/hyundai/hgenius_4/", "HGenius Long Term Internship Program", "Part-Time Jobs"),
        _card("https://www.youthall.com/en/bim/magaza-yoneticisi-programi_1/", "Mağaza Yöneticisi Programı", "Management Trainee"),
        _card("https://www.youthall.com/tr/firma/hukuk-asistani_2/", "Hukuk Asistanı / Adalet MYO Mezunu", "Full Time"),
    ]))
    assert [i["job_title"] for i in items] == ["E-Ticaret Stajyeri", "HGenius Long Term Internship Program"]
    assert cards.crawler.stats.values["cards/not_internship"] == 2


def test_an_item_is_built_from_the_card(cards):
    (item,), _ = _run(cards, _list([
        _card("https://www.youthall.com/en/tchibo/e-ticaret-stajyeri_124/?utm=x", "E-Ticaret Stajyeri",
              "Internship", city="İstanbul +"),
    ]))
    assert item["url"] == "https://www.youthall.com/en/tchibo/e-ticaret-stajyeri_124/"
    assert item["company"] == "Tchibo"
    assert item["location"] == "İstanbul"
    assert item["company_logo_url"].startswith("https://s3.eu-central-1.amazonaws.com/")
    assert item["job_description"] == "N/A"
    assert item["source_site"] == "youthall.com"


def test_one_page_asks_for_no_second_when_none_is_linked(cards):
    _, following = _run(cards, _list([_card("/en/a/staj_1/", "Stajyer", "Internship")]))
    assert following == []


def test_a_linked_second_page_is_followed(cards):
    _, (following,) = _run(cards, _list([_card("/en/a/staj_1/", "Stajyer", "Internship")],
                                        extra='<a href="?page=2">2</a>'))
    assert following.url == f"{LIST_URL}?page=2"


#####################################################################
# THE POSTING PAGE                                                  #
#####################################################################
def _posting_page(valid_through=None, description="<p>Tchibo sürprizlerle doludur.</p>", with_schema=True):
    data = {"@context": "https://schema.org", "@type": "JobPosting", "title": "E-Ticaret Stajyeri",
            "employmentType": "INTERN", "description": description}
    if valid_through:
        data["validThrough"] = valid_through
    schema = f'<script type="application/ld+json">{json.dumps(data)}</script>' if with_schema else ""
    other = '<script type="application/ld+json">{"@type": "Organization", "name": "Youthall"}</script>'
    return HtmlResponse(POSTING_URL, body=f"<html><head>{other}{schema}</head><body></body></html>",
                        encoding="utf-8", request=Request(POSTING_URL))


@pytest.fixture
def check():
    spider = YouthallCheckSpider()
    spider.crawler = _crawler()
    spider.now = lambda: datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc)
    return spider


def test_a_deadline_ahead_is_open(check):
    assert check.verdict(_posting_page("2026-11-14T23:59:59+03:00")) == OPEN


def test_a_deadline_passed_is_closed(check):
    assert check.verdict(_posting_page("2026-09-21T23:59:59+03:00")) == CLOSED


def test_no_job_posting_is_unknown(check):
    assert check.verdict(_posting_page(with_schema=False)) == UNKNOWN
    assert check.crawler.stats.values["youthall/no_job_posting"] == 1


def test_no_readable_deadline_is_unknown(check):
    assert check.verdict(_posting_page(None)) == UNKNOWN


def test_the_description_comes_from_the_job_posting(check):
    assert check.description(_posting_page("2026-11-14T23:59:59+03:00")) == "Tchibo sürprizlerle doludur."
    assert check.description(_posting_page(with_schema=False)) is None
