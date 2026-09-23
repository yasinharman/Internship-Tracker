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

from sqlalchemy import Select, and_, distinct, exists, func, or_, select

from scraper.fields import FIELDS as FIELD_LABELS
from scraper.fields import ORDER as FIELD_ORDER
from scraper.models import UNLISTED_AFTER_DAYS, JobPost, JobPostField

#####################################################
# THE TWO HIDES THAT ARE NOT DELETES                #
#####################################################
# Deliberately kept apart, because they have different owners:
#
#   is_active     the classifier's soft delete (pipeline/classify_jobs.py) - a posting
#                 it judged to be somebody else's field
#   duplicate_of  pipeline/dedupe_jobs.py - the same opening advertised on a second
#                 board, pointing at the row that should be shown instead
#
# Neither deletes anything; both are one UPDATE away from reversal. Folding
# them into a single flag would give two writers the same column and let each
# resurrect rows behind the other's back.
VISIBLE = (JobPost.is_active.is_(True), JobPost.duplicate_of.is_(None))


#####################################################
# THE THIRD HIDE, AND THE ONLY SWITCHABLE ONE       #
#####################################################
# closed_at   the *_check spiders (scraper/openings.py) - the
#             posting is no longer on offer at the board it came from.
#
# Deliberately not is_active either, for a reason that is not just tidiness:
# pipelines.py sets is_active back to True on every re-crawl, so a posting
# closed here would come back to life on the next run. Its own column, its own
# single writer - the same answer duplicate_of got.
#
# Unlike the other two, this one has a switch. "Kapandi" and "baska alan" are
# different things to a person: a job that closed yesterday is still worth
# knowing about, while one the classifier judged to be somebody else's field
# is not. So the board hides closed postings by default and the toggle brings
# them back - and it brings back ONLY these, never the classifier's pile.
OPEN = (JobPost.closed_at.is_(None),)


#####################################################
# THE FOURTH HIDE: NOT SORTED YET                   #
#####################################################
# job_category IS NULL   pipeline/classify_jobs.py has not judged the posting
#                        yet - since 12.09.2026 that mostly means its
#                        description has not arrived.
#
# These were shown until 16.09.2026, whatever the field filter said, on the
# argument that a failed classify step should not blank the board. The owner
# reversed that on 16.09.2026, when Indeed's first full run left 245 of its 296
# postings waiting: a board mostly made of unsorted rows is not the board
# being asked for, and a row with no description has nothing to read anyway.
#
# The cost is the old argument, and it is stated rather than rediscovered: if
# classify stops working, new postings stop appearing. That is not silent -
# /api/meta and /api/stats still count the waiting rows (see
# conditions(waiting=True)), and the dashboard shows that count.
#
# Not a switch. The "Kapananlar" toggle brings back closed postings and still
# only those; an unsorted closed posting is never classified (classify skips
# closed rows), so it stays out either way.
CLASSIFIED = (JobPost.job_category.is_not(None),)


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
# NOTHING IS PRE-SELECTED SINCE 23.09.2026. The board used to open on
# it + general_program, because it was a software board and everything else
# was noise. It is for every student now (scraper/fields.py), and a default
# that shows one field would be the old hide wearing a different hat: a
# mechanical engineering student would open the page and see software
# postings. An empty selection means every field, and the student narrows it.
PREFERRED_CATEGORIES = []

# The dashboard's "Alan" dropdown takes its options from /api/meta, so the
# taxonomy lives in one place: scraper/fields.py. Renaming a field there
# renames it on the board.
CATEGORY_LABELS = dict(FIELD_LABELS)

