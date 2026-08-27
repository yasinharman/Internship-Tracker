"""
Is this posting one of the two kinds the bot collects?

The two regexes these test are what stops the spiders storing everything a
search happens to return.
"""

import pytest

from scraper.job_filters import is_wanted, looks_like_internship, looks_like_parttime


class TestInternship:
    @pytest.mark.parametrize("title", [
        "Yazılım Stajyeri", "Staj Programı", "Stajyerlik", "Uzun dönem stajı",
        "Backend Intern", "Software Internship", "Interns wanted",
        "Graduate Trainee", "Co-op Student", "Coop Engineer",
    ])
    def test_reads_as_an_internship(self, title):
        assert looks_like_internship(title)

    @pytest.mark.parametrize("title", [
        "International Sales Manager",     # the reason `intern` has a \b
        "Internal Audit Specialist",
        "Senior Backend Developer",
    ])
    def test_does_not_fire_on_lookalikes(self, title):
        assert not looks_like_internship(title)


class TestPartTime:
    @pytest.mark.parametrize("title", [
        "Part Time Satış Danışmanı", "Part-time Barista", "PART_TIME Editor",
        "Yarı Zamanlı Grafiker", "yari zamanli asistan", "Yarı gün çalışan",
    ])
    def test_reads_as_part_time(self, title):
        assert looks_like_parttime(title)

    def test_full_time_is_not_part_time(self):
        assert not looks_like_parttime("Full Time Developer")


class TestIsWanted:
    def test_either_kind_counts(self):
        assert is_wanted("Stajyer")
        assert is_wanted("Part Time")

    def test_neither_does_not(self):
        assert not is_wanted("Kıdemli Yazılım Mühendisi")

    def test_any_of_several_fields_can_carry_it(self):
        # The spiders pass title, type and sometimes the snippet together.
        assert is_wanted("Yazılım Mühendisi", "Staj", None)

    def test_none_values_do_not_crash(self):
        assert not is_wanted(None, None)
