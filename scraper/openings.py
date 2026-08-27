"""
IS THIS POSTING STILL ON OFFER?
===============================

The board used to be an archive pretending to be a noticeboard. Nothing ever
marked a posting as gone, so three weeks of crawling piled up and the only way
to find out whether a job was still open was to click it and read a "bu ilan
yayinda degil" page. api/queries.py:40-43 admitted as much: "postings disappear
from the sites within weeks and cannot be fetched again, so we keep the data and
narrow the view instead."

This is the narrowing, done honestly: one request per posting the board can
currently show, and a verdict written to job_posts.closed_at.

WHAT COUNTS AS EVIDENCE
-----------------------
CLOSED is written ONLY on a positive, site-specific signal, measured against
the live sites on 21.08.2026 and recorded in docs/pipeline.md:

    kariyer.net     [data-test="apply-button"] is gone from the detail page
    techcareer.net  head.isCompleted is true in the detail JSON
    Indeed          "isJobExpired":true in window._initialData

Everything else - a block, a redirect, a timeout, a page shape we do not
recognise - is UNKNOWN and writes NOTHING. That asymmetry is the whole design.
A false CLOSED silently removes a real job from the board; a missed one leaves a
dead posting up for another two days, which the user finds out about by clicking
it. This project has always failed in that direction (pipeline/dedupe_jobs.py:30,
api/queries.py:69) and this is no different.

Two traps that a simpler check would fall into, both measured:

  - kariyer.net returns HTTP 200 for a closed posting. A status-code check
    finds nothing at all. The signal is inside the page.
  - Being absent from a search result is NOT evidence of closure. The searches
    are narrow (Istanbul, nine departments) and on 21.08.2026 only 14 of 36
    stored kariyer.net postings appeared in them. Absence proves nothing;
    presence proves the posting is open, which is what last_seen_at records.

WHY THREE SPIDERS AND NOT ONE SCRIPT
------------------------------------
Everything needed to reach Indeed lives in the Scrapy middlewares: the
residential proxy, the TLS handshake ladder, block detection and its budget,
the signed-in session, Playwright. A standalone script would have to
reimplement the most carefully measured part of this project.

And not one spider either: the transport flags are read per SPIDER, not per
request (IMPERSONATE_WITH_CURL, USE_PLAYWRIGHT), and the three sites want
different ones. So each checker subclasses its own crawl spider and inherits
custom_settings, the impersonation ladder, the warm-up and the session for
free. All it replaces is api_requests() - the list of urls to fetch - and
verdict().
"""

import os
from datetime import datetime

from sqlalchemy.orm import sessionmaker

from .models import JobPost, db_connect

# Compared with == rather than `is` below. They are module constants, so
# identity works today - but a checker written later that returns a bare
# "closed" literal would fail the identity test and fall through to the branch
# that REOPENS the posting, which is the worst possible way for that mistake
# to land.
OPEN = "open"
CLOSED = "closed"
UNKNOWN = "unknown"

# 0 = no ceiling, which is the right default: the set to check is the BOARD,
# not the archive - 79 rows on 21.08.2026, of which 60 are Indeed. That is
# under the ~75 requests a day docs/sites/indeed.md balked at for fetching Indeed
# descriptions, on a crawl that runs every two days.
#
# The knob exists for the day Indeed starts refusing us: set it and the oldest
# unchecked postings go first, so the cost is capped and every row still gets
# its turn eventually.
MAX_PER_SITE = int(os.getenv("OPENINGS_MAX_PER_SITE", "0"))


