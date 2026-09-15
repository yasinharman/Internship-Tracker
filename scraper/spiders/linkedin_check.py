"""
IS THIS LINKEDIN POSTING STILL OPEN?

    python -m scrapy crawl linkedin_check -a dry_run=1    verdicts only
    python -m scrapy crawl linkedin_check                 write them

Subclasses linkedin_cards, so the burner session, the browser profile, the
throttle and the block budget all apply unchanged - see
scraper/openings.py for why each checker is a spider rather than a
script.

THE SIGNAL WAS A GUESS FOR A DAY, AND THIS SPIDER IS STILL WRITTEN AROUND THAT
=============================================================================
Every other checker in this project quotes a measurement: kariyer.net's
missing apply-button over four postings, techcareer's `isCompleted` over two,
Indeed's `"isJobExpired":true` over twelve. This one could not, at first: on
26.08.2026 LinkedIn was crawled for the first time and the database held no
posting old enough to have closed. Rather than guess a marker and ship it -
the one mistake openings.py exists to prevent, since a false CLOSED silently
removes a real job from the board - it was written to say UNKNOWN until a real
closure proved otherwise.

MEASURED 27.08.2026. id=59, "Machine Learning Analyst (Remote)",
jobs/view/4459636725/, in a run of 77 that came back 76 open / 1 closed /
0 inconclusive / 0 unanswered. Fetched straight afterwards to see which of the
four guessed phrases actually matched:

    <... aria-label="Error"> No longer accepting applications

English, under locale="tr-TR". The closed page carried no apply affordance of
any kind, so both halves of the verdict agreed. Full write-up in
docs/sites/linkedin.md.

The asymmetry stays exactly as turned up as it was:

  * CLOSED requires the page to say so, in words, in a place we recognise.
  * OPEN requires the apply affordance to be there.
  * ANYTHING ELSE is UNKNOWN and writes nothing at all - not even checked_at,
    so a posting that could not be read stays first in line for next time.

`linkedin/closed_marker_seen` in the stats counts these. Most postings on a
board crawled the same morning are still open, so "N open, 1 closed, 0
inconclusive" is the expected shape of a result rather than a sign of
something wrong.

WHY IT NEEDS ITS OWN page_actions
---------------------------------
The parent's hook waits for job CARDS, which a detail page does not have, and
returns immediately when the request carries no search route. Measured
26.08.2026: read that way, a job page comes back with a correct <title> and a
body that has none of the posting in it - the application renders the detail
pane a second or two after domcontentloaded. A verdict taken from that page
would be UNKNOWN every single time, which is safe and also useless.
"""

import os
import time

from ..openings import CLOSED, OPEN, UNKNOWN, OpeningCheckMixin
from .linkedin_cards import LinkedinCardsSpider

# The apply affordance. Class names on this page are build-hashed
# ("_59162b76", "b424a163"), so they are worthless as anchors; the aria-label
# is user-facing accessibility text and is what was actually measured present
# on a live posting on 26.08.2026.
# MEASURED 27.08.2026 over three live postings: LinkedIn has THREE of these,
# not two, and the third is not a variation on the wording - it is what a
# posting that applies on the employer's own site says instead.
#
#     Easy Apply to this job     apply inside LinkedIn
#     Apply on company website   apply elsewhere - just as open
#
# Missing the third one cost half the board. On the run that found it, four
# of eight postings came back UNKNOWN, and the tell was in the phase log: the
# four that resolved matched the apply selector in 0.0s, the four that did not
# spent 0.9s falling through to the description box. All four were open; none
# of them said anything about being closed. "Apply to this job" is kept as
# well - it was measured 26.08.2026 and costs nothing.
APPLY_MARKERS = (
    'aria-label="Easy Apply to this job"',
    'aria-label="Apply on company website"',
    'aria-label="Apply to this job"',
)

# What a closed posting says. The FIRST entry is MEASURED - 27.08.2026, see
# the module docstring - and the page renders it inside an element carrying
# aria-label="Error". The three Turkish ones have never been observed: the
# page came back in English under locale="tr-TR". They stay because the
# burner account's interface language can change without anyone touching
# this file, and a phrase that never matches costs nothing.
CLOSED_MARKERS = (
    "no longer accepting applications",
    "artık başvuru kabul etmiyor",
    "bu ilan artık başvuru almıyor",
    "this job is no longer available",
)

