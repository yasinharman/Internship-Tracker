"""
Query parameters arrive as comma-joined strings so a copied url stays
readable. This is the only parsing between the url and the SQL.
"""

import pytest

from api.filters import _split


@pytest.mark.parametrize("raw,expected", [
    ("it,general_program", ["it", "general_program"]),
    ("it, general_program", ["it", "general_program"]),   # a space after the comma
    ("indeed.com", ["indeed.com"]),
])
def test_a_list_comes_apart(raw, expected):
    assert _split(raw) == expected


@pytest.mark.parametrize("raw", [None, "", ",", " , , "])
def test_nothing_selected_is_an_empty_list_not_a_blank_entry(raw):
    # An empty string in the list would become `source_site IN ('')` and
    # empty the board.
    assert _split(raw) == []
