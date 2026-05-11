"""
Consolidated Financial Statements UI Tab for Close Command.
Always shows Pre-Elimination vs Post-Elimination side-by-side so the
finance team can see exactly what IC eliminations remove from gross totals.
"""

from __future__ import annotations

import logging
from typing import Optional

import pandas as pd
import streamlit as st

logger = logging.getLogger(__name__)

try:
    import plotly.graph_objects as go
    _PLOTLY = True
except ImportError:
    _PLOTLY = False

# PCon% per entity (1.0 = 100% consolidated, < 1.0 = NCI / partial)
_PCON = {
    "HCG-UK": 1.00, "HCG-DE": 1.00, "HCG-US": 1.00,
    "HCG-FR": 1.00, "HCG-AU": 1.00, "SHARED":  1.00,
    "HCG-SG": 0.75, "HCG-NL": 0.60, "HCG-JP":  0.40,
}


# ── Formatting helpers ────────────────────────────────────────────────────────

def _m(v: float) -> str:
    """Format as $X.XXM."""
    try:
        return f"${abs(float(v)) / 1e6:,.2f}M"
    except Exception:
        return "—"


def _m_signed(v: float) -> str:
    try:
        x = float(v) / 1e6
        return f"${x:,.2f}M" if x >= 0 else f"(${abs(x):,.2f}M)"
    except Exception:
        return "—"


def _pct(num: float, denom: float) -> str:
    try:
        return f"{num / denom * 100:.1f}%" if denom else "—"
    except Exception:
        return "—"


# ── Pre-elimination computation from entity_statements ───────────────────────

def _compute_pre_elim(entity_statements: dict) -> dict:
    """
    Aggregate all entity financial lines (with PCon%) to get gross group totals.
    Returns a flat dict of group P&L and BS figures.
    """
    rev = cogs = opex = 0.0
    assets = liabilities = equity = 0.0
    ic_rev = ic_cogs = ic_assets = ic_liab = 0.0

    for entity_code, stmt in entity_statements.items():
        pcon = _PCON.get(str(entity_code), 1.0)
        rev         += abs(float(stmt.get("total_revenue",     0) or 0)) * pcon
        cogs        += abs(float(stmt.get("total_cogs",        0) or 0)) * pcon
        opex        += abs(float(stmt.get("total_opex",        0) or 0)) * pcon
        assets      += abs(float(stmt.get("total_assets",      0) or 0)) * pcon
        liabilities += abs(float(stmt.get("total_liabilities", 0) or 0)) * pcon
        equity      += abs(float(stmt.get("total_equity",      0) or 0)) * pcon
        ic_rev      += abs(float(stmt.get("ic_revenue",        0) or 0)) * pcon
        ic_cogs     += abs(float(stmt.get("ic_costs",          0) or 0)) * pcon
        ic_assets   += abs(float(stmt.get("ic_receivables",    0) or 0)) * pcon
        ic_liab     += abs(float(stmt.get("ic_payables",       0) or 0)) * pcon

    gross_profit = rev - cogs
    ebit = gross_profit - opex

    return {
        "gross_revenue":    rev,
        "gross_cogs":       cogs,
        "gross_profit":     gross_profit,
        "gross_opex":       opex,
        "ebit":             ebit,
        "gross_assets":     assets,
        "gross_liabilities":liabilities,
        "gross_equity":     equity,
        "ic_revenue":       ic_rev,
        "ic_cogs":          ic_cogs,
        "ic_assets":        ic_assets,
        "ic_liabilities":   ic_liab,
    }


def _compute_entity_pre_elim(entity_statements: dict) -> list[dict]:
    """Per-entity breakdown for the Entity Contributions tab."""
    rows = []
    for entity_code in sorted(entity_statements.keys()):
        stmt = entity_statements[entity_code]
        pcon = _PCON.get(str(entity_code), 1.0)
        rev  = abs(float(stmt.get("total_revenue", 0) or 0)) * pcon
        cogs = abs(float(stmt.get("total_cogs",    0) or 0)) * pcon
        opex = abs(float(stmt.get("total_opex",    0) or 0)) * pcon
        ast  = abs(float(stmt.get("total_assets",  0) or 0)) * pcon
        lib  = abs(float(stmt.get("total_liabilities", 0) or 0)) * pcon
        rows.append({
            "Entity":         entity_code,
            "PCon %":         f"{pcon*100:.0f}%",
            "Revenue $M":     f"{rev/1e6:,.2f}",
            "COGS $M":        f"{cogs/1e6:,.2f}",
            "OpEx $M":        f"{opex/1e6:,.2f}",
            "EBIT $M":        f"{(rev-cogs-opex)/1e6:,.2f}",
            "Assets $M":      f"{ast/1e6:,.2f}",
            "Liabilities $M": f"{lib/1e6:,.2f}",
        })
    return rows


