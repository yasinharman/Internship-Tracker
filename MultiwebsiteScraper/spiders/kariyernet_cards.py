"""
KARIYER.NET - LISTING CARD SPIDER
=================================

kariyer.net has no JSON listing endpoint. Its pagination is plain
`<a href="/is-ilanlari?cp=2">` navigation and the page is server-rendered, so
there is no XHR to intercept - see docs/sites.md.

That turned out not to matter, because every ad card on the listing page is a
`<div data-test="ad-card">` carrying the data as attributes:

    worktypeid="P" worktypetext="Yarı zamanlı" workmodeltext="İş Yerinde"
    positionname="..." positionid="1172" companyid="67293"
    sectorid="006011000" sectorname="..." cityid="34" cityname="İstanbul(Avr.)"

So the listing page already answers the question we care about - is this
posting part-time or an internship - without opening the posting.

That drives the shape of this spider:

    1. page through the filtered search (Istanbul + IT), reading cards
    2. keep only worktypeid in {P, S}
    3. request the detail page ONLY for those, purely to get the description

The site's own filter panel has no combined "part-time or internship" option,
so the split happens here instead. It still costs almost nothing: roughly one
in ten cards survives, so nine out of ten detail pages are never fetched.

Attribute names are matched in lowercase - HTML parsers normalise
`workTypeId` to `worktypeid`, and the CamelCase form silently matches nothing.
"""

import os
from urllib.parse import urlencode, urlparse, parse_qsl, urlunparse

from ..api_spider import BaseApiSpider
from ..browser_session import BrowserSession, profile_for_impersonate
from ..job_filters import looks_like_internship
from ..loaders import KariyerNetLoader


