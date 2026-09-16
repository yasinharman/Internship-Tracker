"""
Which Indeed postings the checker opens, and in what order.

MEASURED 16.09.2026: the checker opened 51 of 296 postings before Cloudflare
refused it, and left 245 without a description. The rule since then, in
indeed_check under "A POSTING PAGE IS OPENED WHEN THERE IS SOMETHING TO
LEARN":

    no description yet                  -> opened, first
    description, seen in a search       -> skipped
      in the last SEEN_RECENTLY_H hours
    description, not seen lately        -> opened, after the above

Nothing here reaches the real database: the queries run against an
in-memory SQLite one.
"""

import logging
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import scraper.openings as openings
from pipeline import classify_jobs
from scraper.models import Base, JobPost
from scraper.openings import OpeningCheckMixin
from scraper.spiders import indeed_check
from scraper.spiders.indeed_check import IndeedCheckSpider, probe_order

NOW = datetime(2026, 9, 17, 4, 0)
SEEN_AFTER = NOW - timedelta(hours=IndeedCheckSpider.SEEN_RECENTLY_H)
JUST_NOW = NOW - timedelta(minutes=40)
TWO_DAYS_AGO = NOW - timedelta(days=2)
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


def _queue(session, seen_after=SEEN_AFTER):
    query = session.query(JobPost).filter(JobPost.source_site == "indeed.com")
    return [row.job_title for row in probe_order(query, seen_after).all()]


class TestWhatIsOpened:

    def test_a_posting_without_a_description_is_opened_even_if_just_seen(self, session):
        # Seen in a search proves it open. It says nothing about the text.
        _posting(session, "waiting", "N/A", last_seen_at=JUST_NOW)
        assert _queue(session) == ["waiting"]

    def test_a_described_posting_the_crawl_just_saw_is_skipped(self, session):
        _posting(session, "known", DESCRIBED, checked_at=TWO_DAYS_AGO, last_seen_at=JUST_NOW)
        assert _queue(session) == []

    def test_a_described_posting_gone_from_the_searches_is_opened(self, session):
        # The one that may have closed - the reason this checker exists.
        _posting(session, "dropped", DESCRIBED, checked_at=TWO_DAYS_AGO, last_seen_at=TWO_DAYS_AGO)
        assert _queue(session) == ["dropped"]

    def test_a_described_posting_never_seen_in_a_search_is_opened(self, session):
        # last_seen_at is NULL. Written the naive way, the negated comparison
        # is NULL too and the row quietly leaves the queue.
        _posting(session, "never_seen", DESCRIBED)
        assert _queue(session) == ["never_seen"]

    def test_the_skip_is_exactly_the_window(self, session):
        _posting(session, "inside", DESCRIBED, last_seen_at=SEEN_AFTER)
        _posting(session, "outside", DESCRIBED, last_seen_at=SEEN_AFTER - timedelta(seconds=1))
        assert _queue(session) == ["outside"]

    @pytest.mark.parametrize("missing", [None, "N/A", ""])
    def test_every_way_of_having_no_description_counts(self, session, missing):
        _posting(session, "waiting", missing, last_seen_at=JUST_NOW)
        assert _queue(session) == ["waiting"]

    def test_it_waits_on_the_same_values_classify_does(self):
        # Otherwise a row could be one that classify is waiting for and that
        # this checker thinks it has already described.
        assert set(indeed_check.NO_DESCRIPTION) == set(classify_jobs.NO_DESCRIPTION)


class TestTheOrder:

    def test_no_description_goes_before_a_row_never_checked(self, session):
        _posting(session, "never_checked", DESCRIBED)
        _posting(session, "checked_no_text", "N/A", checked_at=TWO_DAYS_AGO)
        assert _queue(session) == ["checked_no_text", "never_checked"]

    def test_among_the_waiting_the_unchecked_go_first(self, session):
        _posting(session, "checked_no_text", "N/A", checked_at=TWO_DAYS_AGO)
        _posting(session, "unchecked", "N/A")
        assert _queue(session) == ["unchecked", "checked_no_text"]

    def test_the_rows_a_refusal_left_go_before_tonights_new_ones(self, session):
        _posting(session, "refused_yesterday", "N/A", last_seen_at=JUST_NOW)
        _posting(session, "new_tonight", "N/A", last_seen_at=JUST_NOW)
        assert _queue(session) == ["refused_yesterday", "new_tonight"]

    def test_the_night_of_16_09_in_miniature(self, session):
        # 245 without a description, 51 with one, all seen by that run's crawl.
        # The next night's crawl sees them again: only the 245 are opened.
        for n in range(3):
            _posting(session, f"waiting{n}", "N/A", last_seen_at=JUST_NOW)
        for n in range(2):
            _posting(session, f"described{n}", DESCRIBED,
                     checked_at=NOW - timedelta(hours=18), last_seen_at=JUST_NOW)
        assert _queue(session) == ["waiting0", "waiting1", "waiting2"]


class TestTheSpider:

    def test_other_sites_keep_the_old_order(self, session):
        # The hook's default is what load_open_postings did before it existed.
        _posting(session, "checked", DESCRIBED, checked_at=TWO_DAYS_AGO, last_seen_at=JUST_NOW)
        _posting(session, "unchecked", DESCRIBED, last_seen_at=JUST_NOW)
        query = session.query(JobPost)
        rows = OpeningCheckMixin.probe_query(None, query).all()
        assert [row.job_title for row in rows] == ["unchecked", "checked"]

    def test_load_open_postings_uses_it_and_says_what_it_skipped(
        self, make_checker, engine, session, monkeypatch, caplog,
    ):
        recent = datetime.utcnow() - timedelta(minutes=40)
        _posting(session, "waiting", "N/A", last_seen_at=recent)
        _posting(session, "known", DESCRIBED, checked_at=recent, last_seen_at=recent)
        _posting(session, "dropped", DESCRIBED, checked_at=TWO_DAYS_AGO, last_seen_at=TWO_DAYS_AGO)
        _posting(session, "linkedin", "N/A", source_site="linkedin.com")
        monkeypatch.setattr(openings, "db_connect", lambda: engine)
        spider = make_checker(IndeedCheckSpider)

        with caplog.at_level(logging.INFO):
            rows = spider.load_open_postings()

        assert [row["job_title"] for row in rows] == ["waiting", "dropped"]
        assert "1 posting(s) without a description go first. 1 with one" in caplog.text

    def test_the_cap_is_applied_after_the_order(
        self, make_checker, engine, session, monkeypatch,
    ):
        # OPENINGS_MAX_PER_SITE must cut the queue's tail, not a random slice.
        _posting(session, "dropped", DESCRIBED, checked_at=TWO_DAYS_AGO, last_seen_at=TWO_DAYS_AGO)
        _posting(session, "waiting", "N/A")
        monkeypatch.setattr(openings, "db_connect", lambda: engine)
        monkeypatch.setattr(openings, "MAX_PER_SITE", 1)
        spider = make_checker(IndeedCheckSpider)

        assert [row["job_title"] for row in spider.load_open_postings()] == ["waiting"]
