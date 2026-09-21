"""
CLASSIFY POSTINGS THAT HAVE NOT BEEN CLASSIFIED YET
===================================================

    python -m pipeline.classify_jobs                     classify and WRITE to the database
    python -m pipeline.classify_jobs --dry-run           classify and print, write nothing
    python -m pipeline.classify_jobs --compare a b c     run several models,
                                                        print only the postings
                                                        they disagree on
    python -m pipeline.classify_jobs --limit 20          only the first N rows

Only rows with `job_category IS NULL` are read, so re-running is free: a second
run finds nothing to do. That also means a bad batch can be redone by clearing
the column for those rows.

Postings judged `other` are NOT deleted - `is_active` is set to False and the
row stays, with the model's reason next to it. See docs/pipeline.md for what to do
when a decision looks wrong.
"""

import argparse
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from dotenv import load_dotenv
from sqlalchemy import func, or_
from sqlalchemy.orm import sessionmaker

from scraper.classifier import classify
from scraper.models import JobPost, db_connect

load_dotenv()

# Every reason the model writes is Turkish, and so are most of the titles.
# Python picks the console's encoding for stdout, which is cp1252 on a Turkish
# Windows install and cannot represent "İ" - so printing a verdict raised
# UnicodeEncodeError and killed the run after the work had already been paid
# for. errors="replace" rather than strict: a character that cannot be shown
# is worth a "?", not a crash.
for stream in (sys.stdout, sys.stderr):
    stream.reconfigure(encoding="utf-8", errors="replace")

# Each request is independent. Ollama answers one at a time and queues the
# rest, so this number changes how long a request waits, not how long the run
# takes: 8 and 1 both sorted 70 postings in 91 s (docs/pipeline.md,
# 21.09.2026). Kept at 8 because it costs nothing and the longest wait,
# 12 s, is far inside the SDK's own 600 s timeout.
CONCURRENCY = int(os.getenv("CLASSIFY_CONCURRENCY", "8"))

CATEGORY_ORDER = ["it", "general_program", "other"]

#####################################################
# READ                                              #
#####################################################
# What "no description" looks like in the column. The spiders write the
# literal "N/A" when they have nothing (BaseApiSpider.DEFAULT_VALUE) - and
# since 21.09.2026 every cards spider sends it for every card, because no
# crawl opens a posting page any more; the *_check spiders are the only
# writers of a description. NULL and "" are older rows, and NULL is filtered
# on its own below.
NO_DESCRIPTION = ("N/A", "")


def load_unclassified(session, limit=None):
    # Duplicates are skipped rather than classified: the same job on another
    # board would cost a second call and could come back with a different
    # verdict, which is worse than not knowing - the row is hidden anyway.
    query = (
        session.query(JobPost)
        .filter(JobPost.job_category.is_(None))
        .filter(JobPost.duplicate_of.is_(None))
        # Closed postings are skipped for the same kind of reason: the checks
        # now run BEFORE this step (see main.py run_post_crawl), so a posting
        # they just found gone from its source site would otherwise be paid
        # for here and then hidden behind the "Kapananlar" toggle anyway.
        #
        # The consequence is worth stating rather than discovering: a posting
        # that closed before it was ever classified stays NULL forever, and
        # since 16.09.2026 the dashboard does not show it even with that
        # toggle on (api/queries.py, CLASSIFIED). That is the price of not
        # spending on a dead posting, and it is recoverable - the row is still
        # there and one UPDATE puts it back in the queue.
        .filter(JobPost.closed_at.is_(None))
        ###############################################################
        # AND A ROW WITH NOTHING TO READ WAITS - ADDED 12.09.2026     #
        ###############################################################
        # A description is the input this step was reorganised around. The
        # checks were moved ahead of classify on 09.09.2026 precisely so the
        # model would read the posting instead of guessing from its title,
        # and 32 of 993 rows carried a real description when that decision
        # was measured.
        #
        # What was still missing is the other half of it: a row that has no
        # description YET was classified anyway, from the title, and
        # job_category is only ever written once - so the guess became
        # permanent and the description that arrived the next night changed
        # nothing. On kariyer.net's first night that was roughly 16 of 40
        # postings, because its posting pages are refused past a certain
        # count and the card is stored on its own
        # (kariyernet_cards.parse_listing).
        #
        # So the row waits, unsorted, until there is something to sort it by.
        # A day's delay for a decision made on the real text is the trade, and
        # it was the owner's call on 12.09.2026.
        #
        # WHILE IT WAITS IT IS HIDDEN, since 16.09.2026. It was shown until
        # then; the owner reversed that when Indeed's first full run left 245
        # of 296 postings waiting (api/queries.py, CLASSIFIED).
        #
        # THE RISK, stated rather than discovered: a posting whose
        # description never arrives is never classified, and so never shown.
        # report_waiting below counts it out loud every run, and the dashboard
        # shows the same count, so that a growing pile is noticed rather than
        # accumulating in silence.
        .filter(JobPost.job_description.isnot(None))
        .filter(JobPost.job_description.notin_(NO_DESCRIPTION))
        .order_by(JobPost.created_at.desc())
    )
    if limit:
        query = query.limit(limit)
    return query.all()


