"""
IS THIS techcareer.net POSTING STILL OPEN?

    python -m scrapy crawl techcareer_check -a dry_run=1    verdicts only
    python -m scrapy crawl techcareer_check                 write them

The one site that answers the question directly - see verdict().
"""

from ..api_spider import dig
from ..openings import CLOSED, OPEN, UNKNOWN, OpeningCheckMixin
from .techcareer_api import TechCareerApiSpider


class TechCareerCheckSpider(OpeningCheckMixin, TechCareerApiSpider):
    name = "techcareer_check"

    custom_settings = {
        **TechCareerApiSpider.custom_settings,
        "ITEM_PIPELINES": {},
    }

    def probe_request(self, posting):
        """
        The stored url is the human page (/jobs/detail/<slug>); its JSON twin
        under /_next/data/<buildId>/ is 22 kB instead of 200 and answers the
        question in a field rather than a rendering.

        buildId changes on every deployment and cannot be hardcoded - reading
        it out of the warm-up page is exactly what the parent's on_warmup hook
        already does, and inheriting that is most of why this is a subclass.
        """
        if not self.build_id:
            self.logger.error("no buildId from the warm-up; cannot check %s", posting["url"])
            return None

        slug = posting["url"].rstrip("/").rsplit("/", 1)[-1]
        return self.api_request(
            self._data_url(f"jobs/detail/{slug}"),
            callback=self.parse_check,
            referer=posting["url"],
            headers={"x-nextjs-data": "1"},
            meta={"posting_id": posting["id"]},
            dont_filter=True,
        )

    def verdict(self, response):
        """
        MEASURED 21.08.2026:

            head.isCompleted true,  endDate 2026-08-15 (past)   -> closed
            head.isCompleted false, endDate 2026-08-26 (future) -> open
            a slug that does not exist -> HTTP 200, 105-byte body, no head

        isCompleted is the site's own word for it - the list endpoint filters
        on the same field (jobs[isCompleted]=false, docs/sites/techcareer.md) - so this is
        not a marker that happens to correlate, it is the answer.

        An empty head on a 200 means the posting is gone rather than that
        something went wrong: a blocked or redirected response would not parse
        as this endpoint's JSON at all, and falls through to UNKNOWN below.
        """
        payload = self.parse_json(response)
        if payload is None:
            return UNKNOWN

        detail = dig(payload, "pageProps.jobDetail")
        if detail is None:
            # Not this endpoint's shape - an interstitial, or the route moved.
            return UNKNOWN

        head = detail.get("head") or {}
        if not head:
            return CLOSED

        return CLOSED if head.get("isCompleted") else OPEN
