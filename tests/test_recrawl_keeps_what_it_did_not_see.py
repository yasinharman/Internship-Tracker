"""
A re-crawl does not erase a field it did not see.

Since 21.09.2026 no cards spider opens a posting page, so a card sends the
spiders' default "N/A" for whatever the listing does not carry - always the
description, and on techcareer the job type when the title names none. The
pipeline must treat "N/A" as "not seen this time", not as a new value, or
every re-crawl undoes what the checks paid a request for.

Nothing here reaches the real database: the pipeline writes to an in-memory
SQLite one.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import scraper.pipelines as pipelines
from scraper.models import Base, JobPost

URL = "https://www.techcareer.net/jobs/detail/assistant-product-manager"


class _Spider:
    class logger:
        info = error = staticmethod(lambda *args, **kwargs: None)


@pytest.fixture
def engine(monkeypatch):
    made = create_engine("sqlite://")
    Base.metadata.create_all(made)
    monkeypatch.setattr(pipelines, "db_connect", lambda: made)
    return made


def _stored(engine):
    session = sessionmaker(bind=engine)()
    try:
        return session.query(JobPost).filter_by(url=URL).one()
    finally:
        session.close()


def _card(**fields):
    item = {
        "job_title": "Assistant Product Manager",
        "company": "Bir Firma",
        "location": "İstanbul",
        "url": URL,
        "source_site": "techcareer.net",
        "job_description": "N/A",
        "job_type": "N/A",
    }
    item.update(fields)
    return item


def test_a_card_without_a_type_keeps_the_stored_type(engine):
    pipeline = pipelines.JobScraperPipeline()
    pipeline.process_item(_card(job_type="Part-time"), _Spider())
    assert _stored(engine).job_type == "Part-Time"

    pipeline.process_item(_card(job_type="N/A"), _Spider())

    assert _stored(engine).job_type == "Part-Time"


def test_a_card_that_does_name_a_type_still_updates_it(engine):
    pipeline = pipelines.JobScraperPipeline()
    pipeline.process_item(_card(job_type="Part-time"), _Spider())

    pipeline.process_item(_card(job_type="Stajyer"), _Spider())

    assert _stored(engine).job_type == "Internship"


def test_a_card_keeps_the_description_the_check_wrote(engine):
    pipeline = pipelines.JobScraperPipeline()
    pipeline.process_item(_card(job_description="Ürün ekibimize destek olacak."), _Spider())

    pipeline.process_item(_card(), _Spider())

    assert _stored(engine).job_description == "Ürün ekibimize destek olacak."


def test_a_new_posting_with_no_type_is_stored_as_other(engine):
    # Unchanged: with nothing stored there is nothing to keep, and "Other" is
    # what the board's type filter already knows how to show on request.
    pipelines.JobScraperPipeline().process_item(_card(), _Spider())
    assert _stored(engine).job_type == "Other"
