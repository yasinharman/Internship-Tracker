"""
WHICH ROWS COUNT, AND WHY
=========================

Every rule app.py enforced by hand lives here, once, so that six endpoints
cannot drift apart. The comments are the point: each rule below was written
after something went wrong, and a rule without its reason is one refactor away
from being "simplified" out.

Nothing in this module writes. The dashboard reads a database three other
scripts own.
"""

import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import Select, and_, distinct, func, or_, select

from MultiwebsiteScraper.models import JobPost

#####################################################
# THE TWO HIDES THAT ARE NOT DELETES                #
#####################################################
# Deliberately kept apart, because they have different owners:
#
#   is_active     the classifier's soft delete (classify_jobs.py) - a posting
#                 it judged to be somebody else's field
#   duplicate_of  dedupe_jobs.py - the same opening advertised on a second
#                 board, pointing at the row that should be shown instead
#
# Neither deletes anything; both are one UPDATE away from reversal. Folding
# them into a single flag would give two writers the same column and let each
# resurrect rows behind the other's back.
VISIBLE = (JobPost.is_active.is_(True), JobPost.duplicate_of.is_(None))


#####################################################
# JOB TYPE                                          #
#####################################################
# The types actually being looked for. Everything the scrapers find is still
# stored - postings disappear from the sites within weeks and cannot be
# fetched again, so we keep the data and narrow the view instead. These are
# only the DEFAULT selection; every type the database holds stays selectable.
PREFERRED_JOB_TYPES = ["Internship", "Part-Time"]

# pipelines.normalize_job_type() writes these and nothing else.
JOB_TYPE_LABELS = {
    "Internship": "Staj",
    "Part-Time": "Yarı zamanlı",
    "Full-Time": "Tam zamanlı",
    "Freelance": "Freelance",
    "Temporary": "Geçici",
    "Contract": "Sözleşmeli",
    "Remote": "Uzaktan",
    "Other": "Diğer",
}


#####################################################
# FIELD, AS DECIDED BY THE CLASSIFIER               #
#####################################################
# Two rules here, and the second one is the important one.
#
# Default to it + general_program: the whole point of the classifier is that
# the board should show software work, and general_program stays because
# "Intern" at UPS could still turn out to be software - the employer has not
# said yet.
#
# Unclassified rows (job_category IS NULL) stay VISIBLE no matter what the
# filter says - see category_condition() below. If the LLM API is down, or a
# crawl finished and the classify step failed, the postings are still real and
# the board must not be empty. A silent blank dashboard is a worse failure
# than a few unsorted rows.
PREFERRED_CATEGORIES = ["it", "general_program"]

CATEGORY_LABELS = {
    "it": "Yazılım / IT",
    "general_program": "Genel staj programı",
    "other": "Başka alan",
}

# Cosmetic only - main.py's SITE_LABELS shows a name a human recognises
# instead of the internal spider name. source_site holds these already, but a
# spider renamed later should not change what the board says.
SITE_LABELS = {
    "kariyer.net": "kariyer.net",
    "techcareer.net": "techcareer.net",
    "indeed": "Indeed",
    "indeed.com": "Indeed",
}


#####################################################
# TIME RANGES                                       #
#####################################################
RANGES = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
    "all": None,
}
DEFAULT_RANGE = "7d"

# The daily chart is capped rather than unbounded: 'all' on a board that has
# been collecting for a year would draw 365 unreadable bars. KPIs still count
# the whole range - only the series is trimmed.
MAX_SERIES_DAYS = 90


def display_tz():
    """
    Which midnight "Bugün Eklenen" means.

    created_at is naive UTC (models.py writes datetime.utcnow()), but the user
    and every site scraped are on Turkish time, where "bugün" starts three
    hours before UTC midnight. app.py compared a UTC column against
    datetime.now().date() and so was wrong for three hours a day; doing the
    conversion explicitly is the fix.

    DASHBOARD_TZ overrides it. The fallback is a fixed +03:00 rather than a
    crash: Turkey has had no DST since 2016, so the offset is right even if
    the container ships without a tz database.
    """
    name = os.getenv("DASHBOARD_TZ", "Europe/Istanbul")
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(name)
    except Exception:
        return timezone(timedelta(hours=3))


def utcnow():
    """Naive UTC, to compare against a column written by datetime.utcnow()."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def local_day_start(moment=None):
    """Naive-UTC instant of the most recent local midnight."""
    tz = display_tz()
    local = (moment or datetime.now(timezone.utc)).astimezone(tz)
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight.astimezone(timezone.utc).replace(tzinfo=None)


def range_bounds(range_key, now=None):
    """
    (start, previous_start) for a range key, both naive UTC or None.

    previous_start marks the equally long window before `start`, which is what
    the KPI deltas compare against. 'all' has no start and therefore nothing
    to compare to.
    """
    span = RANGES.get(range_key, RANGES[DEFAULT_RANGE])
    if span is None:
        return None, None
    reference = now or utcnow()
    start = reference - span
    return start, start - span


#####################################################
# BUILDING THE FILTER                               #
#####################################################
def category_condition(categories):
    """
    The rule that must not be lost.

    An empty selection means "no category filter". Otherwise the selected
    categories OR a NULL one - an unclassified posting is not evidence that
    the posting is irrelevant, only that nothing has looked at it yet.
    """
    if not categories:
        return None
    return or_(JobPost.job_category.in_(categories), JobPost.job_category.is_(None))


def search_condition(term):
    """Title or company. Case-insensitive; Postgres ILIKE handles Turkish."""
    if not term:
        return None
    pattern = f"%{term.strip()}%"
    return or_(JobPost.job_title.ilike(pattern), JobPost.company.ilike(pattern))


def conditions(filters, *, apply_range=True):
    """
    Every WHERE clause for one request, VISIBLE first.

    apply_range=False is for the "previous period" half of a delta, which
    supplies its own bounds.
    """
    clauses = list(VISIBLE)

    if filters.sources:
        clauses.append(JobPost.source_site.in_(filters.sources))
    if filters.types:
        clauses.append(JobPost.job_type.in_(filters.types))

    category = category_condition(filters.categories)
    if category is not None:
        clauses.append(category)

    search = search_condition(filters.q)
    if search is not None:
        clauses.append(search)

    if apply_range:
        start, _ = range_bounds(filters.range)
        if start is not None:
            clauses.append(JobPost.created_at >= start)

    return clauses


def base_select(filters, *, apply_range=True) -> Select:
    """A SELECT over the visible, filtered rows. Add columns with .with_only_columns()."""
    return select(JobPost).where(and_(*conditions(filters, apply_range=apply_range)))


def count_where(session, clauses):
    """COUNT(*) over an arbitrary clause list, without materialising rows."""
    return session.scalar(select(func.count()).select_from(JobPost).where(and_(*clauses))) or 0


def distinct_companies_where(session, clauses):
    return (
        session.scalar(
            select(func.count(distinct(JobPost.company)))
            .select_from(JobPost)
            .where(and_(*clauses, JobPost.company.is_not(None)))
        )
        or 0
    )
