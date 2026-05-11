"""
Close Command — Review & Approval Gate tab (HITL).
Displays review cards per transaction and records human decisions to DB.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
import pandas as pd
from datetime import datetime


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


def render_review_tab(state: dict, db) -> None:
    """Render the Review & Approval Gate tab."""

    st.markdown("## Review & Approval Gate")
    st.warning("Nothing posts without named approval. All decisions are logged to the audit trail.")
    st.divider()

    if not state:
        st.info("No pipeline run data available. Start a new close run from the sidebar.")
        return

    batch_id = state.get("batch_id", "")
    period = state.get("period", "")
    review_result = state.get("review_result") or {}
    items_for_review = list(review_result.get("items_for_review") or [])
    close_readiness = review_result.get("close_readiness") or {}

    # ── Derive review items from matching result when review node hasn't run ─
    # interrupt_before=["review"] means the review agent hasn't executed yet.
    # Build review cards for ALL IC pairs — every pair requires human sign-off
    # regardless of match status (Matched, FX Diff, Not Matched, Exception).
    if not items_for_review:
        matching_result = state.get("matching_result") or {}
        matched_pairs   = matching_result.get("matched_pairs") or []
        fx_diff_pairs   = matching_result.get("fx_diff_pairs") or []
        not_matched     = matching_result.get("not_matched_pairs") or []
        exceptions      = matching_result.get("exception_pairs") or []

        def _pair_to_card(pair: dict, match_status: str, requires_override: bool = False) -> dict:
            return {
                "txn_id":                 str(pair.get("txn_id", "N/A")),
                "seller":                 str(pair.get("seller_entity", pair.get("seller", ""))),
                "buyer":                  str(pair.get("buyer_entity", pair.get("buyer", ""))),
                "seller_entity":          str(pair.get("seller_entity", "")),
                "buyer_entity":           str(pair.get("buyer_entity", "")),
                "match_status":           match_status,
                "gap_usd":                float(pair.get("gap_usd", 0)),
                "gap_pct":                float(pair.get("gap_pct", 0)),
                "seller_usd":             float(pair.get("seller_usd", 0)),
                "buyer_usd":              float(pair.get("buyer_usd", 0)),
                "seller_currency":        str(pair.get("seller_currency", "")),
                "buyer_currency":         str(pair.get("buyer_currency", "")),
                "rule_code":              str(pair.get("rule_code", "")),
                "root_cause":             str(pair.get("root_cause", "")),
                "journal_entries":        [],
                "rag_sources":            pair.get("rag_sources") or [],
                "requires_manual_override": requires_override,
            }

        for pair in matched_pairs:
            items_for_review.append(_pair_to_card(pair, "Matched"))
        for pair in fx_diff_pairs:
            items_for_review.append(_pair_to_card(pair, "FX Diff"))
        for pair in not_matched:
            items_for_review.append(_pair_to_card(pair, "Not Matched"))
        for pair in exceptions:
            items_for_review.append(_pair_to_card(pair, "Exception", requires_override=True))

    # ── Period Close Readiness ───────────────────────────────────────────
    st.subheader("Period Close Readiness")

    # Load decisions from DB — scoped to this batch_id only
    existing_decisions = {}
    if batch_id:
        try:
            decisions_list = db.get_review_decisions(batch_id)
            for dec in decisions_list:
                existing_decisions[dec["txn_id"]] = dec
        except Exception:
            pass

    total_items    = len(items_for_review)
    approved_count = sum(
        1 for item in items_for_review
        if existing_decisions.get(item.get("txn_id", ""), {}).get("decision") == "Approved"
    )
    pending_count  = total_items - sum(
        1 for item in items_for_review
        if item.get("txn_id", "") in existing_decisions
    )
    readiness_pct  = int((approved_count / total_items * 100)) if total_items > 0 else 0

    r1, r2, r3, r4 = st.columns(4)
    r1.metric("Total for Review", total_items)
    r2.metric("Approved", approved_count)
    r3.metric("Pending", pending_count)
    r4.metric("Readiness", f"{readiness_pct}%" if total_items > 0 else "N/A")
    st.progress(readiness_pct / 100)

    # Compute is_ready: all items approved (or no items)
    is_ready = (total_items == 0) or (readiness_pct == 100) or close_readiness.get("ready", False)
    if is_ready and total_items == 0:
        st.success(
            "✅ No IC pairs require review — all pairs are matched or have expected FX differences."
        )
        st.info(
            "The pipeline is waiting at the HITL gate. "
            "Click **Resume Pipeline** in the sidebar to proceed to journal output."
        )
    elif is_ready:
        st.success("✅ Period close is READY — all IC pairs have been reviewed and approved.")
        st.info("Click **Resume Pipeline** in the sidebar to proceed to journal output.")
    else:
        st.warning(f"{pending_count} item(s) still require review before period can close.")

    st.divider()

    # ── Bulk Approve ─────────────────────────────────────────────────────
    if items_for_review:
        col_b1, col_b2 = st.columns(2)
        bulk_matched = col_b1.button("✅ Bulk Approve All Matched")
        bulk_fx      = col_b2.button("💱 Bulk Approve All FX Diff")

        for bulk_flag, target_status in [(bulk_matched, "Matched"), (bulk_fx, "FX Diff")]:
          if bulk_flag:
            bulk_count = 0
            for item in items_for_review:
                match_status = item.get("match_status", "")
                if match_status == target_status:
                    decision_record = {
                        "txn_id": item.get("txn_id", ""),
                        "decision": "Approved",
                        "reviewer_name": "BULK_APPROVE",
                        "reviewer_role": "System",
                        "timestamp": datetime.utcnow().isoformat(),
                        "comment": "Bulk approved — clean match, no gap.",
                        "gate_status": "APPROVED",
                        "batch_id": batch_id,
                        "period": period,
                    }
                    try:
                        db.save_review_decision(decision_record)
                        bulk_count += 1
                    except Exception as exc:
                        st.error(f"Failed to save bulk decision for {item.get('txn_id', '')}: {exc}")
            if bulk_count > 0:
                st.success(f"Bulk approved {bulk_count} {target_status} transaction(s).")
                st.rerun()
            else:
                st.info(f"No '{target_status}' items found to bulk approve.")

    st.divider()

    # ── Review Cards ─────────────────────────────────────────────────────
    st.subheader("Review Items")

    if not items_for_review:
        st.info("No review items available for this batch.")
    else:
        for item in items_for_review:
            txn_id = item.get("txn_id", "N/A")
            seller = item.get("seller", item.get("seller_entity", ""))
            buyer = item.get("buyer", item.get("buyer_entity", ""))
            match_status = item.get("match_status", "")
            gap_usd = item.get("gap_usd", 0)
            gap_pct = item.get("gap_pct", 0)

            already_decided = existing_decisions.get(txn_id)
            decision_badge = f" [{already_decided['decision'].upper()}]" if already_decided else ""

            status_icon = {
                "Matched": "✅",
                "Not Matched": "⚠️",
                "FX Diff": "💱",
                "Exception": "🚨",
            }.get(match_status, "○")

            expander_label = (
                f"{status_icon} [{match_status}] {txn_id} — {seller} → {buyer}"
                f" | Gap: {_fmt_usd(gap_usd)} ({_fmt_pct(gap_pct)}){decision_badge}"
            )

            with st.expander(expander_label, expanded=(match_status in ("Exception", "Not Matched") and not already_decided)):

                ec1, ec2, ec3, ec4, ec5 = st.columns(5)
                ec1.markdown(f"**Status:** `{match_status}`")
                ec2.metric("Seller USD", _fmt_usd(item.get("seller_usd", 0)))
                ec3.metric("Buyer USD",  _fmt_usd(item.get("buyer_usd", 0)))
                ec4.metric("Gap USD",    _fmt_usd(gap_usd))
                ec5.metric("Gap %",      _fmt_pct(gap_pct))

                # Proposed journal entries
                journal_entries = item.get("journal_entries") or []
                if journal_entries:
                    st.markdown("**Proposed Journal Entries:**")
                    je_rows = []
                    for je in journal_entries:
                        je_rows.append({
                            "Dr/Cr": je.get("dr_cr", "").upper(),
                            "Account": je.get("account", ""),
                            "Amount USD": _fmt_usd(je.get("amount_usd", 0)),
                            "Rule Code": je.get("rule_code", ""),
                        })
                    st.dataframe(pd.DataFrame(je_rows), use_container_width=True, hide_index=True)

                # RAG Root Cause
                root_cause = item.get("root_cause", "")
                if root_cause:
                    st.markdown("**RAG Root Cause Analysis:**")
                    st.info(root_cause)

                # Validation Notes
                validation_notes = item.get("validation_notes", "")
                if validation_notes:
                    st.markdown("**Validation Notes:**")
                    st.warning(validation_notes)

                # Prior period comparison
                prior_period = item.get("prior_period_amount")
                if prior_period is not None:
                    st.markdown("**Prior Period Comparison:**")
                    ppc1, ppc2 = st.columns(2)
                    ppc1.metric("Current Period", _fmt_usd(gap_usd))
                    ppc2.metric("Prior Period", _fmt_usd(prior_period))

                st.divider()

                # Show existing decision if already recorded
                if already_decided:
                    dec_color = {
                        "Approve": "#28a745",
                        "Reject": "#dc3545",
                        "Escalate": "#ffc107",
                    }.get(already_decided["decision"], "#6c757d")
                    st.markdown(
                        f"**Decision already recorded:** "
                        f"<span style='background:{dec_color};color:white;padding:3px 8px;"
                        f"border-radius:8px'>{already_decided['decision']}</span> "
                        f"by {already_decided.get('reviewer_name', '')} "
                        f"({already_decided.get('reviewer_role', '')}) "
                        f"at {already_decided.get('timestamp', '')}",
                        unsafe_allow_html=True,
                    )
                    if already_decided.get("comment"):
                        st.caption(f"Comment: {already_decided['comment']}")
                else:
                    # Decision form
                    with st.form(key=f"review_form_{txn_id}"):
                        st.markdown("**Record Decision:**")
                        f1, f2 = st.columns(2)
                        reviewer_name = f1.text_input("Reviewer Name", key=f"rname_{txn_id}")
                        reviewer_role = f2.selectbox(
                            "Reviewer Role",
                            ["CFO", "Controller", "Senior Accountant", "IC Accountant", "Auditor"],
                            key=f"rrole_{txn_id}",
                        )
                        decision = st.radio(
                            "Decision",
                            ["Approved", "Rejected", "Escalated"],
                            horizontal=True,
                            key=f"rdec_{txn_id}",
                        )
                        comment = st.text_area("Comment", key=f"rcomment_{txn_id}")
                        submitted = st.form_submit_button("Record Decision")

                        if submitted:
                            if not reviewer_name.strip():
                                st.error("Reviewer name is required.")
                            else:
                                gate_status_map = {
                                    "Approved": "APPROVED",
                                    "Rejected": "REJECTED",
                                    "Escalated": "ESCALATED",
                                }
                                decision_record = {
                                    "txn_id": txn_id,
                                    "decision": decision,
                                    "reviewer_name": reviewer_name.strip(),
                                    "reviewer_role": reviewer_role,
                                    "timestamp": datetime.utcnow().isoformat(),
                                    "comment": comment.strip(),
                                    "gate_status": gate_status_map.get(decision, "PENDING"),
                                    "batch_id": batch_id,
                                    "period": period,
                                }
                                try:
                                    db.save_review_decision(decision_record)
                                    st.success(
                                        f"Decision recorded: {decision} by {reviewer_name} "
                                        f"({reviewer_role}) at {decision_record['timestamp']}"
                                    )
                                    st.rerun()
                                except Exception as exc:
                                    st.error(f"Failed to save decision: {exc}")

    st.divider()

    # ── Decision Log ─────────────────────────────────────────────────────
    st.subheader("Decision Log")

    try:
        all_decisions = db.get_review_decisions(batch_id)
        if all_decisions:
            log_rows = []
            for d in all_decisions:
                log_rows.append({
                    "TxnID": d.get("txn_id", ""),
                    "Decision": d.get("decision", ""),
                    "Reviewer": d.get("reviewer_name", ""),
                    "Role": d.get("reviewer_role", ""),
                    "Timestamp": d.get("timestamp", ""),
                    "Comment": d.get("comment", ""),
                })
            df_log = pd.DataFrame(log_rows)

            st.dataframe(df_log, use_container_width=True, hide_index=True)
        else:
            st.info("No decisions recorded for this batch yet.")
    except Exception as exc:
        st.error(f"Could not load decision log: {exc}")
