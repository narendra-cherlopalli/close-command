"""
Close Command — Pipeline Monitor tab.
Shows per-agent card status, error/escalation log, checkpoint timeline and replay controls.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
import pandas as pd
from datetime import datetime


def _badge(status: str) -> str:
    """Return an HTML badge for an agent status."""
    color_map = {
        "Running": "#0d6efd",
        "Complete": "#28a745",
        "Pending": "#adb5bd",
        "Error": "#dc3545",
        "Skipped": "#6c757d",
    }
    bg = color_map.get(status, "#6c757d")
    return (
        f"<span style='background:{bg};color:white;padding:2px 8px;"
        f"border-radius:12px;font-size:0.8rem'>{status}</span>"
    )


def _agent_status(agent_name: str, current_agent: str, result: dict | None, errors: list) -> str:
    """Determine the display status of an agent from pipeline state."""
    agent_errors = [e for e in errors if agent_name.lower() in e.lower()]
    if agent_errors:
        return "Error"
    if agent_name == current_agent:
        return "Running"
    if result is not None:
        return "Complete"
    return "Pending"


def render_pipeline_monitor(db, state: dict) -> None:
    """Render the Agent Pipeline Monitor tab."""

    st.markdown("## Agent Pipeline Monitor")
    st.divider()

    if not state:
        st.info("No pipeline run data available. Start a new close run from the sidebar.")
        return

    current_agent = state.get("current_agent", "")
    errors = state.get("errors") or []
    escalations = state.get("escalations") or []

    agents_config = [
        {
            "name": "Ingestion",
            "icon": "📥",
            "result_key": "ingestion_result",
            "input_summary_keys": ["source_file", "period", "scenario"],
            "output_summary_keys": ["transaction_count", "entity_count", "status"],
        },
        {
            "name": "Matching",
            "icon": "🔗",
            "result_key": "matching_result",
            "input_summary_keys": ["transaction_count"],
            "output_summary_keys": ["matched_count", "not_matched_count", "exception_count", "match_rate_pct"],
        },
        {
            "name": "Elimination",
            "icon": "📐",
            "result_key": "elimination_result",
            "input_summary_keys": ["pair_count"],
            "output_summary_keys": ["journal_entry_count", "gate_failure_count", "total_dr_usd", "total_cr_usd"],
        },
        {
            "name": "Validation",
            "icon": "✅",
            "result_key": "validation_result",
            "input_summary_keys": [],
            "output_summary_keys": ["validation_score", "recommendation", "balance_check", "continuation_check"],
        },
        {
            "name": "Review",
            "icon": "👁",
            "result_key": "review_result",
            "input_summary_keys": [],
            "output_summary_keys": ["total_items", "pending_items", "approved_count", "rejected_count"],
        },
        {
            "name": "Output",
            "icon": "📄",
            "result_key": "output_result",
            "input_summary_keys": [],
            "output_summary_keys": ["journal_entry_count", "approved_count", "jlf_line_count"],
        },
    ]

    for agent_cfg in agents_config:
        agent_name = agent_cfg["name"]
        icon = agent_cfg["icon"]
        result = state.get(agent_cfg["result_key"])
        status = _agent_status(agent_name, current_agent, result, errors)

        with st.expander(f"{icon} **{agent_name} Agent** — {status}", expanded=(status == "Running")):
            st.markdown(f"**Status:** {_badge(status)}", unsafe_allow_html=True)

            # Input summary
            st.markdown("**Input Summary:**")
            if agent_name == "Ingestion":
                in_cols = st.columns(3)
                in_cols[0].metric("Source File", state.get("source_file") or "N/A")
                in_cols[1].metric("Period", state.get("period") or "N/A")
                in_cols[2].metric("Scenario", state.get("scenario") or "N/A")
            elif agent_name == "Matching":
                ingestion_result = state.get("ingestion_result") or {}
                in_cols = st.columns(2)
                in_cols[0].metric("Transaction Count", ingestion_result.get("transaction_count", 0))
                in_cols[1].metric("Entity Count", ingestion_result.get("entity_count", 0))
            elif agent_name == "Elimination":
                matching_result = state.get("matching_result") or {}
                matched = len(matching_result.get("matched_pairs") or [])
                not_m = len(matching_result.get("not_matched_pairs") or [])
                in_cols = st.columns(2)
                in_cols[0].metric("Matched Pairs", matched)
                in_cols[1].metric("Not Matched Pairs", not_m)
            elif agent_name == "Validation":
                elim_result = state.get("elimination_result") or {}
                in_cols = st.columns(2)
                in_cols[0].metric("Journal Entries", elim_result.get("journal_entry_count", 0))
                in_cols[1].metric("Gate Failures", elim_result.get("gate_failure_count", 0))
            elif agent_name == "Review":
                val_result = state.get("validation_result") or {}
                in_cols = st.columns(2)
                in_cols[0].metric("Validation Score", f"{val_result.get('validation_score', 0):.1f}")
                in_cols[1].metric("Recommendation", val_result.get("recommendation", "N/A"))
            elif agent_name == "Output":
                review_result = state.get("review_result") or {}
                cr = review_result.get("close_readiness") or {}
                in_cols = st.columns(2)
                in_cols[0].metric("Ready", "Yes" if cr.get("ready") else "No")
                in_cols[1].metric("Approved", cr.get("approved_count", 0))

            # Output summary
            if result is not None:
                st.markdown("**Output Summary:**")
                o_keys = agent_cfg["output_summary_keys"]
                if o_keys:
                    out_cols = st.columns(min(len(o_keys), 4))
                    for j, key in enumerate(o_keys):
                        val = result.get(key)
                        if val is None:
                            # Attempt nested look-ups
                            if key == "matched_count":
                                val = len(result.get("matched_pairs") or [])
                            elif key == "not_matched_count":
                                val = len(result.get("not_matched_pairs") or [])
                            elif key == "exception_count":
                                val = len(result.get("exception_pairs") or [])
                        label = key.replace("_", " ").title()
                        display_val = f"{val:.2f}" if isinstance(val, float) else str(val) if val is not None else "N/A"
                        out_cols[j % 4].metric(label, display_val)
                else:
                    st.json({k: v for k, v in result.items() if not isinstance(v, (list, dict)) or len(str(v)) < 200})
            else:
                st.caption("No output available yet.")

            # Agent-specific errors
            agent_errors = [e for e in errors if agent_name.lower() in e.lower()]
            if agent_errors:
                st.error("**Errors from this stage:**")
                for err in agent_errors:
                    st.code(err)

            # Agent-specific escalations
            agent_escs = [e for e in escalations if agent_name.lower() in str(e).lower()]
            if agent_escs:
                st.warning("**Escalations from this stage:**")
                for esc in agent_escs:
                    st.write(f"- {esc.get('message', str(esc))}")

    st.divider()

    # ── Error & Escalation Log ──────────────────────────────────────────
    st.subheader("Error and Escalation Log")

    all_issues = []
    for err in errors:
        all_issues.append({"Type": "Error", "Message": err, "Agent": _extract_agent_from_msg(err)})
    for esc in escalations:
        all_issues.append({
            "Type": "Escalation",
            "Message": esc.get("message", str(esc)),
            "Agent": esc.get("agent", "—"),
        })

    if all_issues:
        df_issues = pd.DataFrame(all_issues)
        st.dataframe(df_issues, use_container_width=True, hide_index=True)
    else:
        st.success("No errors or escalations in this run.")

    st.divider()

    # ── Checkpoint Timeline ─────────────────────────────────────────────
    st.subheader("Checkpoint Timeline — All Batches")

    try:
        all_batches = db.get_all_batches()
        if all_batches:
            df_batches = pd.DataFrame(all_batches)[
                ["batch_id", "period", "scenario", "status", "started_at", "completed_at"]
            ]
            df_batches.columns = ["Batch ID", "Period", "Scenario", "Status", "Started", "Completed"]
            st.dataframe(df_batches, use_container_width=True, hide_index=True)
        else:
            st.info("No batch history recorded yet.")
    except Exception as exc:
        st.error(f"Could not load batch history: {exc}")

    st.divider()

    # ── Replay from Checkpoint ──────────────────────────────────────────
    st.subheader("Replay from Checkpoint")

    try:
        all_batches_list = db.get_all_batches()
        if all_batches_list:
            batch_options = [b["batch_id"] for b in all_batches_list]
            selected_batch = st.selectbox("Select batch to replay:", batch_options)
            if st.button("Replay from Checkpoint"):
                st.session_state["replay_batch_id"] = selected_batch
                st.info(
                    f"Replay requested for batch `{selected_batch}`. "
                    "This will re-run the pipeline from the saved LangGraph checkpoint. "
                    "Use the sidebar to trigger the run."
                )
        else:
            st.info("No batches available for replay.")
    except Exception as exc:
        st.error(f"Could not load batches for replay: {exc}")


def _extract_agent_from_msg(msg: str) -> str:
    """Extract agent name from error message if present."""
    for a in ["ingest_node", "match_node", "eliminate_node", "validate_node", "review_node", "output_node"]:
        if a in msg.lower():
            return a
    return "—"
