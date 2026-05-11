"""
Close Command — RAG Knowledge Base tab.
Displays and manages the four ChromaDB vector collections.
"""

from __future__ import annotations

import sys
import os
import math

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
from datetime import datetime

try:
    import plotly.graph_objects as go
    import plotly.express as px
    _PLOTLY = True
except ImportError:
    _PLOTLY = False


# ── Entity layout positions (fixed coords for the HCG network) ───────────────
_ENTITY_POS = {
    "HCG":        (0.0,  0.0),
    "HCG-UK":     (-2.5,  1.5),
    "HCG-DE":     (-1.0,  2.5),
    "HCG-FR":     ( 0.5,  2.8),
    "HCG-US":     ( 2.5,  1.5),
    "HCG-AU":     ( 3.0, -0.5),
    "HCG-SG":     ( 1.5, -2.5),
    "HCG-JP":     (-1.0, -2.8),
    "HCG-NL":     (-3.0, -0.5),
    "HCG-SHARED": ( 0.0,  1.8),
}

_ENTITY_PCON = {
    "HCG": 100, "HCG-UK": 100, "HCG-DE": 100, "HCG-FR": 100,
    "HCG-US": 100, "HCG-AU": 100, "HCG-SHARED": 100,
    "HCG-SG": 75, "HCG-NL": 60, "HCG-JP": 40,
}

_RULE_COLORS = {
    "IC-001": "#1f77b4",   # blue   - intercompany sales
    "IC-002": "#2ca02c",   # green  - intercompany services
    "IC-003": "#ff7f0e",   # orange - intercompany loans
    "IC-004": "#9467bd",   # purple - royalties
    "IC-005": "#e377c2",   # pink   - management fees
    "IC-006": "#8c564b",   # brown  - interest
    "EQ-001": "#d62728",   # red    - equity eliminations
    "FX-001": "#bcbd22",   # yellow - FX
    "OTHER":  "#7f7f7f",   # grey
}


def _rule_color(rule_code: str) -> str:
    return _RULE_COLORS.get(rule_code, _RULE_COLORS["OTHER"])


