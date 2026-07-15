"""Structure-aware, parent/child chunking of parsed Markdown.

Strategy (see PROJECT_SPEC.md §10.6):
  * Split on Markdown headings -> each section becomes a PARENT chunk.
  * Split each section's body into ~400-600 token CHILD chunks along paragraph
    boundaries (never mid-paragraph).
  * Each child keeps its section_heading and a link to its parent, enabling
    "small-to-big" retrieval: search precise children, expand to parents later.

Token counts here are approximate (word-based). Exact tokenization isn't needed
for chunk sizing, and avoiding a tokenizer dependency keeps this module light.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

TARGET_TOKENS = 500      # aim for ~500 tokens per child chunk
MAX_TOKENS = 600         # hard-ish upper bound before forcing a split
# Rough: English averages ~0.75 words per token, so tokens ~= words / 0.75.
_WORDS_PER_TOKEN = 0.75


def _approx_tokens(text: str) -> int:
    return int(len(text.split()) / _WORDS_PER_TOKEN)


@dataclass
class Chunk:
    text: str
    section_heading: str
    chunk_index: int          # order within the whole document
    is_parent: bool
    parent_index: int | None  # child -> index of its parent chunk
    token_count: int


@dataclass
class _Section:
    heading: str
    body: str = ""
    lines: list[str] = field(default_factory=list)


_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")


def _split_into_sections(markdown: str) -> list[_Section]:
    """Group lines under their nearest preceding Markdown heading."""
    sections: list[_Section] = []
    current = _Section(heading="(document start)")
    for line in markdown.splitlines():
        m = _HEADING_RE.match(line.strip())
        if m:
            if current.lines:
                current.body = "\n".join(current.lines).strip()
                sections.append(current)
            current = _Section(heading=m.group(2).strip())
        else:
            current.lines.append(line)
    if current.lines:
        current.body = "\n".join(current.lines).strip()
        sections.append(current)
    return [s for s in sections if s.body]


def _split_into_units(body: str) -> list[str]:
    """Break a section body into sentence-ish units.

    Splits on blank lines and sentence-ending punctuation. This works whether or
    not the source has paragraph breaks (pdfplumber output often doesn't), so a
    whole chapter still breaks into packable pieces. Any unit that is still huge
    (a very long sentence) is hard-split into word windows.
    """
    rough = re.split(r"\n\s*\n|(?<=[.;:])\s+", body)
    units: list[str] = []
    for u in (s.strip() for s in rough):
        if not u:
            continue
        if _approx_tokens(u) <= MAX_TOKENS:
            units.append(u)
            continue
        # Fallback: hard-split an oversized unit into ~TARGET-token word windows.
        words = u.split()
        window = int(TARGET_TOKENS * _WORDS_PER_TOKEN)
        for i in range(0, len(words), window):
            units.append(" ".join(words[i : i + window]))
    return units


def _split_body_into_children(body: str) -> list[str]:
    """Pack sentence-ish units into ~TARGET_TOKENS chunks."""
    children: list[str] = []
    buf: list[str] = []
    buf_tokens = 0
    for unit in _split_into_units(body):
        ut = _approx_tokens(unit)
        if buf and buf_tokens + ut > MAX_TOKENS:
            children.append(" ".join(buf))
            buf, buf_tokens = [], 0
        buf.append(unit)
        buf_tokens += ut
        if buf_tokens >= TARGET_TOKENS:
            children.append(" ".join(buf))
            buf, buf_tokens = [], 0
    if buf:
        children.append(" ".join(buf))
    return children


def chunk_markdown(markdown: str) -> list[Chunk]:
    """Turn one document's Markdown into ordered parent + child chunks."""
    chunks: list[Chunk] = []
    idx = 0
    for section in _split_into_sections(markdown):
        parent_idx = idx
        chunks.append(
            Chunk(
                text=f"{section.heading}\n\n{section.body}",
                section_heading=section.heading,
                chunk_index=idx,
                is_parent=True,
                parent_index=None,
                token_count=_approx_tokens(section.body),
            )
        )
        idx += 1
        for child_text in _split_body_into_children(section.body):
            chunks.append(
                Chunk(
                    text=child_text,
                    section_heading=section.heading,
                    chunk_index=idx,
                    is_parent=False,
                    parent_index=parent_idx,
                    token_count=_approx_tokens(child_text),
                )
            )
            idx += 1
    return chunks
