"""
INDEED - EMBEDDED JSON FROM THE SEARCH PAGE
===========================================

There is no XHR to intercept on Indeed: the search page is server-rendered.
But the data is not scattered through the DOM either - it sits in the page as
plain JSON:

    window.mosaic.providerData["mosaic-provider-jobcards"]
      -> metaData.mosaicProviderJobCardsModel.results

15 records per page, each with jobkey, title, company, formattedLocation,
taxonomyAttributes and an HTML snippet. Parsing that is far steadier than
walking `div.job_seen_beacon`.

A plain request from a residential IP returns HTTP 200 with the full page -
no Cloudflare challenge, despite Indeed sitting behind Cloudflare. Worth
noting because the old spider pays ScrapeOps for JS rendering that may not be
needed; the residential proxy in api_middlewares should cover the datacenter
case on its own.

WHY THE SEARCH IS BY KEYWORD, NOT BY JOB TYPE
---------------------------------------------
Indeed has its own job-type filter, and it is not usable. Across 120 real
Istanbul internship postings the `job-types` taxonomy said:

    Staj                54        Tam zamanlı        28   <- still internships
    Yarı zamanlı        13        (empty)             5
    ...plus 20 in mixed combinations

28 postings whose only type is "Tam zamanlı" are internships with full-time
hours, and 5 declare nothing at all. Filtering on the type would have dropped
a quarter of them. Searching the WORD instead catches them regardless of how
the employer classified the post.

WHY THERE IS NO FIELD FILTER
----------------------------
Turkish companies routinely advertise one internship for the whole company
and allocate people to departments afterwards - "Intern" at UPS, "Stajyer" at
FarklıFikir Bilişim. There is no field to filter on, and guessing would throw
them away.

The field is not decided here at all. This spider keeps every internship and
part-time posting it finds in Istanbul; `classifier.py` reads each one
afterwards and marks the ones that belong to another line of work. A word
list used to do it at this point and could not be made complete - see
job_filters for the evidence.
"""

import json
import os

from ..api_spider import BaseApiSpider, strip_html
from ..browser_session import BrowserSession, profile_for_impersonate
from ..job_filters import is_wanted, looks_like_internship, looks_like_parttime
from ..loaders import JsonJobLoader
from ..session_cookies import describe as describe_cookies
from ..session_cookies import load_cookies

PROVIDER_KEY = "mosaic-provider-jobcards"


def extract_provider_json(text, key=PROVIDER_KEY):
    """
    Pull one `providerData["<key>"]={...}` object out of the page.

    Scanned brace by brace rather than matched with a regex: the blob is
    ~120 kB of nested JSON containing escaped quotes and braces inside string
    values, which no regex handles correctly.
    """
    marker = f'providerData["{key}"]='
    start = text.find(marker)
    if start < 0:
        return None

    start = text.find("{", start)
    if start < 0:
        return None

    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == '"':
            in_string = not in_string
        elif not in_string:
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return text[start:index + 1]
    return None


