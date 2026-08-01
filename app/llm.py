"""Single LLM entry point (provider-swappable per PROJECT_SPEC.md §7).

Both the generate and classify nodes go through complete(), so provider logic
lives in one place. Default provider is Groq (free, OpenAI-compatible); set
llm_provider="anthropic" for Claude.

Because every call funnels through here, this is also where token usage and cost
are measured (spec §15) — see app/observability/cost.py. Callers that only want
text keep using complete(); anything that needs the numbers calls
complete_with_usage().
"""

from __future__ import annotations

from app.config import settings
from app.observability.cost import Usage, compute_cost, record


def complete_with_usage(
    system: str,
    user: str,
    max_tokens: int = 1024,
    temperature: float = 0.2,
    model: str | None = None,
    node: str | None = None,
) -> tuple[str, Usage]:
    """Return (text, usage) for a system+user prompt.

    The usage is also recorded against the active `cost.capture()` block, so an
    API request can total the cost of every node without threading it through
    the agent state.
    """
    model = model or settings.llm_model

    if settings.llm_provider.lower() == "anthropic":
        import anthropic

        client = anthropic.Anthropic(api_key=settings.anthropic_api_key or None)
        message = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(block.text for block in message.content if block.type == "text")
        prompt_tokens = message.usage.input_tokens
        completion_tokens = message.usage.output_tokens
    else:
        from openai import OpenAI

        client = OpenAI(
            api_key=settings.llm_api_key or "not-needed", base_url=settings.llm_base_url
        )
        resp = client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        text = resp.choices[0].message.content or ""
        # An OpenAI-compatible backend *should* return usage, but not every one
        # does — treat a missing block as zero tokens rather than crashing the
        # request over accounting.
        usage_block = getattr(resp, "usage", None)
        prompt_tokens = getattr(usage_block, "prompt_tokens", 0) or 0
        completion_tokens = getattr(usage_block, "completion_tokens", 0) or 0

    usage = Usage(
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost_usd=compute_cost(model, prompt_tokens, completion_tokens),
        node=node,
    )
    record(usage)
    return text, usage


def complete(
    system: str,
    user: str,
    max_tokens: int = 1024,
    temperature: float = 0.2,
    model: str | None = None,
    node: str | None = None,
) -> str:
    """Return the model's text completion for a system+user prompt.

    `model` overrides settings.llm_model — used e.g. by the eval harness to judge
    with a different (independent) model than the one that generated the answer.
    """
    text, _usage = complete_with_usage(
        system, user, max_tokens=max_tokens, temperature=temperature, model=model, node=node
    )
    return text
