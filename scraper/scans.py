"""
COUNTING RUNS, NOT DAYS
=======================

A posting that turned up in today's search results is open - that is free
evidence and no request has to be spent on it. The reverse is not evidence at
all: absence can mean the posting closed, or that the site stopped showing it,
or that we never finished looking.

Harman's rule, 03.10.2026: a posting that has everything stored is opened again
only after it has been missing from **three complete scans** of its site. Not
three days, three *runs* - and that distinction is the reason this module
exists. On 03.10.2026 nothing had run for ten days; a rule written in days
would have called every posting "missed three runs" and spent 400 requests on
the next run, while a rule written in runs correctly says nothing happened.

WHAT MAKES A SCAN COMPLETE
--------------------------
His definition, 04.10.2026: **every search reached its own end**. "Her arama
kendi sonuna ulaştıysa tam sayılır, aradaki bir sayfanın düşmesi tamlığı
bozmaz." A search sees its end when the site runs out of results, starts
repeating itself, or the page that covers its last result has been read
(api_spider.SAW_THE_END). It is cut short by the MAX_PAGES breaker, by three
pages lost in a row, by an anonymous visitor hitting the sign-in wall, or by
stopping with nobody deciding it was done - a killed spider looks like that.

That replaced a stricter reading on the same day. Until then any dropped
request made the scan incomplete, which would have left Indeed permanently
"never complete": it answered two of 39 requests with a challenge that
afternoon and served the rest, so one lost page per run would have meant the
run-counting rule never applying to the site with the largest queue.

What still makes a scan incomplete, whatever the searches say: it collected
no postings at all, a callback raised, or the crawl did not finish.
"""

import logging
import os
from datetime import datetime, timezone

from sqlalchemy.orm import sessionmaker

from .models import SiteScan, db_connect

logger = logging.getLogger(__name__)

# How many complete scans a posting has to be missing from before its page is
# opened again. Three at a three-day cadence is about nine days, which is
# inside UNLISTED_AFTER_DAYS (10) on purpose - see the note on that constant.
# 0 turns the rule off: every open posting is queued every run, which is what
# the checkers did before 03.10.2026.
MISSED_SCANS_BEFORE_CHECK = int(os.getenv("MISSED_SCANS_BEFORE_CHECK", "3"))

# A search that did not reach its own end is the rule itself; the spider
# counts them (api_spider._report_search_ends) and a killed or crashed run
# shows up there too, as a search nobody finished.
STOPPED_SHORT = (
    "searches/cut_short",
)

# These were the whole test until 04.10.2026 and are now covered by the
# searches above: a dropped request or a pool that ran out of addresses
# prevents a search from reaching its end, which is what gets counted.
# Keeping them here would make Indeed's every run incomplete over a single
# challenge it recovered from - measured 04.10, 2 of 39 requests.

# A callback that raised: the page arrived and we failed to read it, so the
# search's own bookkeeping cannot be trusted either. Scrapy counts these per
# exception class, so the prefix is what has to be looked for.
STOPPED_SHORT_PREFIXES = ("spider_exceptions/",)


def why_incomplete(stats, finish_reason=None):
    """
    The reason this scan cannot be trusted as a complete one, or None.

    `stats` is Scrapy's stats dict. Anything unexpected is read as incomplete
    rather than complete: the cost of being wrong in that direction is a few
    requests, and the cost of being wrong the other way is treating a run that
    never looked as evidence that a posting is gone.
    """
    for key in STOPPED_SHORT:
        count = stats.get(key) or 0
        if count:
            return f"{key}={count}"

    for key, count in (stats or {}).items():
        if count and key.startswith(STOPPED_SHORT_PREFIXES):
            return f"{key}={count}"

    reason = finish_reason or stats.get("finish_reason")
    if reason and reason != "finished":
        return f"finish_reason={reason}"

    # A SCAN THAT BROUGHT NOTHING BACK IS NOT A SCAN. Every one of these sites
    # has postings on it; a crawl that collected none of them has not told us
    # that they are gone, it has told us that something went wrong - and three
    # of those in a row would send every posting we hold to be re-opened.
    #
    # A site that genuinely empties out one day is recorded incomplete too,
    # which costs the next run some requests and nothing else. That is the
    # cheap direction to be wrong in.
    if not (stats or {}).get("item_scraped_count"):
        return "no postings collected"

    return None


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def record(site, stats, finish_reason=None, session=None):
    """
    Write one row for the scan that has just finished. Returns it.

    Called from the cards spiders' close hook. A checker never calls it: a
    checker reads postings it was given, it does not scan the site.
    """
    note = why_incomplete(stats or {}, finish_reason)
    scan = SiteScan(
        site=site,
        finished_at=_now(),
        complete=note is None,
        postings=(stats or {}).get("item_scraped_count") or 0,
        note=note[:200] if note else None,
    )

    own_session = session is None
    session = session or sessionmaker(bind=db_connect())()
    try:
        session.add(scan)
        session.commit()
        logger.info(
            "%s: scan recorded as %s%s, %s posting(s)",
            site, "COMPLETE" if scan.complete else "incomplete",
            f" ({note})" if note else "", scan.postings,
        )
        return scan
    finally:
        if own_session:
            session.close()


def complete_scans(session, site, limit=10):
    """The finishing times of this site's most recent complete scans, newest first."""
    rows = (
        session.query(SiteScan.finished_at)
        .filter(SiteScan.site == site)
        .filter(SiteScan.complete.is_(True))
        .order_by(SiteScan.finished_at.desc())
        .limit(limit)
        .all()
    )
    return [row[0] for row in rows]


def missed_since(session, site, scans=None):
    """
    The cut-off a posting's last_seen_at is compared against, or None.

    None means "no opinion", and the caller must then fall back to queueing
    the posting - which is what the checkers did before this rule. Two ways to
    get it, and both are the honest answer rather than a special case:

      * the rule is switched off (scans=0);
      * this site has not been scanned completely that many times yet, so
        nothing can be three scans old. A fresh database, or a site whose
        crawl has been failing, has no business hiding postings from the
        queue on the strength of scans that never happened.
    """
    scans = MISSED_SCANS_BEFORE_CHECK if scans is None else scans
    if not scans:
        return None

    finished = complete_scans(session, site, limit=scans)
    if len(finished) < scans:
        return None
    return finished[-1]
