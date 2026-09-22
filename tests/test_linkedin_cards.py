"""
LinkedIn as a guest: what the crawl asks for and what it keeps.

Since 22.09.2026 there is no account on LinkedIn at all (docs/sites/linkedin.md,
"A posting page opens with no account"). The crawl opens the public search
page - 60 cards and a total - and then the guest endpoint the page scrolls
with, 10 cards a request from start=60, until the total is reached.

Locked down here:
  * no session can ever be loaded, and the spider will not run outside the
    pool - no LinkedIn request leaves the home address;
  * the title decides, because the keyword also matches descriptions;
  * the logo comes from the card, `src` or `data-delayed-url`, and
    LinkedIn's grey placeholder is not a logo;
  * the search stops at its total.

Nothing here opens a browser or sends a request: pages are built in memory.
"""

from urllib.parse import parse_qs, urlparse

import pytest
from scrapy import Request
from scrapy.http import HtmlResponse

from scraper.spiders.linkedin_cards import LinkedinCardsSpider

ORIGIN = "https://www.linkedin.com"


class _Stats:
    def __init__(self):
        self.values = {}

    def inc_value(self, key, count=1, start=0):
        self.values[key] = self.values.get(key, start) + count


@pytest.fixture
def pooled(monkeypatch):
    monkeypatch.setenv("PROXY_POOL_SPIDERS", "linkedin_cards,linkedin_check")


@pytest.fixture
def spider(pooled):
    instance = LinkedinCardsSpider()
    instance.crawler = type("C", (), {"stats": _Stats()})()
    return instance


def _card(job_id, title, company="Firma", logo_attr="src",
          logo="https://media.licdn.com/dms/image/v2/X/company-logo_100_100/0"):
    image = f'<img class="artdeco-entity-image" {logo_attr}="{logo}">' if logo else ""
    return (
        f'<div class="base-card base-search-card" data-entity-urn="urn:li:jobPosting:{job_id}">'
        f'<a class="base-card__full-link" href="https://tr.linkedin.com/jobs/view/x-{job_id}?refId=1"></a>'
        f"{image}"
        f'<h3 class="base-search-card__title">{title}</h3>'
        f'<h4 class="base-search-card__subtitle"><a>{company}</a></h4>'
        f'<span class="job-search-card__location">Beşiktaş, İstanbul, Türkiye</span>'
        f"</div>"
    )


def _response(cards, page=1, total=None, start=None):
    header = f'<span class="results-context-header__job-count">{total}</span>' if total else ""
    url = f"{ORIGIN}/jobs/search/?keywords=stajyer&geoId=90010422"
    meta = {"search_key": "stajyer", "page": page}
    if start is not None:
        url = f"{ORIGIN}/jobs-guest/jobs/api/seeMoreJobPostings/search?start={start}"
        meta["start"] = start
    body = f"<html><body>{header}{''.join(cards)}</body></html>"
    return HtmlResponse(url, body=body, encoding="utf-8", request=Request(url, meta=meta))


def _run(spider, response):
    out = list(spider.parse_cards(response))
    return [o for o in out if not isinstance(o, Request)], [o for o in out if isinstance(o, Request)]


#####################################################################
# NO ACCOUNT, NO HOME ADDRESS                                       #
#####################################################################
def test_no_session_can_be_loaded():
    assert LinkedinCardsSpider.STORAGE_STATE_ENV is None


def test_it_refuses_to_run_outside_the_pool(monkeypatch):
    monkeypatch.setenv("PROXY_POOL_SPIDERS", "kariyernet_cards")
    with pytest.raises(RuntimeError, match="PROXY_POOL_SPIDERS"):
        LinkedinCardsSpider()


def test_the_first_request_is_the_public_search(spider):
    (request,) = list(spider.api_requests())
    query = parse_qs(urlparse(request.url).query)
    assert urlparse(request.url).path == "/jobs/search/"
    assert query == {"keywords": ["stajyer"], "geoId": ["90010422"]}
    # f_E=1 is ignored for a guest (measured 22.09.2026), so it is not sent.
    assert "f_E" not in query


#####################################################################
# THE CARDS                                                         #
#####################################################################
def test_internship_titles_are_kept_and_the_rest_dropped(spider):
    items, _ = _run(spider, _response([
        _card("4461778243", "Software Engineering Intern"),
        _card("4461778244", "Senior Java Engineer"),
        _card("4461778245", "Uzun Dönem Satış Stajyeri"),
    ], total="531"))

    assert [i["job_title"] for i in items] == ["Software Engineering Intern", "Uzun Dönem Satış Stajyeri"]


def test_an_item_carries_the_canonical_url_and_no_description(spider):
    (item,), _ = _run(spider, _response([_card("4461778243", "Martech Intern", company="Paynion")]))

    assert item["url"] == f"{ORIGIN}/jobs/view/4461778243/"
    assert item["company"] == "Paynion"
    assert item["location"] == "Beşiktaş, İstanbul, Türkiye"
    assert item["job_description"] == "N/A"
    assert item["source_site"] == "linkedin.com"


def test_the_logo_is_read_from_src_or_the_delayed_url(spider):
    items, _ = _run(spider, _response([
        _card("1000000001", "Intern", logo_attr="src"),
        _card("1000000002", "Intern", logo_attr="data-delayed-url"),
    ]))
    assert all(i["company_logo_url"].startswith("https://media.licdn.com/") for i in items)


def test_linkedins_grey_placeholder_is_not_a_logo(spider):
    ghost = "https://static.licdn.com/aero-v1/sc/h/6puxblwmhnodu6fjircz4dn4h"
    (item,), _ = _run(spider, _response([_card("1000000003", "Intern", logo=ghost)]))
    assert "company_logo_url" not in item


#####################################################################
# PAGING TO THE TOTAL                                               #
#####################################################################
def test_page_one_asks_for_the_batch_at_60_referred_by_the_search(spider):
    cards = [_card(str(4000000000 + n), "Intern") for n in range(60)]
    _, (following,) = _run(spider, _response(cards, total="531"))

    assert parse_qs(urlparse(following.url).query)["start"] == ["60"]
    assert "/jobs-guest/jobs/api/seeMoreJobPostings/search" in following.url
    assert following.meta["page"] == 2


def test_the_search_stops_when_its_total_is_reached(spider):
    spider._totals["stajyer"] = 75
    cards = [_card(str(4100000000 + n), "Intern") for n in range(10)]
    _, following = _run(spider, _response(cards, page=2, start=60))
    assert len(following) == 1                    # 70 of 75 - one more batch

    cards = [_card(str(4200000000 + n), "Intern") for n in range(10)]
    _, following = _run(spider, _response(cards, page=3, start=70))
    assert following == []                        # 80 >= 75


def test_an_empty_batch_ends_the_search(spider):
    _, following = _run(spider, _response([], page=5, start=100))
    assert following == []


def test_a_plus_total_is_not_taken_as_a_number(spider):
    # "3.000+" is a floor, not a count; paging falls back to empty/repeat.
    _run(spider, _response([_card("4300000000", "Intern")], total="3.000+"))
    assert "stajyer" not in spider._totals
