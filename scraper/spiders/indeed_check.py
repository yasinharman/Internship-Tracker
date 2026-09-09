"""
IS THIS Indeed POSTING STILL OPEN?

    python -m scrapy crawl indeed_check -a dry_run=1    verdicts only
    python -m scrapy crawl indeed_check                 write them

The expensive one - 60 of the board's 79 postings are Indeed's, and Indeed is
the site most likely to refuse us. It subclasses indeed_cards so the residential
proxy, the signed-in session, the handshake pairing and the block budget all
apply unchanged; see scraper/openings.py.

docs/sites/indeed.md, "The first investigation" > "Description", turned down
fetching /viewjob?jk= per posting for DESCRIPTIONS, at "roughly 75 extra
requests a day". This is the same endpoint for a different question, and the
arithmetic is different: only the postings the
board can still show are checked (60, not 252), and the crawl runs every two
days - about 30 requests a day. OPENINGS_MAX_PER_SITE caps it if that stops
being true.
"""

import json
import re

from ..api_spider import strip_html
from ..openings import CLOSED, OPEN, UNKNOWN, OpeningCheckMixin
from .indeed_cards import IndeedCardsSpider

# Indeed states it outright in window._initialData. Matched with a regex rather
# than by parsing because the blob is ~400 kB of nested JSON with escaped quotes
# inside string values - the same reason extract_provider_json() brace-scans
# instead of using a regex for the card data.
# The description, out of the same ~290 kB blob and for the same reason as
# EXPIRED below: brace-scanning it to parse properly is what
# extract_provider_json() has to do for the card data, and this is one string.
#
# The capture is a JSON string literal - `(?:[^"\\]|\\.)*` walks escaped
# quotes correctly - and json.loads puts it back through the decoder rather
# than unescaping by hand, because the value arrives full of \u003Cbr> and
# would otherwise need every escape re-implemented here.
DESCRIPTION = re.compile(r'"sanitizedJobDescription"\s*:\s*"((?:[^"\\]|\\.)*)"')

EXPIRED = re.compile(r'"isJobExpired"\s*:\s*true')
NOT_EXPIRED = re.compile(r'"isJobExpired"\s*:\s*false')


class IndeedCheckSpider(OpeningCheckMixin, IndeedCardsSpider):
    name = "indeed_check"

    custom_settings = {
        **IndeedCardsSpider.custom_settings,
        "ITEM_PIPELINES": {},
    }

    def description(self, response):
        """
        The description this file's own header says was turned down.

        docs/sites/indeed.md refused fetching /viewjob?jk= per posting FOR
        descriptions at "roughly 75 extra requests a day". That refusal still
        stands for the crawl - and it is moot here, because this checker
        fetches that exact url anyway to ask whether the posting is still
        open. The header above already called it "the same endpoint for a
        different question"; this is the other question, answered for free.

        Measured 09.09.2026: `sanitizedJobDescription` appears exactly once in
        a 290 kB body and holds the full text. Note the asymmetry with the
        crawl - the SEARCH record carries only `snippet`, an excerpt, which is
        why every stored Indeed row reads "N/A" or a fragment. The full text
        was never on the page the crawl looks at.
        """
        match = DESCRIPTION.search(response.text)
        if not match:
            return None
        try:
            text = json.loads(f'"{match.group(1)}"')
        except ValueError:
            # A truncated or re-encoded blob is not worth guessing at.
            return None
        return strip_html(text) or None

    def verdict(self, response):
        """
        MEASURED 21.08.2026 over 12 stored postings: 9 "isJobExpired":false,
        3 true, none ambiguous. Every page answered HTTP 200 from a residential
        address with no challenge, matching the note at the top of
        docs/sites/indeed.md.

        (Both citations here used to be line numbers into a single 1331-line
        docs/sites.md. By the time that file was split on 27.08.2026 they had
        drifted onto unrelated paragraphs, which is the argument for naming a
        section instead.)

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