def _build_ic_network_graph(precedents: list[dict], exceptions: list[dict]) -> "go.Figure | None":
    """Build a Plotly network graph of IC relationships from seeded RAG data."""
    if not _PLOTLY:
        return None

    # ── Count edges by (seller, buyer, rule_code) ────────────────────────────
    edge_map: dict[tuple, dict] = {}
    for p in precedents:
        meta = p.get("metadata", {})
        seller = meta.get("seller", "")
        buyer  = meta.get("buyer", "")
        rule   = meta.get("rule_code", "OTHER")
        key    = (seller, buyer, rule)
        if seller and buyer:
            if key not in edge_map:
                edge_map[key] = {"amount_usd": 0.0, "count": 0, "periods": set()}
            edge_map[key]["amount_usd"] += float(meta.get("amount_usd", 0))
            edge_map[key]["count"]      += 1
            edge_map[key]["periods"].add(meta.get("period", ""))

    # ── Exception overlay: which pairs had exceptions ─────────────────────────
    exc_pairs: set[tuple] = set()
    exc_gap: dict[tuple, float] = {}
    for e in exceptions:
        meta = e.get("metadata", {})
        s = meta.get("seller_entity", "")
        b = meta.get("buyer_entity", "")
        if s and b:
            exc_pairs.add((s, b))
            g = float(meta.get("gap_pct", 0))
            k = (s, b)
            exc_gap[k] = max(exc_gap.get(k, 0), g)

    # ── Collect all entities that appear in edges ─────────────────────────────
    active = set()
    for (s, b, _) in edge_map:
        active.add(s)
        active.add(b)
    for (s, b) in exc_pairs:
        active.add(s)
        active.add(b)

    # Always show all entities with known positions
    active = active | set(_ENTITY_POS.keys())

    # ── Build node traces ─────────────────────────────────────────────────────
    node_x, node_y, node_text, node_color, node_size, node_hover = [], [], [], [], [], []
    for entity in sorted(active):
        if entity not in _ENTITY_POS:
            continue
        x, y = _ENTITY_POS[entity]
        pcon  = _ENTITY_PCON.get(entity, 100)
        node_x.append(x)
        node_y.append(y)
        node_text.append(entity)
        node_size.append(28 if entity == "HCG" else 22)
        if pcon == 100:
            node_color.append("#1f77b4")
        elif pcon >= 70:
            node_color.append("#ff7f0e")
        elif pcon >= 50:
            node_color.append("#e377c2")
        else:
            node_color.append("#d62728")
        node_hover.append(f"<b>{entity}</b><br>PCon: {pcon}%")

    nodes_trace = go.Scatter(
        x=node_x, y=node_y,
        mode="markers+text",
        text=node_text,
        textposition="top center",
        textfont=dict(size=11, color="white"),
        marker=dict(size=node_size, color=node_color, line=dict(width=2, color="white")),
        hovertext=node_hover,
        hoverinfo="text",
        name="Entities",
    )

    # ── Build edge traces (one per rule for legend) ───────────────────────────
    rule_traces: dict[str, dict] = {}

    for (seller, buyer, rule), info in edge_map.items():
        if seller not in _ENTITY_POS or buyer not in _ENTITY_POS:
            continue
        x0, y0 = _ENTITY_POS[seller]
        x1, y1 = _ENTITY_POS[buyer]
        # Slightly offset midpoint for readability
        mx = (x0 + x1) / 2 + 0.05
        my = (y0 + y1) / 2 + 0.05

        has_exc = (seller, buyer) in exc_pairs
        gap_pct = exc_gap.get((seller, buyer), 0)
        line_color = "#ff4444" if has_exc and gap_pct > 5 else (
                     "#ffa500" if has_exc else _rule_color(rule))
        line_width = 3.5 if has_exc else 2.0
        dash = "dot" if has_exc and gap_pct > 5 else "solid"

        periods_str = ", ".join(sorted(info["periods"]))
        hover = (
            f"<b>{seller} → {buyer}</b><br>"
            f"Rule: {rule}<br>"
            f"Total USD: ${info['amount_usd']:,.0f}<br>"
            f"Transactions: {info['count']}<br>"
            f"Periods: {periods_str}"
            + (f"<br>⚠️ Exception: {gap_pct:.1f}% gap" if has_exc else "")
        )

        if rule not in rule_traces:
            rule_traces[rule] = {
                "x": [], "y": [], "hover": [], "color": _rule_color(rule),
                "width": [], "dash": [],
            }

        rule_traces[rule]["x"] += [x0, mx, x1, None]
        rule_traces[rule]["y"] += [y0, my, y1, None]
        rule_traces[rule]["hover"] += [hover, hover, hover, ""]
        rule_traces[rule]["width"].append(line_width)
        rule_traces[rule]["dash"].append(dash)

    edge_scatter_traces = []
    for rule, d in rule_traces.items():
        avg_w = sum(d["width"]) / max(len(d["width"]), 1)
        edge_scatter_traces.append(go.Scatter(
            x=d["x"], y=d["y"],
            mode="lines",
            line=dict(color=d["color"], width=avg_w),
            hovertext=d["hover"],
            hoverinfo="text",
            name=rule,
            legendgroup=rule,
        ))

    # ── Exception highlight circles ───────────────────────────────────────────
    exc_x, exc_y, exc_hover = [], [], []
    for (s, b), gap in exc_gap.items():
        if s in _ENTITY_POS and b in _ENTITY_POS:
            x0, y0 = _ENTITY_POS[s]
            x1, y1 = _ENTITY_POS[b]
            exc_x.append((x0 + x1) / 2)
            exc_y.append((y0 + y1) / 2)
            exc_hover.append(f"⚠️ Exception<br>{s} ↔ {b}<br>Max gap: {gap:.1f}%")

    exc_trace = go.Scatter(
        x=exc_x, y=exc_y,
        mode="markers",
        marker=dict(size=14, color="red", symbol="x", line=dict(width=2, color="white")),
        hovertext=exc_hover,
        hoverinfo="text",
        name="⚠️ Exceptions",
    )

    fig = go.Figure(data=edge_scatter_traces + [nodes_trace, exc_trace])
    fig.update_layout(
        title=dict(
            text="IC Relationship Network — Helios Chemicals Group",
            font=dict(size=16, color="white"),
        ),
        paper_bgcolor="#0e1117",
        plot_bgcolor="#0e1117",
        font=dict(color="white"),
        showlegend=True,
        legend=dict(
            bgcolor="#1e2130", bordercolor="#444", borderwidth=1,
            font=dict(color="white", size=11),
            x=1.01, y=1,
        ),
        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        height=560,
        margin=dict(l=20, r=160, t=50, b=20),
        hovermode="closest",
    )
    return fig


