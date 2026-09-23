"""
The board shows sorted postings only.

Until 16.09.2026 a posting with no category was shown whatever the field
filter said. The owner reversed that the day Indeed's first full run left 245
of its 296 postings waiting for a description, and so for classify. The rows
are still counted, so a classify step that has stopped working shows up as a
growing number rather than as a quietly shrinking board.

Nothing here reaches the real database: the queries run against an in-memory
SQLite one.
"""

from datetime import datetime

import pytest
from sqlalchemy import and_, create_engine, select
from sqlalchemy.orm import sessionmaker

import api.main as api
import api.queries as q
from api.filters import Filters
from scraper.models import Base, JobPost, JobPostField


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    made = sessionmaker(bind=engine)()
    yield made
    made.close()


def _posting(session, name, category, **kwargs):
    posting = JobPost(
        url=f"https://x/{name}",
        job_title=name,
        company="Bir Firma",
        location="İstanbul",
        job_type="Internship",
        source_site=kwargs.get("source_site", "indeed.com"),
        job_description="metin",
        job_category=category,
        closed_at=kwargs.get("closed_at"),
    )
    session.add(posting)
    session.commit()
    # A posting's fields live in their own table since 23.09.2026, and the
    # dashboard's "Alan" filter asks that table - see q.category_condition.
    for rank, field in enumerate(kwargs.get("fields") or ([category] if category else [])):
        session.add(JobPostField(job_post_id=posting.id, field=field, rank=rank))
    session.commit()


def _shown(session, filters):
    rows = session.scalars(select(JobPost).where(and_(*q.conditions(filters))))
    return sorted(row.job_title for row in rows)


def test_an_unsorted_posting_is_not_shown_with_no_field_filter(session):
    _posting(session, "sorted", "yazilim")
    _posting(session, "waiting", None)
    assert _shown(session, Filters()) == ["sorted"]


def test_an_unsorted_posting_is_not_shown_under_a_field_filter(session):
    # The rule this replaced let NULL through exactly here.
    _posting(session, "sorted", "yazilim")
    _posting(session, "waiting", None)
    assert _shown(session, Filters(categories=["yazilim", "genel_program"])) == ["sorted"]


def test_the_field_filter_still_filters(session):
    _posting(session, "yazilim", "yazilim")
    _posting(session, "program", "genel_program")
    _posting(session, "elsewhere", "other")
    assert _shown(session, Filters(categories=["yazilim"])) == ["yazilim"]


def test_the_closed_toggle_brings_back_sorted_closed_postings_only(session):
    closed = datetime(2026, 9, 15)
    _posting(session, "closed_sorted", "yazilim", closed_at=closed)
    _posting(session, "closed_waiting", None, closed_at=closed)
    assert _shown(session, Filters(closed=True)) == ["closed_sorted"]


def test_the_waiting_rows_are_counted_for_the_same_filter(session):
    _posting(session, "sorted", "yazilim")
    _posting(session, "waiting_indeed", None)
    _posting(session, "waiting_linkedin", None, source_site="linkedin.com")
    # Closed: classify never sorts it, so it is not waiting for anything.
    _posting(session, "closed_waiting", None, closed_at=datetime(2026, 9, 15))

    waiting = Filters(sources=["indeed.com"], categories=["yazilim"])
    assert q.count_where(session, q.conditions(waiting, waiting=True)) == 1
    assert q.count_where(session, q.conditions(Filters(closed=True), waiting=True)) == 2


def test_meta_counts_what_it_hides_and_what_the_toggle_adds(session):
    _posting(session, "sorted", "yazilim")
    _posting(session, "waiting", None)
    _posting(session, "closed_sorted", "yazilim", closed_at=datetime(2026, 9, 15))
    _posting(session, "closed_waiting", None, closed_at=datetime(2026, 9, 15))

    meta = api.meta(session=session)

    assert meta.unclassified_count == 1
    assert meta.closed_count == 1
    # The database is not empty just because nothing is sorted yet.
    assert meta.total == 4
