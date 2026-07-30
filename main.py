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
import tempfile
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

# indeed_cards was parked from 28.07.2026 to 30.07.2026. Un-parked on the
# terms the parking comment itself set: the server got the static PROXY_URL
# and the session, `python main.py --spider indeed_cards` was run there once,
# and it returned postings - 61 requests, 61 answered, 335 postings, four
# searches into the page ceiling with results still coming.
#
# Three things had to be true at once, and each was mistaken for the others
# at some point (docs/sites.md has the measurements):
#
#   - a TLS handshake Cloudflare accepts today, which changes without notice
#     and is why IMPERSONATE_CANDIDATES is a ladder rather than a value
#   - a residential exit address, static, so the account and the address stay
#     consistent - the datacenter address the server sits on is refused on
#     every handshake
#   - a signed-in session, carried under the handshake of the browser that
#     created it. The pairing is the part that took longest to see: the
#     tokens measured clean WITHOUT cookies were the ones being challenged
#     WITH them.
#
# If it starts failing, read the first three log lines before anything else.
# They say which handshake, which address and how many session cookies, and
# every wrong turn in those three days came from guessing one of them.
PARKED_SPIDERS = []

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
def _read_item_count(stats_path):
    """Item count the spider left behind, or None if it left nothing."""
    try:
        with open(stats_path, encoding="utf-8") as handle:
            line = handle.read().strip().splitlines()[-1]
        return int(line.split("\t")[1])
    except (OSError, IndexError, ValueError):
        return None
    finally:
        try:
            os.remove(stats_path)
        except OSError:
            pass


def run_spider(spider_name):
    """
    Returns (ok, item_count). item_count is None when the spider did not
    report one - a crash before close, or an older spider class.

    The count matters as much as the exit code: a blocked spider opens, gets
    refused on every request, closes cleanly and exits 0. See
    BaseApiSpider._report_item_count.
    """
    print(f"\n=== {spider_name}: starting ===", flush=True)
    started = time.monotonic()

    # `python -m scrapy` rather than the `scrapy` binary: works the same
    # whether or not the venv's bin directory is on PATH.
    command = [sys.executable, "-m", "scrapy", "crawl", spider_name]

    # Absolute: the subprocess runs with cwd=SCRAPY_PROJECT_FOLDER.
    stats_path = os.path.join(
        tempfile.gettempdir(), f"spider_stats_{os.getpid()}_{spider_name}"
    )
    env = {**os.environ, "SPIDER_STATS_FILE": stats_path}

    try:
        result = subprocess.run(
            command,
            cwd=SCRAPY_PROJECT_FOLDER,
            timeout=SPIDER_TIMEOUT,
            env=env,
        )
        exit_code = result.returncode

    except subprocess.TimeoutExpired:
        print(
            f"=== {spider_name}: KILLED after {SPIDER_TIMEOUT}s "
            f"(raise SPIDER_TIMEOUT if this is legitimate) ===",
            flush=True,
        )
        return False, _read_item_count(stats_path)

    except FileNotFoundError as error:
        print(f"=== {spider_name}: could not start - {error} ===", flush=True)
        return False, None

    elapsed = time.monotonic() - started
    items = _read_item_count(stats_path)
    found = "?" if items is None else items

    if exit_code == 0:
        print(
            f"=== {spider_name}: finished in {elapsed:.0f}s, {found} posting(s) ===",
            flush=True,
        )
        return True, items

    print(
        f"=== {spider_name}: FAILED (exit code {exit_code}) after {elapsed:.0f}s ===",
        flush=True,
    )
    return False, items


