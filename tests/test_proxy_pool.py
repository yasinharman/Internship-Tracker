"""
The bought static IP pool: which address a site gets, and what a refusal does.

The owner's rules, 22.09.2026 (scraper/proxy_pool.py):
  * European addresses first; outside Europe and carrier networks in reserve;
  * every address judged per site - a refusal rests it for that site only;
  * a rest lasts 24 hours and outlives the run;
  * at most 3 switches per site per run.

A refused pooled request must not spend the site's block budget - the pool's
cap ends the site's run instead.

Nothing here opens a socket. The clock is a variable, the files are in tmp_path.
"""

import json
from collections import defaultdict
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from scrapy.exceptions import IgnoreRequest
from scrapy.http import HtmlResponse, Request

from scraper import api_middlewares
from scraper.api_middlewares import BlockDetectionMiddleware, ProxyPoolMiddleware
from scraper.proxy_pool import Address, PoolState, ProxyPool, load_addresses, site_of

T0 = datetime(2026, 9, 22, 12, 0)

LIST = """\
# header comments do not take a number
198.51.100.1:5001:u:p1
198.51.100.2:5002:u:p2
198.51.100.3:5003:u:p3

198.51.100.4:5004:u:p4
198.51.100.5:5005:u:p@5
"""
META = {
    "198.51.100.1": {"country": "US", "org": "AS6079 RCN"},
    "198.51.100.2": {"country": "FR", "org": "AS5511 Orange S.A."},
    "198.51.100.3": {"country": "IT", "org": "AS6762 TELECOM ITALIA SPARKLE S.p.A."},
    "198.51.100.4": {"country": "DE", "org": "AS8881 1&1 Versatel GmbH"},
    # .5 never checked
}


class _Clock:
    def __init__(self):
        self.now = T0

    def __call__(self):
        return self.now


class _Stats:
    def __init__(self):
        self.values = {}

    def inc_value(self, key, count=1, start=0):
        self.values[key] = self.values.get(key, start) + count


@pytest.fixture
def files(tmp_path):
    (tmp_path / "list.txt").write_text(LIST)
    (tmp_path / "meta.json").write_text(json.dumps(META))
    return tmp_path


@pytest.fixture
def clock():
    return _Clock()


@pytest.fixture
def pool(files, clock):
    return ProxyPool(
        load_addresses(files / "list.txt", files / "meta.json"),
        PoolState(files / "state.json"), rest_hours=24, max_switches=3, clock=clock,
    )


#####################################################
# THE LIST AND ITS ORDER                            #
#####################################################
def test_addresses_are_numbered_in_file_order_skipping_comments(pool):
    assert [a.line for a in pool.addresses] == [1, 2, 3, 4, 5]
    assert [a.ip for a in pool.addresses][0] == "198.51.100.1"


def test_tiers_put_europe_first_and_everything_else_in_reserve(pool):
    tiers = {a.ip: a.tier for a in pool.addresses}
    assert tiers["198.51.100.2"] == 0     # FR consumer ISP
    assert tiers["198.51.100.4"] == 0     # DE
    assert tiers["198.51.100.1"] == 1     # US - reserve
    assert tiers["198.51.100.3"] == 2     # IT, but a carrier network - reserve
    assert tiers["198.51.100.5"] == 1     # never checked - reserve until it is


def test_the_url_quotes_credentials_and_the_label_never_shows_them(pool):
    fifth = pool.addresses[4]
    assert fifth.url == "http://u:p%405@198.51.100.5:5005"
    assert "p@5" not in fifth.label and "u" not in fifth.label.split()[0]


def test_site_is_the_host_without_www():
    assert site_of("https://www.kariyer.net/is-ilanlari/stajyer") == "kariyer.net"
    assert site_of("https://tr.indeed.com/viewjob?jk=1") == "tr.indeed.com"


def test_a_site_starts_on_the_first_european_address(pool):
    assert pool.address_for("kariyer.net").ip == "198.51.100.2"


def test_the_least_recently_used_european_address_goes_next(pool, clock):
    first = pool.address_for("kariyer.net")
    pool.note_request("kariyer.net", first)

    # A new run - a fresh ProxyPool on the same state - rotates to the other one.
    clock.now = T0 + timedelta(days=1)
    next_run = ProxyPool(pool.addresses, pool.state, clock=clock)
    assert next_run.address_for("kariyer.net").ip == "198.51.100.4"


#####################################################
# A REFUSAL                                         #
#####################################################
def test_a_refusal_rests_the_address_for_that_site_only(pool):
    refused = pool.address_for("kariyer.net")
    following = pool.on_refusal("kariyer.net", refused.ip, "HTTP 403")

    assert following.ip == "198.51.100.4"
    # Indeed has not refused it, so Indeed still starts there.
    assert pool.address_for("tr.indeed.com").ip == refused.ip


def test_the_rest_lasts_24_hours_and_outlives_the_run(pool, files, clock):
    pool.on_refusal("kariyer.net", pool.address_for("kariyer.net").ip, "HTTP 403")

    clock.now = T0 + timedelta(hours=23)
    tomorrow_early = ProxyPool(pool.addresses, PoolState(files / "state.json"), clock=clock)
    assert tomorrow_early.address_for("kariyer.net").ip != "198.51.100.2"

    clock.now = T0 + timedelta(hours=24, minutes=1)
    rested = ProxyPool(pool.addresses, PoolState(files / "state.json"), clock=clock)
    assert rested.address_for("kariyer.net").ip == "198.51.100.2"