def report_waiting(session):
    """
    How many rows are sorted-able but for a missing description, per site.

    Printed every run. A handful is the normal overnight lag; the same number
    growing week on week means a site has stopped giving up its descriptions
    and the postings are piling up unsorted rather than being classified
    badly, which is the failure this is designed to have.
    """
    rows = (
        session.query(JobPost.source_site, func.count(JobPost.id))
        .filter(JobPost.job_category.is_(None))
        .filter(JobPost.duplicate_of.is_(None))
        .filter(JobPost.closed_at.is_(None))
        .filter(
            or_(
                JobPost.job_description.is_(None),
                JobPost.job_description.in_(NO_DESCRIPTION),
            )
        )
        .group_by(JobPost.source_site)
        .all()
    )
    if not rows:
        return

    total = sum(count for _, count in rows)
    print(
        f"{total} posting(s) waiting for a description before being "
        f"classified - off the dashboard until they are:"
    )
    for site, count in sorted(rows, key=lambda r: -r[1]):
        print(f"    {count:>4}  {site}")


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
def classify_all(rows, model):
    """
    Returns {row_id: JobCategory}. A posting whose call fails is left out
    rather than guessed at, and reported - it stays NULL and the next run
    picks it up again.
    """
    results = {}
    failures = []

    def work(row):
        try:
            return row["id"], classify(row, model=model)
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
            # run's own output, so a wrong one can be spotted without a query.
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
    parser.add_argument("--model", help="Override CLASSIFIER_MODEL.")
    parser.add_argument(
        "--limit", type=int,
        help="Only classify the first N unclassified postings.",
    )
    args = parser.parse_args()

    engine = db_connect()
    session = sessionmaker(bind=engine)()

    try:
        # Before anything else, because it is the line that explains a
        # smaller-than-expected batch - and it prints whether or not there
        # is anything to classify.
        report_waiting(session)

        postings = load_unclassified(session, args.limit)
        if not postings:
            print("0 new rows - everything is already classified, or waiting "
                  "for a description.")
            return

        rows = [snapshot(posting) for posting in postings]
        print(f"{len(rows)} unclassified posting(s).", flush=True)

        ###############################################################
        # LET GO OF THE DATABASE WHILE THE MODEL WORKS - 21.09.2026   #
        ###############################################################
        # The first full run on the local model sorted 314 postings in
        # about 400 s, then lost every verdict: the write found its
        # connection gone ("server closed the connection unexpectedly").
        # That connection had sat idle, holding the read transaction, for
        # the whole run. Postgres itself times out nothing (its idle
        # timeouts are all 0), so the drop is somewhere on the way to the
        # server. Measured the same day, one connection per case, side by
        # side: idle 200 s survived, idle 330 s and 420 s were dropped with
        # the very same error, and 420 s with a TCP keepalive every 60 s
        # survived. With the API a batch took under a minute, so this never
        # showed.
        #
        # The rows are already plain dicts (snapshot), so nothing needs the
        # session until the write. Closing it ends the read transaction;
        # dispose() drops the pooled connection, so the write opens a fresh
        # one - the same thing scraper/openings.py does for every batch of
        # verdicts, which is why the 87-minute Indeed check never hit it.
        session.close()
        engine.dispose()

        ###############################
        # COMPARE SEVERAL MODELS      #
        ###############################
        if args.compare:
            per_model = {}
            for model in args.compare:
                # Every model is served by the same local server, and each
                # must have been pulled. Only one fits in VRAM at a time, so
                # Ollama swaps them - the first posting of each model waits
                # for the load.
                print(f"\n-> {model}", flush=True)
                per_model[model] = classify_all(rows, model)
            print_disagreements(rows, per_model)
            return

        ###############################
        # ONE MODEL                   #
        ###############################
        results = classify_all(rows, args.model)
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
