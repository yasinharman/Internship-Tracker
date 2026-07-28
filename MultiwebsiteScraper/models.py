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
    # Filled in by classify_jobs.py after the crawl. NULL means "not looked
    # at yet", which the dashboard treats as visible - an outage of the LLM
    # API must not empty the board.
    #
    # 'other' postings are not deleted; is_active is set to False instead, so
    # a wrong call can be undone with one UPDATE. reason is kept so that the
    # decision can be read back and argued with.
    job_category = Column(String(32))    # 'it' | 'general_program' | 'other'
    category_reason = Column(Text)
    classified_at = Column(DateTime)

##############################
# CONNECTION TO THE DATABASE #
##############################
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
            "postgresql+psycopg2://user:password@host:5432/dbname"
        )
    return create_engine(db_url)

# FUNCTION TO CREATE TABLE
def create_table(engine):
    Base.metadata.create_all(engine)