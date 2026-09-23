"""
ONE COOKIE JAR PER SITE PER ADDRESS - scraper/cookie_jars.py

Harman, 23.09.2026: "çerezleri kullanarak tarayıcı kimliği oluşturma işini
her site ve IP adresi için yapalım". A jar belongs to one (site, address)
pair, so nothing an address learned travels to another address.
"""

import json
import os
import time

import pytest

from scraper import cookie_jars


@pytest.fixture(autouse=True)
def jars_in_a_temporary_place(tmp_path, monkeypatch):
    monkeypatch.setattr(cookie_jars, "JAR_DIR", tmp_path / "jars")


def a_state(name="cf_clearance", domain=".indeed.com"):
    return {"cookies": [{"name": name, "value": "abc", "domain": domain,
                         "path": "/"}], "origins": []}


def test_nothing_stored_means_the_address_has_never_been_there():
    assert cookie_jars.load("tr.indeed.com", "198.51.100.1") is None


def test_what_is_saved_comes_back():
    cookie_jars.save("tr.indeed.com", "198.51.100.1", a_state())
    stored = cookie_jars.load("tr.indeed.com", "198.51.100.1")
    assert stored["cookies"][0]["name"] == "cf_clearance"


def test_a_jar_belongs_to_one_address_and_one_site():
    cookie_jars.save("tr.indeed.com", "198.51.100.1", a_state())
    # The same site from another address, and the same address on another
    # site, both know nothing. That separation is the whole point.
    assert cookie_jars.load("tr.indeed.com", "198.51.100.2") is None
    assert cookie_jars.load("kariyer.net", "198.51.100.1") is None


def test_the_file_is_readable_only_by_us():
    path = cookie_jars.save("tr.indeed.com", "198.51.100.1", a_state())
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    assert oct(path.parent.stat().st_mode & 0o777) == "0o700"


def test_a_visit_that_left_no_cookie_is_not_stored():
    assert cookie_jars.save("tr.indeed.com", "198.51.100.1", {"cookies": []}) is None
    assert cookie_jars.load("tr.indeed.com", "198.51.100.1") is None


def test_a_stale_jar_is_thrown_away():
    path = cookie_jars.save("tr.indeed.com", "198.51.100.1", a_state())
    eight_days_ago = time.time() - 8 * 86400
    os.utime(path, (eight_days_ago, eight_days_ago))
    assert cookie_jars.load("tr.indeed.com", "198.51.100.1") is None
    assert not path.exists()


def test_a_truncated_jar_does_not_stop_the_run():
    path = cookie_jars.save("tr.indeed.com", "198.51.100.1", a_state())
    path.write_text("{ not json", encoding="utf-8")
    assert cookie_jars.load("tr.indeed.com", "198.51.100.1") is None


def test_a_site_name_cannot_escape_the_directory():
    path = cookie_jars.jar_path("../../etc/passwd", "198.51.100.1")
    assert path.parent == cookie_jars.JAR_DIR
    assert ".." not in path.name


def test_forgetting_a_jar():
    cookie_jars.save("tr.indeed.com", "198.51.100.1", a_state())
    assert cookie_jars.forget("tr.indeed.com", "198.51.100.1") is True
    assert cookie_jars.forget("tr.indeed.com", "198.51.100.1") is False


####################################################
# FOR THE TRANSPORTS THAT ARE NOT THE BROWSER      #
####################################################
def test_the_cookie_header_takes_the_hosts_own_cookies():
    state = {"cookies": [
        {"name": "a", "value": "1", "domain": ".indeed.com"},
        {"name": "b", "value": "2", "domain": "tr.indeed.com"},
        {"name": "c", "value": "3", "domain": "kariyer.net"},
    ]}
    header = cookie_jars.cookie_header(state, "tr.indeed.com")
    assert header == "a=1; b=2"


def test_no_state_is_an_empty_header():
    assert cookie_jars.cookie_header(None, "tr.indeed.com") == ""


####################################################
# WHAT THE SITE HANDS BACK                         #
####################################################
def test_a_new_cookie_is_kept():
    state = cookie_jars.remember({"cookies": []},
                                 ["sid=abc; Path=/; HttpOnly"], "kariyer.net")
    assert state["cookies"] == [
        {"name": "sid", "value": "abc", "domain": "kariyer.net", "path": "/"},
    ]


def test_a_cookie_is_replaced_not_duplicated():
    state = cookie_jars.remember({"cookies": []}, ["sid=one"], "kariyer.net")
    state = cookie_jars.remember(state, ["sid=two"], "kariyer.net")
    assert [c["value"] for c in state["cookies"]] == ["two"]


def test_the_sites_own_domain_wins_over_the_host():
    state = cookie_jars.remember({"cookies": []},
                                 ["a=1; Domain=.indeed.com"], "tr.indeed.com")
    assert state["cookies"][0]["domain"] == "indeed.com"


def test_a_cookie_the_site_cleared_is_dropped():
    state = cookie_jars.remember({"cookies": []}, ["sid=abc"], "kariyer.net")
    state = cookie_jars.remember(state, ["sid=; Max-Age=0"], "kariyer.net")
    assert state["cookies"] == []


def test_rubbish_does_not_stop_the_run():
    state = cookie_jars.remember({"cookies": []}, ["", "not a cookie at all"],
                                 "kariyer.net")
    assert isinstance(state["cookies"], list)


def test_bytes_headers_are_read():
    state = cookie_jars.remember({"cookies": []}, [b"sid=abc"], "kariyer.net")
    assert state["cookies"][0]["value"] == "abc"
