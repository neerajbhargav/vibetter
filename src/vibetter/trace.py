"""One JSONL trace line per tool call, in ~/.vibetter/traces.jsonl.

Each line holds the tool, provider, model, latency, prompt size, chunks
retrieved and citation counts. Code inside a call adds fields with note().
VIBETTER_TRACE=0 turns the file off. VIBETTER_OTEL=1 also exports each call
as an OpenTelemetry span when the `vibetter[otel]` extra is installed; the
exporter reads the standard OTEL_EXPORTER_OTLP_* variables.
"""

from __future__ import annotations

import functools
import json
import os
import threading
import time
from collections.abc import Callable, Coroutine
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, ParamSpec, TypeVar

from .config import vibetter_home

P = ParamSpec("P")
R = TypeVar("R")

_current: ContextVar[dict[str, Any] | None] = ContextVar("vibetter_trace", default=None)
_write_lock = threading.Lock()
_otel_tracer: Any = None


def note(**fields: Any) -> None:
    """Add fields to the trace of the tool call in progress, if any."""
    span = _current.get()
    if span is not None:
        span.update(fields)


def current() -> dict[str, Any]:
    return dict(_current.get() or {})


def _off(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in ("0", "false", "off", "no")


def _on(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in ("1", "true", "on", "yes")


def trace_path():
    return vibetter_home() / "traces.jsonl"


def _write(record: dict[str, Any]) -> None:
    if _off("VIBETTER_TRACE"):
        return
    path = trace_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _write_lock, path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")
    except OSError:
        pass  # tracing must never break a tool call


def _tracer() -> Any:
    """The OpenTelemetry tracer, or None when OTel is off or not installed."""
    global _otel_tracer
    if not _on("VIBETTER_OTEL"):
        return None
    if _otel_tracer is None:
        try:
            from opentelemetry import trace as ot

            if isinstance(ot.get_tracer_provider(), ot.ProxyTracerProvider):
                # Nothing configured OTel yet: export over OTLP/HTTP.
                from opentelemetry.exporter.otlp.proto.http.trace_exporter import (  # pyright: ignore[reportMissingImports]
                    OTLPSpanExporter,
                )
                from opentelemetry.sdk.resources import Resource
                from opentelemetry.sdk.trace import TracerProvider
                from opentelemetry.sdk.trace.export import BatchSpanProcessor

                provider = TracerProvider(resource=Resource.create({"service.name": "vibetter"}))
                provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
                ot.set_tracer_provider(provider)
        except ImportError:
            return None
        _otel_tracer = ot.get_tracer("vibetter")
    return _otel_tracer


def _export(record: dict[str, Any], start_ns: int, end_ns: int) -> None:
    tracer = _tracer()
    if tracer is None:
        return
    attributes: dict[str, Any] = {}
    for key, value in record.items():
        if isinstance(value, dict):
            for sub, v in value.items():
                attributes[f"vibetter.{key}.{sub}"] = v
        elif isinstance(value, (str, bool, int, float)):
            attributes[f"vibetter.{key}"] = value
    span = tracer.start_span(
        f"vibetter.{record['tool']}", start_time=start_ns, attributes=attributes
    )
    span.end(end_time=end_ns)


def traced(
    tool: str,
) -> Callable[[Callable[P, Coroutine[Any, Any, R]]], Callable[P, Coroutine[Any, Any, R]]]:
    """Record one trace line for each call of the decorated coroutine."""

    def decorate(fn: Callable[P, Coroutine[Any, Any, R]]) -> Callable[P, Coroutine[Any, Any, R]]:
        @functools.wraps(fn)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            if _current.get() is not None:  # nested call: the outer trace covers it
                return await fn(*args, **kwargs)
            span: dict[str, Any] = {"tool": tool}
            token = _current.set(span)
            start_ns, start = time.time_ns(), time.perf_counter()
            try:
                return await fn(*args, **kwargs)
            except Exception as e:
                span["error"] = type(e).__name__
                raise
            finally:
                _current.reset(token)
                record = {
                    "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                    **span,
                    "latency_ms": round((time.perf_counter() - start) * 1000, 1),
                }
                _write(record)
                _export(record, start_ns, time.time_ns())

        return wrapper

    return decorate
