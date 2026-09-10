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
api_middlewares.py: set USE_PLAYWRIGHT = True on the spider class. Indeed,
LinkedIn and - since 10.09.2026, for a different reason spelled out below -
kariyer.net. techcareer.net never sees this file; it reads a Next.js data
endpoint that has never asked anything of the client.

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

THE WINDOW TURNED OUT TO BE THE WHOLE ANSWER FOR kariyer.net - 10.09.2026
--------------------------------------------------------------------------
The paragraph that used to sit here guessed that headless might not be
enough and listed PLAYWRIGHT_HEADLESS=0 as a rung to try. On kariyer.net it
is not a rung, it is the entire difference, and the measurement is about as
clean as this project gets. Four launches, interleaved so that an ordering
effect could not be mistaken for a verdict, same binary, same profile shape,
same minute, same address:

    headless #1     9 495 B    0 cards   "Access to this page has been denied"
    headed   #1   621 239 B   36 cards   "Istanbul Staj Ilanlari ..."
    headless #2     9 495 B    0 cards   "Access to this page has been denied"
    headed   #2   621 665 B   36 cards   "Istanbul Staj Ilanlari ..."

Everything else had already been eliminated on the way to that table. A
plain `google-chrome <url>` with a brand-new profile and no CDP attached
loaded the page, which cleared the exit address. Attaching to that same
ordinary Chrome over CDP still loaded it, which cleared the debugging
protocol. Leaving --enable-automation in place, so navigator.webdriver read
`true` the whole way through, still loaded it - PerimeterX is not reading
that flag here. Only the window mattered.

So a spider may declare NEEDS_A_WINDOW = True and this middleware will
refuse to start headless for it, rather than let one stray environment
variable turn a working crawl into 9 kB of block page. That refusal is the
point: headless fails in a way that looks exactly like a dead selector.

WHAT A WINDOW COSTS. It needs a display. On a desktop session there already
is one; for an unattended run there is Xvfb, which is a real windowed
browser painting into a virtual framebuffer rather than a headless one
pretending. _resolve_headless says so with the command to run when no
display is present.
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

# PerimeterX's block page, by contrast, is waiting for a human to press and
# hold a button. It will still be there in ten seconds, in ten minutes, and
# when the crawl gives up - so recognising it is worth a log line and nothing
# else. BlockDetectionMiddleware refuses the response on the 403 and on the
# `px-captcha` in its body; this only stops _wait_out_challenge from spending
# the challenge budget staring at a page that has already finished loading.
DEAD_END_TITLE_MARKERS = (
    "access to this page has been denied",
)


