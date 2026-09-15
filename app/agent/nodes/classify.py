"""Classify node: scope check + past-date extraction.

Asks the LLM whether the question is in-scope for RBI/SEBI compliance and whether
it references a specific past date. Malformed classification fails closed so a
historical query cannot silently become a today query.
"""

from __future__ import annotations

import json
import re
from datetime import date

from pydantic import BaseModel, StrictBool

from app.llm import complete
from app.prompts import CLASSIFY_SYSTEM_PROMPT


class Classification(BaseModel):
    in_scope: StrictBool
    reference_date: date | None = None


def classify_query(question: str) -> dict:
    """Return {'in_scope': bool, 'reference_date': str | None}."""
    try:
        # node="classify" routes this to the small model (see app/llm.py FAST_NODES):
        # a short scope check returning JSON does not need the 70B.
        raw = complete(CLASSIFY_SYSTEM_PROMPT, question, max_tokens=120, node="classify")
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        data = Classification.model_validate(json.loads(match.group()) if match else {})
        return {
            "in_scope": data.in_scope,
            "reference_date": data.reference_date.isoformat() if data.reference_date else None,
        }
    except Exception as exc:
        raise ValueError("Could not resolve question scope and date safely") from exc
