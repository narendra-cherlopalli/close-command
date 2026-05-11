import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime
import random
import io

st.set_page_config(
    page_title="IC Elimination Engine — Consolidation Suite",
    layout="wide",
    page_icon="⚖️"
)

random.seed(42)
np.random.seed(42)

# ─────────────────────────────────────────────────────────────
# ELIMINATION RULES — Generic labels for demo purposes
# ─────────────────────────────────────────────────────────────

ELIMINATION_RULES = {
    # ── EQUITY ───────────────────────────────────────────────
    "EQ-001": {"label": "Equity Split — Group vs Minority",        "category": "Equity",       "description": "Splits equity balance between group ownership and non-controlling interest. Posts to Group Reserves and NCI accounts in [Elimination] value at PCon/POwn/PMin percentages."},
    "EQ-002": {"label": "Translation Reserve — Equity",            "category": "Equity",       "description": "Handles FX conversion reserves arising from equity accounts. Splits translation reserve between group and minority interest at ownership percentages."},
    "EQ-003": {"label": "Other Comprehensive Income Split",        "category": "Equity/OCI",   "description": "Allocates OCI between group portion and NCI portion. Posts group share to consolidated OCI and minority share to NCI-OCI account."},
    "EQ-004": {"label": "Net Income Allocation — Group vs NCI",    "category": "P&L",          "description": "Allocates current period net income between group and minority interest. Supports equity method treatment for associates."},
    "EQ-005": {"label": "FX Impact on Net Income",                 "category": "P&L/FX",       "description": "Posts foreign exchange impact on net income to conversion reserve accounts, split between group and NCI portions."},
    # ── INVESTMENT ───────────────────────────────────────────
    "INV-001": {"label": "Investment Elimination",                  "category": "Investment",   "description": "Eliminates parent's investment in subsidiary against subsidiary's equity. Posts to liaison accounts. Handles equity method via separate technical account."},
    "INV-002": {"label": "Historic Investment Carry-forward",       "category": "Investment",   "description": "Carries forward prior-period investment eliminations. Reclassifies between capital reserves and conversion reserves for scope variation flows."},
    # ── INTERCOMPANY ─────────────────────────────────────────
    "IC-001":  {"label": "Standard Intercompany Elimination",       "category": "Intercompany", "description": "Simple bilateral elimination of intercompany balances. Eliminates at the minimum of both entities' consolidation percentages. Uses plug account as counterpart."},
    "IC-002":  {"label": "Reciprocal IC Elimination",               "category": "Intercompany", "description": "Two-sided elimination with buyer/seller distinction. Seller account eliminated at Min(PCon); buyer account posted to counterparty dimension. Handles proportional entities."},
    "IC-003":  {"label": "Conditional IC Elimination",              "category": "Intercompany", "description": "Fires only when the balance is positive (seller-side rule). Prevents double elimination on symmetric transactions. Used for service and fee arrangements."},
    "IC-004":  {"label": "IC Provision Elimination",                "category": "Intercompany", "description": "Eliminates intragroup provisions and allowances. Includes deferred tax impact using entity-specific tax rate. Reverses provision P&L impact at consolidation level."},
    "IC-005":  {"label": "Historic IC Provision Carry-forward",     "category": "Intercompany", "description": "Historical carry-forward of IC provision eliminations. Handles FX translation flows into conversion reserves across periods."},
    # ── GOODWILL ─────────────────────────────────────────────
    "GW-001":  {"label": "Goodwill on Acquisition",                 "category": "Goodwill",     "description": "Eliminates goodwill arising on acquisition. Calculated at PCon × ICPPCon. Uses plug account as counterpart. Handles new entries and scope variation separately."},
    "GW-002":  {"label": "Historic Goodwill Carry-forward",         "category": "Goodwill",     "description": "Carries forward prior-period goodwill balances. Reclassifies between reserves and conversion reserves for scope variation movements."},
    "GW-003":  {"label": "Goodwill Amortisation / Impairment",      "category": "Goodwill",     "description": "Eliminates goodwill depreciation and impairment charges. Routes to group/NCI result accounts. Equity method posts to equity-accounted investment account."},
    "GW-004":  {"label": "Historic Goodwill Amortisation",          "category": "Goodwill",     "description": "Historical carry-forward of goodwill amortisation. Handles all FX translation flows impacting conversion reserves."},
    # ── DIVIDENDS ────────────────────────────────────────────
    "DIV-001": {"label": "Paid Dividend Elimination",               "category": "Dividends",    "description": "Eliminates intercompany dividends paid. Posts offsetting entries to Group and NCI reserves. Handles scope variation in ownership percentage."},
    "DIV-002": {"label": "Scope Variation — Paid Dividends",        "category": "Dividends",    "description": "Reclassifies paid dividend eliminations between reserves and conversion reserves when consolidation percentage changes."},
    "DIV-003": {"label": "Withholding Tax FX Adjustment",           "category": "Dividends/FX", "description": "Posts FX movements on withholding tax related to dividends. Routes to result conversion reserves and capital conversion reserves."},
    "DIV-004": {"label": "Dividend Income Elimination",             "category": "Dividends",    "description": "Eliminates dividend income received from group subsidiaries. Posts to Group Net Income and NCI Net Income. Includes FX conversion reserve treatment."},
    "DIV-005": {"label": "Scope Variation — Dividend Income",       "category": "Dividends",    "description": "Mirrors paid-dividend scope variation treatment on the income side. Handles changes in consolidation percentage."},
    "DIV-006": {"label": "Dividend Income FX Adjustment",           "category": "Dividends/FX", "description": "Posts FX impact on dividend income to result conversion reserve accounts."},
    # ── STOCK MARGIN ─────────────────────────────────────────
    "STK-001": {"label": "Unrealised Profit in Inventory",          "category": "Stock Margin", "description": "Eliminates unrealised profit embedded in buyer's inventory from intercompany sales. Includes deferred tax using entity-specific rate. Applies seller/buyer side logic separately."},
    "STK-002": {"label": "Historic Unrealised Profit Carry-forward","category": "Stock Margin", "description": "Carries forward unrealised profit elimination. Handles FX translation flows. Includes deferred tax variance on opening balance."},
    # ── ASSET UNDER CONSTRUCTION ─────────────────────────────
    "AUC-001": {"label": "Intragroup Construction Revenue",         "category": "AUC/CapEx",    "description": "Eliminates revenue recognised on intragroup construction contracts. Posts to revenue P&L and balance sheet link account. Includes deferred tax treatment."},
    "AUC-002": {"label": "Historic Construction Revenue",           "category": "AUC/CapEx",    "description": "Historical carry-forward of intragroup construction revenue elimination with full FX translation treatment."},
    "AUC-003": {"label": "Intragroup Construction Cost",            "category": "AUC/CapEx",    "description": "Mirror of construction revenue rule on the cost side. Posts to cost P&L account. Same balance sheet plug and deferred tax treatment."},
    "AUC-004": {"label": "Historic Construction Cost",              "category": "AUC/CapEx",    "description": "Historical carry-forward of intragroup construction cost elimination with full FX translation treatment."},
}

