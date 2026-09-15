"""Bounded parent windows that preserve distinct retrieved child passages."""

from __future__ import annotations

MAX_BLOCK_CHARS = 3000


def _window(parent: str, child: str, budget: int = MAX_BLOCK_CHARS) -> str:
    if len(parent) <= budget:
        return parent
    anchor = parent.find(child)
    if anchor < 0 or len(child) >= budget:
        return child
    # Spend remaining space around the complete child, not around its first byte.
    start = max(0, anchor - (budget - len(child)) // 2)
    return parent[start : start + budget]


def expand_context(hits: list[dict]) -> list[dict]:
    expanded: list[dict] = []
    for hit in hits:
        # Canonical page evidence already has an exact, versioned boundary.
        if hit.get("evidence_id"):
            expanded.append(dict(hit))
            continue
        key = (hit["doc_number"], hit.get("parent_index"))
        covered = any(
            (block["doc_number"], block.get("parent_index")) == key and hit["text"] in block["text"]
            for block in expanded
        )
        if covered:
            continue
        block = dict(hit)
        block["text"] = _window(hit.get("parent_text") or hit["text"], hit["text"])
        if not any(
            (b["doc_number"], b.get("parent_index")) == key and b["text"] == block["text"]
            for b in expanded
        ):
            expanded.append(block)
    return expanded
