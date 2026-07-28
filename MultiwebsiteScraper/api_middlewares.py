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

from scrapy.exceptions import IgnoreRequest, NotConfigured
from scrapy.utils.response import response_status_message

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

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler)

    ###########################################
    # WHY (IF AT ALL) IS THIS RESPONSE A BLOCK #
    ###########################################
    def _block_reason(self, request, response):
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

    def process_response(self, request, response, spider):
        reason = self._block_reason(request, response)
        if not reason:
            return response

        self.crawler.stats.inc_value("blocks/detected")
        domain = request.url.split("/")[2] if "://" in request.url else ""
        escalations = request.meta.get("_escalations", 0)

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

        # ------------------------------------------------------------------
        # Escalation ladder
        # ------------------------------------------------------------------
        if not request.meta.get("_via_proxy"):
            # Rung 1: we were going direct. The server IP is a datacenter IP,
            # so this is the expected first failure. Switch to residential.
            if not self.config.enabled:
                # Nothing to escalate to. Hand the response back untouched so
                # RetryMiddleware / HttpErrorMiddleware handle it the way they
                # always have - dropping it here would silently change how the
                # older DOM spiders behave when they run without a proxy.
                self.crawler.stats.inc_value("blocks/no_proxy_available")
                spider.logger.warning(
                    "BLOCKED going direct (%s) and no residential proxy is "
                    "configured - set PROXY_MODE and the IPROYAL_* variables "
                    "to escalate: %s", reason, request.url,
                )
                return response

            self.state.blocked_domains.add(domain)
            self.crawler.stats.inc_value("blocks/escalated_to_proxy")
            spider.logger.warning(
                "BLOCKED direct (%s) - retrying %s over residential proxy; "
                "all further %s requests will use it too",
                reason, target_url, domain or "same-domain",
            )
            new_meta = {"use_proxy": True}
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
        retry.dont_filter = True
        retry.priority = request.priority + 1
        return retry
