"""
DOWNLOADER MIDDLEWARES FOR THE JSON-API SCRAPING MODE
=====================================================

Two middlewares that work as a pair:

  ResidentialProxyMiddleware  attaches the IPRoyal residential proxy to a
                              request and owns the sticky-session lifecycle.

  BlockDetectionMiddleware    notices that a response is a block rather than
                              data, and retries it one rung further up the
                              escalation ladder:

                                  direct  ->  proxy  ->  proxy + fresh IP

                              and, for spiders that replay a browser TLS
                              handshake, changes WHO we look like at every
                              rung as well - see _next_impersonation.

Both share one ProxyState object that lives on the crawler, so the block
detector can tell the proxy middleware "burn this IP" and have it stick.

Middleware priorities matter here:
  725  ResidentialProxyMiddleware  - must run before Scrapy's own
                                     HttpProxyMiddleware (750), which turns
                                     the credentials in our proxy URL into a
                                     Proxy-Authorization header.
  590  BlockDetectionMiddleware    - on the response path Scrapy walks
                                     middlewares in DECREASING priority, so
                                     590 sees the response before RetryMiddleware
                                     (550) does. That is what we want: a 429
                                     should rotate the exit IP, not be retried
                                     blindly from the same one.
"""

import logging
from collections import defaultdict

from curl_cffi import requests as curl_requests
from scrapy.exceptions import IgnoreRequest, NotConfigured
from scrapy.responsetypes import responsetypes
from scrapy.utils.python import to_unicode
from scrapy.utils.response import response_status_message

from .browser_session import profile_for_impersonate
from .proxy import ProxyConfig, new_session_id

logger = logging.getLogger(__name__)


###############################################################
# SHARED STATE: WHICH SESSION ARE WE ON, WHO IS BLOCKING US    #
###############################################################
class ProxyState:
    """One instance per crawl, shared by both middlewares."""

    def __init__(self, config: ProxyConfig):
        self.config = config
        self.session_id = new_session_id()
        self.requests_on_session = 0
        self.rotations = 0
        # Domains that already refused us while going direct. In 'auto' mode
        # every later request to those domains starts on the proxy, so we do
        # not pay for one wasted block per request.
        self.blocked_domains = set()

    def rotate(self, reason=""):
        # A static residential / ISP address is the only exit there is. Say so
        # once per attempt rather than minting a session id that changes
        # nothing and logging three "fresh" IPs that are all the same one.
        if self.config.is_static:
            logger.info(
                "Would rotate the exit IP (%s) but PROXY_URL is a single "
                "fixed address - there is nothing to rotate to. If this "
                "address is the thing being refused, the ladder is out of "
                "rungs here.",
                reason or "manual",
            )
            return

        self.session_id = new_session_id()
        self.requests_on_session = 0
        self.rotations += 1
        logger.info(
            "Rotating residential proxy session -> %s (%s)",
            self.session_id, reason or "manual",
        )

    def note_request(self):
        self.requests_on_session += 1
        limit = self.config.rotate_after
        if limit and self.requests_on_session >= limit:
            self.rotate(reason=f"{limit} requests on session")


def get_proxy_state(crawler) -> ProxyState:
    state = getattr(crawler, "_proxy_state", None)
    if state is None:
        state = ProxyState(ProxyConfig.from_env())
        crawler._proxy_state = state
    return state


