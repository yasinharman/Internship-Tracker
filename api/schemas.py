"""
Response shapes.

Written out rather than returning bare dicts so the TypeScript client has one
place to be generated from (or checked against) and so an endpoint cannot
quietly stop sending a field the board renders.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class Health(BaseModel):
    status: str
    db: bool
    detail: Optional[str] = None


class Option(BaseModel):
    """One selectable filter value, with the count behind it."""

    value: str
    label: str
    count: int


class Defaults(BaseModel):
    range: str
    types: list[str]
    categories: list[str]


class Meta(BaseModel):
    sources: list[Option]
    types: list[Option]
    categories: list[Option]
    defaults: Defaults
    # Postings the classifier has not looked at yet. Surfaced because they are
    # shown regardless of the category filter and the board should say so.
    unclassified_count: int
    # Postings the checks found gone from their source site. Drives the count
    # on the "Kapananlar" toggle, so the button can say what it would reveal
    # before it is pressed.
    closed_count: int
    last_crawl_at: Optional[datetime]
    total: int


class Delta(BaseModel):
    """
    A KPI's change against the previous equally long window.

    direction is 'up' | 'down' | 'flat' so the arrow is decided here rather
    than re-derived from the sign in the component. percent is None when the
    previous window was empty - a jump from nothing is not a percentage.
    """

    value: float
    percent: Optional[float]
    direction: str
    label: str


class Kpis(BaseModel):
    total: int
    today: int
    companies: int
    unclassified: int
    total_delta: Optional[Delta]
    companies_delta: Optional[Delta]


class DailyPoint(BaseModel):
    date: str
    count: int
    companies: int


class SourceSlice(BaseModel):
    site: str
    label: str
    count: int


class Stats(BaseModel):
    kpis: Kpis
    daily: list[DailyPoint]
    sources: list[SourceSlice]
    range: str
    # True when the series was trimmed to MAX_SERIES_DAYS, so the chart can
    # say it is not showing everything the KPIs counted.
    series_truncated: bool


class Job(BaseModel):
    id: int
    job_title: str
    company: Optional[str]
    location: Optional[str]
    url: str
    source_site: str
    source_label: str
    job_type: Optional[str]
    job_type_label: Optional[str]
    job_category: Optional[str]
    category_label: Optional[str]
    # The classifier's reasoning, shown on purpose: a verdict should be
    # arguable, not silent. A posting in the wrong bucket is obvious the
    # moment its reason reads wrong.
    category_reason: Optional[str]
    created_at: datetime
    # NULL means still on offer. A value is when a check found it gone - the
    # row is only ever sent when the caller asked for closed postings.
    closed_at: Optional[datetime]
    # When a check last got a conclusive answer, and when a crawl last saw
    # this url in a search result. Both None across the board until the first
    # run of the checks, which is why "never checked" has to stay tellable
    # apart from "checked and open".
    checked_at: Optional[datetime]
    last_seen_at: Optional[datetime]


class JobPage(BaseModel):
    rows: list[Job]
    total: int
    limit: int
    offset: int


class Company(BaseModel):
    company: str
    count: int
    sources: list[str]
    last_seen: datetime
    watched: bool


class CompanyPage(BaseModel):
    rows: list[Company]
    total: int
    limit: int
    offset: int


class Source(BaseModel):
    site: str
    label: str
    count: int
    today: int
    companies: int
    last_seen: Optional[datetime]
    # Hours since this source last produced a posting. The one place amber/red
    # belongs on this board: a crawler that stopped returning rows is a real
    # fault, unlike a source simply having fewer openings than another.
    stale_hours: Optional[float]


class WatchlistEntry(BaseModel):
    name: str
    count: int
    last_seen: Optional[datetime]
    notified: int


class Watchlist(BaseModel):
    entries: list[WatchlistEntry]
    # pipeline/notify_watchlist.py reads this file at crawl time; if it is missing the
    # Telegram ping is simply not happening and the page should say that.
    configured: bool
