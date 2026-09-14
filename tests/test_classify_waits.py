"""
A posting with nothing to read waits rather than being judged by its title.

The checks were moved ahead of classify on 09.09.2026 so that the model would
read the posting instead of guessing from its title. The other half of that
was missing until 12.09: a row whose description had not arrived YET was
classified anyway, from the title, and `job_category` is only ever written
once - so the guess became permanent and the description that turned up the
next night changed nothing.

On kariyer.net's first night that was roughly 16 of 40 postings, because its
posting pages are refused past a certain count while the card is stored on
its own.

The row stays VISIBLE while it waits - an unclassified posting is shown on the
dashboard, not hidden. It is simply unsorted until there is something to sort
it by, and `report_waiting` counts them out loud every run so a growing pile
is noticed.

Nothing here reaches the real database: the query is built against an
in-memory SQLite one.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from pipeline.classify_jobs import load_unclassified, report_waiting
from scraper.models import Base, JobPost


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    made = sessionmaker(bind=engine)()
    yield made
    made.close()


def _posting(session, url, description, **kwargs):
    row = JobPost(
        url=url,
        job_title=kwargs.get("job_title", "Stajyer"),
        company=kwargs.get("company", "Bir Firma"),
        location="İstanbul",
        job_type="Internship",
        source_site=kwargs.get("source_site", "kariyernet.com"),
        job_description=description,
        job_category=kwargs.get("job_category"),
        duplicate_of=kwargs.get("duplicate_of"),
        closed_at=kwargs.get("closed_at"),
    )
    session.add(row)
    session.commit()
    return row


def test_a_real_description_is_classified(session):
    _posting(session, "https://x/1", "GENEL NİTELİKLER: uzun bir açıklama")
    assert [p.url for p in load_unclassified(session)] == ["https://x/1"]


def test_a_null_description_waits(session):
    """The card was stored on its own; the posting page has not answered yet."""
    _posting(session, "https://x/2", None)
    assert load_unclassified(session) == []


def test_an_n_a_description_waits(session):
    """What the spiders write when they have nothing - DEFAULT_VALUE."""
    _posting(session, "https://x/3", "N/A")
    assert load_unclassified(session) == []


def test_an_empty_description_waits(session):
    _posting(session, "https://x/4", "")
    assert load_unclassified(session) == []


def test_the_older_filters_still_apply(session):
    """
    Waiting is a fourth reason to skip a row, not a replacement for the three
    that were already there.
    """
    _posting(session, "https://x/5", "metin", job_category="it")
    _posting(session, "https://x/6", "metin", duplicate_of=1)
    from datetime import datetime
    _posting(session, "https://x/7", "metin", closed_at=datetime.utcnow())
    assert load_unclassified(session) == []


def test_waiting_rows_are_counted_out_loud(session, capsys):
    """
    The pile has to be visible. A handful is the normal overnight lag; the
    same number growing week on week means a site has stopped giving up its
    descriptions, and that failure should not be silent.
    """
    _posting(session, "https://x/8", None, source_site="kariyernet.com")
    _posting(session, "https://x/9", "N/A", source_site="kariyernet.com")
    _posting(session, "https://x/10", None, source_site="linkedin.com")
    _posting(session, "https://x/11", "metin", source_site="kariyernet.com")

    report_waiting(session)
    printed = capsys.readouterr().out

    assert "3 posting(s) waiting" in printed
    assert "kariyernet.com" in printed
    assert "linkedin.com" in printed


def test_nothing_waiting_prints_nothing(session, capsys):
    _posting(session, "https://x/12", "metin")
    report_waiting(session)
    assert capsys.readouterr().out == ""
