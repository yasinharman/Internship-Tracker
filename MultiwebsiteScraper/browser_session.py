"""
BROWSER SESSION EMULATION
=========================

When we hit a site's internal JSON API directly, the request must look like it
came from the site's own frontend. A bare Scrapy request is trivially spotted:
no sec-ch-ua, no Referer/Origin, an Accept header that no browser sends for XHR.

This module keeps one *consistent* browser identity per spider run:
    - User-Agent and sec-ch-* hints always describe the SAME browser
    - document requests (warm-up page) and XHR requests (API) get the header
      sets a real browser would send for each
    - header ORDER matches the browser, because Scrapy sends them in insertion
      order and order itself is part of the fingerprint

Never mix profiles inside a single session; that mismatch is what most
anti-bot vendors alert on.
"""

import random
from dataclasses import dataclass, field


###################
# BROWSER PROFILE #
###################
@dataclass(frozen=True)
class BrowserProfile:
    name: str
    user_agent: str
    accept_language: str = "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7"

    # Chromium-only client hints. Firefox leaves these empty.
    sec_ch_ua: str = ""
    sec_ch_ua_platform: str = ""
    sec_ch_ua_mobile: str = "?0"

    @property
    def is_chromium(self) -> bool:
        return bool(self.sec_ch_ua)


#############################################
# PROFILE POOL (KEEP THESE REALISTIC/FRESH) #
#############################################
# NOTE: an outdated Chrome version is itself a bot signal. Bump these every
# few months to whatever the current stable release is.
PROFILES = [
    BrowserProfile(
        name="chrome-133-win",
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"
        ),
        sec_ch_ua='"Not(A:Brand";v="99", "Google Chrome";v="133", "Chromium";v="133"',
        sec_ch_ua_platform='"Windows"',
    ),
    BrowserProfile(
        name="chrome-132-mac",
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36"
        ),
        sec_ch_ua='"Not A(Brand";v="8", "Chromium";v="132", "Google Chrome";v="132"',
        sec_ch_ua_platform='"macOS"',
    ),
    BrowserProfile(
        name="edge-133-win",
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36 Edg/133.0.0.0"
        ),
        sec_ch_ua='"Not(A:Brand";v="99", "Microsoft Edge";v="133", "Chromium";v="133"',
        sec_ch_ua_platform='"Windows"',
    ),
    BrowserProfile(
        name="firefox-135-win",
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:135.0) "
            "Gecko/20100101 Firefox/135.0"
        ),
        # Firefox sends no client hints at all.
    ),
]

PROFILES_BY_NAME = {p.name: p for p in PROFILES}


def pick_profile(name: str = None) -> BrowserProfile:
    """Return a named profile, or a random one when no name is given."""
    if name:
        try:
            return PROFILES_BY_NAME[name]
        except KeyError:
            raise ValueError(
                f"Unknown browser profile '{name}'. "
                f"Available: {', '.join(PROFILES_BY_NAME)}"
            )
    return random.choice(PROFILES)


##################
# HEADER BUILDER #
##################
class BrowserSession:
    """
    One browser identity, reused for every request a spider makes.

    Two header sets:
      document_headers() -> navigating to a normal page (the warm-up request
                            that collects cookies)
      xhr_headers()      -> fetch()/XHR call the frontend makes to its own API
    """

    def __init__(self, profile: BrowserProfile = None, origin: str = None):
        self.profile = profile or pick_profile()
        # Origin of the site whose API we call, e.g. "https://www.kariyer.net"
        self.origin = (origin or "").rstrip("/")

    ###########################################
    # HEADERS FOR A NORMAL PAGE NAVIGATION    #
    ###########################################
    def document_headers(self, referer: str = None) -> dict:
        p = self.profile
        headers = {}

        if p.is_chromium:
            headers["sec-ch-ua"] = p.sec_ch_ua
            headers["sec-ch-ua-mobile"] = p.sec_ch_ua_mobile
            headers["sec-ch-ua-platform"] = p.sec_ch_ua_platform

        headers["Upgrade-Insecure-Requests"] = "1"
        headers["User-Agent"] = p.user_agent
        headers["Accept"] = (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,image/apng,*/*;q=0.8,"
            "application/signed-exchange;v=b3;q=0.7"
        )
        headers["Sec-Fetch-Site"] = "same-origin" if referer else "none"
        headers["Sec-Fetch-Mode"] = "navigate"
        headers["Sec-Fetch-User"] = "?1"
        headers["Sec-Fetch-Dest"] = "document"
        if referer:
            headers["Referer"] = referer
        headers["Accept-Language"] = p.accept_language

        # NOTE: Accept-Encoding is deliberately NOT set. Scrapy advertises
        # exactly the codecs it can actually decode (see requirements.txt:
        # brotli + zstandard are installed so it advertises br/zstd like a
        # real browser). Hardcoding it here would break decompression.
        return headers

    ###########################################
    # HEADERS FOR AN XHR/FETCH CALL TO AN API #
    ###########################################
    def xhr_headers(self, referer: str = None, extra: dict = None,
                    content_type: str = None) -> dict:
        """
        `referer` should be the *page* the user would have been looking at
        when the frontend fired this API call. Sites check it constantly.
        `content_type` is only set for POST/PUT bodies.
        """
        p = self.profile
        headers = {}

        headers["Accept"] = "application/json, text/plain, */*"
        headers["Accept-Language"] = p.accept_language
        if content_type:
            headers["Content-Type"] = content_type

        if p.is_chromium:
            headers["sec-ch-ua"] = p.sec_ch_ua
            headers["sec-ch-ua-mobile"] = p.sec_ch_ua_mobile
            headers["sec-ch-ua-platform"] = p.sec_ch_ua_platform

        headers["User-Agent"] = p.user_agent
        headers["X-Requested-With"] = "XMLHttpRequest"

        if self.origin:
            headers["Origin"] = self.origin
        if referer:
            headers["Referer"] = referer
        elif self.origin:
            headers["Referer"] = self.origin + "/"

        headers["Sec-Fetch-Site"] = "same-origin"
        headers["Sec-Fetch-Mode"] = "cors"
        headers["Sec-Fetch-Dest"] = "empty"

        # Site-specific tokens go last: x-api-key, authorization,
        # x-csrf-token, x-build-id, cookie-derived headers, ...
        if extra:
            headers.update(extra)

        return {k: v for k, v in headers.items() if v is not None}

    def __repr__(self):
        return f"<BrowserSession {self.profile.name} origin={self.origin!r}>"
