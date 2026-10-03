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
import os
import re

from ..api_spider import strip_html
from ..browser_session import BrowserSession, profile_for_impersonate
from ..openings import CLOSED, OPEN, UNKNOWN, OpeningCheckMixin
from .indeed_cards import IndeedCardsSpider

# "No description yet" and "seen in a search since" moved to
# scraper/openings.py on 03.10.2026, together with the queue rule that uses
# them. They were written here on 16.09.2026 because Indeed was the only site
# whose checker owed its postings a description; since 21.09 no crawl opens a
# posting page, so every site's checker does.
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

# The company's logo, in the same blob as the description. Measured
# 23.09.2026 on a saved /viewjob page: the posting carries
# "logoUrl":"https://..." next to "logoAltText":"<company> logo", and null
# where the employer has no logo - which is honest and means the board keeps
# its initials rather than borrowing somebody else's mark.
LOGO_URL = re.compile(r'"logoUrl"\s*:\s*"(https?://[^"]+)"')

EXPIRED = re.compile(r'"isJobExpired"\s*:\s*true')
NOT_EXPIRED = re.compile(r'"isJobExpired"\s*:\s*false')


class IndeedCheckSpider(OpeningCheckMixin, IndeedCardsSpider):
    name = "indeed_check"

    # NOT the pinned one, and not signed in. The parent crawls with Harman's
    # account from a single fixed address; this opens 242 posting pages, which
    # needs the rotation - and needs no account, since an anonymous /viewjob
    # was served 171 times from the pool on 23.09.2026. Inheriting the pin
    # would both rotate the session and spend its address on logged-out
    # traffic.
    USES_PINNED_ADDRESS = False

    custom_settings = {
        **IndeedCardsSpider.custom_settings,
        "ITEM_PIPELINES": {},
    }

    #####################################################################
    # FROM THE POOL: curl_cffi, STRAIGHT TO /viewjob - 22.09.2026       #
    #####################################################################
    '''
        The owner: "indeed check in zaten havuzda olması gerekiyor 1 ip den
        500 tane ilana istek atamayız".

        Through the pool, this checker as it stands - headless Chromium, a
        warm-up on the home page first - was refused on that warm-up by four
        European addresses in a row (docs/proxies.md, "indeed_check through
        the pool"). The same morning, two of the pool's addresses had been
        served by curl_cffi with safari184, straight to /jobs and to an
        anonymous /viewjob.

        INDEED_CHECK_VIA_CURL=1 makes this checker that client:
          - curl_cffi instead of the browser (CurlImpersonateMiddleware);
          - no warm-up. That also means no session: the exported cookies
            only ever ride on the warm-up (api_spider.warmup_cookies), and
            a posting request carries no Referer (Sec-Fetch-Site: none), the
            shape the anonymous /viewjob was served in.
        With no session, the handshake ladder goes back to the anonymous
        order (safari184 first) even if INDEED_COOKIES is set - that
        reordering is for carrying a session, and this sends none.
        INDEED_IMPERSONATE is left for experiments; it pins indeed_cards too.

        curl_cffi blocks the reactor for each request. This spider runs one
        request at a time with a long delay anyway, so nothing is lost.
    '''
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if os.getenv("INDEED_CHECK_VIA_CURL", "").strip().lower() in ("1", "true", "yes", "on"):
            self.USE_PLAYWRIGHT = False
            self.IMPERSONATE_WITH_CURL = True
            self.warmup_url = None
            if not self._impersonate_pinned:
                self.impersonate_candidates = list(self.IMPERSONATE_CANDIDATES)
                self.session = BrowserSession(
                    profile=profile_for_impersonate(self.impersonate_candidates[0]),
                    origin=self.origin,
                )
            self.logger.info(
                "INDEED_CHECK_VIA_CURL: curl_cffi (%s), no warm-up, no session",
                self.impersonate_candidates[0],
            )

    ###################################################################
    # A POSTING PAGE IS OPENED WHEN THERE IS SOMETHING TO LEARN       #
    ###################################################################
    '''
        MEASURED 16.09.2026 (docs/sites/indeed.md, "Refused on the detail
        pages"). This checker opened 51 of 296 postings, and then Cloudflare
        refused every /viewjob request that followed. The address had sent
        145 requests to Indeed by then. 245 postings were left without a
        description, and classify waits for one.

        The refused rows were already safe. A probe that gets no answer does
        not stamp checked_at, and unchecked rows go first, so tomorrow starts
        on them. What was missing is kariyernet_cards' other half, "a posting
        page is worth a request only when there is something to learn from
        it" (10.09.2026). Without it, this checker opens EVERY open posting
        EVERY night - about 300 once the backlog is gone, against a wall
        measured once, at the 51st - so the wall is hit every night, whatever
        the backlog, and refusals accumulate on the address.

        THE RULE MOVED TO scraper/openings.py ON 03.10.2026 and is every
        site's now rather than Indeed's. It also stopped being measured in
        hours: a described posting is skipped while the searches keep finding
        it, and is opened once it has been missing from three COMPLETE scans
        of the site. The twelve-hour window this file used was a stand-in for
        "this run's crawl", and it was wrong in the one case that matters - a
        run that never happened. Ten days without one (23.09 to 03.10.2026)
        would have made every posting look twelve-hours-stale and spent 400
        requests re-confirming rows nothing had touched.

        The ordering it used - no description first, then never checked, then
        longest ago - moved with it and is now every checker's default.
    '''

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
        crawl - the SEARCH record carries only `snippet`, an excerpt. Since
        21.09.2026 the crawl stores "N/A" rather than that excerpt (see
        indeed_cards), so this is the only writer of an Indeed description.
        The full text was never on the page the crawl looks at.
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

    def logo(self, response):
        """
        The employer's logo, off the page this checker fetched anyway.

        Indeed's SEARCH records carry no logo at all (docs/sites/indeed.md,
        "THERE IS NO COMPANY LOGO IN THE CARD RECORDS"), which is why every
        Indeed posting arrived without one and why pipeline/company_logos.py
        exists. The POSTING page has the field, and this checker opens every
        posting page anyway - so it costs nothing.
        """
        match = LOGO_URL.search(response.text)
        return match.group(1).replace("\\u002F", "/") if match else None

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
        #
        # Said out loud since 22.09.2026: the first curl_cffi page from the
        # pool came back 200 with its description and no verdict, and nothing
        # in the log told "both" from "neither" or showed how the flag was
        # written.
        first = body.find("isJobExpired")
        self.logger.info(
            "%s: no verdict - isJobExpired appears %s time(s), %s read as "
            "true, %s as false; first: %r",
            response.url, body.count("isJobExpired"), len(EXPIRED.findall(body)),
            len(NOT_EXPIRED.findall(body)),
            body[max(first - 20, 0):first + 40] if first >= 0 else None,
        )
        return UNKNOWN