#########################################
# RUN THE WHOLE SET, REPORT WHAT HAPPENED #
#########################################
def run_spiders(spiders=None):
    """Returns the list of spider names that failed."""
    spiders = spiders or SPIDERS
    started = datetime.now()
    print(f"Crawl started at {started:%Y-%m-%d %H:%M:%S}", flush=True)

    # name -> (ok, item_count)
    results = {}

    for spider in spiders:
        results[spider] = run_spider(spider)

        # Only chase a follow-up if the spider that feeds it succeeded - a
        # follow-up reading stale hand-off data is worse than not running.
        if results[spider][0]:
            for follow_up in FOLLOW_UP_SPIDERS.get(spider, []):
                results[follow_up] = run_spider(follow_up)
        elif spider in FOLLOW_UP_SPIDERS:
            for follow_up in FOLLOW_UP_SPIDERS[spider]:
                print(
                    f"=== {follow_up}: skipped, {spider} failed ===", flush=True
                )
                results[follow_up] = (False, None)

    ###########
    # SUMMARY #
    ###########
    elapsed = (datetime.now() - started).total_seconds()
    failed = [name for name, (ok, _) in results.items() if not ok]
    # Exited cleanly and found nothing. Almost always a block: the spider is
    # refused on every request, logs it, closes tidily and returns 0.
    empty = [
        name for name, (ok, items) in results.items() if ok and items == 0
    ]

    print(f"\n{'-' * 52}")
    for name, (ok, items) in results.items():
        if not ok:
            status, note = "FAIL ", ""
        elif items == 0:
            status, note = "EMPTY", "   <- found nothing, check for blocks"
        else:
            status, note = "OK   ", ""
        found = "?" if items is None else items
        print(f"  {status}  {name:<22} {found:>4} posting(s){note}")

    print(
        f"{'-' * 52}\n"
        f"{len(results) - len(failed)}/{len(results)} spiders succeeded "
        f"in {elapsed:.0f}s",
        flush=True,
    )

    # Said plainly, and after the table, because this is the failure that
    # otherwise hides behind a green run: every spider exits 0 and the crawl
    # looks healthy while the database gets nothing.
    if empty:
        print(
            f"\n!! {len(empty)} spider(s) returned ZERO postings: "
            f"{', '.join(empty)}\n"
            f"!! They exited cleanly, so this is not a crash - look for 403s, "
            f"sign-in redirects or a changed page shape in the log above.",
            flush=True,
        )

    # A crawl where NOTHING came back is reported as a failed run, even though
    # every spider exited 0. One empty spider is ambiguous - a board really
    # can have no new postings today - but all of them empty means the crawl
    # accomplished nothing, and that should be a red run in Coolify rather
    # than a warning nobody opens the log to read.
    counted = [items for ok, items in results.values() if ok and items is not None]
    found_nothing = bool(counted) and sum(counted) == 0
    if found_nothing:
        print(
            "!! Every spider that ran found nothing - reporting this run as "
            "failed so it does not pass silently.",
            flush=True,
        )

    return failed, found_nothing


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
        # Shown so a parked spider is not silently forgotten - it stays
        # runnable with --spider, it just does not run on a schedule.
        for name in PARKED_SPIDERS:
            print(f"{name}  (parked - see the comment on SPIDERS)")
        sys.exit(0)

    if args.schedule:
        run_with_internal_scheduler()
        sys.exit(0)

    selected = args.spider
    if selected:
        # Parked spiders are runnable by name on purpose: retrying one by hand
        # is how you find out whether it is worth un-parking.
        runnable = (
            set(SPIDERS)
            | set(PARKED_SPIDERS)
            | {f for group in FOLLOW_UP_SPIDERS.values() for f in group}
        )
        unknown = [name for name in selected if name not in runnable]
        if unknown:
            parser.error(
                f"unknown spider(s): {', '.join(unknown)}. "
                f"Available: {', '.join(SPIDERS)}"
                + (f" (parked: {', '.join(PARKED_SPIDERS)})" if PARKED_SPIDERS else "")
            )

    failed_spiders, found_nothing = run_spiders(selected)

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
    # up as a red run instead of passing silently. Two ways to earn it: a
    # spider crashed, or every spider that ran came back empty - see
    # run_spiders for why the second one counts. Classification is not part of
    # this; see run_post_crawl.
    sys.exit(1 if (failed_spiders or found_nothing) else 0)