# Something that proves we are looking at a rendered job page at all, so that
# "nothing matched" can be told apart from "nothing rendered".
RENDERED_MARKERS = ("about the job", "işle ilgili", "about the company")


class LinkedinCheckSpider(OpeningCheckMixin, LinkedinCardsSpider):
    name = "linkedin_check"

    custom_settings = {
        **LinkedinCardsSpider.custom_settings,
        "ITEM_PIPELINES": {},
        # READ EACH PAGE BEFORE FETCHING THE NEXT ONE - 15.09.2026.
        #
        # openings.py writes verdicts every WRITE_EVERY so that a run cut
        # short keeps what it paid for. On LinkedIn that never happened on
        # time: in the 15.09 full run 57 job pages were downloaded before a
        # single verdict was decided, and the first 22 then arrived at once.
        # Seven minutes in, nothing had been written.
        #
        # Why: the probes are yielded from the warm-up's callback, and
        # PlaywrightMiddleware blocks the reactor for every page. Scrapy only
        # stops fetching to run callbacks when the responses waiting for them
        # add up to SCRAPER_SLOT_MAX_ACTIVE_SIZE, 5 MB by default. Reproduced
        # with a toy spider and no network: 60 requests from a callback and a
        # blocking middleware -
        #
        #     5 MB, 380 kB pages   first callback after 14 fetches, then 12 at a time
        #     5 MB,  10 kB pages   first callback after ALL 60
        #     1 B,  either size    first callback after 2, then one per fetch
        #
        # So 1 byte: the engine backs off until the page in hand has been
        # read, which costs nothing here - CONCURRENT_REQUESTS is 1 and the
        # middleware is serial anyway - and holds one page in memory instead
        # of dozens.
        "SCRAPER_SLOT_MAX_ACTIVE_SIZE": 1,
    }

    # The detail pane, not the results list.
    DETAIL_WAIT_MS = 15000

    # Something only the POSTING has. `h2` was tried first and is useless:
    # LinkedIn's page chrome carries its own headings - the notifications
    # tray's "0 notifications" is an h2 - so waiting for one returned in 0.0s
    # on a page whose job pane had not rendered at all (measured 26.08.2026).
    #
    # The apply control is the obvious anchor but cannot be the only one: a
    # CLOSED posting has no apply button, and that is precisely the page this
    # checker exists to read. The description box is present on both.
    #
    # BUILT FROM APPLY_MARKERS, 15.09.2026, rather than written out a second
    # time. It used to be a hand-written copy that said
    # `[aria-label*="Apply to this job"]` - which covers "Easy Apply to this
    # job" and "Apply to this job" as substrings and NOT "Apply on company
    # website", the third form measured on 27.08.2026. The verdict learned
    # that marker; this wait never did. So a company-website posting whose
    # page carried no description box sat out the whole DETAIL_WAIT_MS and
    # was counted as `linkedin/detail_never_rendered` on a page that had
    # rendered perfectly well. tests/test_linkedin_check.py keeps the two
    # lists from drifting apart again.
    DESCRIPTION_BOX = '[data-testid="expandable-text-box"]'
    DETAIL_MARKERS = ", ".join(
        [f"[{marker}]" for marker in APPLY_MARKERS] + [DESCRIPTION_BOX]
    )

    ###################################################################
    # THE WAIT ENDS ON THE FIRST MARKER, NOT ON THE DESCRIPTION       #
    ###################################################################
    '''
        DETAIL_MARKERS is "any of these", so the wait returns the moment the
        apply button exists. Nothing says the description box has rendered
        by then. On 09.09.2026 23 of 40 open pages carried the box and 17 did
        not, with zero detail_never_rendered - and two explanations fit that
        equally well:

          1. a short description is rendered without the EXPANDABLE wrapper,
             so those pages will never have it (the one docs/sites/linkedin.md
             wrote down), or
          2. the box was coming, and content() was taken before it arrived.

        Since 12.09.2026 a row without a description is never classified, so
        this is no longer a nicety. The two are told apart here without a
        single extra request: when the first marker was not the box, wait a
        little longer for the box specifically and count what happened.

            linkedin/description_box_late     it came - explanation 2, and
                                              this wait is the fix
            linkedin/description_box_absent   it never came - explanation 1,
                                              and a second container has to
                                              be found (LINKEDIN_DUMP_DIR)

        Five seconds costs nothing on most pages: the throttle measures its
        8s (0.5x-1.5x) from the START of the previous fetch, and a detail
        page measured 0.7s goto + 0.9s actions on 28.08.2026, so a fetch that
        waits five more seconds usually still finishes inside the delay it
        would have waited anyway.
    '''
    DESCRIPTION_LATE_WAIT_MS = 5000

    ###################################################################
    # HOW LONG ONE POSTING TAKES, FOR THE CEILING IN main.py          #
    ###################################################################
    '''
        MEASURED 28.08.2026, full run: 83 postings in 680s, 8.2s each. The
        throttle waits 0.5x-1.5x DOWNLOAD_DELAY from the start of the
        previous fetch, and a detail page takes ~1.7s to fetch (goto 0.7,
        actions 0.9, content 0.1), so the slowest ordinary posting is the
        1.5x bound, 12s, plus that fetch and Scrapy's own turn: 14s.

        main.py's SPIDER_TIMEOUTS["linkedin_check"] is sized against this
        number, and tests/test_linkedin_check.py checks the sum.
    '''
    WORST_S_PER_POSTING = 14

    def load_open_postings(self):
        """
        The parent's rows, plus a warning when the time limit cannot fit them.

        Since 12.09.2026 a LinkedIn row is not classified until this checker
        has brought its description, so a run that stops at its ceiling
        leaves the rest of the board unsorted until a later run. Not lost -
        the next run starts from the oldest unchecked row - but it should be
        said at the start, not discovered at the end.
        """
        rows = super().load_open_postings()
        limit = self.crawler.settings.getint("CLOSESPIDER_TIMEOUT", 0)
        if limit and len(rows) * self.WORST_S_PER_POSTING > limit:
            self.logger.warning(
                "%s posting(s) to check at up to %ss each will not all fit in "
                "the %s min time limit - roughly %s will. Raise "
                "LINKEDIN_CHECK_TIMEOUT if LinkedIn is not refusing us.",
                len(rows), self.WORST_S_PER_POSTING, limit // 60,
                limit // self.WORST_S_PER_POSTING,
            )
        return rows

    def page_actions(self, page, request):
        """
        Wait for the posting itself, not for search cards.

        The parent's hook waits for job CARDS and returns immediately when a
        request carries no search route, so without this a job page is read
        the instant its shell arrives - correct <title>, none of the posting.
        Every verdict would be UNKNOWN: safe, and useless.

        Failing to find the marker is not an error. verdict() treats a page it
        cannot recognise as UNKNOWN and openings.py writes nothing for it,
        which is the behaviour we want when a page did not load.
        """
        if request.meta.get("route"):
            return super().page_actions(page, request)
        # The warm-up (the feed) carries no posting_id and has no job pane to
        # wait for. It used to go through the wait below anyway, and got out
        # of it in 0.1s on 28.08.2026 only because something on the feed
        # happened to match DETAIL_MARKERS - luck, not design, and a feed
        # without that element would have cost the full DETAIL_WAIT_MS.
        if request.meta.get("posting_id") is None:
            return
        try:
            page.wait_for_selector(self.DETAIL_MARKERS, timeout=self.DETAIL_WAIT_MS)
        except Exception:
            self.crawler.stats.inc_value("linkedin/detail_never_rendered")
            return

        # See DESCRIPTION_LATE_WAIT_MS. wait_for_selector rather than
        # locator.count(): it takes a timeout, and count() is one of the calls
        # that waited forever on a wedged renderer in August.
        started = time.monotonic()
        try:
            page.wait_for_selector(
                self.DESCRIPTION_BOX, timeout=self.DESCRIPTION_LATE_WAIT_MS,
            )
        except Exception:
            self.crawler.stats.inc_value("linkedin/description_box_absent")
            return
        waited = time.monotonic() - started
        # Already there when the first wait returned: nothing to count.
        if waited > 0.25:
            self.crawler.stats.inc_value("linkedin/description_box_late")
            self.logger.debug(
                "description box arrived %.1fs after the page rendered: %s",
                waited, request.url[:100],
            )

    def description(self, response):
        """
        The description box - the same element page_actions already waits for.

        DETAIL_MARKERS gates the render on this selector, so a page that
        rendered enough to answer the verdict rendered enough to answer this
        too, and a page that did not is UNKNOWN either way. No extra request:
        linkedin_cards refuses the description because it would cost one per
        posting, and this page is downloaded regardless to ask whether the job
        is still open.

        Measured 09.09.2026 over two postings: 1462 and 3652 characters of
        real text. The three class-based selectors tried alongside it -
        .jobs-description__content, .jobs-box__html-content, #job-details -
        matched NOTHING, which is what this site's notes predict: LinkedIn
        hashes its class names per build, and data-testid is one of the two
        anchors that survive (docs/sites/linkedin.md).
        """
        node = response.css(self.DESCRIPTION_BOX)
        if not node:
            self._dump_page_without_description(response)
            return None
        text = " ".join(t.strip() for t in node.css("*::text").getall() if t.strip())
        return text or None

    ###################################################################
    # KEEP THE PAGES NOBODY COULD READ, TO LOOK AT BY HAND             #
    ###################################################################
    # `LINKEDIN_DUMP_DIR=/some/dir` writes the html of two kinds of page, up
    # to LINKEDIN_DUMP_MAX between them. Off unless set. No request is added:
    # these are pages the run has already downloaded, and reading them is the
    # only honest way to find a selector this file does not have yet.
    #
    #   <id>-no-description.html   OPEN, but no description box. 15.09.2026:
    #                              one page of 535 - the lower column had not
    #                              rendered after the extra 5s. Walls and
    #                              closed pages are not kept.
    #   <id>-unknown.html          RENDERED, but no apply control and no
    #                              closing words. 15.09.2026: one page of 535,
    #                              id=1042 "Beta Tester - Turkiye", whose
    #                              description did arrive - so the page was
    #                              there and offered some way to apply that
    #                              APPLY_MARKERS does not know. Not kept that
    #                              run, which is why this kind was added.
    def _keep_page(self, response, why):
        folder = (os.getenv("LINKEDIN_DUMP_DIR") or "").strip()
        if not folder:
            return
        limit = int(os.getenv("LINKEDIN_DUMP_MAX", "10"))
        if self.crawler.stats.get_value("linkedin/pages_dumped", 0) >= limit:
            return
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"{response.meta.get('posting_id')}-{why}.html")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(response.text)
        self.crawler.stats.inc_value("linkedin/pages_dumped")
        self.logger.info("%s - page kept at %s (%s)", why, path, response.url)

    def _dump_page_without_description(self, response):
        body = response.text.lower()
        if any(marker.lower() in body for marker in APPLY_MARKERS):
            self._keep_page(response, "no-description")

    def verdict(self, response):
        body = response.text.lower()

        if any(marker in body for marker in CLOSED_MARKERS):
            # Worth a line of its own: this is the first time the marker has
            # ever fired, and it is the measurement the module docstring says
            # is missing. Record the id and put it in docs/sites/linkedin.md.
            self.logger.info(
                "closed-marker matched on %s - this is the evidence the "
                "checker was written without; record it in docs/sites/linkedin.md.",
                response.url[:100],
            )
            self.crawler.stats.inc_value("linkedin/closed_marker_seen")
            # The marker is searched for in the WHOLE body, and a job page
            # carries more than its own posting - other postings, in the
            # rail. 12 closures on 28.08.2026 were hand-checked 3 of 12 and
            # none of those three had an apply control, so this has not been
            # seen. Counted, not acted on: the verdict stays what it was
            # until a run shows this firing, and the url says which page to
            # open.
            if any(marker.lower() in body for marker in APPLY_MARKERS):
                self.crawler.stats.inc_value("linkedin/closed_marker_beside_apply")
                self.logger.warning(
                    "closed-marker AND an apply control on the same page - "
                    "open it and see which one is about THIS posting: %s",
                    response.url[:100],
                )
            return CLOSED

        if any(marker.lower() in body for marker in APPLY_MARKERS):
            return OPEN

        # No apply button and no closing statement. That is not a closed
        # posting - it is a page we did not read: a wall, a redirect, or the
        # detail pane never arriving. openings.py writes nothing for this.
        if not any(marker in body for marker in RENDERED_MARKERS):
            self.crawler.stats.inc_value("linkedin/unreadable_detail")
        else:
            # Rendered, and still neither open nor closed: the interesting
            # kind. See _keep_page.
            self._keep_page(response, "unknown")
        return UNKNOWN
