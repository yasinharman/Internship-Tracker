"""
Classify holds no database connection while the model works.

The first full run on the local model (21.09.2026) sorted 314 postings in
about 400 s and then lost every verdict: the write found its connection gone.
It had sat idle, holding the read transaction, for the whole run, and
something between here and the server drops a connection that idle. With the
API a batch took under a minute, so the gap was never long enough to show.

So the rows are read, the connection is let go, the model runs, and the write
opens a fresh connection. These tests hold main() to that order, against a
SQLite file standing in for Postgres - nothing reaches a server or a model.
"""

import sys

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import pipeline.classify_jobs as classify_jobs
from scraper.classifier import JobCategory
from scraper.models import Base, JobPost


@pytest.fixture
def engine(tmp_path, monkeypatch):
    # A file, not ":memory:" - dispose() would take an in-memory database
    # with it, and the point is that the data outlives the connection.
    made = create_engine(f"sqlite:///{tmp_path / 'jobs.db'}")
    Base.metadata.create_all(made)
    session = sessionmaker(bind=made)()
    session.add(JobPost(
        url="https://x/1",
        job_title="Yazılım Stajyeri",
        company="Bir Firma",
        location="İstanbul",
        job_type="Internship",
        source_site="kariyernet.com",
        job_description="Python bilen stajyer arıyoruz.",
    ))
    session.commit()
    session.close()

    monkeypatch.setattr(classify_jobs, "db_connect", lambda: made)
    monkeypatch.setattr(sys, "argv", ["classify_jobs"])
    return made


def test_no_connection_is_held_while_the_model_works(engine, monkeypatch):
    seen = {}

    def classify_all(rows, model):
        seen["checked_out"] = engine.pool.checkedout()
        return {rows[0]["id"]: JobCategory(category="it", reason="Yazılım stajı.")}

    monkeypatch.setattr(classify_jobs, "classify_all", classify_all)
    classify_jobs.main()

    assert seen["checked_out"] == 0


def test_the_verdict_is_still_written_afterwards(engine, monkeypatch):
    monkeypatch.setattr(
        classify_jobs, "classify_all",
        lambda rows, model: {rows[0]["id"]: JobCategory(category="it", reason="Yazılım stajı.")},
    )
    classify_jobs.main()

    session = sessionmaker(bind=engine)()
    (posting,) = session.query(JobPost).all()
    assert posting.job_category == "it"
    assert posting.category_reason == "Yazılım stajı."
    assert posting.classified_at is not None
    session.close()
