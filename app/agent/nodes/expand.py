"""Expand-context node (small-to-big retrieval, spec §11.5).

We retrieve precise child chunks, then widen each to a bounded WINDOW of its
parent (section) text — the child plus surrounding context — so the generator
sees more than the raw child without exploding the token budget.

Why windowed, not the whole parent: our chunker splits only on chapter/part
headings, so a full parent can be ~20k chars. Sending several whole chapters
overran the LLM's token limit in testing. A budgeted window centered on the
matched child keeps the answer detail and adds context, safely. (Finer parent
granularity would be a better long-term fix.)

Children sharing a parent collapse to one block (removes redundant context).
"""

from __future__ import annotations

MAX_BLOCK_CHARS = 3000


def _window(parent: str, child: str, budget: int = MAX_BLOCK_CHARS) -> str:
    """Return up to `budget` chars of parent centered on where the child appears."""
    if len(parent) <= budget:
        return parent
    anchor = parent.find(child[:120])
    if anchor < 0:
        return child  # can't locate child in parent — keep the precise child
    half = budget // 2
    start = max(0, anchor - half)
    return parent[start : start + budget]


def expand_context(hits: list[dict]) -> list[dict]:
    """Return context blocks widened to a bounded parent window, deduped by parent."""
    seen: set[tuple] = set()
    expanded: list[dict] = []
    for h in hits:
        key = (h["doc_number"], h.get("parent_index"))
        if key in seen:
            continue
        seen.add(key)
        parent = h.get("parent_text") or h["text"]
        block = dict(h)
        block["text"] = _window(parent, h["text"])
        expanded.append(block)
    return expanded
