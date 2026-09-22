"""
IS THIS YOUTHALL POSTING STILL OPEN?
====================================

    python -m scrapy crawl youthall_check -a dry_run=1    verdicts only
    python -m scrapy crawl youthall_check                 write them

Subclasses youthall_cards for the transport and the pace. One request per
posting; the verdict and the description come out of the same response.

THE PAGE CARRIES ITS OWN DEADLINE - MEASURED 22.09.2026
-------------------------------------------------------
Every posting page has a schema.org JobPosting in `ld+json`
(docs/sites/youthall.md). For Tchibo's "E-Ticaret Stajyeri":

    employmentType  INTERN
    validThrough    2026-11-14T23:59:59+03:00    (the title says the same:
                                                  "Son Başvuru: 14.11.2026")
    description     2,447 characters

So the verdict is a date comparison, not a page to interpret:

  * CLOSED  - validThrough is in the past. The site set the deadline itself.
  * OPEN    - validThrough is still ahead.
  * UNKNOWN - no JobPosting on the page, or no readable validThrough. Not yet
    seen is what a taken-down posting serves, so this stays the safe answer
    and writes nothing.
"""

import json
from datetime import datetime, timezone

from ..api_spider import strip_html
from ..openings import CLOSED, OPEN, UNKNOWN, OpeningCheckMixin
from .youthall_cards import YouthallCardsSpider


def job_posting(response):
    """The page's schema.org JobPosting as a dict, or None."""
    for block in response.css('script[type="application/ld+json"]::text').getall():
        try:
            data = json.loads(block)
        except ValueError:
            continue
        for candidate in data if isinstance(data, list) else [data]:
            if isinstance(candidate, dict) and candidate.get("@type") == "JobPosting":
                return candidate
    return None


class YouthallCheckSpider(OpeningCheckMixin, YouthallCardsSpider):
    name = "youthall_check"

    custom_settings = {
        **YouthallCardsSpider.custom_settings,
        "ITEM_PIPELINES": {},
        "SCRAPER_SLOT_MAX_ACTIVE_SIZE": 1,
    }

    def now(self):
        return datetime.now(timezone.utc)

    def verdict(self, response):
        posting = job_posting(response)
        if posting is None:
            self.crawler.stats.inc_value("youthall/no_job_posting")
            return UNKNOWN
        try:
            deadline = datetime.fromisoformat(posting.get("validThrough") or "")
        except ValueError:
            self.crawler.stats.inc_value("youthall/no_deadline")
            return UNKNOWN
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        return CLOSED if deadline < self.now() else OPEN

    def description(self, response):
        posting = job_posting(response)
        if not posting:
            return None
        return strip_html(posting.get("description") or "") or None
