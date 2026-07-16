"""Answer generation node.

Takes the user's question plus retrieved context and calls the configured LLM
with the citation-enforcing, injection-hardened system prompt. The provider is
read from config (swappable per PROJECT_SPEC.md §7):

  * "groq" / "openai" / "ollama" / any OpenAI-compatible endpoint -> openai SDK
    pointed at settings.llm_base_url (Groq is the free default).
  * "anthropic" -> Claude via the anthropic SDK.

Raises on failure — the API layer decides how to degrade gracefully (spec §15).
"""

from __future__ import annotations

from app.config import settings
from app.prompts import (
    GENERATION_PROMPT_VERSION,
    GENERATION_SYSTEM_PROMPT,
    build_generation_user_message,
)


def _generate_openai_compatible(system: str, user: str) -> str:
    """Groq / Ollama / OpenRouter / OpenAI — all share this Chat Completions call."""
    from openai import OpenAI

    # Ollama needs no real key; hosted providers do. Fall back to a placeholder
    # so the local (keyless) case still constructs a client.
    client = OpenAI(
        api_key=settings.llm_api_key or "not-needed",
        base_url=settings.llm_base_url,
    )
    resp = client.chat.completions.create(
        model=settings.llm_model,
        max_tokens=1024,
        temperature=0.2,  # low: we want faithful, grounded answers, not creativity
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    return resp.choices[0].message.content or ""


def _generate_anthropic(system: str, user: str) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key or None)
    message = client.messages.create(
        model=settings.llm_model,
        max_tokens=1024,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return "".join(block.text for block in message.content if block.type == "text")


def generate_answer(question: str, contexts: list[dict]) -> dict:
    """Generate a cited answer from the retrieved context."""
    user = build_generation_user_message(question, contexts)
    if settings.llm_provider.lower() == "anthropic":
        answer = _generate_anthropic(GENERATION_SYSTEM_PROMPT, user)
    else:
        answer = _generate_openai_compatible(GENERATION_SYSTEM_PROMPT, user)
    return {
        "answer": answer,
        "prompt_version": GENERATION_PROMPT_VERSION,
        "model": settings.llm_model,
    }
