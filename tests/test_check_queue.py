"""
Which postings a checker opens, and in what order.

MEASURED 16.09.2026: the Indeed checker opened 51 of 296 postings before
Cloudflare refused it, and left 245 without a description. The rule written
after it lived in indeed_check and was measured in hours; on 03.10.2026 it
moved to scraper/openings.py, became every site's, and started counting RUNS
instead (Harman: "last seen değerini gün bazında yapmak yerine 3 aramada 1
yapalım"):

    no description yet                      -> opened, first
    described, seen since the third most    -> skipped, no request spent
      recent COMPLETE scan of the site
    described, missing from three           -> opened, after the above
      complete scans

Nothing here reaches the real database or a site: the queries run against an
in-memory SQLite one.
"""

import logging
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import scraper.openings as openings
import scraper.scans as scans
from pipeline import classify_jobs
from scraper.models import Base, JobPost, SiteScan
from scraper.openings import OpeningCheckMixin
from scraper.spiders.indeed_check import IndeedCheckSpider

DESCRIBED = "Staj programımız için yazılım geliştirme öğrencisi arıyoruz."


@pytest.fixture
def engine():
    made = create_engine("sqlite://")
    Base.metadata.create_all(made)
    return made


@pytest.fixture
def session(engine):
    made = sessionmaker(bind=engine)()
    yield made
    made.close()


def ago(**kwargs):
    """Relative to the real clock: load_open_postings compares against utcnow()."""
    return datetime.utcnow() - timedelta(**kwargs)


def _posting(session, name, description, *, checked_at=None, last_seen_at=None, **kwargs):
    row = JobPost(
        url=f"https://tr.indeed.com/viewjob?jk={name}",
        job_title=name,
        company="Bir Firma",
        location="İstanbul",
        job_type="Internship",
        source_site=kwargs.get("source_site", "indeed.com"),
        job_description=description,
        checked_at=checked_at,
        last_seen_at=last_seen_at,
    )
    session.add(row)
    session.commit()
    return row


def _scans(session, *finished, site="indeed.com", complete=True):
    for moment in finished:
        session.add(SiteScan(site=site, finished_at=moment, complete=complete,
                             postings=10))
    session.commit()


@pytest.fixture
def three_scans(session):
    """
    Three complete scans, the oldest of them three days back. A posting seen
    since that one has not missed three scans; one seen before it has.
    """
    _scans(session, ago(days=3), ago(days=2), ago(days=1))
    return ago(days=3)


def _opened(spider):
    return [row["job_title"] for row in spider.load_open_postings()]


@pytest.fixture
def checker(make_checker, engine, monkeypatch):
    monkeypatch.setattr(openings, "db_connect", lambda: engine)
    return make_checker(IndeedCheckSpider)


class TestWhatIsOpened:

    def test_a_posting_without_a_description_is_opened_even_if_just_seen(
        self, session, checker, three_scans,
    ):
        # Seen in a search proves it open. It says nothing about the text, and
        # the text is what classify sorts on.
        _posting(session, "waiting", "N/A", last_seen_at=ago(minutes=40))
        assert _opened(checker) == ["waiting"]

    def test_a_described_posting_the_crawl_keeps_seeing_is_skipped(
        self, session, checker, three_scans,
    ):
        _posting(session, "known", DESCRIBED, checked_at=ago(days=2),
                 last_seen_at=ago(minutes=40))
        assert _opened(checker) == []

    def test_a_described_posting_missing_from_three_scans_is_opened(
        self, session, checker, three_scans,
    ):
        # The one that may have closed - the reason this checker exists.
        _posting(session, "dropped", DESCRIBED, checked_at=ago(days=4),
                 last_seen_at=ago(days=4))
        assert _opened(checker) == ["dropped"]

    def test_a_described_posting_never_seen_in_a_search_is_opened(
        self, session, checker, three_scans,
    ):
        # last_seen_at is NULL. Written the naive way, the negated comparison
        # is NULL too and the row quietly leaves the queue.
        _posting(session, "never_seen", DESCRIBED)
        assert _opened(checker) == ["never_seen"]

    def test_the_skip_is_exactly_the_third_scan_back(
        self, session, checker, three_scans,
    ):
        _posting(session, "inside", DESCRIBED, last_seen_at=three_scans)
        _posting(session, "outside", DESCRIBED,
                 last_seen_at=three_scans - timedelta(seconds=1))
        assert _opened(checker) == ["outside"]

    @pytest.mark.parametrize("missing", [None, "N/A", ""])
    def test_every_way_of_having_no_description_counts(
        self, session, checker, three_scans, missing,
    ):
        _posting(session, "waiting", missing, last_seen_at=ago(minutes=40))
        assert _opened(checker) == ["waiting"]

    def test_it_waits_on_the_same_values_classify_does(self):
        # Otherwise a row could be one that classify is waiting for and that
        # this checker thinks it has already described.
        assert set(openings.NO_DESCRIPTION) == set(classify_jobs.NO_DESCRIPTION)


