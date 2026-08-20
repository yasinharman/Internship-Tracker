"""
THE DASHBOARD SERVER
====================

Two jobs in one process:

  /api/*   JSON read over the job_posts table
  /*       the built React app (web/dist), with a catch-all so client-side
           routing survives a hard refresh on /ilanlar

One service on one port, because Coolify starts this image with a build stage
target and nothing else - the fewer moving parts that deploy has, the fewer
ways it drifts from what runs locally.
"""

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import and_, distinct, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from api import queries as q
from api.deps import DatabaseNotConfigured, get_engine, get_session
from api.filters import Filters, filter_params
from api.schemas import (
    Company,
    CompanyPage,
    DailyPoint,
    Defaults,
    Delta,
    Health,
    Job,
    JobPage,
    Kpis,
    Meta,
    Option,
    Source,
    SourceSlice,
    Stats,
    Watchlist,
    WatchlistEntry,
)
from MultiwebsiteScraper.models import JobPost

load_dotenv()

WEB_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"

app = FastAPI(title="İlan Panosu", docs_url="/api/docs", openapi_url="/api/openapi.json")


@app.exception_handler(DatabaseNotConfigured)
def _database_not_configured(request, exc):
    """
    503 with the same instructions Streamlit printed on the page.

    A missing DATABASE_URL is a deployment mistake, not a bug, and the message
    is the whole fix - naming .env, Coolify and the url format is what stops
    the next person guessing at a driver error.
    """
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.exception_handler(SQLAlchemyError)
def _database_unreachable(request, exc):
    """
    503 rather than the 500 an unhandled exception would produce.

    The distinction is the whole point: 500 means this service is broken and
    the board should say so; 503 means the database is not answering, which is
    a different thing to go and look at. Without this the front end gets an
    empty-bodied 500 and can only offer "bir hata oluştu".

    The driver's own message is deliberately not forwarded - it carries the
    host, port and user from the connection string, and this response is
    public.
    """
    return JSONResponse(
        status_code=503,
        content={
            "detail": (
                "Veritabanına ulaşılamıyor. Sunucu ayakta ama sorgu yanıtlanamadı - "
                "DATABASE_URL'in gösterdiği Postgres çalışıyor mu ve buradan erişilebilir mi?"
            ),
            "kind": exc.__class__.__name__,
        },
    )


#####################################################
# HEALTH                                            #
#####################################################
@app.get("/api/health", response_model=Health)
def health():
    """
    Never raises. A health check that 500s tells a monitor the process is
    gone when the truth is that the database is unreachable, which is a
    different call-out.
    """
    try:
        engine = get_engine()
        with engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")
        return Health(status="ok", db=True)
    except DatabaseNotConfigured as error:
        return Health(status="unconfigured", db=False, detail=str(error))
    except SQLAlchemyError as error:
        return Health(status="degraded", db=False, detail=str(error.__class__.__name__))


#####################################################
# FILTER OPTIONS                                    #
#####################################################
def _options(session, column, labels, clauses):
    """
    Distinct values of one column with their counts, biggest first.

    Counted over the VISIBLE rows only - offering a filter value that matches
    nothing the board would ever show is a dead end for the user.
    """
    rows = session.execute(
        select(column, func.count())
        .where(and_(*clauses, column.is_not(None)))
        .group_by(column)
        .order_by(func.count().desc())
    ).all()
    return [Option(value=value, label=labels.get(value, value), count=count) for value, count in rows]


