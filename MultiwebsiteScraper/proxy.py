"""
RESIDENTIAL PROXY CONFIGURATION (IPRoyal)
=========================================

The bot runs on a server whose IP belongs to a datacenter ASN. Job boards
routinely refuse JSON API calls from those ranges, so requests get routed
through IPRoyal residential IPs instead.

Everything is driven by environment variables so no credential ever lands in
the repo. See .env.example for the full list.

    PROXY_MODE=off    -> never use the proxy (local development)
    PROXY_MODE=auto   -> go direct first, switch to the proxy the moment a
                         block is detected (default: cheapest on bandwidth)
    PROXY_MODE=on     -> route every request through the proxy

Sticky sessions: IPRoyal keeps you on the same exit IP as long as the
`_session-<id>` token in the password stays the same. We want that — a session
that changes IP mid-pagination looks far more suspicious than one that
doesn't. The session is rotated deliberately: after N requests, or straight
away when we get blocked.

Quick credential check (no Scrapy involved):

    python -m MultiwebsiteScraper.proxy
"""

import os
import random
import string
from dataclasses import dataclass
from urllib.parse import quote

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # dotenv is optional at runtime
    pass


##########################
# SMALL ENV-READ HELPERS #
##########################
def _env(key, default=None):
    value = os.getenv(key)
    return value if value not in (None, "") else default


def _env_bool(key, default=False):
    value = _env(key)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on", "evet")


def _env_int(key, default):
    try:
        return int(_env(key, default))
    except (TypeError, ValueError):
        return default


def _country_from_env():
    """
    Exit country, distinguishing "unset" from "deliberately blank".

    os.getenv returns None when the variable is absent and "" when it is
    present but empty - the difference _env() throws away, and the difference
    that decides between a Turkish exit IP and the worldwide pool.
    """
    raw = os.getenv("IPROYAL_COUNTRY")
    if raw is None:
        return "tr"
    return raw.strip().lower()


def new_session_id(length=10):
    """Random token for IPRoyal's `_session-<id>` sticky parameter."""
    alphabet = string.ascii_lowercase + string.digits
    return "".join(random.choices(alphabet, k=length))


