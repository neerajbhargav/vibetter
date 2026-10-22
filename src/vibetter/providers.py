"""LLM providers: Gemini, OpenAI, Anthropic and local Ollama.

SDKs are imported lazily, so only the chosen provider's SDK must be installed.
Each provider has a model chain. A transient error (rate limit, 5xx,
connection) or a missing model moves to the next model. Any other error
stops at once. Errors are classified by SDK exception type and HTTP status,
never by matching words in the message.

Environment:
  VIBETTER_PROVIDER  gemini | openai | anthropic | ollama (auto-detected if unset)
  VIBETTER_MODEL     tried before the provider's default chain
  GEMINI_API_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY
  OLLAMA_HOST        default http://127.0.0.1:11434
"""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import Callable
from typing import Any, Literal

from .config import VibetterError

# Model IDs checked against each provider's model list on 2026-10-21:
# platform.claude.com/docs/en/about-claude/models/overview,
# developers.openai.com/api/docs/models, ai.google.dev/gemini-api/docs/models.
# The cheapest current model comes first.
DEFAULT_MODELS: dict[str, tuple[str, ...]] = {
    "gemini": ("gemini-3.5-flash-lite", "gemini-3.8-flash", "gemini-3.6-flash"),
    "openai": ("gpt-6-luna", "gpt-6.1-sol"),
    "anthropic": ("claude-haiku-5-5", "claude-sonnet-5-5"),
    "ollama": ("qwen2.5-coder:7b",),
}

KEY_ENV = {"gemini": "GEMINI_API_KEY", "openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}
SDK = {"gemini": "google-genai", "openai": "openai", "anthropic": "anthropic", "ollama": "ollama"}
MAX_OUTPUT_TOKENS = 8192
JSON_ONLY = "Respond with valid JSON only. No markdown fences and no text outside the JSON."

Kind = Literal["transient", "missing", "fatal"]


class ProviderError(VibetterError):
    pass


def _connection_error_types() -> tuple[type[BaseException], ...]:
    """Network failure types from the SDKs that are already imported."""
    found: list[type[BaseException]] = [ConnectionError, TimeoutError]
    for module, name in (
        ("openai", "APIConnectionError"),
        ("anthropic", "APIConnectionError"),
        ("httpx", "TransportError"),
        ("httpx2", "TransportError"),
    ):
        cls = getattr(sys.modules.get(module), name, None)
        if isinstance(cls, type) and issubclass(cls, BaseException):
            found.append(cls)
    return tuple(found)


def _status(exc: BaseException) -> int | None:
    # openai/anthropic/ollama errors carry status_code; google-genai APIError carries code.
    for attr in ("status_code", "code"):
        value = getattr(exc, attr, None)
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            return value
    return None


def classify(exc: BaseException) -> Kind:
    if isinstance(exc, _connection_error_types()):
        return "transient"
    status = _status(exc)
    if status == 404:
        return "missing"
    if status is not None and (status in (408, 409, 429) or status >= 500):
        return "transient"
    return "fatal"


def get_provider_name() -> str:
    explicit = os.getenv("VIBETTER_PROVIDER", "").strip().lower()
    if explicit:
        if explicit not in DEFAULT_MODELS:
            raise ProviderError(
                f"Unknown VIBETTER_PROVIDER '{explicit}'. Use one of: {', '.join(DEFAULT_MODELS)}."
            )
        return explicit
    for name, env in KEY_ENV.items():
        if os.getenv(env):
            return name
    return "ollama"


# --- clients ----------------------------------------------------------------

_clients: dict[tuple[str, str], Any] = {}


def _import(provider: str, module: str) -> Any:
    try:
        return __import__(module, fromlist=["_"])
    except ImportError as e:
        raise ProviderError(
            f"The {SDK[provider]} package is not installed. Run: pip install 'vibetter[{provider}]'"
        ) from e


def _make_client(provider: str) -> Any:
    if provider == "ollama":
        host = os.getenv("OLLAMA_HOST") or os.getenv("OLLAMA_BASE_URL") or "http://127.0.0.1:11434"
        key = ("ollama", host)
        if key not in _clients:
            _clients[key] = _import("ollama", "ollama").Client(host=host)
        return _clients[key]

    api_key = os.getenv(KEY_ENV[provider])
    if not api_key:
        raise ProviderError(f"{KEY_ENV[provider]} is not set. Add it to ~/.vibetter/.env.")
    key = (provider, api_key)
    if key not in _clients:
        if provider == "gemini":
            _clients[key] = _import(provider, "google.genai").Client(api_key=api_key)
        elif provider == "openai":
            _clients[key] = _import(provider, "openai").OpenAI(api_key=api_key)
        else:
            _clients[key] = _import(provider, "anthropic").Anthropic(api_key=api_key)
    return _clients[key]


# --- one request per provider -------------------------------------------------


def _gemini(client: Any, model: str, prompt: str, json_mode: bool) -> str:
    kwargs: dict[str, Any] = {"model": model, "contents": prompt}
    if json_mode:
        kwargs["config"] = {"response_mime_type": "application/json"}
    return client.models.generate_content(**kwargs).text or ""


def _openai(client: Any, model: str, prompt: str, json_mode: bool) -> str:
    kwargs: dict[str, Any] = {"model": model, "messages": [{"role": "user", "content": prompt}]}
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    return client.chat.completions.create(**kwargs).choices[0].message.content or ""


def _anthropic(client: Any, model: str, prompt: str, json_mode: bool) -> str:
    kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": MAX_OUTPUT_TOKENS,
        "messages": [{"role": "user", "content": prompt}],
    }
    if json_mode:
        kwargs["system"] = JSON_ONLY
    response = client.messages.create(**kwargs)
    # Current Claude models may return thinking blocks before the text.
    return "".join(b.text for b in response.content if getattr(b, "type", None) == "text")


