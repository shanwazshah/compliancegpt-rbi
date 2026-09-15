"""Shared retrieval modes. Importing this module never loads an ML library."""

from typing import Literal

RetrievalStrategy = Literal[
    "dense", "bm25", "hybrid", "hybrid_rerank", "lexical", "pageindex", "graph_pageindex"
]
STRATEGIES = ("dense", "bm25", "hybrid", "hybrid_rerank", "lexical", "pageindex", "graph_pageindex")
VECTOR_STRATEGIES = frozenset({"dense", "bm25", "hybrid", "hybrid_rerank"})
