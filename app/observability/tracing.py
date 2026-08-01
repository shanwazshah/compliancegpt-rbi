"""Node-level tracing for the agent pipeline (spec §15).

Two layers, deliberately:

1. **An in-process span recorder** that always runs. It costs nothing, needs no
   external service, and is what produces the per-node latency numbers the
   project reports (p50/p95 per node). CI and local dev exercise this path.
2. **A Langfuse exporter** that runs only when Langfuse keys are configured.

Splitting them this way means the headline observability claim ("we measure
per-node latency and cost") is backed by something that runs everywhere, rather
than depending on a hosted service being reachable. If Langfuse is unreachable,
misconfigured, or the SDK isn't installed, tracing degrades to layer 1 and the
request still succeeds — an observability backend must never be able to take
down the thing it observes.

Usage::

    with trace("query", question=q) as t:
        with span("retrieve", k=8) as s:
            hits = retrieve(...)
            s.note(hits=len(hits))
    t.duration_ms, t.spans
"""

from __future__ import annotations

import contextvars
import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from app.config import settings

log = logging.getLogger(__name__)

# Emit the "Langfuse not available" warning once per process, not per request.
_export_warned = False


@dataclass
class Span:
    """One timed step inside a trace."""

    name: str
    start: float
    end: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    @property
    def duration_ms(self) -> float:
        return ((self.end or time.monotonic()) - self.start) * 1000

    def note(self, **fields: Any) -> None:
        """Attach metadata discovered while the span was running."""
        self.metadata.update(fields)


@dataclass
class Trace:
    """A whole request: the spans it ran, in order."""

    name: str
    start: float
    end: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    spans: list[Span] = field(default_factory=list)

    @property
    def duration_ms(self) -> float:
        return ((self.end or time.monotonic()) - self.start) * 1000

    def note(self, **fields: Any) -> None:
        self.metadata.update(fields)

    def timings(self) -> dict[str, float]:
        """Per-node durations in ms, for logging and the latency report."""
        return {s.name: round(s.duration_ms, 1) for s in self.spans}


# ContextVar, not a global: FastAPI runs sync endpoints in a threadpool, so a
# module-level "current trace" would interleave spans across concurrent requests.
_current: contextvars.ContextVar[Trace | None] = contextvars.ContextVar(
    "compliancegpt_trace", default=None
)


def current_trace() -> Trace | None:
    return _current.get()


@contextmanager
def trace(name: str, **metadata: Any):
    """Start a trace. Exports to Langfuse on exit when configured."""
    t = Trace(name=name, start=time.monotonic(), metadata=dict(metadata))
    token = _current.set(t)
    try:
        yield t
    finally:
        t.end = time.monotonic()
        _current.reset(token)
        _export(t)


@contextmanager
def span(name: str, **metadata: Any):
    """Time one step. A no-op wrapper when no trace is active."""
    s = Span(name=name, start=time.monotonic(), metadata=dict(metadata))
    t = _current.get()
    if t is not None:
        t.spans.append(s)
    try:
        yield s
    except Exception as exc:
        s.error = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        s.end = time.monotonic()


def langfuse_configured() -> bool:
    """True when both Langfuse keys are set."""
    return bool(settings.langfuse_public_key and settings.langfuse_secret_key)


def _export(t: Trace) -> None:
    """Best-effort export to Langfuse. Never raises, never blocks the response."""
    global _export_warned
    if not langfuse_configured():
        return
    try:
        from langfuse import Langfuse

        client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
        remote = client.trace(name=t.name, metadata=t.metadata)
        for s in t.spans:
            remote.span(
                name=s.name,
                metadata={**s.metadata, **({"error": s.error} if s.error else {})},
                start_time=None,
                end_time=None,
            )
        client.flush()
    except Exception as exc:  # noqa: BLE001 - observability must not break serving
        if not _export_warned:
            log.warning(
                "Langfuse export unavailable (%s: %s); continuing with in-process "
                "tracing only. Install `langfuse` and check LANGFUSE_* settings.",
                type(exc).__name__,
                exc,
            )
            _export_warned = True
