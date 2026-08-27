"""
PING HERMES/TELEGRAM WHEN A WATCHED COMPANY POSTS A JOB
========================================================

    python -m pipeline.notify_watchlist             notify and WRITE notified_at
    python -m pipeline.notify_watchlist --dry-run   print what would be sent

Company names to watch live in config/watched_companies.yml, not here - see that
file for the matching rule (case-insensitive substring) and why editing it
does not retroactively notify about postings already in the database.

Only rows with `notified_at IS NULL` are read, so re-running is free.
notified_at is stamped on every row this script finishes with an opinion
about - a non-matching posting gets it immediately (nothing to send, nothing
to retry), a matching one only once Hermes has accepted it. A posting that
matched but whose delivery failed is left NULL on purpose, so the next run
retries just that send instead of rescanning the whole table's non-matches
every time.

Duplicates are skipped like pipeline/classify_jobs.py skips them: the same job on a
second board would ping Telegram twice for one real opening.
"""

import argparse
import hashlib
import hmac
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
import yaml
from dotenv import load_dotenv
from sqlalchemy.orm import sessionmaker

from scraper.models import JobPost, db_connect
from scraper.pipelines import canonical_forms

load_dotenv()

for stream in (sys.stdout, sys.stderr):
    stream.reconfigure(encoding="utf-8", errors="replace")

# Two levels up, because this file moved into pipeline/ on 27.08.2026 and the
# list moved to config/ at the same time. Worth spelling out: load_watchlist()
# returns [] for a path that does not exist rather than raising, so a wrong
# path here does not crash - it prints "nothing to match against", exits 0 and
# quietly notifies nobody. Anything that moves this file must re-check it.
WATCHLIST_FILE = Path(__file__).resolve().parent.parent / "config" / "watched_companies.yml"

# Per-call ceiling so one unreachable Hermes gateway does not stall the rest
# of the batch - NOTIFY_TIMEOUT (main.py) is the ceiling for the whole
# script, this is the ceiling for a single POST.
REQUEST_TIMEOUT = int(os.getenv("NOTIFY_REQUEST_TIMEOUT", "10"))


#####################################################
# WATCHLIST                                         #
#####################################################
def load_watchlist():
    if not WATCHLIST_FILE.exists():
        return []
    with open(WATCHLIST_FILE, encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    return [name for name in (data.get("companies") or []) if name]


def matches_watchlist(company, watchlist):
    """
    canonical_forms(), not str.lower(): plain Python lowercasing gets Turkish
    wrong ("İş Bankası".lower() == "i̇ş bankası" - a combining-dot artifact
    that matches nothing), the same bug pipelines.py's job-type matching
    already had to work around. Checking every (company form x name form)
    pair costs nothing at this row count and survives a source site that
    writes the company in ALL CAPS.
    """
    company_forms = canonical_forms(company or "")
    for name in watchlist:
        name_forms = canonical_forms(name)
        if any(nf in cf for cf in company_forms for nf in name_forms):
            return name
    return None


#####################################################
# READ                                              #
#####################################################
def load_unnotified(session):
    return (
        session.query(JobPost)
        .filter(JobPost.notified_at.is_(None))
        .filter(JobPost.duplicate_of.is_(None))
        .order_by(JobPost.created_at.desc())
        .all()
    )


#####################################################
# HERMES WEBHOOK DELIVERY                           #
#####################################################
def send_to_hermes(url, secret, payload):
    """
    Returns True on a 2xx response. Signs with the V2 scheme the webhook
    adapter requires: HMAC-SHA256 of "<unix-timestamp>.<raw body>", so the
    exact bytes signed must be the exact bytes sent - json.dumps once,
    reused for both.
    """
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    timestamp = str(int(time.time()))
    signature = hmac.new(
        secret.encode("utf-8"), timestamp.encode() + b"." + body, hashlib.sha256
    ).hexdigest()

    response = requests.post(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-Webhook-Timestamp": timestamp,
            "X-Webhook-Signature-V2": signature,
        },
        timeout=REQUEST_TIMEOUT,
    )
    if response.status_code // 100 != 2:
        print(
            f"  !! Hermes returned {response.status_code}: {response.text[:200]}",
            file=sys.stderr,
        )
        return False
    return True


#####################################################
# ENTRY POINT                                       #
#####################################################
def main():
    parser = argparse.ArgumentParser(
        description="Notify Hermes/Telegram about new postings from watched companies."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would be sent, but call Hermes and write nothing.",
    )
    args = parser.parse_args()

    watchlist = load_watchlist()
    if not watchlist:
        print("config/watched_companies.yml is empty or missing - nothing to match against.")
        return

    url = os.getenv("HERMES_WEBHOOK_URL")
    secret = os.getenv("HERMES_WEBHOOK_SECRET")
    if not args.dry_run and not (url and secret):
        print(
            "HERMES_WEBHOOK_URL / HERMES_WEBHOOK_SECRET not set - see .env.example.",
            file=sys.stderr,
        )
        sys.exit(1)

    session = sessionmaker(bind=db_connect())()

    try:
        postings = load_unnotified(session)
        if not postings:
            print("0 new rows - nothing to check.")
            return
        print(f"{len(postings)} posting(s) to check against {len(watchlist)} watched compan(y/ies).")

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        notified, failed = 0, 0

        for posting in postings:
            matched_name = matches_watchlist(posting.company, watchlist)
            if not matched_name:
                if not args.dry_run:
                    posting.notified_at = now
                continue

            payload = {
                "company": posting.company,
                "job_title": posting.job_title,
                "url": posting.url,
                "source_site": posting.source_site,
            }

            if args.dry_run:
                print(f"  would notify: [{matched_name}] {posting.job_title} - {posting.url}")
                continue

            if send_to_hermes(url, secret, payload):
                posting.notified_at = now
                notified += 1
                print(f"  notified: [{matched_name}] {posting.job_title}")
            else:
                failed += 1
                print(
                    f"  !! id={posting.id} delivery failed, left unnotified for retry: "
                    f"{posting.job_title}",
                    file=sys.stderr,
                )

        if not args.dry_run:
            session.commit()
            print(f"\n{notified} notified, {failed} failed (will retry next run).")
        else:
            print("\n(dry run - nothing was written, nothing was sent)")

    finally:
        session.close()


if __name__ == "__main__":
    main()