@app.get("/api/meta", response_model=Meta)
def meta(session: Session = Depends(get_session)):
    """
    Everything needed to draw the filter bar before any data is on screen.

    Deliberately NOT filtered by the current selection: a filter bar that
    removes its own options as you use them cannot be undone from the UI.
    """
    visible = list(q.VISIBLE)

    types = _options(session, JobPost.job_type, q.JOB_TYPE_LABELS, visible)
    categories = _options(session, JobPost.job_category, q.CATEGORY_LABELS, visible)
    sources = _options(session, JobPost.source_site, q.SITE_LABELS, visible)

    available_types = {option.value for option in types}
    default_types = [t for t in q.PREFERRED_JOB_TYPES if t in available_types]

    available_categories = {option.value for option in categories}
    default_categories = [c for c in q.PREFERRED_CATEGORIES if c in available_categories]

    return Meta(
        sources=sources,
        types=types,
        categories=categories,
        defaults=Defaults(
            range=q.DEFAULT_RANGE,
            # Falling back to "everything" rather than "nothing" when the
            # preferred values are absent: a board opening empty on a fresh
            # database looks broken.
            types=default_types or [option.value for option in types],
            categories=default_categories or [option.value for option in categories],
        ),
        unclassified_count=q.count_where(session, visible + [JobPost.job_category.is_(None)]),
        last_crawl_at=session.scalar(select(func.max(JobPost.created_at)).where(and_(*visible))),
        total=q.count_where(session, visible),
    )


#####################################################
# KPIs, DAILY SERIES, SOURCE SPLIT                  #
#####################################################
def _delta(current, previous, unit):
    """
    None when there is no previous window to compare against ('all'), so the
    card renders the number alone instead of an invented 0%.
    """
    if previous is None:
        return None

    change = current - previous
    percent = (change / previous * 100) if previous else None
    direction = "flat" if change == 0 else ("up" if change > 0 else "down")

    if percent is None:
        label = "yeni" if change else "sabit"
    else:
        label = "sabit" if direction == "flat" else f"%{abs(percent):.1f}".replace(".", ",")

    return Delta(value=float(change), percent=percent, direction=direction, label=label)


@app.get("/api/stats", response_model=Stats)
def stats(filters: Filters = Depends(filter_params), session: Session = Depends(get_session)):
    current = q.conditions(filters)
    start, previous_start = q.range_bounds(filters.range)

    total = q.count_where(session, current)
    companies = q.distinct_companies_where(session, current)

    total_delta = companies_delta = None
    if start is not None and previous_start is not None:
        window = q.conditions(filters, apply_range=False) + [
            JobPost.created_at >= previous_start,
            JobPost.created_at < start,
        ]
        total_delta = _delta(total, q.count_where(session, window), "ilan")
        companies_delta = _delta(companies, q.distinct_companies_where(session, window), "şirket")

    today = q.count_where(
        session,
        q.conditions(filters, apply_range=False) + [JobPost.created_at >= q.local_day_start()],
    )

    # Grouped in the display timezone, not UTC: a posting that arrived at
    # 00:30 Istanbul time belongs to that day's bar, not the previous one.
    tz_name = os.getenv("DASHBOARD_TZ", "Europe/Istanbul")
    local_day = func.date(func.timezone(tz_name, func.timezone("UTC", JobPost.created_at)))

    series_start = start
    floor = q.utcnow() - timedelta(days=q.MAX_SERIES_DAYS)
    truncated = False
    if series_start is None or series_start < floor:
        truncated = series_start is None or series_start < floor
        series_start = floor

    series_clauses = q.conditions(filters, apply_range=False) + [JobPost.created_at >= series_start]
    daily_rows = session.execute(
        select(local_day, func.count(), func.count(distinct(JobPost.company)))
        .where(and_(*series_clauses))
        .group_by(local_day)
        .order_by(local_day)
    ).all()
    by_day = {day.isoformat(): (count, company_count) for day, count, company_count in daily_rows}

    # Every day in the window, including the empty ones. Without this a quiet
    # weekend closes the gap and the chart implies postings arrived when they
    # did not.
    daily = []
    cursor = series_start.date()
    last = q.utcnow().date()
    while cursor <= last:
        key = cursor.isoformat()
        count, company_count = by_day.get(key, (0, 0))
        daily.append(DailyPoint(date=key, count=count, companies=company_count))
        cursor += timedelta(days=1)

    source_rows = session.execute(
        select(JobPost.source_site, func.count())
        .where(and_(*current))
        .group_by(JobPost.source_site)
        .order_by(func.count().desc())
    ).all()

    return Stats(
        kpis=Kpis(
            total=total,
            today=today,
            companies=companies,
            unclassified=q.count_where(session, current + [JobPost.job_category.is_(None)]),
            total_delta=total_delta,
            companies_delta=companies_delta,
        ),
        daily=daily,
        sources=[
            SourceSlice(site=site, label=q.SITE_LABELS.get(site, site), count=count)
            for site, count in source_rows
        ],
        range=filters.range,
        series_truncated=truncated,
    )