class KariyerNetCardsSpider(BaseApiSpider):
    name = "kariyernet_cards"

    site_name = "kariyernet.com"
    origin = "https://www.kariyer.net"
    allowed_domains = ["kariyer.net"]

    # No warm-up: the listing page is the first thing a visitor loads anyway,
    # and it hands us its own cookies.
    warmup_url = None

    ##########################################################
    # THE SEARCH - PASTE THE FILTERED URL FROM THE ADDRESS BAR #
    ##########################################################
    '''
        Because the site is server-rendered, its filters live in the page URL.
        Apply them in the UI (Departman = IT/software, Şehir = İstanbul) and
        paste the resulting address here, without any `cp=` page parameter -
        pagination is added by the spider.

        Parameters in the current search:
            ct = city plate numbers. Istanbul is TWO codes - 34 (European
                 side) and 82 (Asian side); using only 34 loses half the city.
            cs = sector code. 001000000 = Bilişim (IT). This maps exactly onto
                 the `sectorid` attribute on the ad cards, so it can be
                 verified after the fact.
            cp = current page, added by the spider.

        The `/istanbul-bilisim` path segment is an SEO slug. Adding `cp=2`
        makes the site 301 to `/istanbul-bilisim-2?...&cp=2`; Scrapy follows
        that automatically, so there is no need to build the slug ourselves.

        Working type is deliberately NOT filtered here: the site offers no
        "part-time OR internship" combination, so we take the field+city
        result set and split it while parsing.
    '''
    '''
        Two narrow searches rather than one broad one. Both are filtered by
        DEPARTMENT (`wa`), not by sector.

        That distinction did most of the work here. Sector describes what the
        COMPANY does, department describes what the ROLE is. Filtering on
        sector=Bilişim returned mostly sales and office jobs at IT companies,
        while missing the developer internship at a shoe manufacturer and the
        e-commerce role at a car dealer - both of which the department filter
        finds immediately.

        "parttime" - the site's part-time listing. Kept EXACTLY as the site
                     produced it: `tpst` is coupled to the URL slug, and
                     `/is-ilanlari?...&tpst=4` without the matching
                     `istanbul-part+time` slug returns nothing at all. So this
                     URL is copied from the address bar, not assembled here.

        "staj"     - the site's internship search, a slug search over titles
                     rather than a working-type filter. Worth its own search
                     twice over: it finds internships across every department
                     and, unlike the working-type codes, it does not depend on
                     how the employer classified the post.

        Both result sets are small - roughly 6 and 26 postings, one page each -
        so this costs almost nothing to run daily. Overlap between them is
        free: the pipeline upserts on url.

        `ct=34,82` is Istanbul: 34 European side, 82 Asian side.
        `wa=...` is the department list chosen in the UI. To change either,
        redo the search on the site and paste the new address here.
    '''
    DEPARTMENTS = "ct=34,82&wa=2,5,22,54,55,60,63,78,87"

    SEARCHES = {
        "parttime": (
            "https://www.kariyer.net/is-ilanlari/istanbul-part+time"
            f"?{DEPARTMENTS}&tpst=4"
        ),
        "staj": (
            f"https://www.kariyer.net/is-ilanlari/stajyer?{DEPARTMENTS}"
        ),
    }

    # Searches whose every result is an internship by definition, because the
    # site's own internship search produced it. Everything they return is kept
    # and labelled Internship without consulting the title or the work-type
    # code - the site classifies its own postings better than we can guess.
    # "Career Experience Drive - IT" is a real internship with neither "staj"
    # nor "intern" anywhere in its title.
    INTERNSHIP_SEARCHES = {"staj"}

    # Fallback signal for the other searches.
    #   F Tam zamanlı   P Yarı zamanlı   S Staj
    #   D Dönemsel      R Serbest        G Gönüllü
    # `S` is dead in practice - zero occurrences across 316 sampled postings -
    # and internships turn up as D (19 of 26 on the internship search), P or F.
    # So this set is a safety net, not the mechanism.
    WANTED_WORK_TYPES = {"P", "S"}

    #########################################################
    # WHY THIS SPIDER REPLAYS A BROWSER HANDSHAKE TOO       #
    #########################################################
    '''
        "Nothing exotic is needed while the exit IP looks residential"
        stopped being true on 31.07.2026. The crawl came back with zero
        postings twice while the residential proxy was up and the search URLs
        opened normally in a browser, which reads like a dead selector and is
        not one. Measured through the proxy that day:

            safari184   403,   5 kB      firefox147  200, 460 kB, data
            chrome124   403,   5 kB      firefox135  403,   5 kB

        So the page was there the whole time and PerimeterX was refusing the
        handshake, exactly the failure indeed_cards met on 29.07 - and the
        comment there ("only this spider needs it; kariyer.net and
        techcareer.net are fine with Scrapy's own downloader") had simply gone
        stale. Scrapy's own downloader sends Python's ClientHello, which is
        refused before a header is read; the residential proxy cannot help,
        because CONNECT tunnels our fingerprint through unchanged.

        techcareer.net is still fine without this - it defines no handshake
        of its own and nothing here reaches it.

        The transport is CurlImpersonateMiddleware, not the scrapy-impersonate
        package that requirements.txt has carried all along: that package is
        broken against the pinned Scrapy and never actually ran. The middleware
        docstring has the whole story, including why nobody noticed.
    '''
    IMPERSONATE_WITH_CURL = True

    custom_settings = {
        **BaseApiSpider.custom_settings,
        # kariyer.net runs PerimeterX. Stay unhurried - a listing page is
        # 115 kB and there are only a handful of them.
        "CONCURRENT_REQUESTS": 2,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 2,
        "DOWNLOAD_DELAY": 2,
        "RANDOMIZE_DOWNLOAD_DELAY": True,

        # 403 is not in Scrapy's default retry list, and the first page of a
        # search is the one that must not be lost: no page 1, no pagination,
        # no postings. Same reasoning as indeed_cards.
        "RETRY_HTTP_CODES": [403, 408, 429, 500, 502, 503, 504, 522, 524],
        "RETRY_TIMES": 3,
    }

    #####################################################
    # WHICH HANDSHAKE TO REPLAY - A LADDER, NOT A VALUE #
    #####################################################
    '''
        Ordered by what the 31.07.2026 measurement above said, firefox147
        first because it was the only token that came back with data. The
        losers stay in the list: BlockDetectionMiddleware walks them when a
        response comes back as a block, so a stale first entry costs one
        retry instead of the whole crawl.

        Do NOT pin this to the one token that works today. Indeed's ladder
        reversed twice in two days - safari184 and chrome124 were carrying it
        on 30.07 and are the ones refused here on 31.07. Re-measure with

            python -m MultiwebsiteScraper.tls_probe --proxy \
                --url "<a search URL from SEARCHES>" --expect "ad-card"

        and reorder from what it prints. KARIYERNET_IMPERSONATE pins one
        token for a one-off experiment.
    '''
    IMPERSONATE_CANDIDATES = (
        "firefox147", "safari184", "chrome124", "firefox135",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        override = os.getenv("KARIYERNET_IMPERSONATE", "").strip()
        self.impersonate_candidates = (
            [override] if override else list(self.IMPERSONATE_CANDIDATES)
        )

        # The handshake and the headers have to describe the same browser: a
        # Firefox 147 ClientHello arriving under a random profile's Chrome
        # user-agent is a mismatch of exactly the kind PerimeterX looks for.
        # BaseApiSpider picked a random profile in its __init__; replace it
        # with the one that belongs to the token we are about to use.
        token = self.impersonate_candidates[0]
        self.session = BrowserSession(
            profile=profile_for_impersonate(token), origin=self.origin,
        )

        self.logger.info(
            "Handshake ladder: %s (identity: %s)",
            ", ".join(self.impersonate_candidates), self.session.profile.name,
        )

    def default_meta(self):
        """
        On EVERY request, warm-up included - see the base class. This spider
        has no warm-up today, but a request built anywhere else and sent with
        Python's fingerprint would be refused and look like a site block.
        """
        return {
            "impersonate": self.impersonate_candidates[0],
            "impersonate_candidates": self.impersonate_candidates,
        }

    ###############################################################
    # PAGINATION IDENTITY - THE POSTING LINK, NOT THE ELEMENT     #
    ###############################################################
    def record_key(self, record):
        """
        `next_page_allowed` compares pages by record key to notice an index
        that has started repeating itself. A card's identity is its posting
        link; comparing the elements themselves is unreliable.
        """
        href = record.css('a[data-test="ad-card-item"]::attr(href)').get()
        return href or super().record_key(record)

    ##################################
    # PAGE 1 OF THE FILTERED SEARCH  #
    ##################################
    def api_requests(self):
        for search_key in self.SEARCHES:
            yield self._listing_request(search_key, page=1)

    def _listing_request(self, search_key, page):
        base_url = self.SEARCHES[search_key]
        url = self._url_for_page(base_url, page)
        return self.document_request(
            url,
            callback=self.parse_listing,
            referer=base_url if page > 1 else None,
            meta={"page": page, "search_key": search_key},
            dont_filter=True,
        )

    @staticmethod
    def _url_for_page(base_url, page):
        """Replace or add `cp` without disturbing the filter parameters."""
        parts = urlparse(base_url)
        query = [(k, v) for k, v in parse_qsl(parts.query) if k != "cp"]
        query.append(("cp", str(page)))
        return urlunparse(parts._replace(query=urlencode(query)))

    ###############################################
    # READ THE CARDS, KEEP PART-TIME / INTERNSHIP #
    ###############################################
    def parse_listing(self, response):
        cards = response.css('[data-test="ad-card"]')
        page = response.meta["page"]

        from_internship_search = response.meta["search_key"] in self.INTERNSHIP_SEARCHES

        kept = 0
        for card in cards:
            work_type_id = (card.attrib.get("worktypeid") or "").strip().upper()
            title = (card.css('[data-test="ad-card-title"]::text').get() or "").strip()
            position_name = card.attrib.get("positionname") or ""
            is_internship = from_internship_search or looks_like_internship(
                title, position_name
            )

            if not is_internship and work_type_id not in self.WANTED_WORK_TYPES:
                continue

            if is_internship and work_type_id not in ("P", "S"):
                # An internship the employer coded as something else - usually
                # D (Dönemsel) or F. Worth logging: if this count ever drops to
                # zero the searches have probably stopped returning what we
                # think they do.
                self.logger.info(
                    "Internship coded as '%s' by the employer, keeping: %s",
                    work_type_id or "?", title or position_name,
                )
                self.crawler.stats.inc_value("cards/internship_miscoded")

            href = card.css('a[data-test="ad-card-item"]::attr(href)').get()
            if not href:
                # url is the upsert key, so a card without one is unusable.
                self.logger.warning(
                    "Card with no link, skipping: %s",
                    card.attrib.get("positionname"),
                )
                self.crawler.stats.inc_value("items/skipped_no_url")
                continue

            # Which route found it - see BaseApiSpider.note_discovery.
            self.note_discovery(href, response.meta["search_key"])

            kept += 1
            # Internships are labelled Internship whatever the employer coded
            # them as. Otherwise the label would follow an arbitrary employer
            # choice: "Uzun Dönem Staj Programı" arrives as P, "Grafik Tasarım
            # Stajyeri" as F and "Bilgisayar Mühendisliği Stajyeri" as D.
            partial = self._item_from_card(
                card, response, href, force_internship=is_internship,
            )

            # The description only exists on the posting page. This is the
            # only request we spend per posting, and only for the ones we want.
            yield self.document_request(
                response.urljoin(href),
                callback=self.parse_detail,
                referer=response.url,
                meta={"partial_item": partial},
            )

        search_key = response.meta["search_key"]
        self.logger.info(
            "[%s] page %s: %s card(s), %s part-time/internship",
            search_key, page, len(cards), kept,
        )
        self.crawler.stats.inc_value("cards/seen", len(cards))
        self.crawler.stats.inc_value("cards/wanted", kept)

        if self.next_page_allowed(page, cards, search_key):
            yield self._listing_request(search_key, page + 1)

    #########################################
    # CARD ATTRIBUTES -> MOST OF THE ITEM   #
    #########################################
    def _item_from_card(self, card, response, href, force_internship=False):
        loader = KariyerNetLoader(selector=card, response=response)

        # The visible ad title is more specific than the normalised
        # `positionname` attribute ("Beyaz Eşya Mağaza Satış Danışmanı" vs
        # "Mağaza Satış Danışmanı"), so prefer it and keep the attribute as
        # the fallback.
        loader.add_css("job_title", '[data-test="ad-card-title"]::text')
        loader.add_value("job_title", card.attrib.get("positionname"))
        loader.add_value("job_title", self.DEFAULT_VALUE)

        # The logo's alt text carries the full company name; the visible
        # subtitle is sometimes truncated with an ellipsis.
        loader.add_css("company", 'img[data-test="company-image"]::attr(alt)')
        loader.add_css("company", '[data-test="subtitle"]::text')
        loader.add_value("company", self.DEFAULT_VALUE)

        # The rendered text before the `cityname` attribute, which is wrong for
        # multi-city postings: a nationwide ad carries locations="[object
        # Object],[object Object],..." and cityname holds only the first entry,
        # so a listing covering all 81 provinces reports "Adana". The visible
        # text says "İstanbul(Asya) +80 il daha" and stays honest. For
        # single-city ads the two agree.
        loader.add_css("location", '[data-test="location"]::text')
        loader.add_value("location", card.attrib.get("cityname"))
        loader.add_value("location", self.DEFAULT_VALUE)

        # Normally the site's own wording, which pipelines.normalize_job_type
        # maps onto Part-Time / Internship.
        #
        # The exception is a posting the employer coded full-time but titled
        # "... Stajyeri". Storing worktypetext there would write "Tam zamanlı"
        # -> Full-Time, and the dashboard - which defaults to Internship +
        # Part-Time - would hide the very posting we went out of our way to
        # keep. A full-time internship is still an internship, so it is
        # labelled as one.
        if force_internship:
            loader.add_value("job_type", "Staj")
        loader.add_value("job_type", card.attrib.get("worktypetext"))
        loader.add_value("job_type", self.DEFAULT_VALUE)

        loader.add_value("url", response.urljoin(href))
        loader.add_value("source_site", self.site_name)

        return loader.load_item()

    ###################################################
    # DETAIL PAGE - ONLY REACHED FOR WANTED POSTINGS  #
    ###################################################
    def parse_detail(self, response):
        item = response.meta["partial_item"]

        description = response.css(
            'div[data-test="qualifications-and-job-description"] *::text'
        ).getall()
        if not description:
            description = response.css(
                '[data-test="job-description"] *::text'
            ).getall()

        text = " ".join(part.strip() for part in description if part.strip())
        item["job_description"] = text or self.DEFAULT_VALUE

        if not text:
            self.logger.warning("No description found at %s", response.url)
            self.crawler.stats.inc_value("detail/no_description")

        yield item
