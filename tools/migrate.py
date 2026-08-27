"""
SCHEMA MIGRATIONS
=================

    python -m tools.migrate

Why this file exists at all: `Base.metadata.create_all()` only ever CREATES
missing tables. It looks at a table that already exists, sees the name, and
moves on - it will not add a column. So every column added to models.py after
the table was first created needs an explicit ALTER, or the code writes to a
column the database does not have and every insert fails at once.

No Alembic. It brings a versions directory, an env.py and a revision graph,
and this project has one migration. `ADD COLUMN IF NOT EXISTS` is idempotent
on its own, so re-running this is free and safe - which is what a migration
tool would have bought us.

Adding a column later: append it to MIGRATIONS and leave the old entries
alone. The list is the history.
"""

import sys

from dotenv import load_dotenv
from sqlalchemy import text

from scraper.models import db_connect

load_dotenv()

# Postgres only - IF NOT EXISTS on ADD COLUMN is 9.6+. Statements run in
# order, each one on its own, so a failure halfway leaves the earlier ones
# applied and re-running finishes the job.
MIGRATIONS = [
    (
        "job_posts.job_category",
        "ALTER TABLE job_posts ADD COLUMN IF NOT EXISTS job_category VARCHAR(32)",
    ),
    (
        "job_posts.category_reason",
        "ALTER TABLE job_posts ADD COLUMN IF NOT EXISTS category_reason TEXT",
    ),
    (
        "job_posts.classified_at",
        "ALTER TABLE job_posts ADD COLUMN IF NOT EXISTS classified_at TIMESTAMP",
    ),
    # pipeline/classify_jobs.py selects `WHERE job_category IS NULL` on every run, and
    # main.py runs it after every crawl. Cheap to have, and it keeps that scan
    # from walking the whole table as it grows.
    (
        "index on job_posts.job_category",
        "CREATE INDEX IF NOT EXISTS ix_job_posts_job_category "
        "ON job_posts (job_category)",
    ),
    # The same opening advertised on two boards. See models.JobPost.
    (
        "job_posts.duplicate_of",
        "ALTER TABLE job_posts ADD COLUMN IF NOT EXISTS duplicate_of INTEGER "
        "REFERENCES job_posts (id)",
    ),
    (
        "index on job_posts.duplicate_of",
        "CREATE INDEX IF NOT EXISTS ix_job_posts_duplicate_of "
        "ON job_posts (duplicate_of)",
    ),
    # pipeline/notify_watchlist.py selects `WHERE notified_at IS NULL` on every run.
    # See models.JobPost.
    (
        "job_posts.notified_at",
        "ALTER TABLE job_posts ADD COLUMN IF NOT EXISTS notified_at TIMESTAMP",
    ),
    # Whether the posting is still on offer, decided by the *_check spiders.
    # NOT folded into is_active: that column has two writers already
    # (classify_jobs sets it False, pipelines sets it back True on every
    # re-crawl) and a third would have them resurrecting each other's rows.
    # See models.JobPost.
    (
        "job_posts.closed_at",
        "ALTER TABLE job_posts ADD COLUMN IF NOT EXISTS closed_at TIMESTAMP",
    ),
    (
        "job_posts.checked_at",
        "ALTER TABLE job_posts ADD COLUMN IF NOT EXISTS checked_at TIMESTAMP",
    ),
    (
        "job_posts.last_seen_at",
        "ALTER TABLE job_posts ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMP",
    ),
    # Every dashboard query now carries `closed_at IS NULL`, and the check
    # spiders select on it too. Same reasoning as the two indexes above.
    (
        "index on job_posts.closed_at",
        "CREATE INDEX IF NOT EXISTS ix_job_posts_closed_at "
        "ON job_posts (closed_at)",
    ),
]


def main():
    engine = db_connect()

    with engine.begin() as connection:
        for label, statement in MIGRATIONS:
            connection.execute(text(statement))
            print(f"  ok  {label}", flush=True)

    print(f"\n{len(MIGRATIONS)} migration(s) applied.", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Migration failed: {error}", file=sys.stderr)
        sys.exit(1)
