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


def _row(stored, category=None, error=None):
    row = {"id": id(object()), "stored": stored}
    if error:
        row["error"] = error
    else:
        row["category"] = category
    return row


def test_disagreements_are_split_by_what_they_cost():
    groups = tally([
        _row("it", "it"),
        _row("it", "other"),                    # hidden: the decision rule
        _row("general_program", "other"),       # hidden too
        _row("other", "general_program"),       # noise on the board
        _row("it", "general_program"),          # changes nothing shown
        _row("other", "other"),
        _row("it", error="ValueError: no parsed output"),
    ])

    assert len(groups["answered"]) == 6
    assert len(groups["agreed"]) == 2
    assert [r["stored"] for r in groups["wrongly_hidden"]] == ["it", "general_program"]
    assert len(groups["newly_shown"]) == 1
    assert len(groups["swapped"]) == 1
    assert len(groups["failed"]) == 1


def test_a_failed_row_is_not_counted_as_a_verdict():
    groups = tally([_row("it", error="timeout")])
    assert groups["wrongly_hidden"] == []
    assert groups["agreed"] == []
