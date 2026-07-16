"""Single LLM entry point (provider-swappable per PROJECT_SPEC.md §7).

Both the generate and classify nodes go through complete(), so provider logic
lives in one place. Default provider is Groq (free, OpenAI-compatible); set
llm_provider="anthropic" for Claude.
"""

from __future__ import annotations

from app.config import settings


def complete(
    system: str,
    user: str,
    max_tokens: int = 1024,
    temperature: float = 0.2,
    model: str | None = None,
) -> str:
    """Return the model's text completion for a system+user prompt.

    `model` overrides settings.llm_model — used e.g. by the eval harness to judge
    with a different (independent) model than the one that generated the answer.
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
        return "".join(block.text for block in message.content if block.type == "text")

    from openai import OpenAI

    client = OpenAI(api_key=settings.llm_api_key or "not-needed", base_url=settings.llm_base_url)
    resp = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    return resp.choices[0].message.content or ""
