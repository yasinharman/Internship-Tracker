"""
The job-type column, which the dashboard filters on.

Every case here is one the code has a comment about. They are tests because
the comment cannot fail when someone edits the regex.
"""

import pytest

from scraper.pipelines import canonical, canonical_forms, normalize_job_type, turkish_lower


class TestTurkishLowercasing:
    def test_dotless_i_is_the_whole_point(self):
        # str.lower() gives "yari zamanli" with a dotted i, which matches
        # nothing in the alias table.
        assert turkish_lower("YARI ZAMANLI") == "yarı zamanlı"

    def test_capital_dotted_i_becomes_dotted(self):
        assert turkish_lower("İŞ") == "iş"

    def test_both_readings_are_produced(self):
        # Turkish rules turn "TIME" into "tıme", which matches nothing - so
        # the plain lowercasing has to be offered as well.
        forms = canonical_forms("PART-TIME")
        assert "part time" in forms


class TestNormalizeJobType:
    @pytest.mark.parametrize("raw,expected", [
        ("Full-Time", "Full-Time"),
        ("tam zamanlı", "Full-Time"),
        ("Part-Time", "Part-Time"),
        ("YARI ZAMANLI", "Part-Time"),
        ("Internship", "Internship"),
        ("stajyer", "Internship"),
        ("Sözleşmeli", "Contract"),
        ("Remote", "Remote"),
    ])
    def test_known_aliases(self, raw, expected):
        assert normalize_job_type(raw) == expected

    @pytest.mark.parametrize("raw,expected", [
        ("Stajyer (Uzaktan)", "Internship"),
        ("Staj / Intern", "Internship"),
        ("Part-time (Hafta sonu)", "Part-Time"),
    ])
    def test_decorated_values_are_not_lost(self, raw, expected):
        # Exact-match lookup sent all of these to "Other", which was untidy
        # while everything was shown and became data loss once the dashboard
        # started filtering on this column.
        assert normalize_job_type(raw) == expected

    def test_the_more_specific_label_wins(self):
        # "Staj / Tam Zamanlı" matches both. The one being filtered on wins,
        # so an ambiguous posting is shown rather than silently dropped.
        assert normalize_job_type("Staj / Tam Zamanlı") == "Internship"

    def test_remote_loses_to_an_employment_type(self):
        # Remote says WHERE the work happens, not what the job is.
        assert normalize_job_type("Tam Zamanlı, Uzaktan") == "Full-Time"

    @pytest.mark.parametrize("raw", ["Draft Designer", "Adaptasyon Uzmanı"])
    def test_two_letter_aliases_never_match_as_substrings(self, raw):
        # 'ft' inside "Draft", 'pt' inside "Adaptasyon".
        assert normalize_job_type(raw) == "Other"

    @pytest.mark.parametrize("raw", [None, "", 42, "   "])
    def test_junk_is_other_not_a_crash(self, raw):
        assert normalize_job_type(raw) == "Other"


class TestCanonical:
    def test_separators_flatten(self):
        assert canonical("Part-Time") == canonical("part_time") == canonical("Part  Time")
