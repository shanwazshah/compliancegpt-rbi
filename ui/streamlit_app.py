"""Minimal Streamlit chat UI for ComplianceGPT (Phase 1).

Talks to the FastAPI backend's /api/query endpoint. Keep it thin — the UI is a
window onto the API, not where logic lives.

Run (with the API already up on :8000):
    streamlit run ui/streamlit_app.py
"""

import os

import requests
import streamlit as st

API_URL = os.environ.get("COMPLIANCEGPT_API", "http://localhost:8000")


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
        lines.append(f'  "{label.get(e["from"], e["from"])}" -> '
                     f'"{label.get(e["to"], e["to"])}" [label="{e["relation"]}"];')
    lines.append("}")
    return "\n".join(lines)

st.set_page_config(page_title="ComplianceGPT", page_icon="⚖️", layout="centered")
st.title("⚖️ ComplianceGPT")
st.caption("RBI/SEBI compliance Q&A with verifiable citations · Phase 1 (NBFC pilot)")

with st.sidebar:
    st.header("Options")
    ref_date = st.text_input("Reference date (YYYY-MM-DD, optional)", value="")
    st.caption("Leave blank for 'as of today'. Temporal reasoning arrives in Phase 2.")
    st.divider()
    st.caption("⚠️ Decision-support information, not legal advice.")

question = st.text_area(
    "Ask a compliance question",
    placeholder="e.g. What is the re-KYC periodicity for a low-risk NBFC customer?",
)

if st.button("Ask", type="primary") and question.strip():
    payload = {"question": question, "reference_date": ref_date or None}
    with st.spinner("Retrieving and generating…"):
        try:
            resp = requests.post(f"{API_URL}/api/query", json=payload, timeout=120)
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

        # Supersession graph for any cited document that has predecessors/successors.
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
                f"**{s['doc_number']}** · {s.get('section_heading') or '—'} "
                f"· score={s['score']}"
            )

    verified = "✓ verified" if data.get("verified_citations", True) else "⚠ unverified citation"
    cached = " · ⚡cached" if data.get("cached") else ""
    st.caption(
        f"Reference date: {data['reference_date_used']} "
        f"· in-force docs: {data.get('in_force_docs')} "
        f"· {verified}{cached} · model: {data.get('model') or 'n/a'}"
    )