#####################################################
# POSTINGS                                          #
#####################################################
SORTABLE = {
    "created_at": JobPost.created_at,
    "job_title": JobPost.job_title,
    "company": JobPost.company,
    "source_site": JobPost.source_site,
}


def _job(row: JobPost) -> Job:
    return Job(
        id=row.id,
        job_title=row.job_title,
        company=row.company,
        location=row.location,
        url=row.url,
        source_site=row.source_site,
        source_label=q.SITE_LABELS.get(row.source_site, row.source_site),
        job_type=row.job_type,
        job_type_label=q.JOB_TYPE_LABELS.get(row.job_type, row.job_type),
        job_category=row.job_category,
        category_label=q.CATEGORY_LABELS.get(row.job_category) if row.job_category else None,
        category_reason=row.category_reason,
        created_at=row.created_at,
    )


@app.get("/api/jobs", response_model=JobPage)
def jobs(
    filters: Filters = Depends(filter_params),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    sort: str = Query("created_at"),
    direction: str = Query("desc"),
    session: Session = Depends(get_session),
):
    clauses = q.conditions(filters)
    column = SORTABLE.get(sort, JobPost.created_at)
    order = column.desc() if direction == "desc" else column.asc()

    rows = session.scalars(
        select(JobPost).where(and_(*clauses)).order_by(order, JobPost.id.desc()).limit(limit).offset(offset)
    ).all()

    return JobPage(
        rows=[_job(row) for row in rows],
        total=q.count_where(session, clauses),
        limit=limit,
        offset=offset,
    )


