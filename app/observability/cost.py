"""Per-call token and cost accounting (spec §15).

Every LLM call in this system goes through `app.llm.complete()`, so this module
is the one place that has to know about prices. Two pieces:

  * a price table keyed by model, and
  * a per-request accumulator so a single API request can report the *total*
    cost of every node that ran (classify + generate + groundedness), without
    threading a cost parameter through the whole LangGraph state.

## Unknown models cost `None`, not `0.0`

If a model is missing from the table we return `None` and the caller reports
"unknown", rather than silently summing zeros into a confident-looking `$0.0000`
per query. This is the same rule the eval harness applies to failed judge calls
(see docs/adr/0007): a number you could not measure must never be laundered into
a number that looks measured. A `$0.00/query` claim in a README is exactly the
kind of thing an interviewer will probe.

Prices are USD per 1,000,000 tokens, (input, output).
"""

from __future__ import annotations

import contextvars
from contextlib import contextmanager
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Price table
#
# Anthropic list prices (first-party API, verified 2026-08).
# Groq prices are that vendor's published rates for its hosted open-source
# models; they are cheap but NOT free above the free tier, and they change more
# often than Anthropic's. Override any entry via `register_price()` rather than
# editing this table if you are running on a negotiated rate.
# ---------------------------------------------------------------------------
PRICES: dict[str, tuple[float, float]] = {
    # --- Anthropic ---
    "claude-opus-5": (5.00, 25.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
    # --- Groq (default provider for this project) ---
    "llama-3.3-70b-versatile": (0.59, 0.79),
    "llama-3.1-8b-instant": (0.05, 0.08),
}


def register_price(model: str, input_per_mtok: float, output_per_mtok: float) -> None:
    """Add or override a price (for a model or rate this table doesn't know)."""
    PRICES[model] = (input_per_mtok, output_per_mtok)


def price_for(model: str | None) -> tuple[float, float] | None:
    """Return (input, output) price per 1M tokens, or None if we don't know it.

    Falls back to the longest matching prefix so that a dated or suffixed
    variant ("llama-3.3-70b-versatile-preview") still prices correctly instead
    of silently becoming an unknown.
    """
    if not model:
        return None
    if model in PRICES:
        return PRICES[model]
    matches = [k for k in PRICES if model.startswith(k)]
    return PRICES[max(matches, key=len)] if matches else None


@dataclass
class Usage:
    """Token counts and cost for a single LLM call."""

    model: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float | None = None       # None = price unknown, NOT free
    node: str | None = None             # which agent node made the call

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


def compute_cost(model: str | None, prompt_tokens: int, completion_tokens: int) -> float | None:
    """Cost in USD for one call, or None when the model's price is unknown."""
    price = price_for(model)
    if price is None:
        return None
    in_rate, out_rate = price
    return (prompt_tokens * in_rate + completion_tokens * out_rate) / 1_000_000


# ---------------------------------------------------------------------------
# Per-request accumulation
#
# A ContextVar (not a module global) so concurrent requests can't pollute each
# other's totals — FastAPI runs sync endpoints in a threadpool, and each thread
# gets its own context.
# ---------------------------------------------------------------------------
@dataclass
class UsageAccumulator:
    """Collects every Usage recorded inside one `capture()` block."""

    calls: list[Usage] = field(default_factory=list)

    @property
    def prompt_tokens(self) -> int:
        return sum(u.prompt_tokens for u in self.calls)

    @property
    def completion_tokens(self) -> int:
        return sum(u.completion_tokens for u in self.calls)

    @property
    def cost_usd(self) -> float | None:
        """Total cost, or None if ANY call's price was unknown.

        Deliberately pessimistic: a partial total presented as a full one would
        understate cost, and understating cost is the failure mode that matters.
        """
        if not self.calls:
            return None
        if any(u.cost_usd is None for u in self.calls):
            return None
        return sum(u.cost_usd for u in self.calls)  # type: ignore[misc]


_current: contextvars.ContextVar[UsageAccumulator | None] = contextvars.ContextVar(
    "compliancegpt_usage", default=None
)


@contextmanager
def capture():
    """Collect LLM usage recorded inside this block.

    Usage::

        with capture() as usage:
            run_agent(question)
        print(usage.cost_usd, usage.total_tokens)
    """
    acc = UsageAccumulator()
    token = _current.set(acc)
    try:
        yield acc
    finally:
        _current.reset(token)


def record(usage: Usage) -> None:
    """Record one call's usage against the active capture block (if any)."""
    acc = _current.get()
    if acc is not None:
        acc.calls.append(usage)
