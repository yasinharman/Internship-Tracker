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
from concurrent.futures import Future

from scrapy import signals
from scrapy.responsetypes import responsetypes
from scrapy.utils.python import to_unicode

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

        # See save_indeed_session.py - a file from BrowserContext.storage_state(),
        # not the INDEED_COOKIES(_B64) cookie-only export.
        raw_path = os.getenv("INDEED_STORAGE_STATE", "").strip()
        if raw_path and not os.path.isfile(raw_path):
            raise RuntimeError(
                f"INDEED_STORAGE_STATE={raw_path!r} but nothing is there "
                f"(resolved from cwd {os.getcwd()!r}). Use an absolute path - "
                f"run save_indeed_session.py if the file does not exist yet, "
                f"or unset INDEED_STORAGE_STATE to fall back to INDEED_COOKIES."
            )
        self.storage_state_path = raw_path or None

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
                # from an actual by-hand login (see save_indeed_session.py) -
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
                        "No INDEED_STORAGE_STATE set - loading %s cookie(s) "
                        "only, no localStorage/sessionStorage.", len(cookies),
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
            try:
                future.set_result(self._navigate(page, request))
            except Exception as error:
                future.set_exception(error)

    ###################################################################
    # ONE NAVIGATION, RUNS ON THE WORKER THREAD                       #
    ###################################################################
    def _navigate(self, page, request):
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
        page.set_extra_http_headers(headers)

        response = page.goto(
            request.url, referer=referer, wait_until="domcontentloaded",
            timeout=self.timeout_ms,
        )
        self._wait_out_challenge(page)

        html = page.content()
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

        future = Future()
        self._job_queue.put((request, future))
        result = future.result(timeout=self.timeout_ms / 1000 + 30)

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
