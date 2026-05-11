"""
Close Command — Dashboard / Command Centre tab.
Renders KPIs, pipeline status, IC breakdown, review panel and escalation alerts.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
from datetime import datetime

try:
    import plotly.graph_objects as go
    _PLOTLY = True
except ImportError:
    _PLOTLY = False


def _safe(state: dict, *keys, default=None):
    """Safely navigate nested dict keys."""
    obj = state
    for k in keys:
        if not isinstance(obj, dict):
            return default
        obj = obj.get(k, default)
        if obj is None:
            return default
    return obj


def render_dashboard(db, state: dict) -> None:
    """Render the Close Command dashboard tab."""

    # ── Header ──────────────────────────────────────────────────────────
    st.markdown(
        """
        <h1 style='margin-bottom:0'>⚗️ Close Command</h1>
        <p style='color:#888;font-size:1.1rem;margin-top:0'>
            Agentic Financial Close Engine &nbsp;·&nbsp; Helios Chemicals Group
        </p>
        """,
        unsafe_allow_html=True,
    )
    st.divider()

    # Guard — show placeholder if no state yet
    if not state:
        st.info("No pipeline run data available. Start a new close run from the sidebar.")
        return

    period = state.get("period", "—")
    scenario = state.get("scenario", "—")
    batch_id = state.get("batch_id", "—")
    overall_status = state.get("overall_status", "UNKNOWN")
    started_at = state.get("started_at", "")
    last_updated = state.get("last_updated", "")

    matching_result = state.get("matching_result") or {}
    review_result = state.get("review_result") or {}
    escalations = state.get("escalations") or []

    # ── Period Info ──────────────────────────────────────────────────────
    col_period, col_scenario, col_batch, col_status = st.columns(4)
    col_period.metric("Period", period)
    col_scenario.metric("Scenario", scenario)
    col_batch.metric("Batch ID", batch_id)

    status_color_map = {"COMPLETE": "🟢", "RUNNING": "🔵", "ERROR": "🔴", "ESCALATED": "🟠", "UNKNOWN": "⚪"}
    col_status.metric("Status", f"{status_color_map.get(overall_status, '⚪')} {overall_status}")

    st.divider()

    # ── KPI Row ──────────────────────────────────────────────────────────
    st.subheader("Key Performance Indicators")

    ingestion_result = state.get("ingestion_result") or {}
    matched_pairs   = matching_result.get("matched_pairs", []) or []
    not_matched     = matching_result.get("not_matched_pairs", []) or []
    fx_diff         = matching_result.get("fx_diff_pairs", []) or []
    exceptions      = matching_result.get("exception_pairs", []) or []

    # Ingestion counts
    total_fs_lines  = ingestion_result.get("total_lines", 0) or 0
    ic_lines        = ingestion_result.get("ic_lines", 0) or 0
    non_ic_lines    = ingestion_result.get("non_ic_lines", 0) or 0
    entities_present = ingestion_result.get("entities_present", []) or []
    quality_score   = ingestion_result.get("quality_score", 0.0) or 0.0

    # Matching counts
    total_ic_pairs  = len(matched_pairs) + len(not_matched) + len(fx_diff) + len(exceptions)
    matched_count   = len(matched_pairs)
    not_matched_count = len(not_matched)
    fx_diff_count   = len(fx_diff)
    exception_count = len(exceptions)
    matched_pct     = (matched_count / total_ic_pairs * 100) if total_ic_pairs > 0 else 0.0
    exception_pct   = (exception_count / total_ic_pairs * 100) if total_ic_pairs > 0 else 0.0

    close_readiness = review_result.get("close_readiness", {}) or {}
    is_ready        = close_readiness.get("ready", False)
    period_status   = "READY" if is_ready else ("BLOCKED" if exception_count > 0 else "PENDING")
    status_emoji    = {"READY": "🟢 READY", "BLOCKED": "🔴 BLOCKED", "PENDING": "🟡 PENDING"}

    # Row 1 — Financial statement overview
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Total FS Lines",   total_fs_lines,  help="All financial statement lines loaded")
    k2.metric("IC Lines",         ic_lines,         help="Intercompany lines fed to matching pipeline")
    k3.metric("Non-IC Lines",     non_ic_lines,     help="External lines used in consolidation")
    k4.metric("Entities Loaded",  len(entities_present), help=", ".join(entities_present) if entities_present else "—")

    st.write("")

    # Row 2 — IC matching results
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("IC Pairs Matched",    matched_count,       delta=f"{matched_pct:.1f}%")
    m2.metric("Not Matched",         not_matched_count,   delta=f"-{not_matched_count}" if not_matched_count else "✓ None",   delta_color="inverse")
    m3.metric("FX Diff Pairs",       fx_diff_count,       help="Cross-currency — expected translation gap")
    m4.metric("Exceptions",          exception_count,     delta=f"-{exception_count}" if exception_count else "✓ None", delta_color="inverse")

    st.write("")

    # Row 3 — Quality and close status
    q1, q2, q3, q4 = st.columns(4)
    q1.metric("Data Quality Score",  f"{quality_score:.1f}",  delta="PASS" if quality_score >= 85 else "FAIL",   delta_color="normal" if quality_score >= 85 else "inverse")
    q2.metric("Total IC Pairs",      total_ic_pairs,           help="Total bilateral IC pairs processed")
    q3.metric("Journal Entries",     len((state.get("elimination_result") or {}).get("journal_entries") or []), help="Elimination journal entries generated")
    q4.metric("Period Close Status", status_emoji.get(period_status, period_status))

    st.divider()

    # ── Agent Pipeline Status ─────────────────────────────────────────────
    st.subheader("Agent Pipeline Status")

    agent_sequence = ["Ingestion", "Matching", "Elimination", "Validation", "Review", "Output"]
    current_agent = state.get("current_agent", "")

    agent_results_map = {
        "Ingestion": state.get("ingestion_result"),
        "Matching": state.get("matching_result"),
        "Elimination": state.get("elimination_result"),
        "Validation": state.get("validation_result"),
        "Review": state.get("review_result"),
        "Output": state.get("output_result"),
    }

    # Determine completed agents: any agent before current with a result
    try:
        current_idx = agent_sequence.index(current_agent)
    except ValueError:
        current_idx = -1

    cols = st.columns(len(agent_sequence))
    for i, (col, agent) in enumerate(zip(cols, agent_sequence)):
        result_available = agent_results_map.get(agent) is not None
        if agent == current_agent:
            col.markdown(
                f"<div style='text-align:center;background:#d4edda;border-radius:8px;padding:8px;'>"
                f"<b style='color:#155724'>▶ {agent}</b><br/><small style='color:#155724'>Running</small></div>",
                unsafe_allow_html=True,
            )
        elif result_available or (current_idx >= 0 and i < current_idx):
            col.markdown(
                f"<div style='text-align:center;background:#e2e3e5;border-radius:8px;padding:8px;'>"
                f"<b style='color:#383d41'>✓ {agent}</b><br/><small style='color:#383d41'>Complete</small></div>",
                unsafe_allow_html=True,
            )
        else:
            col.markdown(
                f"<div style='text-align:center;background:#f8f9fa;border-radius:8px;padding:8px;'>"
                f"<span style='color:#adb5bd'>○ {agent}</span><br/><small style='color:#adb5bd'>Pending</small></div>",
                unsafe_allow_html=True,
            )

    st.divider()

    # ── IC Transaction Breakdown ─────────────────────────────────────────
    left_col, right_col = st.columns([1, 1])

    with left_col:
        st.subheader("IC Transaction Breakdown")
        b1, b2, b3, b4 = st.columns(4)
        b1.metric("Matched",     matched_count,       delta="✓ Clean")
        b2.metric("Not Matched", not_matched_count,   delta=f"-{not_matched_count}" if not_matched_count else "✓ None", delta_color="inverse")
        b3.metric("FX Diff",     fx_diff_count,       help="Cross-currency translation gaps")
        b4.metric("Exception",   exception_count,     delta=f"-{exception_count}" if exception_count else "✓ None", delta_color="inverse")

        # Donut chart
        if _PLOTLY and total_ic_pairs > 0:
            labels = ["Matched", "Not Matched", "FX Diff", "Exception"]
            values = [matched_count, not_matched_count, fx_diff_count, exception_count]
            colors = ["#28a745", "#dc3545", "#ffc107", "#fd7e14"]
            fig = go.Figure(data=[go.Pie(
                labels=labels,
                values=values,
                hole=0.55,
                marker_colors=colors,
                textinfo="label+percent",
                hoverinfo="label+value",
            )])
            fig.update_layout(
                showlegend=True,
                height=280,
                margin=dict(t=20, b=20, l=20, r=20),
                title_text="Match Status",
                title_x=0.5,
            )
            st.plotly_chart(fig, use_container_width=True)
        elif total_ic_pairs == 0:
            st.info("No IC pair data to chart yet.")

    with right_col:
        st.subheader("Review Status Panel")
        items_for_review = review_result.get("items_for_review") or []
        approved_count = sum(1 for x in items_for_review if x.get("decision") == "Approve")
        pending_count = sum(1 for x in items_for_review if not x.get("decision"))
        rejected_count = sum(1 for x in items_for_review if x.get("decision") == "Reject")
        escalated_count = sum(1 for x in items_for_review if x.get("decision") == "Escalate")

        r1, r2, r3, r4 = st.columns(4)
        r1.metric("Approved", approved_count)
        r2.metric("Pending", pending_count)
        r3.metric("Rejected", rejected_count, delta_color="inverse")
        r4.metric("Escalated", escalated_count)

        # Period Close Readiness bar
        total_for_review = len(items_for_review)
        readiness_pct = int((approved_count / total_for_review * 100)) if total_for_review > 0 else 0

        st.write("")
        st.markdown(f"**Period Close Readiness: {readiness_pct}%**")
        st.progress(readiness_pct / 100)

        if readiness_pct == 100:
            st.success("All items reviewed — period close is READY.")
        elif readiness_pct > 0:
            st.warning(f"{total_for_review - approved_count} item(s) still require review.")
        else:
            st.info("Review process has not started.")

    st.divider()

    # ── Run Info ─────────────────────────────────────────────────────────
    st.subheader("Run Information")
    ri1, ri2 = st.columns(2)
    ri1.markdown(f"**Last Run Started:** `{started_at or 'N/A'}`")
    ri1.markdown(f"**Last Updated:** `{last_updated or 'N/A'}`")
    ri2.markdown(f"**Batch ID:** `{batch_id}`")

    # Attempt to get next scheduled run from db batch history
    try:
        all_batches = db.get_all_batches()
        if all_batches:
            latest = all_batches[0]
            ri2.markdown(f"**Latest Batch Status:** `{latest.get('status', 'UNKNOWN')}`")
    except Exception:
        pass

    st.divider()

    # ── Escalation Alerts ────────────────────────────────────────────────
    if escalations:
        st.subheader("Escalation Alerts")
        for esc in escalations:
            esc_type = esc.get("type", "UNKNOWN")
            esc_msg = esc.get("message", str(esc))
            st.warning(f"**{esc_type}** — {esc_msg}")
    else:
        st.success("No active escalations.")
