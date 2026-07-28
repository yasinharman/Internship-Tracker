"""
SCRAPER ENTRY POINT
===================

Runs every spider once and exits. The schedule lives OUTSIDE this script:
the container starts idle (`sleep infinity`, see Dockerfile) and Coolify's
scheduled task runs

    python main.py

inside the already-running container on its own cron expression.

Exiting when the work is done is the whole point - a scheduled task that never
returns would be reported as still running and the next tick would pile a
second crawl on top of the first.

    python main.py                          all spiders, then classify
    python main.py --spider indeed_cards    one spider (schedule sites separately)
    python main.py --skip-classify          crawl only, skip dedupe + classify
    python main.py --list                   show the spider names
    python main.py --schedule               legacy in-process APScheduler loop,
                                            for running without Coolify
"""

import argparse
import os
import subprocess
import sys
import time
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

SCRAPY_PROJECT_FOLDER = "MultiwebsiteScraper"

# Two sites are deliberately absent, and their spiders have been deleted.
# See docs/sites.md for the full reasoning; the code is in git history.
#
#   linkedin  Its JSON API (Voyager) only answers authenticated requests, and
#             pointing the bot at a personal account risks a permanent ban for
#             very little extra coverage. Checked by hand instead.
#
#   jooble    An aggregator: its postings are collected from kariyer.net and
#             the like, so they arrive as duplicates under a jooble url - a
#             second row for a job we already have. It is also behind a
#             Cloudflare challenge, so it would cost metered residential
#             bandwidth to re-fetch what we already hold. Dropping it also
#             removes the urller.jsonl handoff to detail_worker, which was the
#             most fragile piece of the pipeline.

# Their DOM-parsing predecessors (kariyerNet, TechCareer, indeed_html) have
# been deleted - see docs/sites.md for what each site actually turned out to
# need, and git history for the old code.
SPIDERS = ["kariyernet_cards", "techcareer_api", "indeed_cards"]

# spider -> spiders that must run straight after it. Empty: the only user was
# jooble, which handed urls to detail_worker through a file. Both are gone.
FOLLOW_UP_SPIDERS = {}

# A wedged spider must not hold the scheduled task open forever.
SPIDER_TIMEOUT = int(os.getenv("SPIDER_TIMEOUT", "1800"))

# 150 postings at 8 concurrent requests finish in well under a minute; this is
# a ceiling for a hung provider, not an expected duration.
CLASSIFY_TIMEOUT = int(os.getenv("CLASSIFY_TIMEOUT", "900"))

# Pure SQL over a few hundred rows - a second is generous.
DEDUPE_TIMEOUT = int(os.getenv("DEDUPE_TIMEOUT", "120"))


####################################
# RUN ONE SPIDER AS A SUBPROCESS   #
####################################
def run_spider(spider_name):
    """Returns True when the spider exited cleanly."""
    print(f"\n=== {spider_name}: starting ===", flush=True)
    started = time.monotonic()

    # `python -m scrapy` rather than the `scrapy` binary: works the same
    # whether or not the venv's bin directory is on PATH.
    command = [sys.executable, "-m", "scrapy", "crawl", spider_name]

    try:
        result = subprocess.run(
            command,
            cwd=SCRAPY_PROJECT_FOLDER,
            timeout=SPIDER_TIMEOUT,
        )
        exit_code = result.returncode

    except subprocess.TimeoutExpired:
        print(
            f"=== {spider_name}: KILLED after {SPIDER_TIMEOUT}s "
            f"(raise SPIDER_TIMEOUT if this is legitimate) ===",
            flush=True,
        )
        return False

    except FileNotFoundError as error:
        print(f"=== {spider_name}: could not start - {error} ===", flush=True)
        return False

    elapsed = time.monotonic() - started

    if exit_code == 0:
        print(f"=== {spider_name}: finished in {elapsed:.0f}s ===", flush=True)
        return True

    print(
        f"=== {spider_name}: FAILED (exit code {exit_code}) after {elapsed:.0f}s ===",
        flush=True,
    )
    return False


#########################################
# RUN THE WHOLE SET, REPORT WHAT HAPPENED #
#########################################
def run_spiders(spiders=None):
    """Returns the list of spider names that failed."""
    spiders = spiders or SPIDERS
    started = datetime.now()
    print(f"Crawl started at {started:%Y-%m-%d %H:%M:%S}", flush=True)

    results = {}

    for spider in spiders:
        results[spider] = run_spider(spider)

        # Only chase a follow-up if the spider that feeds it succeeded - a
        # follow-up reading stale hand-off data is worse than not running.
        if results[spider]:
            for follow_up in FOLLOW_UP_SPIDERS.get(spider, []):
                results[follow_up] = run_spider(follow_up)
        elif spider in FOLLOW_UP_SPIDERS:
            for follow_up in FOLLOW_UP_SPIDERS[spider]:
                print(
                    f"=== {follow_up}: skipped, {spider} failed ===", flush=True
                )
                results[follow_up] = False

    ###########
    # SUMMARY #
    ###########
    elapsed = (datetime.now() - started).total_seconds()
    failed = [name for name, ok in results.items() if not ok]

    print(f"\n{'-' * 46}")
    for name, ok in results.items():
        print(f"  {'OK  ' if ok else 'FAIL'}  {name}")
    print(
        f"{'-' * 46}\n"
        f"{len(results) - len(failed)}/{len(results)} spiders succeeded "
        f"in {elapsed:.0f}s",
        flush=True,
    )

    return failed


