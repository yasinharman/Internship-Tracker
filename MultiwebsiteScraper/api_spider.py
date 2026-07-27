"""
BASE SPIDER FOR THE JSON-API SCRAPING MODE
==========================================

The old spiders asked a site for HTML and dug the fields out of the DOM. That
breaks every time a designer renames a CSS class. The sites' own frontends do
not work that way: they call an internal JSON endpoint and render the result.
We now call the same endpoint.

What this base class handles so each spider does not have to:

  * one consistent browser identity for the whole run (see browser_session.py)
  * an optional warm-up navigation that collects the cookies the API expects
    before any API call is made
  * XHR-shaped headers, Origin/Referer included
  * JSON parsing that fails loudly and legibly instead of throwing a bare
    JSONDecodeError halfway through a 40k response
  * dotted-path field extraction so a spider is mostly a mapping table
  * raw-response dumps for developing a new endpoint (API_DEBUG_DUMP=1)

A concrete spider only needs to supply: the endpoint, the browser-copied
headers, and the JSON -> JobPostItem mapping. See spiders/_api_template.py.
"""

import json
import os
import re
from collections import defaultdict
from datetime import datetime
from urllib.parse import urlparse

import scrapy

from .browser_session import BrowserSession, pick_profile
from .loaders import JsonJobLoader


####################################################
# SAFE LOOKUP INSIDE A DEEPLY NESTED JSON DOCUMENT #
####################################################
def dig(data, path, default=None):
    """
    Read a nested value with a dotted path, without a pile of .get() calls.

        dig(record, "company.name")
        dig(record, "locations.0.city")
        dig(payload, "data.jobSearch.results")

    Any missing key, wrong type or out-of-range index returns `default`
    instead of raising - API payloads are inconsistent and one job posting
    missing a field must not kill the whole crawl.
    """
    if path is None:
        return default

    current = data
    for part in str(path).split("."):
        if current is None:
            return default
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, (list, tuple)):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return default
        else:
            return default

    return default if current is None else current


##################################################
# HTML EMBEDDED IN JSON FIELDS (job descriptions) #
##################################################
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def strip_html(value):
    """Job descriptions inside JSON are almost always HTML fragments."""
    if not isinstance(value, str):
        return value
    text = value.replace("</p>", "\n").replace("<br>", "\n").replace("<br/>", "\n")
    text = _TAG_RE.sub(" ", text)
    text = (
        text.replace("&nbsp;", " ").replace("&amp;", "&")
        .replace("&lt;", "<").replace("&gt;", ">")
        .replace("&quot;", '"').replace("&#39;", "'")
    )
    return _WS_RE.sub(" ", text).strip()


