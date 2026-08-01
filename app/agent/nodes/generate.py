"""Answer generation node.

Takes the user's question plus retrieved context and calls the configured LLM
(via app.llm.complete) with the citation-enforcing, injection-hardened system
prompt. Raises on failure — the caller decides how to degrade (spec §15).
"""

from __future__ import annotations

from app.config import settings
from app.llm import complete
from app.prompts import (
    GENERATION_PROMPT_VERSION,
    GENERATION_SYSTEM_PROMPT,
    build_generation_user_message,
)


def generate_answer(question: str, contexts: list[dict]) -> dict:
    """Generate a cited answer from the retrieved context."""
    user = build_generation_user_message(question, contexts)
    # Deliberately NOT routed to the small model: this is the node whose output
    # the user reads and whose citations every metric scores.
    answer = complete(GENERATION_SYSTEM_PROMPT, user, max_tokens=1024, node="generate")
    return {
        "answer": answer,
        "prompt_version": GENERATION_PROMPT_VERSION,
        "model": settings.llm_model,
    }
