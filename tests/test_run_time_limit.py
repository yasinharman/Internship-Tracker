"""
What main.py does when a spider runs out of time.

MEASURED 15.09.2026 (docs/sites/indeed.md): the old kill cost indeed_check 23
verdicts it had already paid for, and made a crawl that had stored 280
postings read "Calismadi - crash veya baslamadan hata". Nothing here starts
a spider: subprocess.run is replaced.
"""

import subprocess

import main


def _fake_run(monkeypatch, outcome):
    calls = []

    def fake(command, **kwargs):
        calls.append(command)
        if outcome == "kill":
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(main.subprocess, "run", fake)
    return calls


def test_every_spider_is_told_to_close_before_it_would_be_killed(monkeypatch):
    calls = _fake_run(monkeypatch, "exit")
    monkeypatch.setattr(main, "_read_spider_stats", lambda path: None)

    main.run_spider("indeed_cards")

    limit = main.SPIDER_TIMEOUTS["indeed_cards"] - main.CLOSE_GRACE_S
    assert f"CLOSESPIDER_TIMEOUT={limit}" in calls[0]


def test_the_checker_gets_its_own_ceiling_not_check_timeout(monkeypatch):
    calls = _fake_run(monkeypatch, "exit")
    monkeypatch.setattr(main, "_read_spider_stats", lambda path: None)

    main.run_spider("indeed_check", timeout=main.CHECK_TIMEOUT)

    limit = main.SPIDER_TIMEOUTS["indeed_check"] - main.CLOSE_GRACE_S
    assert f"CLOSESPIDER_TIMEOUT={limit}" in calls[0]


def test_a_killed_spider_is_not_reported_as_one_that_never_ran(monkeypatch, capsys):
    _fake_run(monkeypatch, "kill")
    monkeypatch.setattr(main, "_read_spider_stats", lambda path: None)

    ok, stats = main.run_spider("indeed_cards")
    main._print_run_summary({"indeed_cards": (ok, stats)})

    out = capsys.readouterr().out
    assert not ok
    assert "Calismadi" not in out
    assert "zorla durduruldu" in out
    assert "indeed_cards" in main._CRAWL_FINISHED_AT


def test_a_spider_closed_at_its_limit_says_so(monkeypatch, capsys):
    _fake_run(monkeypatch, "exit")
    stats = {"name": "indeed_cards", "items": 280, "requests": 70,
             "finish_reason": "closespider_timeout"}
    monkeypatch.setattr(main, "_read_spider_stats", lambda path: dict(stats))

    ok, got = main.run_spider("indeed_cards")
    main._print_run_summary({"indeed_cards": (ok, got)})

    out = capsys.readouterr().out
    assert ok
    assert "STOPPED AT ITS TIME LIMIT" in out
    assert "280 ilan bulundu" in out
    assert "sure siniri doldu" in out


def test_the_indeed_crawl_ceiling_clears_its_worst_case():
    """The arithmetic next to SPIDER_TIMEOUTS, so it fails if the delay moves."""
    from scraper.spiders.indeed_cards import IndeedCardsSpider as spider

    # warm-up, nine searches to MAX_PAGES, and ten 429 retries.
    requests = 1 + len(spider.SEARCHES) * spider.MAX_PAGES + 10
    slowest = spider.custom_settings["DOWNLOAD_DELAY"] * 1.5 + 2

    closes_at = main.soft_close_after(main.SPIDER_TIMEOUTS["indeed_cards"])
    worst_case = requests * slowest
    assert closes_at > worst_case, (
        f"indeed_cards can take {worst_case / 60:.0f} min but closes at "
        f"{closes_at / 60:.0f} min"
    )
