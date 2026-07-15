"""Unit tests for structure-aware chunking."""

from ingestion.indexing.chunking import chunk_markdown

SAMPLE = """# Master Direction on KYC

## 1. Introduction

This Master Direction applies to all NBFCs. It sets out the framework for
customer identification and periodic updation.

## 2. Periodic Updation

Re-KYC shall be carried out at prescribed intervals depending on the customer
risk category. Low-risk customers require updation once every ten years.

High-risk customers require updation once every two years. Medium-risk once
every eight years.
"""


def test_produces_parents_and_children():
    chunks = chunk_markdown(SAMPLE)
    parents = [c for c in chunks if c.is_parent]
    children = [c for c in chunks if not c.is_parent]
    assert parents, "should produce at least one parent (section) chunk"
    assert children, "should produce at least one child chunk"


def test_children_link_to_a_parent():
    chunks = chunk_markdown(SAMPLE)
    by_index = {c.chunk_index: c for c in chunks}
    for child in (c for c in chunks if not c.is_parent):
        assert child.parent_index in by_index
        assert by_index[child.parent_index].is_parent


def test_section_heading_preserved():
    chunks = chunk_markdown(SAMPLE)
    headings = {c.section_heading for c in chunks}
    assert "2. Periodic Updation" in headings
