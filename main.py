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
import json
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

# A handful of HTTP calls to Hermes, each with its own REQUEST_TIMEOUT
# (notify_watchlist.py) - this is the ceiling for the whole batch, not one
# call, in case a run has an unusually large number of watchlist matches.
NOTIFY_TIMEOUT = int(os.getenv("NOTIFY_TIMEOUT", "300"))


####################################
# RUN ONE SPIDER AS A SUBPROCESS   #
####################################

# Cosmetic only - used by _print_run_summary() to show a name a human
# recognises instead of the internal spider class name.
SITE_LABELS = {
    "kariyernet_cards": "kariyer.net",
    "techcareer_api": "techcareer.net",
    "indeed_cards": "Indeed",
}


def _read_spider_stats(stats_path):
    """
    The dict BaseApiSpider._report_item_count left behind, or None if it
    left nothing (a crash before close, or an older spider class).

    stats["items"] matters as much as the exit code: a blocked spider opens,
    gets refused on every request, closes cleanly and exits 0.
    """
    try:
        with open(stats_path, encoding="utf-8") as handle:
            line = handle.read().strip().splitlines()[-1]
        return json.loads(line)
    except (OSError, IndexError, ValueError):
        return None
    finally:
        try:
            os.remove(stats_path)
        except OSError:
            pass


def run_spider(spider_name):
    """
    Returns (ok, stats). stats is the dict from _read_spider_stats(), or
    None when the spider did not report one.
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
        return False, _read_spider_stats(stats_path)

    except FileNotFoundError as error:
        print(f"=== {spider_name}: could not start - {error} ===", flush=True)
        return False, None

    elapsed = time.monotonic() - started
    stats = _read_spider_stats(stats_path)
    items = stats["items"] if stats else None
    found = "?" if items is None else items

    if exit_code == 0:
        print(
            f"=== {spider_name}: finished in {elapsed:.0f}s, {found} posting(s) ===",
            flush=True,
        )
        return True, stats

    print(
        f"=== {spider_name}: FAILED (exit code {exit_code}) after {elapsed:.0f}s ===",
        flush=True,
    )
    return False, stats


####################################################
# THE HUMAN-READABLE VERSION OF WHAT JUST HAPPENED #
####################################################
def _print_run_summary(results):
    """
    One plain-language block per site: requests made, searches run and what
    each found, postings kept, and whether a block cut the run short.

    Meant to be read once a day without opening the scrapy log above it -
    the log is for debugging, this is for "did today's run work".
    """
    print(f"\n{'=' * 60}")
    print("CALISTIRMA OZETI")
    print(f"{'=' * 60}")

    total_items = 0
    for name, (ok, stats) in results.items():
        label = SITE_LABELS.get(name, name)
        print(f"\n{label} ({name})")

        if not ok and not stats:
            print("  Calismadi - crash veya baslamadan hata. Log'a bak.")
            continue

        items = stats.get("items", 0) if stats else 0
        requests = stats.get("requests") if stats else None
        total_items += items

        request_bit = f"{requests} istek atildi" if requests is not None else "istek sayisi bilinmiyor"
        print(f"  {request_bit} -> {items} ilan bulundu")

        responses = (stats or {}).get("responses") or {}
        if responses:
            parts = [f"{code}: {count}" for code, count in sorted(responses.items())]
            print(f"  Yanitlar: {', '.join(parts)}")

        routes = (stats or {}).get("routes") or {}
        if routes:
            parts = [f'"{route}" ({count} ilan)' for route, count in routes.items()]
            print(f"  Aramalar: {' | '.join(parts)}")

        if (stats or {}).get("blocked"):
            print(
                "  Not: Site bir noktada engelledi (Cloudflare/PerimeterX vb.) "
                "- kod kendi guvenlik butcesiyle temiz sekilde durdu, o ana "
                "kadar bulunanlar korundu."
            )

        if not ok:
            print("  UYARI: bu site FAILED olarak isaretlendi, log'daki hataya bak.")

    succeeded = sum(1 for ok, _ in results.values() if ok)
    print(f"\n{'-' * 60}")
    print(f"TOPLAM: {total_items} ilan | {succeeded}/{len(results)} site basarili")
    print(f"{'-' * 60}")


#########################################
# RUN THE WHOLE SET, REPORT WHAT HAPPENED #
#########################################
def run_spiders(spiders=None):
    """Returns the list of spider names that failed."""
    spiders = spiders or SPIDERS
    started = datetime.now()
    print(f"Crawl started at {started:%Y-%m-%d %H:%M:%S}", flush=True)

    # name -> (ok, stats). stats is the dict from _read_spider_stats(), see
    # BaseApiSpider._report_item_count for its shape.
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

    def _items(stats):
        return stats["items"] if stats else None

    # Exited cleanly and found nothing. Almost always a block: the spider is
    # refused on every request, logs it, closes tidily and returns 0.
    empty = [
        name for name, (ok, stats) in results.items() if ok and _items(stats) == 0
    ]

    _print_run_summary(results)
    print(f"({elapsed:.0f}s toplam)", flush=True)

    # Said plainly, and after the summary, because this is the failure that
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
    counted = [
        _items(stats) for ok, stats in results.values()
        if ok and _items(stats) is not None
    ]
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
    verdicts. Notifying Hermes about watchlist companies also happens after
    dedupe and for the same reason: the duplicate copy of a watched posting
    should not ping Telegram a second time.

    Notifying does not need classify's verdict - the watchlist match is on
    company name alone - so it runs before classify rather than after,
    trading a slightly earlier Telegram ping for nothing classify would have
    added.

    None of dedupe, notify or classify failing stops the others. A job listed
    twice, a missed Telegram ping, or an unsorted posting are each worth far
    less than leaving everything the crawl just found untouched.
    """
    deduped = run_step("dedupe", "dedupe_jobs.py", DEDUPE_TIMEOUT)
    notified = run_step("notify", "notify_watchlist.py", NOTIFY_TIMEOUT)
    classified = run_step("classify", "classify_jobs.py", CLASSIFY_TIMEOUT)
    return deduped and notified and classified


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
