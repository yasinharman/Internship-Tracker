"""
techcareer's crawl reads the list and nothing else - since 21.09.2026.

Until then parse_list only filtered, and every kept record cost one
/_next/data/<buildId>/tr/jobs/detail/<slug>.json request that built the item.
Everything that request read except the description and the working type is on
the list record too, so the item is now built there and the description is
left to techcareer_check, which downloads that payload anyway for its verdict.

The records below carry only keys from the list-record inventory in
docs/sites/techcareer.md (27.07.2026): id, title, slug, jobTitle, location,
owner.name, owner.logo. Nothing here touches the network or the database.
"""

import json

from scrapy.http import Request, TextResponse

from scraper.pipelines import normalize_job_type
from scraper.spiders.techcareer_api import TechCareerApiSpider
from scraper.spiders.techcareer_check import TechCareerCheckSpider

BUILD_ID = "build-abc"
ORIGIN = "https://www.techcareer.net"


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


def _spider(spider_class=TechCareerApiSpider):
    # The real constructor: it builds a BrowserSession, which touches nothing
    # outside the process. The buildId is what on_warmup would have read.
    spider = spider_class()
    spider.crawler = _Crawler()
    spider.debug_dump = False
    spider.build_id = BUILD_ID
    return spider


def _record(n, title, *, location="İstanbul / Türkiye", owner=None):
    return {
        "id": n,
        "title": title,
        "slug": f"posting-{n}",
        "jobTitle": "",
        "location": location,
        "owner": owner if owner is not None else {
            "name": f"Firma {n}",
            "logo": f"http://cdn1.kariyer.net/logo{n}.png",
        },
    }


def _page(records, *, search_key="scan", page=1, page_count=1):
    body = {"pageProps": {"initialJobList": {
        "jobListItems": records,
        "pagination": {"pageCount": page_count, "total": len(records)},
    }}}
    url = f"{ORIGIN}/_next/data/{BUILD_ID}/tr/jobs.json"
    request = Request(url, meta={"page": page, "search_key": search_key})
    return TextResponse(url, body=json.dumps(body).encode("utf-8"),
                        encoding="utf-8", request=request)


def _split(spider, response):
    items, requests = [], []
    for out in spider.parse_list(response):
        (requests if isinstance(out, Request) else items).append(out)
    return items, requests


def test_the_crawl_makes_no_detail_request():
    spider = _spider()
    items, requests = _split(spider, _page([
        _record(1, "Yazılım Stajyeri"),
        _record(2, "Yarı Zamanlı Destek Uzmanı"),
    ]))

    assert len(items) == 2
    assert requests == [], "one page, so no pagination either - and no detail"


def test_the_item_is_built_from_the_list_record():
    spider = _spider()
    items, _ = _split(spider, _page([_record(9664, "IT Stajyeri")]))
    item = items[0]

    assert item["job_title"] == "IT Stajyeri"
    assert item["company"] == "Firma 9664"
    # http:// kept as it is - cdn1.kariyer.net has no working certificate.
    assert item["company_logo_url"] == "http://cdn1.kariyer.net/logo9664.png"
    assert item["location"] == "İstanbul / Türkiye"
    # The same url parse_detail built, so stored rows still match the upsert.
    assert item["url"] == f"{ORIGIN}/jobs/detail/posting-9664"
    assert item["source_site"] == "techcareer.net"
    assert normalize_job_type(item["job_type"]) == "Internship"
    assert spider.crawler.stats.values["logo/found"] == 1


def test_the_description_is_left_to_the_checker():
    # "N/A" is what pipelines.py refuses to write over a stored description.
    spider = _spider()
    items, _ = _split(spider, _page([_record(1, "Yazılım Stajyeri")]))

    assert items[0]["job_description"] == "N/A"


def test_the_title_types_the_posting():
    spider = _spider()
    items, _ = _split(spider, _page([
        _record(1, "Bilgisayar Mühendisliği Stajyeri"),
        _record(2, "Yarı Zamanlı Satış Danışmanı"),
    ]))

    assert [normalize_job_type(i["job_type"]) for i in items] == [
        "Internship", "Part-Time",
    ]


