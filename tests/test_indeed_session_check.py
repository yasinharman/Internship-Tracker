"""
Which session IndeedCardsSpider checks for the sign-in cookies.

MEASURED 15.09.2026 (docs/sites/indeed.md): the check read the cookie export
while the browser loaded the storage-state file instead, so every run warned
"no SOCK/SHOE" about cookies that were never sent. Nothing here opens a
browser or makes a request.
"""

import json
import logging
from unittest.mock import MagicMock

import pytest

from scraper.spiders.indeed_cards import IndeedCardsSpider

EXPORT_WITHOUT_SOCK = {
    "__Secure-PassportAuthProxy-RefreshToken": "x", "JSESSIONID": "x", "CTK": "x",
}


def _spider(cookies):
    spider = IndeedCardsSpider.__new__(IndeedCardsSpider)
    spider.session_cookies = cookies
    spider.impersonate_candidates = ["safari184"]
    spider.session = MagicMock()
    spider.__dict__["logger"] = logging.getLogger("indeed-session-test")
    return spider


def _storage_state(tmp_path, names, domain=".indeed.com"):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({
        "cookies": [{"name": n, "value": "x", "domain": domain} for n in names],
        "origins": [],
    }))
    return str(path)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in ("INDEED_STORAGE_STATE", "INDEED_COOKIES_B64", "INDEED_COOKIES"):
        monkeypatch.delenv(var, raising=False)


def test_the_file_the_browser_loads_is_what_gets_checked(monkeypatch, tmp_path, caplog):
    monkeypatch.setenv("INDEED_STORAGE_STATE",
                       _storage_state(tmp_path, ["SOCK", "SHOE", "CTK"]))

    with caplog.at_level(logging.INFO):
        _spider(EXPORT_WITHOUT_SOCK)._require_a_whole_session()

    assert "no SOCK/SHOE" not in caplog.text
    assert "INDEED_STORAGE_STATE carries SOCK/SHOE" in caplog.text


def test_google_cookies_do_not_count_as_indeed_ones(monkeypatch, tmp_path):
    monkeypatch.setenv("INDEED_STORAGE_STATE",
                       _storage_state(tmp_path, ["SOCK", "SHOE"], ".google.com"))

    with pytest.raises(ValueError, match="save_session"):
        _spider(EXPORT_WITHOUT_SOCK)._require_a_whole_session()


def test_without_a_file_the_export_is_still_checked(caplog):
    with caplog.at_level(logging.INFO):
        _spider(EXPORT_WITHOUT_SOCK)._require_a_whole_session()

    assert "Session in INDEED_COOKIES has no SOCK/SHOE" in caplog.text


def test_an_anonymous_crawl_checks_nothing(monkeypatch, tmp_path):
    monkeypatch.setenv("INDEED_STORAGE_STATE", _storage_state(tmp_path, []))
    _spider({})._require_a_whole_session()
