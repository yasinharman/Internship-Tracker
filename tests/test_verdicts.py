"""
IS THIS POSTING STILL OPEN? - the asymmetry, locked down.

scraper/openings.py exists to make one mistake impossible: a false CLOSED
silently removes a real job from the board. So CLOSED is only ever written on
a positive, site-specific signal, and everything else - a block, a redirect, a
page shape nobody recognises - is UNKNOWN and writes nothing at all.

That rule lives in four `verdict()` methods and nowhere else. These tests are
the only thing that fails when someone loosens one of them.

The fixtures are the smallest fragment that carries the signal, not saved
pages: a real Indeed page is ~400 kB of nested JSON, and none of the other
399 kB is what the verdict reads.
"""

import pytest
from scrapy.http import HtmlResponse, TextResponse

from scraper.openings import CLOSED, OPEN, UNKNOWN
from scraper.spiders.indeed_check import IndeedCheckSpider
from scraper.spiders.kariyernet_check import KariyerNetCheckSpider
from scraper.spiders.linkedin_check import LinkedinCheckSpider
from scraper.spiders.techcareer_check import TechCareerCheckSpider


def html(body):
    return HtmlResponse(url="https://example.test/job/1", body=body,
                        encoding="utf-8")


def text(body):
    return TextResponse(url="https://example.test/job/1", body=body,
                        encoding="utf-8")


class TestKariyerNet:
    """Measured 21.08.2026: both states answer HTTP 200, so the signal is in
    the page. An id that never existed 200s too, after redirecting to the
    listing - which is why the description block is required before anything
    is called closed."""

    def verdict(self, make_checker, body):
        return make_checker(KariyerNetCheckSpider).verdict(html(body))

    def test_apply_button_means_open(self, make_checker):
        assert self.verdict(make_checker, b'<div data-test="apply-button">Basvur</div>') == OPEN

    def test_no_apply_button_on_a_posting_page_means_closed(self, make_checker):
        body = b'<div data-test="qualifications-and-job-description">...</div>'
        assert self.verdict(make_checker, body) == CLOSED

    def test_the_listing_page_is_not_a_closed_posting(self, make_checker):
        # A dead id redirects here and answers 200. No description block, so
        # there is no evidence of anything.
        assert self.verdict(make_checker, b'<div class="ad-list">...</div>') == UNKNOWN

    def test_an_interstitial_is_unknown(self, make_checker):
        assert self.verdict(make_checker, b'<title>Just a moment...</title>') == UNKNOWN


class TestTechCareer:
    """The one site that answers the question in a field. isCompleted is the
    site's own word for it - the list endpoint filters on the same field."""

    def verdict(self, make_checker, body):
        return make_checker(TechCareerCheckSpider).verdict(text(body))

    def test_is_completed_true_means_closed(self, make_checker):
        body = b'{"pageProps":{"jobDetail":{"head":{"isCompleted":true}}}}'
        assert self.verdict(make_checker, body) == CLOSED

    def test_is_completed_false_means_open(self, make_checker):
        body = b'{"pageProps":{"jobDetail":{"head":{"isCompleted":false}}}}'
        assert self.verdict(make_checker, body) == OPEN

    def test_an_empty_head_means_the_posting_is_gone(self, make_checker):
        # A slug that does not exist answers 200 with a 105-byte body.
        body = b'{"pageProps":{"jobDetail":{"head":{}}}}'
        assert self.verdict(make_checker, body) == CLOSED

    def test_another_endpoints_shape_is_unknown(self, make_checker):
        # An interstitial or a moved route would not parse as this endpoint.
        assert self.verdict(make_checker, b'{"pageProps":{}}') == UNKNOWN

    def test_junk_is_unknown_not_closed(self, make_checker):
        assert self.verdict(make_checker, b'<html>blocked</html>') == UNKNOWN


class TestIndeed:
    """Measured 21.08.2026 over 12 stored postings. The flag appears several
    times per page - the view-job model and match-insights both carry it - so
    a page holding both readings is UNKNOWN rather than resolved by whichever
    regex ran first."""

    def verdict(self, make_checker, body):
        return make_checker(IndeedCheckSpider).verdict(text(body))

    def test_expired_true_means_closed(self, make_checker):
        assert self.verdict(make_checker, b'window._initialData={"isJobExpired":true}') == CLOSED

    def test_expired_false_means_open(self, make_checker):
        assert self.verdict(make_checker, b'window._initialData={"isJobExpired":false}') == OPEN

    def test_whitespace_in_the_json_still_matches(self, make_checker):
        assert self.verdict(make_checker, b'{"isJobExpired" : true}') == CLOSED

    def test_a_page_contradicting_itself_is_unknown(self, make_checker):
        body = b'{"isJobExpired":true} ... {"isJobExpired":false}'
        assert self.verdict(make_checker, body) == UNKNOWN

    def test_the_localised_word_expired_is_not_a_signal(self, make_checker):
        # "This job has expired on Indeed" is a localisation entry present on
        # every page, expired or not. So is "no longer".
        body = ('{"messages":{"expired":"Indeed\'de bu is ilaninin suresi doldu",'
                '"noLonger":"no longer accepting"}}').encode()
        assert self.verdict(make_checker, body) == UNKNOWN

    def test_a_signin_wall_is_unknown(self, make_checker):
        assert self.verdict(make_checker, b'<h1>Sign in to continue</h1>') == UNKNOWN


class TestLinkedIn:
    """
    Guest pages since 22.09.2026 - there is no account any more
    (docs/sites/linkedin.md). MEASURED with no account on two postings: the
    open one carries the apply link, the closed one the closed-job notice and
    "Artık başvuru kabul etmiyor", and no apply link.
    """

    def verdict(self, make_checker, body):
        return make_checker(LinkedinCheckSpider).verdict(html(body))

    @pytest.mark.parametrize("control", [
        "public_jobs_apply-link-onsite",     # measured 22.09.2026
        "public_jobs_apply-link-offsite",    # the same control, employer's site
    ])
    def test_the_apply_link_means_open(self, make_checker, control):
        body = f'<a data-tracking-control-name="{control}">Başvur</a>'.encode()
        assert self.verdict(make_checker, body) == OPEN

    @pytest.mark.parametrize("notice", [
        '<span class="closed-job__flavor--closed">x</span>',   # measured
        "<p>Artık başvuru kabul etmiyor</p>",                     # measured
        "<p>No longer accepting applications</p>",                # signed-in, 27.08
    ])
    def test_the_page_saying_so_means_closed(self, make_checker, notice):
        assert self.verdict(make_checker, notice.encode()) == CLOSED

    def test_a_rendered_page_with_neither_is_unknown(self, make_checker):
        body = b'<h1 class="top-card-layout__title">Intern</h1>'
        assert self.verdict(make_checker, body) == UNKNOWN

    def test_an_unreadable_page_is_unknown_and_counted(self, make_checker):
        spider = make_checker(LinkedinCheckSpider)
        assert spider.verdict(html(b"<div>Oturum a\xc3\xa7\xc4\xb1n</div>")) == UNKNOWN
        assert spider.crawler.stats.values["linkedin/unreadable_posting"] == 1


class TestNobodyGuesses:
    """The default this whole design rests on."""

    @pytest.mark.parametrize("spider_class", [
        KariyerNetCheckSpider, TechCareerCheckSpider,
        IndeedCheckSpider, LinkedinCheckSpider,
    ])
    def test_an_empty_page_is_never_closed(self, make_checker, spider_class):
        assert make_checker(spider_class).verdict(text(b"")) != CLOSED
