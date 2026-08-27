"""
PLAYWRIGHT TRANSPORT - A REAL BROWSER FOR THE ONE SITE CURL_CFFI CANNOT PASS
=============================================================================

curl_cffi replays a browser's TLS ClientHello, which gets past IP/fingerprint
scoring, but it has no JS engine - so it cannot run whatever Cloudflare's
managed challenge asks of the page to do. MEASURED 05.08.2026: the exact same
home connection that loads tr.indeed.com cleanly in an actual browser got a
403 (cf-mitigated=challenge) from curl_cffi on the very FIRST request of two
separate runs that day, with the session cookies loaded both times. The
address was not the problem - opening the same url by hand, from the same
machine, in the same minute, worked. The client was the problem.

Playwright drives an actual Chromium, so it runs whatever JS the challenge
needs and carries the session the way a browser actually does: loaded into
the browser's own cookie jar once, rather than replayed as a static header
on every request (see _navigate below - the Cookie header Scrapy would have
sent is deliberately dropped for that reason).

OPT-IN, PER SPIDER, same convention as CurlImpersonateMiddleware in
api_middlewares.py: set USE_PLAYWRIGHT = True on the spider class. Nothing
else changes transport - kariyer.net and techcareer.net never see this file.

WHY A DEDICATED THREAD, NOT sync_playwright() CALLED DIRECTLY
---------------------------------------------------------------
This project's TWISTED_REACTOR is AsyncioSelectorReactor (see indeed_cards.py
custom_settings), so Scrapy's callbacks - including this middleware's
process_request - run on the main thread while an asyncio loop is live on
that same thread. Playwright's sync API refuses to start inside a thread
that already has a running loop ("Please use the Async API instead"). So the
browser is launched and driven from a separate, plain OS thread that owns
its own loop; process_request blocks waiting for that thread's answer via a
Future, the same way CurlImpersonateMiddleware blocks on a synchronous
curl_cffi call. One request in flight at a time either way, which matches
CONCURRENT_REQUESTS = 1 on indeed_cards.

UNMEASURED PAST HEADLESS. This is the first attempt: headless Chromium,
05.08.2026. If Cloudflare's challenge still refuses a headless browser (a
real possibility - automation tells like navigator.webdriver and a
headless-specific WebGL renderer are well documented), the next rung is
PLAYWRIGHT_HEADLESS=0 (a visible window) or PLAYWRIGHT_CHANNEL=chrome (the
actually-installed Chrome instead of Playwright's bundled Chromium build),
neither of which needs a code change.
"""

import logging
import os
import queue
import threading
from collections import defaultdict
from concurrent.futures import Future, TimeoutError as FutureTimeout

from scrapy import signals
from scrapy.exceptions import IgnoreRequest
from scrapy.responsetypes import responsetypes
from scrapy.utils.python import to_unicode

from .throttle import SlotThrottle

logger = logging.getLogger(__name__)

# Cloudflare's managed challenge resolves itself via JS in a few seconds when
# it resolves at all - these are the page titles it shows while that runs.
CHALLENGE_TITLE_MARKERS = (
    "just a moment",
    "checking your browser",
    "attention required",
)


