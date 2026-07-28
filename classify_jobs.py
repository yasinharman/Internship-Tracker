"""
CLASSIFY POSTINGS THAT HAVE NOT BEEN CLASSIFIED YET
===================================================

    python classify_jobs.py                     classify and WRITE to the database
    python classify_jobs.py --dry-run           classify and print, write nothing
    python classify_jobs.py --compare a b c     run several models, print only
                                                the postings they disagree on
    python classify_jobs.py --limit 20          only the first N rows

Only rows with `job_category IS NULL` are read, so re-running is free: a second
run finds nothing to do. That also means a bad batch can be redone by clearing
the column for those rows.

Postings judged `other` are NOT deleted - `is_active` is set to False and the
row stays, with the model's reason next to it. See docs/sites.md for what to do
when a decision looks wrong.
"""

import argparse
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from dotenv import load_dotenv
from sqlalchemy.orm import sessionmaker

from MultiwebsiteScraper.classifier import DEFAULT_MODELS, classify
from MultiwebsiteScraper.models import JobPost, db_connect

load_dotenv()

# Every reason the model writes is Turkish, and so are most of the titles.
# Python picks the console's encoding for stdout, which is cp1252 on a Turkish
# Windows install and cannot represent "İ" - so printing a verdict raised
# UnicodeEncodeError and killed the run after the work had already been paid
# for. errors="replace" rather than strict: a character that cannot be shown
# is worth a "?", not a crash.
for stream in (sys.stdout, sys.stderr):
    stream.reconfigure(encoding="utf-8", errors="replace")

# Each request is independent, and the wait is entirely network - so threads
# are the right tool and the number can be generous. 8 keeps 150 postings to
# well under a minute without tripping per-minute rate limits.
CONCURRENCY = int(os.getenv("CLASSIFY_CONCURRENCY", "8"))

CATEGORY_ORDER = ["it", "general_program", "other"]


#####################################################
# READ                                              #
#####################################################
def load_unclassified(session, limit=None):
    query = (
        session.query(JobPost)
        .filter(JobPost.job_category.is_(None))
        .order_by(JobPost.created_at.desc())
    )
    if limit:
        query = query.limit(limit)
    return query.all()


def snapshot(posting):
    """
    A detached copy of just the fields the classifier reads.

    The worker threads must not touch the ORM objects: a Session is not thread
    safe, and a lazy attribute load from a worker would emit a query on a
    connection another thread is using.
    """
    return {
        "id": posting.id,
        "job_title": posting.job_title,
        "company": posting.company,
        "location": posting.location,
        "job_description": posting.job_description,
    }


#####################################################
# CLASSIFY IN PARALLEL                              #
#####################################################
def classify_all(rows, provider, model):
    """
    Returns {row_id: JobCategory}. A posting whose call fails is left out
    rather than guessed at, and reported - it stays NULL and the next run
    picks it up again.
    """
    results = {}
    failures = []

    def work(row):
        try:
            return row["id"], classify(row, provider=provider, model=model)
        except Exception as error:
            return row["id"], error

    with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
        for row_id, outcome in pool.map(work, rows):
            if isinstance(outcome, Exception):
                failures.append((row_id, outcome))
            else:
                results[row_id] = outcome

    for row_id, error in failures:
        print(f"  !! id={row_id} classification failed: {error}", file=sys.stderr)
    if failures:
        print(
            f"  {len(failures)} posting(s) left unclassified - re-run to retry.",
            file=sys.stderr,
        )

    return results


#####################################################
# PRINTING                                          #
#####################################################
def print_grouped(rows, results):
    by_id = {row["id"]: row for row in rows}

    for category in CATEGORY_ORDER:
        matching = [
            (by_id[row_id], verdict)
            for row_id, verdict in results.items()
            if verdict.category == category
        ]
        print(f"\n{'=' * 70}\n{category.upper()}  ({len(matching)})\n{'=' * 70}")
        for row, verdict in sorted(matching, key=lambda pair: pair[0]["job_title"] or ""):
            print(f"  {row['job_title']}  [{row['company']}]")
            print(f"      {verdict.reason}")

    counts = ", ".join(
        f"{category}: {sum(1 for v in results.values() if v.category == category)}"
        for category in CATEGORY_ORDER
    )
    print(f"\n{'-' * 70}\n{len(results)} classified - {counts}")


