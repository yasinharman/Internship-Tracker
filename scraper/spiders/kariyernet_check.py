"""
IS THIS kariyer.net POSTING STILL OPEN?

    python -m scrapy crawl kariyernet_check -a dry_run=1    verdicts only
    python -m scrapy crawl kariyernet_check                 write them

Subclasses the crawl spider so the transport comes along - a real windowed
browser and the delay between navigations. Only the urls and the verdict
differ. See scraper/openings.py for why this is a spider at all.

EVERY PROBE IS A POSTING PAGE, so every probe needs its own browser context.
That is the whole finding of 10.09.2026 and it is not optional here: this
spider does nothing BUT fetch posting pages, so without it the first probe
succeeds and every one after it is refused. probe_request below sets the
flag; the measurement is in kariyernet_cards.

IT NEEDS A WINDOW TOO, inherited from NEEDS_A_WINDOW on the parent. Headless
does not fail here, it lies: PerimeterX answers it with a block page that
carries neither an apply button nor a description container, which is
verdict()'s exact definition of UNKNOWN. A headless run would therefore
report every posting in the database as unverifiable rather than as blocked.
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

    def probe_request(self, posting):
        """
        One probe per posting, each from a browser that has never been to the
        site - see the module docstring and kariyernet_cards.

        The parent's request is taken and its meta added to rather than
        rebuilt, so anything openings.py starts putting there (it owns
        posting_id, and dont_filter is load bearing) keeps arriving.
        """
        request = super().probe_request(posting)
        if request is not None:
            request.meta["fresh_context"] = True
        return request

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

    def description(self, response):
        """
        The container the verdict above already selects, read for its text.

        Note what that means: on a CLOSED posting this is the branch that
        fired, so the description is available exactly when the page has no
        apply button left. A closed posting still deserves a right verdict
        from the classifier - it is shown behind the "Kapananlar" toggle.

        Selectors and the join were copied from kariyernet_cards.parse_detail
        rather than re-derived, so the two paths could not drift into
        disagreeing about what this site's description is.

        SINCE 21.09.2026 THERE IS ONE PATH. The crawl opens no posting page
        any more and parse_detail is gone, so this is the only place a
        kariyer.net description is read - a selector that stops matching here
        leaves every new posting unclassified, and `check/description_missing`
        is the counter that will say so.
        """
        parts = response.css(
            'div[data-test="qualifications-and-job-description"] *::text'
        ).getall()
        if not parts:
            parts = response.css('[data-test="job-description"] *::text').getall()
        text = " ".join(part.strip() for part in parts if part.strip())
        return text or None
