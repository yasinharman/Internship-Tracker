from sqlalchemy import create_engine, Integer, String, Boolean, Column, Text, DateTime, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from datetime import datetime
import os

# WE ARE USING 'Base' INSIDE OF OUR CLASSES TO INDICATE THAT WE ARE CREATING A SQL TABLE INSIDE THE CLASS
Base = declarative_base()

###################################################################
# CREATED OUR TABLE'S STRUCTURE ON THE DATABASE USING SQL ALCHEMY #
###################################################################
class JobPost(Base):
    __tablename__ = "job_posts"
    id = Column(Integer, primary_key=True)

    job_title = Column(String, nullable=False)

    company = Column(String)

    location = Column(String)

    job_description = Column(Text)

    url = Column(String, unique=True, nullable=False)

    source_site = Column(String, nullable=False)

    created_at = Column(DateTime, default=lambda: datetime.utcnow())
    updated_at = Column(DateTime, default=lambda: datetime.utcnow(), onupdate=lambda: datetime.utcnow())
    is_active = Column(Boolean, default=True)

    job_type = Column(String)

    ###################################################################
    # LLM CLASSIFICATION                                              #
    ###################################################################
    # Filled in by pipeline/classify_jobs.py after the crawl. NULL means "not looked
    # at yet", which the dashboard treats as visible - an outage of the LLM
    # API must not empty the board.
    #
    # 'other' postings are not deleted; is_active is set to False instead, so
    # a wrong call can be undone with one UPDATE. reason is kept so that the
    # decision can be read back and argued with.
    # index=True so a database created from scratch by create_all() ends up
    # with the same indexes tools/migrate.py adds to an existing one. Without it the
    # two paths diverge silently: a fresh deploy gets the columns but not the
    # indexes, and classify_jobs scans the whole table on every run.
    # SQLAlchemy names these ix_job_posts_<column>, matching tools/migrate.py.
    job_category = Column(String(32), index=True)  # it|general_program|other
    category_reason = Column(Text)
    classified_at = Column(DateTime)

    ###################################################################
    # THE SAME JOB, ADVERTISED ON TWO BOARDS                          #
    ###################################################################
    # techcareer.net belongs to kariyer.net and carries the same ads, so one
    # opening arrives twice under two urls - two rows, since url is what makes
    # a posting unique and it is genuinely different.
    #
    # NULL means "this is the row to show". Otherwise it points at the row
    # this one duplicates. Deliberately not folded into is_active: that flag
    # belongs to the classifier, and a second writer would resurrect or hide
    # rows behind its back. Points at an id rather than being a boolean so the
    # pairing can be read back and argued with.
    duplicate_of = Column(Integer, ForeignKey("job_posts.id"), index=True)

    ###################################################################
    # WATCHLIST NOTIFICATION (Hermes agent / Telegram)                #
    ###################################################################
    # Set by pipeline/notify_watchlist.py once a matching posting has been handed to
    # the Hermes webhook successfully. NULL means "not tried yet, or the last
    # attempt failed" - either way the next run will retry it, same shape as
    # job_category above.
    notified_at = Column(DateTime)

    ###################################################################
    # STILL ON OFFER?                                                 #
    ###################################################################
    # Owned by the three *_check spiders (scraper/openings.py).
    # NULL means "still open"; a value is the moment a check found the
    # posting gone from the board it came from.
    #
    # Deliberately NOT folded into is_active, for the same reason
    # duplicate_of is not: that column already has two writers - the
    # classifier sets it False for another field, and pipelines.py sets it
    # back to True on every re-crawl. A third writer would have them
    # resurrecting each other's rows, and a closed posting would come back to
    # life on the next run. It also has to stay separate for the dashboard:
    # "kapandi" and "baska alan" are different things to a person, and the
    # board's toggle only reveals the first.
    #
    # index=True because every dashboard query now carries
    # `closed_at IS NULL` - same reasoning as job_category above, and
    # tools/migrate.py adds the matching index to an existing database.
    closed_at = Column(DateTime, index=True)

    # When a check last got a CONCLUSIVE answer. A blocked or timed-out probe
    # leaves this alone on purpose, so "checked and open" stays
    # distinguishable from "never successfully checked" - which is the whole
    # database on the day this ships.
    checked_at = Column(DateTime)

    # Written by pipelines.py on every upsert: this url was in a search
    # result at this moment, so the posting was definitely open then.
    #
    # Not updated_at, which looks like it would do: SQLAlchemy's onupdate
    # only fires when some other field actually changes value, so a re-crawl
    # that finds nothing different leaves it untouched. Nothing reads
    # updated_at either.
    #
    # Used in ONE direction only. Being in a search result proves a posting
    # is open; being absent from one proves nothing, because the searches are
    # narrow (Istanbul, nine departments) and measured 21.08.2026 only 14 of
    # 36 stored kariyer.net postings appear in them on any given day.
    last_seen_at = Column(DateTime)

##############################
# CONNECTION TO THE DATABASE #
##############################
def normalize_db_url(db_url):
    """
    Accept the `postgres://` url that hosting panels hand out.

    Coolify (like Heroku and Render) shows the connection string as
    `postgres://user:pass@host:5432/db`. SQLAlchemy dropped that alias in 1.4
    and only answers to `postgresql://`, so pasting the panel's own value
    verbatim fails with

        NoSuchModuleError: Can't load plugin: sqlalchemy.dialects:postgres

    which reads like a missing driver rather than a one-word url problem. The
    scheme is the only difference, so rewrite it instead of asking every
    deployment to remember. `postgresql://` on its own already resolves to
    psycopg2, so no driver needs naming.
    """
    if db_url.startswith("postgres://"):
        return "postgresql://" + db_url[len("postgres://"):]
    return db_url


def db_connect():
    """
    DATABASE_URL is required, and deliberately has no fallback.

    The old default pointed at a `job_posts` database that does not exist,
    while app.py defaulted to `job_applications_db` with a hardcoded password.
    A misconfigured run therefore failed one item at a time inside the
    pipeline's exception handler rather than saying what was wrong. Failing
    here, immediately, is easier to diagnose.
    """
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise RuntimeError(
            "DATABASE_URL is not set. Put it in .env for local runs, or in the "
            "service's environment variables in Coolify. Format: "
            "postgresql://user:password@host:5432/dbname"
        )
    return create_engine(normalize_db_url(db_url))

# FUNCTION TO CREATE TABLE
def create_table(engine):
    Base.metadata.create_all(engine)