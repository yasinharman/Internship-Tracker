"""
LINKEDIN - THE SIGNED-IN SEARCH PAGE, READ THE WAY A PERSON SEES IT
====================================================================

LinkedIn was out of scope from 27.07.2026 to 26.08.2026 and docs/sites/linkedin.md said
so in as many words: "Do not add LinkedIn back." That entry has not been
deleted, and the reasoning in it has not been refuted - it has been paid for.
Its API answers nobody who is not signed in, and pointing a bot at an account
is how accounts get closed permanently. What changed on 26.08.2026 is WHOSE
account: a burner opened for this, holding nothing, connected to nobody.

Guest access was re-tested first and is genuinely gone - every anonymous
request is refused. So unlike Indeed there is no anonymous mode to degrade to.
No session means no LinkedIn, and this spider says that and stops rather than
reporting a clean run that collected nothing.

WHY THE PAGE AND NOT THE API
----------------------------
Voyager (/voyager/api/...) returns the same postings as clean JSON and needs
only li_at plus a csrf-token header. It is also the single most mechanical
thing a client can do here: no page, no render, no human shape at all. On an
account we expect to lose eventually, the cheaper the signal we give, the
longer it lasts. So this reads the same page a person reads, in the same
browser Indeed already uses.

WHAT WAS MEASURED, 26.08.2026
-----------------------------
All of it through the burner session, headless Chromium, one navigation each:

  * HTTP 200, no authwall, no challenge, over ~15 navigations in ~20 minutes.
  * `location=İstanbul, Türkiye` as TEXT IS IGNORED. A "stajyer" search that
    way returned 4,446 results including Konya and İzmir. The location filter
    only binds through `geoId`, which is why GEO_ID below is a number and not
    a place name. Read off LinkedIn's own typeahead by driving it:
    "Greater Istanbul" -> 90010422.
  * Pagination is `start=0,25,50...`, 25 per page, and pages 1-3 of the same
    search shared no job id at all.
  * THE CARDS ARE NOT ALL THERE. See page_actions below - this is the one
    thing that would have silently cost us 72% of every page.
  * Filter ids, read out of the filter panel's own inputs rather than guessed:
        f_E   experience level   1=Internship 2=Entry 3=Associate
                                 4=Mid-Senior 5=Director 6=Executive
        f_JT  job type           I=Internship P=Part-time F=Full-time
                                 C=Contract T=Temporary V=Volunteer O=Other
        f_TPR date posted        r86400=24h r604800=week r2592000=month
        f_WT  workplace          1=On-site 2=Remote 3=Hybrid
        f_F   job function       it=Information Technology eng=Engineering

WHAT THIS SPIDER DOES NOT COLLECT
---------------------------------
The description. A LinkedIn card carries a title, a company, a location and
nothing else - there is no snippet to take, so job_description is "N/A" and
the classifier decides on the title alone. Reading descriptions means one
extra request per posting, which doubles the traffic on the account we are
least able to replace. If the classifier's `general_program` pile grows to
the point of being useless, that is when this becomes worth revisiting - not
before, and it should be measured then rather than assumed now.
"""

import json
import os
import time
from urllib.parse import urlencode

from ..api_spider import BaseApiSpider
from ..job_filters import is_wanted, looks_like_internship, looks_like_parttime
from ..loaders import JsonJobLoader
from ..session_cookies import describe as describe_cookies
from ..session_cookies import load_cookies

CARD = "li[data-occludable-job-id]"
RENDERED = "div.job-card-container"


####################################################################
# WHY ::text IS NOT ENOUGH ON A CARD                               #
####################################################################
def node_text(card, selector):
    """
    All of an element's text, not the first text node in it.

    Ember writes its bindings as `<span><!---->Guess Europe Sagl<!----></span>`,
    so the element's first text node is the whitespace BEFORE the comment and
    `css("...::text").get()` returns "\n    ". Measured 26.08.2026: every
    company and location came back "N/A" that way while the page plainly had
    them, because the loader compresses that to "" and falls through to the
    default.

    Concatenating the descendant text is the fix and is also robust to
    LinkedIn wrapping the value in another span tomorrow.
    """
    node = card.css(selector)
    if not node:
        return None
    return " ".join(node[0].xpath(".//text()").getall()).strip() or None


