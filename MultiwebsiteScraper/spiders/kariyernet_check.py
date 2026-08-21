"""
IS THIS kariyer.net POSTING STILL OPEN?

    python -m scrapy crawl kariyernet_check -a dry_run=1    verdicts only
    python -m scrapy crawl kariyernet_check                 write them

Subclasses the crawl spider so the curl_cffi transport, the impersonation
ladder and the 4s delay all come along; only the urls and the verdict differ.
See MultiwebsiteScraper/openings.py for why this is a spider at all.
"""

from ..openings import CLOSED, OPEN, UNKNOWN, OpeningCheckMixin
from .kariyernet_cards import KariyerNetCardsSpider


class KariyerNetCheckSpider(OpeningCheckMixin, KariyerNetCardsSpider):
    name = "kariyernet_check"

    # No items, so no pipeline. Without this the pipeline opens a database
    # connection at startup for rows it will never be handed.
    custom_settings = {
        **KariyerNetCardsSpider.custom_settings,
        "ITEM_PIPELINES": {},
    }

    def verdict(self, response):
        """
        MEASURED 21.08.2026, two live postings against two closed ones.

        The apply button is the signal:

            live    4487444 (Eczacibasi), 4502891 (BASF)   -> 1 button each
            closed  4469047 (PepsiCo), 4498903 (TK Asansor) -> 0, and a
                    "Benzer Ilanlar" block appears instead

        BOTH RETURN HTTP 200, so a status-code check sees nothing at all. And
        an id that never existed 200s as well, after redirecting to
        /is-ilanlari - which is why the description block is checked before
        anything is called closed: it proves we are looking at a posting page
        rather than the listing page, a Cloudflare interstitial or an error.

        data-test attributes are the same family the listing spider already
        depends on (data-test="ad-card", "ad-card-title"), so this is not a
        new class of selector to keep working.
        """
        if response.css('[data-test="apply-button"]'):
            return OPEN

        on_a_posting_page = response.css(
            '[data-test="qualifications-and-job-description"], [data-test="job-description"]'
        )
        if on_a_posting_page:
            return CLOSED

        return UNKNOWN