############################
# RESIDENTIAL PROXY ATTACH #
############################
class ResidentialProxyMiddleware:
    """
    Decides per request whether it goes out direct or through IPRoyal.

    Per-request override, useful when only some endpoints are protected:
        Request(..., meta={'use_proxy': True})   # force proxy
        Request(..., meta={'use_proxy': False})  # force direct
    """

    def __init__(self, crawler):
        self.state = get_proxy_state(crawler)
        self.config = self.state.config

        if self.config.mode == "off":
            raise NotConfigured("PROXY_MODE=off - residential proxy disabled")

        if not self.config.is_configured:
            # Do not kill the crawl: locally we simply have no credentials and
            # going direct is the correct behaviour. On the server this warning
            # is the thing to grep for when everything starts returning 403.
            logger.warning(
                "PROXY_MODE=%s but IPRoyal credentials are missing - all "
                "requests will go out DIRECT. Set IPROYAL_USERNAME / "
                "IPROYAL_PASSWORD in .env",
                self.config.mode,
            )
            raise NotConfigured("IPRoyal credentials missing")

        logger.info("Residential proxy active: %s", self.config.describe())

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler)

    ###################################################
    # SHOULD THIS PARTICULAR REQUEST USE THE PROXY?   #
    ###################################################
    def _should_use_proxy(self, request) -> bool:
        explicit = request.meta.get("use_proxy")
        if explicit is not None:
            return bool(explicit)

        if self.config.mode == "on":
            return True

        # mode == 'auto': direct until this domain has proven hostile.
        domain = request.url.split("/")[2] if "://" in request.url else ""
        return domain in self.state.blocked_domains

    def process_request(self, request, spider):
        if not self._should_use_proxy(request):
            return None

        self.state.note_request()
        request.meta["proxy"] = self.config.build_url(self.state.session_id)
        request.meta["proxy_session"] = self.state.session_id
        # Marks the request as "already escalated", so the block detector knows
        # a failure here means the IP is burnt rather than that we forgot the proxy.
        request.meta["_via_proxy"] = True
        return None

    ##########################################################
    # A DEAD EXIT NODE LOOKS LIKE A CONNECTION ERROR, NOT 403 #
    ##########################################################
    def process_exception(self, request, exception, spider):
        if request.meta.get("_via_proxy"):
            self.state.rotate(reason=f"transport error: {type(exception).__name__}")
        return None