class PlaywrightMiddleware:
    def __init__(self, crawler):
        self.crawler = crawler
        self.channel = os.getenv("PLAYWRIGHT_CHANNEL", "").strip() or None
        self.timeout_ms = crawler.settings.getfloat("DOWNLOAD_TIMEOUT", 60) * 1000

        # Resolved per SPIDER, not here - see _resolve_headless and
        # _resolve_storage_state. This middleware is built before it is told
        # which spider it serves, and both answers belong to the spider: the
        # storage-state file IS an account, so one fixed variable would hand
        # Indeed's session to whatever spider asked for a browser, and
        # headless is the difference between a crawl and a block page on
        # kariyer.net while being free everywhere else.
        self.headless = None
        self.profile_dir = None
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
        self._resolve_headless(spider)
        self._resolve_profile_dir(spider)
        self._resolve_storage_state(spider)
        logger.info(
            "Starting Playwright (headless=%s, channel=%s, profile=%s) for %s",
            self.headless, self.channel or "bundled chromium",
            self.profile_dir or "ephemeral", spider.name,
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

    ###################################################################
    # WINDOW OR NO WINDOW - THE ONE SETTING kariyer.net CARES ABOUT   #
    ###################################################################
    def _resolve_headless(self, spider):
        """
        Headless unless the spider says it cannot be, and never headless
        behind the spider's back.

        PLAYWRIGHT_HEADLESS still overrides, because a one-off experiment
        needs to be able to say "show me". What it may no longer do is
        silently switch a NEEDS_A_WINDOW spider into the mode that returns a
        block page - see the interleaved measurement in the module docstring.
        Refusing there is the difference between a run that fails with a
        reason and a run that reports zero postings and looks like rot in the
        selectors.
        """
        needs_window = bool(getattr(spider, "NEEDS_A_WINDOW", False))
        raw = os.getenv("PLAYWRIGHT_HEADLESS", "").strip().lower()
        asked_for = None
        if raw:
            asked_for = raw not in ("0", "false", "no", "off")

        if needs_window and asked_for:
            raise RuntimeError(
                f"{spider.name} sets NEEDS_A_WINDOW but PLAYWRIGHT_HEADLESS="
                f"{raw!r} asks for a headless browser. On this site headless "
                f"is answered with a 9 kB block page and no cards at all, so "
                f"the run would 'succeed' having found nothing. Unset "
                f"PLAYWRIGHT_HEADLESS, or run the spider that does not need a "
                f"window."
            )

        self.headless = False if needs_window else (
            True if asked_for is None else asked_for
        )

        if self.headless:
            return

        # A windowed browser needs somewhere to draw. Say so now, with the
        # fix, rather than let Chromium fail to start 60 seconds from here
        # with "Missing X server or $DISPLAY".
        if os.getenv("DISPLAY") or os.getenv("WAYLAND_DISPLAY"):
            return
        raise RuntimeError(
            f"{spider.name} needs a windowed browser but neither DISPLAY nor "
            f"WAYLAND_DISPLAY is set, so there is nothing to draw into. For an "
            f"unattended run install Xvfb (`sudo apt install xvfb`) and start "
            f"the job with `xvfb-run -a python main.py --spider {spider.name}` "
            f"- that is a real window on a virtual screen, not headless."
        )

    ###################################################################
    # A PROFILE THAT SURVIVES THE NIGHT                               #
    ###################################################################
    def _resolve_profile_dir(self, spider):
        """
        Where this spider's browser keeps its cookies, history and storage
        between runs, or None for a fresh one every time.

        A person visiting kariyer.net every other day arrives with the
        visitor id PerimeterX gave them weeks ago; a crawl that builds a new
        context each night arrives as a stranger, every night, forever. The
        directory costs nothing and makes the second visit look like a second
        visit.

        Deliberately NOT combinable with a storage-state file: Playwright's
        persistent context owns its own on-disk state and `storage_state` is
        an argument to the ephemeral one. A spider that carries a signed-in
        session wants the file; a spider that just wants to be a returning
        anonymous visitor wants the directory. Nobody needs both, and letting
        both through would quietly ignore one of them.
        """
        configured = getattr(spider, "PLAYWRIGHT_PROFILE_DIR", None)
        raw = (os.getenv("PLAYWRIGHT_PROFILE_DIR") or configured or "").strip()
        if not raw:
            self.profile_dir = None
            return

        path = os.path.abspath(os.path.expanduser(raw))
        os.makedirs(path, exist_ok=True)
        self.profile_dir = path

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
                f"not run from the project root. Run `python -m tools.save_session "
                f"<site>` if the file does not exist yet, or unset {env_var} "
                f"to fall back to the cookie-only export."
            )
        self.storage_state_env = env_var
        self.storage_state_path = raw_path or None

        if self.storage_state_path and self.profile_dir:
            raise RuntimeError(
                f"{spider.name} has both a persistent profile "
                f"({self.profile_dir}) and a storage-state file "
                f"({env_var}={raw_path}). Playwright can honour only one - a "
                f"persistent context owns its own on-disk state - so one of "
                f"them would be silently ignored and the run would carry a "
                f"session nobody could point at. Pick one."
            )

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
                launch_kwargs = self._launch_kwargs()
                context_kwargs = {
                    "locale": "tr-TR",
                    "viewport": {"width": 1280, "height": 800},
                }

                if self.profile_dir:
                    browser, context = self._open_persistent(
                        p, launch_kwargs, context_kwargs
                    )
                else:
                    browser, context = self._open_ephemeral(
                        p, launch_kwargs, context_kwargs
                    )

                self._seed_cookies(context)

                self._ready.set()
                self._run_job_loop(context)

                context.close()
                if browser is not None:
                    browser.close()
        except Exception as error:
            self._startup_error = error
            self._ready.set()

    def _launch_kwargs(self):
        return {
            "headless": self.headless,
            # The full browser rather than Playwright's headless shell, which
            # is what `headless=True` picks by default. Measured 28.08.2026,
            # same flags otherwise: navigator.plugins is 0 on the shell and 5
            # on this, and 0 plugins is a documented headless tell. Override
            # with PLAYWRIGHT_CHANNEL if a machine only has the shell.
            "channel": self.channel or "chromium",
            # navigator.webdriver is `true` without this, which is the browser
            # volunteering that it is automated before any fingerprinting has
            # to work for it. tools/save_session.py has always launched with
            # this flag - the browser that CREATES the session was harder to
            # spot than the one that replays it, which is backwards.
            #
            # Worth knowing what it is NOT doing: kariyer.net's PerimeterX was
            # measured on 10.09.2026 to serve cards to a browser whose
            # navigator.webdriver read `true` throughout, and a block page to
            # a headless one with the flag in place. This hides a tell that at
            # least one vendor is not reading; the window is what it reads.
            "args": ["--disable-blink-features=AutomationControlled"],
        }

    ###################################################################
    # A BROWSER THAT REMEMBERS LAST NIGHT                             #
    ###################################################################
    def _open_persistent(self, p, launch_kwargs, context_kwargs):
        """
        One on-disk profile, reused every run. Returns (None, context) -
        launch_persistent_context hands back the context and owns the browser
        behind it, so there is no separate object to close.

        No user_agent override on this path, unlike the ephemeral one below.
        The correction there exists for exactly one string, "HeadlessChrome",
        and a profile directory is what a spider that must run windowed asks
        for - so on this path the browser's own answer is already true and
        editing it would only reintroduce the mismatch the comment below
        spent a paragraph removing. The warning covers the combination
        nobody has asked for yet.
        """
        if self.headless:
            logger.warning(
                "Persistent profile with headless=True: navigator.userAgent "
                "will read HeadlessChrome, which this path does not rewrite. "
                "If that matters here, the spider probably wants a window."
            )
        context = p.chromium.launch_persistent_context(
            self.profile_dir, **launch_kwargs, **context_kwargs
        )
        logger.info(
            "Browser profile kept at %s - cookies and storage from the "
            "previous run come with it.", self.profile_dir,
        )
        return None, context

    def _open_ephemeral(self, p, launch_kwargs, context_kwargs):
        """A fresh context per run, the way this middleware started."""
        browser = p.chromium.launch(**launch_kwargs)

        ###########################################################
        # THE BROWSER DESCRIBES ITSELF                            #
        ###########################################################
        # user_agent is deliberately NOT set to a profile's any more.
        #
        # MEASURED 28.08.2026. The impersonation profile's UA was
        # being applied to the context, and document_headers() was
        # sending the same one as an HTTP header, so a page asking
        # who this was got:
        #
        #   navigator.userAgent   Macintosh ... Safari/605.1.15
        #   navigator.platform    Linux x86_64
        #   navigator.webdriver   true
        #   WebGL renderer        SwiftShader
        #   navigator.plugins     0
        #
        # A UA claiming macOS Safari on a headless Linux Chromium that
        # is also announcing itself as automated. Five contradictions
        # in the first fifty milliseconds of any fingerprinting
        # script, and Cloudflare has challenged the fourth search page
        # on every run since.
        #
        # The profile's UA exists to be PAIRED WITH A TLS HANDSHAKE -
        # that is what browser_session.py's table is for, and it is
        # right for curl_cffi, which really does replay the handshake
        # it is told to. Playwright brings its own engine and its own
        # handshake, so borrowing the label without the thing it
        # labels only creates the mismatch.
        #
        # Left unset, Chromium reports itself, and the UA, the Client
        # Hints, the platform and the engine finally agree.
        # ...with ONE correction. Headless Chromium puts the word
        # into its own User-Agent - "HeadlessChrome/151.0.0.0" - which
        # is a plainer statement of what we are than any of the
        # mismatches this replaced. Taken from the browser itself and
        # edited by one word, so the version, the platform and the
        # engine all stay true; we are not claiming to be a different
        # browser, only declining to announce the mode.
        scratch = browser.new_context()
        scratch_page = scratch.new_page()
        real_ua = scratch_page.evaluate("() => navigator.userAgent")
        scratch_page.close()
        scratch.close()
        honest_ua = real_ua.replace("HeadlessChrome/", "Chrome/")

        context_kwargs = {**context_kwargs, "user_agent": honest_ua}
        if honest_ua != real_ua:
            logger.info("User-Agent: %s", honest_ua)

        # storage_state carries cookies AND localStorage/sessionStorage
        # from an actual by-hand login (see tools/save_session.py) -
        # takes priority because a plain cookie replay was measured
        # 05.08.2026 to get every search's page 1 through cleanly and
        # then hit a sign-in wall on page 2 every time, which reads
        # like Indeed's own page-two check wants more than cookies
        # from a Google/OAuth-linked account.
        if self.storage_state_path:
            context_kwargs["storage_state"] = self.storage_state_path
            logger.info(
                "Loading full session state from %s (cookies + "
                "localStorage/sessionStorage)", self.storage_state_path,
            )

        return browser, browser.new_context(**context_kwargs)

    def _seed_cookies(self, context):
        """
        The cookie-only export, for a spider that has one and no
        storage-state file to supersede it.

        Applies to both context flavours, which is why it is here rather
        than inside either of them: a persistent profile that has never
        been signed in still wants the exported session on its first run.
        """
        cookies = getattr(self._spider, "session_cookies", None)
        if not cookies or self.storage_state_path:
            return
        logger.info(
            "No %s set - loading %s cookie(s) only, no "
            "localStorage/sessionStorage.",
            self.storage_state_env, len(cookies),
        )
        context.add_cookies([
            {"name": name, "value": value, "url": self._spider.origin}
            for name, value in cookies.items()
        ])

    def _run_job_loop(self, context):
        """
        ONE PAGE PER NAVIGATION, NOT ONE PAGE PER CRAWL.

        This used to open a single page at start-up and hand the same object
        to every navigation. MEASURED 27.08.2026, linkedin_check: the warm-up
        and the first job page returned in under a second each; the second job
        page dequeued and never came back. Not slowly - at all. The only
        reason the log ever moved again was a SIGTERM breaking the driver
        connection seven minutes later.

        The wedge was in `page.set_extra_http_headers()`, before the
        navigation had even started, and that call is representative rather
        than special: it takes no timeout, and neither do `content()` or
        `evaluate()`. `set_default_timeout` does not cover them either -
        Playwright applies it only to "methods accepting a timeout option".
        So a page whose renderer has stopped servicing protocol calls blocks
        every one of them forever, and since the worker is a single OS thread,
        every request behind it waits forever too. Today that turned a 77-page
        check into a 20-minute timeout with two verdicts in it.

        LinkedIn's job pages leave enough running to get a renderer into that
        state within two or three visits. A page is cheap - about 10ms - and a
        fresh one per navigation means a renderer that stops answering dies
        with the page it belongs to instead of poisoning the rest of the run.

        The CONTEXT is kept: it holds the cookies and the storage state, which
        are the expensive part and the whole reason we are signed in.
        """
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
            page = None
            try:
                page = context.new_page()
                future.set_result(self._navigate(page, request))
            except Exception as error:
                future.set_exception(error)
            finally:
                if page is not None:
                    try:
                        page.close()
                    except Exception as error:
                        # A page that cannot be closed is the wedged case
                        # again. Nothing to do about it here, but it must not
                        # take the loop down with it - the next job gets a new
                        # page and has every chance of working.
                        logger.debug("could not close page: %s", error)

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
        #
        # User-Agent and the sec-ch-ua hints join that list on 28.08.2026, for
        # a different reason: they are not ignored, they WORK, and setting
        # them was overriding the truthful values Chromium sends with a
        # description of a browser this is not. See the context note above.
        for owned_by_the_browser in (
            "Accept", "Upgrade-Insecure-Requests",
            "Sec-Fetch-Site", "Sec-Fetch-Mode", "Sec-Fetch-User", "Sec-Fetch-Dest",
            "User-Agent", "sec-ch-ua", "sec-ch-ua-mobile", "sec-ch-ua-platform",
        ):
            headers.pop(owned_by_the_browser, None)

        # set_extra_http_headers takes NO timeout and is not covered by
        # set_default_timeout either - Playwright's default applies only to
        # "methods accepting a timeout option", and this is not one. So it can
        # block for as long as the driver connection does. Logged separately
        # from goto because on 27.08.2026 a wedge landed between "worker
        # dequeued" and "goto done", and those two lines could not tell which
        # of the two calls it was.
        page.set_extra_http_headers(headers)

        phase["headers"] = round(_time.monotonic() - _t0, 1)
        logger.debug("  headers done in %ss", phase["headers"])
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
            if any(marker in title for marker in DEAD_END_TITLE_MARKERS):
                logger.warning(
                    "Served a press-and-hold block page (%r) - that one never "
                    "clears itself, so this navigation is already lost. If "
                    "this is kariyer.net, check that the browser really has a "
                    "window: headless is answered with exactly this page.",
                    title[:60],
                )
                self.crawler.stats.inc_value("playwright/dead_end_challenge")
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
