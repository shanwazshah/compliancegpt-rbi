"""Streamlit chat UI for local API use and the self-contained hosted demo."""

from pathlib import Path
import sys

import requests
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import settings

API_URL = settings.compliancegpt_api
BUNDLED_CORPUS = PROJECT_ROOT / "streamlit_data" / "corpus.json"


@st.cache_data(ttl=30)
def _api_available() -> bool:
    try:
        return requests.get(f"{API_URL}/api/ready", timeout=2).status_code == 200
    except Exception:
        return False


USE_EMBEDDED = BUNDLED_CORPUS.exists() and not _api_available()


@st.cache_data(ttl=300)
def _doc_id_by_number() -> dict:
    """Map doc_number -> id (cached) so we can fetch a cited doc's graph."""
    try:
        docs = requests.get(f"{API_URL}/api/documents", timeout=15).json()
        return {d["doc_number"]: d["id"] for d in docs}
    except Exception:
        return {}


def _graph_dot(doc_id: str) -> str | None:
    """Fetch a document's supersession graph and render it as Graphviz DOT."""
    try:
        g = requests.get(f"{API_URL}/api/documents/{doc_id}/supersession-graph", timeout=15).json()
    except Exception:
        return None
    if not g.get("edges"):
        return None
    label = {n["id"]: n["doc_number"] for n in g["nodes"]}
    lines = ["digraph { rankdir=LR; node [shape=box, style=rounded];"]
    for e in g["edges"]:
        lines.append(
            f'  "{label.get(e["from"], e["from"])}" -> '
            f'"{label.get(e["to"], e["to"])}" [label="{e["relation"]}"];'
        )
    lines.append("}")
    return "\n".join(lines)


st.set_page_config(page_title="ComplianceGPT", page_icon="⚖️", layout="centered")
st.title("⚖️ ComplianceGPT")
st.caption(
    "RBI/SEBI compliance Q&A with verifiable citations · temporally aware "
    "(ask 'as of <date>') · NBFC pilot corpus"
)

with st.sidebar:
    if USE_EMBEDDED:
        st.success("Hosted PageIndex demo")
        st.caption("Uses a bundled, versioned five-document RBI pilot corpus.")
    st.header("Options")
    ref_date = st.text_input("Reference date (YYYY-MM-DD, optional)", value="")
    st.caption("Leave blank for today. Historical answers require a verified source version.")
    strategy = "pageindex" if USE_EMBEDDED else settings.retrieval_strategy
    if st.checkbox("Show development controls"):
        choices = (
            ["lexical", "pageindex", "graph_pageindex"]
            if USE_EMBEDDED
            else ["dense", "lexical", "pageindex", "graph_pageindex"]
        )
        strategy = st.selectbox(
            "Retrieval strategy",
            choices,
            index=choices.index(strategy) if strategy in choices else 0,
        )
    st.divider()
    st.caption("⚠️ Decision-support information, not legal advice.")

question = st.text_area(
    "Ask a compliance question",
    placeholder="e.g. What is the re-KYC periodicity for a low-risk NBFC customer?",
)

if st.button("Ask", type="primary") and question.strip():
    payload = {"question": question, "reference_date": ref_date or None, "strategy": strategy}
    with st.spinner("Retrieving and generating…"):
        try:
            if USE_EMBEDDED:
                from app.cloud_runtime import run_cloud_query

                data = run_cloud_query(**payload)
            else:
                resp = requests.post(
                    f"{API_URL}/api/query",
                    json=payload,
                    headers={"X-API-Key": settings.api_key},
                    timeout=120,
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            st.error(f"Request failed: {exc}")
            st.stop()

    if data.get("degraded"):
        st.warning("Answer service unavailable — showing retrieved passages only.")

    st.subheader("Answer")
    st.write(data["answer"])

    if data["citations"]:
        st.subheader("Citations")
        for c in data["citations"]:
            st.markdown(f"- **[{c['doc_number']}]** {c['title']} — [source]({c['url']})")
            if c.get("evidence_url"):
                st.markdown(f"[Inspect PDF page {c['page_start']}]({API_URL}{c['evidence_url']})")

        # Supersession graph for any cited document that has predecessors/successors.
        if not USE_EMBEDDED:
            id_map = _doc_id_by_number()
            for c in data["citations"]:
                doc_id = id_map.get(c["doc_number"])
                dot = _graph_dot(doc_id) if doc_id else None
                if dot:
                    st.subheader(f"🕸️ Supersession graph — {c['doc_number']}")
                    st.caption("Which document(s) this rule consolidated/superseded.")
                    st.graphviz_chart(dot)

    with st.expander(f"Retrieved sources ({len(data['retrieved_sources'])})"):
        for s in data["retrieved_sources"]:
            st.markdown(
                f"**{s['doc_number']}** · {s.get('section_heading') or '—'} · score={s['score']}"
            )

            if s.get("text"):
                st.text(s["text"])

    if data.get("graph_paths"):
        with st.expander("Source-backed document connections"):
            for edge in data["graph_paths"]:
                st.write(f"{edge['source']} → {edge['predicate']} → {edge['target']}")
                st.caption(f"Source PDF page {edge['source_page']}")
                st.text(edge["evidence_quote"])

    verified = "✓ verified" if data.get("verified_citations", True) else "⚠ unverified citation"
    cached = " · ⚡cached" if data.get("cached") else ""
    st.caption(
        f"Reference date: {data['reference_date_used']} "
        f"· in-force docs: {data.get('in_force_docs')} "
        f"· {verified}{cached} · model: {data.get('model') or 'n/a'}"
    )
