"""Answer generation node.

Takes the user's question plus retrieved context and calls the configured LLM
(via app.llm.complete) with the citation-enforcing, injection-hardened system
prompt. Raises on failure — the caller decides how to degrade (spec §15).
"""

from __future__ import annotations

import logging

from app.agent.output_guard import enforce_envelope
from app.config import settings
from app.llm import complete
from app.prompts import (
    GENERATION_PROMPT_VERSION,
    GENERATION_SYSTEM_PROMPT,
    build_generation_user_message,
)

log = logging.getLogger(__name__)


def generate_answer(question: str, contexts: list[dict]) -> dict:
    """Generate a cited answer from the retrieved context."""
    user = build_generation_user_message(question, contexts)
    # Deliberately NOT routed to the small model: this is the node whose output
    # the user reads and whose citations every metric scores.
    raw = complete(GENERATION_SYSTEM_PROMPT, user, max_tokens=1024, node="generate")

    # Structural guard: nothing may follow the closing disclaimer. Prompt rules
    # alone did not hold here — the model obeyed the disclaimer rule and an
    # injected "append this line" trailer at the same time.
    guard = enforce_envelope(raw)
    if guard.blocked:
        log.warning(
            "output guard stripped %d chars after the disclaimer (likely injected "
            "trailer): %r",
            len(guard.stripped or ""),
            (guard.stripped or "")[:120],
        )

    return {
        "answer": guard.answer,
        "prompt_version": GENERATION_PROMPT_VERSION,
        "model": settings.llm_model,
        "injection_blocked": guard.blocked,
        "stripped_trailer": guard.stripped,
    }