# Cosmetic only - main.py's SITE_LABELS shows a name a human recognises
# instead of the internal spider name. source_site holds these already, but a
# spider renamed later should not change what the board says.
SITE_LABELS = {
    "kariyer.net": "kariyer.net",
    "techcareer.net": "techcareer.net",
    "indeed": "Indeed",
    "indeed.com": "Indeed",
    "linkedin.com": "LinkedIn",
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

# Everything, by default.
#
# The board already lists postings newest first, so a time window is not what
# makes the recent ones easy to find - it only hides the older ones. And
# hiding them is the wrong default for this data: a posting that is three
# weeks old is still open, and the crawl schedule means a quiet fortnight
# would leave a seven-day board looking broken rather than quiet.
#
# The cost is that the KPI deltas have nothing to compare against and are
# omitted (see _delta), which is honest - there is no "previous period" for
# all of time. Pick 24h/7d/30d in the header to get them back.
DEFAULT_RANGE = "all"

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


#####################################################
# THE FIFTH HIDE: NOT IN THE LISTINGS ANY MORE      #
#####################################################
# last_seen_at   scraper/pipelines.py stamps it every time a posting turns up
#                in a search. A row the crawl has not seen for
#                UNLISTED_AFTER_DAYS drops off the board, and the checker
#                stops spending a request on it (scraper/openings.py).
#
# Not a verdict and not a write: absence from a search proves nothing on its
# own (21.08.2026, only 14 of 36 kariyer.net postings showed up in that day's
# searches). This is the board declining to vouch for a posting nobody has
# seen in a week, and it reverses itself - the next crawl that finds the
# posting stamps a fresh last_seen_at and the row is back, same id, same
# history.
#
# Applied with OPEN rather than with VISIBLE, so the "Kapananlar" toggle still
# shows closed postings however old they are. A posting that is neither closed
# nor still listed is in neither view; that is the crude part of the rule, and
# docs/activity-checks-plan.md is where it gets fixed.
def listed(now=None):
    """The one condition, built at call time because it moves with the clock."""
    cutoff = (now or utcnow()) - timedelta(days=UNLISTED_AFTER_DAYS)
    # NULL is not evidence that a posting has gone quiet - it is a row written
    # before the column existed - so it stays on the board.
    return (
        or_(JobPost.last_seen_at.is_(None), JobPost.last_seen_at > cutoff),
    )


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
    An empty selection means "no category filter". Otherwise the selected
    fields and nothing else.

    A posting carries up to three fields (scraper/fields.py), so this asks
    job_post_fields rather than the posting's own column: a "Yazılım ve Veri
    Stajyeri" is in the veri_yapay_zeka list as well as the yazilim one, and
    matching on job_category alone would show it in neither if the student
    picked the second. EXISTS rather than a join so a posting in two selected
    fields is still one row.

    Until 16.09.2026 this also let a NULL category through, whatever was
    selected. That rule is gone on purpose; see CLASSIFIED.
    """
    if not categories:
        return None
    return exists().where(
        (JobPostField.job_post_id == JobPost.id)
        & (JobPostField.field.in_(categories))
    )


def search_condition(term):
    """Title or company. Case-insensitive; Postgres ILIKE handles Turkish."""
    if not term:
        return None
    pattern = f"%{term.strip()}%"
    return or_(JobPost.job_title.ilike(pattern), JobPost.company.ilike(pattern))


def conditions(filters, *, apply_range=True, waiting=False):
    """
    Every WHERE clause for one request, VISIBLE first.

    apply_range=False is for the "previous period" half of a delta, which
    supplies its own bounds.

    waiting=True asks the opposite question about the same filter: which rows
    it would match, were they sorted, that are still waiting for classify.
    That is the count the dashboard shows for the rows CLASSIFIED hides. The
    field filter is left out, because a row with no category cannot match one,
    and so are closed rows, because classify never sorts those.
    """
    clauses = list(VISIBLE)

    # Closed postings are out unless they were explicitly asked for, and so
    # are postings the crawl has stopped seeing - see listed().
    if waiting or not filters.closed:
        clauses.extend(OPEN)
        clauses.extend(listed())

    if filters.sources:
        clauses.append(JobPost.source_site.in_(filters.sources))
    if filters.types:
        clauses.append(JobPost.job_type.in_(filters.types))

    if waiting:
        clauses.append(JobPost.job_category.is_(None))
    else:
        clauses.extend(CLASSIFIED)
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


###############################################################
# ONE LOGO PER EMPLOYER, BORROWED ACROSS POSTINGS             #
###############################################################
# `company_logo_url` says what the crawl saw on ONE posting, and three of the
# four boards supply it. Indeed supplies nothing: measured 09.09.2026, its
# card records carry a company name, an opaque id and a rating, and no artwork
# at all - docs/sites/indeed.md has the counts. So an Indeed row can never
# earn a logo of its own, however many times it is re-crawled.
#
# It can borrow one. If LinkedIn showed us Trendyol's mark on Tuesday, that is
# still Trendyol's mark on the Indeed posting we found on Wednesday.
#
# THIS IS A READ-TIME FALLBACK, NOT A WRITE. Nothing copies a url onto a row
# the crawl did not see it on: the column keeps meaning "what this posting
# showed us", so a wrong logo can never be laundered into looking like
# evidence, and the day Indeed starts serving artwork the borrowed value is
# simply replaced by the real one. It also improves on its own - every crawl
# that finds a new employer widens what the rest of the board can borrow.
#
# Matched on a normalised name because the four boards do not spell employers
# the same way. Case and inner whitespace are folded, and Turkish casing is
# used: "İŞ BANKASI".lower() is "i̇ş bankasi" under the invariant rules and
# only matches itself if both sides are folded the same way. Nothing fuzzier
# than that, and the reason is measured rather than assumed. Stripping legal
# suffixes - A.Ş., Ltd., Şti., San., Tic., Inc., GmbH, Holding, Group - was
# tried on 09.09.2026 against the 110 Indeed employers with no logo: 16 match
# on the normalised name and the looser rule added EXACTLY ZERO. The other 94
# have no logo anywhere in the data because they do not post on the boards
# that carry one. So the looser rule buys nothing and costs the risk of
# hanging one employer's mark on another's posting.
def normalize_company(name):
    if not name:
        return None
    folded = " ".join(str(name).split()).casefold()
    return folded or None


def logos_by_company(session, companies):
    """
    {normalised name: logo url} for the employers asked about.

    Newest first and first-one-wins, so an employer that changed its mark is
    represented by the most recent posting that showed it.
    """
    wanted = {normalize_company(name) for name in companies}
    wanted.discard(None)
    if not wanted:
        return {}

    # Narrowed by DISTINCT ON rather than by a WHERE on the name, and that is
    # deliberate: the match is Python's casefold and SQL's lower() is not the
    # same function on Turkish text, so a name filter here would quietly drop
    # candidates the Python side would have matched. One row per spelling
    # instead - bounded by the number of employers that have ever shown a
    # logo, a few hundred - and the comparison happens in one place.
    #
    # The board's own hides do not apply. A logo is a fact about an employer,
    # not about whether one of its postings is still open or was classified
    # into another field, and the row it came from having closed does not make
    # the mark wrong.
    rows = session.execute(
        select(JobPost.company, JobPost.company_logo_url, JobPost.created_at)
        .where(
            JobPost.company_logo_url.is_not(None),
            JobPost.company.is_not(None),
        )
        .distinct(JobPost.company)
        .order_by(JobPost.company, JobPost.created_at.desc())
    ).all()

    found = {}
    for company, logo, _created in sorted(rows, key=lambda r: r[2], reverse=True):
        key = normalize_company(company)
        if key in wanted and key not in found:
            found[key] = logo
    return found
