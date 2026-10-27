"""Provider dispatch: model chains, typed error classification, fallback."""

from __future__ import annotations

import asyncio
import re
from types import SimpleNamespace
from typing import Any, cast

import anthropic
import ollama
import openai
import pytest
from google.genai import errors as genai_errors

from vibetter import providers
from vibetter.providers import ProviderError, call_llm, classify


class _Resp:
    """The few attributes the SDK status errors read from an HTTP response."""

    def __init__(self, status: int):
        self.status_code = status
        self.headers: dict[str, str] = {}
        self.request = None


def status_error(cls: type, status: int, message: str = "error") -> Exception:
    return cls(message, response=cast(Any, _Resp(status)), body=None)


class FakeAnthropic:
    """Mimics client.messages.create; raises queued errors, then answers."""

    def __init__(self, *errors: Exception, blocks: list[Any] | None = None):
        self.errors = list(errors)
        self.models: list[str] = []
        self.blocks = blocks or [SimpleNamespace(type="text", text="answer")]
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs: Any) -> Any:
        self.models.append(kwargs["model"])
        if self.errors:
            raise self.errors.pop(0)
        return SimpleNamespace(content=self.blocks)


class FakeOpenAI:
    def __init__(self, *errors: Exception):
        self.errors = list(errors)
        self.models: list[str] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs: Any) -> Any:
        self.models.append(kwargs["model"])
        if self.errors:
            raise self.errors.pop(0)
        message = SimpleNamespace(content="openai answer")
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class FakeOllama:
    def __init__(self, *errors: Exception):
        self.errors = list(errors)
        self.models: list[str] = []
        self.kwargs: list[dict[str, Any]] = []

    def chat(self, **kwargs: Any) -> Any:
        self.models.append(kwargs["model"])
        self.kwargs.append(kwargs)
        if self.errors:
            raise self.errors.pop(0)
        return SimpleNamespace(message=SimpleNamespace(content="ollama answer"))


def run(coro):
    return asyncio.run(coro)


RETIRED = {
    "claude-haiku-4-20250414",  # never existed
    "claude-sonnet-4-20250514",
    "gpt-3.5-turbo",
    "gpt-4o",
    "gpt-4o-mini",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "llama3",
    "codellama",
}


def test_regression_no_retired_model_ids():
    chains = [m for chain in providers.DEFAULT_MODELS.values() for m in chain]
    assert chains and not RETIRED & set(chains)


def test_ollama_default_model_is_qwen_coder():
    assert providers.DEFAULT_MODELS["ollama"][0] == "qwen2.5-coder:7b"


def test_provider_autodetected_from_key(monkeypatch: pytest.MonkeyPatch):
    assert providers.get_provider_name() == "ollama"
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert providers.get_provider_name() == "openai"
    monkeypatch.setenv("VIBETTER_PROVIDER", "anthropic")
    assert providers.get_provider_name() == "anthropic"


@pytest.mark.parametrize(
    ("exc", "kind"),
    [
        (status_error(anthropic.RateLimitError, 429), "transient"),
        (status_error(anthropic.InternalServerError, 500), "transient"),
        (status_error(anthropic.NotFoundError, 404), "missing"),
        (status_error(anthropic.AuthenticationError, 401), "fatal"),
        (status_error(openai.RateLimitError, 429), "transient"),
        (status_error(openai.PermissionDeniedError, 403), "fatal"),
        (anthropic.APIConnectionError(request=cast(Any, None)), "transient"),
        (openai.APITimeoutError(request=cast(Any, None)), "transient"),
        (genai_errors.ClientError(404, {"error": {"message": "not found"}}), "missing"),
        (genai_errors.ServerError(503, {"error": {"message": "unavailable"}}), "transient"),
        (ollama.ResponseError("model not found", 404), "missing"),
        (ConnectionError("Failed to connect to Ollama"), "transient"),
        (ValueError("anything else"), "fatal"),
    ],
)
def test_classify_uses_exception_types_and_status(exc: Exception, kind: str):
    assert classify(exc) == kind


def test_regression_generate_in_message_is_not_rate_limit():
    # The old substring check treated "generate" as "rate" and retried.
    exc = status_error(anthropic.BadRequestError, 400, "could not generate: prompt invalid")
    assert classify(exc) == "fatal"


def test_fallback_moves_to_next_model_on_404_and_429():
    client = FakeAnthropic(
        status_error(anthropic.NotFoundError, 404),
        status_error(anthropic.RateLimitError, 429),
    )
    models = ["first", "second", "third"]
    out = run(call_llm("hi", provider="anthropic", client=client, models=models))
    assert out == "answer"
    assert client.models == models


def test_auth_error_stops_without_fallback():
    client = FakeOpenAI(status_error(openai.AuthenticationError, 401, "bad key"))
    with pytest.raises(ProviderError, match="bad key"):
        run(call_llm("hi", provider="openai", client=client, models=["a", "b"]))
    assert client.models == ["a"]


def test_all_models_exhausted_raises_with_details():
    client = FakeOllama(ollama.ResponseError("model not found", 404))
    with pytest.raises(ProviderError, match=re.escape("ollama pull qwen2.5-coder:7b")):
        run(call_llm("hi", provider="ollama", client=client, models=["qwen2.5-coder:7b"]))


def test_ollama_connection_refused_is_explained():
    client = FakeOllama(ConnectionError("Failed to connect to Ollama"))
    with pytest.raises(ProviderError, match="Is Ollama running"):
        run(call_llm("hi", provider="ollama", client=client, models=["qwen2.5-coder:7b"]))


def test_missing_api_key_raises_before_any_call(monkeypatch: pytest.MonkeyPatch):
    with pytest.raises(ProviderError, match="ANTHROPIC_API_KEY is not set"):
        run(call_llm("hi", provider="anthropic"))


def test_model_override_is_tried_first(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("VIBETTER_MODEL", "my-model")
    client = FakeOpenAI()
    run(call_llm("hi", provider="openai", client=client))
    assert client.models == ["my-model"]


def test_anthropic_reply_skips_thinking_blocks():
    blocks = [
        SimpleNamespace(type="thinking", thinking="hmm"),
        SimpleNamespace(type="text", text="final"),
    ]
    out = run(
        call_llm("hi", provider="anthropic", client=FakeAnthropic(blocks=blocks), models=["m"])
    )
    assert out == "final"


def test_regression_ollama_window_fits_the_prompt(monkeypatch: pytest.MonkeyPatch):
    # Ollama's default window silently drops the start of a long prompt,
    # which is where the retrieved code sits.
    client = FakeOllama()
    prompt = "x = 1\n" * 20_000  # 120k characters
    run(call_llm(prompt, provider="ollama", client=client, models=["qwen2.5-coder:7b"]))
    num_ctx = client.kwargs[0]["options"]["num_ctx"]
    assert num_ctx >= len(prompt) // 4
    assert providers.ollama_num_ctx("short") == 8192
    # Each new num_ctx reloads the model, so nearby prompt sizes share one value.
    assert providers.ollama_num_ctx("x" * 20_000) == providers.ollama_num_ctx("x" * 30_000) == 16384
    monkeypatch.setenv("VIBETTER_OLLAMA_NUM_CTX", "4096")
    assert providers.ollama_num_ctx(prompt) == 4096
