"""
The query string every endpoint accepts, parsed once.

Multi-value parameters arrive comma-separated (`?sources=indeed,kariyer.net`)
rather than repeated, because the React side keeps them in the URL and a
comma-joined value is what survives a copy-pasted link legibly.
"""

from dataclasses import dataclass, field
from typing import Optional

from fastapi import Query

from api.queries import DEFAULT_RANGE, RANGES


def _split(value: Optional[str]):
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


@dataclass
class Filters:
    range: str = DEFAULT_RANGE
    sources: list = field(default_factory=list)
    types: list = field(default_factory=list)
    categories: list = field(default_factory=list)
    q: Optional[str] = None
    # Include postings the checks found gone from their source site. Off by
    # default: the board is a noticeboard, not an archive.
    closed: bool = False


def filter_params(
    range: str = Query(DEFAULT_RANGE, description="24h | 7d | 30d | all"),
    sources: Optional[str] = Query(None, description="Virgülle ayrılmış kaynak listesi"),
    types: Optional[str] = Query(None, description="Virgülle ayrılmış iş tipi listesi"),
    categories: Optional[str] = Query(None, description="Virgülle ayrılmış alan listesi"),
    q: Optional[str] = Query(None, description="Başlık veya şirket adında arama"),
    closed: bool = Query(False, description="Kapanmış ilanları da göster"),
) -> Filters:
    """
    FastAPI dependency.

    An unknown range falls back to the default instead of 422ing: the value
    comes from a URL a user may have edited by hand, and a broken link should
    show the board rather than an error page.
    """
    return Filters(
        range=range if range in RANGES else DEFAULT_RANGE,
        sources=_split(sources),
        types=_split(types),
        categories=_split(categories),
        q=q,
        closed=closed,
    )
