"""
A posting the crawl has stopped seeing drops off the board and out of the
checker's queue.

DECIDED 20.09.2026, as the crude stand-in for docs/activity-checks-plan.md.
The per-posting check request is what the sites refuse - Indeed stopped
answering after 145 of them on 16.09.2026 - so the queue has to stop growing
before anything cleverer is built. The rule is one WHERE clause in two places
and writes nothing: scraper.models.UNLISTED_AFTER_DAYS.

What these tests are really guarding is the two ways it could go wrong
quietly: hiding a posting that IS still listed, and hiding the closed pile
that the "Kapananlar" toggle exists to show.

Nothing here reaches the real database: the queries run against an in-memory
SQLite one.
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import and_, create_engine, select
from sqlalchemy.orm import sessionmaker

import api.queries as q
import scraper.openings as openings
from api.filters import Filters
from scraper.models import UNLISTED_AFTER_DAYS, Base, JobPost
from scraper.spiders.kariyernet_check import KariyerNetCheckSpider

NOW = datetime(2026, 9, 20, 6, 0)
STILL_LISTED = NOW - timedelta(days=2)
GONE_QUIET = NOW - timedelta(days=UNLISTED_AFTER_DAYS + 1)


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


def _posting(session, name, last_seen_at, **kwargs):
    session.add(JobPost(
        url=f"https://www.kariyer.net/is-ilani/{name}",
        job_title=name,
        company="Bir Firma",
        location="İstanbul",
        job_type="Internship",
        source_site="kariyernet.com",
        job_description="Staj programı için öğrenci arıyoruz.",
        job_category=kwargs.get("job_category", "it"),
        closed_at=kwargs.get("closed_at"),
        last_seen_at=last_seen_at,
    ))
    session.commit()


def _shown(session, filters=None):
    rows = session.scalars(
        select(JobPost).where(and_(*q.conditions(filters or Filters())))
    )
    return sorted(row.job_title for row in rows)


class TestTheBoard:

    @pytest.fixture(autouse=True)
    def pinned_clock(self, monkeypatch):
        """
        Pin the clock the horizon is measured against, and pin it in ONE
        place - the helper the board itself calls. An earlier version of this
        file added the horizon to the WHERE clause by hand instead, which
        made the closed-toggle test fail against correct code: conditions()
        leaves the horizon out on purpose there, and the test put it back.
        """
        monkeypatch.setattr(q, "utcnow", lambda: NOW)

    def test_a_posting_seen_in_the_last_crawl_is_shown(self, session):
        _posting(session, "listed", STILL_LISTED)
        assert _shown(session) == ["listed"]

    def test_a_posting_nobody_has_seen_for_a_week_is_not(self, session):
        _posting(session, "listed", STILL_LISTED)
        _posting(session, "quiet", GONE_QUIET)
        assert _shown(session) == ["listed"]

    def test_a_row_with_no_last_seen_at_stays(self, session):
        # NULL is a row written before the column existed, not evidence that
        # the posting has gone. Hiding on missing evidence is the direction
        # this project refuses to fail in.
        _posting(session, "unknown", None)
        assert _shown(session) == ["unknown"]

    def test_the_closed_toggle_still_shows_old_closed_postings(self, session):
        # Closed postings are old by definition - they left the listings. If
        # the horizon applied to them too, "Kapananlar" would empty itself a
        # week after every closure.
        _posting(session, "closed_long_ago", GONE_QUIET, closed_at=NOW - timedelta(days=8))
        assert _shown(session, Filters(closed=True)) == ["closed_long_ago"]


class TestTheCheckerQueue:

    def test_the_queue_leaves_out_what_the_crawl_stopped_seeing(
        self, make_checker, engine, session, monkeypatch,
    ):
        # The request saving is entirely here: one row fewer in this list is
        # one request fewer against a site that refuses after 145 of them.
        _posting(session, "listed", datetime.utcnow() - timedelta(days=2))
        _posting(session, "quiet", datetime.utcnow() - timedelta(days=UNLISTED_AFTER_DAYS + 1))
        monkeypatch.setattr(openings, "db_connect", lambda: engine)
        spider = make_checker(KariyerNetCheckSpider)

        rows = spider.load_open_postings()

        assert [row["job_title"] for row in rows] == ["listed"]

    def test_a_row_with_no_last_seen_at_is_still_checked(
        self, make_checker, engine, session, monkeypatch,
    ):
        _posting(session, "unknown", None)
        monkeypatch.setattr(openings, "db_connect", lambda: engine)
        spider = make_checker(KariyerNetCheckSpider)

        assert [row["job_title"] for row in spider.load_open_postings()] == ["unknown"]
