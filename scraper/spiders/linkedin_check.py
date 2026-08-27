"""
IS THIS LINKEDIN POSTING STILL OPEN?

    python -m scrapy crawl linkedin_check -a dry_run=1    verdicts only
    python -m scrapy crawl linkedin_check                 write them

Subclasses linkedin_cards, so the burner session, the browser profile, the
throttle and the block budget all apply unchanged - see
scraper/openings.py for why each checker is a spider rather than a
script.

THE SIGNAL IS NOT MEASURED YET, AND THIS SPIDER IS WRITTEN AROUND THAT
======================================================================
Every other checker in this project quotes a measurement: kariyer.net's
missing apply-button over four postings, techcareer's `isCompleted` over two,
Indeed's `"isJobExpired":true` over twelve. This one cannot yet. On 26.08.2026
LinkedIn was crawled for the first time and the database held no LinkedIn
posting old enough to have closed, so there was nothing to read a closed page
off. Guessing the marker and shipping it would be the one mistake openings.py
exists to prevent: a false CLOSED silently removes a real job from the board.

So the asymmetry is turned up rather than down:

  * CLOSED requires the page to say so, in words, in a place we recognise.
  * OPEN requires the apply affordance to be there.
  * ANYTHING ELSE is UNKNOWN and writes nothing at all - not even checked_at,
    so a posting that could not be read stays first in line for next time.

Until the first real closure comes through, the expected outcome of a run is
"N open, 0 closed, M inconclusive", and that is a correct result rather than a
broken one. When one does close, `linkedin/closed_marker_seen` in the stats is
the confirmation, and the marker below should then be recorded in
docs/sites/linkedin.md with the id and the date - the way the other three are.

WHY IT NEEDS ITS OWN page_actions
---------------------------------
The parent's hook waits for job CARDS, which a detail page does not have, and
returns immediately when the request carries no search route. Measured
26.08.2026: read that way, a job page comes back with a correct <title> and a
body that has none of the posting in it - the application renders the detail
pane a second or two after domcontentloaded. A verdict taken from that page
would be UNKNOWN every single time, which is safe and also useless.
"""

from ..openings import CLOSED, OPEN, UNKNOWN, OpeningCheckMixin
from .linkedin_cards import LinkedinCardsSpider

# The apply affordance. Class names on this page are build-hashed
# ("_59162b76", "b424a163"), so they are worthless as anchors; the aria-label
# is user-facing accessibility text and is what was actually measured present
# on a live posting on 26.08.2026.
APPLY_MARKERS = (
    'aria-label="Easy Apply to this job"',
    'aria-label="Apply to this job"',
)

# What a closed posting is expected to say. UNMEASURED - see the module
# docstring. English and Turkish because the burner account's interface
# language can change without anyone touching this file.
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
    DETAIL_MARKERS = (
        '[aria-label*="Apply to this job"], '
        '[data-testid="expandable-text-box"]'
    )

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
        try:
            page.wait_for_selector(self.DETAIL_MARKERS, timeout=self.DETAIL_WAIT_MS)
        except Exception:
            self.crawler.stats.inc_value("linkedin/detail_never_rendered")

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
            return CLOSED

        if any(marker.lower() in body for marker in APPLY_MARKERS):
            return OPEN

        # No apply button and no closing statement. That is not a closed
        # posting - it is a page we did not read: a wall, a redirect, or the
        # detail pane never arriving. openings.py writes nothing for this.
        if not any(marker in body for marker in RENDERED_MARKERS):
            self.crawler.stats.inc_value("linkedin/unreadable_detail")
        return UNKNOWN
