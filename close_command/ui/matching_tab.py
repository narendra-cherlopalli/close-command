"""
Close Command — IC Matching Engine tab.
Shows matched, not-matched, FX diff and exception sub-tabs with RAG root cause analysis.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
import pandas as pd


def _fmt_usd(val) -> str:
    try:
        return f"${float(val):,.2f}"
    except Exception:
        return str(val)


def _fmt_pct(val) -> str:
    try:
        return f"{float(val):.2f}%"
    except Exception:
        return str(val)


def _build_pair_df(pairs: list[dict]) -> pd.DataFrame:
    """Convert a list of pair dicts to a display DataFrame."""
    rows = []
    for p in pairs:
        rows.append({
            "TxnID": p.get("txn_id", ""),
            "Seller": p.get("seller_entity", p.get("seller", "")),
            "Buyer": p.get("buyer_entity", p.get("buyer", "")),
            "Rule Code": p.get("rule_code", ""),
            "Seller USD": _fmt_usd(p.get("seller_usd", 0)),
            "Buyer USD": _fmt_usd(p.get("buyer_usd", 0)),
            "Gap USD": _fmt_usd(p.get("gap_usd", 0)),
            "Gap %": _fmt_pct(p.get("gap_pct", 0)),
        })
    return pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=["TxnID", "Seller", "Buyer", "Rule Code", "Seller USD", "Buyer USD", "Gap USD", "Gap %"]
    )


def render_matching_tab(state: dict) -> None:
    """Render the IC Matching Engine tab."""

    st.markdown("## IC Matching Engine")
    st.divider()

    if not state:
        st.info("No pipeline run data available. Start a new close run from the sidebar.")
        return

    matching_result = state.get("matching_result") or {}

    matched_pairs = matching_result.get("matched_pairs") or []
    not_matched = matching_result.get("not_matched_pairs") or []
    fx_diff = matching_result.get("fx_diff_pairs") or []
    exceptions = matching_result.get("exception_pairs") or []

    total = len(matched_pairs) + len(not_matched) + len(fx_diff) + len(exceptions)
    match_rate = (len(matched_pairs) / total * 100) if total > 0 else 0.0

    # ── Summary metrics ─────────────────────────────────────────────────
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Pairs", total)
    c2.metric("Match Rate", f"{match_rate:.1f}%")
    c3.metric("Exceptions", len(exceptions))
    c4.metric("FX Differences", len(fx_diff))

    st.divider()

    # ── Sub-tabs ─────────────────────────────────────────────────────────
    tab_matched, tab_notmatched, tab_fx, tab_exception = st.tabs([
        f"Matched ({len(matched_pairs)})",
        f"Not Matched ({len(not_matched)})",
        f"FX Diff ({len(fx_diff)})",
        f"Exception ({len(exceptions)})",
    ])

    # ── Matched ──────────────────────────────────────────────────────────
    with tab_matched:
        st.markdown("### Matched Transactions")
        if matched_pairs:
            df = _build_pair_df(matched_pairs)
            st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.info("No matched transactions in this run.")

    # ── Not Matched ──────────────────────────────────────────────────────
    with tab_notmatched:
        st.markdown("### Not Matched Transactions")
        if not_matched:
            for pair in not_matched:
                txn_id = pair.get("txn_id", "N/A")
                seller = pair.get("seller_entity", pair.get("seller", ""))
                buyer = pair.get("buyer_entity", pair.get("buyer", ""))
                gap_usd = pair.get("gap_usd", 0)
                gap_pct = pair.get("gap_pct", 0)
                rule_code = pair.get("rule_code", "")
                root_cause = pair.get("root_cause", "No root cause available.")
                rag_sources = pair.get("rag_sources") or []

                row_label = f"[{rule_code}] {txn_id} — {seller} → {buyer} | Gap: {_fmt_usd(gap_usd)} ({_fmt_pct(gap_pct)})"
                with st.expander(row_label):
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("Seller USD", _fmt_usd(pair.get("seller_usd", 0)))
                    c2.metric("Buyer USD", _fmt_usd(pair.get("buyer_usd", 0)))
                    c3.metric("Gap USD", _fmt_usd(gap_usd))
                    c4.metric("Gap %", _fmt_pct(gap_pct))

                    st.markdown("**Root Cause Analysis:**")
                    st.info(root_cause)

                    if rag_sources:
                        st.markdown("**Historical Similar Exceptions:**")
                        for src in rag_sources:
                            if isinstance(src, dict):
                                st.markdown(
                                    f"- **{src.get('id', '')}** "
                                    f"(similarity: {src.get('similarity', 0):.2f}) — "
                                    f"{src.get('document', '')}"
                                )
                            else:
                                st.markdown(f"- {src}")

                    resolution = pair.get("resolution", "")
                    if resolution:
                        st.markdown("**Suggested Resolution:**")
                        st.success(resolution)

            # Summary table below
            st.divider()
            st.markdown("**Summary Table:**")
            df_nm = _build_pair_df(not_matched)
            df_nm["RAG Root Cause"] = [p.get("root_cause", "")[:80] + "..." if len(p.get("root_cause", "")) > 80 else p.get("root_cause", "") for p in not_matched]
            st.dataframe(df_nm, use_container_width=True, hide_index=True)
        else:
            st.success("All transactions matched — no outstanding differences.")

    # ── FX Diff ───────────────────────────────────────────────────────────
    with tab_fx:
        st.markdown("### FX Translation Differences")
        st.info(
            "Cross-currency pairs — FX translation differences are expected and "
            "not classified as exceptions. These are posted as FX elimination entries."
        )
        if fx_diff:
            rows = []
            for p in fx_diff:
                rows.append({
                    "TxnID": p.get("txn_id", ""),
                    "Seller": p.get("seller_entity", p.get("seller", "")),
                    "Buyer": p.get("buyer_entity", p.get("buyer", "")),
                    "Seller CCY": p.get("seller_currency", ""),
                    "Buyer CCY": p.get("buyer_currency", ""),
                    "Seller Amount": _fmt_usd(p.get("seller_amount", 0)),
                    "Buyer Amount": _fmt_usd(p.get("buyer_amount", 0)),
                    "Seller USD": _fmt_usd(p.get("seller_usd", 0)),
                    "Buyer USD": _fmt_usd(p.get("buyer_usd", 0)),
                    "FX Gap USD": _fmt_usd(p.get("gap_usd", 0)),
                })
            df_fx = pd.DataFrame(rows)
            st.dataframe(df_fx, use_container_width=True, hide_index=True)
        else:
            st.info("No FX differences in this run.")

    # ── Exception ─────────────────────────────────────────────────────────
    with tab_exception:
        st.markdown("### Exception Transactions")
        st.error(
            "Exception transactions are hard-blocked. "
            "They cannot be eliminated without human review and resolution."
        )
        if exceptions:
            for pair in exceptions:
                txn_id = pair.get("txn_id", "N/A")
                seller = pair.get("seller_entity", pair.get("seller", ""))
                buyer = pair.get("buyer_entity", pair.get("buyer", ""))
                gap_usd = pair.get("gap_usd", 0)
                gap_pct = pair.get("gap_pct", 0)
                rule_code = pair.get("rule_code", "")
                root_cause = pair.get("root_cause", "No root cause available.")
                rag_sources = pair.get("rag_sources") or []

                row_label = f"[{rule_code}] {txn_id} — {seller} → {buyer} | Gap: {_fmt_usd(gap_usd)} ({_fmt_pct(gap_pct)})"
                with st.expander(row_label):
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("Seller USD", _fmt_usd(pair.get("seller_usd", 0)))
                    c2.metric("Buyer USD", _fmt_usd(pair.get("buyer_usd", 0)))
                    c3.metric("Gap USD", _fmt_usd(gap_usd))
                    c4.metric("Gap %", _fmt_pct(gap_pct))

                    st.markdown("**Root Cause Analysis:**")
                    st.error(root_cause)

                    if rag_sources:
                        st.markdown("**Historical Similar Exceptions:**")
                        for src in rag_sources:
                            if isinstance(src, dict):
                                st.markdown(
                                    f"- **{src.get('id', '')}** "
                                    f"(similarity: {src.get('similarity', 0):.2f}) — "
                                    f"{src.get('document', '')}"
                                )
                            else:
                                st.markdown(f"- {src}")

                    resolution = pair.get("resolution", "")
                    if resolution:
                        st.markdown("**Suggested Resolution:**")
                        st.warning(resolution)

            # Summary table
            st.divider()
            st.markdown("**Exception Summary Table:**")
            exc_rows = []
            for p in exceptions:
                exc_rows.append({
                    "TxnID": p.get("txn_id", ""),
                    "Seller": p.get("seller_entity", p.get("seller", "")),
                    "Buyer": p.get("buyer_entity", p.get("buyer", "")),
                    "Rule Code": p.get("rule_code", ""),
                    "Gap USD": _fmt_usd(p.get("gap_usd", 0)),
                    "Gap %": _fmt_pct(p.get("gap_pct", 0)),
                    "Root Cause": (p.get("root_cause", "")[:80] + "...") if len(p.get("root_cause", "")) > 80 else p.get("root_cause", ""),
                })
            df_exc = pd.DataFrame(exc_rows)
            st.dataframe(df_exc, use_container_width=True, hide_index=True)
        else:
            st.success("No exceptions in this run.")
