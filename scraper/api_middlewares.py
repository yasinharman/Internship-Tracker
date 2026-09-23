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
import os
from collections import defaultdict
from urllib.parse import urlparse

from curl_cffi import requests as curl_requests
from scrapy import signals
from scrapy.exceptions import IgnoreRequest, NotConfigured
from scrapy.responsetypes import responsetypes
from scrapy.utils.python import to_unicode
from scrapy.utils.response import response_status_message

from . import cookie_jars
from .browser_session import profile_for_impersonate
from .proxy import ProxyConfig, new_session_id
from .proxy_pool import ProxyPool, site_of
from .throttle import SlotThrottle, sleep_out_loud

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


#####################################################
# THE BOUGHT STATIC IP POOL - see proxy_pool.py     #
#####################################################
def get_proxy_pool(crawler):
    """One ProxyPool per crawl, shared with BlockDetectionMiddleware."""
    pool = getattr(crawler, "_proxy_pool", None)
    if pool is None:
        pool = ProxyPool.from_env()
        crawler._proxy_pool = pool
    return pool


def cookie_jars_on():
    """
    Whether a pooled request carries the cookies its address already has for
    that site.

    Harman, 23.09.2026: "çerez oturumu her sitede her zaman kullanılmalı bu
    standart olması lazım yoksa ip ler erir". Behind a switch only until it
    has been measured once on a live site - a full run was in flight the
    afternoon it was written, and changing what the run was doing halfway
    would have spoiled both the run and the measurement.
    """
    return os.getenv("COOKIE_JARS", "0").strip().lower() in ("1", "true", "yes", "on")


def pool_spiders():
    return {
        name.strip() for name in os.getenv("PROXY_POOL_SPIDERS", "").split(",")
        if name.strip()
    }