def test_a_typed_posting_whose_title_says_neither_is_not_guessed():
    """
    9830 *Assistant Product Manager* on 14.09.2026: tagged Yarı Zamanlı by
    the site, found only by the typed pass, nothing in the title. The list
    record has no working-type field, and 2,4 means part-time OR internship,
    so the item says nothing rather than picking one - and it is counted, so
    a run shows how many postings the missing field cost.
    """
    spider = _spider()
    items, _ = _split(spider, _page(
        [_record(9830, "Assistant Product Manager")], search_key="typed",
    ))

    assert len(items) == 1, "the typed pass keeps it without reading the title"
    assert items[0]["job_type"] == "N/A"
    assert normalize_job_type(items[0]["job_type"]) == "Other"
    assert spider.crawler.stats.values["job_type/untyped"] == 1


def test_a_hidden_employer_falls_back_to_na_with_no_logo():
    spider = _spider()
    items, _ = _split(spider, _page([
        _record(9830, "Yarı Zamanlı Asistan", owner={"name": "", "logo": ""}),
    ]))

    assert items[0]["company"] == "N/A"
    # Absent, not "N/A": pipelines.py leaves a stored logo alone.
    assert "company_logo_url" not in items[0]
    assert spider.crawler.stats.values["logo/missing"] == 1


def test_the_scan_still_filters_on_city_and_title():
    spider = _spider()
    items, _ = _split(spider, _page([
        _record(1, "Yazılım Stajyeri", location="Muğla / Türkiye"),
        _record(2, "Kıdemli Yazılım Mühendisi"),
        _record(3, "Yazılım Stajyeri", location="İstanbul(Asya) / Türkiye"),
    ]))

    assert [i["url"].rsplit("-", 1)[-1] for i in items] == ["3"]


def test_a_posting_both_passes_find_is_yielded_once_and_credited_to_both():
    spider = _spider()
    record = _record(9664, "IT Stajyeri")
    typed, _ = _split(spider, _page([record], search_key="typed"))
    scan, _ = _split(spider, _page([record], search_key="scan"))

    assert len(typed) + len(scan) == 1
    assert spider._discovery["posting-9664"] == {"typed", "scan"}


def test_pagination_keeps_each_pass_on_its_own_filter():
    spider = _spider()
    _, typed_next = _split(spider, _page(
        [_record(1, "Yazılım Stajyeri")], search_key="typed", page_count=2,
    ))
    _, scan_next = _split(spider, _page(
        [_record(2, "Yazılım Stajyeri")], search_key="scan", page_count=2,
    ))

    assert [r.url for r in typed_next] == [
        f"{ORIGIN}/_next/data/{BUILD_ID}/tr/jobs.json"
        "?jobs%5BisCompleted%5D=false&jobs%5Bpage%5D=2"
        "&jobs%5Bfilters%5D%5BtypeOfWork%5D=2,4"
    ]
    assert [r.url for r in scan_next] == [
        f"{ORIGIN}/_next/data/{BUILD_ID}/tr/jobs.json"
        "?jobs%5BisCompleted%5D=false&jobs%5Bpage%5D=2"
    ]


def test_the_last_page_asks_for_nothing_more():
    spider = _spider()
    _, requests = _split(spider, _page(
        [_record(1, "Yazılım Stajyeri")], page=2, page_count=2,
    ))

    assert requests == []


def test_the_checker_still_fetches_the_detail_json():
    """
    The detail payload moved from the crawl to the checker; the checker's
    request is what now carries the description, and it depends on the
    buildId the shared warm-up reads.
    """
    spider = _spider(TechCareerCheckSpider)
    request = spider.probe_request(
        {"id": 7, "url": f"{ORIGIN}/jobs/detail/posting-7"}
    )

    # _data_url ends this in an empty "?", which Scrapy drops.
    assert request.url == (
        f"{ORIGIN}/_next/data/{BUILD_ID}/tr/jobs/detail/posting-7.json"
    )
    body = {"pageProps": {"jobDetail": {
        "head": {"isCompleted": False},
        "content": {"description": "<p>Staj</p><p>programı</p>"},
    }}}
    response = TextResponse(request.url, body=json.dumps(body).encode("utf-8"),
                            encoding="utf-8")
    assert spider.description(response) == "Staj programı"
