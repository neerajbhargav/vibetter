"""
Multi-provider LLM dispatch for VIBETTER.
Lazy imports so users only need the SDK for their chosen provider.

Config (env vars):
  VIBETTER_PROVIDER  = gemini | openai | anthropic | ollama  (auto-detected if unset)
  GEMINI_API_KEY     = ...
  OPENAI_API_KEY     = ...
  ANTHROPIC_API_KEY  = ...
  OLLAMA_BASE_URL    = http://localhost:11434  (default)
  VIBETTER_MODEL     = override the primary model name
"""

import os
import asyncio

# Per-provider default model fallback chains
DEFAULT_MODELS = {
    "gemini":    ["gemini-2.0-flash-lite", "gemini-2.5-flash", "gemini-2.0-flash"],
    "openai":    ["gpt-4o-mini", "gpt-4o", "gpt-3.5-turbo"],
    "anthropic": ["claude-sonnet-4-20250514", "claude-haiku-4-20250414"],
    "ollama":    ["llama3", "mistral", "codellama"],
}

# Cached clients (initialized on first call)
_clients = {}


def _is_transient(err_str: str) -> bool:
    """Check if an error is transient (rate limit, capacity, temporary outage)."""
    lower = err_str.lower()
    return any(x in lower for x in (
        "429", "503", "529", "rate", "quota", "resource_exhausted",
        "unavailable", "overloaded", "high demand", "capacity",
        "no longer available", "deprecated",
    ))


def _is_model_missing(err_str: str) -> bool:
    """Check if error means the model doesn't exist (try next model)."""
    lower = err_str.lower()
    return any(x in lower for x in ("404", "not_found", "does not exist", "not found"))


# ---- Gemini ----------------------------------------------------------------

async def _call_gemini(prompt: str, json_mode: bool, models: list) -> str:
    try:
        from google import genai
        from google.genai import types as genai_types
    except ImportError:
        return "Error: google-genai package not installed. Run: pip install google-genai"

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return "Error: GEMINI_API_KEY is not set. Add it to backend/.env"

    if "gemini" not in _clients:
        _clients["gemini"] = genai.Client(api_key=api_key)
    client = _clients["gemini"]

    config = genai_types.GenerateContentConfig(
        response_mime_type="application/json"
    ) if json_mode else None
    last_error = None

    for model in models:
        try:
            kwargs = {"model": model, "contents": prompt}
            if config:
                kwargs["config"] = config
            response = await asyncio.to_thread(
                client.models.generate_content, **kwargs
            )
            return response.text
        except Exception as e:
            err = str(e)
            if _is_transient(err) or _is_model_missing(err):
                last_error = e
                continue
            raise

    return f"Error: All Gemini models exhausted. Details: {last_error}"


# ---- OpenAI ----------------------------------------------------------------

async def _call_openai(prompt: str, json_mode: bool, models: list) -> str:
    try:
        import openai
    except ImportError:
        return "Error: openai package not installed. Run: pip install openai"

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return "Error: OPENAI_API_KEY is not set. Add it to backend/.env"

    if "openai" not in _clients:
        _clients["openai"] = openai.OpenAI(api_key=api_key)
    client = _clients["openai"]
    last_error = None

    for model in models:
        try:
            kwargs = {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
            }
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}
            response = await asyncio.to_thread(
                client.chat.completions.create, **kwargs
            )
            return response.choices[0].message.content
        except Exception as e:
            err = str(e)
            if _is_transient(err) or _is_model_missing(err):
                last_error = e
                continue
            raise

    return f"Error: All OpenAI models exhausted. Details: {last_error}"


# ---- Anthropic -------------------------------------------------------------

async def _call_anthropic(prompt: str, json_mode: bool, models: list) -> str:
    try:
        import anthropic
    except ImportError:
        return "Error: anthropic package not installed. Run: pip install anthropic"

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return "Error: ANTHROPIC_API_KEY is not set. Add it to backend/.env"

    if "anthropic" not in _clients:
        _clients["anthropic"] = anthropic.Anthropic(api_key=api_key)
    client = _clients["anthropic"]
    last_error = None

    for model in models:
        try:
            kwargs = {
                "model": model,
                "max_tokens": 16384,
                "messages": [{"role": "user", "content": prompt}],
            }
            if json_mode:
                kwargs["system"] = (
                    "Respond with valid JSON only. "
                    "No markdown fences, no explanation, no text outside the JSON."
                )
            response = await asyncio.to_thread(
                client.messages.create, **kwargs
            )
            return response.content[0].text
        except Exception as e:
            err = str(e)
            if _is_transient(err) or _is_model_missing(err):
                last_error = e
                continue
            raise

    return f"Error: All Anthropic models exhausted. Details: {last_error}"


# ---- Ollama ----------------------------------------------------------------

async def _call_ollama(prompt: str, json_mode: bool, models: list) -> str:
    try:
        import ollama
    except ImportError:
        return "Error: ollama package not installed. Run: pip install ollama"

    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    if "ollama" not in _clients:
        _clients["ollama"] = ollama.Client(host=base_url)
    client = _clients["ollama"]
    last_error = None

    for model in models:
        try:
            kwargs = {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
            }
            if json_mode:
                kwargs["format"] = "json"
            response = await asyncio.to_thread(client.chat, **kwargs)
            return response.message.content
        except Exception as e:
            err = str(e)
            if _is_transient(err) or _is_model_missing(err):
                last_error = e
                continue
            raise

    return f"Error: All Ollama models exhausted. Is Ollama running? Details: {last_error}"


# ---- Dispatch --------------------------------------------------------------

PROVIDERS = {
    "gemini":    _call_gemini,
    "openai":    _call_openai,
    "anthropic": _call_anthropic,
    "ollama":    _call_ollama,
}


def get_provider_name() -> str:
    """Detect provider from VIBETTER_PROVIDER env var, or auto-detect from API key."""
    explicit = os.getenv("VIBETTER_PROVIDER", "").lower().strip()
    if explicit in PROVIDERS:
        return explicit
    # Auto-detect from whichever API key is set
    if os.getenv("GEMINI_API_KEY"):
        return "gemini"
    if os.getenv("OPENAI_API_KEY"):
        return "openai"
    if os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic"
    return "ollama"


async def call_llm(prompt: str, json_mode: bool = False) -> str:
    """Single entry point for all LLM calls. Replaces _call_gemini everywhere."""
    provider = get_provider_name()
    if provider not in PROVIDERS:
        return f"Error: Unknown provider '{provider}'. Use: gemini, openai, anthropic, or ollama"

    model_override = os.getenv("VIBETTER_MODEL")
    default_chain = DEFAULT_MODELS.get(provider, [])
    models = ([model_override] + default_chain) if model_override else default_chain

    return await PROVIDERS[provider](prompt, json_mode, models)
