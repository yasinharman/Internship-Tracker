"""
The classifier runs on a local model, behind Ollama.

Chosen by measurement on 21.09.2026 (docs/pipeline.md, "A local model on the
70 labelled rows"); the OpenAI and Anthropic paths were removed the same day.
Two things about the call are worth locking down, because each one fails
silently rather than loudly:

- It must never carry a real OpenAI key. An older `.env` still holds one, and
  the SDK picks it up from the environment on its own - so the client is
  built with a throwaway key, and a misconfigured URL gets a refusal, not a
  bill.
- It must send the request the model was measured with. Without temperature 0
  and reasoning off, the server falls back to each model's own defaults and
  the measured numbers no longer describe what runs.

The OpenAI client is replaced by a recorder, so nothing here reaches a server.
"""

from types import SimpleNamespace

import openai
import pytest

from scraper.classifier import (
    DEFAULT_MODEL,
    LOCAL_BASE_URL,
    LOCAL_REQUEST,
    PostingFields,
    classify,
)
from tools.eval_classifier import REQUEST

POSTING = {
    "job_title": "Yazılım Stajyeri",
    "company": "Bir Firma",
    "location": "İstanbul",
    "job_description": "Python ve SQL bilen stajyer arıyoruz.",
}


@pytest.fixture
def made(monkeypatch):
    """Every client built during the test: its settings and its calls."""
    clients = []

    class Recorder:
        def __init__(self, **settings):
            self.settings = settings
            self.calls = []
            self.chat = SimpleNamespace(completions=SimpleNamespace(parse=self._parse))
            clients.append(self)

        def _parse(self, **request):
            self.calls.append(request)
            verdict = PostingFields(fields=["yazilim"], is_internship=True,
                                    reason="Başlıkta yazılım geçiyor.")
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(parsed=verdict))])

    monkeypatch.setattr(openai, "OpenAI", Recorder)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-the-real-one")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.delenv("CLASSIFIER_MODEL", raising=False)
    monkeypatch.delenv("CLASSIFIER_URL", raising=False)
    return clients


def test_the_client_never_carries_the_real_key(made):
    classify(POSTING)

    (client,) = made
    assert client.settings["api_key"] == "local"
    assert client.settings["base_url"] == LOCAL_BASE_URL


def test_the_request_is_the_one_that_was_measured(made):
    verdict = classify(POSTING)

    (call,) = made[0].calls
    assert call["model"] == DEFAULT_MODEL == "gemma4:12b"
    assert call["temperature"] == 0
    assert call["reasoning_effort"] == "none"
    assert call["response_format"] is PostingFields
    assert verdict.fields == ["yazilim"]
    assert verdict.is_internship is True


def test_the_measuring_tool_sends_the_same_dict():
    # Not equal - the same object. A copy could drift.
    assert REQUEST is LOCAL_REQUEST


def test_the_model_and_server_can_be_named(made, monkeypatch):
    monkeypatch.setenv("CLASSIFIER_MODEL", "qwen3.5:9b")
    monkeypatch.setenv("CLASSIFIER_URL", "http://127.0.0.1:8080/v1")
    classify(POSTING)

    assert made[0].settings["base_url"] == "http://127.0.0.1:8080/v1"
    assert made[0].calls[0]["model"] == "qwen3.5:9b"


def test_a_model_passed_in_wins_over_the_environment(made, monkeypatch):
    # --model and --compare pass it in.
    monkeypatch.setenv("CLASSIFIER_MODEL", "qwen3.5:9b")
    classify(POSTING, model="gemma4:12b")

    assert made[0].calls[0]["model"] == "gemma4:12b"