#####################################################
# COMPANIES                                         #
#####################################################
@app.get("/api/companies", response_model=CompanyPage)
def companies(
    filters: Filters = Depends(filter_params),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
):
    clauses = q.conditions(filters) + [JobPost.company.is_not(None), JobPost.company != ""]

    grouped = (
        select(
            JobPost.company,
            func.count().label("count"),
            func.max(JobPost.created_at).label("last_seen"),
            func.array_agg(distinct(JobPost.source_site)).label("sources"),
        )
        .where(and_(*clauses))
        .group_by(JobPost.company)
    )

    rows = session.execute(
        grouped.order_by(func.count().desc(), JobPost.company.asc()).limit(limit).offset(offset)
    ).all()

    total = session.scalar(select(func.count()).select_from(grouped.subquery())) or 0

    watchlist = _watchlist_names()
    return CompanyPage(
        rows=[
            Company(
                company=company,
                count=count,
                sources=sorted(sources or []),
                last_seen=last_seen,
                watched=_matches_watchlist(company, watchlist) is not None,
            )
            for company, count, last_seen, sources in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


#####################################################
# SOURCES                                           #
#####################################################
@app.get("/api/sources", response_model=list[Source])
def sources(filters: Filters = Depends(filter_params), session: Session = Depends(get_session)):
    """
    Per-site health. The source filter is ignored on purpose: a site missing
    from this list because it was filtered out is exactly the site you would
    have wanted to see had stopped producing.
    """
    unfiltered = Filters(
        range=filters.range, sources=[], types=filters.types, categories=filters.categories, q=filters.q
    )
    clauses = q.conditions(unfiltered)
    day_start = q.local_day_start()
    now = q.utcnow()

    rows = session.execute(
        select(
            JobPost.source_site,
            func.count(),
            func.count(distinct(JobPost.company)),
            func.max(JobPost.created_at),
        )
        .where(and_(*clauses))
        .group_by(JobPost.source_site)
        .order_by(func.count().desc())
    ).all()

    result = []
    for site, count, company_count, last_seen in rows:
        today = q.count_where(
            session,
            q.conditions(unfiltered, apply_range=False)
            + [JobPost.source_site == site, JobPost.created_at >= day_start],
        )
        result.append(
            Source(
                site=site,
                label=q.SITE_LABELS.get(site, site),
                count=count,
                today=today,
                companies=company_count,
                last_seen=last_seen,
                stale_hours=round((now - last_seen).total_seconds() / 3600, 1) if last_seen else None,
            )
        )
    return result


#####################################################
# WATCHLIST                                         #
#####################################################
def _watchlist_names():
    """
    notify_watchlist.py owns this file; importing its loader rather than
    re-reading the YAML keeps one parser and one set of rules about what an
    entry means.
    """
    try:
        from notify_watchlist import load_watchlist

        return load_watchlist()
    except Exception:
        return []


def _matches_watchlist(company, watchlist):
    try:
        from notify_watchlist import matches_watchlist

        return matches_watchlist(company, watchlist)
    except Exception:
        return None


@app.get("/api/watchlist", response_model=Watchlist)
def watchlist(filters: Filters = Depends(filter_params), session: Session = Depends(get_session)):
    """
    Which watched companies actually posted, and whether Hermes was told.

    Matching happens in Python via notify_watchlist.matches_watchlist rather
    than as a SQL ILIKE: str.lower() gets Turkish wrong ("İş Bankası" grows a
    combining dot and matches nothing), and that helper already works around
    it. A few hundred companies is nothing to loop over.
    """
    names = _watchlist_names()
    if not names:
        return Watchlist(entries=[], configured=False)

    clauses = q.conditions(filters) + [JobPost.company.is_not(None)]
    rows = session.execute(
        select(JobPost.company, JobPost.created_at, JobPost.notified_at).where(and_(*clauses))
    ).all()

    tally = {name: {"count": 0, "last_seen": None, "notified": 0} for name in names}
    for company, created_at, notified_at in rows:
        matched = _matches_watchlist(company, names)
        if not matched:
            continue
        entry = tally[matched]
        entry["count"] += 1
        if notified_at is not None:
            entry["notified"] += 1
        if entry["last_seen"] is None or created_at > entry["last_seen"]:
            entry["last_seen"] = created_at

    return Watchlist(
        entries=[
            WatchlistEntry(name=name, count=data["count"], last_seen=data["last_seen"], notified=data["notified"])
            for name, data in sorted(tally.items(), key=lambda item: (-item[1]["count"], item[0]))
        ],
        configured=True,
    )


#####################################################
# THE REACT APP                                     #
#####################################################
# Mounted last so that nothing here can shadow /api. If web/dist is absent
# the API still serves - that is the state during `npm run dev`, where Vite
# serves the front end itself and proxies /api here.
if WEB_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        """
        Catch-all so a hard refresh on /ilanlar returns the app rather than a
        404 - the router runs in the browser and the server has no such route.

        A real file (favicon, logo) is served as itself; everything else gets
        index.html. /api never reaches here: FastAPI matches the routes above
        first, and an unknown /api path should 404 as JSON, not as HTML.
        """
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")

        candidate = (WEB_DIST / full_path).resolve()
        if full_path and candidate.is_file() and candidate.is_relative_to(WEB_DIST.resolve()):
            return FileResponse(candidate)
        return FileResponse(WEB_DIST / "index.html")