def _build_exception_heatmap(exceptions: list[dict]) -> "go.Figure | None":
    """Heatmap of exception gap% by entity pair."""
    if not _PLOTLY or not exceptions:
        return None

    pairs: dict[tuple, list] = {}
    for e in exceptions:
        meta = e.get("metadata", {})
        s = meta.get("seller_entity", "")
        b = meta.get("buyer_entity", "")
        g = float(meta.get("gap_pct", 0))
        if s and b:
            pairs.setdefault((s, b), []).append(g)

    if not pairs:
        return None

    sellers = sorted({s for s, _ in pairs})
    buyers  = sorted({b for _, b in pairs})
    z = [[sum(pairs.get((s, b), [0])) / max(len(pairs.get((s, b), [1])), 1)
          for b in buyers] for s in sellers]

    fig = go.Figure(data=go.Heatmap(
        z=z, x=buyers, y=sellers,
        colorscale="RdYlGn_r",
        zmin=0, zmax=10,
        text=[[f"{v:.1f}%" for v in row] for row in z],
        texttemplate="%{text}",
        hovertemplate="Seller: %{y}<br>Buyer: %{x}<br>Avg Gap: %{z:.1f}%<extra></extra>",
        colorbar=dict(title=dict(text="Gap %", font=dict(color="white")), tickfont=dict(color="white")),
    ))
    fig.update_layout(
        title=dict(text="Exception Gap% Heatmap (Seller → Buyer)", font=dict(color="white", size=14)),
        paper_bgcolor="#0e1117", plot_bgcolor="#0e1117",
        font=dict(color="white"),
        xaxis=dict(tickfont=dict(color="white"), title="Buyer"),
        yaxis=dict(tickfont=dict(color="white"), title="Seller"),
        height=380,
        margin=dict(l=100, r=40, t=50, b=80),
    )
    return fig


def _build_volume_bar(precedents: list[dict]) -> "go.Figure | None":
    """Grouped bar: IC volume by rule code and period."""
    if not _PLOTLY or not precedents:
        return None

    from collections import defaultdict
    data: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for p in precedents:
        meta = p.get("metadata", {})
        rule   = meta.get("rule_code", "OTHER")
        period = meta.get("period", "")
        amt    = float(meta.get("amount_usd", 0))
        if rule and period:
            data[rule][period] += amt

    periods = sorted({meta.get("metadata", {}).get("period", "") for meta in precedents if meta.get("metadata", {}).get("period")})
    rules   = sorted(data.keys())

    traces = []
    for rule in rules:
        traces.append(go.Bar(
            name=rule,
            x=periods,
            y=[data[rule].get(p, 0) / 1_000_000 for p in periods],
            marker_color=_rule_color(rule),
        ))

    fig = go.Figure(data=traces)
    fig.update_layout(
        barmode="group",
        title=dict(text="IC Volume by Rule Code & Period ($M)", font=dict(color="white", size=14)),
        paper_bgcolor="#0e1117", plot_bgcolor="#0e1117",
        font=dict(color="white"),
        xaxis=dict(tickfont=dict(color="white"), title="Period"),
        yaxis=dict(tickfont=dict(color="white"), title="Amount USD $M"),
        legend=dict(bgcolor="#1e2130", font=dict(color="white")),
        height=360,
        margin=dict(l=60, r=20, t=50, b=60),
    )
    return fig