class ProxyPoolMiddleware:
    """
    Sends a listed spider's requests from the pool: one address per site,
    the next one when the site refuses it (BlockDetectionMiddleware calls
    back into the pool for that).

    Opt-in by name, PROXY_POOL_SPIDERS=kariyernet_cards,kariyernet_check,...
    - nothing changes for a spider that is not listed. Independent of
    PROXY_MODE, which drives the older IPRoyal path.

    Priority 727: after ResidentialProxyMiddleware (725), so for a listed
    spider the pool's address is the one that stands; before the two
    transports that read meta["proxy"] - PlaywrightMiddleware (729) and
    CurlImpersonateMiddleware (730) - and Scrapy's HttpProxyMiddleware (750).
    """

    def __init__(self, crawler):
        self.spiders = pool_spiders()
        if not self.spiders:
            raise NotConfigured("PROXY_POOL_SPIDERS is empty")
        self.crawler = crawler
        # (site, ip) -> the jar as it stands this run, and which of them have
        # changed since they were read. Written back when the spider closes.
        self._jars = {}
        self._dirty = set()
        crawler.signals.connect(self._closed, signal=signals.spider_closed)

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler)

    def process_request(self, request, spider):
        if spider.name not in self.spiders or request.meta.get("use_proxy") is False:
            return None

        pool = get_proxy_pool(self.crawler)
        site = site_of(request.url)
        address = pool.address_for(site)
        if address is None:
            self.crawler.stats.inc_value("pool/dropped_no_address")
            raise IgnoreRequest(f"{site}: {pool.given_up.get(site, 'no pool address left')}")

        pool.note_request(site, address)
        self.crawler.stats.inc_value(f"pool/requests/{site}")
        request.meta["proxy"] = address.url
        request.meta["pool_address"] = address.ip
        # Same flag the IPRoyal path sets: this request is already on a proxy.
        request.meta["_via_proxy"] = True

        if cookie_jars_on():
            self._carry_the_jar(request, site, address.ip)
        return None

    ###################################################################
    # THE ADDRESS ARRIVES AS ITSELF, NOT AS A STRANGER                #
    ###################################################################
    def _jar(self, site, ip):
        """This run's copy of the (site, address) jar, read from disk once."""
        key = (site, ip)
        if key not in self._jars:
            self._jars[key] = cookie_jars.load(site, ip) or {"cookies": []}
        return self._jars[key]

    def _carry_the_jar(self, request, site, ip):
        """
        Put this address's cookies for this site on the request.

        The header is written HERE rather than left to Scrapy's
        CookiesMiddleware (700), which keeps one jar for the whole spider and
        would hand kariyer.net's cookies to whichever address happens to go
        next. This middleware runs after it on the request path, so what is
        set here is what is sent. PlaywrightMiddleware drops the header and
        uses the same jar as a browser storage_state instead - a browser
        keeps its own cookies.
        """
        request.meta["cookie_jar"] = (site, ip)
        header = cookie_jars.cookie_header(self._jar(site, ip), urlparse(request.url).netloc)
        if header:
            request.headers[b"Cookie"] = header

    def process_response(self, request, response, spider):
        """Keep whatever the site handed this address."""
        key = request.meta.get("cookie_jar")
        handed = response.headers.getlist("Set-Cookie") if key else []
        if handed:
            site, ip = key
            host = urlparse(response.url).netloc
            self._jars[key] = cookie_jars.remember(self._jar(site, ip), handed, host)
            self._dirty.add(key)
        return response

    def _closed(self, spider):
        for (site, ip) in self._dirty:
            cookie_jars.save(site, ip, self._jars[(site, ip)])
        pool = getattr(self.crawler, "_proxy_pool", None)
        if pool is not None:
            pool.close()


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
        # LinkedIn's wall for a request it will not serve without an account.
        # Its other one, /uas/login, needs no entry - "/login" already covers
        # it. Worth having because it is what tells an expired burner session
        # apart from an address being refused, exactly as page-two-signin does
        # for Indeed (see IndeedCardsSpider.note_sign_in_wall).
        "/authwall",
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

        # See _cool_off. domain -> blocks since the last response that was not
        # one, and how many pauses this run has already spent.
        self.blocks_in_a_row = defaultdict(int)
        self.cooldowns_taken = 0

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

    ###################################################################
    # THE OTHER ANSWER TO A BLOCK: WAIT, THEN CARRY ON                #
    ###################################################################
    '''
        _over_budget above ends the run. That is right when there is nothing
        left to change and every further request is spending the address's
        credit for nothing - which was the whole story while the ladder was
        the only tool. It is the wrong answer for a spider with hours to
        spend and a site whose refusals expire.

        MEASURED 10.09.2026 on kariyer.net, first live run through a windowed
        browser: ten pages served, then every request refused, in one step,
        and it stayed refused for the rest of the run. The block is a STATE,
        not a coin flip - so retrying immediately, however many hats we put
        on, cannot work, and eight tries at it is just eight more refusals on
        an address that needs quiet.

        Quiet is exactly what is cheap here. The crawl is thirty-odd pages on
        a job that runs overnight, so ten minutes of doing nothing costs the
        run nothing and is the one thing documented to actually clear this -
        docs/sites/indeed.md measured a home address recovering on its own in
        about eight minutes after the same treatment.

        OPT-IN, so the spiders that would rather fail fast still do. A spider
        sets BLOCK_COOLDOWN_S to ask for it; kariyer.net is the only one that
        does. Three things keep this from becoming an infinite crawl:

          * the pause only starts after BLOCK_COOLDOWN_AFTER refusals IN A
            ROW, so a single blip is still just a retry
          * BLOCK_COOLDOWNS_ALLOWED caps how many pauses one run may take
          * once they are used up, the budget takes over again and ends the
            run the way it always did

        The wait blocks the reactor, like every other wait in this project -
        see throttle.py - and says so once every thirty seconds, because ten
        silent minutes is indistinguishable from a hang.
    '''
    def _cool_off(self, request, spider, domain, reason):
        """
        Wait out a refusal and hand back a retry, or None to let the caller
        escalate the way it always has.
        """
        seconds = getattr(spider, "BLOCK_COOLDOWN_S", 0)
        if not seconds:
            return None

        after = getattr(spider, "BLOCK_COOLDOWN_AFTER", 2)
        allowed = getattr(spider, "BLOCK_COOLDOWNS_ALLOWED", 3)

        if self.blocks_in_a_row[domain] < after:
            return None

        if self.cooldowns_taken >= allowed:
            logger.warning(
                "%s is still refusing us and this run has already waited %s "
                "time(s) - not waiting again. Whatever the site is unhappy "
                "about, it is not a burst that a pause fixes.",
                domain, self.cooldowns_taken,
            )
            return None

        self.cooldowns_taken += 1
        self.crawler.stats.inc_value("blocks/cooldowns")
        logger.warning(
            "%s has refused %s requests in a row (%s). Pausing %s minute(s) "
            "and picking up where this left off - refusals here expire, and "
            "this crawl has nowhere to be. Pause %s of %s.",
            domain, self.blocks_in_a_row[domain], reason,
            round(seconds / 60), self.cooldowns_taken, allowed,
        )
        sleep_out_loud(seconds, f"cool-off: {domain} refused us", every_s=30)

        # The run starts again from here as far as both counters are
        # concerned. Not resetting them would mean the pause bought time and
        # nothing else: the next refusal would still land on a budget that a
        # burst before the pause had already half spent.
        self.blocks_in_a_row[domain] = 0
        self.blocks_by_domain[domain] = 0

        retry = request.copy()
        retry.meta.pop("proxy", None)
        retry.meta.pop("_via_proxy", None)
        retry.dont_filter = True
        retry.priority = request.priority + 1
        return retry

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

        # A VERDICT ON THE CLIENT, NOT ON THE ADDRESS - measured 23.09.2026.
        # Indeed answers a posting page opened by our BROWSER with 401 and a
        # page that redirects to
        #   /account/login?branding=login-required&from=bot-detection-anonymous
        # while curl_cffi was served 81 posting pages from the same pool
        # addresses that afternoon. It is not the address: resting one for 24
        # hours over this costs a good address and changes nothing, because
        # the next one gets the same answer.
        if b"from=bot-detection-anonymous" in response.body:
            return "indeed bot-detection: sign in required (the client, not the address)"

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
        domain = request.url.split("/")[2] if "://" in request.url else ""

        reason = self._block_reason(request, response)
        if not reason:
            # A served page ends the streak. _cool_off counts refusals IN A
            # ROW rather than in total, because a run that is mostly working
            # with the odd refusal in it does not want a ten-minute pause.
            self.blocks_in_a_row[domain] = 0
            if request.meta.get("pool_address"):
                original = (request.meta.get("redirect_urls") or [None])[0] or request.url
                get_proxy_pool(self.crawler).note_answer(site_of(original))
            return response

        self.crawler.stats.inc_value("blocks/detected")
        self.blocks_in_a_row[domain] += 1
        escalations = request.meta.get("_escalations", 0)

        # A request from the bought pool is answered by the pool: this
        # address rests for this site and the request is retried from the
        # next one. It spends neither the site's block budget nor a cool-off.
        # The pool's own cap (PROXY_POOL_MAX_SWITCHES) is what ends a site's
        # run, and moving on beats waiting when a refusal is a state that
        # does not clear - kariyer.net's press-and-hold page never does.
        pool_ip = request.meta.get("pool_address")
        if pool_ip:
            return self._retry_from_the_pool(request, spider, pool_ip, reason, escalations)

        # Before spending the budget on it. A spider that has asked to wait
        # would rather wait than be given up on, and waiting is the only
        # answer measured to work against a refusal that has become a state.
        waited = self._cool_off(request, spider, domain, reason)
        if waited is not None:
            return waited

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

        retry = self._retry_of(request)
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

    @staticmethod
    def _retry_of(request):
        """
        Retry what we originally asked for, not where we were sent.

        When the block arrived as a redirect, `request` is the redirected
        request - the sign-in page - because RedirectMiddleware already
        followed it. Copying that would fetch the sign-in page again on the
        fresh IP, get a clean 200 with no redirect this time, sail past every
        check here, and hand the parser a login page: the same silent empty
        crawl, now with an escalation in the stats to make it look like
        something was done about it.
        """
        original_url = (request.meta.get("redirect_urls") or [None])[0]
        if original_url and original_url != request.url:
            retry = request.replace(url=original_url)
            for key in ("redirect_urls", "redirect_reasons", "redirect_times"):
                retry.meta.pop(key, None)
            return retry
        return request.copy()

    def _retry_from_the_pool(self, request, spider, pool_ip, reason, escalations):
        """
        Rest the refused address for this site, retry from the next one - or
        end the site's run when the pool says there is none.

        The TLS identity is left alone on purpose: the address is the one
        thing that changes, so a retry that passes says the address was the
        problem (memory: control-must-differ-by-one-thing).
        """
        pool = get_proxy_pool(self.crawler)
        original_url = (request.meta.get("redirect_urls") or [None])[0] or request.url
        site = site_of(original_url)

        # A refusal aimed at the client rests nothing: the address is fine and
        # the next one would be told exactly the same thing. The site's run
        # ends here instead, and the transport is what has to change.
        if "the client, not the address" in reason:
            self.crawler.stats.inc_value("pool/client_refused")
            pool.give_up(site, reason)
            raise IgnoreRequest(f"{site}: {reason}")

        following = pool.on_refusal(site, pool_ip, reason)
        if following is None:
            self.crawler.stats.inc_value("pool/gave_up")
            raise IgnoreRequest(f"{site}: {pool.given_up.get(site, 'pool exhausted')}")

        self.crawler.stats.inc_value("pool/switched")
        spider.logger.warning(
            "BLOCKED on pool address %s (%s) - retrying %s from %s",
            pool_ip, reason, original_url, following.label,
        )
        retry = self._retry_of(request)
        retry.meta["_escalations"] = escalations + 1
        # ProxyPoolMiddleware puts the current address back on the way out.
        for key in ("proxy", "pool_address", "_via_proxy"):
            retry.meta.pop(key, None)
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
        makes, which is how every handshake measurement in docs/sites/indeed.md was
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

        # This transport never reaches Downloader._enqueue_request, so
        # DOWNLOAD_DELAY does not apply to it on its own. See throttle.py -
        # the same hole exists in playwright_middleware.py.
        self.throttle = SlotThrottle(crawler.settings)

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

        self.throttle.wait_turn(request)

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
