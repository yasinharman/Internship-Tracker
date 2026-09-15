"""
linkedin_check: the wait for the job page, and the time it is given.

15.09.2026. Three things the checker got wrong without any run saying so:

  * DETAIL_MARKERS was a hand-written copy of APPLY_MARKERS that never learned
    "Apply on company website", so a page applying on the employer's site and
    carrying no description box sat out the whole wait and was counted as
    never rendered.
  * the wait ended on the FIRST marker, so content() could be read before the
    description box arrived - and since 12.09.2026 a LinkedIn row without a
    description is never classified.
  * main.py gave it the shared 1200s, about 140 postings of a 760-row board.

Nothing here touches the network or the database. The page and the parent's
load_open_postings are stand-ins.
"""

import time

import pytest
from parsel import Selector
from scrapy.http import HtmlResponse, Request
from scrapy.settings import Settings

import main
from scraper.openings import CLOSED, OPEN, OpeningCheckMixin
from scraper.spiders.linkedin_check import APPLY_MARKERS, LinkedinCheckSpider


def html(body, posting_id=7):
    return HtmlResponse(
        url="https://www.linkedin.com/jobs/view/4459636725/",
        body=body, encoding="utf-8",
        request=Request("https://www.linkedin.com/jobs/view/4459636725/",
                        meta={"posting_id": posting_id}),
    )


class FakePage:
    """
    Answers wait_for_selector the way a page would.

    `renders` is what exists once the page has rendered; `late` is what turns
    up only if you keep waiting; everything else never appears.
    """

    def __init__(self, renders=(), late=()):
        self.renders = set(renders)
        self.late = set(late)
        self.waited_for = []

    def wait_for_selector(self, selector, timeout):
        self.waited_for.append(selector)
        wanted = {part.strip() for part in selector.split(", ")}
        if wanted & self.renders:
            return
        if wanted & self.late:
            time.sleep(0.3)
            return
        raise TimeoutError(selector)


BOX = LinkedinCheckSpider.DESCRIPTION_BOX
COMPANY_SITE = '[aria-label="Apply on company website"]'
EASY_APPLY = '[aria-label="Easy Apply to this job"]'
DETAIL = Request("https://www.linkedin.com/jobs/view/1/", meta={"posting_id": 1})


class TestTheWaitForTheJobPage:

    @pytest.mark.parametrize("marker", APPLY_MARKERS)
    def test_every_apply_control_the_verdict_knows_ends_the_wait(self, marker):
        # The drift this replaced: the verdict knew three, the wait knew two.
        page = Selector(text=f"<button {marker}></button>")
        assert page.css(LinkedinCheckSpider.DETAIL_MARKERS)

    def test_the_description_box_ends_the_wait_too(self):
        # A closed posting has no apply control; this is how its page is read.
        page = Selector(text='<div data-testid="expandable-text-box">x</div>')
        assert page.css(LinkedinCheckSpider.DETAIL_MARKERS)

    def test_the_feed_is_not_waited_on(self, make_checker):
        spider = make_checker(LinkedinCheckSpider)
        page = FakePage()
        spider.page_actions(page, Request("https://www.linkedin.com/feed/"))
        assert page.waited_for == []

    def test_a_box_already_there_costs_nothing_and_counts_nothing(self, make_checker):
        spider = make_checker(LinkedinCheckSpider)
        spider.page_actions(FakePage(renders={EASY_APPLY, BOX}), DETAIL)
        assert "linkedin/description_box_late" not in spider.crawler.stats.values
        assert "linkedin/description_box_absent" not in spider.crawler.stats.values

    def test_a_box_that_arrives_after_the_button_is_waited_for(self, make_checker):
        spider = make_checker(LinkedinCheckSpider)
        spider.page_actions(FakePage(renders={COMPANY_SITE}, late={BOX}), DETAIL)
        assert spider.crawler.stats.values["linkedin/description_box_late"] == 1

    def test_a_box_that_never_comes_is_counted(self, make_checker):
        spider = make_checker(LinkedinCheckSpider)
        spider.page_actions(FakePage(renders={COMPANY_SITE}), DETAIL)
        stats = spider.crawler.stats.values
        assert stats["linkedin/description_box_absent"] == 1
        assert "linkedin/detail_never_rendered" not in stats

    def test_a_page_that_never_rendered_is_not_waited_on_twice(self, make_checker):
        spider = make_checker(LinkedinCheckSpider)
        page = FakePage()
        spider.page_actions(page, DETAIL)
        assert spider.crawler.stats.values["linkedin/detail_never_rendered"] == 1
        assert len(page.waited_for) == 1


