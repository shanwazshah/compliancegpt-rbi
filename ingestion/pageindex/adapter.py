"""Small boundary around the optional official PageIndex SDK."""

from __future__ import annotations

from pathlib import Path

from app.config import settings


def build_tree(pdf_path: Path) -> tuple[list[dict], dict]:
    try:
        from pageindex import PageIndexLocalClient
    except ImportError as exc:
        raise RuntimeError('Install the pageindex extra: pip install -e ".[pageindex]"') from exc
    if settings.pageindex_tree_mode == "layout":
        from pageindex.flash import page_index_flash
        from pageindex.utils import write_node_id

        result = page_index_flash(str(pdf_path), summary=False, optimize=False)
        tree = result.get("structure") or []
        if not tree:
            raise ValueError("PageIndex layout extraction returned no structure")
        write_node_id(tree)
        return tree, {
            "sdk_version": "0.2.10",
            "tree_mode": "layout",
            "summaries": False,
            "index_model": None,
        }
    selected = settings.llm_model_fast or settings.llm_model
    model = settings.pageindex_index_model or f"openai/{selected}"
    client = PageIndexLocalClient(
        index_model=model,
        storage_path=settings.pageindex_storage_path,
        index_backend={
            "api_key": settings.llm_api_key or "not-needed",
            "base_url": settings.llm_base_url,
        },
    )
    from openai import OpenAI

    from ingestion.pageindex.pacing import PacedCompletions, paced_sdk

    with OpenAI(
        api_key=settings.llm_api_key or "not-needed",
        base_url=settings.llm_base_url,
        timeout=120,
        max_retries=0,
    ) as transport:
        controller = PacedCompletions(
            transport,
            Path(settings.pageindex_storage_path) / "completion_cache",
            settings.pageindex_min_interval_seconds,
            settings.pageindex_max_attempts,
            settings.pageindex_max_retry_wait_seconds,
            max_output_tokens=settings.pageindex_max_output_tokens,
        )
        with paced_sdk(controller):
            submitted = client.submit_document(str(pdf_path), wait=True)
    doc_id = submitted["doc_id"]
    tree = client.get_document_structure(doc_id)
    if not isinstance(tree, list) or not tree:
        raise ValueError("PageIndex returned no usable document structure")
    return tree, {
        "sdk_document_id": doc_id,
        "index_model": model,
        "sdk_version": "0.2.10",
        "tree_mode": "full",
    }


def normalize_tree(tree: list[dict], page_count: int) -> list[dict]:
    """Accept SDK section starts and legacy bounded nodes; preserve physical pages."""
    result: list[dict] = []
    seen: set[str] = set()

    def visit(nodes: list[dict], parent: str | None, upper: int) -> None:
        for i, node in enumerate(nodes):
            node_id = str(node.get("node_id", ""))
            if not node_id or node_id in seen:
                raise ValueError("Tree node IDs must be unique and nonempty")
            seen.add(node_id)
            start = int(node.get("page_index", node.get("start_index", 0)))
            next_start = upper + 1
            if i + 1 < len(nodes):
                following = nodes[i + 1]
                next_start = int(following.get("page_index", following.get("start_index", 0)))
                if next_start < start:
                    raise ValueError("Tree pages must be ordered")
            # Include the boundary page: two sections can start on the same PDF page.
            end = int(node.get("end_index", min(upper, next_start)))
            if not 1 <= start <= end <= page_count:
                raise ValueError(f"Tree node {node_id} has an invalid page range")
            result.append(
                {
                    "node_id": node_id,
                    "parent_id": parent,
                    "title": str(node.get("title", "")),
                    "summary": str(node.get("summary", node.get("prefix_summary", ""))),
                    "page_start": start,
                    "page_end": end,
                }
            )
            visit(node.get("nodes", []), node_id, end)

    visit(tree, None, page_count)
    return result
