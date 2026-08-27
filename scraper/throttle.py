"""
DOWNLOAD_DELAY FOR TRANSPORTS THAT NEVER REACH THE DOWNLOADER
=============================================================

Two middlewares in this project fetch a request themselves and return the
Response from process_request: CurlImpersonateMiddleware (api_middlewares.py)
and PlaywrightMiddleware (playwright_middleware.py). Both do it for good
reasons - a replayed TLS handshake and a real JS engine respectively.

The cost is not obvious and is not documented anywhere in Scrapy: returning a
Response from process_request short-circuits the download entirely.
Downloader._enqueue_request is what owns the per-domain slot, and it is never
reached, so DOWNLOAD_DELAY, CONCURRENT_REQUESTS_PER_DOMAIN and AutoThrottle
stop applying to those spiders. Silently. The settings stay in
custom_settings, the logs look normal, and the crawl simply goes as fast as
the network allows.

MEASURED 21.08.2026 on kariyernet_check: 14 requests in 3.3s against a
configured DOWNLOAD_DELAY of 4, which should have taken 56. The giveaway is in
the stats - `downloader/request_count` is missing entirely while
`downloader/response_count` is 14, because the counter lives in the method
that was skipped. Restoring the delay took the same run to 33s, and the run
after that was refused with 403s until the site forgave us, which is what the
delay was there to prevent.

It hid for so long because the crawl spiders make few requests: two searches
and a handful of listing pages. The *_check spiders make one per posting - 60
against Indeed - which is where an unthrottled transport stops being a
technicality.

Sleeping is the right shape here rather than restructuring: both callers
already block the reactor by design and say so in their docstrings, so the
sleep costs nothing the fetch was not already costing.
"""

import random
import time

from scrapy.utils.httpobj import urlparse_cached


class SlotThrottle:
    """Per-domain DOWNLOAD_DELAY, enforced by the caller instead of the engine."""

    def __init__(self, settings):
        self.delay = settings.getfloat("DOWNLOAD_DELAY", 0)
        self.randomize = settings.getbool("RANDOMIZE_DOWNLOAD_DELAY", True)
        # slot key -> monotonic time the last fetch started.
        self._last = {}

    def wait_turn(self, request):
        """Block until this domain's delay has elapsed since the last fetch."""
        if self.delay <= 0:
            return

        # The same key Scrapy's own slots use, so a request routed around the
        # downloader still queues behind the same domain rather than getting
        # its own private allowance.
        key = request.meta.get("download_slot") or urlparse_cached(request).netloc

        wait = self.delay
        if self.randomize:
            # Scrapy's own spread: uniform over 0.5x - 1.5x the delay.
            wait = random.uniform(0.5 * self.delay, 1.5 * self.delay)

        previous = self._last.get(key)
        if previous is not None:
            remaining = wait - (time.monotonic() - previous)
            if remaining > 0:
                time.sleep(remaining)

        self._last[key] = time.monotonic()
