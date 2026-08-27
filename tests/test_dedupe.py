"""
Linking the same opening advertised on two boards.

The conservative half is the part worth locking down: two ads with the same
title and company on ONE board are usually two real openings, and this
project's rule is never to lose a posting.
"""

from datetime import datetime, timedelta

from pipeline.dedupe_jobs import find_duplicates


class FakePosting:
    """Only the four attributes find_duplicates() reads."""

    def __init__(self, id, job_title, company, source_site, created_at=None):
        self.id = id
        self.job_title = job_title
        self.company = company
        self.source_site = source_site
        self.created_at = created_at or datetime(2026, 8, 1)


def test_same_job_on_two_boards_is_linked():
    older = FakePosting(1, "Yazılım Stajyeri", "Trendyol", "kariyer.net",
                        datetime(2026, 8, 1))
    newer = FakePosting(2, "Yazılım Stajyeri", "Trendyol", "techcareer.net",
                        datetime(2026, 8, 3))
    assert find_duplicates([older, newer]) == {2: 1}


def test_the_oldest_row_wins_regardless_of_order():
    # Stable across runs, unlike anything based on which crawl finished first.
    older = FakePosting(9, "Backend Intern", "Getir", "indeed.com",
                        datetime(2026, 8, 1))
    newer = FakePosting(3, "Backend Intern", "Getir", "linkedin.com",
                        datetime(2026, 8, 5))
    assert find_duplicates([newer, older]) == {3: 9}


def test_same_site_collision_is_left_alone():
    # Two teams, two districts, or the board's own repost - all real postings.
    a = FakePosting(1, "Data Intern", "Aselsan", "kariyer.net")
    b = FakePosting(2, "Data Intern", "Aselsan", "kariyer.net")
    assert find_duplicates([a, b]) == {}


def test_a_differently_written_company_does_not_match():
    # The safe direction to fail: the job stays listed twice.
    a = FakePosting(1, "QA Stajyeri", "Turkcell A.Ş.", "kariyer.net")
    b = FakePosting(2, "QA Stajyeri", "Turkcell", "indeed.com")
    assert find_duplicates([a, b]) == {}


def test_matching_is_turkish_aware():
    # canonical() lowercases the Turkish way; "İŞ BANKASI".lower() produces a
    # combining-dot artifact that matches nothing.
    a = FakePosting(1, "YARI ZAMANLI ASİSTAN", "İŞ BANKASI", "kariyer.net")
    b = FakePosting(2, "Yarı Zamanlı Asistan", "İş Bankası", "indeed.com")
    assert find_duplicates([a, b]) == {2: 1}


def test_three_boards_all_point_at_one_keeper():
    base = datetime(2026, 8, 1)
    rows = [
        FakePosting(1, "Intern", "PepsiCo", "kariyer.net", base),
        FakePosting(2, "Intern", "PepsiCo", "techcareer.net", base + timedelta(days=1)),
        FakePosting(3, "Intern", "PepsiCo", "linkedin.com", base + timedelta(days=2)),
    ]
    assert find_duplicates(rows) == {2: 1, 3: 1}


def test_equal_timestamps_are_broken_by_id():
    # created_at can be equal to the second when two spiders run back to back.
    same = datetime(2026, 8, 1, 12, 0, 0)
    a = FakePosting(7, "Intern", "Getir", "kariyer.net", same)
    b = FakePosting(4, "Intern", "Getir", "indeed.com", same)
    assert find_duplicates([a, b]) == {7: 4}


def test_a_lone_posting_is_not_a_duplicate():
    assert find_duplicates([FakePosting(1, "Intern", "Getir", "kariyer.net")]) == {}