################
# PROXY CONFIG #
################
@dataclass
class ProxyConfig:
    mode: str = "auto"              # off | auto | on
    host: str = ""
    port: str = ""
    username: str = ""
    password: str = ""
    country: str = "tr"             # exit country; job boards are TR-facing
    lifetime: str = "30m"           # how long IPRoyal holds one sticky IP
    rotate_after: int = 50          # rotate the session every N requests
    full_url: str = ""              # PROXY_URL overrides everything above

    ##############################################
    # BUILD THE CONFIG FROM ENVIRONMENT VARIABLES #
    ##############################################
    @classmethod
    def from_env(cls):
        mode = (_env("PROXY_MODE", "auto") or "auto").strip().lower()
        if mode not in ("off", "auto", "on"):
            mode = "auto"

        # Legacy switch: PROXY_ENABLED=false wins over PROXY_MODE.
        if not _env_bool("PROXY_ENABLED", True):
            mode = "off"

        return cls(
            mode=mode,
            host=_env("IPROYAL_HOST", "geo.iproyal.com"),
            port=_env("IPROYAL_PORT", "12321"),
            username=_env("IPROYAL_USERNAME", ""),
            password=_env("IPROYAL_PASSWORD", ""),
            # `IPROYAL_COUNTRY=` - present but blank - has to mean "any
            # country", because that is the only way to reach the worldwide
            # exit pool: the country is a token we put in the proxy password
            # on every request, not a setting in the IPRoyal dashboard.
            #
            # _env() cannot express it (it maps "" to the default), and the
            # old `or "tr"` closed the door a second time, so every value of
            # this variable produced a Turkish exit IP. That matters the day
            # a site burns the TR pool: the obvious experiment silently
            # changes nothing and you conclude the worldwide pool is blocked
            # too. Read the raw variable so a deliberate blank survives;
            # unset still means Turkey, since the boards are TR-facing.
            country=_country_from_env(),
            lifetime=_env("IPROYAL_SESSION_LIFETIME", "30m"),
            rotate_after=_env_int("PROXY_ROTATE_AFTER", 50),
            full_url=_env("PROXY_URL", ""),
        )

    ###########################################
    # IS THERE ENOUGH INFO TO ACTUALLY DIAL? #
    ###########################################
    @property
    def is_configured(self) -> bool:
        if self.full_url:
            return True
        return bool(self.host and self.port and self.username and self.password)

    @property
    def enabled(self) -> bool:
        return self.mode != "off" and self.is_configured

    ##########################################################
    # ONE FIXED EXIT IP, OR A POOL WE CAN ASK FOR ANOTHER?   #
    ##########################################################
    @property
    def is_static(self) -> bool:
        """
        True for a dedicated address - IPRoyal's static residential / ISP
        product, or any PROXY_URL pointing at a single host.

        Worth knowing because half of this module does not apply to one.
        Sticky sessions, `_session-<id>`, lifetime, rotate_after and the
        block detector's "burn this IP and take another" rung all assume a
        pool standing behind the endpoint. With a static address the rotation
        still runs, still logs, still counts - and lands on the same IP every
        time, which reads in the logs as three fresh addresses all refusing
        us. That is a misleading diagnosis, not a working fallback.

        The rest of the code checks this and says so plainly instead.
        """
        return bool(self.full_url)

    ####################################################
    # IPROYAL PACKS ITS OPTIONS INTO THE PASSWORD FIELD #
    ####################################################
    def _password_for(self, session_id: str) -> str:
        """
        IPRoyal syntax:
            <password>_country-<cc>_session-<id>_lifetime-<ttl>
        Omitting a token means "let IPRoyal decide", e.g. country="" gives a
        random worldwide exit IP.
        """
        parts = [self.password]
        if self.country:
            parts.append(f"country-{self.country}")
        if session_id:
            parts.append(f"session-{session_id}")
            if self.lifetime:
                parts.append(f"lifetime-{self.lifetime}")
        return "_".join(parts)

    ###############################################
    # FINAL PROXY URL THAT GOES INTO request.meta #
    ###############################################
    def build_url(self, session_id: str = "") -> str:
        """
        Credentials are embedded in the URL on purpose: Scrapy's built-in
        HttpProxyMiddleware strips them out and turns them into a proper
        Proxy-Authorization header for us.
        """
        if self.full_url:
            return self.full_url

        user = quote(self.username, safe="")
        pwd = quote(self._password_for(session_id), safe="")
        return f"http://{user}:{pwd}@{self.host}:{self.port}"

    ##################################################
    # SAFE-TO-LOG VERSION (NEVER PRINT THE PASSWORD) #
    ##################################################
    def describe(self, session_id: str = "") -> str:
        if not self.is_configured:
            return f"proxy mode={self.mode} (NOT CONFIGURED)"
        if self.full_url:
            return f"proxy mode={self.mode} url=PROXY_URL(custom)"
        return (
            f"proxy mode={self.mode} host={self.host}:{self.port} "
            f"user={self.username} country={self.country or 'any'} "
            f"session={session_id or '-'} lifetime={self.lifetime} "
            f"rotate_after={self.rotate_after}"
        )


#############################################
# STANDALONE CHECK: python -m ...proxy      #
#############################################
def _selftest():
    """Send one request through the proxy and print the exit IP."""
    import json
    import urllib.request

    config = ProxyConfig.from_env()
    session_id = new_session_id()
    print(config.describe(session_id))

    if not config.is_configured:
        print(
            "\nMissing credentials. Fill IPROYAL_USERNAME / IPROYAL_PASSWORD "
            "in .env (see .env.example)."
        )
        return

    proxy_url = config.build_url(session_id)
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
    )

    def show(label, use_proxy):
        target = "https://ipinfo.io/json"
        try:
            fetch = opener.open if use_proxy else urllib.request.urlopen
            with fetch(target, timeout=30) as response:
                data = json.loads(response.read().decode("utf-8"))
            print(
                f"{label:9} ip={data.get('ip')} "
                f"country={data.get('country')} org={data.get('org')}"
            )
        except Exception as error:
            print(f"{label:9} FAILED: {error}")

    show("direct:", False)
    show("proxy:", True)

    # Same session id must return the same IP; that is what "sticky" means.
    show("proxy:", True)


if __name__ == "__main__":
    _selftest()
