"""
Close Command — Elimination Engine tab.
Shows journal entries, rule details, gate conditions and RAG validation per transaction.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
import pandas as pd

try:
    from close_command.data.rules import ELIMINATION_RULES
except ImportError:
    ELIMINATION_RULES = {}


def _fmt_usd(val) -> str:
    try:
        return f"${abs(float(val)):,.2f}"
    except Exception:
        return str(val)


def _fmt_pct(val) -> str:
    try:
        return f"{float(val):.2f}%"
    except Exception:
        return str(val)


def render_elimination_tab(state: dict) -> None:
    """Render the Elimination Engine tab."""

    st.markdown("## Elimination Engine")
    st.divider()

    if not state:
        st.info("No pipeline run data available. Start a new close run from the sidebar.")
        return

    elimination_result = state.get("elimination_result") or {}
    journal_entries = elimination_result.get("journal_entries") or []
    computation_log = elimination_result.get("computation_log") or {}

    # ── Summary ──────────────────────────────────────────────────────────
    total_je = len(journal_entries)
    total_dr = sum(abs(float(e.get("amount_usd", 0))) for e in journal_entries if e.get("dr_cr", "").upper() == "DR")
    total_cr = sum(abs(float(e.get("amount_usd", 0))) for e in journal_entries if e.get("dr_cr", "").upper() == "CR")
    is_balanced = abs(total_dr - total_cr) < 0.01

    s1, s2, s3, s4 = st.columns(4)
    s1.metric("Journal Entries", total_je)
    s2.metric("Total Dr (USD)", _fmt_usd(total_dr))
    s3.metric("Total Cr (USD)", _fmt_usd(total_cr))
    s4.metric("Balanced", "Yes" if is_balanced else "No")

    if is_balanced:
        st.success("Journal is balanced — Dr = Cr.")
    else:
        st.error(f"Journal is NOT balanced — Dr/Cr difference: {_fmt_usd(abs(total_dr - total_cr))}")

    st.divider()

    if not journal_entries:
        st.info("No journal entries generated yet.")
        return

    # ── Transaction selector ─────────────────────────────────────────────
    # Get unique txn_ids
    txn_ids = list(dict.fromkeys(e.get("txn_id", "") for e in journal_entries if e.get("txn_id")))
    selected_txn = st.selectbox("Select Transaction to Inspect:", txn_ids)

    selected_entries = [e for e in journal_entries if e.get("txn_id") == selected_txn]

    if not selected_entries:
        st.info("No entries found for selected transaction.")
    else:
        first_entry = selected_entries[0]
        rule_code = first_entry.get("rule_code", "")
        seller = first_entry.get("seller", "")
        buyer = first_entry.get("buyer", "")

        st.markdown(f"**Transaction:** `{selected_txn}` &nbsp;|&nbsp; **{seller}** → **{buyer}** &nbsp;|&nbsp; Rule: `{rule_code}`")
        st.divider()

        panel_je, panel_rule, panel_gate, panel_rag = st.tabs([
            "Journal Entries",
            "Rule Details",
            "Gate Conditions",
            "RAG Validation",
        ])

        # ── Panel A — Journal Entries ────────────────────────────────────
        with panel_je:
            st.markdown("### Journal Entries for Transaction")
            rows = []
            for e in selected_entries:
                dr_cr = e.get("dr_cr", "").upper()
                rows.append({
                    "Rule Code": e.get("rule_code", ""),
                    "Account": e.get("account", ""),
                    "Flow": e.get("flow", "F00"),
                    "ICP": e.get("icp", ""),
                    "Custom3 CCY": e.get("custom3_ccy", "USD"),
                    "Dr/Cr": dr_cr,
                    "Amount (Abs)": _fmt_usd(e.get("amount", 0)),
                    "Amount USD": _fmt_usd(e.get("amount_usd", 0)),
                    "Audit Code": e.get("audit_code", ""),
                })
            df_je = pd.DataFrame(rows)

            def highlight_dr_cr(row):
                if row["Dr/Cr"] == "DR":
                    return ["background-color: #e8f5e9"] * len(row)
                elif row["Dr/Cr"] == "CR":
                    return ["background-color: #e3f2fd"] * len(row)
                return [""] * len(row)

            styled = df_je.style.apply(highlight_dr_cr, axis=1)
            st.dataframe(styled, use_container_width=True, hide_index=True)

        # ── Panel B — Rule Details ────────────────────────────────────────
        with panel_rule:
            st.markdown("### Rule Details")
            rule = ELIMINATION_RULES.get(rule_code)
            if rule:
                rd1, rd2 = st.columns(2)
                rd1.markdown(f"**Rule Code:** `{rule_code}`")
                rd1.markdown(f"**Description:** {rule.get('description', '')}")
                rd1.markdown(f"**Category:** `{rule.get('category', '')}`")
                rd2.markdown(f"**Dr Account:** {rule.get('dr_account', '')}")
                rd2.markdown(f"**Cr Account:** {rule.get('cr_account', '')}")

                nci = rule.get("nci_applicable", False)
                if nci:
                    st.markdown(
                        "<span style='background:#17a2b8;color:white;padding:3px 10px;"
                        "border-radius:12px;font-size:0.85rem'>NCI Applicable</span>",
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        "<span style='background:#6c757d;color:white;padding:3px 10px;"
                        "border-radius:12px;font-size:0.85rem'>NCI Not Applicable</span>",
                        unsafe_allow_html=True,
                    )

                st.markdown(f"**Formula Description:**")
                st.info(rule.get("formula_description", "No description available."))

                st.markdown("**Gate Conditions:**")
                for gc in rule.get("gate_conditions", []):
                    st.markdown(f"- `{gc}`")
            else:
                st.warning(f"Rule `{rule_code}` not found in ELIMINATION_RULES registry.")

        # ── Panel C — Gate Conditions ─────────────────────────────────────
        with panel_gate:
            st.markdown("### Gate Conditions Check")
            txn_log = computation_log.get(selected_txn) or {}
            gate_results = txn_log.get("gate_conditions") or {}

            if gate_results:
                for condition, passed in gate_results.items():
                    if passed:
                        st.markdown(f"✅ `{condition}` — **PASSED**")
                    else:
                        st.markdown(f"❌ `{condition}` — **FAILED**")
            else:
                rule = ELIMINATION_RULES.get(rule_code, {})
                gate_conditions = rule.get("gate_conditions", [])
                if gate_conditions:
                    st.caption("Gate condition results not logged — displaying expected conditions:")
                    for gc in gate_conditions:
                        st.markdown(f"○ `{gc}`")
                else:
                    st.info("No gate conditions defined for this rule.")

            gate_status = first_entry.get("gate_status", "PENDING")
            color = {"APPROVED": "#28a745", "PENDING": "#ffc107", "REJECTED": "#dc3545"}.get(gate_status, "#6c757d")
            st.markdown(
                f"**Overall Gate Status:** "
                f"<span style='background:{color};color:white;padding:3px 10px;"
                f"border-radius:12px'>{gate_status}</span>",
                unsafe_allow_html=True,
            )

        # ── Panel D — RAG Validation ──────────────────────────────────────
        with panel_rag:
            st.markdown("### RAG Validation")
            txn_log = computation_log.get(selected_txn) or {}
            rag_validation = txn_log.get("rag_validation") or {}

            confidence = float(rag_validation.get("confidence", 0.0))
            notes = rag_validation.get("notes", "No RAG validation notes available.")
            similar = rag_validation.get("similar_entries") or []

            st.markdown("**Confidence Score:**")
            st.progress(min(confidence, 1.0))
            st.caption(f"{confidence * 100:.1f}% confidence")

            st.markdown("**Validation Notes:**")
            if confidence >= 0.65:
                st.success(notes)
            elif confidence >= 0.40:
                st.warning(notes)
            else:
                st.error(notes)

            if similar:
                st.markdown("**Similar Historical Entries:**")
                for s in similar:
                    if isinstance(s, dict):
                        st.markdown(
                            f"- `{s.get('id', '')}` — similarity {s.get('similarity', 0):.2f}: "
                            f"{s.get('document', '')}"
                        )
                    else:
                        st.markdown(f"- {s}")

    st.divider()

    # ── Full Journal Entries Table ────────────────────────────────────────
    st.subheader("All Journal Entries")

    all_rows = []
    for e in journal_entries:
        all_rows.append({
            "TxnID": e.get("txn_id", ""),
            "Seller": e.get("seller", ""),
            "Buyer": e.get("buyer", ""),
            "Rule Code": e.get("rule_code", ""),
            "Account": e.get("account", ""),
            "Dr/Cr": e.get("dr_cr", "").upper(),
            "Amount USD": _fmt_usd(e.get("amount_usd", 0)),
            "Audit Code": e.get("audit_code", ""),
            "Gate Status": e.get("gate_status", "PENDING"),
        })

    if all_rows:
        df_all = pd.DataFrame(all_rows)

        def color_gate(val):
            c = {"APPROVED": "background-color:#d4edda", "REJECTED": "background-color:#f8d7da",
                 "PENDING": "background-color:#fff3cd", "BLOCKED": "background-color:#f8d7da"}.get(val, "")
            return c

        styled_all = df_all.style.map(color_gate, subset=["Gate Status"])
        st.dataframe(styled_all, use_container_width=True, hide_index=True)
    else:
        st.info("No journal entries to display.")
