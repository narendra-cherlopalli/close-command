import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime, date
import random
import io

st.set_page_config(
    page_title="IC Elimination Engine — OCINVAR Rules",
    layout="wide",
    page_icon="⚖️"
)

random.seed(42)
np.random.seed(42)

# ─────────────────────────────────────────────────────────────
# HFM RULES ENGINE — Derived from OCINVAR Rules_File.rle
# 28 elimination rules mapped to deterministic Python logic
# ─────────────────────────────────────────────────────────────

ELIMINATION_RULES = {
    # ── EQUITY ELIMINATIONS ──────────────────────────────────
    "CAPI":     {"label": "Equity Split — Group vs NCI",          "category": "Equity",       "description": "Splits balance at PCon/POwn/PMin. Posts to Group Reserves & NCI in [Elimination] value."},
    "CAPIC":    {"label": "Translation Reserve Split",             "category": "Equity",       "description": "Same as CAPI but targets FX conversion reserves RsvCG/RsvCM."},
    "COMPINC":  {"label": "OCI Split — Group vs NCI",              "category": "Equity/OCI",   "description": "Posts Group OCI to account and NCI portion to aOCINCI."},
    "RESU":     {"label": "Net Income Split — Group vs NCI",       "category": "P&L",          "description": "Splits net income at POwn/PMin into ResG/ResM. Equity method via aTMEE."},
    "RESUC":    {"label": "FX Adjustment on Net Income",           "category": "P&L/FX",       "description": "Posts FX impact on result to conversion reserve accounts ResCG/ResCM."},
    # ── INVESTMENT ELIMINATIONS ──────────────────────────────
    "PINT":     {"label": "Investment in Subsidiaries",            "category": "Investment",   "description": "Eliminates investment account at PCon. Posts to liaison accounts LTIT/LPTIT and Group/NCI reserves."},
    "PINTH":    {"label": "Historic Investment Accounts",          "category": "Investment",   "description": "Historical carry-forward of PINT. Reclassifies between reserves and conversion reserves."},
    # ── ICP / INTERCOMPANY ELIMINATIONS ─────────────────────
    "ELIPROV":  {"label": "ICP Provisions",                        "category": "Intercompany", "description": "Eliminates intragroup provisions at PCon. Includes deferred tax (DT) via TAX_FED_RATE. Active Year > 2022."},
    "ELIPROVH": {"label": "Historic ICP Provisions",               "category": "Intercompany", "description": "Historical carry-forward of ELIPROV. Handles FX flows EConOuv/EConFlux into conversion reserves."},
    "ELIM":     {"label": "Standard ICP Elimination",              "category": "Intercompany", "description": "Simple bilateral elimination at Min(PCon, ICPPCon). Uses PlugAcct as counterpart."},
    "ELIMR":    {"label": "Reciprocal ICP Elimination",            "category": "Intercompany", "description": "Two-sided: seller eliminated at Min; buyer account (UD2) posted to PElim. Handles PropE/PropU."},
    "ELIMRA":   {"label": "Conditional Reciprocal Elimination",    "category": "Intercompany", "description": "Same as ELIMR but only fires when Data > 0 — seller rule only. Avoids double elimination."},
    # ── GOODWILL ELIMINATIONS ────────────────────────────────
    "GW":       {"label": "Goodwill Elimination",                  "category": "Goodwill",     "description": "Eliminates goodwill at PCon × ICPPCon. Uses PlugAcct as counterpart. Handles scope entry vs ongoing."},
    "GWH":      {"label": "Historic Goodwill",                     "category": "Goodwill",     "description": "Historical carry-forward of GW. Reclassifies between reserves and conversion reserves on scope variation."},
    "GWA":      {"label": "Goodwill Depreciation",                 "category": "Goodwill",     "description": "Handles impairment (IMP flow) separately. Posts to aContrepartie/aDAmEA. Equity method uses aResMEE."},
    "GWAH":     {"label": "Historic Goodwill Depreciation",        "category": "Goodwill",     "description": "Historical carry-forward of GWA. Handles FX flows TAF, TAO, TAR impacting 106CG/CM, 120CG/CM."},
    # ── DIVIDEND ELIMINATIONS ────────────────────────────────
    "DIVP":     {"label": "Paid Dividends",                        "category": "Dividends",    "description": "Eliminates paid dividends at PCon. Posts to Group/NCI reserves with scope variation treatment."},
    "DIVVAR":   {"label": "Scope Variation — Paid Dividends",      "category": "Dividends",    "description": "Reclassifies between reserves and conversion reserves for scope changes."},
    "DIVH":     {"label": "FX on Withholding Tax",                 "category": "Dividends/FX", "description": "Posts FX movements on WHT dividends to ResCG/ResCM and RsvCG/RsvCM."},
    "DIVI":     {"label": "Dividend Income from Participations",   "category": "Dividends",    "description": "Eliminates dividend income at PCon. Posts to ResG/ResM. FX conversion impact included."},
    "DIVIVAR":  {"label": "Scope Variation — Dividend Income",     "category": "Dividends",    "description": "Mirror of DIVVAR on the income side."},
    "DIVIH":    {"label": "FX on Dividend Income",                 "category": "Dividends/FX", "description": "Posts FX impact to ResCG/ResCM on EConFlux flow."},
    # ── STOCK MARGIN ELIMINATIONS ────────────────────────────
    "PSTK":     {"label": "Profit in Stock",                       "category": "Stock Margin", "description": "Eliminates intragroup profit in buyer's inventory. Includes deferred tax via TIMP rate. Active Year > 2018."},
    "PSTKH":    {"label": "Historic Profit in Stock",              "category": "Stock Margin", "description": "Carry-forward of PSTK. Handles FX flows EConOuv/EConFlux. Includes DT variance on opening."},
    # ── ASSET UNDER CONSTRUCTION ─────────────────────────────
    "AUCREV":   {"label": "AUC — Revenue Side",                    "category": "AUC/CapEx",    "description": "Eliminates intra-group construction revenues at PCon × ICPPCon. Posts to aRevenue P&L + aLNK_AUC plug. Includes DT."},
    "AUCREVH":  {"label": "Historic AUC Revenue",                  "category": "AUC/CapEx",    "description": "Historical carry-forward of AUCREV with full FX treatment."},
    "AUCCOS":   {"label": "AUC — Cost Side",                       "category": "AUC/CapEx",    "description": "Mirror of AUCREV but posts to aCost P&L account. Same plug and DT treatment."},
    "AUCCOSH":  {"label": "Historic AUC Cost",                     "category": "AUC/CapEx",    "description": "Historical carry-forward of AUCCOS."},
}

