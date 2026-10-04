"""
COUNTING RUNS, NOT DAYS - scraper/scans.py

Harman, 03.10.2026: a described posting is opened again only after it has been
missing from three COMPLETE scans of its site. The point of counting runs
rather than days is the case this project actually hit: nothing ran between
23.09 and 03.10, and a rule written in days would have called every posting
"missed three runs" and spent 400 requests on the next run.

So what has to hold is narrow and testable: a scan counts only when the
searches reached their end, and with fewer than three such scans the rule has
no opinion at all.
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import scraper.scans as scans
from scraper.models import Base, SiteScan

NOW = datetime(2026, 10, 3, 12, 0)


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    made = sessionmaker(bind=engine)()
    yield made
    made.close()


def _scan(session, site, moment, complete=True, note=None):
    session.add(SiteScan(site=site, finished_at=moment, complete=complete,
                         postings=1, note=note))
    session.commit()


####################################################
# WHAT MAKES A SCAN COMPLETE                       #
####################################################
def test_a_crawl_that_reached_the_end_of_its_searches_is_complete():
    assert scans.why_incomplete({"item_scraped_count": 173}, "finished") is None


def test_a_repeated_page_does_not_make_it_incomplete():
    # Reason 2 in api_spider.next_page_allowed: the site is telling us it has
    # nothing more to give, which IS the end of the search.
    stats = {"pagination/repeated_page": 2, "item_scraped_count": 40}
    assert scans.why_incomplete(stats, "finished") is None


def test_a_search_that_did_not_reach_its_end_makes_the_scan_incomplete():
    note = scans.why_incomplete(
        {"item_scraped_count": 300, "searches/started": 3,
         "searches/ended": 2, "searches/cut_short": 1}, "finished")
    assert note == "searches/cut_short=1"


def test_a_lost_page_alone_does_not_make_it_incomplete():
    """
    HIS RULE, 04.10.2026: "her arama kendi sonuna ulastiysa tam sayilir,
    aradaki bir sayfanin dusmesi tamligi bozmaz."

    The stricter reading it replaced would have left Indeed permanently
    incomplete: that afternoon it answered 2 of 39 requests with a challenge
    and served the rest, so one lost page per run would have meant the
    run-counting rule never applying to the site with the largest queue.
    """
    stats = {"item_scraped_count": 434, "searches/started": 3,
             "searches/ended": 3, "searches/cut_short": 0,
             "pagination/page_lost": 1, "pool/pinned_refused": 2}
    assert scans.why_incomplete(stats, "finished") is None


def test_a_scan_that_collected_nothing_is_incomplete():
    # Whatever the searches say: every one of these sites has postings on it,
    # so nothing collected means something broke. This is what catches the
    # 03.10 case, where chromium was missing and every request failed.
    assert scans.why_incomplete(
        {"searches/cut_short": 0, "item_scraped_count": 0}, "finished",
    ) == "no postings collected"
    assert scans.why_incomplete(
        {"downloader/exception_count": 4, "item_scraped_count": 0}, "finished",
    ) == "no postings collected"


def test_a_callback_that_raised_is_incomplete():
    # The page arrived and we failed to read it, so the search's own
    # bookkeeping cannot be trusted either.
    note = scans.why_incomplete(
        {"spider_exceptions/ValueError": 1, "item_scraped_count": 5}, "finished")
    assert note == "spider_exceptions/ValueError=1"


def test_a_crawl_that_did_not_finish_is_incomplete():
    # main.py kills a spider that overruns its timeout; Scrapy's own shutdown
    # paths look the same from here.
    note = scans.why_incomplete({}, "closespider_timeout")
    assert note == "finish_reason=closespider_timeout"


def test_the_finish_reason_in_the_stats_is_read_too():
    assert scans.why_incomplete({"finish_reason": "shutdown"}) is not None


####################################################
# WRITING ONE                                      #
####################################################
def test_a_complete_scan_is_recorded_with_what_it_found(session):
    scan = scans.record("indeed.com", {"item_scraped_count": 559}, "finished",
                        session=session)
    assert (scan.complete, scan.postings, scan.note) == (True, 559, None)


def test_an_incomplete_scan_keeps_the_reason(session):
    scan = scans.record("indeed.com", {"item_scraped_count": 40,
                                       "searches/cut_short": 2}, "finished",
                        session=session)
    assert scan.complete is False
    assert "searches/cut_short" in scan.note


####################################################
# THE ONLY QUESTION ASKED OF THEM                  #
####################################################
def test_the_cutoff_is_the_third_scan_back(session):
    for days in (1, 2, 3, 4):
        _scan(session, "indeed.com", NOW - timedelta(days=days))
    assert scans.missed_since(session, "indeed.com", scans=3) == NOW - timedelta(days=3)


def test_two_complete_scans_are_no_opinion(session):
    _scan(session, "indeed.com", NOW - timedelta(days=1))
    _scan(session, "indeed.com", NOW - timedelta(days=2))
    assert scans.missed_since(session, "indeed.com", scans=3) is None


def test_incomplete_scans_are_not_counted(session):
    _scan(session, "indeed.com", NOW - timedelta(days=1))
    _scan(session, "indeed.com", NOW - timedelta(days=2))
    _scan(session, "indeed.com", NOW - timedelta(hours=2), complete=False,
          note="pagination/hit_ceiling=1")
    assert scans.missed_since(session, "indeed.com", scans=3) is None


def test_each_site_is_counted_on_its_own(session):
    for days in (1, 2, 3):
        _scan(session, "kariyernet.com", NOW - timedelta(days=days))
    assert scans.missed_since(session, "kariyernet.com", scans=3) is not None
    assert scans.missed_since(session, "indeed.com", scans=3) is None


def test_zero_switches_the_rule_off(session):
    for days in (1, 2, 3):
        _scan(session, "indeed.com", NOW - timedelta(days=days))
    assert scans.missed_since(session, "indeed.com", scans=0) is None


def test_the_ten_day_horizon_leaves_room_for_three_runs():
    # The two rules share one clock: three runs at the three-day cadence is
    # about nine days, and the board lets a posting go at ten. Set the horizon
    # below nine and the board would drop postings the checker never asked
    # about. See the note on UNLISTED_AFTER_DAYS.
    from scraper.models import UNLISTED_AFTER_DAYS

    cadence_days = 3
    assert UNLISTED_AFTER_DAYS > cadence_days * scans.MISSED_SCANS_BEFORE_CHECK - 1


####################################################
# WHO WRITES ONE                                   #
####################################################
class _Stats:
    def __init__(self, values):
        self.values = values

    def get_stats(self):
        return self.values


class _Crawler:
    def __init__(self, values):
        self.stats = _Stats(values)


def _spider(spider_class, stats):
    spider = object.__new__(spider_class)
    spider.crawler = _Crawler(stats)
    return spider


def test_a_cards_spider_records_its_scan(monkeypatch):
    from scraper.spiders.indeed_cards import IndeedCardsSpider

    written = []
    monkeypatch.setattr(scans, "record",
                        lambda site, stats, reason: written.append((site, stats, reason)))
    _spider(IndeedCardsSpider, {"item_scraped_count": 559})._record_scan("finished")

    assert written == [("indeed.com", {"item_scraped_count": 559}, "finished")]


def test_a_checker_records_nothing(monkeypatch):
    from scraper.spiders.indeed_check import IndeedCheckSpider

    written = []
    monkeypatch.setattr(scans, "record", lambda *a: written.append(a))
    _spider(IndeedCheckSpider, {"item_scraped_count": 81})._record_scan("finished")

    assert written == []


def test_a_failure_while_recording_does_not_break_the_crawl(monkeypatch, caplog):
    # The postings are already stored by then. Losing the scan row costs the
    # next run a fallback to queueing everything, not the crawl.
    from scraper.spiders.indeed_cards import IndeedCardsSpider

    def boom(*args):
        raise RuntimeError("database is gone")

    monkeypatch.setattr(scans, "record", boom)
    spider = _spider(IndeedCardsSpider, {})
    spider._record_scan("finished")        # must not raise