class IndeedCardsSpider(BaseApiSpider):
    name = "indeed_cards"

    site_name = "indeed.com"
    origin = "https://tr.indeed.com"
    allowed_domains = ["indeed.com"]

    # Which environment variables carry THIS site's exported session. Named on
    # the spider rather than hardcoded in the loader or the middleware, because
    # a session file is the account: a second site reading these would send
    # Indeed's cookies to somewhere that is not Indeed. See
    # PlaywrightMiddleware._resolve_storage_state.
    COOKIES_ENV = "INDEED_COOKIES"
    STORAGE_STATE_ENV = "INDEED_STORAGE_STATE"

    ###################################################################
    # WHY THIS SPIDER LOADS THE HOME PAGE IT DOES NOT NEED            #
    ###################################################################
    '''
        The search page carries its own data, so for a long time this was
        None and the run opened by asking for search results directly.

        That request told Indeed two things that cannot both be true:

            Referer:        https://tr.indeed.com/
            Sec-Fetch-Site: same-origin
            Cookie:         (nothing at all)

        A browser that had just been on tr.indeed.com would be carrying the
        cookies tr.indeed.com set. Claiming the journey without the evidence
        of it is a cleaner bot signal than sending no Referer would have
        been. Measured through one fixed residential IP, one token, one
        minute apart:

            no Referer, Sec-Fetch-Site: none      200, 1.13 MB, data
            Referer + same-origin, no cookies     403, Cloudflare challenge
            Referer + same-origin, after warm-up  200, 1.13 MB, data

        So: go there first. One extra request per run, the claim becomes
        true, and pagination inherits a real session instead of looking like
        four unrelated visitors who each arrived mid-search.

        Note this was invisible from a home connection - every combination
        passed there. It only decided anything from the proxy, which is why
        it survived until the exit IP was the last variable left.
    '''
    warmup_url = "https://tr.indeed.com/"

    LOCATION = "İstanbul"
    PAGE_SIZE = 10          # Indeed's `start` offset step, not the record count

    # One search per term, merged afterwards. Indeed has no category taxonomy,
    # only free-text search, so a single query would miss whatever it does not
    # literally match - "stajyer" does not find "Long Term Intern".
    #
    # WIDER BEATS DEEPER. The four broad terms below all ran into MAX_PAGES on
    # 30.07 with results still arriving, which reads as "raise the ceiling"
    # and is a trap: pages 10-15 of `intern` returned the same six postings
    # over and over (Haleon, Peak, Maersk, GE, Novartis), all of them already
    # stored. Indeed pads a deep result set rather than ending it. A new term
    # costs one request for its first page and brings fifteen postings nobody
    # has seen; page 16 of an old term costs one request for fifteen repeats.
    #
    # The field terms were added 30.07 for that reason. They also address the
    # yield problem the classifier exposes: of 157 postings that run found,
    # 14 were IT and 112 were filed as "other" - cleaners, waiters, teachers,
    # HR. The broad terms are what a general job search returns; these ask
    # for what is actually wanted.
    #
    # Keep both kinds. The discovery report prints found/sole per term, so a
    # term that stops earning its request can be measured out rather than
    # guessed out - and note that on 30.07 EVERY term was the sole finder of
    # something, including the two the field terms most overlap with.
    # ORDER MATTERS, and not for tidiness. Searches enter the queue in this
    # order, and DOMAIN_BLOCK_BUDGET can end a run partway through - it did on
    # 30.07, eight refusals in, with two of the four searches never started.
    # Whatever is last is what gets lost, so the precise terms go first and
    # the broad ones - which mostly re-find what is already stored - absorb
    # the loss.
    SEARCHES = {
        # field: the job-shape term plus what we actually want it to be about
        "yazilim-stajyer": "yazılım stajyer",
        "bilgisayar-muhendisligi-stajyer": "bilgisayar mühendisliği stajyer",
        "software-intern": "software intern",
        "developer-intern": "developer intern",
        "it-intern": "IT intern",
        # broad: the job-shape terms, high volume, low precision
        "stajyer": "stajyer",
        "intern": "intern",
        "part-time": "part time",
        "yari-zamanli": "yarı zamanlı",
    }

    #####################################################################
    # HOW DEEP WE GO DEPENDS ON WHETHER WE ARE SIGNED IN                #
    #####################################################################
    '''
        Indeed shows an anonymous visitor the first page of results and asks
        everyone else to sign in. Its own url says so: page two answers with
        `307 -> secure.indeed.com/auth?...&branding=page-two-signin`, and the
        parameter is named after exactly what it is.

        Asking anyway, anonymously, is not merely wasted. Measured on the run
        that found this (29.07.2026), four searches:

            yari-zamanli page 1   200, 8 postings kept
            part-time    page 1   200, 10 postings kept
            page 2 x2             sign-in wall, 3 escalations each
            intern       page 1   CHALLENGED
            stajyer      page 1   CHALLENGED

        The page-two retries carry priority+1, so they overtook the two
        searches that had not started yet, and the burst of refusals spent
        enough of the address's credit that their first pages - which would
        have worked - were challenged too. Chasing page two anonymously cost
        us two whole searches.

        So: anonymous runs stop at page one, and that is a normal ending
        rather than the "narrow your search" ERROR the base class raises.
        With INDEED_COOKIES set we are past the wall the ceiling exists for,
        and pagination goes back to being bounded by the results themselves.

        MEASURED 30.07.2026, and the account is the answer. The first
        authenticated run was 61 requests, 61 of them HTTP 200, no
        escalations, 367 items, and all four searches ran into this ceiling
        with results still arriving (`pagination/hit_ceiling: 4`). The same
        url that walled anonymously at 13:18 returned data with a session at
        13:44 from that same address, so the address was never the reason.
        MAX_PAGES = 15 is a real ceiling and could go higher.

        The session outlives its oauth cookies. Measured again at 16:30 the
        same day with a cookie file exported at 13:43 - nearly three hours
        old, well past the ~55 minutes in which PPID/BearerToken/OauthExpires
        fill up - page two still answered 200 with data. Repeated with only
        the durable cookies (CTK, JSESSIONID, PPID, RF, SOCK, SHOE): same
        result. The oauth trio the browser refreshes is not what opens the
        wall, so a scheduled run does not need a browser to keep it alive.
        Control run at the same minute with no cookies: page one data, page
        two wall. Still unmeasured beyond three hours; a scheduled 03:00 run
        is the next data point.
    '''
    MAX_PAGES = 15
    ANONYMOUS_MAX_PAGES = 1

    def next_page_allowed(self, page, records, search_key="default"):
        if not self.session_cookies and page >= self.ANONYMOUS_MAX_PAGES:
            if records:
                self.logger.info(
                    "[%s] page %s: %s posting(s). Not asking for page %s - "
                    "Indeed requires an account past the first page, and "
                    "INDEED_COOKIES is not set.",
                    search_key, page, len(records), page + 1,
                )
            return False

        return super().next_page_allowed(page, records, search_key)

    ###################################################################
    # TLS FINGERPRINT - AND THE HANDLER THAT WAS NEVER INSTALLED      #
    ###################################################################
    '''
        Cloudflare fingerprints the TLS handshake itself (JA3/JA4), not just
        the IP and headers. Measured from one machine, one address, one
        moment, with identical headers:

            curl              -> 200
            python requests   -> 403
            Scrapy            -> 403 on every request

        Python's OpenSSL stack has a different ClientHello from a browser's,
        and Indeed rejects it before a single header is read. The residential
        proxy does not change that: it tunnels with CONNECT, so our own
        ClientHello still reaches the server.

        THAT IS THE THEORY. WHAT THIS SPIDER ACTUALLY DOES IS SIMPLER, and it
        took until 31.07.2026 to notice: it crawls over Scrapy's own
        downloader and always has. Two mistakes cancelled out.

        First, a DOWNLOAD_HANDLERS entry pointing at scrapy-impersonate used
        to live in custom_settings BELOW this comment - and never took effect,
        because a triple-quoted comment written inside a dict does not stay a
        comment. Python concatenates it with the string literal that follows,
        so the setting's name was swallowed into one enormous key. No error,
        no handler, no impersonation. (`[k for k in
        IndeedCardsSpider.custom_settings if len(k) > 40]` was how it finally
        showed itself.)

        Second, the package could not have worked anyway: scrapy-impersonate
        1.7.0, the newest release, is incompatible with the pinned Scrapy
        2.13.3 and raises TypeError on every request. So the typo was load-
        bearing. Had the setting worked, this spider would have died on its
        first request rather than quietly returning 773 postings, as it did on
        the morning this was found.

        What actually gets Indeed's pages, then, is the static residential
        exit address plus the signed-in session cookies - not the handshake.
        IMPERSONATE_CANDIDATES below and the ladder in BlockDetectionMiddleware
        still swap meta["impersonate"] on a block, but nothing reads it here,
        so treat the "Switching TLS handshake" log line as noise on this
        spider. tls_probe calls curl_cffi directly, which is why its
        measurements never described what this crawl was doing.

        THE DEAD SETTING HAS BEEN REMOVED, NOT REPAIRED. Repairing it would
        install a transport that raises TypeError and take a working crawl
        down with it. If Indeed ever does start refusing us on the handshake,
        the way in is CurlImpersonateMiddleware - already written, already
        proven on kariyer.net - by setting IMPERSONATE_WITH_CURL = True on
        this class. Read that middleware's docstring first: it fetches
        synchronously and would serialise a sixty-request crawl.

        TWISTED_REACTOR below is a real, live setting and stays.
    '''
    ###################################################################
    # PLAYWRIGHT - A REAL BROWSER, BECAUSE CURL_CFFI HAS NO JS ENGINE  #
    ###################################################################
    '''
        MEASURED 05.08.2026. Two runs that day, both with the session loaded,
        both blocked (cf-mitigated=challenge) on the very FIRST request -
        no pages served, not even the warm-up. The same machine, same address,
        opening tr.indeed.com by hand in an actual browser at the same time:
        loads clean. curl_cffi's replayed TLS handshake gets past the
        IP/fingerprint scoring that used to be the whole story here (see the
        big comment below), but it has no JS engine, so it cannot run
        whatever Cloudflare's managed challenge now asks the page to do.
        That is not an address problem, so no proxy or impersonation token
        fixes it - the client itself has to be a real browser.

        See playwright_middleware.py for how this actually runs (a
        dedicated thread driving Playwright's sync API, because this
        project's asyncio reactor cannot host it directly) and why the
        session cookies go into the browser's own cookie jar instead of a
        Cookie header.

        UNMEASURED PAST HEADLESS - this is the first attempt. If a headless
        Chromium is refused too, PLAYWRIGHT_HEADLESS=0 or
        PLAYWRIGHT_CHANNEL=chrome are the next rungs, not a code change.
    '''
    USE_PLAYWRIGHT = True

    custom_settings = {
        **BaseApiSpider.custom_settings,
        # The most protected of the sites and the only independent source left,
        # so it gets the gentlest treatment.
        "CONCURRENT_REQUESTS": 1,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 1,
        # Raised from 4 on 03.08.2026 - a slower, less mechanical cadence is
        # one of the few free levers left once a session is loaded and TLS
        # identity switching is off the table (see BlockDetectionMiddleware).
        # Unmeasured whether this alone moves the block point.
        "DOWNLOAD_DELAY": 6,
        "RANDOMIZE_DOWNLOAD_DELAY": True,

        "TWISTED_REACTOR": "twisted.internet.asyncioreactor.AsyncioSelectorReactor",

        # Impersonation gets almost everything through, but not quite all: one
        # request in a live run still came back 403, and because it was the
        # FIRST page of the "stajyer" search that single response killed the
        # whole route - no page 1, no pagination, no postings. 403 is not in
        # Scrapy's default retry list, so it is added here.
        "RETRY_HTTP_CODES": [403, 408, 429, 500, 502, 503, 504, 522, 524],
        "RETRY_TIMES": 3,
    }

    #####################################################################
    # WHICH HANDSHAKE TO REPLAY - AND WHY IT IS A LIST, NOT A CONSTANT  #
    #####################################################################
    '''
        This used to be `IMPERSONATE = "chrome131"`, verified 200 on
        28.07.2026. On 29.07 the same token returned an HTTP 403 carrying
        `Security Check - Indeed.com` and `cf-mitigated: challenge` from a
        home IP that had worked the day before. Nothing on our side changed;
        Cloudflare's scoring did.

        Measured that day, two runs each, one address, identical headers:

            chrome110  403 challenge     chrome124   200, 1.19 MB, data
            chrome131  403 challenge     firefox135  200, 1.19 MB, data
            chrome136  403 challenge     firefox147  200, 1.19 MB, data
            chrome142  403 challenge     safari184   200, 1.19 MB, data
            chrome145  403 challenge     safari260   1 of 2 challenged
            chrome146  403 challenge

        Every Chrome token but one was challenged, and it was not a
        newest-is-best gradient - chrome124 passes while chrome110 and
        chrome146 do not. Chrome is what almost all impersonating traffic
        claims to be, so it is where the scrutiny goes; Firefox got through
        untouched. That is a fact about a vendor's current model, not a law,
        which is exactly why nothing here is pinned to one value any more.

        The list is an escalation ladder, same idea as the proxy one:
        BlockDetectionMiddleware moves to the next token when a response
        comes back as a block, so one stale entry costs a retry instead of
        the whole crawl. Ordered by what measured cleanest, with a Chrome
        entry last so we are not betting everything on one engine.

        Re-measure with `python -m MultiwebsiteScraper.tls_probe` - it prints
        this table fresh - and reorder from what it says. Do not "fix" this
        by pinning the one token that works today; that is the bug above.

        INDEED_IMPERSONATE overrides the order for a one-off experiment.

        Re-measured 30.07.2026, through the static residential proxy, and the
        ladder had turned over completely in a day:

            firefox147  403 challenge    safari184  200, 1.14 MB, data
            firefox135  403 challenge    chrome124  200, 1.14 MB, data

        The two tokens that carried the successful morning run were being
        challenged by the afternoon, and chrome124 - last in the list because
        Chrome is where the scrutiny goes - was fine. Reordered from that
        measurement, not from a preference. This is the second reversal in
        two days: read the ladder as weather, and run tls_probe before
        assuming today's order is still right.

        Worth knowing: the exported session was created in FIREFOX, and it
        keeps working under the safari184 handshake. The browser-must-match
        note in session_cookies.py is a caution, not an observed refusal.
    '''
    IMPERSONATE_CANDIDATES = (
        "safari184", "chrome124", "firefox147", "firefox135",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        override = os.getenv("INDEED_IMPERSONATE", "").strip()
        self._impersonate_pinned = bool(override)
        self.impersonate_candidates = (
            [override] if override else list(self.IMPERSONATE_CANDIDATES)
        )

        # A real signed-in session, exported from a browser by hand. Empty is
        # the normal case and means "crawl anonymously". See session_cookies.
        self.session_cookies = load_cookies(self.COOKIES_ENV)
        self._require_a_whole_session()
        self._prefer_the_session_s_browser()
        # Set once the sign-in wall has been seen WITH cookies loaded, so the
        # spider complains about the session exactly once instead of on every
        # search left in the queue.
        self._warned_stale_session = False

        # The handshake and the User-Agent have to describe the same browser,
        # so the identity follows the token rather than being drawn at random.
        token = self.impersonate_candidates[0]
        self.session = BrowserSession(
            profile=profile_for_impersonate(token), origin=self.origin,
        )
        self.logger.info(
            "TLS handshake order: %s (identity: %s) - %s",
            ", ".join(self.impersonate_candidates), self.session.profile.name,
            describe_cookies(self.session_cookies),
        )

    #####################################################################
    # A SESSION PICKS THE HANDSHAKE - MEASURED, NOT ASSUMED             #
    #####################################################################
    SESSION_BROWSER = "firefox"

    def _prefer_the_session_s_browser(self):
        """
        Carry a session under the handshake of the browser that made it.

        Measured on the server, 30.07.2026, one address, ten minutes apart:

            ladder as ordered (safari184 first)   8 of 11 requests refused,
                                                  block budget spent, run over
            firefox147 pinned                     61 of 61 answered, no
                                                  challenge, 335 postings

        And the refusals were not spread evenly: every one of the three
        responses the first run did get came back on firefox147, while
        safari184 went 0 for 2 and chrome124 0 for 4. The session was exported
        from Firefox. A session presented under a different browser's
        handshake is a session being used by something other than what made
        it, which is a cheaper thing to notice than any fingerprint - the
        warning in session_cookies.py said so before this measured it.

        Note what this does NOT say: safari184 and chrome124 had both been
        measured clean by tls_probe minutes earlier, from the same address.
        The probe sends no cookies. So the ladder is not stale - something
        about carrying a session changes the verdict, and an anonymous crawl
        keeps the measured order untouched.

        AND THE PAIRING IS NOT THE WHOLE STORY. Later the same evening, from
        the HOME machine through that same proxy, the Firefox session was
        carried under safari184 and answered 200 with data, twice, while
        firefox147 was refused - the exact opposite of the server. Same exit
        address, same session, same hour. So the accepted combination
        involves the client environment too (curl_cffi on Windows/3.14 here,
        Linux/3.12 there), and "use the session's browser" is the rule that
        fits where this actually runs rather than a law about Cloudflare.

        Which is only the standing rule restated: measure where the spider
        runs. A verdict from a laptop says nothing about the server, and that
        confusion has now cost this project three separate afternoons.

        Set INDEED_SESSION_BROWSER if the session was made somewhere else,
        and INDEED_IMPERSONATE still overrides everything for an experiment.
        """
        if not self.session_cookies or self._impersonate_pinned:
            # A pinned token is someone running an experiment on purpose, and
            # the mismatch warning below would read as a mistake.
            return

        # `or` rather than a getenv default: .env.example ships the key with
        # an empty value, and empty has to mean "the default" instead of
        # "skip this", or copying the example file would silently turn the
        # pairing off.
        browser = (os.getenv("INDEED_SESSION_BROWSER", "").strip().lower()
                   or self.SESSION_BROWSER)

        matching = [t for t in self.impersonate_candidates
                    if t.startswith(browser)]
        if not matching:
            self.logger.warning(
                "The session was made in %s but no %s handshake is in the "
                "ladder (%s). Carrying it under another browser is what "
                "cost a run on 30.07.2026 - expect challenges.",
                browser, browser, ", ".join(self.impersonate_candidates),
            )
            return

        rest = [t for t in self.impersonate_candidates if t not in matching]
        if self.impersonate_candidates != matching + rest:
            self.logger.info(
                "Session was made in %s, so %s leads the ladder - the other "
                "tokens stay as fallbacks.", browser, matching[0],
            )
        self.impersonate_candidates = matching + rest

    #####################################################################
    # A HALF-SESSION IS WORSE THAN NO SESSION                           #
    #####################################################################
    SIGNED_IN_COOKIES = ("SOCK", "SHOE")

    # A Google/OAuth-linked Indeed account (no password ever set) never gets
    # SOCK/SHOE - it carries this pair instead. Discovered 03.08.2026;
    # unlike SIGNED_IN_COOKIES this has not been measured past page 1, see
    # _require_a_whole_session().
    OAUTH_SIGNED_IN_COOKIES = ("__Secure-PassportAuthProxy-RefreshToken",
                               "JSESSIONID")

    def _require_a_whole_session(self):
        """
        Refuse a session that is missing the cookies that do the work.

        SOCK and SHOE are what actually carry the sign-in: measured
        30.07.2026, those two plus CTK/JSESSIONID/PPID/RF opened page two on
        their own, three hours after export, with the oauth cookies long
        expired. A session without them is not a session.

        The failure this catches is silent by nature. A value truncated on
        its way through a panel's text box still decodes, still parses, and
        still yields a plausible-looking pile of cookies - it just quietly
        crawls one page out of fifteen and reports success, which is the
        shape of every expensive mistake this spider has already made. Better
        to stop with the reason on screen.
        """
        if not self.session_cookies:
            return                                  # anonymous, on purpose

        missing = [name for name in self.SIGNED_IN_COOKIES
                   if name not in self.session_cookies]
        oauth_missing = [name for name in self.OAUTH_SIGNED_IN_COOKIES
                          if name not in self.session_cookies]
        if missing and oauth_missing:
            raise ValueError(
                f"The Indeed session is missing {', '.join(missing)} - it "
                f"loaded {len(self.session_cookies)} cookie(s) but not the "
                f"ones that carry the sign-in. A value cut short in a panel's "
                f"environment box does exactly this. Re-export the Cookie "
                f"header and set INDEED_COOKIES_B64 again; unset it if an "
                f"anonymous one-page crawl is what you want."
            )
        if missing:
            # UNMEASURED as of 03.08.2026: a Google-linked account never
            # carries SOCK/SHOE, only the __Secure-PassportAuthProxy-* /
            # JSESSIONID family. Letting it through is a real experiment,
            # not a known-good path - note_sign_in_wall() below will say so
            # loudly in the log if page 2 turns out to be a sign-in wall
            # rather than data.
            self.logger.warning(
                "Session has no %s (native login) but does have %s "
                "(Google/OAuth login) - proceeding as an unmeasured "
                "experiment. Watch for a sign-in-wall error past page 1.",
                "/".join(self.SIGNED_IN_COOKIES),
                "/".join(self.OAUTH_SIGNED_IN_COOKIES),
            )

        # Which browser the session was actually created in is not something
        # this process can know - it only sees the cookie values. So it does
        # not pretend to check: it prints the identity the session is about
        # to be used under and leaves the comparison to the person who signed
        # in, who is the only one holding the other half of it.
        #
        # Worth printing at all because the mismatch it guards against - a
        # session created in one browser and used from another - is cheaper
        # for a site to spot than anything else measured here, and the fix is
        # sixty seconds of signing in again with the right browser.
        if self.session_cookies:
            self.logger.info(
                "Session cookies will be sent as %s / %s. Sign in with that "
                "browser if you have not - a session used by something other "
                "than what created it is the easiest kind of anomaly to spot.",
                self.impersonate_candidates[0], self.session.profile.user_agent,
            )

    def warmup_cookies(self):
        return self.session_cookies

    ###################################################################
    # TELLING AN EXPIRED SESSION FROM A REFUSED ADDRESS               #
    ###################################################################
    def note_sign_in_wall(self, url):
        """
        Called by BlockDetectionMiddleware whenever Indeed answers with its
        sign-in page. Both failures look identical in a log - no postings,
        a redirect to /auth - and they need opposite responses: one is fixed
        by signing in again, the other by leaving the address alone for ten
        minutes. Guessing wrong between them cost an afternoon on 28.07.

        The cookies being loaded is what separates them. Said once per run:
        the searches still queued will each hit the same wall, and four
        copies of the same instruction is how a log stops being read.
        """
        if not self.session_cookies or self._warned_stale_session:
            return

        self._warned_stale_session = True
        self.crawler.stats.set_value("indeed/session_expired", True)
        self.logger.error(
            "INDEED_COOKIES is set, but Indeed still asked us to sign in. The "
            "exported session has almost certainly expired - sign in again in "
            "the browser, copy the Cookie header and replace the value. This "
            "is NOT the address being blocked; do not go looking for a proxy "
            "problem. (%s)", url[:100],
        )

    def default_meta(self):
        """
        Carried by every request including the warm-up, which the base class
        builds before this spider gets a say. A warm-up sent without these
        goes out on Python's own TLS fingerprint and is refused - and since
        it is the first request of the run, the whole crawl dies there.
        """
        return {
            # Tells scrapy-impersonate which browser handshake to replay.
            "impersonate": self.impersonate_candidates[0],
            # The rest of the ladder, for BlockDetectionMiddleware to climb
            # when this one comes back challenged.
            "impersonate_candidates": self.impersonate_candidates,
        }

    ###########################################
    # ONE SEARCH PER KEYWORD                  #
    ###########################################
    def api_requests(self):
        for search_key in self.SEARCHES:
            yield self._search_request(search_key, page=1)

    def _search_request(self, search_key, page, referer=None):
        from urllib.parse import urlencode

        params = {
            "q": self.SEARCHES[search_key],
            "l": self.LOCATION,
            "start": (page - 1) * self.PAGE_SIZE,
        }
        url = f"{self.origin}/jobs?{urlencode(params)}"

        # A document request, not api_request: the response is HTML with JSON
        # inside it, so `expect_json` would make BlockDetectionMiddleware treat
        # every good page as a block.
        #
        # The referer is the page we actually came from - the home page for
        # the first request of a search, the previous result page after that.
        # Both are true statements by the time they are sent; see warmup_url.
        return self.document_request(
            url,
            callback=self.parse_search,
            referer=referer or self.warmup_url,
            meta={"page": page, "search_key": search_key},
            dont_filter=True,
        )

    ###########################################
    # PARSE THE EMBEDDED JSON                 #
    ###########################################
    def parse_search(self, response):
        blob = extract_provider_json(response.text)
        if not blob:
            self.logger.error(
                "No %s blob at %s (HTTP %s, %s bytes) - either the page shape "
                "changed or we were served an interstitial.",
                PROVIDER_KEY, response.url, response.status, len(response.body),
            )
            self.crawler.stats.inc_value("indeed/no_provider_data")
            return

        try:
            payload = json.loads(blob)
        except json.JSONDecodeError as error:
            self.logger.error("providerData blob is not valid JSON: %s", error)
            return

        records = (
            payload.get("metaData", {})
            .get("mosaicProviderJobCardsModel", {})
            .get("results", [])
        )

        page = response.meta["page"]
        search_key = response.meta["search_key"]
        kept = 0

        for record in records:
            title = record.get("displayTitle") or record.get("title") or ""

            # The keyword search matches the description too, so postings that
            # are neither an internship nor part-time come back as well.
            if not is_wanted(title):
                continue

            jobkey = record.get("jobkey")
            if not jobkey:
                self.crawler.stats.inc_value("items/skipped_no_url")
                continue

            self.note_discovery(jobkey, search_key)
            kept += 1
            yield self._item_from_record(record, jobkey)

        self.logger.info(
            "[%s] page %s: %s posting(s), %s kept", search_key, page,
            len(records), kept,
        )
        self.crawler.stats.inc_value("jobs/seen", len(records))

        if self.next_page_allowed(page, records, search_key):
            yield self._search_request(search_key, page + 1, referer=response.url)

    ###########################################
    # RECORD -> ITEM                          #
    ###########################################
    def _item_from_record(self, record, jobkey):
        loader = JsonJobLoader()

        loader.add_value("job_title", record.get("displayTitle"))
        loader.add_value("job_title", record.get("title"))
        loader.add_value("job_title", self.DEFAULT_VALUE)

        loader.add_value("company", record.get("company"))
        loader.add_value("company", self.DEFAULT_VALUE)

        loader.add_value("location", record.get("formattedLocation"))
        loader.add_value("location", record.get("jobLocationCity"))
        loader.add_value("location", self.DEFAULT_VALUE)

        # taxonomyAttributes -> [{"label": "job-types", "attributes": [...]}]
        job_types = []
        for group in record.get("taxonomyAttributes") or []:
            if group.get("label") == "job-types":
                job_types = [a.get("label") for a in group.get("attributes") or []]
                break

        # An internship whose employer only ticked "Tam zamanlı" would
        # normalise to Full-Time and then be hidden by the dashboard, which
        # defaults to Internship + Part-Time. That was 19 of 72 postings on a
        # sampled run - "STAJYER DANISMA", "Finance Intern" and the like, all
        # found BY the internship search. A full-time internship is still an
        # internship, so the title's verdict is put first and
        # normalize_job_type ranks Internship above Full-Time.
        title = record.get("displayTitle") or record.get("title") or ""
        if looks_like_internship(title):
            job_types = ["Staj"] + [t for t in job_types if t != "Staj"]
        elif looks_like_parttime(title):
            job_types = ["Yarı zamanlı"] + [
                t for t in job_types if t != "Yarı zamanlı"
            ]

        loader.add_value("job_type", ", ".join(t for t in job_types if t) or None)
        loader.add_value("job_type", self.DEFAULT_VALUE)

        # `snippet` is an excerpt, not the full text. Enough for the dashboard
        # to be readable, and it costs no extra request - which matters on the
        # site most likely to block us, and the only independent source we have
        # left. Fetch /viewjob?jk=<key> per posting if the full text is ever
        # needed, at roughly 75 extra requests a day.
        #
        # Set in one go rather than with a fallback add_value: this field's
        # output processor is Join(' '), so a second value is APPENDED rather
        # than ignored, and the fallback would leave "...18:00 ). N/A".
        loader.add_value(
            "job_description",
            strip_html(record.get("snippet")) or self.DEFAULT_VALUE,
        )

        loader.add_value("url", f"{self.origin}/viewjob?jk={jobkey}")
        loader.add_value("source_site", self.site_name)

        return loader.load_item()