class TestTheTimeItIsGiven:

    def test_the_ceiling_clears_a_board_of_a_thousand_at_the_worst_rate(self):
        closes_at = main.soft_close_after(main.SPIDER_TIMEOUTS["linkedin_check"])
        worst_case = 1000 * LinkedinCheckSpider.WORST_S_PER_POSTING
        assert closes_at > worst_case, (
            f"linkedin_check can take {worst_case / 60:.0f} min for 1000 "
            f"postings but closes at {closes_at / 60:.0f} min"
        )

    def test_the_worst_rate_follows_the_delay(self):
        # 1.5x is the throttle's upper bound; the rest is the fetch itself.
        delay = LinkedinCheckSpider.custom_settings["DOWNLOAD_DELAY"]
        assert LinkedinCheckSpider.WORST_S_PER_POSTING >= delay * 1.5

    def test_a_board_too_big_for_the_ceiling_is_said_at_the_start(
        self, make_checker, monkeypatch, caplog,
    ):
        rows = [{"id": n, "url": f"u{n}", "job_title": "t"} for n in range(300)]
        monkeypatch.setattr(OpeningCheckMixin, "load_open_postings", lambda self: rows)
        spider = make_checker(LinkedinCheckSpider)
        spider.crawler.settings = Settings({"CLOSESPIDER_TIMEOUT": 600})

        with caplog.at_level("WARNING"):
            assert spider.load_open_postings() == rows
        assert "will not all fit" in caplog.text

    def test_a_board_that_fits_says_nothing(self, make_checker, monkeypatch, caplog):
        rows = [{"id": n, "url": f"u{n}", "job_title": "t"} for n in range(300)]
        monkeypatch.setattr(OpeningCheckMixin, "load_open_postings", lambda self: rows)
        spider = make_checker(LinkedinCheckSpider)
        spider.crawler.settings = Settings(
            {"CLOSESPIDER_TIMEOUT": main.soft_close_after(main.SPIDER_TIMEOUTS["linkedin_check"])}
        )

        with caplog.at_level("WARNING"):
            spider.load_open_postings()
        assert "will not all fit" not in caplog.text


class TestWhatTheRunLeavesToLookAt:

    def test_a_closed_marker_beside_an_apply_control_is_counted_not_acted_on(
        self, make_checker,
    ):
        spider = make_checker(LinkedinCheckSpider)
        body = (b'<p>No longer accepting applications</p>'
                b'<button aria-label="Easy Apply to this job"></button>')
        assert spider.verdict(html(body)) == CLOSED
        assert spider.crawler.stats.values["linkedin/closed_marker_beside_apply"] == 1

    def test_a_plain_closed_page_is_not_flagged(self, make_checker):
        spider = make_checker(LinkedinCheckSpider)
        spider.verdict(html(b'<p>No longer accepting applications</p>'))
        assert "linkedin/closed_marker_beside_apply" not in spider.crawler.stats.values

    def test_an_open_page_without_a_description_is_kept_when_asked(
        self, make_checker, monkeypatch, tmp_path,
    ):
        monkeypatch.setenv("LINKEDIN_DUMP_DIR", str(tmp_path))
        spider = make_checker(LinkedinCheckSpider)
        spider.crawler.stats.get_value = (
            lambda key, default=None: spider.crawler.stats.values.get(key, default)
        )
        response = html(b'<button aria-label="Apply on company website"></button>')

        assert spider.verdict(response) == OPEN
        assert spider.description(response) is None
        assert (tmp_path / "7.html").exists()

    def test_a_wall_is_not_kept(self, make_checker, monkeypatch, tmp_path):
        monkeypatch.setenv("LINKEDIN_DUMP_DIR", str(tmp_path))
        spider = make_checker(LinkedinCheckSpider)
        spider.crawler.stats.get_value = (
            lambda key, default=None: spider.crawler.stats.values.get(key, default)
        )
        spider.description(html(b'<div>Sign in</div>'))
        assert list(tmp_path.iterdir()) == []

    def test_nothing_is_kept_unless_asked(self, make_checker, monkeypatch, tmp_path):
        monkeypatch.delenv("LINKEDIN_DUMP_DIR", raising=False)
        monkeypatch.chdir(tmp_path)
        spider = make_checker(LinkedinCheckSpider)
        spider.description(html(b'<button aria-label="Easy Apply to this job"></button>'))
        assert list(tmp_path.iterdir()) == []


def test_each_page_is_read_before_the_next_is_fetched():
    """
    SCRAPER_SLOT_MAX_ACTIVE_SIZE, measured 15.09.2026: at Scrapy's 5 MB the
    full run fetched 57 job pages before deciding one verdict, so WRITE_EVERY
    never got its chance. Starting a real crawler here would need the reactor,
    so this pins the setting and linkedin_check.py carries the measurement.
    """
    assert LinkedinCheckSpider.custom_settings["SCRAPER_SLOT_MAX_ACTIVE_SIZE"] == 1
