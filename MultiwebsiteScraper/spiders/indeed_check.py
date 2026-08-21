"""
IS THIS Indeed POSTING STILL OPEN?

    python -m scrapy crawl indeed_check -a dry_run=1    verdicts only
    python -m scrapy crawl indeed_check                 write them

The expensive one - 60 of the board's 79 postings are Indeed's, and Indeed is
the site most likely to refuse us. It subclasses indeed_cards so the residential
proxy, the signed-in session, the handshake pairing and the block budget all
apply unchanged; see MultiwebsiteScraper/openings.py.

docs/sites.md:733 turned down fetching /viewjob?jk= per posting for
DESCRIPTIONS, at "roughly 75 extra requests a day". This is the same endpoint
for a different question, and the arithmetic is different: only the postings the
board can still show are checked (60, not 252), and the crawl runs every two
days - about 30 requests a day. OPENINGS_MAX_PER_SITE caps it if that stops
being true.
"""

import re

from ..openings import CLOSED, OPEN, UNKNOWN, OpeningCheckMixin
from .indeed_cards import IndeedCardsSpider

# Indeed states it outright in window._initialData. Matched with a regex rather
# than by parsing because the blob is ~400 kB of nested JSON with escaped quotes
# inside string values - the same reason extract_provider_json() brace-scans
# instead of using a regex for the card data.
EXPIRED = re.compile(r'"isJobExpired"\s*:\s*true')
NOT_EXPIRED = re.compile(r'"isJobExpired"\s*:\s*false')


class IndeedCheckSpider(OpeningCheckMixin, IndeedCardsSpider):
    name = "indeed_check"

    custom_settings = {
        **IndeedCardsSpider.custom_settings,
        "ITEM_PIPELINES": {},
    }

    def verdict(self, response):
        """
        MEASURED 21.08.2026 over 12 stored postings: 9 "isJobExpired":false,
        3 true, none ambiguous. Every page answered HTTP 200 from a residential
        address with no challenge, matching docs/sites.md:687.

        Two neighbouring fields were tried first and are NOT usable, which is
        worth writing down so nobody reaches for them again:

          - the strings "expired" and "no longer" appear on every page,
            expired or not - they are localisation entries in the bundle
            ("This job has expired on Indeed" -> "Indeed'de bu is ilaninin
            suresi doldu"), not state.
          - "expiredJobMetadataModel" was null on all 12, live and expired
            alike.

        The flag appears several times per page (the view-job model and the
        match-insights provider both carry it). They agreed everywhere, but
        the check is written so that a page carrying both readings is UNKNOWN
        rather than resolved by whichever regex ran first.
        """
        body = response.text
        says_expired = bool(EXPIRED.search(body))
        says_live = bool(NOT_EXPIRED.search(body))

        if says_expired and not says_live:
            return CLOSED
        if says_live and not says_expired:
            return OPEN
        # Neither: a challenge page, a sign-in wall, or a page shape that has
        # changed. Both: Indeed contradicting itself. Neither is evidence.
        return UNKNOWN