###################
# BLOCK DETECTION #
###################
class BlockDetectionMiddleware:
    """
    A blocked JSON API rarely says so honestly. It gives you a 403, or a 200
    carrying an HTML challenge page, or an empty body. All three break the
    parser in confusing ways, so we catch them here and escalate.
    """

    # Statuses that mean "we do not like where you are calling from".
    BLOCK_STATUSES = {401, 403, 407, 409, 429, 444, 499, 503}

    # Fingerprints of the usual anti-bot interstitials.
    BODY_SIGNATURES = (
        b"cf-browser-verification",
        b"cf_chl_opt",
        b"Just a moment...",
        b"Checking your browser",
        b"Attention Required! | Cloudflare",
        b"/cdn-cgi/challenge-platform",
        b"Access Denied",
        b"Request unsuccessful. Incapsula",
        b"_Incapsula_Resource",
        b"PerimeterX",
        b"px-captcha",
        b"DataDome",
        b"captcha-delivery.com",
    )

    # Url fragments that mean we were sent to a sign-in page. Matched against
    # the url we ENDED UP at, and only when the url we asked for did not
    # already contain them - otherwise deliberately fetching a login page
    # would count as a block.
    LOGIN_URL_SIGNATURES = (
        "/auth?",
        "/login",
        "/signin",
        "sign_in",
        "page-two-signin",
    )

    def __init__(self, crawler):
        self.crawler = crawler
        self.state = get_proxy_state(crawler)
        self.config = self.state.config
        self.max_escalations = crawler.settings.getint("PROXY_MAX_ESCALATIONS", 3)

        # See _over_budget. domain -> blocks seen this run.
        self.blocks_by_domain = defaultdict(int)
        self.budget = crawler.settings.getint("DOMAIN_BLOCK_BUDGET", 8)
        self.gave_up_on = set()

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler)

    ###################################################################
    # KNOWING WHEN TO STOP KNOCKING                                   #
    ###################################################################
    '''
        Everything else in this class answers "what should we change and try
        again". Nothing answered "should we still be asking at all", and the
        cost of that showed up twice in one afternoon.

        A refusal is not free. Indeed sorts an address into a bucket and the
        bucket has memory: after a burst of refused requests a home connection
        that had been serving 1.19 MB pages went to challenging every single
        request, and stayed there for about eight minutes before recovering on
        its own. The static residential IP did the same thing, from a run that
        had been working, because chasing page two burned it.

        So a run that keeps escalating does not just fail - it spends the
        address's credit and takes the NEXT run's first pages down with it.
        Four searches times four identities is sixteen refusals, delivered in
        under a minute, which is a very efficient way to convince a site that
        this address is worth distrusting.

        Past the budget we stop sending to that domain entirely: not a retry
        with a different hat, no request on the wire at all. The crawl ends
        early with whatever it collected, which is both the honest outcome
        and the one that leaves the address usable in ten minutes rather than
        an hour.
    '''
    def _over_budget(self, domain):
        if not domain or self.budget <= 0:
            return False
        if self.blocks_by_domain[domain] < self.budget:
            return False

        if domain not in self.gave_up_on:
            self.gave_up_on.add(domain)
            self.crawler.stats.set_value(f"blocks/budget_spent/{domain}", True)
            logger.error(
                "%s has refused %s requests this run - stopping. Continuing "
                "would spend this address's remaining credit and leave the "
                "next run worse off; it recovers on its own in minutes if we "
                "stop now. Whatever was collected before this point is kept.",
                domain, self.blocks_by_domain[domain],
            )
        return True

    def process_request(self, request, spider):
        domain = request.url.split("/")[2] if "://" in request.url else ""
        if self._over_budget(domain):
            self.crawler.stats.inc_value("blocks/dropped_after_budget")
            raise IgnoreRequest(f"{domain}: block budget spent this run")
        return None

    ###########################################
    # WHY (IF AT ALL) IS THIS RESPONSE A BLOCK #
    ###########################################
    def _block_reason(self, request, response):
        # Cloudflare says so itself when it acts on a request. Cheaper and
        # more certain than pattern-matching the interstitial it serves, and
        # it names the action - `challenge` on Indeed's 403 - so the log line
        # says what happened instead of just quoting a status code.
        mitigated = response.headers.get("cf-mitigated", b"").decode(
            errors="replace"
        )
        if mitigated:
            return f"cloudflare cf-mitigated={mitigated}"

        if response.status in self.BLOCK_STATUSES:
            return response_status_message(response.status)

        ###################################################################
        # A BLOCK WEARING A 200                                           #
        ###################################################################
        # Indeed answers an ordinary job search from an IP it does not trust
        # with 307 -> secure.indeed.com/auth?...&branding=page-two-signin: a
        # 131 kB HTML sign-in page, served as 200.
        #
        # Every other test below waves it through. The status is fine, no
        # anti-bot vendor fingerprint appears anywhere in it, and the request
        # never set expect_json because the search page is HTML by design. So
        # the parser looked for embedded job data, found none, logged an
        # error - and the spider still exited 0. A production run reported
        # "3/3 spiders succeeded" while Indeed contributed nothing at all.
        #
        # Caught here rather than in the spider so the escalation ladder
        # below gets its chance: a sign-in wall is exactly the case a fresh
        # residential IP might get past.
        #
        # The url we asked for comes from meta["redirect_urls"], NOT from
        # request.url. Scrapy's RedirectMiddleware runs ahead of this one and
        # follows the 307 by issuing a fresh request, so by the time the final
        # response arrives here request.url IS the sign-in page and comparing
        # the two urls compares a value against itself. That is precisely how
        # the first version of this check silently did nothing.
        redirect_chain = request.meta.get("redirect_urls") or []
        if redirect_chain:
            asked_for = redirect_chain[0].lower()
            landed_on = (response.url or request.url or "").lower()
            for signature in self.LOGIN_URL_SIGNATURES:
                if signature in landed_on and signature not in asked_for:
                    return (
                        f"redirected to a sign-in wall "
                        f"({(response.url or request.url)[:120]})"
                    )

        body = response.body or b""

        # An endpoint we asked for JSON from that answers with an HTML page is
        # being intercepted, whatever status code it claims.
        if request.meta.get("expect_json"):
            content_type = response.headers.get("Content-Type", b"").lower()
            if b"json" not in content_type:
                if b"<html" in body[:2000].lower():
                    return f"HTML challenge page instead of JSON ({content_type!r})"
                if not body.strip():
                    return "empty body where JSON was expected"

        head = body[:4000]
        for signature in self.BODY_SIGNATURES:
            if signature in head:
                return f"anti-bot signature {signature.decode(errors='replace')!r}"

        return None

    #########################################################
    # THE OTHER THING WE CAN CHANGE: WHO WE LOOK LIKE       #
    #########################################################
    '''
        A spider using scrapy-impersonate carries meta["impersonate"], the
        browser whose TLS handshake curl_cffi replays, and can carry
        meta["impersonate_candidates"], the ordered list to fall back through.

        This exists because a pinned token is a dependency on someone else's
        detection model, and that model moves without telling us. Indeed's
        spider ran on `chrome131` for a day and then met a Cloudflare
        challenge on every request from an address that had just worked. The
        crawl had no way to try anything else, so it reported zero postings
        and the cause looked like the exit IP - which is where two rounds of
        proxy debugging went.

        Rotating the handshake is also the cheapest rung on the ladder: it
        costs one retry and no metered residential bandwidth, so it is worth
        doing at every escalation rather than only after the proxy options
        run out.
    '''
    def _next_impersonation(self, request):
        """The next token to try, or None when the list is exhausted."""
        candidates = request.meta.get("impersonate_candidates") or []
        current = request.meta.get("impersonate")
        if len(candidates) < 2:
            return None

        try:
            position = candidates.index(current)
        except ValueError:
            return candidates[0] if current != candidates[0] else None

        if position + 1 >= len(candidates):
            return None
        return candidates[position + 1]

    def _wear_identity(self, request, token):
        """
        Point the request at another browser - handshake AND headers.

        scrapy-impersonate forwards request.headers to curl_cffi as they are,
        so swapping only meta["impersonate"] would leave the previous
        browser's User-Agent on the new handshake. The client hints are
        removed outright for Firefox and Safari, neither of which sends them.
        """
        profile = profile_for_impersonate(token)
        request.meta["impersonate"] = token
        request.headers[b"User-Agent"] = profile.user_agent

        for name in (b"sec-ch-ua", b"sec-ch-ua-mobile", b"sec-ch-ua-platform"):
            request.headers.pop(name, None)
        if profile.is_chromium:
            request.headers[b"sec-ch-ua"] = profile.sec_ch_ua
            request.headers[b"sec-ch-ua-mobile"] = profile.sec_ch_ua_mobile
            request.headers[b"sec-ch-ua-platform"] = profile.sec_ch_ua_platform
        return profile

    def process_response(self, request, response, spider):
        reason = self._block_reason(request, response)
        if not reason:
            return response

        self.crawler.stats.inc_value("blocks/detected")
        domain = request.url.split("/")[2] if "://" in request.url else ""
        escalations = request.meta.get("_escalations", 0)

        # A sign-in wall means something specific to a spider carrying an
        # exported session: the session is gone. Only the spider knows whether
        # it had one, so tell it and let it decide whether that matters.
        if "sign-in wall" in reason and hasattr(spider, "note_sign_in_wall"):
            spider.note_sign_in_wall(response.url or request.url)

        self.blocks_by_domain[domain] += 1
        if self._over_budget(domain):
            raise IgnoreRequest(f"{domain}: block budget spent this run")

        if escalations >= self.max_escalations:
            self.crawler.stats.inc_value("blocks/given_up")
            spider.logger.error(
                "BLOCKED after %s escalations (%s): %s",
                escalations, reason, request.url,
            )
            raise IgnoreRequest(f"blocked: {reason}")

        # What the retry will actually ask for - see the comment where the
        # retry is built. Computed here so the log lines below name the url
        # being retried rather than the sign-in page we bounced off.
        original_url = (request.meta.get("redirect_urls") or [None])[0]
        target_url = original_url or request.url

        # The other lever, pulled at every rung because it is free. None once
        # the spider has been through every browser it knows how to be.
        next_token = self._next_impersonation(request)

        # ------------------------------------------------------------------
        # Escalation ladder
        # ------------------------------------------------------------------
        if not request.meta.get("_via_proxy"):
            # Rung 1: we were going direct. The server IP is a datacenter IP,
            # so this is the expected first failure. Switch to residential.
            if self.config.enabled:
                self.state.blocked_domains.add(domain)
                self.crawler.stats.inc_value("blocks/escalated_to_proxy")
                spider.logger.warning(
                    "BLOCKED direct (%s) - retrying %s over residential "
                    "proxy; all further %s requests will use it too",
                    reason, target_url, domain or "same-domain",
                )
                new_meta = {"use_proxy": True}

            elif next_token and not getattr(spider, "session_cookies", None):
                # No proxy to escalate to, but the address is not the only
                # thing we can change. A local run has a perfectly good IP and
                # a handshake the site has learnt to challenge - which is the
                # whole of the Indeed failure, and it used to end right here.
                self.crawler.stats.inc_value("blocks/no_proxy_available")
                spider.logger.warning(
                    "BLOCKED going direct (%s) and no residential proxy is "
                    "configured - retrying %s as %s",
                    reason, target_url, next_token,
                )
                new_meta = {}

            else:
                # Nothing left to change. Hand the response back untouched so
                # RetryMiddleware / HttpErrorMiddleware handle it the way they
                # always have - dropping it here would silently change how the
                # older DOM spiders behave when they run without a proxy.
                #
                # A loaded session_cookies takes this branch even when
                # next_token is available: switching TLS handshake mid-run
                # means the same signed-in cookie gets replayed under two
                # different browser identities, which is the exact anomaly
                # _prefer_the_session_s_browser() warns about elsewhere.
                # Better to stop within budget than make the session look
                # stolen. Unmeasured whether this actually slows the block -
                # 03.08.2026, see the run that prompted it.
                self.crawler.stats.inc_value("blocks/no_proxy_available")
                spider.logger.warning(
                    "BLOCKED going direct (%s) and nothing left to escalate "
                    "to - set PROXY_MODE and the IPROYAL_* variables, or give "
                    "the spider more impersonation candidates: %s",
                    reason, request.url,
                )
                return response
        else:
            # Rung 2+: the residential IP itself is burnt. Get another one.
            self.state.rotate(reason=f"blocked: {reason}")
            self.crawler.stats.inc_value("blocks/rotated_session")
            spider.logger.warning(
                "BLOCKED on proxy session %s (%s) - retrying %s on a fresh IP",
                request.meta.get("proxy_session"), reason, target_url,
            )
            new_meta = {"use_proxy": True}

        # Retry what we originally asked for, not where we were sent.
        #
        # When the block arrived as a redirect, `request` is the redirected
        # request - the sign-in page - because RedirectMiddleware already
        # followed it. Copying that would fetch the sign-in page again on the
        # fresh IP, get a clean 200 with no redirect this time, sail past
        # every check here, and hand the parser a login page: the same silent
        # empty crawl, now with an escalation in the stats to make it look
        # like something was done about it.
        if original_url and original_url != request.url:
            retry = request.replace(url=original_url)
            for key in ("redirect_urls", "redirect_reasons", "redirect_times"):
                retry.meta.pop(key, None)
        else:
            retry = request.copy()

        retry.meta.update(new_meta)
        retry.meta["_escalations"] = escalations + 1
        # Drop the stale proxy so ResidentialProxyMiddleware rebuilds the URL
        # with the current session id.
        retry.meta.pop("proxy", None)
        retry.meta.pop("_via_proxy", None)

        if next_token:
            profile = self._wear_identity(retry, next_token)
            self.crawler.stats.inc_value("blocks/rotated_impersonation")
            spider.logger.info(
                "Switching TLS handshake to %s (identity: %s)",
                next_token, profile.name,
            )

        retry.dont_filter = True
        retry.priority = request.priority + 1
        return retry


