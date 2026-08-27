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