def print_disagreements(rows, per_model):
    """
    per_model: {"model-name": {row_id: JobCategory}}

    Agreement is the boring case and there is a lot of it, so only the rows
    where the models split are printed - that is the whole point of the
    comparison, and reading 130 identical verdicts is not.
    """
    by_id = {row["id"]: row for row in rows}
    models = list(per_model)

    shared_ids = set.intersection(*(set(v) for v in per_model.values()))
    disagreed = [
        row_id for row_id in shared_ids
        if len({per_model[m][row_id].category for m in models}) > 1
    ]

    print(f"\n{'=' * 70}")
    print(f"DISAGREEMENTS: {len(disagreed)} of {len(shared_ids)} postings")
    print(f"{'=' * 70}")

    for row_id in sorted(disagreed, key=lambda i: by_id[i]["job_title"] or ""):
        row = by_id[row_id]
        print(f"\n  {row['job_title']}  [{row['company']}]")
        for model in models:
            verdict = per_model[model][row_id]
            print(f"      {model:<22} {verdict.category:<16} {verdict.reason}")

    print(f"\n{'-' * 70}")
    for model in models:
        counts = ", ".join(
            f"{c}: {sum(1 for v in per_model[model].values() if v.category == c)}"
            for c in CATEGORY_ORDER
        )
        print(f"  {model:<22} {counts}")


#####################################################
# WRITE                                             #
#####################################################
def write_results(session, results):
    # UTC, but written back as a naive value: classified_at is `timestamp
    # without time zone`, like created_at, and handing psycopg2 an aware
    # datetime for a naive column loses the offset silently. utcnow() would do
    # the same thing but is deprecated.
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    deactivated = 0

    for posting in session.query(JobPost).filter(JobPost.id.in_(results)).all():
        verdict = results[posting.id]

        posting.job_category = verdict.category
        posting.category_reason = verdict.reason
        posting.classified_at = now

        if verdict.category == "other":
            posting.is_active = False
            deactivated += 1
            # Logged at INFO on purpose: every exclusion is visible in the
            # Coolify logs, so a wrong one can be spotted without a query.
            print(f"  hidden: {posting.job_title} - {verdict.reason}")

    session.commit()
    return deactivated


#####################################################
# ENTRY POINT                                       #
#####################################################
def main():
    parser = argparse.ArgumentParser(
        description="Classify unclassified job postings with an LLM."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Classify and print the result, but write nothing.",
    )
    parser.add_argument(
        "--compare", nargs="+", metavar="MODEL",
        help="Run these models over the same postings and print only the "
             "postings they disagree on. Implies --dry-run.",
    )
    parser.add_argument(
        "--provider", choices=sorted(DEFAULT_MODELS),
        help="Override LLM_PROVIDER.",
    )
    parser.add_argument("--model", help="Override CLASSIFIER_MODEL.")
    parser.add_argument(
        "--limit", type=int,
        help="Only classify the first N unclassified postings.",
    )
    args = parser.parse_args()

    engine = db_connect()
    session = sessionmaker(bind=engine)()

    try:
        postings = load_unclassified(session, args.limit)
        if not postings:
            print("0 new rows - everything is already classified.")
            return

        rows = [snapshot(posting) for posting in postings]
        print(f"{len(rows)} unclassified posting(s).", flush=True)

        ###############################
        # COMPARE SEVERAL MODELS      #
        ###############################
        if args.compare:
            per_model = {}
            for model in args.compare:
                # A model name alone does not say who serves it. The provider
                # flag applies to all of them; mixing providers in one compare
                # run means two invocations.
                print(f"\n-> {model}", flush=True)
                per_model[model] = classify_all(rows, args.provider, model)
            print_disagreements(rows, per_model)
            return

        ###############################
        # ONE MODEL                   #
        ###############################
        results = classify_all(rows, args.provider, args.model)
        if not results:
            print("Nothing classified.")
            return

        if args.dry_run:
            print_grouped(rows, results)
            print("\n(dry run - nothing was written)")
            return

        deactivated = write_results(session, results)
        counts = ", ".join(
            f"{c}: {sum(1 for v in results.values() if v.category == c)}"
            for c in CATEGORY_ORDER
        )
        print(f"\n{len(results)} written - {counts}")
        print(f"{deactivated} posting(s) hidden from the dashboard.")

    finally:
        session.close()


if __name__ == "__main__":
    main()
