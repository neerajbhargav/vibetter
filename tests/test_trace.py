"""Tracing: one JSONL line per tool call, plus the optional OpenTelemetry span."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import FakeLLM, call_tool

from vibetter import trace
from vibetter.providers import ProviderError
from vibetter.server import create_server


def read_traces() -> list[dict]:
    path = trace.trace_path()
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def test_one_trace_line_per_tool_call(repo: Path):
    llm = FakeLLM("divide is at src/calc.py:L5-L8 and nowhere.py:1")
    server = create_server(repo, llm)
    call_tool(server, "scholar_explain", {"file_path": "src/calc.py", "question": "q"})
    call_tool(server, "search_code", {"query": "clamp"})
    first, second = read_traces()
    assert first["tool"] == "scholar_explain"
    assert first["provider"] == "injected"
    assert first["prompt_chars"] == len(llm.last)
    assert first["chunks_retrieved"] >= 1 and first["chunks_in_context"] >= 1
    assert first["citations"] == {"total": 2, "valid": 1, "grounded": 1, "unverified": 1}
    assert first["latency_ms"] >= 0 and "ts" in first
    assert second["tool"] == "search_code" and "prompt_chars" not in second


def test_failed_call_is_traced_with_the_error(repo: Path):
    server = create_server(repo, FakeLLM(error=ProviderError("no key")))
    result = call_tool(server, "scholar_explain", {"file_path": "src/calc.py", "question": "q"})
    assert result.is_error
    (line,) = read_traces()
    assert line["error"] == "ProviderError"


def test_trace_file_can_be_turned_off(repo: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("VIBETTER_TRACE", "0")
    call_tool(create_server(repo, FakeLLM()), "search_code", {"query": "clamp"})
    assert read_traces() == []


def test_provider_and_model_are_traced(repo: Path, monkeypatch: pytest.MonkeyPatch):
    from types import SimpleNamespace

    from vibetter import providers

    class Client:
        def chat(self, **kwargs):
            return SimpleNamespace(message=SimpleNamespace(content="ok"))

    monkeypatch.setenv("VIBETTER_PROVIDER", "ollama")
    monkeypatch.setattr(providers, "_make_client", lambda provider: Client())
    call_tool(create_server(repo), "scholar_explain", {"file_path": "src/calc.py", "question": "q"})
    (line,) = read_traces()
    assert (line["provider"], line["model"], line["fallback_hops"]) == (
        "ollama",
        "qwen2.5-coder:7b",
        0,
    )


def test_opentelemetry_span_exported(repo: Path, monkeypatch: pytest.MonkeyPatch):
    from opentelemetry import trace as ot
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    ot.set_tracer_provider(provider)  # once per process; this is the only test that sets it
    monkeypatch.setattr(trace, "_otel_tracer", None)
    monkeypatch.setenv("VIBETTER_OTEL", "1")
    call_tool(create_server(repo, FakeLLM()), "search_code", {"query": "clamp"})
    # FastMCP exports its own spans too; keep ours.
    (span,) = [s for s in exporter.get_finished_spans() if s.name.startswith("vibetter.")]
    assert span.name == "vibetter.search_code"
    chunks = (span.attributes or {}).get("vibetter.chunks_retrieved")
    assert isinstance(chunks, int) and chunks >= 1