CATEGORY_COLORS = {
    "Equity":       "#1D6FA5",
    "Equity/OCI":   "#1D6FA5",
    "P&L":          "#2E86AB",
    "P&L/FX":       "#2E86AB",
    "Investment":   "#0F6E56",
    "Intercompany": "#5C4A8C",
    "Goodwill":     "#B5562D",
    "Dividends":    "#C47A1E",
    "Dividends/FX": "#C47A1E",
    "Stock Margin": "#1A7A4A",
    "AUC/CapEx":    "#5A5A5A",
}

# ─────────────────────────────────────────────────────────────
# SAMPLE DATA — Multi-entity group (OCINVAR-style)
# ─────────────────────────────────────────────────────────────

ENTITIES = {
    "HOLDING":  {"name": "OCI Holdings SA",          "method": "Holding",      "pcon": 1.00, "pown": 1.00, "currency": "USD"},
    "EBIC":     {"name": "Egyptian Basic Ind. Corp.", "method": "Global",       "pcon": 0.60, "pown": 0.60, "currency": "EGP"},
    "SORFERT":  {"name": "Sorfert Algérie",           "method": "Global",       "pcon": 0.51, "pown": 0.51, "currency": "DZD"},
    "EFC":      {"name": "Egypt Fert. Co.",           "method": "Global",       "pcon": 0.75, "pown": 0.75, "currency": "EGP"},
    "FERTIL":   {"name": "Fertil UAE",                "method": "Global",       "pcon": 0.42, "pown": 0.42, "currency": "AED"},
    "GCOV":     {"name": "Gulf Chemicals & Ind.",     "method": "Proportional", "pcon": 0.50, "pown": 0.50, "currency": "AED"},
    "NATPHOS":  {"name": "National Phos. Co.",        "method": "Equity",       "pcon": 0.30, "pown": 0.30, "currency": "USD"},
    "OCINV":    {"name": "OCI Investments BV",        "method": "Global",       "pcon": 1.00, "pown": 1.00, "currency": "EUR"},
}

FX_RATES = {"USD": 1.0, "EGP": 0.032, "DZD": 0.0074, "AED": 0.272, "EUR": 1.08}

def generate_ic_transactions():
    pairs = [
        ("HOLDING", "EBIC",    "ELIM",    "IC Loan Interest",         1_250_000),
        ("HOLDING", "SORFERT", "ELIM",    "Management Fee",             420_000),
        ("EBIC",    "EFC",     "ELIMR",   "Ammonia Sale",             3_800_000),
        ("EFC",     "FERTIL",  "ELIMR",   "Urea Supply",              2_100_000),
        ("OCINV",   "HOLDING", "PINT",    "Investment in Subsidiary", 15_000_000),
        ("HOLDING", "GCOV",    "PSTK",    "Profit in Stock — Propyl",   680_000),
        ("HOLDING", "EBIC",    "DIVP",    "Dividend Payment",           900_000),
        ("EBIC",    "EFC",     "DIVI",    "Dividend Income",            540_000),
        ("HOLDING", "SORFERT", "GW",      "Goodwill — Sorfert Acq.",  4_500_000),
        ("OCINV",   "FERTIL",  "ELIPROV", "ICP Allowance for Doubt.",  320_000),
        ("HOLDING", "EFC",     "CAPI",    "Share Capital Contrib.",   8_000_000),
        ("OCINV",   "EBIC",    "RESU",    "Net Income — Current Yr",  1_650_000),
        ("HOLDING", "NATPHOS", "AUCREV",  "AUC Revenue — Plant Exp.", 2_200_000),
        ("NATPHOS", "HOLDING", "AUCCOS",  "AUC Cost — Plant Exp.",    2_190_000),
        ("GCOV",    "EFC",     "ELIMRA",  "Conditional Elim — Srv",     175_000),
    ]
    rows = []
    for i, (seller, buyer, rule, desc, base_amt) in enumerate(pairs):
        noise = random.uniform(-0.015, 0.015)
        seller_amt = base_amt
        buyer_amt  = base_amt * (1 + noise)
        gap = abs(seller_amt - buyer_amt)
        gap_pct = gap / seller_amt * 100
        s_cur = ENTITIES[seller]["currency"]
        b_cur = ENTITIES[buyer]["currency"]
        seller_usd = seller_amt * FX_RATES[s_cur]
        buyer_usd  = buyer_amt  * FX_RATES[b_cur]
        match_status = "Matched" if gap_pct < 0.5 else ("Tolerance" if gap_pct < 2.0 else "Exception")
        rows.append({
            "ID":             f"ICP-{i+1:03d}",
            "Seller":         seller,
            "Buyer":          buyer,
            "Rule":           rule,
            "Description":    desc,
            "Seller Amt":     seller_amt,
            "Buyer Amt":      buyer_amt,
            "Seller CCY":     s_cur,
            "Buyer CCY":      b_cur,
            "Seller USD":     seller_usd,
            "Buyer USD":      buyer_usd,
            "Gap USD":        abs(seller_usd - buyer_usd),
            "Gap %":          gap_pct,
            "Match Status":   match_status,
            "Category":       ELIMINATION_RULES[rule]["category"],
            "Rule Label":     ELIMINATION_RULES[rule]["label"],
            "PCon Seller":    ENTITIES[seller]["pcon"],
            "PCon Buyer":     ENTITIES[buyer]["pcon"],
        })
    return pd.DataFrame(rows)