# ── Main tab renderer ─────────────────────────────────────────────────────────

def render_consolidation_tab(state: Optional[dict]) -> None:
    """
    Render the Consolidated Financial Statements tab.
    Always shows Pre vs Post elimination comparison.
    """
    st.markdown("## Consolidated Financial Statements — Helios Chemicals Group")
    st.divider()

    if state is None:
        st.info("Run the full pipeline to see consolidated statements.")
        return

    period   = state.get("period",   "—")
    scenario = state.get("scenario", "—")
    batch_id = state.get("batch_id", "—")

    ingestion_result     = state.get("ingestion_result")     or {}
    consolidation_result = state.get("consolidation_result")
    elimination_result   = state.get("elimination_result")   or {}
    entity_statements    = ingestion_result.get("entity_statements") or {}

    if not entity_statements:
        st.info("No entity financial data yet. Upload a file and run the pipeline.")
        return

    # ── Header row ────────────────────────────────────────────────────────────
    h1, h2, h3, h4 = st.columns(4)
    h1.metric("Period",   period)
    h2.metric("Scenario", scenario)
    h3.metric("Batch ID", batch_id)
    pipeline_done = consolidation_result is not None
    h4.metric("Status", "✅ Complete" if pipeline_done else "⏳ Awaiting Resume")

    if not pipeline_done:
        st.info(
            "Pipeline is paused at the HITL review gate. "
            "Pre-elimination totals are shown now. "
            "Click **Resume Pipeline** in the sidebar to apply IC eliminations and complete consolidation."
        )

    st.divider()

    # ── Compute pre-elim from entity statements (always available) ────────────
    pre = _compute_pre_elim(entity_statements)

    # ── Extract post-elim from consolidation_result (available after Resume) ──
    cr = consolidation_result or {}

    def _post(key: str, fallback: float = 0.0) -> float:
        return abs(float(cr.get(key, fallback) or fallback))

    post_rev       = _post("net_revenue")
    post_cogs      = _post("net_cogs")
    post_gross_pft = post_rev - post_cogs
    post_opex      = _post("net_opex")
    post_ebit      = _post("ebit")
    post_nci       = _post("nci_share")
    post_profit    = _post("group_profit")
    post_assets    = _post("net_assets")
    post_liab      = _post("net_liabilities")
    post_equity    = _post("net_equity")

    ic_rev_elim    = _post("ic_revenue_eliminated",  pre["ic_revenue"])
    ic_cogs_elim   = _post("ic_cogs_eliminated",     pre["ic_cogs"])
    ic_assets_elim = _post("ic_assets_eliminated",   pre["ic_assets"])
    ic_liab_elim   = _post("ic_liabilities_eliminated", pre["ic_liabilities"])

    # ── Sub-tabs ──────────────────────────────────────────────────────────────
    tab_pl, tab_bs, tab_entity, tab_elim = st.tabs([
        "📊 Consolidated P&L",
        "🏦 Balance Sheet",
        "🏢 Entity Contributions",
        "✂️ Elimination Impact",
    ])

    # ══════════════════════════════════════════════════════════════════════════
    # Tab 1 — Consolidated P&L
    # ══════════════════════════════════════════════════════════════════════════
    with tab_pl:
        st.markdown("### Consolidated Profit & Loss")
        st.caption("All amounts in USD millions · IC eliminations in parentheses")

        # ── KPI summary row ───────────────────────────────────────────────────
        k1, k2, k3, k4, k5 = st.columns(5)
        k1.metric(
            "Gross Revenue",
            _m(pre["gross_revenue"]),
            help="Sum of all entity revenues before IC elimination",
        )
        k2.metric(
            "IC Eliminated",
            f"({_m(ic_rev_elim)})" if ic_rev_elim else "Pending",
            help="IC intercompany revenue eliminated on consolidation",
        )
        k3.metric(
            "Net Revenue",
            _m(post_rev) if pipeline_done else "Pending",
            delta=f"-{_m(ic_rev_elim)}" if pipeline_done and ic_rev_elim else None,
            delta_color="inverse",
        )
        k4.metric(
            "EBIT",
            _m(post_ebit) if pipeline_done else f"~{_m(pre['ebit'])} (pre-elim)",
        )
        k5.metric(
            "Group Profit",
            _m(post_profit) if pipeline_done else "Pending",
        )

        st.divider()

        # ── Bridge table ──────────────────────────────────────────────────────
        pl_rows = [
            {
                "Line Item":              "Revenue",
                "Gross (Pre-Elim) $M":    f"{pre['gross_revenue']/1e6:,.2f}",
                "IC Eliminated $M":       f"({ic_rev_elim/1e6:,.2f})" if ic_rev_elim else "—",
                "Net (Consolidated) $M":  f"{post_rev/1e6:,.2f}" if pipeline_done else "—",
            },
            {
                "Line Item":              "Cost of Sales",
                "Gross (Pre-Elim) $M":    f"({pre['gross_cogs']/1e6:,.2f})",
                "IC Eliminated $M":       f"({ic_cogs_elim/1e6:,.2f})" if ic_cogs_elim else "—",
                "Net (Consolidated) $M":  f"({post_cogs/1e6:,.2f})" if pipeline_done else "—",
            },
            {
                "Line Item":              "Gross Profit",
                "Gross (Pre-Elim) $M":    f"{pre['gross_profit']/1e6:,.2f}",
                "IC Eliminated $M":       "—",
                "Net (Consolidated) $M":  f"{post_gross_pft/1e6:,.2f}" if pipeline_done else "—",
            },
            {
                "Line Item":              "Operating Expenses",
                "Gross (Pre-Elim) $M":    f"({pre['gross_opex']/1e6:,.2f})",
                "IC Eliminated $M":       "—",
                "Net (Consolidated) $M":  f"({post_opex/1e6:,.2f})" if pipeline_done else "—",
            },
            {
                "Line Item":              "EBIT",
                "Gross (Pre-Elim) $M":    f"{pre['ebit']/1e6:,.2f}",
                "IC Eliminated $M":       "—",
                "Net (Consolidated) $M":  f"{post_ebit/1e6:,.2f}" if pipeline_done else "—",
            },
            {
                "Line Item":              "NCI Adjustment",
                "Gross (Pre-Elim) $M":    "—",
                "IC Eliminated $M":       f"({post_nci/1e6:,.2f})" if pipeline_done and post_nci else "—",
                "Net (Consolidated) $M":  f"({post_nci/1e6:,.2f})" if pipeline_done and post_nci else "—",
            },
            {
                "Line Item":              "Group Profit",
                "Gross (Pre-Elim) $M":    "—",
                "IC Eliminated $M":       "—",
                "Net (Consolidated) $M":  f"{post_profit/1e6:,.2f}" if pipeline_done else "Pending",
            },
        ]

        pl_df = pd.DataFrame(pl_rows)
        st.dataframe(pl_df, use_container_width=True, hide_index=True)

        # ── Waterfall chart ───────────────────────────────────────────────────
        if _PLOTLY:
            st.divider()
            st.markdown("#### P&L Bridge — Gross to Net")

            if pipeline_done:
                labels   = ["Gross Revenue", "IC Eliminated", "Net Revenue",
                            "Cost of Sales", "Gross Profit", "OpEx", "EBIT",
                            "NCI", "Group Profit"]
                values   = [pre["gross_revenue"]/1e6, -ic_rev_elim/1e6, 0,
                            -post_cogs/1e6, 0, -post_opex/1e6, 0, -post_nci/1e6, 0]
                measures = ["absolute", "relative", "total",
                            "relative", "total", "relative", "total",
                            "relative", "total"]
            else:
                labels   = ["Gross Revenue", "Cost of Sales", "Gross Profit",
                            "OpEx", "EBIT"]
                values   = [pre["gross_revenue"]/1e6, -pre["gross_cogs"]/1e6, 0,
                            -pre["gross_opex"]/1e6, 0]
                measures = ["absolute", "relative", "total", "relative", "total"]

            fig = go.Figure(go.Waterfall(
                orientation="v",
                measure=measures,
                x=labels,
                y=values,
                connector={"line": {"color": "#555"}},
                decreasing={"marker": {"color": "#EF5350"}},
                increasing={"marker": {"color": "#26A69A"}},
                totals={"marker": {"color": "#42A5F5"}},
                texttemplate="%{y:,.1f}M",
                textposition="outside",
            ))
            fig.update_layout(
                title=f"P&L Bridge ({'Post-Elimination' if pipeline_done else 'Pre-Elimination'}) — USD Millions",
                yaxis_title="USD Millions",
                showlegend=False,
                height=430,
                margin=dict(t=40, b=20),
            )
            st.plotly_chart(fig, use_container_width=True)

        # ── Margin metrics (only when complete) ──────────────────────────────
        if pipeline_done and post_rev > 0:
            st.divider()
            mg1, mg2, mg3 = st.columns(3)
            mg1.metric("Gross Margin", _pct(post_gross_pft, post_rev))
            mg2.metric("EBIT Margin",  _pct(post_ebit, post_rev))
            mg3.metric("Net Margin",   _pct(post_profit, post_rev))

    # ══════════════════════════════════════════════════════════════════════════
    # Tab 2 — Balance Sheet
    # ══════════════════════════════════════════════════════════════════════════
    with tab_bs:
        st.markdown("### Consolidated Balance Sheet")
        st.caption("All amounts in USD millions")

        # KPI summary
        b1, b2, b3 = st.columns(3)
        b1.metric("Gross Assets",     _m(pre["gross_assets"]))
        b2.metric("IC Eliminated",    f"({_m(ic_assets_elim)})" if ic_assets_elim else "Pending")
        b3.metric("Net Assets",       _m(post_assets) if pipeline_done else "Pending")

        st.divider()

        bs_rows = [
            {
                "Item":                   "Assets",
                "Gross (Pre-Elim) $M":    f"{pre['gross_assets']/1e6:,.2f}",
                "IC Eliminated $M":       f"({ic_assets_elim/1e6:,.2f})" if ic_assets_elim else "—",
                "Net (Consolidated) $M":  f"{post_assets/1e6:,.2f}" if pipeline_done else "—",
            },
            {
                "Item":                   "Liabilities",
                "Gross (Pre-Elim) $M":    f"({pre['gross_liabilities']/1e6:,.2f})",
                "IC Eliminated $M":       f"({ic_liab_elim/1e6:,.2f})" if ic_liab_elim else "—",
                "Net (Consolidated) $M":  f"({post_liab/1e6:,.2f})" if pipeline_done else "—",
            },
            {
                "Item":                   "Equity",
                "Gross (Pre-Elim) $M":    f"{pre['gross_equity']/1e6:,.2f}",
                "IC Eliminated $M":       "—",
                "Net (Consolidated) $M":  f"{post_equity/1e6:,.2f}" if pipeline_done else "—",
            },
            {
                "Item":                   "Net Assets = L + E",
                "Gross (Pre-Elim) $M":    f"{(pre['gross_assets'] - pre['gross_liabilities'])/1e6:,.2f}",
                "IC Eliminated $M":       "—",
                "Net (Consolidated) $M":  f"{post_assets/1e6:,.2f}" if pipeline_done else "—",
            },
        ]

        bs_df = pd.DataFrame(bs_rows)
        st.dataframe(bs_df, use_container_width=True, hide_index=True)

        # Balance check
        if pipeline_done:
            bs_balanced = cr.get("balance_sheet_balanced", False)
            total_le = post_liab + post_equity
            if bs_balanced:
                st.success(
                    f"✅ Balance Sheet Balanced — Net Assets ${post_assets/1e6:,.2f}M "
                    f"= Total L&E ${total_le/1e6:,.2f}M"
                )
            else:
                diff = abs(post_assets - total_le)
                st.error(
                    f"⚠️ Out of Balance — Net Assets ${post_assets/1e6:,.2f}M, "
                    f"Total L&E ${total_le/1e6:,.2f}M, Diff ${diff/1e6:,.2f}M"
                )

        # Stacked bar chart by entity
        if _PLOTLY:
            st.divider()
            entity_rows_pre = _compute_entity_pre_elim(entity_statements)
            if entity_rows_pre:
                ents  = [r["Entity"] for r in entity_rows_pre]
                ast_v = [float(r["Assets $M"].replace(",","")) for r in entity_rows_pre]
                lib_v = [float(r["Liabilities $M"].replace(",","")) for r in entity_rows_pre]
                eq_v  = [a - l for a, l in zip(ast_v, lib_v)]

                fig_bs = go.Figure(data=[
                    go.Bar(name="Assets",      x=ents, y=ast_v, marker_color="#42A5F5"),
                    go.Bar(name="Liabilities", x=ents, y=lib_v, marker_color="#EF5350"),
                    go.Bar(name="Equity",      x=ents, y=eq_v,  marker_color="#66BB6A"),
                ])
                fig_bs.update_layout(
                    barmode="group",
                    title="Entity Assets / Liabilities / Equity (Pre-Elimination, USD Millions)",
                    yaxis_title="USD Millions", height=380,
                    margin=dict(t=40, b=20),
                )
                st.plotly_chart(fig_bs, use_container_width=True)

    # ══════════════════════════════════════════════════════════════════════════
    # Tab 3 — Entity Contributions
    # ══════════════════════════════════════════════════════════════════════════
    with tab_entity:
        st.markdown("### Entity Contributions to Group")
        st.caption("Amounts after applying PCon% · USD millions")

        entity_rows_pre = _compute_entity_pre_elim(entity_statements)
        if entity_rows_pre:
            st.dataframe(
                pd.DataFrame(entity_rows_pre),
                use_container_width=True, hide_index=True,
            )

        # Post-elim entity contributions from consolidation_result
        post_entity = cr.get("entity_contributions") or {}
        if pipeline_done and post_entity:
            st.divider()
            st.markdown("**Post-Elimination Entity Contributions**")
            post_rows = []
            for entity_code in sorted(post_entity.keys()):
                ec = post_entity[entity_code]
                post_rows.append({
                    "Entity":      entity_code,
                    "Revenue $M":  f"{abs(float(ec.get('revenue',      0) or 0))/1e6:,.2f}",
                    "COGS $M":     f"{abs(float(ec.get('cogs',         0) or 0))/1e6:,.2f}",
                    "Assets $M":   f"{abs(float(ec.get('assets',       0) or 0))/1e6:,.2f}",
                    "Liab $M":     f"{abs(float(ec.get('liabilities',  0) or 0))/1e6:,.2f}",
                    "PCon %":      f"{float(ec.get('pcon_pct', ec.get('pcon', 1.0)) or 1.0):.0f}%",
                })
            if post_rows:
                st.dataframe(pd.DataFrame(post_rows), use_container_width=True, hide_index=True)

        # Revenue contribution donut
        if _PLOTLY and entity_rows_pre:
            st.divider()
            ents    = [r["Entity"] for r in entity_rows_pre]
            rev_v   = [float(r["Revenue $M"].replace(",","")) for r in entity_rows_pre]
            ebit_v  = [float(r["EBIT $M"].replace(",",""))    for r in entity_rows_pre]

            col_ch1, col_ch2 = st.columns(2)
            with col_ch1:
                fig_pie = go.Figure(go.Pie(
                    labels=ents, values=rev_v, hole=0.5,
                    textinfo="label+percent", hoverinfo="label+value",
                ))
                fig_pie.update_layout(
                    title="Revenue Mix by Entity (Pre-Elim)",
                    height=340, margin=dict(t=40, b=10),
                    showlegend=True,
                )
                st.plotly_chart(fig_pie, use_container_width=True)

            with col_ch2:
                fig_bar = go.Figure(data=[
                    go.Bar(name="Revenue $M", x=ents, y=rev_v,  marker_color="#26A69A"),
                    go.Bar(name="EBIT $M",    x=ents, y=ebit_v, marker_color="#42A5F5"),
                ])
                fig_bar.update_layout(
                    barmode="group",
                    title="Revenue vs EBIT by Entity",
                    height=340, margin=dict(t=40, b=10),
                )
                st.plotly_chart(fig_bar, use_container_width=True)

    # ══════════════════════════════════════════════════════════════════════════
    # Tab 4 — Elimination Impact
    # ══════════════════════════════════════════════════════════════════════════
    with tab_elim:
        st.markdown("### IC Elimination Impact")
        st.caption(
            "Shows what is removed from gross group totals to avoid double-counting "
            "intercompany transactions."
        )

        # Always show estimated pre-elim IC amounts
        e1, e2, e3, e4 = st.columns(4)
        e1.metric("IC Revenue (estimated)",       _m(pre["ic_revenue"]),      help="IC revenue lines in entity statements")
        e2.metric("IC Costs (estimated)",         _m(pre["ic_cogs"]),         help="IC COGS lines in entity statements")
        e3.metric("IC Receivables (estimated)",   _m(pre["ic_assets"]),       help="IC balance sheet asset lines")
        e4.metric("IC Payables (estimated)",      _m(pre["ic_liabilities"]),  help="IC balance sheet liability lines")

        st.divider()

        # Post-elim elimination actuals from consolidation_result
        elim_summary = cr.get("elimination_summary") or {}
        if pipeline_done and elim_summary:
            st.markdown("**Actual Eliminations Applied (Post-Pipeline)**")
            f1, f2, f3, f4, f5 = st.columns(5)
            ic_r  = abs(float(elim_summary.get("ic_revenue_eliminated",      0) or 0))
            ic_c  = abs(float(elim_summary.get("ic_cogs_eliminated",         0) or 0))
            ic_a  = abs(float(elim_summary.get("ic_assets_eliminated",       0) or 0))
            ic_l  = abs(float(elim_summary.get("ic_liabilities_eliminated",  0) or 0))
            ic_t  = abs(float(elim_summary.get("total_elimination_impact",   0) or 0))
            f1.metric("Revenue Eliminated",  _m(ic_r))
            f2.metric("Costs Eliminated",    _m(ic_c))
            f3.metric("Assets Eliminated",   _m(ic_a))
            f4.metric("Liabilities Eliminated", _m(ic_l))
            f5.metric("Total Impact",        _m(ic_t))

        # Show elimination journal entries count from elimination_result
        journal_entries = elimination_result.get("journal_entries") or []
        if journal_entries:
            st.divider()
            st.markdown(f"**{len(journal_entries)} elimination journal entries** were generated by the Elimination Engine.")
            # Summarise by rule_code
            from collections import Counter
            rule_counts = Counter(str(e.get("rule_code","—")) for e in journal_entries)
            rule_rows = [{"Rule Code": rc, "Entries": cnt} for rc, cnt in sorted(rule_counts.items())]
            st.dataframe(pd.DataFrame(rule_rows), use_container_width=True, hide_index=True)

        # Side-by-side bar: Gross vs Net
        if _PLOTLY:
            st.divider()
            categories = ["Revenue", "Cost of Sales", "Assets", "Liabilities"]
            gross_vals = [
                pre["gross_revenue"]/1e6,
                pre["gross_cogs"]/1e6,
                pre["gross_assets"]/1e6,
                pre["gross_liabilities"]/1e6,
            ]
            if pipeline_done:
                net_vals = [
                    post_rev/1e6,
                    post_cogs/1e6,
                    post_assets/1e6,
                    post_liab/1e6,
                ]
                elim_vals = [g - n for g, n in zip(gross_vals, net_vals)]
            else:
                net_vals  = [None] * 4
                elim_vals = [
                    pre["ic_revenue"]/1e6,
                    pre["ic_cogs"]/1e6,
                    pre["ic_assets"]/1e6,
                    pre["ic_liabilities"]/1e6,
                ]

            fig_impact = go.Figure(data=[
                go.Bar(name="Gross (Pre-Elim)", x=categories, y=gross_vals, marker_color="#42A5F5"),
                go.Bar(name="IC Eliminated",    x=categories, y=elim_vals,  marker_color="#EF5350"),
            ])
            if pipeline_done and any(v is not None for v in net_vals):
                fig_impact.add_trace(
                    go.Bar(name="Net (Post-Elim)", x=categories, y=net_vals, marker_color="#26A69A")
                )
            fig_impact.update_layout(
                barmode="group",
                title="Pre vs Post Elimination Impact (USD Millions)",
                yaxis_title="USD Millions", height=400,
                margin=dict(t=40, b=20),
            )
            st.plotly_chart(fig_impact, use_container_width=True)