###############################################################
# CURL_CFFI TRANSPORT - ACTUALLY REPLAY THE BROWSER HANDSHAKE #
###############################################################
class CurlImpersonateMiddleware:
    '''
        Fetches a request with curl_cffi instead of Scrapy's downloader, so
        the TLS ClientHello is a real browser's rather than Python's.

        WHY NOT scrapy-impersonate, WHICH IS ALREADY IN requirements.txt:
        it is broken against the pinned Scrapy. 1.7.0 (the newest release)
        defines `download_request(self, request)` while Scrapy 2.13.3 calls it
        with `(request, spider)`, so every request dies with

            TypeError: ImpersonateDownloadHandler.download_request() takes 2
            positional arguments but 3 were given

        That went unnoticed for days because the DOWNLOAD_HANDLERS setting
        that would have installed it never took effect: it was written inside
        custom_settings directly after a triple-quoted comment, and Python
        concatenated the two into one enormous dict key. The typo was load-
        bearing - had the setting worked, indeed_cards would have died on
        every request instead of quietly crawling over Scrapy's own
        downloader. See the comment in spiders/kariyernet_cards.py.

        So this replaces the library rather than fixing the setting, and it
        depends on nothing but curl_cffi - the same call tls_probe already
        makes, which is how every handshake measurement in docs/sites.md was
        taken.

        OPT-IN, PER SPIDER. A spider gets this transport only by setting
        IMPERSONATE_WITH_CURL = True. indeed_cards deliberately does NOT:
        it writes meta["impersonate"] too, but it has been crawling perfectly
        well on the plain downloader (773 postings on 31.07.2026) carried by
        the residential proxy and its session cookies. Switching its transport
        would be changing the one thing that works, for a benefit nobody has
        measured.

        Priority 730 is between ResidentialProxyMiddleware (725), which puts
        the proxy url in meta, and Scrapy's HttpProxyMiddleware (750), which
        would strip the credentials out of it into a header curl_cffi never
        sees. It also sits after CookiesMiddleware (700), so the Cookie header
        is already built by the time we copy the headers across.

        KNOWN COST - THIS FETCH BLOCKS THE REACTOR. curl_cffi is synchronous,
        so Twisted stops for the length of every request and CONCURRENT_
        REQUESTS stops meaning anything: the crawl is serial while this
        transport is in use. kariyer.net can afford it - two searches, a
        handful of listing pages, roughly a second each, and its settings ask
        for a 2s delay between requests anyway, which is longer than the stall.
        A spider with sixty requests could not, and that is the second reason
        indeed_cards is left alone. If this ever needs to scale, the fix is to
        run the call in a thread (deferToThread) rather than to widen its use.
    '''

    def __init__(self, crawler):
        self.crawler = crawler
        self.timeout = crawler.settings.getfloat("DOWNLOAD_TIMEOUT", 180)

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler)

    def process_request(self, request, spider):
        if not getattr(spider, "IMPERSONATE_WITH_CURL", False):
            return None

        token = request.meta.get("impersonate")
        if not token:
            # Nothing to replay - let Scrapy download it normally.
            return None

        headers = {
            to_unicode(name): to_unicode(b", ".join(values))
            for name, values in request.headers.items()
        }

        proxy = request.meta.get("proxy")
        proxies = {"http": proxy, "https": proxy} if proxy else None

        try:
            reply = curl_requests.request(
                request.method,
                request.url,
                headers=headers,
                data=request.body or None,
                impersonate=token,
                proxies=proxies,
                timeout=self.timeout,
                # Scrapy's RedirectMiddleware has to see the 3xx itself: a
                # sign-in redirect IS the block signal on Indeed, and
                # following it here would hide it behind a 200.
                allow_redirects=False,
                verify=True,
            )
        except Exception as error:
            # Raised, not swallowed: ResidentialProxyMiddleware.process_
            # exception reads a transport error as "this exit node is dead"
            # and rotates the session. Returning None here would instead
            # re-download the request over Python's TLS and get a refusal
            # that looks like the site's verdict on us.
            spider.logger.warning(
                "curl_cffi (%s) could not fetch %s: %s",
                token, request.url, error,
            )
            raise

        # Multi-value headers matter here - Set-Cookie arrives one per line
        # and dict() would keep only the last of them.
        raw_headers = defaultdict(list)
        try:
            items = reply.headers.multi_items()
        except AttributeError:
            items = reply.headers.items()
        for name, value in items:
            # curl_cffi already decompressed the body, but the header saying
            # so survives. Left in place, HttpCompressionMiddleware would try
            # to decompress plain bytes and fail on a response that is fine.
            if name.lower() in ("content-encoding", "content-length"):
                continue
            raw_headers[name].append(value)

        response_class = responsetypes.from_args(
            headers=raw_headers, url=reply.url, body=reply.content,
        )
        return response_class(
            url=reply.url,
            status=reply.status_code,
            headers=raw_headers,
            body=reply.content,
            request=request,
        )
