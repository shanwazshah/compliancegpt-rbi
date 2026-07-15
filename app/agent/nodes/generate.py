"""Answer generation node.

Takes the user's question plus the retrieved context chunks and calls the LLM
with the citation-enforcing, injection-hardened system prompt. The LLM provider
is read from config (swappable per PROJECT_SPEC.md §7); this node implements the
Anthropic path.
"""

from __future__ import annotations

from app.config import settings
from app.prompts import (
    GENERATION_PROMPT_VERSION,
    GENERATION_SYSTEM_PROMPT,
    build_generation_user_message,
)


def generate_answer(question: str, contexts: list[dict]) -> dict:
    """Generate a cited answer from the retrieved context.

    Returns {answer, prompt_version, model}. Raises if the LLM call fails — the
    API layer decides how to degrade gracefully (spec §15).
    """
    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key or None)
    message = client.messages.create(
        model=settings.llm_model,
        max_tokens=1024,
        system=GENERATION_SYSTEM_PROMPT,
        messages=[
            {"role": "user", "content": build_generation_user_message(question, contexts)}
        ],
    )
    answer = "".join(block.text for block in message.content if block.type == "text")
    return {
        "answer": answer,
        "prompt_version": GENERATION_PROMPT_VERSION,
        "model": settings.llm_model,
    }