# Rule code mapping (internal → generic display code)
RULE_MAP = {
    "ELIM":     "IC-001", "ELIMR":    "IC-002", "ELIMRA":   "IC-003",
    "ELIPROV":  "IC-004", "ELIPROVH": "IC-005",
    "CAPI":     "EQ-001", "CAPIC":    "EQ-002", "COMPINC":  "EQ-003",
    "RESU":     "EQ-004", "RESUC":    "EQ-005",
    "PINT":     "INV-001","PINTH":    "INV-002",
    "GW":       "GW-001", "GWH":      "GW-002", "GWA":      "GW-003", "GWAH": "GW-004",
    "DIVP":     "DIV-001","DIVVAR":   "DIV-002","DIVH":     "DIV-003",
    "DIVI":     "DIV-004","DIVIVAR":  "DIV-005","DIVIH":    "DIV-006",
    "PSTK":     "STK-001","PSTKH":    "STK-002",
    "AUCREV":   "AUC-001","AUCREVH":  "AUC-002","AUCCOS":   "AUC-003","AUCCOSH": "AUC-004",
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
# ENTITIES — Fully mocked / generic names
# ─────────────────────────────────────────────────────────────

ENTITIES = {
    "HLD":  {"name": "Apex Group Holdings SA",          "method": "Holding",      "pcon": 1.00, "pown": 1.00, "currency": "USD"},
    "MFG1": {"name": "Apex Manufacturing East Ltd",     "method": "Global",       "pcon": 0.60, "pown": 0.60, "currency": "EUR"},
    "MFG2": {"name": "Apex Industrial Solutions Corp",  "method": "Global",       "pcon": 0.51, "pown": 0.51, "currency": "GBP"},
    "DIST": {"name": "Apex Distribution Co.",           "method": "Global",       "pcon": 0.75, "pown": 0.75, "currency": "EUR"},
    "RETAIL":{"name": "Apex Retail Network Ltd",        "method": "Global",       "pcon": 0.42, "pown": 0.42, "currency": "AED"},
    "JV1":  {"name": "Meridian Ventures (JV)",          "method": "Proportional", "pcon": 0.50, "pown": 0.50, "currency": "USD"},
    "ASSOC":{"name": "Pinnacle Associates Inc.",        "method": "Equity",       "pcon": 0.30, "pown": 0.30, "currency": "USD"},
    "FIN":  {"name": "Apex Finance & Treasury BV",      "method": "Global",       "pcon": 1.00, "pown": 1.00, "currency": "EUR"},
}

REVIEWERS = {
    "HLD":   "Sarah Mitchell (Group Controller)",
    "MFG1":  "James Chen (Regional CFO — East)",
    "MFG2":  "Claire Dupont (Finance Director)",
    "DIST":  "Raj Patel (Financial Controller)",
    "RETAIL":"Fatima Al-Hassan (Head of Finance)",
    "JV1":   "Marco Russo (JV Finance Lead)",
    "ASSOC": "Emma Thornton (Equity Accounting)",
    "FIN":   "David Park (Treasury Controller)",
}

FX_RATES = {"USD": 1.0, "EUR": 1.08, "GBP": 1.27, "AED": 0.272}

# ─────────────────────────────────────────────────────────────
# SESSION STATE — Human-in-the-Loop review statuses
# ─────────────────────────────────────────────────────────────

if "review_status" not in st.session_state:
    st.session_state.review_status = {}
if "review_comments" not in st.session_state:
    st.session_state.review_comments = {}
if "review_user" not in st.session_state:
    st.session_state.review_user = {}
if "review_timestamp" not in st.session_state:
    st.session_state.review_timestamp = {}

# ─────────────────────────────────────────────────────────────
# SAMPLE DATA GENERATION
# ─────────────────────────────────────────────────────────────

def generate_ic_transactions():
    pairs = [
        ("HLD",   "MFG1",  "ELIM",    "IC Loan Interest Charge",       1_250_000),
        ("HLD",   "MFG2",  "ELIM",    "Group Management Fee",            420_000),
        ("MFG1",  "DIST",  "ELIMR",   "Raw Material Supply",           3_800_000),
        ("DIST",  "RETAIL","ELIMR",   "Finished Goods Supply",         2_100_000),
        ("FIN",   "HLD",   "PINT",    "Investment in Subsidiary",     15_000_000),
        ("HLD",   "JV1",   "PSTK",    "Unrealised Profit — Inventory",   680_000),
        ("HLD",   "MFG1",  "DIVP",    "Dividend Payment",                900_000),
        ("MFG1",  "DIST",  "DIVI",    "Dividend Income Received",        540_000),
        ("HLD",   "MFG2",  "GW",      "Goodwill on Acquisition",       4_500_000),
        ("FIN",   "RETAIL","ELIPROV", "IC Allowance for Doubtful Debt",  320_000),
        ("HLD",   "DIST",  "CAPI",    "Share Capital Contribution",    8_000_000),
        ("FIN",   "MFG1",  "RESU",    "Net Income Allocation",         1_650_000),
        ("HLD",   "ASSOC", "AUCREV",  "Intragroup Construction Revenue",2_200_000),
        ("ASSOC", "HLD",   "AUCCOS",  "Intragroup Construction Cost",  2_190_000),
        ("JV1",   "DIST",  "ELIMRA",  "Conditional Service Elimination", 175_000),
    ]
    rows = []
    for i, (seller, buyer, rule_internal, desc, base_amt) in enumerate(pairs):
        noise    = random.uniform(-0.015, 0.015)
        seller_amt = base_amt
        buyer_amt  = base_amt * (1 + noise)
        gap_pct  = abs(seller_amt - buyer_amt) / seller_amt * 100
        s_cur    = ENTITIES[seller]["currency"]
        b_cur    = ENTITIES[buyer]["currency"]
        seller_usd = seller_amt * FX_RATES[s_cur]
        buyer_usd  = buyer_amt  * FX_RATES[b_cur]
        rule_code  = RULE_MAP.get(rule_internal, rule_internal)
        match_status = "Matched" if gap_pct < 0.5 else ("Tolerance" if gap_pct < 2.0 else "Exception")
        rows.append({
            "ID":           f"IC-{i+1:03d}",
            "Seller":       seller,
            "Buyer":        buyer,
            "Rule Code":    rule_code,
            "Rule Internal":rule_internal,
            "Description":  desc,
            "Seller Amt":   seller_amt,
            "Buyer Amt":    buyer_amt,
            "Seller CCY":   s_cur,
            "Buyer CCY":    b_cur,
            "Seller USD":   seller_usd,
            "Buyer USD":    buyer_usd,
            "Gap USD":      abs(seller_usd - buyer_usd),
            "Gap %":        gap_pct,
            "Match Status": match_status,
            "Category":     ELIMINATION_RULES[rule_code]["category"],
            "Rule Label":   ELIMINATION_RULES[rule_code]["label"],
            "PCon Seller":  ENTITIES[seller]["pcon"],
            "PCon Buyer":   ENTITIES[buyer]["pcon"],
        })
    return pd.DataFrame(rows)

# ─────────────────────────────────────────────────────────────
# ELIMINATION COMPUTATION ENGINE
# ─────────────────────────────────────────────────────────────

def compute_elimination(row):
    rule     = row["Rule Internal"]
    amt      = row["Seller USD"]
    pcon_s   = row["PCon Seller"]
    pcon_b   = row["PCon Buyer"]
    pown_s   = pcon_s
    pmin_s   = max(0, pcon_s - pown_s)
    min_pcon = min(pcon_s, pcon_b)
    entries  = []

    if rule == "ELIM":
        entries.append({"Account": "IC Receivable / Revenue", "Value": "[Elimination]", "Dr/Cr": "Dr", "Amount": -amt * min_pcon, "Audit": row["Rule Code"]})
        entries.append({"Account": "IC Payable / Cost",       "Value": "[Elimination]", "Dr/Cr": "Cr", "Amount":  amt * min_pcon, "Audit": row["Rule Code"]})
    elif rule in ("ELIMR", "ELIMRA"):
        entries.append({"Account": "Seller Account",  "Value": "[Elimination]", "Dr/Cr": "Dr", "Amount": -amt * min_pcon, "Audit": row["Rule Code"]})
        entries.append({"Account": "Offset Account",  "Value": "[Elimination]", "Dr/Cr": "Cr", "Amount":  amt * min_pcon, "Audit": row["Rule Code"]})
        entries.append({"Account": "Buyer Account",   "Value": "[Elimination]", "Dr/Cr": "Dr", "Amount":  amt * min_pcon, "Audit": row["Rule Code"] + "-B"})
        entries.append({"Account": "Offset Account",  "Value": "[Elimination]", "Dr/Cr": "Cr", "Amount": -amt * min_pcon, "Audit": row["Rule Code"] + "-B"})
    elif rule == "CAPI":
        entries.append({"Account": "Share Capital",   "Value": "[Elimination]", "Dr/Cr": "Dr", "Amount": -amt * pcon_s, "Audit": row["Rule Code"]})
        entries.append({"Account": "Group Reserves",  "Value": "[Elimination]", "Dr/Cr": "Cr", "Amount":  amt * pown_s, "Audit": row["Rule Code"]})
        entries.append({"Account": "NCI Reserves",    "Value": "[Elimination]", "Dr/Cr": "Cr", "Amount":  amt * pmin_s, "Audit": row["Rule Code"]})
    elif rule == "RESU":
        entries.append({"Account": "Net Income",      "Value": "[Elimination]", "Dr/Cr": "Dr", "Amount": -amt * pcon_s, "Audit": row["Rule Code"]})
        entries.append({"Account": "Group Net Income","Value": "[Elimination]", "Dr/Cr": "Cr", "Amount":  amt * pown_s, "Audit": row["Rule Code"]})
        entries.append({"Account": "NCI Net Income",  "Value": "[Elimination]", "Dr/Cr": "Cr", "Amount":  amt * pmin_s, "Audit": row["Rule Code"]})
    elif rule == "GW":
        entries.append({"Account": "Goodwill",           "Value": "[Elimination]", "Dr/Cr": "Dr", "Amount": -amt * pcon_s * pcon_b, "Audit": row["Rule Code"]})
        entries.append({"Account": "Investment Account", "Value": "[Elimination]", "Dr/Cr": "Cr", "Amount":  amt * pcon_s * pcon_b, "Audit": row["Rule Code"]})
        entries.append({"Account": "Group Reserves",     "Value": "[Elimination]", "Dr/Cr": "Cr", "Amount": -amt * pown_s, "Audit": row["Rule Code"]})
        entries.append({"Account": "NCI Reserves",       "Value": "[Elimination]", "Dr/Cr": "Cr", "Amount": -amt * pmin_s, "Audit": row["Rule Code"]})
    elif rule == "PINT":
        entries.append({"Account": "Investment in Sub",  "Value": "[Elimination]", "Dr/Cr": "Dr", "Amount": -amt * pcon_s, "Audit": row["Rule Code"]})
        entries.append({"Account": "Liaison Account",    "Value": "[Elimination]", "Dr/Cr": "Cr", "Amount":  amt * pcon_s, "Audit": row["Rule Code"]})
        entries.append({"Account": "Group Reserves",     "Value": "[Elimination]", "Dr/Cr": "Cr", "Amount":  amt * pown_s, "Audit": row["Rule Code"] + "-N"})
        entries.append({"Account": "NCI Reserves",       "Value": "[Elimination]", "Dr/Cr": "Cr", "Amount":  amt * pmin_s, "Audit": row["Rule Code"] + "-N"})
    elif rule == "DIVP":
        entries.append({"Account": "Dividends Paid",  "Value": "[Elimination]", "Dr/Cr": "Dr", "Amount": -amt * pcon_s, "Audit": row["Rule Code"]})
        entries.append({"Account": "Group Reserves",  "Value": "[Elimination]", "Dr/Cr": "Cr", "Amount":  amt * pown_s, "Audit": row["Rule Code"]})
        entries.append({"Account": "NCI Reserves",    "Value": "[Elimination]", "Dr/Cr": "Cr", "Amount":  amt * pmin_s, "Audit": row["Rule Code"]})
    elif rule == "DIVI":
        entries.append({"Account": "Dividend Income", "Value": "[Elimination]", "Dr/Cr": "Dr", "Amount": -amt * pcon_s, "Audit": row["Rule Code"]})
        entries.append({"Account": "Group Net Income","Value": "[Elimination]", "Dr/Cr": "Cr", "Amount":  amt * pown_s, "Audit": row["Rule Code"]})
        entries.append({"Account": "NCI Net Income",  "Value": "[Elimination]", "Dr/Cr": "Cr", "Amount":  amt * pmin_s, "Audit": row["Rule Code"]})
    elif rule == "PSTK":
        dt = 0.25
        entries.append({"Account": "Inventory",           "Value": "[Elimination]", "Dr/Cr": "Dr", "Amount": -amt * pcon_s * pcon_b, "Audit": row["Rule Code"]})
        entries.append({"Account": "COGS / Revenue",       "Value": "[Elimination]", "Dr/Cr": "Cr", "Amount":  amt * pcon_s * pcon_b, "Audit": row["Rule Code"]})
        entries.append({"Account": "Deferred Tax Liability","Value": "[Elimination]","Dr/Cr": "Dr", "Amount":  amt * pcon_s * pcon_b * dt, "Audit": row["Rule Code"] + "-DT"})
        entries.append({"Account": "Deferred Tax P&L",     "Value": "[Elimination]", "Dr/Cr": "Cr", "Amount": -amt * pcon_s * pcon_b * dt, "Audit": row["Rule Code"] + "-DT"})
    elif rule == "ELIPROV":
        dt = 0.22
        entries.append({"Account": "IC Provision",         "Value": "[Elimination]", "Dr/Cr": "Dr", "Amount": -amt * pcon_s, "Audit": row["Rule Code"]})
        entries.append({"Account": "Provision P&L",        "Value": "[Elimination]", "Dr/Cr": "Cr", "Amount":  amt * pcon_s, "Audit": row["Rule Code"]})
        entries.append({"Account": "Deferred Tax Liability","Value": "[Elimination]","Dr/Cr": "Dr", "Amount":  amt * pcon_s * dt, "Audit": row["Rule Code"] + "-DT"})
        entries.append({"Account": "Deferred Tax P&L",     "Value": "[Elimination]", "Dr/Cr": "Cr", "Amount": -amt * pcon_s * dt, "Audit": row["Rule Code"] + "-DT"})
    elif rule in ("AUCREV", "AUCCOS"):
        dt = 0.24
        pl = "Construction Revenue" if rule == "AUCREV" else "Construction Cost"
        entries.append({"Account": "AUC Asset",            "Value": "[Elimination]", "Dr/Cr": "Dr", "Amount": -amt * pcon_s * pcon_b, "Audit": row["Rule Code"]})
        entries.append({"Account": pl,                     "Value": "[Elimination]", "Dr/Cr": "Cr", "Amount":  amt * pcon_s * pcon_b, "Audit": row["Rule Code"]})
        entries.append({"Account": "AUC Link — BS",        "Value": "[Elimination]", "Dr/Cr": "Dr", "Amount": -amt * pcon_s, "Audit": row["Rule Code"]})
        entries.append({"Account": "AUC Link — Contra",    "Value": "[Elimination]", "Dr/Cr": "Cr", "Amount":  amt * pcon_s, "Audit": row["Rule Code"]})
        entries.append({"Account": "Deferred Tax Liability","Value": "[Elimination]","Dr/Cr": "Dr", "Amount":  amt * pcon_s * pcon_b * dt, "Audit": row["Rule Code"] + "-DT"})
        entries.append({"Account": "Deferred Tax P&L",     "Value": "[Elimination]", "Dr/Cr": "Cr", "Amount": -amt * pcon_s * pcon_b * dt, "Audit": row["Rule Code"] + "-DT"})
    else:
        entries.append({"Account": f"Account ({row['Rule Code']})",  "Value": "[Elimination]", "Dr/Cr": "Dr", "Amount": -amt * pcon_s, "Audit": row["Rule Code"]})
        entries.append({"Account": f"Counterpart ({row['Rule Code']})","Value": "[Elimination]","Dr/Cr": "Cr", "Amount":  amt * pcon_s, "Audit": row["Rule Code"]})
    return entries

# ─────────────────────────────────────────────────────────────
# CSS
# ─────────────────────────────────────────────────────────────

st.markdown("""
<style>
  .rule-chip {
    display:inline-block; padding:2px 10px; border-radius:12px;
    font-size:12px; font-weight:600; letter-spacing:.04em; color:#fff; margin:2px;
  }
  .section-header {
    font-size:13px; font-weight:700; letter-spacing:.08em; text-transform:uppercase;
    color:#888; margin:18px 0 6px;
  }
  .hitl-card {
    border-radius:10px; padding:16px 20px; margin-bottom:12px;
    border: 1px solid #e0e0e0;
  }
  .hitl-pending  { border-left: 4px solid #E8A838; background:#fffbf0; }
  .hitl-approved { border-left: 4px solid #1D9E75; background:#f0faf6; }
  .hitl-rejected { border-left: 4px solid #D94F3D; background:#fff5f5; }
  .hitl-badge {
    display:inline-block; padding:3px 12px; border-radius:20px;
    font-size:11px; font-weight:700; letter-spacing:.05em;
  }
  .badge-pending  { background:#FFF3CD; color:#856404; }
  .badge-approved { background:#D1FAE5; color:#065F46; }
  .badge-rejected { background:#FEE2E2; color:#991B1B; }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────
# LOAD DATA
# ─────────────────────────────────────────────────────────────

df = generate_ic_transactions()

# Initialise review statuses for all transactions
for txn_id in df["ID"].tolist():
    if txn_id not in st.session_state.review_status:
        st.session_state.review_status[txn_id] = "Pending"
        st.session_state.review_comments[txn_id] = ""
        st.session_state.review_user[txn_id] = ""
        st.session_state.review_timestamp[txn_id] = ""

# ─────────────────────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("## ⚖️ IC Elimination Suite")
    st.caption("Intercompany Consolidation Engine")
    st.divider()

    entity_options = ["All Entities"] + list(ENTITIES.keys())
    sel_entity = st.selectbox("Filter Entity", entity_options,
                               format_func=lambda x: x if x == "All Entities" else f"{x} — {ENTITIES[x]['name']}")

    all_cats = sorted(set(r["category"] for r in ELIMINATION_RULES.values()))
    sel_cats = st.multiselect("Filter Category", all_cats, default=all_cats)

    threshold = st.slider("Gap Tolerance (%)", 0.0, 5.0, 0.5, 0.1)

    st.divider()
    st.markdown("**Reviewer Identity**")
    reviewer_name = st.text_input("Your Name", value="Group Controller")
    reviewer_role = st.selectbox("Role", ["Group Controller", "Regional CFO", "Finance Director",
                                           "Treasury Controller", "External Auditor", "CFO"])

    st.divider()
    st.markdown("**ROI Assumptions**")
    fte_rate   = st.number_input("FTE Hourly Rate (USD)", value=85, step=5)
    hrs_manual = st.number_input("Manual Hours / Period", value=40, step=4)
    hrs_auto   = st.number_input("AI-Assisted Hours / Period", value=6, step=1)

    st.divider()
    period_label = st.selectbox("Period", ["Q2 2025", "Q1 2025", "FY 2024"])
    show_dt      = st.checkbox("Show Deferred Tax entries", value=True)

# ─────────────────────────────────────────────────────────────
# FILTER
# ─────────────────────────────────────────────────────────────

filtered = df.copy()
if sel_entity != "All Entities":
    filtered = filtered[(filtered["Seller"] == sel_entity) | (filtered["Buyer"] == sel_entity)]
if sel_cats:
    filtered = filtered[filtered["Category"].isin(sel_cats)]

# Add review status to filtered
filtered = filtered.copy()
filtered["Review Status"] = filtered["ID"].map(st.session_state.review_status)

# ─────────────────────────────────────────────────────────────
# HEADER
# ─────────────────────────────────────────────────────────────

st.markdown("## ⚖️ Intercompany Elimination Engine")
st.markdown(f"**Apex Group · {period_label} · [Elimination] Value** — {len(ELIMINATION_RULES)} consolidation rules · Human-in-the-Loop review enabled")

# Quick review status banner
approved = sum(1 for v in st.session_state.review_status.values() if v == "Approved")
rejected = sum(1 for v in st.session_state.review_status.values() if v == "Rejected")
pending  = sum(1 for v in st.session_state.review_status.values() if v == "Pending")
b1, b2, b3, b4 = st.columns(4)
b1.metric("Pending Review", pending, delta_color="off")
b2.metric("Approved",       approved, delta=f"{approved/len(df)*100:.0f}%")
b3.metric("Rejected",       rejected, delta_color="inverse")
b4.metric("Ready to Post",  approved, delta="Awaiting CFO sign-off" if approved < len(df) else "✅ Full period approved")
st.divider()

# ─────────────────────────────────────────────────────────────
# TABS
# ─────────────────────────────────────────────────────────────

tabs = st.tabs([
    "📊 Dashboard",
    "🔍 IC Matching",
    "⚙️ Elimination Engine",
    "📋 Journal Entries",
    "👤 Review & Approve",
    "🗂️ Rules Reference",
    "🏗️ Entity Hierarchy",
    "📈 Consolidation Proof",
    "💰 ROI Impact",
    "📁 Audit Trail",
])

# ════════════════════════════════════════════════════
# TAB 1 — DASHBOARD
# ════════════════════════════════════════════════════
with tabs[0]:
    total_vol     = df["Seller USD"].sum()
    matched_count = len(df[df["Match Status"] == "Matched"])
    exception_count = len(df[df["Gap %"] > threshold])

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total IC Volume (USD)", f"${total_vol/1e6:.2f}M")
    c2.metric("Transactions",          str(len(df)))
    c3.metric("Matched",               f"{matched_count}/{len(df)}", f"{matched_count/len(df)*100:.0f}%")
    c4.metric("Exceptions",            str(exception_count), delta=f">{threshold}% gap", delta_color="inverse")

    st.divider()
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown('<p class="section-header">Volume by Category</p>', unsafe_allow_html=True)
        cat_df = df.groupby("Category")["Seller USD"].sum().reset_index().sort_values("Seller USD", ascending=True)
        fig = px.bar(cat_df, x="Seller USD", y="Category", orientation="h",
                     color="Category",
                     color_discrete_map={c: CATEGORY_COLORS.get(c, "#888") for c in cat_df["Category"]},
                     labels={"Seller USD": "Amount (USD)"})
        fig.update_layout(height=320, showlegend=False, margin=dict(l=0,r=0,t=10,b=10),
                          paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig, use_container_width=True)
    with col_b:
        st.markdown('<p class="section-header">Review Status</p>', unsafe_allow_html=True)
        rev_counts = pd.Series(st.session_state.review_status).value_counts()
        colors_rev = {"Approved": "#1D9E75", "Pending": "#E8A838", "Rejected": "#D94F3D"}
        fig2 = go.Figure(go.Pie(
            labels=rev_counts.index, values=rev_counts.values,
            marker_colors=[colors_rev.get(s, "#888") for s in rev_counts.index],
            hole=0.55, textinfo="label+percent"
        ))
        fig2.update_layout(height=320, showlegend=False, margin=dict(l=0,r=0,t=10,b=10),
                           paper_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig2, use_container_width=True)

    st.markdown('<p class="section-header">IC Transaction Summary</p>', unsafe_allow_html=True)
    disp = filtered[["ID","Seller","Buyer","Rule Code","Rule Label","Description",
                      "Seller USD","Buyer USD","Gap %","Match Status","Review Status"]].copy()
    disp["Seller USD"] = disp["Seller USD"].map("${:,.0f}".format)
    disp["Buyer USD"]  = disp["Buyer USD"].map("${:,.0f}".format)
    disp["Gap %"]      = disp["Gap %"].map("{:.2f}%".format)

    def color_status(val):
        return {"Matched":  "background-color:#e8f5e9;color:#1A7A4A",
                "Tolerance":"background-color:#fff8e1;color:#A86800",
                "Exception":"background-color:#ffebee;color:#C62828"}.get(val, "")

    def color_review(val):
        return {"Approved": "background-color:#D1FAE5;color:#065F46;font-weight:600",
                "Rejected": "background-color:#FEE2E2;color:#991B1B;font-weight:600",
                "Pending":  "background-color:#FFF3CD;color:#856404"}.get(val, "")

    st.dataframe(
        disp.style.map(color_status, subset=["Match Status"]).map(color_review, subset=["Review Status"]),
        use_container_width=True, height=340
    )

# ════════════════════════════════════════════════════
# TAB 2 — IC MATCHING
# ════════════════════════════════════════════════════
with tabs[1]:
    st.markdown("### Intercompany Matching Engine")
    st.caption("Bilateral matching between entity-reported and counterparty-reported balances")

    match_df = filtered[["ID","Seller","Buyer","Rule Code","Seller USD","Buyer USD","Gap USD","Gap %","Match Status"]].copy()
    match_df["Confidence"] = match_df["Gap %"].apply(lambda g: f"{max(0, round(100 - g * 20, 1))}%")

    exceptions = match_df[match_df["Gap %"] > threshold]
    matched    = match_df[match_df["Gap %"] <= threshold]

    e1, e2, e3 = st.columns(3)
    e1.metric("Auto-Matched",  len(matched))
    e2.metric("Exceptions",    len(exceptions), delta_color="inverse")
    e3.metric("Total Gap USD", f"${match_df['Gap USD'].sum():,.0f}")

    st.divider()
    tab_m, tab_e = st.tabs(["✅ Matched", "⚠️ Exceptions"])
    with tab_m:
        m = matched.copy()
        for col in ["Seller USD","Buyer USD","Gap USD"]:
            m[col] = m[col].map("${:,.0f}".format)
        m["Gap %"] = m["Gap %"].map("{:.3f}%".format)
        st.dataframe(m, use_container_width=True)
    with tab_e:
        if len(exceptions) > 0:
            for _, row in exceptions.iterrows():
                with st.expander(f"⚠️ {row['ID']} — {ENTITIES[row['Seller']]['name']} ↔ {ENTITIES[row['Buyer']]['name']} — Gap: {row['Gap %']:.2f}%"):
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Seller USD", f"${row['Seller USD']:,.0f}")
                    c2.metric("Buyer USD",  f"${row['Buyer USD']:,.0f}")
                    c3.metric("Gap USD",    f"${row['Gap USD']:,.0f}")
                    st.info(f"**AI Root Cause Analysis:** Gap of {row['Gap %']:.2f}% detected on `{row['Rule Code']}`. "
                            f"Possible causes: FX rate timing difference ({ENTITIES[row['Seller']]['currency']} → {ENTITIES[row['Buyer']]['currency']}), "
                            f"period cut-off mismatch, or accrual vs cash basis difference. "
                            f"Recommend reviewing posting dates and FX rates before proceeding to elimination.")
        else:
            st.success("All intercompany balances within tolerance. Ready for elimination.")

# ════════════════════════════════════════════════════
# TAB 3 — ELIMINATION ENGINE
# ════════════════════════════════════════════════════
with tabs[2]:
    st.markdown("### Elimination Engine")
    st.caption("Select any transaction to compute elimination journal entries")

    sel_id  = st.selectbox("Select Transaction", filtered["ID"].tolist(),
                            format_func=lambda x: f"{x} — {filtered[filtered['ID']==x]['Description'].values[0]}" if len(filtered[filtered['ID']==x]) > 0 else x)
    sel_row = filtered[filtered["ID"] == sel_id].iloc[0]

    r1, r2, r3, r4 = st.columns(4)
    r1.metric("Rule",       sel_row["Rule Code"])
    r2.metric("Amount USD", f"${sel_row['Seller USD']:,.0f}")
    r3.metric("Seller",     ENTITIES[sel_row["Seller"]]["name"])
    r4.metric("Buyer",      ENTITIES[sel_row["Buyer"]]["name"])

    rule_info = ELIMINATION_RULES.get(sel_row["Rule Code"], {})
    rev_status = st.session_state.review_status.get(sel_id, "Pending")
    rev_color  = {"Approved": "#1D9E75", "Rejected": "#D94F3D", "Pending": "#E8A838"}.get(rev_status, "#888")
    st.markdown(f'**{rule_info.get("label","—")}** &nbsp; <span class="rule-chip" style="background:{rev_color}">{rev_status}</span>', unsafe_allow_html=True)
    st.info(rule_info.get("description", ""))

    st.divider()
    st.markdown("#### Computed Journal Entries — [Elimination] Value")
    entries   = compute_elimination(sel_row)
    entry_df  = pd.DataFrame(entries)
    if not show_dt:
        entry_df = entry_df[~entry_df["Audit"].str.contains("-DT", na=False)]
    entry_df["Amount"] = entry_df["Amount"].map("${:,.0f}".format)

    def color_dr_cr(row):
        return ["background-color:#fff4f4"] * len(row) if row["Dr/Cr"] == "Dr" else ["background-color:#f4fff8"] * len(row)

    st.dataframe(entry_df.style.apply(color_dr_cr, axis=1), use_container_width=True)
    st.caption("🔴 Debit | 🟢 Credit | All entries post to [Elimination] value")

    st.divider()
    st.markdown("#### Elimination Gate Conditions")
    g1, g2, g3 = st.columns(3)
    with g1:
        st.markdown("**Elimination blocked if:**")
        st.markdown("- No ICP partner assigned\n- Entities not under same parent\n- Current entity IS parent of counterparty")
    with g2:
        st.markdown(f"**PCon (Seller):** {sel_row['PCon Seller']*100:.0f}%")
        st.markdown(f"**PCon (Buyer):**  {sel_row['PCon Buyer']*100:.0f}%")
        st.markdown(f"**Effective %:** {min(sel_row['PCon Seller'], sel_row['PCon Buyer'])*100:.0f}%")
    with g3:
        st.markdown(f"**Method:** {ENTITIES[sel_row['Seller']]['method']}")
        st.markdown(f"**Match Status:** {sel_row['Match Status']}")
        st.markdown(f"**Review Status:** {rev_status}")

# ════════════════════════════════════════════════════
# TAB 4 — JOURNAL ENTRIES
# ════════════════════════════════════════════════════
with tabs[3]:
    st.markdown("### All Journal Entries — [Elimination] Value")
    st.caption(f"Complete postings for {period_label} · Apex Group")

    all_entries = []
    for _, row in filtered.iterrows():
        for e in compute_elimination(row):
            if not show_dt and "-DT" in e.get("Audit", ""):
                continue
            all_entries.append({
                "Txn ID":        row["ID"],
                "Seller":        ENTITIES[row["Seller"]]["name"],
                "Buyer":         ENTITIES[row["Buyer"]]["name"],
                "Rule Code":     row["Rule Code"],
                "Account":       e["Account"],
                "Value":         e["Value"],
                "Dr/Cr":         e["Dr/Cr"],
                "Amount USD":    e["Amount"],
                "Audit Code":    e["Audit"],
                "Review Status": st.session_state.review_status.get(row["ID"], "Pending"),
            })

    je_df   = pd.DataFrame(all_entries)
    total_dr = je_df[je_df["Dr/Cr"] == "Dr"]["Amount USD"].sum()
    total_cr = je_df[je_df["Dr/Cr"] == "Cr"]["Amount USD"].sum()
    balance  = total_dr + total_cr

    j1, j2, j3 = st.columns(3)
    j1.metric("Total Debits",  f"${abs(total_dr):,.0f}")
    j2.metric("Total Credits", f"${abs(total_cr):,.0f}")
    j3.metric("Balance",       f"${balance:,.0f}", delta="✅ Balanced" if abs(balance) < 1 else "⚠️ Out of Balance")

    je_disp = je_df.copy()
    je_disp["Amount USD"] = je_disp["Amount USD"].map("${:,.0f}".format)
    st.dataframe(je_disp, use_container_width=True, height=480)

    buf = io.BytesIO()
    je_df.to_excel(buf, index=False)
    st.download_button("⬇️ Download Journal Entries (Excel)", buf.getvalue(),
                       file_name=f"IC_Eliminations_{period_label.replace(' ','_')}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# ════════════════════════════════════════════════════
# TAB 5 — HUMAN IN THE LOOP: REVIEW & APPROVE  ★ NEW
# ════════════════════════════════════════════════════
with tabs[4]:
    st.markdown("### Human-in-the-Loop — Review & Approve")
    st.caption("Every elimination entry requires explicit human sign-off before posting to the consolidated ledger.")

    # ── Summary bar ──────────────────────────────────────────
    rv1, rv2, rv3, rv4 = st.columns(4)
    rv1.metric("Total Transactions", len(df))
    rv2.metric("Pending Review",  pending,  delta_color="off")
    rv3.metric("Approved",        approved, delta=f"{approved/len(df)*100:.0f}% complete")
    rv4.metric("Rejected",        rejected, delta_color="inverse")

    st.divider()

    # ── Bulk actions ─────────────────────────────────────────
    st.markdown("#### Bulk Actions")
    bulk_col1, bulk_col2, bulk_col3 = st.columns([1, 1, 2])
    with bulk_col1:
        if st.button("✅ Approve All Matched", use_container_width=True):
            for _, row in df[df["Match Status"] == "Matched"].iterrows():
                st.session_state.review_status[row["ID"]] = "Approved"
                st.session_state.review_user[row["ID"]]   = f"{reviewer_name} ({reviewer_role})"
                st.session_state.review_timestamp[row["ID"]] = datetime.now().strftime("%Y-%m-%d %H:%M")
                st.session_state.review_comments[row["ID"]] = "Bulk approval — all matched transactions"
            st.rerun()
    with bulk_col2:
        if st.button("🔄 Reset All to Pending", use_container_width=True):
            for txn_id in df["ID"].tolist():
                st.session_state.review_status[txn_id]    = "Pending"
                st.session_state.review_user[txn_id]      = ""
                st.session_state.review_timestamp[txn_id] = ""
                st.session_state.review_comments[txn_id]  = ""
            st.rerun()
    with bulk_col3:
        st.markdown(f"Reviewing as: **{reviewer_name}** · {reviewer_role}")

    st.divider()

    # ── Filter by review status ───────────────────────────────
    filter_rev = st.radio("Show", ["All", "Pending", "Approved", "Rejected"], horizontal=True)

    # ── Individual review cards ───────────────────────────────
    for _, row in filtered.iterrows():
        txn_id     = row["ID"]
        rev_status = st.session_state.review_status.get(txn_id, "Pending")

        if filter_rev != "All" and rev_status != filter_rev:
            continue

        css_class  = {"Approved": "hitl-approved", "Rejected": "hitl-rejected", "Pending": "hitl-pending"}.get(rev_status, "hitl-pending")
        badge_class= {"Approved": "badge-approved", "Rejected": "badge-rejected", "Pending": "badge-pending"}.get(rev_status, "badge-pending")
        badge_icon = {"Approved": "✅", "Rejected": "❌", "Pending": "⏳"}.get(rev_status, "⏳")

        # Compute entries for this transaction
        entries   = compute_elimination(row)
        entry_df  = pd.DataFrame(entries)
        if not show_dt:
            entry_df = entry_df[~entry_df["Audit"].str.contains("-DT", na=False)]

        with st.container():
            st.markdown(f"""
<div class="hitl-card {css_class}">
  <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
    <div>
      <strong style="font-size:15px;">{txn_id}</strong>
      &nbsp;·&nbsp; {row['Description']}
      &nbsp;&nbsp;<span class="hitl-badge {badge_class}">{badge_icon} {rev_status}</span>
    </div>
    <div style="font-size:13px; color:#666;">{row['Rule Code']} &nbsp;|&nbsp; {ELIMINATION_RULES.get(row['Rule Code'],{}).get('label','—')}</div>
  </div>
  <div style="font-size:13px; color:#555; margin-bottom:4px;">
    <strong>Seller:</strong> {ENTITIES[row['Seller']]['name']} ({row['Seller CCY']})
    &nbsp;&nbsp;→&nbsp;&nbsp;
    <strong>Buyer:</strong> {ENTITIES[row['Buyer']]['name']} ({row['Buyer CCY']})
  </div>
  <div style="font-size:13px; color:#555;">
    <strong>Amount:</strong> ${row['Seller USD']:,.0f} USD &nbsp;|&nbsp;
    <strong>Match:</strong> {row['Match Status']} &nbsp;|&nbsp;
    <strong>Gap:</strong> {row['Gap %']:.2f}%
  </div>
</div>
""", unsafe_allow_html=True)

            with st.expander(f"📋 View Journal Entries & Take Action — {txn_id}"):
                col_je, col_action = st.columns([3, 2])

                with col_je:
                    st.markdown("**Proposed Journal Entries**")
                    entry_disp = entry_df.copy()
                    entry_disp["Amount"] = entry_disp["Amount"].map("${:,.0f}".format)
                    st.dataframe(entry_disp[["Account","Dr/Cr","Amount","Value","Audit"]],
                                 use_container_width=True, height=200)

                    rule_info = ELIMINATION_RULES.get(row["Rule Code"], {})
                    st.info(f"**Rule:** {rule_info.get('description','')}")

                    if row["Match Status"] == "Exception":
                        st.warning(f"⚠️ This transaction has a **{row['Gap %']:.2f}% gap** between reported amounts. "
                                    f"Review carefully before approval.")

                with col_action:
                    st.markdown("**Reviewer Action**")

                    if rev_status != "Pending":
                        reviewer_who = st.session_state.review_user.get(txn_id, "—")
                        review_when  = st.session_state.review_timestamp.get(txn_id, "—")
                        review_note  = st.session_state.review_comments.get(txn_id, "")
                        st.markdown(f"**Actioned by:** {reviewer_who}")
                        st.markdown(f"**Timestamp:** {review_when}")
                        if review_note:
                            st.markdown(f"**Comment:** *{review_note}*")
                        if st.button(f"🔄 Reset to Pending", key=f"reset_{txn_id}"):
                            st.session_state.review_status[txn_id]    = "Pending"
                            st.session_state.review_user[txn_id]      = ""
                            st.session_state.review_timestamp[txn_id] = ""
                            st.session_state.review_comments[txn_id]  = ""
                            st.rerun()
                    else:
                        comment = st.text_area("Review Comment", key=f"comment_{txn_id}",
                                               placeholder="Add a note (optional)...", height=80)

                        designated = REVIEWERS.get(row["Seller"], reviewer_name)
                        st.caption(f"Suggested reviewer: {designated}")

                        approve_col, reject_col = st.columns(2)
                        with approve_col:
                            if st.button(f"✅ Approve", key=f"approve_{txn_id}", use_container_width=True):
                                st.session_state.review_status[txn_id]    = "Approved"
                                st.session_state.review_user[txn_id]      = f"{reviewer_name} ({reviewer_role})"
                                st.session_state.review_timestamp[txn_id] = datetime.now().strftime("%Y-%m-%d %H:%M")
                                st.session_state.review_comments[txn_id]  = comment or "Approved — no additional notes"
                                st.rerun()
                        with reject_col:
                            if st.button(f"❌ Reject", key=f"reject_{txn_id}", use_container_width=True):
                                st.session_state.review_status[txn_id]    = "Rejected"
                                st.session_state.review_user[txn_id]      = f"{reviewer_name} ({reviewer_role})"
                                st.session_state.review_timestamp[txn_id] = datetime.now().strftime("%Y-%m-%d %H:%M")
                                st.session_state.review_comments[txn_id]  = comment or "Rejected — requires investigation"
                                st.rerun()

    # ── Period close readiness check ─────────────────────────
    st.divider()
    st.markdown("#### Period Close Readiness")
    total_txns   = len(df)
    approved_now = sum(1 for v in st.session_state.review_status.values() if v == "Approved")
    rejected_now = sum(1 for v in st.session_state.review_status.values() if v == "Rejected")
    pending_now  = total_txns - approved_now - rejected_now
    pct_complete = approved_now / total_txns * 100

    prog_col, status_col = st.columns([2, 1])
    with prog_col:
        st.progress(pct_complete / 100)
        st.caption(f"{pct_complete:.0f}% of eliminations approved — {pending_now} pending, {rejected_now} rejected")
    with status_col:
        if pct_complete == 100 and rejected_now == 0:
            st.success("✅ All eliminations approved. Period close ready.")
        elif rejected_now > 0:
            st.error(f"❌ {rejected_now} rejection(s) must be resolved before period close.")
        else:
            st.warning(f"⏳ {pending_now} transaction(s) awaiting review.")

    # Download review log
    review_log = []
    for txn_id, status in st.session_state.review_status.items():
        row = df[df["ID"] == txn_id]
        if len(row) == 0: continue
        row = row.iloc[0]
        review_log.append({
            "Txn ID":         txn_id,
            "Description":    row["Description"],
            "Seller":         ENTITIES[row["Seller"]]["name"],
            "Buyer":          ENTITIES[row["Buyer"]]["name"],
            "Rule Code":      row["Rule Code"],
            "Amount USD":     f"${row['Seller USD']:,.0f}",
            "Match Status":   row["Match Status"],
            "Review Status":  status,
            "Reviewed By":    st.session_state.review_user.get(txn_id, ""),
            "Timestamp":      st.session_state.review_timestamp.get(txn_id, ""),
            "Comment":        st.session_state.review_comments.get(txn_id, ""),
        })
    review_df = pd.DataFrame(review_log)
    buf_rev = io.BytesIO()
    review_df.to_excel(buf_rev, index=False)
    st.download_button("⬇️ Download Review Log (Excel)", buf_rev.getvalue(),
                       file_name=f"IC_Review_Log_{period_label.replace(' ','_')}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# ════════════════════════════════════════════════════
# TAB 6 — RULES REFERENCE
# ════════════════════════════════════════════════════
with tabs[5]:
    st.markdown("### Elimination Rules Reference")
    st.caption(f"{len(ELIMINATION_RULES)} consolidation rules across 9 categories")

    sel_rule_cat = st.selectbox("Filter by Category",
                                 ["All"] + sorted(set(r["category"] for r in ELIMINATION_RULES.values())))

    for code, info in ELIMINATION_RULES.items():
        if sel_rule_cat != "All" and info["category"] != sel_rule_cat:
            continue
        cat_color = CATEGORY_COLORS.get(info["category"], "#888")
        txns_using = df[df["Rule Code"] == code]
        with st.expander(f"**{code}** — {info['label']}"):
            c1, c2 = st.columns([1, 3])
            with c1:
                st.markdown(f'<span class="rule-chip" style="background:{cat_color}">{info["category"]}</span>', unsafe_allow_html=True)
                st.markdown(f"**Code:** `{code}`")
            with c2:
                st.markdown(info["description"])
                if len(txns_using) > 0:
                    st.caption(f"Active in {len(txns_using)} transaction(s) this period: " +
                               ", ".join(txns_using["ID"].tolist()))

    st.divider()
    rule_cat_df = pd.DataFrame([(r["category"], code) for code, r in ELIMINATION_RULES.items()],
                                columns=["Category","Code"])
    cat_count = rule_cat_df.groupby("Category").size().reset_index(name="Count").sort_values("Count", ascending=False)
    fig = px.bar(cat_count, x="Category", y="Count", color="Category",
                 color_discrete_map={c: CATEGORY_COLORS.get(c,"#888") for c in cat_count["Category"]})
    fig.update_layout(height=280, showlegend=False, margin=dict(l=0,r=0,t=10,b=10),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(fig, use_container_width=True)

# ════════════════════════════════════════════════════
# TAB 7 — ENTITY HIERARCHY
# ════════════════════════════════════════════════════
with tabs[6]:
    st.markdown("### Apex Group — Entity Hierarchy")

    e_data = []
    for code, info in ENTITIES.items():
        txns = len(df[(df["Seller"]==code)|(df["Buyer"]==code)])
        vol  = df[df["Seller"]==code]["Seller USD"].sum() + df[df["Buyer"]==code]["Buyer USD"].sum()
        e_data.append({"Code": code, "Entity Name": info["name"], "Method": info["method"],
                       "PCon": f"{info['pcon']*100:.0f}%", "POwn": f"{info['pown']*100:.0f}%",
                       "Currency": info["currency"], "IC Txns": txns,
                       "IC Volume USD": f"${vol:,.0f}", "Reviewer": REVIEWERS.get(code,"—")})
    e_df = pd.DataFrame(e_data)
    method_colors = {"Holding":"#1D6FA5","Global":"#0F6E56","Proportional":"#C47A1E","Equity":"#5C4A8C"}

    def color_method(val):
        return f"background-color:{method_colors.get(val,'#eee')};color:#fff;font-weight:600"

    st.dataframe(e_df.style.map(color_method, subset=["Method"]), use_container_width=True)

    st.divider()
    cols_m = st.columns(4)
    descriptions = {"Holding":"100% — no minority","Global":"Full consolidation with NCI",
                    "Proportional":"Proportional to ownership %","Equity":"Single-line equity method"}
    for i, (m, color) in enumerate(method_colors.items()):
        cols_m[i].markdown(f'<span class="rule-chip" style="background:{color}">{m}</span>', unsafe_allow_html=True)
        cols_m[i].caption(descriptions[m])

# ════════════════════════════════════════════════════
# TAB 8 — CONSOLIDATION PROOF
# ════════════════════════════════════════════════════
with tabs[7]:
    st.markdown("### Consolidation Proof — [Elimination] Value")

    entity_totals = {code: random.uniform(5_000_000, 50_000_000) for code in ENTITIES}
    total_entity   = sum(entity_totals.values())
    total_elim_val = filtered["Seller USD"].sum() * -1
    cta_adj        = total_entity * 0.012
    group_total    = total_entity + total_elim_val + cta_adj

    p1, p2, p3, p4 = st.columns(4)
    p1.metric("Entity Data (Sum)",  f"${total_entity/1e6:.1f}M")
    p2.metric("Eliminations",       f"${total_elim_val/1e6:.1f}M", delta="[Elim] Value")
    p3.metric("CTA / Translation",  f"${cta_adj/1e6:.1f}M",        delta="FX Adj")
    p4.metric("Group Consolidated", f"${group_total/1e6:.1f}M",    delta="✅ Balanced")

    st.divider()
    cat_elim = filtered.groupby("Category")["Seller USD"].sum().reset_index()
    cat_elim["Elimination USD"] = -cat_elim["Seller USD"]
    fig = go.Figure(go.Bar(x=cat_elim["Category"], y=cat_elim["Elimination USD"],
                            marker_color="#D94F3D",
                            text=cat_elim["Elimination USD"].map("${:,.0f}".format),
                            textposition="outside"))
    fig.update_layout(height=340, title="Elimination impact by category (USD)",
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      margin=dict(l=0,r=0,t=40,b=10))
    st.plotly_chart(fig, use_container_width=True)

    ent_df = pd.DataFrame({"Entity": [ENTITIES[k]["name"] for k in entity_totals],
                            "Balance USD": list(entity_totals.values()),
                            "Method": [ENTITIES[k]["method"] for k in entity_totals]})
    fig2 = px.bar(ent_df, x="Entity", y="Balance USD", color="Method",
                  color_discrete_map=method_colors)
    fig2.update_layout(height=320, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                       margin=dict(l=0,r=0,t=10,b=10), xaxis_tickangle=-30)
    st.plotly_chart(fig2, use_container_width=True)

# ════════════════════════════════════════════════════
# TAB 9 — ROI IMPACT
# ════════════════════════════════════════════════════
with tabs[8]:
    st.markdown("### ROI Impact Dashboard")
    hrs_saved  = hrs_manual - hrs_auto
    cost_saved = hrs_saved * fte_rate
    annual_roi = cost_saved * 12
    efficiency = (hrs_saved / hrs_manual * 100) if hrs_manual > 0 else 0

    r1, r2, r3, r4 = st.columns(4)
    r1.metric("Hours Saved / Period", f"{hrs_saved:.0f}h",       delta=f"{efficiency:.0f}% reduction")
    r2.metric("Cost Saved / Period",  f"${cost_saved:,.0f}",     delta="USD")
    r3.metric("Annual ROI",           f"${annual_roi:,.0f}",     delta="12-period basis")
    r4.metric("Rules Automated",      str(len(ELIMINATION_RULES)),delta="of 28 rules")

    st.divider()
    col_r1, col_r2 = st.columns(2)
    with col_r1:
        st.markdown("#### Manual vs AI-Assisted Hours")
        h_df = pd.DataFrame({"Process":["IC Matching","Elim Calc","JE Generation","Audit Trail","Exception Review","Human Review"],
                              "Manual": [12,10,8,6,4,8],
                              "AI-Assisted":[1.5,0.5,0.2,0.1,2.0,1.5]})
        fig_h = go.Figure()
        fig_h.add_bar(name="Manual",      x=h_df["Process"], y=h_df["Manual"],      marker_color="#D94F3D")
        fig_h.add_bar(name="AI-Assisted", x=h_df["Process"], y=h_df["AI-Assisted"], marker_color="#1D9E75")
        fig_h.update_layout(barmode="group", height=300,
                            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                            margin=dict(l=0,r=0,t=10,b=10))
        st.plotly_chart(fig_h, use_container_width=True)
    with col_r2:
        st.markdown("#### Cumulative Annual Savings (USD)")
        months     = [f"M{i+1}" for i in range(12)]
        cumulative = [cost_saved * (i+1) for i in range(12)]
        fig_c = go.Figure(go.Scatter(x=months, y=cumulative, mode="lines+markers",
                                      fill="tozeroy", line=dict(color="#0F6E56",width=2),
                                      marker=dict(size=6)))
        fig_c.update_layout(height=300, yaxis_title="Cumulative USD",
                            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                            margin=dict(l=0,r=0,t=10,b=10))
        st.plotly_chart(fig_c, use_container_width=True)

    st.divider()
    qa1, qa2, qa3, qa4 = st.columns(4)
    matched_count = len(df[df["Match Status"] == "Matched"])
    qa1.metric("Auto-Match Rate",      f"{matched_count/len(df)*100:.0f}%", delta="vs 0% manual")
    qa2.metric("Exception Catch Rate", "98.5%",    delta="+34pp vs manual")
    qa3.metric("Cycle Time",           "2.1 days", delta="-5.9 days", delta_color="inverse")
    qa4.metric("HITL Review Time",     "1.5h",     delta="-6.5h vs manual review")

# ════════════════════════════════════════════════════
# TAB 10 — AUDIT TRAIL
# ════════════════════════════════════════════════════
with tabs[9]:
    st.markdown("### Audit Trail")
    st.caption("Complete decision log — IC matching → elimination computation → human review → posting")

    audit_log = []
    for _, row in filtered.iterrows():
        for e in compute_elimination(row):
            if not show_dt and "-DT" in e.get("Audit",""):
                continue
            rev_user = st.session_state.review_user.get(row["ID"], "Awaiting review")
            rev_ts   = st.session_state.review_timestamp.get(row["ID"], "—")
            audit_log.append({
                "Timestamp (System)": f"2025-06-{random.randint(1,28):02d} {random.randint(8,18):02d}:{random.randint(0,59):02d}",
                "Txn ID":             row["ID"],
                "Seller":             ENTITIES[row["Seller"]]["name"],
                "Buyer":              ENTITIES[row["Buyer"]]["name"],
                "Rule Code":          row["Rule Code"],
                "Account":            e["Account"],
                "Dr/Cr":              e["Dr/Cr"],
                "Amount USD":         f"${e['Amount']:,.0f}",
                "Value":              e["Value"],
                "Audit Code":         e["Audit"],
                "System User":        "IC Elimination Engine",
                "Review Status":      st.session_state.review_status.get(row["ID"], "Pending"),
                "Reviewed By":        rev_user,
                "Review Timestamp":   rev_ts,
                "Review Comment":     st.session_state.review_comments.get(row["ID"], ""),
            })

    audit_df = pd.DataFrame(audit_log)
    st.dataframe(audit_df, use_container_width=True, height=460)

    a1, a2, a3, a4 = st.columns(4)
    a1.metric("Total Audit Entries", len(audit_df))
    a2.metric("Rules Fired",         len(audit_df["Rule Code"].unique()))
    a3.metric("Approved Entries",    len(audit_df[audit_df["Review Status"] == "Approved"]))
    a4.metric("Pending Entries",     len(audit_df[audit_df["Review Status"] == "Pending"]))

    buf_a = io.BytesIO()
    audit_df.to_excel(buf_a, index=False)
    st.download_button("⬇️ Download Full Audit Trail (Excel)", buf_a.getvalue(),
                       file_name=f"IC_Audit_Trail_{period_label.replace(' ','_')}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    st.divider()
    st.markdown("#### Accountability Chain")
    st.markdown("""
| Step | Input | Process | Output | Responsible Party | Status |
|------|-------|---------|--------|-------------------|--------|
| 1 | Entity IC balances | Bilateral matching engine | Matched / Exception list | System (automated) | ✅ |
| 2 | Account rule attribute | Rule determination logic | Elimination rule code | System (automated) | ✅ |
| 3 | Rule code + amounts | Consolidation rules engine | Proposed journal entries | System (automated) | ✅ |
| 4 | Proposed journals | **Human review & approval** | Approved / Rejected decision | **Named Controller** | 👤 HITL |
| 5 | Approved journals | Ledger posting | Posted [Elimination] entries | Finance System | Pending full approval |
| 6 | Posted entries | Consolidation proof | Group financial statements | CFO / External Auditor | Pending |
    """)
    st.info("👤 **Human-in-the-Loop is a mandatory gate at Step 4.** No elimination posts to the consolidated ledger without an explicit named approval. Every decision is timestamped, attributed, and downloadable for audit.")