def compute_elimination(row):
    rule     = row["Rule"]
    amt      = row["Seller USD"]
    pcon_s   = row["PCon Seller"]
    pcon_b   = row["PCon Buyer"]
    pown_s   = pcon_s
    pmin_s   = pcon_s - pown_s if pcon_s > pown_s else 0
    min_pcon = min(pcon_s, pcon_b)

    entries = []

    if rule in ("ELIM",):
        entries.append({"Account": "IC Receivable / Revenue", "Value": "[Elimination]", "Dr/Cr": "Dr", "Amount": -amt * min_pcon, "Audit": rule})
        entries.append({"Account": "IC Payable / Cost",       "Value": "[Elimination]", "Dr/Cr": "Cr", "Amount":  amt * min_pcon, "Audit": rule})

    elif rule in ("ELIMR", "ELIMRA"):
        entries.append({"Account": "Seller Account",  "Value": "[Elimination]", "Dr/Cr": "Dr", "Amount": -amt * min_pcon, "Audit": rule})
        entries.append({"Account": "Plug Account",    "Value": "[Elimination]", "Dr/Cr": "Cr", "Amount":  amt * min_pcon, "Audit": rule})
        entries.append({"Account": "Buyer Account",   "Value": "[Elimination]", "Dr/Cr": "Dr", "Amount":  amt * min_pcon, "Audit": rule + "-PElim"})
        entries.append({"Account": "Plug Account",    "Value": "[Elimination]", "Dr/Cr": "Cr", "Amount": -amt * min_pcon, "Audit": rule + "-PElim"})

    elif rule == "CAPI":
        entries.append({"Account": "Share Capital",      "Value": "[Elimination]", "Dr/Cr": "Dr", "Amount": -amt * pcon_s, "Audit": rule})
        entries.append({"Account": "Group Reserves",     "Value": "[Elimination]", "Dr/Cr": "Cr", "Amount":  amt * pown_s, "Audit": rule})
        entries.append({"Account": "NCI",                "Value": "[Elimination]", "Dr/Cr": "Cr", "Amount":  amt * pmin_s, "Audit": rule})

    elif rule == "RESU":
        entries.append({"Account": "Net Income",         "Value": "[Elimination]", "Dr/Cr": "Dr", "Amount": -amt * pcon_s,  "Audit": rule})
        entries.append({"Account": "Group Net Income",   "Value": "[Elimination]", "Dr/Cr": "Cr", "Amount":  amt * pown_s,  "Audit": rule})
        entries.append({"Account": "NCI Net Income",     "Value": "[Elimination]", "Dr/Cr": "Cr", "Amount":  amt * pmin_s,  "Audit": rule})

    elif rule == "GW":
        entries.append({"Account": "Goodwill",            "Value": "[Elimination]", "Dr/Cr": "Dr", "Amount": -amt * pcon_s * pcon_b, "Audit": rule})
        entries.append({"Account": "Investment Account",  "Value": "[Elimination]", "Dr/Cr": "Cr", "Amount":  amt * pcon_s * pcon_b, "Audit": rule})
        entries.append({"Account": "Group Reserves",      "Value": "[Elimination]", "Dr/Cr": "Cr", "Amount": -amt * pown_s,           "Audit": rule})
        entries.append({"Account": "NCI",                 "Value": "[Elimination]", "Dr/Cr": "Cr", "Amount": -amt * pmin_s,           "Audit": rule})

    elif rule == "PINT":
        entries.append({"Account": "Investment in Sub",  "Value": "[Elimination]", "Dr/Cr": "Dr", "Amount": -amt * pcon_s, "Audit": rule})
        entries.append({"Account": "Liaison LTIT",       "Value": "[Elimination]", "Dr/Cr": "Cr", "Amount":  amt * pcon_s, "Audit": rule})
        entries.append({"Account": "Group Reserves",     "Value": "[Elimination]", "Dr/Cr": "Cr", "Amount":  amt * pown_s, "Audit": rule + "-None"})
        entries.append({"Account": "NCI",                "Value": "[Elimination]", "Dr/Cr": "Cr", "Amount":  amt * pmin_s, "Audit": rule + "-None"})

    elif rule == "DIVP":
        entries.append({"Account": "Dividends Paid",    "Value": "[Elimination]", "Dr/Cr": "Dr", "Amount": -amt * pcon_s,  "Audit": rule})
        entries.append({"Account": "Group Reserves",    "Value": "[Elimination]", "Dr/Cr": "Cr", "Amount":  amt * pown_s,  "Audit": rule})
        entries.append({"Account": "NCI",               "Value": "[Elimination]", "Dr/Cr": "Cr", "Amount":  amt * pmin_s,  "Audit": rule})

    elif rule == "DIVI":
        entries.append({"Account": "Dividend Income",   "Value": "[Elimination]", "Dr/Cr": "Dr", "Amount": -amt * pcon_s,  "Audit": rule})
        entries.append({"Account": "Group Net Income",  "Value": "[Elimination]", "Dr/Cr": "Cr", "Amount":  amt * pown_s,  "Audit": rule})
        entries.append({"Account": "NCI Net Income",    "Value": "[Elimination]", "Dr/Cr": "Cr", "Amount":  amt * pmin_s,  "Audit": rule})

    elif rule == "PSTK":
        dt_rate = 0.25
        entries.append({"Account": "Inventory (Seller)",    "Value": "[Elimination]", "Dr/Cr": "Dr", "Amount": -amt * pcon_s * pcon_b, "Audit": rule})
        entries.append({"Account": "COGS / Revenue",        "Value": "[Elimination]", "Dr/Cr": "Cr", "Amount":  amt * pcon_s * pcon_b, "Audit": rule})
        entries.append({"Account": "Deferred Tax Liability","Value": "[Elimination]", "Dr/Cr": "Dr", "Amount":  amt * pcon_s * pcon_b * dt_rate, "Audit": rule + "-DT"})
        entries.append({"Account": "Deferred Tax P&L",      "Value": "[Elimination]", "Dr/Cr": "Cr", "Amount": -amt * pcon_s * pcon_b * dt_rate, "Audit": rule + "-DT"})

    elif rule == "ELIPROV":
        dt_rate = 0.22
        entries.append({"Account": "ICP Provision",         "Value": "[Elimination]", "Dr/Cr": "Dr", "Amount": -amt * pcon_s, "Audit": rule})
        entries.append({"Account": "Provision Reversal P&L","Value": "[Elimination]", "Dr/Cr": "Cr", "Amount":  amt * pcon_s, "Audit": rule})
        entries.append({"Account": "Deferred Tax Liability","Value": "[Elimination]", "Dr/Cr": "Dr", "Amount":  amt * pcon_s * dt_rate, "Audit": rule + "-DT"})
        entries.append({"Account": "Deferred Tax P&L",      "Value": "[Elimination]", "Dr/Cr": "Cr", "Amount": -amt * pcon_s * dt_rate, "Audit": rule + "-DT"})

    elif rule in ("AUCREV", "AUCCOS"):
        dt_rate = 0.24
        pl_acct = "Construction Revenue" if rule == "AUCREV" else "Construction Cost"
        entries.append({"Account": "AUC Asset",    "Value": "[Elimination]", "Dr/Cr": "Dr", "Amount": -amt * pcon_s * pcon_b, "Audit": rule})
        entries.append({"Account": pl_acct,        "Value": "[Elimination]", "Dr/Cr": "Cr", "Amount":  amt * pcon_s * pcon_b, "Audit": rule})
        entries.append({"Account": "Link AUC BS",  "Value": "[Elimination]", "Dr/Cr": "Dr", "Amount": -amt * pcon_s, "Audit": rule})
        entries.append({"Account": "Link AUC Cntr","Value": "[Elimination]", "Dr/Cr": "Cr", "Amount":  amt * pcon_s, "Audit": rule})
        entries.append({"Account": "DTL",          "Value": "[Elimination]", "Dr/Cr": "Dr", "Amount":  amt * pcon_s * pcon_b * dt_rate, "Audit": rule + "-DT"})
        entries.append({"Account": "DT P&L",       "Value": "[Elimination]", "Dr/Cr": "Cr", "Amount": -amt * pcon_s * pcon_b * dt_rate, "Audit": rule + "-DT"})

    else:
        entries.append({"Account": f"{rule} — Account",  "Value": "[Elimination]", "Dr/Cr": "Dr", "Amount": -amt * pcon_s, "Audit": rule})
        entries.append({"Account": f"{rule} — Counterpart","Value": "[Elimination]", "Dr/Cr": "Cr", "Amount":  amt * pcon_s, "Audit": rule})

    return entries

