"""
KARIYER.NET - LISTING CARD SPIDER
=================================

kariyer.net has no JSON listing endpoint. Its pagination is plain
`<a href="/is-ilanlari?cp=2">` navigation and the page is server-rendered, so
there is no XHR to intercept - see docs/sites/kariyernet.md.

That turned out not to matter, because every ad card on the listing page is a
`<div data-test="ad-card">` carrying the data as attributes:

    worktypeid="P" worktypetext="Yarı zamanlı" workmodeltext="İş Yerinde"
    positionname="..." positionid="1172" companyid="67293"
    sectorid="006011000" sectorname="..." cityid="34" cityname="İstanbul(Avr.)"

So the listing page already answers the question we care about - is this
posting part-time or an internship - without opening the posting.

That drives the shape of this spider:

    1. page through the filtered search (Istanbul + IT), reading cards
    2. keep only worktypeid in {P, S}
    3. request the detail page ONLY for those, purely to get the description

The site's own filter panel has no combined "part-time or internship" option,
so the split happens here instead. It still costs almost nothing: roughly one
in ten cards survives, so nine out of ten detail pages are never fetched.

Attribute names are matched in lowercase - HTML parsers normalise
`workTypeId` to `worktypeid`, and the CamelCase form silently matches nothing.

HOW IT REACHES THE PAGE IS NO LONGER AN HTTP CLIENT. Since 10.09.2026 this
spider drives a real Chromium with a real window, because that is the one
thing kariyer.net's PerimeterX turned out to be checking - see "WHAT THIS
SPIDER IS: A BROWSER WINDOW, OPENED ON PURPOSE" below for the measurement
that says so and the two days of wrong answers it replaced.
"""

import os
import time
from urllib.parse import urlencode, urlparse, parse_qsl, urlunparse

from ..api_spider import BaseApiSpider, logo_url
from ..job_filters import looks_like_internship
from ..loaders import KariyerNetLoader