############################################
# CLASSIFY WHAT THE CRAWL JUST BROUGHT IN  #
############################################
def run_step(label, script, timeout):
    """
    Run one post-crawl script. Returns True when it exited cleanly.

    Deliberately NOT part of the crawl's pass/fail: by the time these run the
    postings are already stored. A failure here leaves them unsorted, which
    the dashboard shows anyway - a degraded run, not a lost one, and marking
    the whole scheduled task red would cry wolf.
    """
    print(f"\n=== {label}: starting ===", flush=True)
    started = time.monotonic()

    try:
        result = subprocess.run([sys.executable, script], timeout=timeout)
        exit_code = result.returncode
    except subprocess.TimeoutExpired:
        print(f"=== {label}: KILLED after {timeout}s ===", flush=True)
        return False
    except FileNotFoundError as error:
        print(f"=== {label}: could not start - {error} ===", flush=True)
        return False

    elapsed = time.monotonic() - started

    if exit_code == 0:
        print(f"=== {label}: finished in {elapsed:.0f}s ===", flush=True)
        return True

    print(
        f"=== {label}: FAILED (exit code {exit_code}) after {elapsed:.0f}s ===",
        flush=True,
    )
    return False


def run_post_crawl():
    """
    Everything that happens after the postings are in the database.

    Order matters: linking duplicates BEFORE classifying means the copy of a
    job already advertised on another board is never sent to the LLM - one
    fewer call, and no chance of the two copies coming back with different
    verdicts.

    Dedupe failing does not stop classification. The consequence is a job
    listed twice for a day, which is worth far less than leaving everything
    the crawl just found unsorted.
    """
    deduped = run_step("dedupe", "dedupe_jobs.py", DEDUPE_TIMEOUT)
    classified = run_step("classify", "classify_jobs.py", CLASSIFY_TIMEOUT)
    return deduped and classified


############################################
# LEGACY: SCHEDULE INSIDE THE PROCESS      #
############################################
def run_with_internal_scheduler():
    """
    Pre-Coolify behaviour: this process stays alive and fires the crawl itself.
    Kept for running the stack without an external scheduler (docker-compose
    locally). Do NOT use this for a Coolify scheduled task - it never exits.
    """
    from apscheduler.schedulers.blocking import BlockingScheduler

    scheduler = BlockingScheduler()
    scheduler.add_job(run_spiders, "cron", day="*/2", hour=3, minute=0)

    print("Internal scheduler ready (every 2 days at 03:00).", flush=True)
    run_spiders()

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        print("Scheduler stopped.", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run the job-board spiders once and exit."
    )
    parser.add_argument(
        "--spider",
        action="append",
        metavar="NAME",
        help="Run only this spider. Repeatable. Default: all of them.",
    )
    parser.add_argument(
        "--list", action="store_true", help="Print the spider names and exit."
    )
    parser.add_argument(
        "--schedule",
        action="store_true",
        help="Stay alive and schedule the crawl in-process (legacy).",
    )
    parser.add_argument(
        "--skip-classify",
        action="store_true",
        help="Crawl only - skip both the dedupe and the classify step. New "
             "postings stay unsorted and remain visible on the dashboard "
             "until a later run picks them up.",
    )
    args = parser.parse_args()

    if args.list:
        for name in SPIDERS:
            follow_ups = FOLLOW_UP_SPIDERS.get(name)
            suffix = f"  (then: {', '.join(follow_ups)})" if follow_ups else ""
            print(f"{name}{suffix}")
        sys.exit(0)

    if args.schedule:
        run_with_internal_scheduler()
        sys.exit(0)

    selected = args.spider
    if selected:
        unknown = [
            name for name in selected
            if name not in SPIDERS
            and name not in {f for group in FOLLOW_UP_SPIDERS.values() for f in group}
        ]
        if unknown:
            parser.error(
                f"unknown spider(s): {', '.join(unknown)}. "
                f"Available: {', '.join(SPIDERS)}"
            )

    failed_spiders = run_spiders(selected)

    # Classify whatever the crawl added. Runs even when a spider failed: the
    # other spiders' postings are in the database and deserve to be sorted.
    if not args.skip_classify:
        if not run_post_crawl():
            print(
                "  (post-crawl step did not finish - postings are stored and "
                "visible, just unsorted)",
                flush=True,
            )

    # Non-zero tells Coolify the scheduled task failed, so a broken crawl shows
    # up as a red run instead of passing silently. Only the spiders decide this
    # - see run_classifier for why a failed classification does not.
    sys.exit(1 if failed_spiders else 0)