def test_reserve_is_used_once_every_european_address_rests(pool):
    site = "kariyer.net"
    pool.on_refusal(site, pool.address_for(site).ip, "403")        # FR
    reserve = pool.on_refusal(site, pool.address_for(site).ip, "403")  # DE
    assert reserve.tier == 1


def test_three_switches_then_the_site_is_done_for_the_run(pool):
    site = "kariyer.net"
    for _ in range(3):
        assert pool.on_refusal(site, pool.address_for(site).ip, "403") is not None
    assert pool.on_refusal(site, pool.address_for(site).ip, "403") is None
    assert pool.address_for(site) is None
    assert "3 switches" in pool.given_up[site]
    # Four addresses refused, four rests recorded.
    assert sum(e["refusals"] for e in pool.state.sites[site].values()) == 4


def test_two_refusals_from_one_address_switch_only_once(pool):
    site = "kariyer.net"
    refused = pool.address_for(site).ip
    first = pool.on_refusal(site, refused, "403")
    second = pool.on_refusal(site, refused, "403")     # the request in flight

    assert first.ip == second.ip
    assert pool.switches[site] == 1


def test_state_is_written_as_the_refusal_happens(pool, files):
    pool.on_refusal("kariyer.net", pool.address_for("kariyer.net").ip, "HTTP 403")
    saved = json.loads((files / "state.json").read_text())
    entry = saved["sites"]["kariyer.net"]["198.51.100.2"]
    assert entry["refusals"] == 1
    assert entry["rest_until"] == "2026-09-23T12:00:00"


#####################################################
# THE MIDDLEWARES                                   #
#####################################################
@pytest.fixture
def crawler(pool):
    return SimpleNamespace(stats=_Stats(), _proxy_pool=pool, signals=SimpleNamespace(connect=lambda *a, **k: None))


def _spider(name):
    return SimpleNamespace(name=name, logger=SimpleNamespace(warning=lambda *a, **k: None))


def test_an_unlisted_spider_is_left_alone(crawler, monkeypatch):
    monkeypatch.setenv("PROXY_POOL_SPIDERS", "kariyernet_check")
    middleware = ProxyPoolMiddleware(crawler)
    request = Request("https://tr.indeed.com/jobs?q=staj")
    middleware.process_request(request, _spider("indeed_cards"))
    assert "proxy" not in request.meta


def test_a_listed_spider_leaves_from_its_site_s_address(crawler, monkeypatch):
    monkeypatch.setenv("PROXY_POOL_SPIDERS", "kariyernet_check, techcareer_api")
    middleware = ProxyPoolMiddleware(crawler)
    request = Request("https://www.kariyer.net/is-ilani/x-123")
    middleware.process_request(request, _spider("kariyernet_check"))

    assert request.meta["proxy"] == "http://u:p2@198.51.100.2:5002"
    assert request.meta["pool_address"] == "198.51.100.2"
    assert crawler.stats.values["pool/requests/kariyer.net"] == 1


def test_no_pool_spiders_means_the_middleware_is_off(crawler, monkeypatch):
    from scrapy.exceptions import NotConfigured
    monkeypatch.delenv("PROXY_POOL_SPIDERS", raising=False)
    with pytest.raises(NotConfigured):
        ProxyPoolMiddleware(crawler)


@pytest.fixture
def blocks(crawler):
    instance = object.__new__(BlockDetectionMiddleware)
    instance.crawler = crawler
    instance.blocks_in_a_row = defaultdict(int)
    instance.blocks_by_domain = defaultdict(int)
    return instance


def _refused(url, ip):
    request = Request(url, meta={"proxy": "http://u:x@" + ip + ":1", "pool_address": ip, "_via_proxy": True})
    return request, HtmlResponse(url, status=403, body=b"denied", request=request)


def test_a_refused_pooled_request_is_retried_from_the_next_address(blocks, pool):
    url = "https://www.kariyer.net/is-ilani/x-123"
    request, response = _refused(url, pool.address_for("kariyer.net").ip)

    retry = blocks.process_response(request, response, _spider("kariyernet_check"))

    assert retry.url == url
    assert "proxy" not in retry.meta and "pool_address" not in retry.meta
    assert pool.current["kariyer.net"].ip == "198.51.100.4"
    # The site's own block budget is not spent - the pool governs.
    assert blocks.blocks_by_domain["www.kariyer.net"] == 0


def test_when_the_pool_is_spent_the_request_is_dropped(blocks, pool):
    url = "https://www.kariyer.net/is-ilani/x-123"
    for _ in range(3):
        request, response = _refused(url, pool.address_for("kariyer.net").ip)
        blocks.process_response(request, response, _spider("kariyernet_check"))

    request, response = _refused(url, pool.address_for("kariyer.net").ip)
    with pytest.raises(IgnoreRequest):
        blocks.process_response(request, response, _spider("kariyernet_check"))
