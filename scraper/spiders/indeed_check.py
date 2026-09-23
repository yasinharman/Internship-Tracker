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
from datetime import datetime, timedelta

from sqlalchemy import and_, case, or_

from ..api_spider import strip_html
from ..browser_session import BrowserSession, profile_for_impersonate
from ..models import JobPost
from ..openings import CLOSED, OPEN, UNKNOWN, OpeningCheckMixin
from .indeed_cards import IndeedCardsSpider

# What "no description yet" looks like in the column: the crawl writes "N/A",
# and "" has been seen too. The same two values pipeline/classify_jobs.py waits
# on, so "this checker still owes the row a description" and "classify is
# still waiting for one" mean the same rows. A test keeps them in step.
NO_DESCRIPTION = ("N/A", "")


def lacks_description():
    return or_(
        JobPost.job_description.is_(None),
        JobPost.job_description.in_(NO_DESCRIPTION),
    )


def seen_since(moment):
    return and_(JobPost.last_seen_at.is_not(None), JobPost.last_seen_at >= moment)


def probe_order(query, seen_after):
    """
    See "A POSTING PAGE IS OPENED WHEN THERE IS SOMETHING TO LEARN" below.

    Written with the NULLs in mind. A row never seen in a search has a NULL
    last_seen_at, and `NOT (last_seen_at >= x)` is NULL for it - which a
    WHERE clause treats as false, so the row would drop out of the queue
    without anything saying so. seen_since() tests for NULL first, so its
    negation is true for that row.
    """
    missing = lacks_description()
    return (
        query
        .filter(or_(missing, ~seen_since(seen_after)))
        .order_by(
            case((missing, 0), else_=1),
            JobPost.checked_at.asc().nulls_first(),
            # Oldest row first among equals: the postings a refusal left
            # behind go ahead of the ones tonight's crawl just added.
            JobPost.id.asc(),
        )
    )

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
        on them. What was missing is kariyer.net's other half, "a posting
        page is worth a request only when there is something to learn from
        it" (kariyernet_cards, 10.09.2026). Without it, this checker opens
        EVERY open posting EVERY night - about 300 once the backlog is gone,
        against a wall measured once, at the 51st - so the wall is hit every
        night, whatever the backlog, and refusals accumulate on the address.

        So a row is opened when one of two things can be learned:

            no description yet                      -> open it, FIRST
            description, seen in a search result    -> skip it
              in the last SEEN_RECENTLY_H hours
            description, not seen lately            -> open it, after the above

        THE SKIP rests on the rule openings.py is built on: a posting in a
        search result is open, and last_seen_at is that evidence. A posting
        tonight's crawl just saw has nothing to tell the checker. One that
        has dropped out of the searches is the one that may have closed, and
        it is still opened. The cost: a posting that closes while Indeed
        still lists it in search is caught only once it drops out.

        TWELVE HOURS is "this run's crawl" with room to spare. The crawl may
        take 90 minutes, and the checker starts right after it. A checker run
        on its own the next day finds every sighting older than that and
        opens the described rows again - after the ones without a description.

        DESCRIPTION FIRST, even ahead of a row never checked. A posting that
        was checked but had no description on its page would otherwise wait
        behind every row that was never checked. It is also the order
        classify needs: it sorts nothing until the text arrives.

        One cost is accepted, not solved. A page that NEVER carries
        sanitizedJobDescription is opened first every night. None has been
        seen - 51 of 51 open pages had one on 16.09 - and check/
        description_missing in the stats would show one.
    '''
    SEEN_RECENTLY_H = 12

    def probe_query(self, query):
        seen_after = datetime.utcnow() - timedelta(hours=self.SEEN_RECENTLY_H)
        waiting = query.filter(lacks_description()).count()
        skipped = query.filter(~lacks_description(), seen_since(seen_after)).count()
        self.logger.info(
            "%s posting(s) without a description go first. %s with one were "
            "in a search result in the last %sh and are not opened again.",
            waiting, skipped, self.SEEN_RECENTLY_H,
        )
        return probe_order(query, seen_after)

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