class OpeningCheckMixin:
    """
    Mix in FRONT of a crawl spider:

        class KariyernetCheckSpider(OpeningCheckMixin, KariyernetCardsSpider):
            name = "kariyernet_check"
            def verdict(self, response): ...

    The parent's warm-up, headers, transport and throttle all still apply;
    only the requests and what is done with them change.
    """

    # `scrapy crawl <name> -a dry_run=1` decides verdicts and prints them
    # without touching the database. Worth doing once per site before trusting
    # a new signal - the first real run on a three-week backlog will close a
    # lot of rows at once, and "Aktif Ilan" dropping by half should be a
    # thing you expected.
    dry_run = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # -a dry_run=1 arrives as the string "1".
        self.dry_run = str(self.dry_run).strip().lower() in ("1", "true", "yes", "on")
        # posting id -> verdict, filled in as responses arrive.
        self._verdicts = {}
        # id -> (url, title), for the printed summary. The ORM objects are
        # deliberately not kept: the read session below is closed before the
        # first request goes out, so nothing holds a database connection open
        # for the length of a six-minute crawl.
        self._postings = {}

    ###########################################################
    # WHAT TO CHECK                                           #
    ###########################################################
    def load_open_postings(self):
        """
        The rows the board can currently show for this site.

        Not the whole table: the classifier's `other` pile is hidden anyway,
        and including it would quadruple the request count to re-confirm
        postings nobody will ever see. Cost scales with the board.
        """
        session = sessionmaker(bind=db_connect())()
        try:
            reopened = self._reopen_seen_again(session)

            query = (
                session.query(JobPost)
                .filter(JobPost.source_site == self.site_name)
                .filter(JobPost.is_active.is_(True))
                .filter(JobPost.duplicate_of.is_(None))
                .filter(JobPost.closed_at.is_(None))
                # Never checked first, then longest ago. Only matters when
                # MAX_PER_SITE is set, but it makes the cap fair rather than
                # arbitrary. NULLS FIRST is spelled out because Postgres sorts
                # them LAST on an ascending order by, which is the opposite of
                # what "never checked" should mean here.
                .order_by(JobPost.checked_at.asc().nulls_first())
            )
            if MAX_PER_SITE > 0:
                query = query.limit(MAX_PER_SITE)

            rows = [
                {"id": row.id, "url": row.url, "job_title": row.job_title}
                for row in query.all()
            ]
        finally:
            session.close()

        self.logger.info(
            "%s: %s posting(s) to check%s%s",
            self.site_name,
            len(rows),
            f", {reopened} reopened" if reopened else "",
            " (DRY RUN - nothing will be written)" if self.dry_run else "",
        )
        return rows

    def _reopen_seen_again(self, session):
        """
        Undo a close that a later crawl contradicted.

        If a spider found this url in a search result AFTER we marked it
        closed, the posting is open and our verdict was wrong - a transient
        page shape, a block that slipped past the UNKNOWN guard, or the
        employer reposting. This is what makes a false close self-healing
        rather than permanent, and it is the only reason last_seen_at exists.

        One direction only. `last_seen_at` going stale is not evidence of
        anything; see the module docstring.
        """
        stale = (
            session.query(JobPost)
            .filter(JobPost.source_site == self.site_name)
            .filter(JobPost.closed_at.is_not(None))
            .filter(JobPost.last_seen_at.is_not(None))
            .filter(JobPost.last_seen_at > JobPost.closed_at)
            .all()
        )
        for posting in stale:
            self.logger.info(
                "reopening id=%s - seen in a search result after it was closed: %s",
                posting.id, posting.job_title,
            )
            if not self.dry_run:
                posting.closed_at = None
        if stale and not self.dry_run:
            session.commit()
        return len(stale)

    ###########################################################
    # THE REQUESTS                                            #
    ###########################################################
    def api_requests(self):
        """
        Replaces the crawl spider's search requests with one probe per row.

        Hooked here rather than at start_requests so the parent's warm-up
        still runs first - techcareer needs it for the buildId, Indeed needs
        it to make its Referer truthful.
        """
        for posting in self.load_open_postings():
            self._postings[posting["id"]] = posting
            request = self.probe_request(posting)
            if request is not None:
                yield request

    def probe_request(self, posting):
        """
        One request for one posting. Override where the url stored in the
        database is not the one worth fetching (techcareer).

        dont_filter because two postings can legitimately share a url after a
        site redirect, and losing one to the dupe filter would leave it
        unchecked forever rather than merely unresolved.
        """
        return self.document_request(
            posting["url"],
            callback=self.parse_check,
            meta={"posting_id": posting["id"]},
            dont_filter=True,
        )

    def parse_check(self, response):
        posting_id = response.meta["posting_id"]
        try:
            outcome = self.verdict(response)
        except Exception as error:
            # A parse error is not evidence that a job closed.
            self.logger.warning("id=%s verdict failed: %s", posting_id, error)
            outcome = UNKNOWN

        self._verdicts[posting_id] = outcome
        self.logger.debug("id=%s -> %s (%s)", posting_id, outcome, response.url)

    def verdict(self, response):
        """Override: OPEN, CLOSED or UNKNOWN. Default refuses to guess."""
        return UNKNOWN

    ###########################################################
    # WRITE ONCE, AT THE END                                  #
    ###########################################################
    def closed(self, reason):
        try:
            self._write_verdicts()
        finally:
            # The parent reports the item count to main.py; keep that working.
            super().closed(reason)

    def _write_verdicts(self):
        counts = {OPEN: 0, CLOSED: 0, UNKNOWN: 0}
        for outcome in self._verdicts.values():
            counts[outcome] = counts.get(outcome, 0) + 1

        # A posting we never got a response for is not UNKNOWN-and-checked, it
        # is unattempted - the crawl was cut short by the block budget or the
        # timeout. Counted separately so the summary does not read as "we
        # looked at everything and could not tell".
        unanswered = len(self._postings) - len(self._verdicts)

        # Plain strings, never ORM objects. session.commit() expires every
        # attribute and session.close() detaches the instance, so reading
        # posting.job_title afterwards re-queries on a closed session and
        # raises DetachedInstanceError - which is exactly what happened on the
        # first real run, after the commit had already succeeded. The write
        # was fine and the log was what fell over.
        newly_closed = []
        reopened = []

        if self.dry_run:
            newly_closed = [
                self._postings[pid]["job_title"]
                for pid, outcome in self._verdicts.items()
                if outcome == CLOSED
            ]
        elif self._verdicts:
            now = datetime.utcnow()
            session = sessionmaker(bind=db_connect())()
            try:
                rows = (
                    session.query(JobPost)
                    .filter(JobPost.id.in_(list(self._verdicts)))
                    .all()
                )
                for posting in rows:
                    outcome = self._verdicts[posting.id]
                    if outcome == UNKNOWN:
                        # Not even checked_at: a probe that could not tell is
                        # not a check, and stamping it would hide a site that
                        # has started refusing us behind a fresh timestamp.
                        continue
                    if outcome == CLOSED:
                        if posting.closed_at is None:
                            posting.closed_at = now
                            newly_closed.append(posting.job_title)
                    elif posting.closed_at is not None:
                        # The site says it is open after all. Rare - the crawl
                        # normally gets here first via last_seen_at - but a
                        # reposted job lands exactly here.
                        posting.closed_at = None
                        reopened.append(posting.job_title)
                    posting.checked_at = now
                session.commit()
            finally:
                session.close()

        for title in newly_closed:
            self.logger.info("closed: %s", title)
        for title in reopened:
            self.logger.info("reopened (site says it is open again): %s", title)

        self.logger.info(
            "%s: %s open, %s closed, %s inconclusive, %s unanswered%s",
            self.site_name,
            counts[OPEN], counts[CLOSED], counts[UNKNOWN], unanswered,
            " (DRY RUN - nothing written)" if self.dry_run else "",
        )

        # main.py reads item_scraped_count as "did this spider accomplish
        # anything". A checker scrapes no items, so lend it the number that
        # means the same thing here: verdicts we could actually act on. Zero
        # then means what it means for a crawl spider - the site refused us.
        try:
            self.crawler.stats.set_value(
                "item_scraped_count", counts[OPEN] + counts[CLOSED]
            )
        except Exception:
            pass