class KariyerNetCardsSpider(BaseApiSpider):
    name = "kariyernet_cards"

    site_name = "kariyernet.com"
    origin = "https://www.kariyer.net"
    allowed_domains = ["kariyer.net"]

    # No warm-up: the listing page is the first thing a visitor loads anyway,
    # and it hands us its own cookies.
    warmup_url = None

    ##########################################################
    # THE SEARCH - PASTE THE FILTERED URL FROM THE ADDRESS BAR #
    ##########################################################
    '''
        Because the site is server-rendered, its filters live in the page URL.
        Apply them in the UI (Departman = IT/software, Şehir = İstanbul) and
        paste the resulting address here, without any `cp=` page parameter -
        pagination is added by the spider.

        Parameters in the current search:
            ct = city plate numbers. Istanbul is TWO codes - 34 (European
                 side) and 82 (Asian side); using only 34 loses half the city.
            cs = sector code. 001000000 = Bilişim (IT). This maps exactly onto
                 the `sectorid` attribute on the ad cards, so it can be
                 verified after the fact.
            cp = current page, added by the spider.

        The `/istanbul-bilisim` path segment is an SEO slug. Adding `cp=2`
        makes the site 301 to `/istanbul-bilisim-2?...&cp=2`; Scrapy follows
        that automatically, so there is no need to build the slug ourselves.

        Working type is deliberately NOT filtered here: the site offers no
        "part-time OR internship" combination, so we take the field+city
        result set and split it while parsing.
    '''
    '''
        Two narrow searches rather than one broad one. Both are filtered by
        DEPARTMENT (`wa`), not by sector.

        That distinction did most of the work here. Sector describes what the
        COMPANY does, department describes what the ROLE is. Filtering on
        sector=Bilişim returned mostly sales and office jobs at IT companies,
        while missing the developer internship at a shoe manufacturer and the
        e-commerce role at a car dealer - both of which the department filter
        finds immediately.

        "parttime" - the site's part-time listing. Kept EXACTLY as the site
                     produced it: `tpst` is coupled to the URL slug, and
                     `/is-ilanlari?...&tpst=4` without the matching
                     `istanbul-part+time` slug returns nothing at all. So this
                     URL is copied from the address bar, not assembled here.

        "staj"     - the site's internship search, a slug search over titles
                     rather than a working-type filter. Worth its own search
                     twice over: it finds internships across every department
                     and, unlike the working-type codes, it does not depend on
                     how the employer classified the post.

        Both result sets are small - roughly 6 and 26 postings, one page each -
        so this costs almost nothing to run daily. Overlap between them is
        free: the pipeline upserts on url.

        `ct=34,82` is Istanbul: 34 European side, 82 Asian side.
        `wa=...` is the department list chosen in the UI. To change either,
        redo the search on the site and paste the new address here.
    '''
    DEPARTMENTS = "ct=34,82&wa=2,5,22,54,55,60,63,78,87"

    SEARCHES = {
        "parttime": (
            "https://www.kariyer.net/is-ilanlari/istanbul-part+time"
            f"?{DEPARTMENTS}&tpst=4"
        ),
        "staj": (
            f"https://www.kariyer.net/is-ilanlari/stajyer?{DEPARTMENTS}"
        ),
    }

    # Searches whose every result is an internship by definition, because the
    # site's own internship search produced it. Everything they return is kept
    # and labelled Internship without consulting the title or the work-type
    # code - the site classifies its own postings better than we can guess.
    # "Career Experience Drive - IT" is a real internship with neither "staj"
    # nor "intern" anywhere in its title.
    INTERNSHIP_SEARCHES = {"staj"}

    # Fallback signal for the other searches.
    #   F Tam zamanlı   P Yarı zamanlı   S Staj
    #   D Dönemsel      R Serbest        G Gönüllü
    # `S` is dead in practice - zero occurrences across 316 sampled postings -
    # and internships turn up as D (19 of 26 on the internship search), P or F.
    # So this set is a safety net, not the mechanism.
    WANTED_WORK_TYPES = {"P", "S"}

    ###############################################################
    # WHAT THIS SPIDER IS: A BROWSER WINDOW, OPENED ON PURPOSE    #
    ###############################################################
    '''
        Everything above describes reading the site. This describes reaching
        it, and on 10.09.2026 the answer changed completely.

        WHAT WAS HERE BEFORE. curl_cffi replaying a browser's TLS ClientHello,
        with a ladder of four handshakes to fall through when one was refused.
        That worked from 31.07 until it did not: 09.09 produced roughly two
        hours of uninterrupted 403 across every rung of the ladder, and by
        10.09 the very first probe of the day was refused as well -

            firefox147   403,  5 065 bytes,  marker absent

        - while the same address, in a browser, opened any page on the site
        the moment a human asked it to. So the address was fine and the client
        was not, which is exactly the shape indeed_cards met on 05.08.

        WHAT THE MEASUREMENT ACTUALLY FOUND. Not what anyone expected. Working
        down from "a real browser" to "our real browser", one variable at a
        time, all of it on 10.09.2026 from this machine:

            plain `google-chrome <url>`, new profile, nothing attached   CARDS
            the same Chrome, attached to over CDP afterwards             CARDS
            Playwright launching Chrome, --enable-automation left in,
                navigator.webdriver reading `true` the whole way         CARDS
            the same, headless                                    BLOCK PAGE

        Then interleaved, so that a cooling-off effect could not be mistaken
        for a verdict - headless, headed, headless, headed, same minute:

            headless #1     9 495 B   0 cards   "Access to this page ... denied"
            headed   #1   621 239 B  36 cards   "Istanbul Staj Ilanlari ..."
            headless #2     9 495 B   0 cards   "Access to this page ... denied"
            headed   #2   621 665 B  36 cards   "Istanbul Staj Ilanlari ..."

        PerimeterX is not reading navigator.webdriver here, and it is not
        reading the debugging protocol. It is refusing a browser with no
        window. Everything else we spent two days changing - handshakes,
        exit addresses, impersonation ladders - was answering a question the
        site was not asking.

        WHAT THAT MAKES THIS SPIDER. A window. Not a fingerprint that argues
        it is one: NEEDS_A_WINDOW below makes PlaywrightMiddleware refuse to
        start headless for this spider at all, because headless does not fail
        loudly - it returns 9 kB of block page, zero cards, and a run that
        exits 0 having found nothing, which is indistinguishable from a
        selector that has rotted.

        FOR AN UNATTENDED RUN AT MIDNIGHT the display is the new dependency.
        A desktop session already has one. Otherwise Xvfb:

            sudo apt install xvfb
            xvfb-run -a .venv/bin/python main.py --spider kariyernet_cards

        which is a genuinely windowed browser painting into a virtual screen,
        not a headless one wearing a hat. The middleware says this, with the
        command, if it is asked for a window and finds no display.

        THE CANDIDATE LADDER IS GONE, and so is KARIYERNET_IMPERSONATE. There
        is no handshake to choose any more; Chromium brings its own. Both are
        in git history alongside the numbers that justified them.
    '''
    USE_PLAYWRIGHT = True
    NEEDS_A_WINDOW = True

    # Not Indeed's, which is what the middleware falls back to when a spider
    # does not name its own - and that default would load a signed-in Indeed
    # session into a browser about to navigate to kariyer.net. Nothing is
    # expected at this variable: the site needs no account, and leaving it
    # unset is what says so.
    STORAGE_STATE_ENV = "KARIYERNET_STORAGE_STATE"

    ###############################################################
    # A POSTING PAGE IS OPENED BY SOMEBODY WHO HAS JUST ARRIVED   #
    ###############################################################
    '''
        The second measurement of 10.09.2026, and the one that actually got
        the descriptions.

        The window got the LISTING pages. Posting pages kept refusing, and
        for most of an afternoon that looked like PerimeterX detecting
        automation: Chrome, Chromium and Firefox were all refused, over CDP
        and over Juggler alike, while a plain `google-chrome` opened the same
        posting twice in a row from the same address.

        Two variables had been moving together the whole time. Every
        automated probe loaded the listing first, because that is the human
        path and it is where the urls come from. The un-driven control went
        STRAIGHT to a posting. So "automated" and "arrived carrying a cookie
        the listing had set" were never separated. Separating them:

            fresh context, first navigation IS the posting     200, 377 kB
            the same again, another posting                    200, 395 kB
            one context, posting after posting, no listing     #1 200,
                                                               #2-8 all 403
            NEW CONTEXT PER POSTING, one browser throughout    5 of 5 at 200,
                                                               description
                                                               container in
                                                               every one

        So the posting route refuses a request carrying a `_px3` earned
        somewhere else, and serves one carrying nothing. The allowance is per
        cookie jar - not per browser, not per address, not per automation
        protocol. And a context costs FOUR MILLISECONDS to make.

        Hence `fresh_context` on the detail request. The listing requests do
        not set it: they share the run's context happily, three of them in a
        row on the first live run, all 200.

        WHAT THIS IS NOT. Nothing is forged, no challenge is answered, no
        automation is concealed. Each posting is opened by a browser that has
        not been to the site before - which is what a person opening a link
        in a fresh private window looks like.

        THE PERSISTENT PROFILE THAT USED TO BE HERE IS GONE. It was added
        the same morning on the theory that a returning visitor should look
        like one, and flagged in its own comment as not load bearing. This
        measurement makes it actively wrong: the whole point is to arrive
        with no history, and the one profile that HAD accumulated history had
        accumulated a hundred refusals with it. It is in git history.
    '''

    # The identity in browser_session.py that describes THIS machine rather
    # than a plausible other one. Under Playwright almost all of these headers
    # are dropped in favour of the browser's own (see the middleware), but
    # Accept-Language survives, and a run whose header set and whose engine
    # disagree is the one avoidable mismatch left.
    browser_profile_name = "chrome-151-linux"

    #############################################
    # HOW HARD TO KNOCK - AND THE DAY WE LEARNT #
    #############################################
    '''
        kariyer.net runs PerimeterX, and on 31.07.2026 it stopped being enough
        to be merely unhurried.

        A verification run of this spider - roughly 35 requests at about one a
        second, all through the static residential exit - got that address
        refused site-wide. Measured straight afterwards: from the proxy every
        one of the four handshakes returned the same 5065-byte block page,
        while from a home address all four returned 460 kB of cards. Same
        tokens, same minute; the only difference was where the request came
        from.

        That measurement was taken through curl_cffi and a proxy, neither of
        which is in the picture any more, so treat the number below as
        inherited caution rather than a measured floor - unlike indeed_cards'
        20, which was earned twice. What has not changed is the shape of the
        cost: a refusal here is not free, it moves the address into a bucket
        with a memory, and this crawl is small enough that patience is nearly
        free. Two searches, one page each, and a detail page for the roughly
        one card in ten worth opening - about 30 navigations. At 8 seconds
        that is some seven minutes including render time, on a job that runs
        overnight and has nowhere to be.

        Concurrency stays at 1 for a reason that survived the transport
        change: PlaywrightMiddleware drives ONE browser page at a time from a
        single worker thread, so a higher number would not buy parallelism, it
        would only queue requests behind a lock while reading as permission to
        go faster.
    '''
    custom_settings = {
        **BaseApiSpider.custom_settings,
        "CONCURRENT_REQUESTS": 1,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 1,

        ###########################################################
        # 8 -> 180 -> 20, AND THE 180 WAS A BUDGETING MISTAKE     #
        ###########################################################
        # The 8 is worth recording because it was MEASURED to be too fast
        # rather than guessed at: at 8 seconds the run collected 34
        # consecutive postings - a large improvement on the 7 before it - and
        # was then refused, having made those 34 in five minutes. Every
        # request now arrives as a new browser context, so that is about seven
        # brand-new visitors a minute from one address; the fix for the
        # per-request signal had become a per-hour one.
        #
        # 180 came next and was wrong for a reason worth keeping. The owner
        # had said a full run may take three to four hours, and that was read
        # as three to four hours FOR THIS SITE. It is the budget for the whole
        # job, and the whole job is mostly other people's sites:
        #
        #     indeed_cards                             ~41 min   (measured)
        #     linkedin_cards                           ~65 min   (measured)
        #     indeed_check    60 postings x 20s        ~20 min
        #     linkedin_check  487 postings x 8s        ~65 min
        #     techcareer, dedupe, notify, classify      ~5 min
        #     ----------------------------------------------------
        #     everything except kariyer.net           ~3h 12m
        #
        # So the share available here is forty to fifty minutes, not three
        # hours, and 180s would have spent the entire nightly budget on the
        # smallest site on the board.
        #
        # 20 fits that share: this site costs ~50 requests on the crawl and
        # ~46 on the check, and at 20s plus ~10s of page time each that is
        # about 25 minutes and 23 minutes. It is also not an arbitrary number
        # - it is indeed_cards' floor, measured twice on a site with the same
        # shape of problem (docs/sites/indeed.md), which makes it the most
        # defensible guess available without spending another afternoon of
        # this address's credit to find out.
        #
        # STILL A GUESS. The only measurement is that 8 was too fast. If 20 is
        # also refused, do NOT raise it - there is no room left in the budget
        # to raise it into. Cut the REQUEST COUNT instead: a per-site
        # OPENINGS_MAX_PER_SITE would halve the checker's 46 without touching
        # LinkedIn, which is where the descriptions come from (see
        # docs/pipeline.md).
        "DOWNLOAD_DELAY": 20,
        "RANDOMIZE_DOWNLOAD_DELAY": True,

        # Playwright's sync API cannot start on a thread that already has a
        # running asyncio loop, which is why the browser lives on its own
        # thread - see the middleware. This is the reactor that arrangement
        # was built for, and indeed_cards and linkedin_cards both set it.
        "TWISTED_REACTOR": "twisted.internet.asyncioreactor.AsyncioSelectorReactor",

        # 403 is not in Scrapy's default retry list, and the first page of a
        # search is the one that must not be lost: no page 1, no pagination,
        # no postings. Same reasoning as indeed_cards.
        #
        # ONE retry, not three, since 12.09.2026. Once this site starts
        # refusing it does not stop (see below), so the second and third
        # attempts are spent refusals - three of them per url, on every url
        # left in the queue. One covers the blip that the entry above is
        # about and stops there.
        "RETRY_HTTP_CODES": [403, 408, 429, 500, 502, 503, 504, 522, 524],
        "RETRY_TIMES": 1,

        # The run ends after three refusals rather than the shared eight.
        # Same reason: they are not evidence of a bad patch, they are the wall,
        # and five more of them only spend the address's credit on the way to
        # the same place. Whatever was collected before the wall is kept.
        "DOMAIN_BLOCK_BUDGET": 3,
    }

    ###############################################################
    # THE LIMIT IS A COUNT, NOT A RATE - AND WAITING DOES NOT FIX #
    ###############################################################
    '''
        MEASURED TWICE, and the second measurement killed the first one's
        remedy.

        10.09.2026, delay 8s:   34 consecutive requests, then refused
        12.09.2026, delay 20s:  36 consecutive requests, then refused

        Two and a half times the spacing bought TWO more requests. Whatever
        this site is counting, it is not a rate - so slowing down is not the
        lever and there is no point looking for a delay that works.

        WAITING IS NOT THE LEVER EITHER, which is what this section used to
        say and was wrong about. A cool-off of ten minutes was added on
        10.09 on the strength of docs/sites/indeed.md, where a home address
        recovered on its own in about eight. Measured against THIS site:

            10.09  after each 10-minute pause, exactly ONE request got
                   through before the wall came back
            12.09  after the first 10-minute pause, ZERO did

        Six pauses is an hour of waiting for nothing, and every pause ends
        with two more refused requests finding that out. So
        BLOCK_COOLDOWNS_ALLOWED is 0: the run stops at the wall and keeps
        what it has. The cool-off machinery stays in
        BlockDetectionMiddleware - it is opt-in per spider, tested, and a
        site whose refusals really do expire would want it - but this spider
        does not ask for it any more.

        WHAT ACTUALLY WORKS IS FEWER REQUESTS, and the crawl already gets
        there by itself over a few nights, because a posting stored without a
        description is fetched again next time (see "THE POSTING PAGE IS
        FETCHED ONCE"):

            night 1   4 listing + 46 detail   ~36 get through, ~24 stored
                                               with a description
            night 2   4 listing + ~22 detail  = ~26 requests, under the wall
            night 3+  4 listing + that day's new postings ~ 8 requests

        So the queue drains and then stays drained, and the steady state is
        comfortably inside whatever the limit is. The first night is the only
        one that hits the wall, and hitting it costs nothing except the
        postings that wait until tomorrow.

        IF THE WALL EVER MOVES DOWN far enough that night 2 cannot finish
        either, the next lever is still request count, not time: a per-site
        OPENINGS_MAX_PER_SITE would halve the checker's share (see
        docs/pipeline.md), and it is the checker rather than the crawl that
        would have to give, because the crawl is what discovers new postings.
    '''
    BLOCK_COOLDOWN_S = 600
    BLOCK_COOLDOWN_AFTER = 2
    BLOCK_COOLDOWNS_ALLOWED = 0

    ###############################################################
    # WHAT THE BROWSER DOES ON EACH PAGE BEFORE IT IS READ        #
    ###############################################################
    '''
        Two different things, because a listing page and a posting page are
        read differently - by a person and now by this spider. The split is on
        `search_key`, which is on every listing request and on no posting
        request. _read_the_listing and _read_the_posting below carry the
        measurement behind each.
    '''
    # A wall clock over the scrolling rather than a step count, for the reason
    # linkedin_cards gives at length: page.evaluate() runs javascript in the
    # page and takes no timeout, so a wedged renderer waits forever. This does
    # not rescue one wedged call - nothing here can - but it stops the loop
    # from adding to it.
    SCROLL_BUDGET_S = 20
    SCROLL_STEP_PX = 900
    SCROLL_SETTLE_MS = 400

    ###############################################################
    # A PAGE IS LEFT OPEN LONG ENOUGH TO FINISH LOADING           #
    ###############################################################
    '''
        THIS WAS ADDED FOR A REASON THAT TURNED OUT TO BE WRONG, and the
        wrong reason is worth keeping because it was a good theory that
        survived one measurement and died to the next.

        The theory. PlaywrightMiddleware opens a page, navigates, and closes
        it, so with no actions defined a posting page existed for the length
        of `goto` and no longer - 0.1 to 0.6 seconds. The first live run
        served two listing pages that had been scrolled for seconds and seven
        posting pages that had not, then refused everything after. Counting
        directly with a request handler, a listing page given a four-second
        dwell made FOUR PerimeterX sensor requests, and a page torn down 300ms
        after DOMContentLoaded makes none. So: the sensor never gets to post,
        `_px3` is never refreshed, and it goes stale.

        Why it is wrong. A later probe gave posting pages a four-second dwell
        and counted TEN sensor requests on each - and every one of them was
        still refused. The sensor was running fine. What actually decides it
        is whether the request carries a `_px3` earned somewhere else at all;
        see "A POSTING PAGE IS OPENED BY SOMEBODY WHO HAS JUST ARRIVED".

        Why it stays. Four seconds is what every passing measurement used,
        including the five-of-five that settled the design, so removing it
        now would change the one thing that is known to work in order to save
        three minutes on an overnight job. It is also just true that a page
        should be allowed to finish loading before it is read.

        Treat it as unmeasured rather than as load bearing. If it ever needs
        to go, take it out on its own and watch the item count.
    '''
    POSTING_DWELL_S = 4

    def page_actions(self, page, request):
        """Called by PlaywrightMiddleware between goto() and content()."""
        if request.meta.get("search_key"):
            self._read_the_listing(page, request)
        else:
            self._read_the_posting(page)

    ###############################################################
    # THE LOGOS ARE ONLY THERE IF SOMEBODY SCROLLS PAST THEM      #
    ###############################################################
    def _read_the_listing(self, page, request):
        """
        Scroll to the bottom, which is what makes the lazily-loaded logos
        load. MEASURED 09.09.2026 without scrolling: 25 of 40 cards carried a
        1x1 transparent SVG. MEASURED 10.09.2026 with it: 41 of 46 cards
        yielded a real logo url, so this is the difference between a third of
        a page having a mark and nearly all of it.

        It doubles as the dwell - the scroll took 1.7-2.6s on the two listing
        pages of the first run, and neither was ever refused.
        """
        deadline = time.monotonic() + self.SCROLL_BUDGET_S
        was_at_the_bottom = False
        while time.monotonic() < deadline:
            # One evaluate rather than two: scroll, then report where that
            # left us, so the answer cannot describe a page that has moved on
            # between the two calls.
            at_the_bottom = page.evaluate(
                """(step) => {
                    window.scrollBy(0, step);
                    const height = Math.max(
                        document.body.scrollHeight,
                        document.documentElement.scrollHeight,
                    );
                    return window.scrollY + window.innerHeight >= height - 2;
                }""",
                self.SCROLL_STEP_PX,
            )
            page.wait_for_timeout(self.SCROLL_SETTLE_MS)
            # Twice, not once. The first time the bottom is reached the page
            # may still be growing underneath - kariyer.net appends nothing
            # here today, but a list that did would be cut short by a single
            # check, and the extra step costs 400ms.
            if at_the_bottom and was_at_the_bottom:
                break
            was_at_the_bottom = at_the_bottom
        else:
            self.logger.info(
                "Still scrolling %s after %ss - reading it as it stands; the "
                "logo counter will show what that cost.",
                request.url[:70], self.SCROLL_BUDGET_S,
            )
            self.crawler.stats.inc_value("cards/scroll_budget_spent")

        # Back to the top, because that is where a reader leaves a page they
        # are about to click a link on, and because a screenshot taken by
        # anyone debugging this should show the page rather than its footer.
        page.evaluate("() => window.scrollTo(0, 0)")

    def _read_the_posting(self, page):
        """
        Leave a posting page open for as long as reading its first screen
        would take. See POSTING_DWELL_S above for what this is actually for.

        Nothing is scrolled here. The description is server-rendered into
        `[data-test="qualifications-and-job-description"]` and is in the DOM
        whether or not anyone has scrolled to it - measured across every
        posting the first run collected, 630 to 2 537 characters each.
        """
        page.wait_for_timeout(int(self.POSTING_DWELL_S * 1000))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Populated on first use by described_urls(). None rather than an
        # empty set, so "not loaded yet" and "loaded, nothing stored" stay
        # tellable apart - the second is the normal state of a fresh database
        # and must not be retried on every card.
        self._described_urls = None

    def default_meta(self):
        """
        Meta that belongs on EVERY request, warm-up included - see the base
        class.

        `fresh_context` is here rather than on the detail requests alone, and
        it moved on 10.09.2026 after one run said so. The theory was that only
        posting pages needed a clean cookie jar, because listing pages had
        never been refused while sharing one - three of them in a row on the
        first live run. It stopped being true the same afternoon: with the
        address tired from a day of measurements, the SECOND listing page in
        a shared context was refused too.

        There is no reason to keep the distinction. A context costs four
        milliseconds, the site serves a browser that arrives carrying nothing,
        and "every page is opened by someone who has just got here" is one
        rule instead of two - which also means there is no second rule to
        forget when a new kind of request is added.

        The impersonation token this used to carry is gone with curl_cffi.
        """
        return {"fresh_context": True}

    ###############################################################
    # THE POSTING PAGE IS FETCHED ONCE, NOT EVERY NIGHT           #
    ###############################################################
    '''
        MEASURED 10.09.2026: this site refuses the crawl somewhere around the
        35th request, and the crawl was spending ~46 of them re-reading
        descriptions it already had.

        A description does not change. The posting page was being opened every
        single night for every single posting, to extract text identical to
        what was stored the night before - and then kariyernet_check opened
        the SAME pages again an hour later for the open/closed verdict. Two
        visits per posting per night, one of which was pure repetition.

        So the detail page is now requested only when there is something to
        learn from it:

            not in the database yet          -> fetch it
            stored, description is real      -> skip, spend nothing
            stored, description is "N/A"     -> fetch it again

        THE THIRD CASE IS THE ONE THAT MATTERS and a url-only check would
        have missed it. On 10.09 twelve of the forty-six postings were refused
        and stored with "N/A"; under "skip anything already stored" they would
        never be opened again and would sit there without a description
        forever. This way a refused posting simply rejoins the queue tomorrow,
        and the queue shrinks as the descriptions land - which also means the
        load on the site falls as it succeeds rather than staying flat.

        WHAT THIS DOES NOT TOUCH is whether a posting is still open. Nothing
        in parse_detail ever answered that: `last_seen_at` is stamped by
        pipelines.py for any item the crawl yields, and its evidence is the
        card appearing in a search result, not the posting page opening.
        kariyernet_check still visits every posting for the verdict - that is
        its whole job and none of it changes here. The one real trap was that
        parse_detail used to be the ONLY place this spider yielded an item, so
        skipping it would have stopped `last_seen_at` from being stamped and
        made every known posting look like it had left the board; parse_listing
        yields the item itself now.

        A SKIPPED ITEM CARRIES NO job_description AT ALL, deliberately - not
        "N/A". pipelines.py only overwrites the stored description when the
        incoming one is truthy and not "N/A", so either would be safe, but an
        absent field says "I have nothing to say about this column" while
        "N/A" says "it is unknown", and only one of those is true here.
    '''
    def described_urls(self):
        """
        Urls this site already has a real description for, read once per run.

        One query rather than one per card. Loaded lazily so that a hand-run
        `scrapy crawl` against a machine with no database still works: a
        failure here returns an EMPTY set, which means every posting looks new
        and every detail page is fetched - the old behaviour, and the safe
        direction to fail in. Skipping fetches on a failed query would quietly
        collect nothing.
        """
        if self._described_urls is not None:
            return self._described_urls

        from sqlalchemy.orm import sessionmaker

        from ..models import JobPost, db_connect
        from ..pipelines import NO_DESCRIPTION

        try:
            session = sessionmaker(bind=db_connect())()
            try:
                rows = (
                    session.query(JobPost.url)
                    .filter(JobPost.source_site == self.site_name)
                    .filter(JobPost.job_description.isnot(None))
                    .filter(JobPost.job_description != NO_DESCRIPTION)
                    .filter(JobPost.job_description != "")
                    .all()
                )
                self._described_urls = {row[0] for row in rows}
            finally:
                session.close()
        except Exception as error:
            self.logger.warning(
                "Could not read which postings already have a description "
                "(%s: %s) - fetching every posting page, which is what this "
                "spider did before the optimisation.",
                type(error).__name__, error,
            )
            self._described_urls = set()

        self.logger.info(
            "%s posting(s) already have a description and will not be "
            "re-opened tonight.", len(self._described_urls),
        )
        return self._described_urls

    ###############################################################
    # PAGINATION IDENTITY - THE POSTING LINK, NOT THE ELEMENT     #
    ###############################################################
    def record_key(self, record):
        """
        `next_page_allowed` compares pages by record key to notice an index
        that has started repeating itself. A card's identity is its posting
        link; comparing the elements themselves is unreliable.
        """
        href = record.css('a[data-test="ad-card-item"]::attr(href)').get()
        return href or super().record_key(record)

    ##################################
    # PAGE 1 OF THE FILTERED SEARCH  #
    ##################################
    def api_requests(self):
        for search_key in self.SEARCHES:
            yield self._listing_request(search_key, page=1)

    def _listing_request(self, search_key, page):
        base_url = self.SEARCHES[search_key]
        url = self._url_for_page(base_url, page)
        return self.document_request(
            url,
            callback=self.parse_listing,
            referer=base_url if page > 1 else None,
            meta={"page": page, "search_key": search_key},
            dont_filter=True,
        )

    @staticmethod
    def _url_for_page(base_url, page):
        """Replace or add `cp` without disturbing the filter parameters."""
        parts = urlparse(base_url)
        query = [(k, v) for k, v in parse_qsl(parts.query) if k != "cp"]
        query.append(("cp", str(page)))
        return urlunparse(parts._replace(query=urlencode(query)))

    ###############################################
    # READ THE CARDS, KEEP PART-TIME / INTERNSHIP #
    ###############################################
    def parse_listing(self, response):
        cards = response.css('[data-test="ad-card"]')
        page = response.meta["page"]

        from_internship_search = response.meta["search_key"] in self.INTERNSHIP_SEARCHES

        kept = 0
        for card in cards:
            work_type_id = (card.attrib.get("worktypeid") or "").strip().upper()
            title = (card.css('[data-test="ad-card-title"]::text').get() or "").strip()
            position_name = card.attrib.get("positionname") or ""
            is_internship = from_internship_search or looks_like_internship(
                title, position_name
            )

            if not is_internship and work_type_id not in self.WANTED_WORK_TYPES:
                continue

            if is_internship and work_type_id not in ("P", "S"):
                # An internship the employer coded as something else - usually
                # D (Dönemsel) or F. Worth logging: if this count ever drops to
                # zero the searches have probably stopped returning what we
                # think they do.
                self.logger.info(
                    "Internship coded as '%s' by the employer, keeping: %s",
                    work_type_id or "?", title or position_name,
                )
                self.crawler.stats.inc_value("cards/internship_miscoded")

            href = card.css('a[data-test="ad-card-item"]::attr(href)').get()
            if not href:
                # url is the upsert key, so a card without one is unusable.
                self.logger.warning(
                    "Card with no link, skipping: %s",
                    card.attrib.get("positionname"),
                )
                self.crawler.stats.inc_value("items/skipped_no_url")
                continue

            # Which route found it - see BaseApiSpider.note_discovery.
            self.note_discovery(href, response.meta["search_key"])

            kept += 1
            # Internships are labelled Internship whatever the employer coded
            # them as. Otherwise the label would follow an arbitrary employer
            # choice: "Uzun Dönem Staj Programı" arrives as P, "Grafik Tasarım
            # Stajyeri" as F and "Bilgisayar Mühendisliği Stajyeri" as D.
            partial = self._item_from_card(
                card, response, href, force_internship=is_internship,
            )

            url = response.urljoin(href)

            ###########################################################
            # THE CARD IS STORED NOW. THE DESCRIPTION CAN BE LATE.    #
            ###########################################################
            # MEASURED 12.09.2026: 46 cards were kept and 24 rows were
            # written. The other 22 postings produced NO ROW AT ALL, because
            # parse_detail was the only place an item was yielded and their
            # posting pages were refused - so a title, a company, a city, a
            # work type, a logo and a link, all of it already collected from
            # the card, were thrown away because ONE field was missing.
            #
            # That is the opposite of this project's rule about never losing
            # a posting, so the card goes in immediately and the description
            # catches up when the posting page answers - tonight if it
            # answers, tomorrow if it does not. `job_description` is nullable
            # (models.py) and pipelines.py only overwrites the column when
            # the incoming value is real, so the late arrival wins and
            # nothing blanks it in between.
            #
            # The posting is visible on the dashboard from the first night
            # either way: an unclassified row is shown, not hidden. What it
            # waits for is being SORTED - classify_jobs skips a row with no
            # description rather than judging it by its title, which is the
            # whole reason the checks were moved ahead of it on 09.09.
            yield partial

            # The description does not change, so the posting page is worth
            # a request exactly once - see "THE POSTING PAGE IS FETCHED
            # ONCE, NOT EVERY NIGHT" above.
            if url in self.described_urls():
                self.crawler.stats.inc_value("detail/already_described")
                continue

            # fresh_context is what makes the posting page answerable at all -
            # see "A POSTING PAGE IS OPENED BY SOMEBODY WHO HAS JUST ARRIVED"
            # above. The referer stays, because it is true and it is what a
            # person's browser would send; it is simply not the thing that
            # mattered.
            #
            # A COPY, because the item above has already gone to the
            # pipeline. parse_detail adds the description to what it is given
            # and yields it again; handing it the same object would be
            # mutating a row mid-flight for no reason.
            self.crawler.stats.inc_value("detail/fetched")
            yield self.document_request(
                url,
                callback=self.parse_detail,
                referer=response.url,
                meta={"partial_item": partial.copy(), "fresh_context": True},
            )

        search_key = response.meta["search_key"]
        self.logger.info(
            "[%s] page %s: %s card(s), %s part-time/internship",
            search_key, page, len(cards), kept,
        )
        self.crawler.stats.inc_value("cards/seen", len(cards))
        self.crawler.stats.inc_value("cards/wanted", kept)

        if self.next_page_allowed(page, cards, search_key):
            yield self._listing_request(search_key, page + 1)

    #########################################
    # CARD ATTRIBUTES -> MOST OF THE ITEM   #
    #########################################
    def _item_from_card(self, card, response, href, force_internship=False):
        loader = KariyerNetLoader(selector=card, response=response)

        # The visible ad title is more specific than the normalised
        # `positionname` attribute ("Beyaz Eşya Mağaza Satış Danışmanı" vs
        # "Mağaza Satış Danışmanı"), so prefer it and keep the attribute as
        # the fallback.
        loader.add_css("job_title", '[data-test="ad-card-title"]::text')
        loader.add_value("job_title", card.attrib.get("positionname"))
        loader.add_value("job_title", self.DEFAULT_VALUE)

        # The logo's alt text carries the full company name; the visible
        # subtitle is sometimes truncated with an ellipsis.
        loader.add_css("company", 'img[data-test="company-image"]::attr(alt)')
        loader.add_css("company", '[data-test="subtitle"]::text')
        loader.add_value("company", self.DEFAULT_VALUE)

        # The same <img> whose alt gave us the company name, read for its src
        # this time. No DEFAULT_VALUE fallback: a posting with no logo has to
        # arrive as an absent field, not as "N/A" - see logo_url().
        #
        # Measured 09.09.2026 over 40 cards on one listing page: 12 absolute
        # https, 2 protocol-relative, 1 card with no img at all, and 25 that
        # carry a 1x1 transparent SVG because the card had not lazily loaded.
        # logo_url() drops that last group, so roughly a third of the cards on
        # a page yield one. The counter below is what will say whether the
        # kept postings - a tenth of the cards, and the only ones stored - do
        # better or worse than that.
        logo = logo_url(
            card.css('img[data-test="company-image"]::attr(src)').get(),
            base=response.url,
        )
        loader.add_value("company_logo_url", logo)
        self.crawler.stats.inc_value("logo/found" if logo else "logo/missing")

        # The rendered text before the `cityname` attribute, which is wrong for
        # multi-city postings: a nationwide ad carries locations="[object
        # Object],[object Object],..." and cityname holds only the first entry,
        # so a listing covering all 81 provinces reports "Adana". The visible
        # text says "İstanbul(Asya) +80 il daha" and stays honest. For
        # single-city ads the two agree.
        loader.add_css("location", '[data-test="location"]::text')
        loader.add_value("location", card.attrib.get("cityname"))
        loader.add_value("location", self.DEFAULT_VALUE)

        # Normally the site's own wording, which pipelines.normalize_job_type
        # maps onto Part-Time / Internship.
        #
        # The exception is a posting the employer coded full-time but titled
        # "... Stajyeri". Storing worktypetext there would write "Tam zamanlı"
        # -> Full-Time, and the dashboard - which defaults to Internship +
        # Part-Time - would hide the very posting we went out of our way to
        # keep. A full-time internship is still an internship, so it is
        # labelled as one.
        if force_internship:
            loader.add_value("job_type", "Staj")
        loader.add_value("job_type", card.attrib.get("worktypetext"))
        loader.add_value("job_type", self.DEFAULT_VALUE)

        loader.add_value("url", response.urljoin(href))
        loader.add_value("source_site", self.site_name)

        return loader.load_item()

    ###################################################
    # DETAIL PAGE - ONLY REACHED FOR WANTED POSTINGS  #
    ###################################################
    def parse_detail(self, response):
        item = response.meta["partial_item"]

        description = response.css(
            'div[data-test="qualifications-and-job-description"] *::text'
        ).getall()
        if not description:
            description = response.css(
                '[data-test="job-description"] *::text'
            ).getall()

        text = " ".join(part.strip() for part in description if part.strip())
        item["job_description"] = text or self.DEFAULT_VALUE

        if not text:
            self.logger.warning("No description found at %s", response.url)
            self.crawler.stats.inc_value("detail/no_description")

        yield item