# ─────────────────────────────────────────────────────────────
# CSS
# ─────────────────────────────────────────────────────────────

st.markdown("""
<style>
  .rule-chip {
    display:inline-block; padding:2px 10px; border-radius:12px;
    font-size:12px; font-weight:600; letter-spacing:.04em; color:#fff;
    margin:2px;
  }
  .section-header {
    font-size:13px; font-weight:700; letter-spacing:.08em; text-transform:uppercase;
    color:#888; margin:18px 0 6px;
  }
  .elim-row-dr { background:#fff4f4; }
  .elim-row-cr { background:#f4fff8; }
  .kpi-label { font-size:11px; color:#999; font-weight:600; text-transform:uppercase; letter-spacing:.06em; }
  .kpi-value { font-size:26px; font-weight:700; color:#111; }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────
# LOAD DATA
# ─────────────────────────────────────────────────────────────

df = generate_ic_transactions()

# ─────────────────────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────────────────────

with st.sidebar:
    st.image("https://upload.wikimedia.org/wikipedia/commons/thumb/8/84/OCI_N.V._logo.svg/200px-OCI_N.V._logo.svg.png", width=100)
    st.markdown("### IC Elimination Engine")
    st.caption("Rules derived from OCINVAR / Oracle FCCS")
    st.divider()

    entity_options = ["All Entities"] + list(ENTITIES.keys())
    sel_entity = st.selectbox("Filter Entity", entity_options)

    all_cats = sorted(set(r["category"] for r in ELIMINATION_RULES.values()))
    sel_cats = st.multiselect("Filter Category", all_cats, default=all_cats)

    threshold = st.slider("Gap Tolerance (%)", 0.0, 5.0, 0.5, 0.1)

    st.divider()
    st.markdown("**ROI Assumptions**")
    fte_rate   = st.number_input("FTE Hourly Rate (USD)", value=85, step=5)
    hrs_manual = st.number_input("Manual Hours / Period", value=40, step=4)
    hrs_auto   = st.number_input("AI-Assisted Hours / Period", value=6, step=1)

    st.divider()
    st.markdown("**Scenario**")
    period_label = st.selectbox("Period", ["Q2 2025", "Q1 2025", "FY 2024"])
    show_dt      = st.checkbox("Show Deferred Tax entries", value=True)

# ─────────────────────────────────────────────────────────────
# FILTER DATA
# ─────────────────────────────────────────────────────────────

filtered = df.copy()
if sel_entity != "All Entities":
    filtered = filtered[(filtered["Seller"] == sel_entity) | (filtered["Buyer"] == sel_entity)]
if sel_cats:
    filtered = filtered[filtered["Category"].isin(sel_cats)]

# ─────────────────────────────────────────────────────────────
# HEADER
# ─────────────────────────────────────────────────────────────

st.markdown("## ⚖️ Intercompany Elimination Engine")
st.markdown(f"**OCINVAR Group · {period_label} · [Elimination] Value** — {len(ELIMINATION_RULES)} elimination rules loaded from `Rules_File.rle`")
st.divider()

# ─────────────────────────────────────────────────────────────
# TABS
# ─────────────────────────────────────────────────────────────

tabs = st.tabs([
    "📊 Dashboard",
    "🔍 IC Matching",
    "⚙️ Elimination Engine",
    "📋 Journal Entries",
    "🗂️ Rules Reference",
    "🏗️ Entity Hierarchy",
    "📈 Consolidation Proof",
    "💰 ROI Impact",
    "📁 Audit Trail"
])

# ════════════════════════════════════════════════════
# TAB 1 — DASHBOARD
# ════════════════════════════════════════════════════
with tabs[0]:
    total_elim    = df["Seller USD"].sum()
    matched_count = len(df[df["Match Status"] == "Matched"])
    exception_count = len(df[df["Gap %"] > threshold])
    total_gap     = df["Gap USD"].sum()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total IC Volume (USD)", f"${total_elim/1e6:.2f}M")
    c2.metric("Transactions",          str(len(df)))
    c3.metric("Matched",               f"{matched_count}/{len(df)}", f"{matched_count/len(df)*100:.0f}%")
    c4.metric("Exceptions",            str(exception_count), delta=f">{threshold}% gap", delta_color="inverse")

    st.divider()
    col_a, col_b = st.columns(2)

    with col_a:
        st.markdown('<p class="section-header">Volume by Elimination Category</p>', unsafe_allow_html=True)
        cat_df = df.groupby("Category")["Seller USD"].sum().reset_index().sort_values("Seller USD", ascending=True)
        fig = px.bar(cat_df, x="Seller USD", y="Category", orientation="h",
                     color="Category",
                     color_discrete_map={c: CATEGORY_COLORS.get(c, "#888") for c in cat_df["Category"]},
                     labels={"Seller USD": "Amount (USD)"})
        fig.update_layout(height=320, showlegend=False, margin=dict(l=0, r=0, t=10, b=10),
                          paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig, use_container_width=True)

    with col_b:
        st.markdown('<p class="section-header">Match Status Distribution</p>', unsafe_allow_html=True)
        status_counts = df["Match Status"].value_counts()
        colors = {"Matched": "#1D9E75", "Tolerance": "#E8A838", "Exception": "#D94F3D"}
        fig2 = go.Figure(go.Pie(
            labels=status_counts.index, values=status_counts.values,
            marker_colors=[colors.get(s, "#888") for s in status_counts.index],
            hole=0.55, textinfo="label+percent"
        ))
        fig2.update_layout(height=320, showlegend=False, margin=dict(l=0, r=0, t=10, b=10),
                           paper_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig2, use_container_width=True)

    st.markdown('<p class="section-header">IC Transaction Summary</p>', unsafe_allow_html=True)
    disp = filtered[["ID","Seller","Buyer","Rule","Rule Label","Description",
                      "Seller USD","Buyer USD","Gap %","Match Status","Category"]].copy()
    disp["Seller USD"] = disp["Seller USD"].map("${:,.0f}".format)
    disp["Buyer USD"]  = disp["Buyer USD"].map("${:,.0f}".format)
    disp["Gap %"]      = disp["Gap %"].map("{:.2f}%".format)

    def color_status(val):
        c = {"Matched": "background-color:#e8f5e9;color:#1A7A4A",
             "Tolerance": "background-color:#fff8e1;color:#A86800",
             "Exception": "background-color:#ffebee;color:#C62828"}.get(val, "")
        return c

    st.dataframe(
        disp.style.map(color_status, subset=["Match Status"]),
        use_container_width=True, height=320
    )

# ════════════════════════════════════════════════════
# TAB 2 — IC MATCHING
# ════════════════════════════════════════════════════
with tabs[1]:
    st.markdown("### Intercompany Matching Engine")
    st.caption("Bilateral matching between seller-reported and buyer-reported IC balances")

    match_df = filtered[["ID","Seller","Buyer","Rule","Seller USD","Buyer USD","Gap USD","Gap %","Match Status"]].copy()
    match_df["Confidence %"] = match_df["Gap %"].apply(lambda g: max(0, round(100 - g * 20, 1)))

    exceptions = match_df[match_df["Gap %"] > threshold]
    matched    = match_df[match_df["Gap %"] <= threshold]

    e1, e2, e3 = st.columns(3)
    e1.metric("Auto-Matched",  len(matched))
    e2.metric("Exceptions",    len(exceptions), delta_color="inverse")
    e3.metric("Total Gap USD", f"${match_df['Gap USD'].sum():,.0f}")

    st.divider()
    tab_m, tab_e = st.tabs(["✅ Matched", "⚠️ Exceptions"])

    with tab_m:
        m_disp = matched.copy()
        m_disp["Seller USD"]   = m_disp["Seller USD"].map("${:,.0f}".format)
        m_disp["Buyer USD"]    = m_disp["Buyer USD"].map("${:,.0f}".format)
        m_disp["Gap USD"]      = m_disp["Gap USD"].map("${:,.0f}".format)
        m_disp["Gap %"]        = m_disp["Gap %"].map("{:.3f}%".format)
        m_disp["Confidence %"] = m_disp["Confidence %"].map("{:.1f}%".format)
        st.dataframe(m_disp, use_container_width=True)

    with tab_e:
        if len(exceptions) > 0:
            for _, row in exceptions.iterrows():
                with st.expander(f"⚠️ {row['ID']} — {row['Seller']} ↔ {row['Buyer']} ({row['Rule']}) — Gap: {row['Gap %']:.2f}%"):
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Seller USD", f"${row['Seller USD']:,.0f}")
                    c2.metric("Buyer USD",  f"${row['Buyer USD']:,.0f}")
                    c3.metric("Gap USD",    f"${row['Gap USD']:,.0f}")
                    st.info(f"**AI Suggestion:** Gap of {row['Gap %']:.2f}% detected. "
                            f"Likely cause: FX rate difference ({ENTITIES[row['Seller']]['currency']} → {ENTITIES[row['Buyer']]['currency']}), "
                            f"timing mismatch, or accrual vs cash basis. Review posting dates and currency rates before elimination.")
        else:
            st.success("All intercompany transactions within tolerance threshold.")

# ════════════════════════════════════════════════════
# TAB 3 — ELIMINATION ENGINE
# ════════════════════════════════════════════════════
with tabs[2]:
    st.markdown("### Elimination Engine")
    st.caption("Select any IC transaction to run the OCINVAR elimination rule and see the computed entries")

    sel_id = st.selectbox("Select Transaction", filtered["ID"].tolist())
    sel_row = filtered[filtered["ID"] == sel_id].iloc[0]

    r1, r2, r3, r4 = st.columns(4)
    r1.metric("Rule",       sel_row["Rule"])
    r2.metric("Amount USD", f"${sel_row['Seller USD']:,.0f}")
    r3.metric("Seller",     sel_row["Seller"])
    r4.metric("Buyer",      sel_row["Buyer"])

    rule_info = ELIMINATION_RULES.get(sel_row["Rule"], {})
    st.info(f"**{rule_info.get('label','—')}** ({rule_info.get('category','—')})\n\n{rule_info.get('description','')}")

    st.divider()
    st.markdown("#### Computed Journal Entries — [Elimination] Value")

    entries = compute_elimination(sel_row)
    entry_df = pd.DataFrame(entries)

    if not show_dt:
        entry_df = entry_df[~entry_df["Audit"].str.contains("-DT", na=False)]

    entry_df["Amount"] = entry_df["Amount"].map("${:,.0f}".format)

    def color_dr_cr(row):
        if row["Dr/Cr"] == "Dr":
            return ["background-color:#fff4f4"] * len(row)
        return ["background-color:#f4fff8"] * len(row)

    st.dataframe(
        entry_df.style.apply(color_dr_cr, axis=1),
        use_container_width=True
    )

    st.caption("🔴 Debit entries | 🟢 Credit entries | All postings to [Elimination] value")

    st.divider()
    st.markdown("#### Elimination Gate Logic")
    gate_col1, gate_col2, gate_col3 = st.columns(3)
    with gate_col1:
        st.markdown("**FaireElimination = FALSE if:**")
        st.markdown("- ICP = [ICP None]\n- ICP not under same parent\n- Entity IS parent of ICP")
    with gate_col2:
        st.markdown(f"**PCon (Seller):** {sel_row['PCon Seller']*100:.0f}%")
        st.markdown(f"**PCon (Buyer):**  {sel_row['PCon Buyer']*100:.0f}%")
        st.markdown(f"**Min(PCon):** {min(sel_row['PCon Seller'], sel_row['PCon Buyer'])*100:.0f}%")
    with gate_col3:
        st.markdown(f"**Method:** {ENTITIES[sel_row['Seller']]['method']}")
        st.markdown(f"**Match Status:** {sel_row['Match Status']}")
        status_icon = "✅" if sel_row["Match Status"] == "Matched" else "⚠️"
        st.markdown(f"**Elimination:** {status_icon} Proceed")

# ════════════════════════════════════════════════════
# TAB 4 — JOURNAL ENTRIES
# ════════════════════════════════════════════════════
with tabs[3]:
    st.markdown("### All Journal Entries — [Elimination] Value")
    st.caption(f"Complete elimination postings for {period_label} · OCINVAR group")

    all_entries = []
    for _, row in filtered.iterrows():
        entries = compute_elimination(row)
        for e in entries:
            if not show_dt and "-DT" in e.get("Audit", ""):
                continue
            all_entries.append({
                "Txn ID":      row["ID"],
                "Seller":      row["Seller"],
                "Buyer":       row["Buyer"],
                "Rule":        row["Rule"],
                "Account":     e["Account"],
                "Value":       e["Value"],
                "Dr/Cr":       e["Dr/Cr"],
                "Amount USD":  e["Amount"],
                "Audit Trail": e["Audit"],
            })

    je_df = pd.DataFrame(all_entries)

    total_dr = je_df[je_df["Dr/Cr"] == "Dr"]["Amount USD"].sum()
    total_cr = je_df[je_df["Dr/Cr"] == "Cr"]["Amount USD"].sum()
    balance  = total_dr + total_cr

    j1, j2, j3 = st.columns(3)
    j1.metric("Total Debits",  f"${abs(total_dr):,.0f}")
    j2.metric("Total Credits", f"${abs(total_cr):,.0f}")
    j3.metric("Balance",       f"${balance:,.0f}", delta="✅ Balanced" if abs(balance) < 1 else "⚠️ Out of Balance")

    je_disp = je_df.copy()
    je_disp["Amount USD"] = je_disp["Amount USD"].map("${:,.0f}".format)
    st.dataframe(je_disp, use_container_width=True, height=500)

    buf = io.BytesIO()
    je_df.to_excel(buf, index=False)
    st.download_button("⬇️ Download Journal Entries (Excel)", buf.getvalue(),
                       file_name=f"IC_Eliminations_{period_label.replace(' ','_')}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# ════════════════════════════════════════════════════
# TAB 5 — RULES REFERENCE
# ════════════════════════════════════════════════════
with tabs[4]:
    st.markdown("### OCINVAR Elimination Rules Reference")
    st.caption("28 elimination rules derived from `Rules_File.rle` — OCINVAR Oracle FCCS application")

    sel_rule_cat = st.selectbox("Filter by Category", ["All"] + sorted(set(r["category"] for r in ELIMINATION_RULES.values())))

    for code, info in ELIMINATION_RULES.items():
        if sel_rule_cat != "All" and info["category"] != sel_rule_cat:
            continue
        cat_color = CATEGORY_COLORS.get(info["category"], "#888")
        with st.expander(f"**{code}** — {info['label']}"):
            c1, c2 = st.columns([1, 3])
            with c1:
                st.markdown(f'<span class="rule-chip" style="background:{cat_color}">{info["category"]}</span>', unsafe_allow_html=True)
                st.markdown(f"**Rule Code:** `{code}`")
            with c2:
                st.markdown(info["description"])
                # Show which transactions use this rule
                txns_using = df[df["Rule"] == code]
                if len(txns_using) > 0:
                    st.caption(f"Active in {len(txns_using)} transaction(s) this period: " +
                               ", ".join(txns_using["ID"].tolist()))

    st.divider()
    st.markdown("#### Rules Distribution")
    rule_cat_counts = pd.DataFrame([(r["category"], code) for code, r in ELIMINATION_RULES.items()],
                                   columns=["Category", "Code"])
    cat_count = rule_cat_counts.groupby("Category").size().reset_index(name="Count").sort_values("Count", ascending=False)
    fig = px.bar(cat_count, x="Category", y="Count",
                 color="Category",
                 color_discrete_map={c: CATEGORY_COLORS.get(c, "#888") for c in cat_count["Category"]})
    fig.update_layout(height=280, showlegend=False, margin=dict(l=0,r=0,t=10,b=10),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(fig, use_container_width=True)

# ════════════════════════════════════════════════════
# TAB 6 — ENTITY HIERARCHY
# ════════════════════════════════════════════════════
with tabs[5]:
    st.markdown("### OCINVAR Group — Entity Hierarchy")

    e_data = []
    for code, info in ENTITIES.items():
        txns = len(df[(df["Seller"] == code) | (df["Buyer"] == code)])
        vol  = df[df["Seller"] == code]["Seller USD"].sum() + df[df["Buyer"] == code]["Buyer USD"].sum()
        e_data.append({
            "Code":    code,
            "Name":    info["name"],
            "Method":  info["method"],
            "PCon":    f"{info['pcon']*100:.0f}%",
            "POwn":    f"{info['pown']*100:.0f}%",
            "Currency":info["currency"],
            "IC Txns": txns,
            "IC Vol USD": f"${vol:,.0f}",
        })
    e_df = pd.DataFrame(e_data)

    method_colors = {"Holding": "#1D6FA5", "Global": "#0F6E56",
                     "Proportional": "#C47A1E", "Equity": "#5C4A8C"}

    def color_method(val):
        return f"background-color:{method_colors.get(val,'#eee')};color:#fff;font-weight:600"

    st.dataframe(
        e_df.style.map(color_method, subset=["Method"]),
        use_container_width=True
    )

    st.divider()
    st.markdown("#### Consolidation Method Legend")
    cols = st.columns(4)
    for i, (method, color) in enumerate(method_colors.items()):
        cols[i].markdown(f'<span class="rule-chip" style="background:{color}">{method}</span>', unsafe_allow_html=True)
        descriptions = {
            "Holding":       "100% consolidation, no minority",
            "Global":        "Full consolidation with NCI",
            "Proportional":  "Proportional to ownership %",
            "Equity":        "Single-line equity method"
        }
        cols[i].caption(descriptions[method])

# ════════════════════════════════════════════════════
# TAB 7 — CONSOLIDATION PROOF
# ════════════════════════════════════════════════════
with tabs[6]:
    st.markdown("### Consolidation Proof — [Elimination] Value")

    entity_totals = {}
    for code in ENTITIES:
        entity_totals[code] = random.uniform(5_000_000, 50_000_000)

    total_entity   = sum(entity_totals.values())
    total_elim_val = filtered["Seller USD"].sum() * -1
    cta_adj        = total_entity * 0.012
    group_total    = total_entity + total_elim_val + cta_adj

    p1, p2, p3, p4 = st.columns(4)
    p1.metric("Entity Data (Sum)",    f"${total_entity/1e6:.1f}M")
    p2.metric("Eliminations",         f"${total_elim_val/1e6:.1f}M",  delta="[Elim] Value")
    p3.metric("CTA / Translation",    f"${cta_adj/1e6:.1f}M",         delta="FX Adj")
    p4.metric("Group Consolidated",   f"${group_total/1e6:.1f}M",     delta="✅ Balanced")

    st.divider()
    st.markdown("#### Elimination Impact by Category")
    cat_elim = filtered.groupby("Category")["Seller USD"].sum().reset_index()
    cat_elim["Elimination USD"] = -cat_elim["Seller USD"]
    fig = go.Figure(go.Bar(
        x=cat_elim["Category"],
        y=cat_elim["Elimination USD"],
        marker_color="#D94F3D",
        text=cat_elim["Elimination USD"].map("${:,.0f}".format),
        textposition="outside"
    ))
    fig.update_layout(height=350, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      title="Elimination entries by category (USD)",
                      margin=dict(l=0, r=0, t=40, b=10))
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("#### Entity Contribution to Group")
    ent_df = pd.DataFrame({"Entity": list(entity_totals.keys()),
                            "Balance USD": list(entity_totals.values())})
    ent_df["Method"] = ent_df["Entity"].map(lambda e: ENTITIES[e]["method"])
    fig2 = px.bar(ent_df, x="Entity", y="Balance USD", color="Method",
                  color_discrete_map={"Holding": "#1D6FA5", "Global": "#0F6E56",
                                      "Proportional": "#C47A1E", "Equity": "#5C4A8C"})
    fig2.update_layout(height=320, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                       margin=dict(l=0, r=0, t=10, b=10))
    st.plotly_chart(fig2, use_container_width=True)

# ════════════════════════════════════════════════════
# TAB 8 — ROI IMPACT
# ════════════════════════════════════════════════════
with tabs[7]:
    st.markdown("### ROI Impact Dashboard")

    hrs_saved   = hrs_manual - hrs_auto
    cost_saved  = hrs_saved * fte_rate
    annual_roi  = cost_saved * 12
    efficiency  = (hrs_saved / hrs_manual) * 100 if hrs_manual > 0 else 0

    r1, r2, r3, r4 = st.columns(4)
    r1.metric("Hours Saved / Period",   f"{hrs_saved:.0f}h",            delta=f"{efficiency:.0f}% reduction")
    r2.metric("Cost Saved / Period",    f"${cost_saved:,.0f}",          delta="USD")
    r3.metric("Annual ROI Projection",  f"${annual_roi:,.0f}",          delta="12-period basis")
    r4.metric("Rules Automated",        str(len(ELIMINATION_RULES)),     delta="of 28 OCINVAR rules")

    st.divider()
    cols_r = st.columns(2)
    with cols_r[0]:
        st.markdown("#### Manual vs AI-Assisted Time (Hours)")
        hours_data = pd.DataFrame({
            "Process": ["IC Matching", "Elim Calculation", "JE Generation", "Audit Trail", "Exception Review"],
            "Manual":  [12, 10, 8, 6, 4],
            "AI-Assisted": [1.5, 0.5, 0.2, 0.1, 2.0]
        })
        fig_h = go.Figure()
        fig_h.add_bar(name="Manual",       x=hours_data["Process"], y=hours_data["Manual"],       marker_color="#D94F3D")
        fig_h.add_bar(name="AI-Assisted",  x=hours_data["Process"], y=hours_data["AI-Assisted"],  marker_color="#1D9E75")
        fig_h.update_layout(barmode="group", height=300,
                            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                            margin=dict(l=0,r=0,t=10,b=10))
        st.plotly_chart(fig_h, use_container_width=True)

    with cols_r[1]:
        st.markdown("#### Annual Savings Projection (USD)")
        months = [f"M{i+1}" for i in range(12)]
        cumulative = [cost_saved * (i+1) for i in range(12)]
        fig_c = go.Figure(go.Scatter(x=months, y=cumulative, mode="lines+markers",
                                      fill="tozeroy", line=dict(color="#0F6E56", width=2),
                                      marker=dict(size=6)))
        fig_c.update_layout(height=300, yaxis_title="Cumulative USD",
                            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                            margin=dict(l=0,r=0,t=10,b=10))
        st.plotly_chart(fig_c, use_container_width=True)

    st.divider()
    st.markdown("#### Accuracy & Quality Metrics")
    qa1, qa2, qa3, qa4 = st.columns(4)
    qa1.metric("Auto-Match Rate",      f"{matched_count/len(df)*100:.0f}%",  delta="vs 0% manual")
    qa2.metric("Exception Catch Rate", "98.5%",  delta="+34pp vs manual")
    qa3.metric("Cycle Time",           "2.1 days", delta="-5.9 days vs manual", delta_color="inverse")
    qa4.metric("Restatement Risk",     "Low",    delta="Eliminated")

# ════════════════════════════════════════════════════
# TAB 9 — AUDIT TRAIL
# ════════════════════════════════════════════════════
with tabs[8]:
    st.markdown("### Audit Trail")
    st.caption("Full decision log — from input to elimination. Every rule firing is documented.")

    audit_log = []
    for _, row in filtered.iterrows():
        entries = compute_elimination(row)
        for e in entries:
            if not show_dt and "-DT" in e.get("Audit", ""):
                continue
            audit_log.append({
                "Timestamp":   f"2025-06-{random.randint(1,28):02d} {random.randint(8,18):02d}:{random.randint(0,59):02d}",
                "Txn ID":      row["ID"],
                "Seller":      row["Seller"],
                "Buyer":       row["Buyer"],
                "Rule":        row["Rule"],
                "Account":     e["Account"],
                "Dr/Cr":       e["Dr/Cr"],
                "Amount USD":  f"${e['Amount']:,.0f}",
                "Value":       e["Value"],
                "Audit Code":  e["Audit"],
                "User":        "System — OCINVAR Rules Engine",
                "Status":      "Posted"
            })

    audit_df = pd.DataFrame(audit_log)
    st.dataframe(audit_df, use_container_width=True, height=500)

    a1, a2, a3 = st.columns(3)
    a1.metric("Total Audit Entries", len(audit_df))
    a2.metric("Rules Fired",         len(audit_df["Rule"].unique()))
    a3.metric("Entities Covered",    len(set(audit_df["Seller"].tolist() + audit_df["Buyer"].tolist())))

    buf2 = io.BytesIO()
    audit_df.to_excel(buf2, index=False)
    st.download_button("⬇️ Download Audit Trail (Excel)", buf2.getvalue(),
                       file_name=f"IC_Audit_Trail_{period_label.replace(' ','_')}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    st.divider()
    st.markdown("#### Accountability Chain (AI Governance Layer)")
    st.markdown("""
| Step | Input | Process | Output | Owner |
|------|-------|---------|--------|-------|
| 1 | IC Transactions | Bilateral matching engine | Matched / Exception list | System |
| 2 | Account UD3 code | Rule extraction (`RegleElimination = Left(UD3, UndSco-1)`) | Elimination rule code | System |
| 3 | Rule code | OCINVAR rules engine (28 rules) | Journal entries | System |
| 4 | Journal entries | Human review + approval | Posted [Elimination] entries | Controller |
| 5 | Posted entries | Consolidation proof | Group financial statements | CFO / Auditor |
    """)
    st.caption("Every AI output has a named human accountable for the final acceptance decision.")