class TestWhenTheRuleStaysOut:
    """
    The rule is an optimisation, and an optimisation that fires on no evidence
    is a bug. Every case here falls back to what the checkers did before
    03.10.2026: ask about everything.
    """

    def test_fewer_than_three_complete_scans_skips_nothing(self, session, checker):
        _scans(session, ago(days=2), ago(days=1))
        _posting(session, "known", DESCRIBED, last_seen_at=ago(minutes=40))
        assert _opened(checker) == ["known"]

    def test_an_incomplete_scan_does_not_count_towards_the_three(
        self, session, checker,
    ):
        # Two complete and one cut short: the site has not been scanned three
        # times, whatever the row count says.
        _scans(session, ago(days=2), ago(days=1))
        _scans(session, ago(hours=2), complete=False)
        _posting(session, "known", DESCRIBED, last_seen_at=ago(minutes=40))
        assert _opened(checker) == ["known"]

    def test_another_sites_scans_are_not_ours(self, session, checker):
        _scans(session, ago(days=3), ago(days=2), ago(days=1), site="kariyernet.com")
        _posting(session, "known", DESCRIBED, last_seen_at=ago(minutes=40))
        assert _opened(checker) == ["known"]

    def test_the_rule_can_be_switched_off(self, session, checker, three_scans, monkeypatch):
        monkeypatch.setattr(scans, "MISSED_SCANS_BEFORE_CHECK", 0)
        _posting(session, "known", DESCRIBED, last_seen_at=ago(minutes=40))
        assert _opened(checker) == ["known"]


class TestTheOrder:

    def _queued(self, session):
        query = session.query(JobPost).filter(JobPost.source_site == "indeed.com")
        rows = OpeningCheckMixin.probe_query(None, query).all()
        return [row.job_title for row in rows]

    def test_no_description_goes_before_a_row_never_checked(self, session):
        _posting(session, "never_checked", DESCRIBED)
        _posting(session, "checked_no_text", "N/A", checked_at=ago(days=2))
        assert self._queued(session) == ["checked_no_text", "never_checked"]

    def test_among_the_waiting_the_unchecked_go_first(self, session):
        _posting(session, "checked_no_text", "N/A", checked_at=ago(days=2))
        _posting(session, "unchecked", "N/A")
        assert self._queued(session) == ["unchecked", "checked_no_text"]

    def test_the_rows_a_refusal_left_go_before_tonights_new_ones(self, session):
        _posting(session, "refused_yesterday", "N/A", last_seen_at=ago(minutes=40))
        _posting(session, "new_tonight", "N/A", last_seen_at=ago(minutes=40))
        assert self._queued(session) == ["refused_yesterday", "new_tonight"]

    def test_every_checker_gets_this_order_now(self, session):
        # It was indeed_check's own until 03.10.2026, and nothing about it was
        # specific to Indeed once every site's description came from a checker.
        assert "probe_query" not in IndeedCheckSpider.__dict__


class TestTheWholeQueue:

    def test_what_a_run_opens_and_what_it_says_it_skipped(
        self, session, checker, three_scans, caplog,
    ):
        _posting(session, "waiting", "N/A", last_seen_at=ago(minutes=40))
        _posting(session, "known", DESCRIBED, checked_at=ago(minutes=40),
                 last_seen_at=ago(minutes=40))
        _posting(session, "dropped", DESCRIBED, checked_at=ago(days=4),
                 last_seen_at=ago(days=4))
        _posting(session, "linkedin", "N/A", source_site="linkedin.com")

        with caplog.at_level(logging.INFO):
            assert _opened(checker) == ["waiting", "dropped"]

        assert "1 posting(s) skipped" in caplog.text

    def test_the_night_of_16_09_in_miniature(self, session, checker, three_scans):
        # 245 without a description, 51 with one, all seen by that run's crawl.
        # The next run sees them again: only the undescribed ones are opened.
        for n in range(3):
            _posting(session, f"waiting{n}", "N/A", last_seen_at=ago(minutes=40))
        for n in range(2):
            _posting(session, f"described{n}", DESCRIBED,
                     checked_at=ago(hours=18), last_seen_at=ago(minutes=40))
        assert _opened(checker) == ["waiting0", "waiting1", "waiting2"]

    def test_the_cap_is_applied_after_the_order(
        self, session, checker, three_scans, monkeypatch,
    ):
        # OPENINGS_MAX_PER_SITE must cut the queue's tail, not a random slice.
        _posting(session, "dropped", DESCRIBED, checked_at=ago(days=4),
                 last_seen_at=ago(days=4))
        _posting(session, "waiting", "N/A")
        monkeypatch.setattr(openings, "MAX_PER_SITE", 1)
        assert _opened(checker) == ["waiting"]

    def test_a_checker_never_records_a_scan_of_its_own(self):
        # It reads a queue it was handed; it does not read the search results,
        # so a scan row from it would claim a scan that never happened.
        assert IndeedCheckSpider.RECORDS_A_SCAN is False
