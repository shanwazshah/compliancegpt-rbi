"""Answer generation node.

Takes the user's question plus retrieved context and calls the configured LLM
(via app.llm.complete) with the citation-enforcing, injection-hardened system
prompt. Raises on failure — the caller decides how to degrade (spec §15).
"""

from __future__ import annotations

import logging
import re

from app.agent.output_guard import guard_output
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
    # Some models copy the source heading or use decorative brackets. Preserve
    # the exact ID (including unknown IDs so verification can reject them).
    raw = re.sub(
        r"[\[【]Source \d+ \| [^\]\n】]*?citation:\s*(?:citation:\s*)?(E:[A-Za-z0-9:-]+)\s*[\]】]",
        r"[\1]",
        raw,
    )
    raw = re.sub(r"[\[【]\s*(?:citation:\s*)?(E:[A-Za-z0-9:-]+)\s*[\]】]", r"[\1]", raw)
    guard = guard_output(raw, GENERATION_SYSTEM_PROMPT)
    if guard.blocked:
        log.warning(
            "output guard stripped %d chars after the disclaimer (likely injected trailer): %r",
            len(guard.stripped or ""),
            "[redacted]",
        )
    if guard.prompt_leak_blocked:
        log.warning("output guard removed leaked system-prompt text from the answer")

    return {
        "answer": guard.answer,
        "prompt_version": GENERATION_PROMPT_VERSION,
        "model": settings.llm_model,
        "injection_blocked": guard.blocked or guard.prompt_leak_blocked,
        "stripped_trailer": guard.stripped,
        "prompt_leak_blocked": guard.prompt_leak_blocked,
    }