###################
# BASE API SPIDER #
###################
class BaseApiSpider(scrapy.Spider):

    # ---- subclass configuration -------------------------------------------

    # Value written to job_posts.source_site.
    site_name = None

    # Scheme + host of the site, used for Origin/Referer. e.g.
    # "https://www.kariyer.net"
    origin = None

    # A normal page to load before touching the API, so the session picks up
    # whatever cookies the endpoint checks for. None = skip the warm-up.
    warmup_url = None

    # Pin a browser profile ("chrome-133-win", ...) or leave None for random.
    browser_profile_name = None

    # Headers the endpoint needs that a generic XHR does not have: x-api-key,
    # authorization, x-csrf-token, x-build-id... Copy them from DevTools.
    api_headers = {}

    # JSON path to the list of postings inside the response body, e.g.
    # "data.jobs" or "result.items". None means the body IS the list.
    results_path = None

    # field name -> JSON path, or -> callable(record, response) for anything
    # that needs real logic.
    field_map = {}

    # Written when the API omits a field, matching what the old DOM spiders
    # stored. `url` is excluded on purpose: it is the upsert key, so a missing
    # one means the record gets skipped rather than collapsed onto a shared row.
    DEFAULT_VALUE = "N/A"
    DEFAULTED_FIELDS = (
        "job_title", "company", "location", "job_type", "job_description",
    )

    # Pagination runs until the site runs out of results, because the searches
    # are already narrowed by filters (job type, date) to a set small enough to
    # exhaust. This is a CIRCUIT BREAKER, not a target - reaching it means
    # something is wrong, and next_page_allowed() says so loudly.
    MAX_PAGES = 200

    # -----------------------------------------------------------------------

    custom_settings = {
        # Sessions need cookies; that is the whole point of the warm-up.
        "COOKIES_ENABLED": True,
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if not self.origin and self.warmup_url:
            parsed = urlparse(self.warmup_url)
            self.origin = f"{parsed.scheme}://{parsed.netloc}"

        self.session = BrowserSession(
            profile=pick_profile(self.browser_profile_name),
            origin=self.origin,
        )
        self.debug_dump = os.getenv("API_DEBUG_DUMP", "").strip().lower() in (
            "1", "true", "yes", "on",
        )
        self._dump_counter = 0

        # Record keys already returned during this run, per search. Used to
        # notice an API that has started repeating itself.
        self._seen_keys = defaultdict(set)

        # posting key -> set of routes that found it. See note_discovery().
        self._discovery = defaultdict(set)

    def start_requests(self):
        self.logger.info(
            "Browser identity for this run: %s", self.session.profile.name
        )

        if self.warmup_url:
            yield self.document_request(
                self.warmup_url,
                callback=self._after_warmup,
                dont_filter=True,
            )
        else:
            yield from self.api_requests()

    ###########################################################
    # WARM-UP: LOAD A REAL PAGE FIRST TO COLLECT ITS COOKIES  #
    ###########################################################
    def _after_warmup(self, response):
        cookies = response.headers.getlist("Set-Cookie")
        self.logger.info(
            "Warm-up %s -> HTTP %s, %s cookie(s) picked up",
            response.url, response.status, len(cookies),
        )
        # Anything the page embeds (build id, csrf token, api key) can be
        # pulled out here by overriding this hook in the spider.
        self.on_warmup(response)
        yield from self.api_requests()

    def on_warmup(self, response):
        """Override to extract tokens from the warm-up page. Optional."""
        return None

    def api_requests(self):
        """Override: yield the first API request(s) of the crawl."""
        raise NotImplementedError(
            f"{type(self).__name__} must implement api_requests()"
        )

    #########################
    # REQUEST CONSTRUCTORS  #
    #########################
    def document_request(self, url, callback, *, referer=None, **kwargs):
        """A normal page navigation, headers shaped like a browser tab."""
        meta = kwargs.pop("meta", {}) or {}
        headers = self.session.document_headers(referer=referer)
        headers.update(kwargs.pop("headers", {}) or {})
        return scrapy.Request(
            url=url, callback=callback, headers=headers, meta=meta, **kwargs
        )

    def api_request(self, url, callback, *, method="GET", json_body=None,
                    form_body=None, referer=None, headers=None, meta=None,
                    **kwargs):
        """
        An XHR to the site's own JSON API.

        `referer` should be the page a user would be on when the frontend
        fires this call - many endpoints reject a mismatched Referer outright.
        """
        content_type = None
        body = kwargs.pop("body", None)

        if json_body is not None:
            body = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
            content_type = "application/json"
            method = method if method != "GET" else "POST"
        elif form_body is not None:
            from urllib.parse import urlencode
            body = urlencode(form_body).encode("utf-8")
            content_type = "application/x-www-form-urlencoded; charset=UTF-8"
            method = method if method != "GET" else "POST"

        request_headers = self.session.xhr_headers(
            referer=referer,
            extra={**self.api_headers, **(headers or {})},
            content_type=content_type,
        )

        request_meta = {
            # Tells BlockDetectionMiddleware that an HTML answer here means we
            # were intercepted, not that the endpoint moved.
            "expect_json": True,
        }
        if meta:
            request_meta.update(meta)

        return scrapy.Request(
            url=url,
            method=method,
            body=body,
            callback=callback,
            headers=request_headers,
            meta=request_meta,
            **kwargs,
        )

    ##########################################
    # PARSE THE BODY, COMPLAIN USEFULLY      #
    ##########################################
    def parse_json(self, response):
        """
        Returns the decoded body, or None after logging what actually arrived.
        Returning None instead of raising keeps one bad page from aborting a
        whole run; the caller just checks for it.
        """
        self._maybe_dump(response)

        if not response.body:
            self.logger.error("Empty body from %s (HTTP %s)",
                              response.url, response.status)
            return None

        try:
            return json.loads(response.text)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            preview = response.text[:400].replace("\n", " ")
            self.logger.error(
                "Body from %s is not JSON (HTTP %s, content-type=%s): %s\n"
                "First 400 chars: %s",
                response.url,
                response.status,
                response.headers.get("Content-Type", b"").decode(errors="replace"),
                error,
                preview,
            )
            return None

    def _maybe_dump(self, response):
        """API_DEBUG_DUMP=1 writes raw bodies to debug/ while building a spider."""
        if not self.debug_dump:
            return
        self._dump_counter += 1
        folder = os.path.join("debug", self.name)
        os.makedirs(folder, exist_ok=True)
        stamp = datetime.now().strftime("%H%M%S")
        path = os.path.join(folder, f"{self._dump_counter:03d}_{stamp}.json")
        with open(path, "wb") as handle:
            handle.write(response.body)
        self.logger.debug("Dumped raw response -> %s", path)

    ###############################################
    # PULL THE LIST OF POSTINGS OUT OF THE BODY   #
    ###############################################
    def extract_records(self, payload):
        records = dig(payload, self.results_path) if self.results_path else payload
        if records is None:
            self.logger.warning(
                "No records at results_path=%r. Top-level keys: %s",
                self.results_path,
                list(payload)[:20] if isinstance(payload, dict) else type(payload).__name__,
            )
            return []
        if isinstance(records, dict):
            records = [records]
        if not isinstance(records, list):
            self.logger.warning(
                "results_path=%r gave %s, expected a list",
                self.results_path, type(records).__name__,
            )
            return []
        return records

    ###############################################################
    # EXHAUSTIVE PAGINATION, WITHOUT THE RUNAWAY-LOOP FAILURE MODE #
    ###############################################################
    def record_key(self, record):
        """
        Something stable that identifies a posting, used to spot repeats.
        Override if the API uses an unusual id field.
        """
        if not isinstance(record, dict):
            # parsel Selector and friends. NOT repr(): parsel truncates its
            # repr to ~40 characters, so unrelated elements collapse onto the
            # same string, look like repeats, and cut the crawl short.
            getter = getattr(record, "get", None)
            if callable(getter):
                try:
                    return (getter() or repr(record))[:2000]
                except TypeError:
                    pass
            return repr(record)

        for field in ("id", "jobId", "positionId", "adId", "uid", "slug", "url"):
            value = record.get(field)
            if value not in (None, ""):
                return f"{field}={value}"
        # No id field: fall back to the whole record.
        return json.dumps(record, sort_keys=True, ensure_ascii=False)[:500]

    def next_page_allowed(self, page, records, search_key="default"):
        """
        Decide whether to ask for page+1. Call it once per parsed page and only
        yield the next request when it returns True.

        Three ways a crawl ends, and only the first is the happy one:

          1. the page came back empty - the site is out of results

          2. the page was full but every posting on it was already seen. Lots
             of paginated APIs answer an out-of-range page with page 1 instead
             of an error, so "keep going until empty" would loop forever,
             burning metered residential bandwidth and getting us blocked.

          3. MAX_PAGES - a circuit breaker. Reaching it means the searches are
             not narrow enough or detection 2 failed, so it logs an ERROR.
        """
        if not records:
            self.logger.info(
                "[%s] page %s empty - search exhausted", search_key, page
            )
            return False

        seen = self._seen_keys[search_key]
        keys = {self.record_key(record) for record in records}
        fresh = keys - seen
        seen.update(keys)

        if not fresh:
            self.logger.warning(
                "[%s] page %s returned %s posting(s), all already seen this "
                "run - the API is repeating itself, so stopping here instead "
                "of looping. Total collected: %s",
                search_key, page, len(records), len(seen),
            )
            self.crawler.stats.inc_value("pagination/repeated_page")
            return False

        if page >= self.MAX_PAGES:
            self.logger.error(
                "[%s] hit the MAX_PAGES ceiling (%s) with results still "
                "coming. Narrow the search (job type / date / keyword) or "
                "raise MAX_PAGES deliberately.",
                search_key, self.MAX_PAGES,
            )
            self.crawler.stats.inc_value("pagination/hit_ceiling")
            return False

        self.logger.debug(
            "[%s] page %s: %s new of %s", search_key, page, len(fresh), len(records)
        )
        return True

    ###############################################################
    # WHICH ROUTE FOUND WHAT - THE FILTER-LEAK DETECTOR           #
    ###############################################################
    '''
        Every board so far classifies its own postings badly, so each spider
        looks for the same posting by more than one route: the site's own
        filter or category page, and a broader scan matched on the title.

        The question that matters is not "did we find things" but "would we
        have missed something if we trusted only one route". Recording which
        route found each posting answers it directly:

          * a route with a unique contribution of 0, run after run, is
            redundant and can be dropped
          * a route that is the SOLE finder of postings is carrying the crawl,
            and the other route is leaking

        This is how we noticed that kariyer.net hides 85% of its internships
        behind a working-type code no employer uses. Without the counter it
        took two manual audits to see it.
    '''
    def note_discovery(self, key, route):
        """Record that `route` found the posting identified by `key`."""
        self._discovery[key].add(route)

    def _log_discovery_report(self):
        if not self._discovery:
            return

        routes = {}
        sole = defaultdict(int)
        for key, found_by in self._discovery.items():
            for route in found_by:
                routes[route] = routes.get(route, 0) + 1
            if len(found_by) == 1:
                sole[next(iter(found_by))] += 1

        self.logger.info(
            "Discovery report - %s unique posting(s) via %s route(s):",
            len(self._discovery), len(routes),
        )
        for route, count in sorted(routes.items(), key=lambda kv: -kv[1]):
            only = sole.get(route, 0)
            self.logger.info(
                "  %-14s found %3s  |  sole finder of %s", route, count, only
            )
            self.crawler.stats.set_value(f"discovery/{route}/found", count)
            self.crawler.stats.set_value(f"discovery/{route}/sole", only)

        if len(routes) > 1:
            for route, count in sole.items():
                if count:
                    self.logger.warning(
                        "%s posting(s) were found ONLY by '%s'. The other "
                        "route(s) are leaking - do not drop this one.",
                        count, route,
                    )
        redundant = [r for r in routes if not sole.get(r)]
        if redundant and len(routes) > 1:
            self.logger.info(
                "Route(s) with no unique finds this run: %s. Harmless, but if "
                "that holds for weeks they are costing requests for nothing.",
                ", ".join(sorted(redundant)),
            )

    def closed(self, reason):
        self._log_discovery_report()

    ###################################################
    # ONE JSON RECORD -> ONE JobPostItem, VIA field_map #
    ###################################################
    def build_item(self, record, response=None, extra=None):
        """
        Turn one API record into an item using `field_map`.

        A mapping value is either a dotted path, or a callable taking
        (record, response) for the cases a path cannot express:

            field_map = {
                "job_title":   "title",
                "company":     "company.displayName",
                "url":         lambda record, response: BASE + record["slug"],
            }
        """
        loader = JsonJobLoader(response=response) if response else JsonJobLoader()

        for field_name, source in self.field_map.items():
            if callable(source):
                try:
                    value = source(record, response)
                except Exception as error:
                    self.logger.warning(
                        "field_map[%r] raised %s: %s", field_name,
                        type(error).__name__, error,
                    )
                    value = None
            else:
                value = dig(record, source)

            if field_name == "job_description":
                value = strip_html(value)

            if value in (None, "") and field_name in self.DEFAULTED_FIELDS:
                value = self.DEFAULT_VALUE

            loader.add_value(field_name, value)

        if "source_site" not in self.field_map:
            loader.add_value("source_site", self.site_name or self.name)

        for field_name, value in (extra or {}).items():
            loader.add_value(field_name, value)

        item = loader.load_item()

        # job_posts.url is UNIQUE NOT NULL and drives the upsert, so a record
        # without one cannot be stored at all.
        if not item.get("url"):
            self.logger.warning(
                "Skipping record with no url. Keys present: %s",
                list(record)[:20] if isinstance(record, dict) else type(record).__name__,
            )
            self.crawler.stats.inc_value("items/skipped_no_url")
            return None

        return item