###################################################################
# FINDING THE THING THAT SCROLLS, WITHOUT NAMING IT               #
###################################################################
# The element that actually scrolls the result list has the class
# "GEKTuqWiIyqOShwESkHQRbcfLJlXGyMrOloAXU". Its neighbours are called things
# like "rdRMqzZIOBExrYlvadiFbLXxRVbgJSo". These are build-hashed and will be
# different names next week, so the scroller is found by SHAPE instead: walk
# up from a job card to the first ancestor that both admits to overflowing and
# actually does. Nothing in this string is a LinkedIn class name, on purpose.
SCROLL_STEP_JS = """
() => {
  const card = document.querySelector('li[data-occludable-job-id]');
  if (!card) return false;
  let el = card.parentElement;
  while (el && el !== document.body) {
    const style = getComputedStyle(el);
    const scrolls = (style.overflowY === 'auto' || style.overflowY === 'scroll')
                    && el.scrollHeight > el.clientHeight + 20;
    if (scrolls) { el.scrollTop += 700; return true; }
    el = el.parentElement;
  }
  window.scrollBy(0, 700);
  return false;
}
"""


class LinkedinCardsSpider(BaseApiSpider):
    name = "linkedin_cards"

    site_name = "linkedin.com"
    origin = "https://www.linkedin.com"
    allowed_domains = ["linkedin.com"]

    # The feed, for the same reason Indeed loads its home page: the search
    # requests claim a Referer and a same-origin journey, and arriving
    # straight at a search url makes that claim untrue. See indeed_cards.py.
    warmup_url = "https://www.linkedin.com/feed/"

    COOKIES_ENV = "LINKEDIN_COOKIES"
    STORAGE_STATE_ENV = "LINKEDIN_STORAGE_STATE"

    # A real browser, because that is what the session was made in and what
    # the page needs to render at all. See playwright_middleware.py.
    USE_PLAYWRIGHT = True

    # Not a random pick from the pool: this profile is the browser this
    # actually runs in, and the session was created under it. Carrying a
    # signed-in session under a browser that did not make it is the mistake
    # indeed_cards.py measured on 30.07.2026.
    browser_profile_name = "chrome-151-linux"

    # "Greater Istanbul". A place name in `location=` does not filter - see
    # the module docstring.
    GEO_ID = "90010422"
    PAGE_SIZE = 25

    # 25 x 5 = 125 postings per route before the circuit breaker. Deliberately
    # low for a first season: next_page_allowed() already stops on an empty or
    # a repeated page, so this only ever fires when something is wrong, and on
    # a burner account the cheaper failure is stopping early.
    MAX_PAGES = 5

    ###################################################################
    # TWO ROUTES, BECAUSE ONE HAS ALWAYS LEAKED                       #
    ###################################################################
    '''
        docs/sites/README.md's standing rule: every posting must be reachable by at
        least two independent routes. On kariyer.net the site's own working
        type hid 85% of the internships; on techcareer the typeOfWork filter
        did not know about "Bilgisayar Muhendisligi Stajyeri". There is no
        reason to expect LinkedIn's tick-boxes to be better, and one concrete
        reason to expect them to be worse: on LinkedIn the EMPLOYER picks the
        experience level, and "Career Experience Drive - IT" - a real
        internship with neither "staj" nor "intern" in its title - is exactly
        the posting a keyword scan loses and a filter keeps.

        So both:
          filter-*  what LinkedIn itself files as an internship or part-time
          scan-*    free text, kept or dropped on the title

        ORDER MATTERS and not for tidiness. Searches enter the queue in this
        order and DOMAIN_BLOCK_BUDGET can end a run partway through, so
        whatever is last is what gets lost. The site's own filters are the
        highest-yield routes here, so they go first and the broad scans -
        which mostly re-find what the filters already found - absorb the loss.

        note_discovery() records which route found what, and the closing
        report prints the sole-finder count. Read it: a route that is never
        the only finder of anything is spending requests for nothing, and a
        route that is the only finder of many is carrying the crawl.
    '''
    ROUTES = {
        "filter-staj":         {"f_E": "1"},
        "filter-parttime":     {"f_JT": "P"},
        "scan-yazilim":        {"keywords": "yazılım stajyer"},
        "scan-stajyer":        {"keywords": "stajyer"},
        "scan-intern":         {"keywords": "intern"},
        "scan-part-time":      {"keywords": "part time"},
    }

    # Routes where the SITE has already said this is an internship or
    # part-time work. The title is not consulted on these, deliberately: the
    # whole value of the route is the postings whose titles say nothing.
    SITE_CLASSIFIED_ROUTES = {
        "filter-staj": "Staj",
        "filter-parttime": "Yarı zamanlı",
    }

    custom_settings = {
        **BaseApiSpider.custom_settings,
        # Slower than Indeed's 6s. Indeed can refuse us and be forgiven in ten
        # minutes; LinkedIn can close the account, and there is no second one
        # waiting. Cheapest possible insurance.
        "CONCURRENT_REQUESTS": 1,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 1,
        "DOWNLOAD_DELAY": 8,
        "RANDOMIZE_DOWNLOAD_DELAY": True,
        "TWISTED_REACTOR": "twisted.internet.asyncioreactor.AsyncioSelectorReactor",
        # Below the default 60 on purpose. PlaywrightMiddleware gives one
        # navigation DOWNLOAD_TIMEOUT plus headroom for the whole job, and on
        # this spider the job also contains waiting for the list and scrolling
        # it to the end. 45 leaves room for both inside that budget.
        "DOWNLOAD_TIMEOUT": 45,
        # 429 is what LinkedIn answers when it wants us to slow down, and it
        # is not in Scrapy's default retry list.
        "RETRY_HTTP_CODES": [403, 408, 429, 500, 502, 503, 504, 522, 524],
        "RETRY_TIMES": 2,
    }

    ###################################################################
    # SCROLLING IS NOT A NICETY HERE                                  #
    ###################################################################
    MAX_SCROLL_STEPS = 40
    SCROLL_PAUSE_MS = 400
    # Stop once this many consecutive scrolls have added nothing. Four rather
    # than one because the list refills unevenly - a step that adds nothing is
    # normal mid-page, several in a row means the end.
    SCROLL_IDLE_LIMIT = 4
    # How long to give the list to appear at all. Generous: the cost of
    # waiting is seconds on a spider that already pauses 8s between requests,
    # and the cost of being impatient is an empty page that looks like an
    # exhausted search.
    CARD_WAIT_MS = 15000
    # A wall clock over the scrolling, because the step count is not a bound.
    # page.evaluate() and locator.count() both run javascript in the page and
    # neither takes a timeout: if LinkedIn's own scripts wedge the renderer,
    # they wait for it forever. MEASURED 26.08.2026: one navigation sat inside
    # page_actions for five minutes against a 40-step loop that should have
    # taken twenty seconds, and PlaywrightMiddleware's own budget expired
    # underneath it as a TimeoutError carrying no message at all.
    #
    # This does not stop a single wedged call - nothing here can - but it
    # stops the LOOP from adding to one, and it makes the run's own log say
    # that the page was slow rather than that the search was empty.
    ACTIONS_BUDGET_S = 25

    def page_actions(self, page, request):
        """
        Called by PlaywrightMiddleware between goto() and content().

        MEASURED 26.08.2026, one search page: 25 <li data-occludable-job-id>
        present the instant the page loaded, and SEVEN of them carrying a
        title. The other eighteen were empty shells - LinkedIn renders a card
        when it comes near the viewport and not before. A spider that trusted
        the first content() would have stored 7 of every 25 postings and
        reported a clean run, which is this project's most expensive shape of
        bug and the reason this hook exists at all.

        Scrolling in 700px steps took it 7 -> 13 -> 18 -> 23 -> 25 in four
        steps. The loop below stops on the count rather than on a fixed number
        of scrolls, so a page of 12 results costs one check and a page that
        never fills up costs MAX_SCROLL_STEPS and says so.

        AND IT HAS TO WAIT FIRST. PlaywrightMiddleware navigates with
        wait_until="domcontentloaded", which on an Ember application means the
        shell has arrived and the list has not. Measured 26.08.2026: counting
        immediately found ZERO cards on a 1.3 MB page that had 25 of them a
        second later, so the first version of this hook returned instantly and
        the spider reported "no cards at all" for every search. The recon
        script had a sleep in it and never saw this.

        The warm-up has no route in its meta and never waits - otherwise every
        run would open by staring at the feed for twenty seconds.
        """
        if not request.meta.get("route"):
            return

        try:
            page.wait_for_selector(CARD, timeout=self.CARD_WAIT_MS)
        except Exception:
            # Genuinely no results, a wall, or changed markup. parse_search
            # says which, with the response in hand; nothing to add here.
            self.crawler.stats.inc_value("linkedin/no_cards_after_wait")
            return

        ###############################################################
        # DO NOT ASK HOW MANY THERE ARE. ASK WHEN IT STOPS GROWING.   #
        ###############################################################
        # The first version of this counted the cards once and scrolled until
        # that many had rendered. It scrolled zero times and collected 7 of
        # 25, because the count it trusted was 7: the <li> shells are not all
        # there at the start either - they are appended as you approach them,
        # so "how many are there" has no answer until you have already
        # scrolled to the end.
        #
        # MEASURED 26.08.2026, same page read twice: 7 cards a fifth of a
        # second after the first one appeared, 25 after polling for twenty.
        # Both readings were correct; only one of them was the whole page.
        #
        # So the loop stops on the shape of the answer instead: scroll until
        # several consecutive steps add nothing. A page with 25 results and a
        # last page with 6 both end correctly, and neither needs a number
        # written down here that LinkedIn could change.
        best = 0
        idle = 0
        steps = 0
        deadline = time.monotonic() + self.ACTIONS_BUDGET_S
        for steps in range(1, self.MAX_SCROLL_STEPS + 1):
            if time.monotonic() > deadline:
                self.logger.warning(
                    "Gave up scrolling after %ss with %s card(s) rendered on "
                    "%s - the page is not keeping up. What rendered is stored; "
                    "the rest of this page is lost for this run.",
                    self.ACTIONS_BUDGET_S, best, request.url[:80],
                )
                self.crawler.stats.inc_value("linkedin/scroll_budget_spent")
                break
            page.evaluate(SCROLL_STEP_JS)
            page.wait_for_timeout(self.SCROLL_PAUSE_MS)
            rendered = page.locator(RENDERED).count()
            if rendered > best:
                best, idle = rendered, 0
            else:
                idle += 1
                if idle >= self.SCROLL_IDLE_LIMIT:
                    break

        if steps >= self.MAX_SCROLL_STEPS:
            # Ran out of scrolls while the list was still growing. Not raised:
            # what did render is real. But it must not pass silently - the
            # difference between "this page had 12 results" and "we only saw
            # 12 of them" is invisible in the item count, and that is exactly
            # the bug this whole comment exists because of.
            self.logger.warning(
                "Still finding new cards after %s scroll step(s) on %s - "
                "stopped at %s. Raise MAX_SCROLL_STEPS if LinkedIn has "
                "started paging deeper.",
                self.MAX_SCROLL_STEPS, request.url[:90], best,
            )
            self.crawler.stats.inc_value("linkedin/partial_render")

        self.logger.debug(
            "rendered %s card(s) in %s scroll step(s)", best, steps,
        )
        self.crawler.stats.inc_value("linkedin/cards_rendered", best)

    ###################################################################
    # NO SESSION, NO CRAWL - AND SAY SO BEFORE SPENDING A REQUEST     #
    ###################################################################
    SIGNED_IN_COOKIE = "li_at"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.session_cookies = load_cookies(self.COOKIES_ENV)
        self._require_a_session()
        self._warned_sign_in_wall = False
        # Not describe_cookies() on its own: with a storage state configured
        # LINKEDIN_COOKIES is legitimately empty, and "no session cookies
        # (anonymous)" next to a loaded session reads as a failure.
        self.logger.info(
            "Browser identity: %s | cookie env: %s",
            self.session.profile.name, describe_cookies(self.session_cookies),
        )

    def _require_a_session(self):
        """
        Refuse to start without a signed-in session.

        Indeed can be crawled anonymously for one page per search, so an empty
        INDEED_COOKIES means "anonymous, on purpose" there. Here it means
        nothing works: LinkedIn refuses guests outright, and an anonymous run
        would spend a warm-up, get walled, and exit 0 with no postings - a
        green run that did nothing, which main.py only catches when EVERY
        spider comes back empty.

        Two ways to hold a session, checked in the order the middleware reads
        them: the storage_state file (cookies + localStorage, what
        tools/save_session.py writes) or the cookie-only export. The file is opened
        and looked INTO rather than merely existing, because a run of
        tools/save_session.py that timed out on the login still leaves a perfectly
        valid JSON file with no li_at in it.
        """
        state_path = (os.getenv(self.STORAGE_STATE_ENV) or "").strip()
        if state_path and os.path.isfile(state_path):
            try:
                with open(state_path, encoding="utf-8") as handle:
                    names = {c.get("name") for c in json.load(handle).get("cookies", [])}
            except (OSError, ValueError, AttributeError) as error:
                raise ValueError(
                    f"{self.STORAGE_STATE_ENV} points at {state_path!r} but it "
                    f"could not be read as a Playwright storage state "
                    f"({type(error).__name__}). Re-run: python -m tools.save_session "
                    f"linkedin"
                ) from error
            if self.SIGNED_IN_COOKIE in names:
                self.logger.info(
                    "Session: %s (%s cookies, %s present)",
                    os.path.basename(state_path), len(names),
                    self.SIGNED_IN_COOKIE,
                )
                return
            raise ValueError(
                f"{state_path!r} holds {len(names)} cookie(s) but not "
                f"{self.SIGNED_IN_COOKIE} - that file is a browser that was "
                f"never signed in. Re-run: python -m tools.save_session linkedin"
            )

        if self.SIGNED_IN_COOKIE in self.session_cookies:
            return

        raise ValueError(
            f"LinkedIn needs a signed-in session and there is none. LinkedIn "
            f"refuses guests outright, so unlike Indeed there is no anonymous "
            f"mode to fall back to - a run without this collects nothing and "
            f"reports success. Fix: python -m tools.save_session linkedin, then put "
            f"the path it prints in {self.STORAGE_STATE_ENV}."
        )

    def warmup_cookies(self):
        return self.session_cookies

    ###################################################################
    # TELLING AN EXPIRED SESSION FROM A REFUSED ADDRESS               #
    ###################################################################
    def note_sign_in_wall(self, url):
        """
        Called by BlockDetectionMiddleware when LinkedIn answers with its
        sign-in wall (/authwall, /uas/login - see LOGIN_URL_SIGNATURES).

        On Indeed the same message distinguishes an expired session from a
        blocked address. Here it means one more thing, and the worse one: a
        burner account that has been closed looks exactly like a session that
        has expired. Both are fixed by looking at the account, not by touching
        the crawler - which is what this says, once per run.
        """
        if self._warned_sign_in_wall:
            return
        self._warned_sign_in_wall = True
        self.crawler.stats.set_value("linkedin/session_expired", True)
        self.logger.error(
            "LinkedIn asked us to sign in. The session has expired - or the "
            "burner account has been closed, which looks identical from here. "
            "Open it in a browser before changing anything in the crawler: if "
            "it still signs in, re-run `python -m tools.save_session linkedin`; if "
            "it does not, the account is gone and LinkedIn stops until there "
            "is a new one. This is NOT the address being blocked. (%s)",
            url[:100],
        )

    ###########################################
    # ONE SEARCH PER ROUTE                    #
    ###########################################
    def api_requests(self):
        for route in self.ROUTES:
            yield self._search_request(route, page=1)

    ###################################################################
    # THE ORDER IN THE DICT IS NOT THE ORDER THINGS RUN               #
    ###################################################################
    '''
        Scrapy's default in-memory queue is LIFO, so yielding six searches in
        order runs them backwards. Measured on this spider's first run,
        26.08.2026: ROUTES lists filter-staj first and scan-part-time last,
        and scan-part-time went out first.

        That matters because DOMAIN_BLOCK_BUDGET can end a run partway
        through, so the routes that never get their turn are lost - and
        without this, the ones lost are precisely the ones written first for
        being the most valuable.

        Priority makes the intended order the actual order, rather than
        leaving it to a queue implementation. Every page of a route shares
        its route's priority, so a high-priority route is followed to its end
        before a lower one starts - which is what we want when the run may be
        cut short: complete routes beat six half-crawled ones.
    '''
    def _route_priority(self, route):
        return (len(self.ROUTES) - list(self.ROUTES).index(route)) * 10

    def _search_request(self, route, page, referer=None):
        params = {
            "geoId": self.GEO_ID,
            # Most recent first. A crawl that runs every couple of days wants
            # the new postings on page one; relevance ordering would bury them
            # under the same well-matched jobs every time.
            "sortBy": "DD",
            "start": (page - 1) * self.PAGE_SIZE,
        }
        params.update(self.ROUTES[route])
        url = f"{self.origin}/jobs/search/?{urlencode(params)}"

        # A document request, not api_request: this is a page, and expect_json
        # would make BlockDetectionMiddleware read every good page as a block.
        return self.document_request(
            url,
            callback=self.parse_search,
            referer=referer or self.warmup_url,
            meta={"page": page, "route": route},
            priority=self._route_priority(route),
            dont_filter=True,
        )

    ###########################################
    # PARSE THE RENDERED CARDS                #
    ###########################################
    ###################################################################
    # THE TITLE IS IN THE <strong>, NOT IN THE aria-label             #
    ###################################################################
    def _title_of(self, card):
        """
        aria-label was the obvious source and is wrong for half the board.

        LinkedIn appends its verified-poster badge to the accessible name, so
        a posting from a verified company reads

            aria-label="Web & Mobile Design Intern with verification"
            <strong>   Web & Mobile Design Intern

        MEASURED 26.08.2026 on the first real crawl: 113 of 230 stored titles
        carried " with verification". That is not merely untidy - dedupe_jobs
        matches postings across boards on normalised title AND company, so
        every one of those 113 was unable to pair with its own copy on
        kariyer.net or Indeed. The badge would have quietly disabled half of
        LinkedIn's duplicate detection.

        The element text is the fix; aria-label stays as a fallback for a card
        whose markup changes, because a title with a badge on it is still much
        better than no title at all.
        """
        return (
            node_text(card, "a.job-card-list__title--link strong")
            or node_text(card, "a.job-card-list__title--link")
            or (card.css("a.job-card-list__title--link::attr(aria-label)").get()
                or "").strip()
        )

    def record_key(self, record):
        """The job id, so next_page_allowed() compares postings and not HTML."""
        return record.attrib.get("data-occludable-job-id") or super().record_key(record)

    def parse_search(self, response):
        route = response.meta["route"]
        page = response.meta["page"]
        cards = response.css(CARD)

        if not cards:
            self.logger.warning(
                "[%s] page %s: no cards at all (HTTP %s, %s bytes). Either the "
                "search is exhausted or the card markup has changed - %r is "
                "the selector to check.",
                route, page, response.status, len(response.body), CARD,
            )
            self.crawler.stats.inc_value("linkedin/no_cards")
            return

        site_says = self.SITE_CLASSIFIED_ROUTES.get(route)
        kept = 0

        for card in cards:
            job_id = card.attrib.get("data-occludable-job-id")
            if not job_id:
                self.crawler.stats.inc_value("items/skipped_no_url")
                continue

            title = self._title_of(card)
            if not title:
                # An unrendered shell. page_actions already warned about the
                # count; counted here too so the two numbers can be compared.
                self.crawler.stats.inc_value("linkedin/unrendered_card")
                continue

            # LinkedIn matches the description as well as the title, so a
            # keyword scan returns plenty that is neither an internship nor
            # part-time - "Supply Chain Specialist" at Nike came back for
            # "stajyer" on 26.08.2026. The filter routes are exempt: there the
            # SITE has said what this is, and the postings whose titles say
            # nothing are the entire reason that route exists.
            if not site_says and not is_wanted(title):
                continue

            self.note_discovery(job_id, route)
            kept += 1
            yield self._item_from_card(card, job_id, title, site_says)

        self.logger.info(
            "[%s] page %s: %s card(s), %s kept", route, page, len(cards), kept,
        )
        self.crawler.stats.inc_value("jobs/seen", len(cards))

        if self.next_page_allowed(page, cards, route):
            yield self._search_request(route, page + 1, referer=response.url)

    ###########################################
    # CARD -> ITEM                            #
    ###########################################
    def _item_from_card(self, card, job_id, title, site_says):
        loader = JsonJobLoader()

        loader.add_value("job_title", title)
        loader.add_value("job_title", self.DEFAULT_VALUE)

        company = node_text(card, ".artdeco-entity-lockup__subtitle")
        loader.add_value("company", company)
        loader.add_value("company", self.DEFAULT_VALUE)

        # "Istanbul, Türkiye (On-site)", "Greater Istanbul (Remote)",
        # "Sarıyer, Istanbul, Türkiye (Hybrid)" - stored as LinkedIn writes it.
        # The caption is a <ul> and can carry more than the place (salary,
        # for one), so it is the FIRST item that is the location.
        location = node_text(
            card, ".artdeco-entity-lockup__caption "
                  ".job-card-container__metadata-wrapper li"
        ) or node_text(card, ".artdeco-entity-lockup__caption")
        loader.add_value("location", location)
        loader.add_value("location", self.DEFAULT_VALUE)

        # The card carries no employment type at all, so it comes from the two
        # things that do know: the route, when the site itself classified the
        # posting, and otherwise the title. Same ordering as Indeed - a
        # full-time-hours internship is an internship - except that here there
        # is no third opinion to rank against.
        job_type = site_says
        if not job_type:
            if looks_like_internship(title):
                job_type = "Staj"
            elif looks_like_parttime(title):
                job_type = "Yarı zamanlı"
        loader.add_value("job_type", job_type)
        loader.add_value("job_type", self.DEFAULT_VALUE)

        # Set in one go, not with a fallback add_value: job_description_out is
        # Join(' '), so a second value is appended rather than ignored and
        # every description would end in " N/A". Same trap as indeed_cards.
        loader.add_value("job_description", self.DEFAULT_VALUE)

        # The canonical url, rebuilt rather than taken from the card's href -
        # that one carries refId/trackingId/eBP query parameters that change
        # on every crawl, and url is the UNIQUE upsert key. Taking the href
        # would store the same posting again under a new url every run.
        loader.add_value("url", f"{self.origin}/jobs/view/{job_id}/")
        loader.add_value("source_site", self.site_name)

        return loader.load_item()
