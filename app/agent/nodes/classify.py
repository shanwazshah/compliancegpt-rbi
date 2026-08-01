"""Classify node: scope check + past-date extraction.

Asks the LLM whether the question is in-scope for RBI/SEBI compliance and whether
it references a specific past date. Robust to LLM/JSON failure — on any error it
"fails open" (assume in-scope, no date) so the system still attempts an answer.
"""

from __future__ import annotations

import json
import re

from app.llm import complete
from app.prompts import CLASSIFY_SYSTEM_PROMPT


def classify_query(question: str) -> dict:
    """Return {'in_scope': bool, 'reference_date': str | None}."""
    try:
        # node="classify" routes this to the small model (see app/llm.py FAST_NODES):
        # a short scope check returning JSON does not need the 70B.
        raw = complete(CLASSIFY_SYSTEM_PROMPT, question, max_tokens=120, node="classify")
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        data = json.loads(match.group()) if match else {}
        return {
            "in_scope": bool(data.get("in_scope", True)),
            "reference_date": data.get("reference_date") or None,
        }
    except Exception:
        return {"in_scope": True, "reference_date": None}