def render_rag_tab(vectorstore, indexer) -> None:
    """Render the RAG Knowledge Base tab."""

    st.markdown("## RAG Knowledge Base")
    st.divider()

    rag_available = vectorstore is not None

    if not rag_available:
        st.warning(
            "RAG components are not available. "
            "Install `chromadb` and `sentence-transformers` to enable the knowledge base."
        )
        return

    # ── Collection Stats ─────────────────────────────────────────────────
    st.subheader("Collection Statistics")

    try:
        stats = vectorstore.get_collection_stats()
    except Exception as exc:
        st.error(f"Could not retrieve collection stats: {exc}")
        stats = {}

    s1, s2, s3, s4 = st.columns(4)
    s1.metric("Historical Exceptions", stats.get("historical_exceptions", 0))
    s2.metric("Elimination Precedents", stats.get("elimination_precedents", 0))
    s3.metric("Policy Documents", stats.get("policy_documents", 0))
    s4.metric("Period Journals", stats.get("period_journals", 0))

    st.divider()

    # ── Sub-tabs ─────────────────────────────────────────────────────────
    tab_graph, tab_exc, tab_prec, tab_policy, tab_journals = st.tabs([
        "🕸️ Knowledge Graph",
        "Historical Exceptions",
        "Elimination Precedents",
        "Policy Documents",
        "Period Journals",
    ])

    # ── Knowledge Graph ───────────────────────────────────────────────────
    with tab_graph:
        st.markdown("### IC Relationship Network")
        st.caption(
            "Nodes = HCG entities (blue=100% owned, orange=75%, pink=60%, red=40%). "
            "Edges = intercompany relationships by rule code. "
            "Red ✕ = entity pairs with historical exceptions."
        )

        # Load data from vectorstore
        prec_raw = []
        exc_raw  = []
        try:
            prec_raw = vectorstore.query_elimination_precedents(
                "intercompany sales loan interest royalty management fee", rule_code="", n_results=50
            )
        except Exception:
            pass
        try:
            exc_raw = vectorstore.query_historical_exceptions(
                "timing FX dispute mismatch gap difference", n_results=50
            )
        except Exception:
            pass

        if not _PLOTLY:
            st.warning("Install `plotly` to view graphs: `pip install plotly`")
        elif not prec_raw and not exc_raw:
            st.info("No RAG data yet. Run the seed script or complete a pipeline to populate graphs.")
        else:
            # ── Network graph ──────────────────────────────────────────────
            fig_net = _build_ic_network_graph(prec_raw, exc_raw)
            if fig_net:
                st.plotly_chart(fig_net, use_container_width=True)

            col_heat, col_bar = st.columns(2)

            # ── Exception heatmap ──────────────────────────────────────────
            with col_heat:
                fig_heat = _build_exception_heatmap(exc_raw)
                if fig_heat:
                    st.plotly_chart(fig_heat, use_container_width=True)
                else:
                    st.info("No exception data for heatmap.")

            # ── IC volume bar ──────────────────────────────────────────────
            with col_bar:
                fig_bar = _build_volume_bar(prec_raw)
                if fig_bar:
                    st.plotly_chart(fig_bar, use_container_width=True)
                else:
                    st.info("No precedent data for volume chart.")

        # ── Legend ────────────────────────────────────────────────────────
        st.divider()
        st.markdown("**Rule Code Legend**")
        leg_cols = st.columns(4)
        legend_items = [
            ("IC-001", "Intercompany Sales"),
            ("IC-002", "Intercompany Services"),
            ("IC-003", "Intercompany Loans (BS)"),
            ("IC-004", "Royalties"),
            ("IC-005", "Management Fees"),
            ("IC-006", "IC Interest"),
            ("EQ-001", "Equity Eliminations"),
            ("FX-001", "FX Differences"),
        ]
        for i, (code, desc) in enumerate(legend_items):
            color = _rule_color(code)
            leg_cols[i % 4].markdown(
                f'<span style="color:{color}; font-size:18px;">■</span> '
                f'**{code}** — {desc}',
                unsafe_allow_html=True,
            )

    # ── Historical Exceptions ─────────────────────────────────────────────
    with tab_exc:
        st.markdown("### Historical Exceptions")

        search_exc = st.text_input(
            "Search Historical Exceptions:",
            placeholder="e.g. timing difference UK DE IC-001",
            key="search_exc",
        )
        if search_exc:
            try:
                results = vectorstore.query_historical_exceptions(search_exc, n_results=5)
                if results:
                    for r in results:
                        with st.container():
                            st.markdown(
                                f"**ID:** `{r.get('id', '')}` &nbsp;|&nbsp; "
                                f"**Similarity:** {r.get('similarity', 0):.3f}"
                            )
                            st.markdown(r.get("document", ""))
                            meta = r.get("metadata", {})
                            if meta:
                                m1, m2, m3 = st.columns(3)
                                m1.caption(f"Rule: {meta.get('rule_code', '')}")
                                m2.caption(f"Gap: {meta.get('gap_pct', 0):.2f}%")
                                m3.caption(f"Period: {meta.get('period', '')}")
                            st.divider()
                else:
                    st.info("No results found.")
            except Exception as exc:
                st.error(f"Search failed: {exc}")

        st.divider()
        st.markdown("### Add New Exception to Knowledge Base")

        with st.form("add_exception_form"):
            ae1, ae2 = st.columns(2)
            entity_pair_seller = ae1.text_input("Seller Entity", placeholder="e.g. HCG-UK")
            entity_pair_buyer = ae2.text_input("Buyer Entity", placeholder="e.g. HCG-DE")
            rule_code_exc = st.text_input("Rule Code", placeholder="e.g. IC-001")
            gap_pct_exc = st.number_input("Gap %", min_value=0.0, max_value=100.0, step=0.1)
            description_exc = st.text_area("Root Cause Description", placeholder="Describe the root cause...")
            resolution_exc = st.text_area("Resolution", placeholder="Describe how it was resolved...")
            period_exc = st.text_input("Period", value=datetime.utcnow().strftime("%Y-%m"))
            submitted_exc = st.form_submit_button("Index Exception")

            if submitted_exc:
                if not entity_pair_seller or not entity_pair_buyer or not rule_code_exc:
                    st.error("Seller, Buyer, and Rule Code are required.")
                else:
                    match_data = {
                        "txn_id": None,
                        "seller_entity": entity_pair_seller.strip(),
                        "buyer_entity": entity_pair_buyer.strip(),
                        "rule_code": rule_code_exc.strip(),
                        "gap_pct": float(gap_pct_exc),
                        "root_cause": description_exc.strip(),
                        "period": period_exc.strip(),
                    }
                    try:
                        if indexer:
                            success = indexer.index_resolved_exception(match_data, resolution_exc.strip())
                        else:
                            vectorstore.add_historical_exception({
                                **match_data,
                                "resolution": resolution_exc.strip(),
                            })
                            success = True
                        if success:
                            st.success("Exception indexed successfully.")
                            st.rerun()
                        else:
                            st.error("Indexing failed.")
                    except Exception as exc:
                        st.error(f"Failed to index exception: {exc}")

    # ── Elimination Precedents ────────────────────────────────────────────
    with tab_prec:
        st.markdown("### Elimination Precedents")

        search_prec = st.text_input(
            "Search Elimination Precedents:",
            placeholder="e.g. IC-001 HCG-UK intercompany sales",
            key="search_prec",
        )
        rule_filter = st.text_input(
            "Filter by Rule Code (optional):",
            placeholder="e.g. IC-001",
            key="prec_rule_filter",
        )
        if search_prec:
            try:
                results = vectorstore.query_elimination_precedents(
                    search_prec, rule_code=rule_filter.strip(), n_results=5
                )
                if results:
                    for r in results:
                        with st.container():
                            st.markdown(
                                f"**ID:** `{r.get('id', '')}` &nbsp;|&nbsp; "
                                f"**Similarity:** {r.get('similarity', 0):.3f}"
                            )
                            st.markdown(r.get("document", ""))
                            meta = r.get("metadata", {})
                            if meta:
                                m1, m2, m3 = st.columns(3)
                                m1.caption(f"Rule: {meta.get('rule_code', '')}")
                                m2.caption(f"Amount USD: ${meta.get('amount_usd', 0):,.2f}")
                                m3.caption(f"Period: {meta.get('period', '')}")
                            st.divider()
                else:
                    st.info("No results found.")
            except Exception as exc:
                st.error(f"Search failed: {exc}")
        else:
            st.info("Enter a search query to retrieve similar elimination precedents.")

    # ── Policy Documents ──────────────────────────────────────────────────
    with tab_policy:
        st.markdown("### Policy Documents")

        search_policy = st.text_input(
            "Search Policy Documents:",
            placeholder="e.g. NCI equity elimination pcon",
            key="search_policy",
        )
        if search_policy:
            try:
                results = vectorstore.query_policy_documents(search_policy, n_results=5)
                if results:
                    for r in results:
                        with st.container():
                            st.markdown(
                                f"**ID:** `{r.get('id', '')}` &nbsp;|&nbsp; "
                                f"**Similarity:** {r.get('similarity', 0):.3f}"
                            )
                            st.markdown(r.get("document", ""))
                            meta = r.get("metadata", {})
                            if meta:
                                m1, m2 = st.columns(2)
                                m1.caption(f"Category: {meta.get('category', '')}")
                                m2.caption(f"Rule: {meta.get('rule_code', '')}")
                            st.divider()
                else:
                    st.info("No results found.")
            except Exception as exc:
                st.error(f"Search failed: {exc}")
        else:
            st.info("Enter a search query to retrieve relevant policy documents.")

        st.divider()
        st.markdown("### Add Policy Document")

        with st.form("add_policy_form"):
            pp1, pp2 = st.columns(2)
            doc_title = pp1.text_input("Document Title", placeholder="e.g. Group FX Policy 2024")
            doc_category = pp2.text_input("Category", placeholder="e.g. FX_POLICY")
            doc_rule_code = st.text_input("Rule Code (if applicable)", placeholder="e.g. IC-001")
            doc_content = st.text_area(
                "Document Content",
                placeholder="Paste or type the policy document content here...",
                height=150,
            )
            submitted_policy = st.form_submit_button("Index Policy Document")

            if submitted_policy:
                if not doc_title or not doc_content:
                    st.error("Title and content are required.")
                else:
                    doc_data = {
                        "title": doc_title.strip(),
                        "category": doc_category.strip(),
                        "rule_code": doc_rule_code.strip(),
                        "content": doc_content.strip(),
                    }
                    try:
                        vectorstore.add_policy_document(doc_data)
                        st.success("Policy document indexed successfully.")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Failed to index policy document: {exc}")

    # ── Period Journals ───────────────────────────────────────────────────
    with tab_journals:
        st.markdown("### Period Journals")

        search_journals = st.text_input(
            "Search Period Journals:",
            placeholder="e.g. HCG-UK IC-001 revenue elimination",
            key="search_journals",
        )
        period_filter = st.text_input(
            "Filter by Period (optional):",
            placeholder="e.g. 2024-03",
            key="journals_period_filter",
        )
        if search_journals:
            try:
                results = vectorstore.query_period_journals(
                    search_journals, period=period_filter.strip(), n_results=5
                )
                if results:
                    for r in results:
                        with st.container():
                            st.markdown(
                                f"**ID:** `{r.get('id', '')}` &nbsp;|&nbsp; "
                                f"**Similarity:** {r.get('similarity', 0):.3f}"
                            )
                            st.markdown(r.get("document", ""))
                            meta = r.get("metadata", {})
                            if meta:
                                m1, m2, m3 = st.columns(3)
                                m1.caption(f"Rule: {meta.get('rule_code', '')}")
                                m2.caption(f"Period: {meta.get('period', '')}")
                                m3.caption(f"Amount: ${meta.get('amount_usd', 0):,.2f}")
                            st.divider()
                else:
                    st.info("No results found.")
            except Exception as exc:
                st.error(f"Search failed: {exc}")
        else:
            st.info("Enter a search query to retrieve similar period journal entries.")

    st.divider()

    # ── Retrieval Quality Metrics ─────────────────────────────────────────
    st.subheader("Retrieval Quality Metrics")

    # Estimated average similarity scores (based on collection size as proxy)
    collection_names = ["historical_exceptions", "elimination_precedents", "policy_documents", "period_journals"]
    display_names = ["Historical\nExceptions", "Elimination\nPrecedents", "Policy\nDocuments", "Period\nJournals"]

    doc_counts = [stats.get(c, 0) for c in collection_names]
    # Estimate: more documents = richer retrieval = higher confidence
    estimated_scores = []
    for count in doc_counts:
        if count == 0:
            estimated_scores.append(0.0)
        elif count < 5:
            estimated_scores.append(0.45)
        elif count < 20:
            estimated_scores.append(0.65)
        elif count < 50:
            estimated_scores.append(0.75)
        else:
            estimated_scores.append(0.85)

    if _PLOTLY:
        fig = go.Figure(data=[
            go.Bar(
                x=display_names,
                y=estimated_scores,
                marker_color=["#28a745" if s >= 0.65 else "#ffc107" if s >= 0.40 else "#dc3545"
                               for s in estimated_scores],
                text=[f"{s:.0%}" for s in estimated_scores],
                textposition="auto",
            )
        ])
        fig.update_layout(
            title="Estimated Average Confidence Score per Collection",
            yaxis_title="Confidence",
            yaxis=dict(range=[0, 1.05]),
            height=320,
            margin=dict(t=50, b=40, l=50, r=20),
        )
        fig.add_hline(y=0.65, line_dash="dash", line_color="orange",
                      annotation_text="Confidence Threshold (0.65)")
        st.plotly_chart(fig, use_container_width=True)
    else:
        # Fallback plain display
        for name, score, count in zip(display_names, estimated_scores, doc_counts):
            st.write(f"**{name.replace(chr(10), ' ')}**: {score:.0%} (docs: {count})")

    st.caption(
        "Confidence scores are estimated based on collection size. "
        "Run a close pipeline to generate actual retrieval scores."
    )
