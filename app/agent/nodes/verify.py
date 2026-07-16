"""Verify-citations node (spec §11.7).

Parse every document number the answer cites and confirm each one is actually
present in the retrieved context. A cited number that was NOT retrieved is a
hallucinated citation — the single most damaging failure for a compliance tool.
"""

from __future__ import annotations

import re

# Matches bracketed regulator doc numbers, e.g. [RBI/DOR/2025-26/361], [SEBI/...].
_CITATION_RE = re.compile(r"\[\s*((?:RBI|SEBI)/[^\]]+?)\s*\]", re.IGNORECASE)


def verify_citations(answer: str, hits: list[dict]) -> tuple[bool, list[str], list[str]]:
    """Return (all_valid, cited_numbers, hallucinated_numbers).

    Comparison is case-insensitive (RBI doc numbers vary between DoR/DOR).
    """
    retrieved = {h["doc_number"].lower() for h in hits}
    cited = sorted({m.strip() for m in _CITATION_RE.findall(answer)})
    hallucinated = [c for c in cited if c.lower() not in retrieved]
    return (len(hallucinated) == 0, cited, hallucinated)
