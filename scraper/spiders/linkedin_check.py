"""
IS THIS LINKEDIN POSTING STILL OPEN? - AS A GUEST
=================================================

    python -m scrapy crawl linkedin_check -a dry_run=1    verdicts only
    python -m scrapy crawl linkedin_check                 write them

Subclasses linkedin_cards, so the guest rules come along: no session, only
from the pool, one request at a time, 8 s apart. See scraper/openings.py for
why each checker is a spider.

One request per posting: `/jobs/view/<id>/`, the page LinkedIn serves whole
to a visitor with no account (docs/sites/linkedin.md, 22.09.2026). The
verdict and the description come out of the same response.

WHAT THE GUEST PAGE SAYS - MEASURED 22.09.2026
----------------------------------------------
Two postings, read as a guest through the pool:

    open    4439226311   apply link  data-tracking-control-name=
                                     "public_jobs_apply-link-onsite"   x2
                         closed-job classes                          0
    closed  4460320033   apply link                                  0
                         closed-job__flavor--closed etc.             5
                         "Artık başvuru kabul etmiyor"
                         (4460320033 was called closed by the burner-era
                         checker on 02.09.2026; still closed)

The description, `div.show-more-less-html__markup`, is on both.

The asymmetry every checker in this project keeps:

  * CLOSED requires the page to say so - the class or the sentence.
  * OPEN requires the apply link.
  * Anything else is UNKNOWN and writes nothing, not even checked_at, so a
    posting that could not be read stays first in line next time.

A FRESH CONTEXT PER POSTING
---------------------------
Every posting page is opened by a browser that has not been to LinkedIn
before, the way kariyer.net's are (playwright_middleware.py, fresh_context):
a guest who opens posting after posting from one cookie jar is the pattern a
site counts. Unmeasured on LinkedIn; cheap, and the kariyer.net measurement
is why it is the default.
"""

from ..openings import CLOSED, OPEN, UNKNOWN, OpeningCheckMixin
from .linkedin_cards import LinkedinCardsSpider

# Measured 22.09.2026 on a closed posting, as a guest (module docstring). The
# English sentence is what the signed-in page said on 27.08.2026 and costs
# nothing to keep.
CLOSED_MARKERS = (
    "closed-job__flavor--closed",
    "artık başvuru kabul etmiyor",
    "no longer accepting applications",
)

# The apply link on an open posting, by its tracking name - "-onsite" was
# measured; "-offsite" is the same control for a posting that applies on the
# employer's site.
APPLY_MARKERS = ("public_jobs_apply-link",)

DESCRIPTION = "div.show-more-less-html__markup"


class LinkedinCheckSpider(OpeningCheckMixin, LinkedinCardsSpider):
    name = "linkedin_check"

    custom_settings = {
        **LinkedinCardsSpider.custom_settings,
        "ITEM_PIPELINES": {},
        # Read each page before fetching the next (measured 15.09.2026 on the
        # burner-era checker): with the default 5 MB slot, dozens of pages
        # were downloaded before the first verdict was written.
        "SCRAPER_SLOT_MAX_ACTIVE_SIZE": 1,
    }

    def probe_request(self, posting):
        return self.document_request(
            posting["url"], callback=self.parse_check,
            meta={"posting_id": posting["id"], "fresh_context": True},
            dont_filter=True,
        )

    def page_actions(self, page, request):
        """Wait for the posting's own top card or its closed notice."""
        try:
            page.wait_for_selector(
                f"h1.top-card-layout__title, .closed-job, {DESCRIPTION}", timeout=15000,
            )
        except Exception:
            self.crawler.stats.inc_value("linkedin/no_posting_rendered")

    def verdict(self, response):
        body = response.text.lower()
        if any(marker in body for marker in CLOSED_MARKERS):
            return CLOSED
        if any(marker in body for marker in APPLY_MARKERS):
            return OPEN
        self.crawler.stats.inc_value("linkedin/unreadable_posting")
        return UNKNOWN

    def description(self, response):
        text = " ".join(
            part.strip() for part in response.css(f"{DESCRIPTION} ::text").getall()
            if part.strip()
        )
        return text or None