def _ollama(client: Any, model: str, prompt: str, json_mode: bool) -> str:
    kwargs: dict[str, Any] = {"model": model, "messages": [{"role": "user", "content": prompt}]}
    if json_mode:
        kwargs["format"] = "json"
    return client.chat(**kwargs).message.content or ""


REQUEST: dict[str, Callable[[Any, str, str, bool], str]] = {
    "gemini": _gemini,
    "openai": _openai,
    "anthropic": _anthropic,
    "ollama": _ollama,
}


def _hint(provider: str, failures: list[tuple[str, BaseException]]) -> str:
    if provider != "ollama":
        return ""
    if any(classify(e) == "missing" for _, e in failures):
        return f" Pull the model first: ollama pull {failures[0][0]}"
    return " Is Ollama running? Start it with: ollama serve"


async def call_llm(
    prompt: str,
    json_mode: bool = False,
    *,
    provider: str | None = None,
    client: Any = None,
    models: list[str] | tuple[str, ...] | None = None,
) -> str:
    """Send one prompt and return the reply text. Raises ProviderError."""
    provider = provider or get_provider_name()
    if models is None:
        override = os.getenv("VIBETTER_MODEL", "").strip()
        models = ((override,) if override else ()) + DEFAULT_MODELS[provider]
    if client is None:
        client = _make_client(provider)
    request = REQUEST[provider]

    failures: list[tuple[str, BaseException]] = []
    for model in models:
        try:
            return await asyncio.to_thread(request, client, model, prompt, json_mode)
        except Exception as e:  # noqa: BLE001 - classified below; unknown errors stop the chain
            failures.append((model, e))
            if classify(e) == "fatal":
                break
    details = "; ".join(f"{model}: {type(e).__name__}: {e}" for model, e in failures)
    raise ProviderError(f"{provider} request failed ({details}).{_hint(provider, failures)}")