class PlaywrightMiddleware:
    def __init__(self, crawler):
        self.crawler = crawler
        self.headless = os.getenv("PLAYWRIGHT_HEADLESS", "1").strip().lower() not in (
            "0", "false", "no", "off",
        )
        self.channel = os.getenv("PLAYWRIGHT_CHANNEL", "").strip() or None
        self.timeout_ms = crawler.settings.getfloat("DOWNLOAD_TIMEOUT", 60) * 1000

        # Resolved per SPIDER in _resolve_storage_state, not here: this
        # middleware is built before it is told which spider it serves, and
        # the storage-state file IS an account. Reading one fixed variable
        # would hand Indeed's session to whatever spider asked for a browser.
        self.storage_state_env = None
        self.storage_state_path = None

        # See process_request: this transport bypasses the downloader's own
        # slot, so it has to keep the delay itself.
        self.throttle = SlotThrottle(crawler.settings)

        self._worker = None
        self._spider = None
        self._job_queue = queue.Queue()
        self._ready = threading.Event()
        self._startup_error = None

        crawler.signals.connect(self._closed, signal=signals.spider_closed)

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler)

    ###################################################################
    # LAZY START - ONLY SPIDERS THAT ASK FOR IT PAY FOR A BROWSER     #
    ###################################################################
    def _ensure_worker(self, spider):
        if self._worker is not None:
            if self._startup_error:
                raise self._startup_error
            return

        self._spider = spider
        self._resolve_storage_state(spider)
        logger.info(
            "Starting Playwright (headless=%s, channel=%s) for %s",
            self.headless, self.channel or "bundled chromium", spider.name,
        )
        self._worker = threading.Thread(
            target=self._worker_main, name="playwright-" + spider.name,
            daemon=True,
        )
        self._worker.start()

        if not self._ready.wait(timeout=60):
            raise RuntimeError(
                "Playwright browser did not finish starting within 60s"
            )
        if self._startup_error:
            raise self._startup_error

    def _resolve_storage_state(self, spider):
        """
        Which exported session belongs to THIS spider.

        The variable name comes from the spider class rather than being a
        constant here, because a storage-state file is the account itself:
        one fixed `INDEED_STORAGE_STATE` would load Indeed's cookies -
        including its Google SSO ones - into a LinkedIn browser context and
        send them to linkedin.com on the first navigation. That is not a
        preference, it is a credential leak between sites.

        The Indeed default keeps a spider that predates this hook working
        untouched.

        Checked here rather than in __init__ because __init__ does not know
        the spider yet. The cost is that a bad path now fails on the first
        request instead of at startup - still loud (the warm-up is the first
        request, so the crawl dies there) and _startup_error re-raises it on
        every later call, so the reason cannot scroll past unnoticed.
        """
        env_var = getattr(spider, "STORAGE_STATE_ENV", "INDEED_STORAGE_STATE")
        raw_path = (os.getenv(env_var) or "").strip()
        if raw_path and not os.path.isfile(raw_path):
            raise RuntimeError(
                f"{env_var}={raw_path!r} but nothing is there (resolved from "
                f"cwd {os.getcwd()!r}). Use an absolute path - the spider does "
                f"not run from the project root. Run `python save_session.py "
                f"<site>` if the file does not exist yet, or unset {env_var} "
                f"to fall back to the cookie-only export."
            )
        self.storage_state_env = env_var
        self.storage_state_path = raw_path or None

    def _worker_main(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as error:
            self._startup_error = RuntimeError(
                "playwright is not installed in this environment - "
                "pip install playwright && playwright install chromium"
            )
            self._ready.set()
            return

        try:
            with sync_playwright() as p:
                launch_kwargs = {"headless": self.headless}
                if self.channel:
                    launch_kwargs["channel"] = self.channel
                browser = p.chromium.launch(**launch_kwargs)

                context_kwargs = {
                    "user_agent": self._spider.session.profile.user_agent,
                    "locale": "tr-TR",
                    "viewport": {"width": 1280, "height": 800},
                }

                # storage_state carries cookies AND localStorage/sessionStorage
                # from an actual by-hand login (see save_session.py) -
                # takes priority because a plain cookie replay was measured
                # 05.08.2026 to get every search's page 1 through cleanly and
                # then hit a sign-in wall on page 2 every time, which reads
                # like Indeed's own page-two check wants more than cookies
                # from a Google/OAuth-linked account.
                storage_state_path = self.storage_state_path
                cookies = getattr(self._spider, "session_cookies", None)
                if storage_state_path:
                    context_kwargs["storage_state"] = storage_state_path
                    logger.info(
                        "Loading full session state from %s (cookies + "
                        "localStorage/sessionStorage)", storage_state_path,
                    )
                elif cookies:
                    logger.info(
                        "No %s set - loading %s cookie(s) only, no "
                        "localStorage/sessionStorage.",
                        self.storage_state_env, len(cookies),
                    )

                context = browser.new_context(**context_kwargs)

                if cookies and not storage_state_path:
                    context.add_cookies([
                        {"name": name, "value": value, "url": self._spider.origin}
                        for name, value in cookies.items()
                    ])

                page = context.new_page()
                self._ready.set()
                self._run_job_loop(page)

                context.close()
                browser.close()
        except Exception as error:
            self._startup_error = error
            self._ready.set()

    def _run_job_loop(self, page):
        while True:
            job = self._job_queue.get()
            if job is None:
                return
            request, future = job
            # Paired with the "navigation phases" line at the end of
            # _navigate: a dequeue with no phases line after it means the
            # worker is wedged inside one navigation, which is what a
            # message-less TimeoutError upstream looks like from here.
            logger.debug("worker dequeued %s", request.url[:80])
            try:
                future.set_result(self._navigate(page, request))
            except Exception as error:
                future.set_exception(error)

    ###################################################################
    # ONE NAVIGATION, RUNS ON THE WORKER THREAD                       #
    ###################################################################
    def _navigate(self, page, request):
        # Phase timings. A navigation that overruns its budget surfaces as a
        # bare TimeoutError with no message and no indication of WHICH part
        # ran long - goto, the challenge wait, the spider's page actions or
        # reading the html back. Measured 26.08.2026, they can differ by two
        # orders of magnitude on the same url minutes apart, so the log has to
        # say which one it was.
        import time as _time
        phase = {}
        _t0 = _time.monotonic()

        headers = {
            to_unicode(name): to_unicode(b", ".join(values))
            for name, values in request.headers.items()
        }
        referer = headers.pop("Referer", None)
        # The browser context carries its own cookie jar, seeded once from
        # session_cookies above - a Cookie header here would fight it rather
        # than let the site set/rotate cookies the way it does for a real
        # visitor. See the module docstring.
        headers.pop("Cookie", None)
        headers.pop("Host", None)
        headers.pop("Content-Length", None)

        ###############################################################
        # HEADERS THE BROWSER OWNS - AND ALREADY IGNORED US ABOUT     #
        ###############################################################
        # set_extra_http_headers applies to EVERY request the page makes -
        # stylesheets, images, and every XHR the application fires after it
        # boots. BrowserSession.document_headers() describes a NAVIGATION, so
        # sending it that way told LinkedIn that the JSON call fetching a list
        # of jobs was a top-level document which accepts text/html.
        #
        # MEASURED 26.08.2026, one url, three variants, same session: with no
        # extra headers, 25 job cards in a second; with the full document
        # headers, 0 cards and a body of 0 bytes - the application never
        # booted; with identity headers only, 25 cards again. It arrived
        # looking like "the search returned nothing".
        #
        # THE PART WORTH KNOWING BEFORE YOU WORRY ABOUT INDEED. Removing
        # these does NOT change what a navigation sends, because Chromium was
        # never letting us set them in the first place. Measured the same day
        # against a local server that printed what it received:
        #
        #   set_extra_http_headers({... Sec-Fetch-Site: same-origin ...})
        #     -> the server saw Sec-Fetch-Site: none, and Chromium's own
        #        full Accept, not ours
        #   the same navigation with nothing set
        #     -> byte for byte the same headers
        #
        # Sec-Fetch-* is browser-controlled and cannot be forged from here -
        # not through extra headers, and not through a route handler either
        # (that was tried and measured too; only Accept survives that path).
        # So indeed_cards.py's "Referer AND Sec-Fetch-Site: same-origin AND
        # the cookies together" was measured through curl_cffi, which really
        # does send what it is told. Under Playwright that request has always
        # gone out as Sec-Fetch-Site: none, before this change and after it.
        #
        # Which leaves subresources as the only thing these headers ever
        # actually affected, and one site that was being broken by them.
        for owned_by_the_browser in (
            "Accept", "Upgrade-Insecure-Requests",
            "Sec-Fetch-Site", "Sec-Fetch-Mode", "Sec-Fetch-User", "Sec-Fetch-Dest",
        ):
            headers.pop(owned_by_the_browser, None)

        page.set_extra_http_headers(headers)

        phase["headers"] = round(_time.monotonic() - _t0, 1)
        _t = _time.monotonic()
        response = page.goto(
            request.url, referer=referer, wait_until="domcontentloaded",
            timeout=self.timeout_ms,
        )
        phase["goto"] = round(_time.monotonic() - _t, 1)
        logger.debug("  goto done in %ss", phase["goto"])

        _t = _time.monotonic()
        self._wait_out_challenge(page)
        phase["challenge"] = round(_time.monotonic() - _t, 1)
        logger.debug("  challenge done in %ss", phase["challenge"])

        ###############################################################
        # A PAGE THAT ONLY RENDERS WHAT YOU HAVE SCROLLED PAST        #
        ###############################################################
        # MEASURED 26.08.2026 on LinkedIn's job search: all 25 results are in
        # the DOM as <li data-occludable-job-id> the moment the page loads,
        # but only the seven on screen carry a title, a company or a location.
        # The other eighteen are empty shells until they are scrolled near.
        # `goto` plus `content()` therefore returns a page that looks complete
        # and is 72% blank.
        #
        # Scrolling is the spider's business, not this middleware's - the
        # shape of the thing to scroll differs per site - so the hook is
        # opt-in and Indeed, which defines no page_actions, reaches
        # content() by exactly the path it always did.
        #
        # Deliberately NOT wrapped in try/except: a page whose actions failed
        # is a page we cannot trust the emptiness of, and returning it anyway
        # would store 7 postings and silently drop 18. Let it raise, let the
        # request fail, let Scrapy retry it.
        _t = _time.monotonic()
        actions = getattr(self._spider, "page_actions", None)
        if callable(actions):
            actions(page, request)
        phase["actions"] = round(_time.monotonic() - _t, 1)
        logger.debug("  actions done in %ss", phase["actions"])

        _t = _time.monotonic()
        html = page.content()
        phase["content"] = round(_time.monotonic() - _t, 1)
        logger.debug(
            "navigation phases (s): %s - %s",
            ", ".join(f"{k}={v}" for k, v in phase.items()), request.url[:80],
        )
        status = response.status if response else 200
        resp_headers = defaultdict(list)
        if response:
            for name, value in response.headers.items():
                # page.content() is already-decoded text - Playwright/Chromium
                # did the br/gzip decompression internally. The header saying
                # so survives on response.headers though, and Scrapy's
                # HttpCompressionMiddleware would try to decompress plain
                # bytes a second time and fail (brotli.error: decoder failed).
                # Same fix as CurlImpersonateMiddleware in api_middlewares.py.
                if name.lower() in ("content-encoding", "content-length"):
                    continue
                resp_headers[name].append(value)

        return {
            "url": page.url,
            "status": status,
            "headers": dict(resp_headers),
            "body": html.encode("utf-8"),
        }

    def _wait_out_challenge(self, page, timeout_ms=10000, interval_ms=1000):
        """
        Cloudflare's managed challenge, when it resolves at all, does it via
        JS in a few seconds without any click - give it room to finish before
        reading the page rather than capturing the interstitial mid-flight.
        BlockDetectionMiddleware's body-signature check still catches it
        downstream if this times out with the challenge unresolved.
        """
        waited = 0
        while waited < timeout_ms:
            try:
                title = (page.title() or "").lower()
            except Exception:
                return
            if not any(marker in title for marker in CHALLENGE_TITLE_MARKERS):
                return
            page.wait_for_timeout(interval_ms)
            waited += interval_ms

    ###################################################################
    # DOWNLOADER MIDDLEWARE HOOKS                                     #
    ###################################################################
    def process_request(self, request, spider):
        if not getattr(spider, "USE_PLAYWRIGHT", False):
            return None

        self._ensure_worker(spider)

        # Playwright answers the request here and returns the Response, which
        # short-circuits the downloader and takes DOWNLOAD_DELAY with it - so
        # indeed_cards' configured 6s between requests was never actually
        # being waited. See throttle.py for the measurement. This matters more
        # here than anywhere else in the project: Indeed is the site most
        # likely to refuse us and the only independent source left.
        self.throttle.wait_turn(request)

        future = Future()
        self._job_queue.put((request, future))
        # DOWNLOAD_TIMEOUT covers the navigation; the headroom covers the rest
        # of the job - waiting out a challenge, and now page_actions, which on
        # a list that renders as you scroll is the longest part. Raised from
        # 30 on 26.08.2026 when the two together could exceed the budget and
        # surface as a bare, message-less TimeoutError on a page that was
        # loading perfectly well.
        budget = self.timeout_ms / 1000 + 60
        try:
            result = future.result(timeout=budget)
        except FutureTimeout:
            # concurrent.futures.TimeoutError carries no message, so Scrapy's
            # retry line reads "failed 1 times: " with nothing after the colon
            # - which is how this cost an hour on 26.08.2026. Say what it is.
            #
            # Worth knowing when reading this in a log: the browser thread is
            # STILL working on that navigation. It cannot be interrupted from
            # here, so the requests behind it wait for it to finish on its own.
            # A run with several of these is a slow site, not a dead crawler.
            self.crawler.stats.inc_value("playwright/navigation_timeout")
            raise IgnoreRequest(
                f"Playwright did not finish this navigation within {budget:.0f}s "
                f"(DOWNLOAD_TIMEOUT + headroom). The browser is still on it; "
                f"page javascript that never settles does this. {request.url[:90]}"
            ) from None

        # Playwright follows redirects itself, so Scrapy's RedirectMiddleware
        # never sees them and request.meta["redirect_urls"] stays empty - the
        # sign-in-wall check in BlockDetectionMiddleware reads exactly that
        # key. Filling it in when we landed somewhere other than what was
        # asked for reuses that check instead of duplicating it here.
        if result["url"] != request.url:
            request.meta["redirect_urls"] = [request.url]

        response_class = responsetypes.from_args(
            headers=result["headers"], url=result["url"], body=result["body"],
        )
        return response_class(
            url=result["url"], status=result["status"],
            headers=result["headers"], body=result["body"], request=request,
        )

    def _closed(self, spider):
        if self._worker is None:
            return
        self._job_queue.put(None)
        self._worker.join(timeout=15)
