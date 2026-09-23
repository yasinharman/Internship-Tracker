"""
The measuring tool for a local classifier model: what it refuses, and how it
counts.

Two things here are worth locking down. The tool must never send a request
anywhere but this machine - .env holds the real OpenAI key, and a measurement
that quietly became an API bill is the failure it is built to avoid. And a
disagreement has to be counted by what it COSTS: a posting the stored label
shows and the model hides is the decision rule (docs/pipeline.md), while one
the model shows that was hidden is a row of noise.

Nothing here reaches a server or the database.
"""

import pytest

from tools.eval_classifier import REQUEST, check_local, tally


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:11434/v1",
    "http://localhost:8080/v1",
    "http://[::1]:11434/v1",
])
def test_a_local_server_is_accepted(url):
    check_local(url)


@pytest.mark.parametrize("url", [
    "https://api.openai.com/v1",
    "http://192.168.1.20:11434/v1",
    "http://localhost.example.com/v1",
])
def test_anything_else_is_refused(url):
    with pytest.raises(SystemExit):
        check_local(url)


def test_every_model_is_asked_the_same_way():
    # Left to the server, each model would reason or not and pick its own
    # temperature - two variables hidden behind the model name.
    assert REQUEST == {"temperature": 0, "reasoning_effort": "none"}


def _row(stored, given=None, error=None, stored_internship=True, internship=True):
    row = {"id": id(object()), "job_title": "Stajyer", "reason": "",
           "stored": (stored or [None])[0], "stored_fields": list(stored or []),
           "stored_internship": stored_internship}
    if error:
        row["error"] = error
    else:
        row["fields"] = list(given or [])
        row["category"] = row["fields"][0] if row["fields"] else None
        row["is_internship"] = internship
    return row


def test_disagreements_are_split_by_what_they_cost():
    groups = tally([
        _row(["yazilim"], ["yazilim"]),                       # identical
        _row(["yazilim", "veri_yapay_zeka"], ["yazilim"]),    # missed one
        _row(["yazilim"], ["yazilim", "tasarim"]),            # added one
        _row(["hukuk"], ["finans_muhasebe"]),                 # not one in common
        _row(["egitim"], ["egitim"], internship=False),       # hidden by this model
        _row(["saglik"], ["saglik"], stored_internship=False),  # shown by this model
        _row(["yazilim"], error="ValueError: no parsed output"),
    ])

    assert len(groups["answered"]) == 6
    assert len(groups["agreed"]) == 3      # rows 1, 5 and 6 - the field sets match
    # The disjoint row counts in both: it missed hukuk and added
    # finans_muhasebe. missed/extra are about fields, disjoint about postings.
    assert len(groups["missed"]) == 2
    assert len(groups["extra"]) == 2
    assert len(groups["disjoint"]) == 1
    assert [r["stored"] for r in groups["wrongly_hidden"]] == ["egitim"]
    assert [r["stored"] for r in groups["newly_shown"]] == ["saglik"]
    assert len(groups["failed"]) == 1


def test_a_posting_that_shares_one_field_is_not_a_disjoint_miss():
    # "Yazılım ve Veri Stajyeri" stored under both, this model says yazilim:
    # the student filtering for yazilim still finds it. Worth counting, but
    # not worth the same as a posting filed under nothing it belongs to.
    groups = tally([_row(["yazilim", "veri_yapay_zeka"], ["yazilim"])])
    assert len(groups["overlapping"]) == 1
    assert groups["disjoint"] == []


def test_a_failed_row_is_not_counted_as_a_verdict():
    groups = tally([_row(["yazilim"], error="timeout")])
    assert groups["wrongly_hidden"] == []
    assert groups["agreed"] == []
