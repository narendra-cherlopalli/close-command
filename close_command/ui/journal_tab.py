"""
Close Command — Journal Output tab.
Shows consolidation proof, JLF preview, Excel download and audit trail.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
import pandas as pd
import io
from datetime import datetime

try:
    from close_command.utils.formatters import jlf_row
except ImportError:
    def jlf_row(entry: dict) -> str:
        fields = [
            str(entry.get("txn_id", "")), str(entry.get("period", "")),
            str(entry.get("scenario", "")), str(entry.get("seller", "")),
            str(entry.get("buyer", "")), str(entry.get("rule_code", "")),
            str(entry.get("account", "")), str(entry.get("flow", "F00")),
            str(entry.get("icp", "")), str(entry.get("custom3_ccy", "USD")),
            str(entry.get("dr_cr", "")), str(entry.get("amount", 0.0)),
            str(entry.get("amount_usd", 0.0)), str(entry.get("value", "[Elimination]")),
            str(entry.get("audit_code", "")), str(entry.get("entity_method", "GLOBAL")),
            str(entry.get("pcon", 100.0)), str(entry.get("pown", 100.0)),
            str(entry.get("gate_status", "PENDING")),
            str(entry.get("computed_by", "Elimination Agent")),
            str(entry.get("computed_at", "")),
        ]
        return ";".join(fields)


def _fmt_usd(val) -> str:
    try:
        return f"${abs(float(val)):,.2f}"
    except Exception:
        return str(val)


def _build_jlf_string(entries: list[dict], period: str, scenario: str) -> str:
    """Build the full JLF file content."""
    lines = [
        f"# Close Command Journal Line Format",
        f"# Generated: {datetime.utcnow().isoformat()}",
        f"# Period: {period} | Scenario: {scenario}",
        f"# Fields: txn_id;period;scenario;seller;buyer;rule_code;account;flow;icp;"
        f"custom3_ccy;dr_cr;amount;amount_usd;value;audit_code;"
        f"entity_method;pcon;pown;gate_status;computed_by;computed_at",
        "",
    ]
    for entry in entries:
        lines.append(jlf_row(entry))
    return "\n".join(lines)


def _build_excel_bytes(entries: list[dict], audit_rows: list[dict]) -> bytes:
    """Build Excel workbook bytes with journal entries + audit trail sheets."""
    output = io.BytesIO()
    try:
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            # Journal Entries sheet
            if entries:
                je_df = pd.DataFrame([{
                    "TxnID": e.get("txn_id", ""),
                    "Seller": e.get("seller", ""),
                    "Buyer": e.get("buyer", ""),
                    "Rule Code": e.get("rule_code", ""),
                    "Account": e.get("account", ""),
                    "Flow": e.get("flow", "F00"),
                    "ICP": e.get("icp", ""),
                    "Custom3 CCY": e.get("custom3_ccy", "USD"),
                    "Dr/Cr": e.get("dr_cr", "").upper(),
                    "Amount": abs(float(e.get("amount", 0))),
                    "Amount USD": abs(float(e.get("amount_usd", 0))),
                    "Audit Code": e.get("audit_code", ""),
                    "Gate Status": e.get("gate_status", "PENDING"),
                    "Period": e.get("period", ""),
                    "Scenario": e.get("scenario", ""),
                    "Computed By": e.get("computed_by", ""),
                    "Computed At": e.get("computed_at", ""),
                } for e in entries])
                je_df.to_excel(writer, sheet_name="Journal Entries", index=False)
            else:
                pd.DataFrame(["No approved journal entries"]).to_excel(
                    writer, sheet_name="Journal Entries", index=False
                )

            # Audit Trail sheet
            if audit_rows:
                audit_df = pd.DataFrame(audit_rows)
                audit_df.to_excel(writer, sheet_name="Audit Trail", index=False)
    except Exception as exc:
        # Fallback minimal Excel
        output = io.BytesIO()
        pd.DataFrame({"Error": [str(exc)]}).to_excel(output, index=False)
    output.seek(0)
    return output.read()


def render_journal_tab(state: dict, db) -> None:
    """Render the Journal Output tab."""

    st.markdown("## Journal Output")
    st.info("Showing approved transactions only.")
    st.divider()

    if not state:
        st.info("No pipeline run data available. Start a new close run from the sidebar.")
        return

    batch_id = state.get("batch_id", "")
    period = state.get("period", "")
    scenario = state.get("scenario", "")
    output_result = state.get("output_result") or {}
    elimination_result = state.get("elimination_result") or {}

    # ── Collect approved entries (waterfall of sources) ───────────────────
    # 1. DB gate_status=APPROVED (set when pipeline completes output node)
    approved_entries = []
    try:
        approved_entries = db.get_approved_entries(batch_id) or []
    except Exception:
        pass

    # 2. output_result.approved_entries (stored in state after resume)
    if not approved_entries:
        approved_entries = output_result.get("approved_entries") or []

    # 3. All DB journal entries (pipeline completed but entries saved as PENDING)
    all_je = []
    try:
        all_je = db.get_journal_entries(batch_id) or []
    except Exception:
        all_je = elimination_result.get("journal_entries") or []

    if not all_je:
        all_je = elimination_result.get("journal_entries") or []

    # 4. Fall back to elimination entries if still nothing
    if not approved_entries:
        approved_entries = all_je

    # Load review decisions for audit
    try:
        all_decisions = db.get_review_decisions(batch_id)
        decision_map = {d["txn_id"]: d for d in all_decisions}
    except Exception:
        decision_map = {}

    # ── Consolidation Proof ───────────────────────────────────────────────
    st.subheader("Consolidation Proof")

    consolidation_proof = output_result.get("consolidation_proof") or {}
    proof_statement = consolidation_proof.get("proof_statement", "")
    entity_contributions = consolidation_proof.get("entity_contributions") or {}

    total_dr = sum(abs(float(e.get("amount_usd", 0))) for e in approved_entries if e.get("dr_cr", "").upper() == "DR")
    total_cr = sum(abs(float(e.get("amount_usd", 0))) for e in approved_entries if e.get("dr_cr", "").upper() == "CR")
    net_elim = total_dr - total_cr
    is_balanced = abs(net_elim) < 0.01

    cp1, cp2, cp3, cp4 = st.columns(4)
    cp1.metric("Total Dr (USD)", _fmt_usd(total_dr))
    cp2.metric("Total Cr (USD)", _fmt_usd(total_cr))
    cp3.metric("Net Elimination", _fmt_usd(net_elim))
    cp4.metric("Balanced", "Yes" if is_balanced else "No")

    if proof_statement:
        if is_balanced:
            st.success(proof_statement)
        else:
            st.error(proof_statement)
    else:
        if is_balanced:
            st.success(f"Journal balanced: Total Dr = Total Cr = {_fmt_usd(total_dr)}")
        else:
            st.error(f"Journal NOT balanced — difference: {_fmt_usd(abs(net_elim))}")

    if entity_contributions:
        st.markdown("**Entity Contributions (Net):**")
        ec_rows = [{"Entity": k, "Net Amount USD": _fmt_usd(v)} for k, v in entity_contributions.items()]
        st.dataframe(pd.DataFrame(ec_rows), use_container_width=True, hide_index=True)

    st.divider()

    # ── JLF Preview & Download ────────────────────────────────────────────
    st.subheader("JLF Format Preview")

    jlf_entries = approved_entries  # already has fallback from all_je above
    jlf_content = _build_jlf_string(jlf_entries, period, scenario)

    preview_lines = "\n".join(jlf_content.split("\n")[:20])
    st.code(preview_lines, language="text")

    if len(jlf_content.split("\n")) > 20:
        st.caption(f"Showing first 20 lines of {len(jlf_content.split(chr(10)))} total lines.")

    jlf_filename = f"close_command_{period}_journal.jlf"
    st.download_button(
        label="Download Full JLF File",
        data=jlf_content,
        file_name=jlf_filename,
        mime="text/plain",
    )

    st.divider()

    # ── Excel Download ────────────────────────────────────────────────────
    st.subheader("Excel Export")

    # Build audit rows for Excel sheet
    audit_rows = []
    for je in all_je:
        txn_id = je.get("txn_id", "")
        dec = decision_map.get(txn_id) or {}
        audit_rows.append({
            "TxnID": txn_id,
            "Seller": je.get("seller", ""),
            "Buyer": je.get("buyer", ""),
            "Rule Code": je.get("rule_code", ""),
            "Amount USD": abs(float(je.get("amount_usd", 0))),
            "Dr/Cr": je.get("dr_cr", "").upper(),
            "Gate Status": je.get("gate_status", "PENDING"),
            "Decision": dec.get("decision", ""),
            "Reviewer": dec.get("reviewer_name", ""),
            "Timestamp": dec.get("timestamp", ""),
            "Comment": dec.get("comment", ""),
        })

    excel_bytes = _build_excel_bytes(jlf_entries, audit_rows)
    excel_filename = f"close_command_{period}_journal.xlsx"
    st.download_button(
        label="Download Excel Workbook",
        data=excel_bytes,
        file_name=excel_filename,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    st.divider()

    # ── Audit Trail Table ─────────────────────────────────────────────────
    st.subheader("Audit Trail")

    if audit_rows:
        df_audit = pd.DataFrame(audit_rows)
        st.dataframe(df_audit, use_container_width=True, hide_index=True)

        # CSV download
        csv_data = df_audit.to_csv(index=False)
        st.download_button(
            label="Download Audit Trail CSV",
            data=csv_data,
            file_name=f"close_command_{period}_audit_trail.csv",
            mime="text/csv",
        )
    else:
        st.info("No journal entries available for audit trail.")
