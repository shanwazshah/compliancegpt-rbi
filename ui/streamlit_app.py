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

    with st.expander(f"Retrieved sources ({len(data['retrieved_sources'])})"):
        for s in data["retrieved_sources"]:
            st.markdown(
                f"**{s['doc_number']}** · {s.get('section_heading') or '—'} "
                f"· score={s['score']}"
            )

    st.caption(
        f"Reference date used: {data['reference_date_used']} "
        f"· model: {data.get('model') or 'n/a'}"
    )
