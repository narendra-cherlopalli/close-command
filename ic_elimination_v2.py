import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime
import sqlite3
import io
import os

st.set_page_config(
    page_title="IC Elimination Engine — Consolidation Suite",
    layout="wide",
    page_icon="⚖️"
)

# ─────────────────────────────────────────────────────────────
# SQLITE — Persistent state layer
# ─────────────────────────────────────────────────────────────

DB_PATH = "ic_elimination.db"

def init_db():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id TEXT PRIMARY KEY,
            seller TEXT, buyer TEXT,
            rule_code TEXT, rule_internal TEXT,
            description TEXT,
            seller_amt REAL, buyer_amt REAL,
            seller_ccy TEXT, buyer_ccy TEXT,
            seller_usd REAL, buyer_usd REAL,
            gap_usd REAL, gap_pct REAL,
            match_status TEXT, category TEXT,
            rule_label TEXT, pcon_seller REAL, pcon_buyer REAL,
            period TEXT, scenario TEXT,
            source TEXT DEFAULT 'sample'
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS reviews (
            txn_id TEXT PRIMARY KEY,
            status TEXT DEFAULT 'Pending',
            reviewer TEXT DEFAULT '',
            review_ts TEXT DEFAULT '',
            comment TEXT DEFAULT ''
        )
    """)
    con.commit()
    con.close()

def load_transactions_from_db():
    con = sqlite3.connect(DB_PATH)
    df = pd.read_sql("SELECT * FROM transactions", con)
    con.close()
    return df

def save_transactions_to_db(df):
    con = sqlite3.connect(DB_PATH)
    df.to_sql("transactions", con, if_exists="replace", index=False)
    con.commit()
    con.close()

def load_reviews_from_db():
    con = sqlite3.connect(DB_PATH)
    rows = con.execute("SELECT txn_id, status, reviewer, review_ts, comment FROM reviews").fetchall()
    con.close()
    return {r[0]: {"status": r[1], "reviewer": r[2], "ts": r[3], "comment": r[4]} for r in rows}

def upsert_review(txn_id, status, reviewer, ts, comment):
    con = sqlite3.connect(DB_PATH)
    con.execute("""
        INSERT INTO reviews (txn_id, status, reviewer, review_ts, comment)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(txn_id) DO UPDATE SET
            status=excluded.status,
            reviewer=excluded.reviewer,
            review_ts=excluded.review_ts,
            comment=excluded.comment
    """, (txn_id, status, reviewer, ts, comment))
    con.commit()
    con.close()

def reset_review(txn_id):
    con = sqlite3.connect(DB_PATH)
    con.execute("DELETE FROM reviews WHERE txn_id=?", (txn_id,))
    con.commit()
    con.close()

def reset_all_reviews():
    con = sqlite3.connect(DB_PATH)
    con.execute("DELETE FROM reviews")
    con.commit()
    con.close()

init_db()

# ─────────────────────────────────────────────────────────────
# ELIMINATION RULES
# ─────────────────────────────────────────────────────────────

ELIMINATION_RULES = {
    "EQ-001":  {"label": "Equity Split — Group vs Minority",          "category": "Equity",       "description": "Splits equity balance between group and NCI. Posts to Group Reserves and NCI at PCon/POwn/PMin percentages."},
    "EQ-002":  {"label": "Translation Reserve — Equity",              "category": "Equity",       "description": "Handles FX conversion reserves from equity accounts."},
    "EQ-003":  {"label": "Other Comprehensive Income Split",          "category": "Equity/OCI",   "description": "Allocates OCI between group and NCI portions."},
    "EQ-004":  {"label": "Net Income Allocation — Group vs NCI",      "category": "P&L",          "description": "Allocates current period net income between group and minority interest."},
    "EQ-005":  {"label": "FX Impact on Net Income",                   "category": "P&L/FX",       "description": "Posts FX impact on net income to conversion reserve accounts."},
    "INV-001": {"label": "Investment Elimination",                    "category": "Investment",   "description": "Eliminates parent's investment in subsidiary against subsidiary's equity."},
    "INV-002": {"label": "Historic Investment Carry-forward",         "category": "Investment",   "description": "Carries forward prior-period investment eliminations."},
    "IC-001":  {"label": "Standard Intercompany Elimination",         "category": "Intercompany", "description": "Simple bilateral elimination at Min(PCon). Uses plug account as counterpart."},
    "IC-002":  {"label": "Reciprocal IC Elimination",                 "category": "Intercompany", "description": "Two-sided elimination with buyer/seller distinction. Handles proportional entities."},
    "IC-003":  {"label": "Conditional IC Elimination",                "category": "Intercompany", "description": "Fires only when balance is positive. Prevents double elimination."},
    "IC-004":  {"label": "IC Provision Elimination",                  "category": "Intercompany", "description": "Eliminates intragroup provisions. Reverses provision P&L at consolidation level."},
    "IC-005":  {"label": "Historic IC Provision Carry-forward",       "category": "Intercompany", "description": "Historical carry-forward of IC provision eliminations."},
    "GW-001":  {"label": "Goodwill on Acquisition",                   "category": "Goodwill",     "description": "Eliminates goodwill at PCon × ICPPCon. Handles scope entry vs ongoing."},
    "GW-002":  {"label": "Historic Goodwill Carry-forward",           "category": "Goodwill",     "description": "Carries forward prior-period goodwill balances."},
    "GW-003":  {"label": "Goodwill Amortisation / Impairment",        "category": "Goodwill",     "description": "Eliminates goodwill depreciation and impairment charges."},
    "GW-004":  {"label": "Historic Goodwill Amortisation",            "category": "Goodwill",     "description": "Historical carry-forward of goodwill amortisation."},
    "DIV-001": {"label": "Paid Dividend Elimination",                 "category": "Dividends",    "description": "Eliminates intercompany dividends paid. Posts to Group and NCI reserves."},
    "DIV-002": {"label": "Scope Variation — Paid Dividends",          "category": "Dividends",    "description": "Reclassifies paid dividend eliminations on scope changes."},
    "DIV-003": {"label": "Withholding Tax FX Adjustment",             "category": "Dividends/FX", "description": "Posts FX movements on withholding tax to conversion reserves."},
    "DIV-004": {"label": "Dividend Income Elimination",               "category": "Dividends",    "description": "Eliminates dividend income from group subsidiaries."},
    "DIV-005": {"label": "Scope Variation — Dividend Income",         "category": "Dividends",    "description": "Mirrors paid-dividend scope variation on the income side."},
    "DIV-006": {"label": "Dividend Income FX Adjustment",             "category": "Dividends/FX", "description": "Posts FX impact on dividend income to conversion reserves."},
    "STK-001": {"label": "Unrealised Profit in Inventory",            "category": "Stock Margin", "description": "Eliminates unrealised profit in buyer's inventory from intercompany sales."},
    "STK-002": {"label": "Historic Unrealised Profit Carry-forward",  "category": "Stock Margin", "description": "Carries forward unrealised profit elimination."},
    "AUC-001": {"label": "Intragroup Construction Revenue",           "category": "AUC/CapEx",    "description": "Eliminates revenue on intragroup construction contracts. Posts to revenue P&L and BS link."},
    "AUC-002": {"label": "Historic Construction Revenue",             "category": "AUC/CapEx",    "description": "Historical carry-forward of construction revenue elimination."},
    "AUC-003": {"label": "Intragroup Construction Cost",              "category": "AUC/CapEx",    "description": "Mirror of construction revenue rule on the cost side."},
    "AUC-004": {"label": "Historic Construction Cost",                "category": "AUC/CapEx",    "description": "Historical carry-forward of construction cost elimination."},
}

RULE_MAP = {
    "ELIM": "IC-001", "ELIMR": "IC-002", "ELIMRA": "IC-003",
    "ELIPROV": "IC-004", "ELIPROVH": "IC-005",
    "CAPI": "EQ-001", "CAPIC": "EQ-002", "COMPINC": "EQ-003",
    "RESU": "EQ-004", "RESUC": "EQ-005",
    "PINT": "INV-001", "PINTH": "INV-002",
    "GW": "GW-001", "GWH": "GW-002", "GWA": "GW-003", "GWAH": "GW-004",
    "DIVP": "DIV-001", "DIVVAR": "DIV-002", "DIVH": "DIV-003",
    "DIVI": "DIV-004", "DIVIVAR": "DIV-005", "DIVIH": "DIV-006",
    "PSTK": "STK-001", "PSTKH": "STK-002",
    "AUCREV": "AUC-001", "AUCREVH": "AUC-002",
    "AUCCOS": "AUC-003", "AUCCOSH": "AUC-004",
}

CATEGORY_COLORS = {
    "Equity": "#1D6FA5", "Equity/OCI": "#1D6FA5",
    "P&L": "#2E86AB", "P&L/FX": "#2E86AB",
    "Investment": "#0F6E56", "Intercompany": "#5C4A8C",
    "Goodwill": "#B5562D", "Dividends": "#C47A1E", "Dividends/FX": "#C47A1E",
    "Stock Margin": "#1A7A4A", "AUC/CapEx": "#5A5A5A",
}

ENTITIES = {
    "HLD":   {"name": "Apex Group Holdings SA",         "method": "Holding",      "pcon": 1.00, "pown": 1.00, "currency": "USD"},
    "MFG1":  {"name": "Apex Manufacturing East Ltd",    "method": "Global",       "pcon": 0.60, "pown": 0.60, "currency": "EUR"},
    "MFG2":  {"name": "Apex Industrial Solutions Corp", "method": "Global",       "pcon": 0.51, "pown": 0.51, "currency": "GBP"},
    "DIST":  {"name": "Apex Distribution Co.",          "method": "Global",       "pcon": 0.75, "pown": 0.75, "currency": "EUR"},
    "RETAIL":{"name": "Apex Retail Network Ltd",        "method": "Global",       "pcon": 0.42, "pown": 0.42, "currency": "AED"},
    "JV1":   {"name": "Meridian Ventures (JV)",         "method": "Proportional", "pcon": 0.50, "pown": 0.50, "currency": "USD"},
    "ASSOC": {"name": "Pinnacle Associates Inc.",       "method": "Equity",       "pcon": 0.30, "pown": 0.30, "currency": "USD"},
    "FIN":   {"name": "Apex Finance & Treasury BV",     "method": "Global",       "pcon": 1.00, "pown": 1.00, "currency": "EUR"},
}

FX_RATES = {"USD": 1.0, "EUR": 1.08, "GBP": 1.27, "AED": 0.272}

# ─────────────────────────────────────────────────────────────
# SAMPLE DATA
# ─────────────────────────────────────────────────────────────

def generate_sample_transactions(period="DEC 2025", scenario="ACTUAL"):
    import random
    random.seed(42)
    np.random.seed(42)
    pairs = [
        ("HLD",   "MFG1",   "ELIM",   "IC Loan Interest Charge",          1_250_000),
        ("HLD",   "MFG2",   "ELIM",   "Group Management Fee",               420_000),
        ("MFG1",  "DIST",   "ELIMR",  "Raw Material Supply",              3_800_000),
        ("DIST",  "RETAIL", "ELIMR",  "Finished Goods Supply",            2_100_000),
        ("FIN",   "HLD",    "PINT",   "Investment in Subsidiary",        15_000_000),
        ("HLD",   "JV1",    "PSTK",   "Unrealised Profit — Inventory",      680_000),
        ("HLD",   "MFG1",   "DIVP",   "Dividend Payment",                   900_000),
        ("MFG1",  "DIST",   "DIVI",   "Dividend Income Received",           540_000),
        ("HLD",   "MFG2",   "GW",     "Goodwill on Acquisition",          4_500_000),
        ("FIN",   "RETAIL", "ELIPROV","IC Allowance for Doubtful Debt",     320_000),
        ("HLD",   "DIST",   "CAPI",   "Share Capital Contribution",       8_000_000),
        ("FIN",   "MFG1",   "RESU",   "Net Income Allocation",            1_650_000),
        ("HLD",   "ASSOC",  "AUCREV", "Intragroup Construction Revenue",  2_200_000),
        ("ASSOC", "HLD",    "AUCCOS", "Intragroup Construction Cost",     2_190_000),
        ("JV1",   "DIST",   "ELIMRA", "Conditional Service Elimination",    175_000),
    ]
    rows = []
    for i, (seller, buyer, rule_internal, desc, base_amt) in enumerate(pairs):
        noise = random.uniform(-0.015, 0.015)
        seller_amt = base_amt
        buyer_amt  = base_amt * (1 + noise)
        gap_pct    = abs(seller_amt - buyer_amt) / seller_amt * 100
        s_cur  = ENTITIES[seller]["currency"]
        b_cur  = ENTITIES[buyer]["currency"]
        s_usd  = seller_amt * FX_RATES[s_cur]
        b_usd  = buyer_amt  * FX_RATES[b_cur]
        rc     = RULE_MAP.get(rule_internal, rule_internal)
        ms     = "Matched" if gap_pct < 0.5 else ("Tolerance" if gap_pct < 2.0 else "Exception")
        rows.append({
            "id": f"IC-{i+1:03d}", "seller": seller, "buyer": buyer,
            "rule_code": rc, "rule_internal": rule_internal,
            "description": desc,
            "seller_amt": seller_amt, "buyer_amt": buyer_amt,
            "seller_ccy": s_cur, "buyer_ccy": b_cur,
            "seller_usd": s_usd, "buyer_usd": b_usd,
            "gap_usd": abs(s_usd - b_usd), "gap_pct": gap_pct,
            "match_status": ms,
            "category": ELIMINATION_RULES[rc]["category"],
            "rule_label": ELIMINATION_RULES[rc]["label"],
            "pcon_seller": ENTITIES[seller]["pcon"],
            "pcon_buyer":  ENTITIES[buyer]["pcon"],
            "period": period, "scenario": scenario,
            "source": "sample",
        })
    return pd.DataFrame(rows)

# ─────────────────────────────────────────────────────────────
# FILE UPLOAD PARSER
# ─────────────────────────────────────────────────────────────

REQUIRED_COLS = [
    "Txn_ID","Seller_Entity","Buyer_Entity","Rule_Code",
    "Description","Seller_CCY","Buyer_CCY",
    "Seller_Amount","Buyer_Amount","PCon_Seller","PCon_Buyer",
    "Period","Scenario"
]

def parse_uploaded_file(uploaded_file, period, scenario):
    try:
        if uploaded_file.name.endswith(".csv"):
            raw = pd.read_csv(uploaded_file)
        else:
            raw = pd.read_excel(uploaded_file)
    except Exception as e:
        return None, f"Could not read file: {e}"

    missing = [c for c in REQUIRED_COLS if c not in raw.columns]
    if missing:
        return None, f"Missing columns: {', '.join(missing)}"

    rows = []
    for _, r in raw.iterrows():
        rc = str(r["Rule_Code"]).strip()
        if rc not in ELIMINATION_RULES:
            rc = RULE_MAP.get(rc, rc)
        if rc not in ELIMINATION_RULES:
            return None, f"Unknown rule code '{rc}' on row for {r.get('Txn_ID','?')}. Check Rules Reference."

        s_amt = float(r["Seller_Amount"])
        b_amt = float(r["Buyer_Amount"])
        s_cur = str(r["Seller_CCY"]).upper()
        b_cur = str(r["Buyer_CCY"]).upper()
        s_usd = s_amt * FX_RATES.get(s_cur, 1.0)
        b_usd = b_amt * FX_RATES.get(b_cur, 1.0)
        gap_pct = abs(s_amt - b_amt) / s_amt * 100 if s_amt > 0 else 0
        ms = "Matched" if gap_pct < 0.5 else ("Tolerance" if gap_pct < 2.0 else "Exception")

        seller_code = str(r["Seller_Entity"]).split(".")[-1]
        buyer_code  = str(r["Buyer_Entity"]).split(".")[-1]
        pcon_s = float(r["PCon_Seller"])
        pcon_b = float(r["PCon_Buyer"])

        rows.append({
            "id": str(r["Txn_ID"]),
            "seller": seller_code, "buyer": buyer_code,
            "rule_code": rc, "rule_internal": rc,
            "description": str(r["Description"]),
            "seller_amt": s_amt, "buyer_amt": b_amt,
            "seller_ccy": s_cur, "buyer_ccy": b_cur,
            "seller_usd": s_usd, "buyer_usd": b_usd,
            "gap_usd": abs(s_usd - b_usd), "gap_pct": gap_pct,
            "match_status": ms,
            "category": ELIMINATION_RULES[rc]["category"],
            "rule_label": ELIMINATION_RULES[rc]["label"],
            "pcon_seller": pcon_s, "pcon_buyer": pcon_b,
            "period": period, "scenario": scenario,
            "source": "upload",
        })
    return pd.DataFrame(rows), None

def build_sample_csv():
    rows = [
        ["IC-001","APEX.HLD","APEX.MFG1","IC-001","IC Loan Interest","USD","EUR",1250000,1148148,1.00,0.60,"DEC 2025","ACTUAL"],
        ["IC-002","APEX.HLD","APEX.MFG2","IC-001","Group Management Fee","USD","GBP",420000,330709,1.00,0.51,"DEC 2025","ACTUAL"],
        ["IC-003","APEX.MFG1","APEX.DIST","IC-002","Raw Material Supply","EUR","EUR",3800000,3742200,0.60,0.75,"DEC 2025","ACTUAL"],
        ["IC-004","APEX.DIST","APEX.RETAIL","IC-002","Finished Goods Supply","EUR","AED",2100000,8360640,0.75,0.42,"DEC 2025","ACTUAL"],
        ["IC-005","APEX.FIN","APEX.HLD","INV-001","Investment in Subsidiary","EUR","USD",15000000,16200000,1.00,1.00,"DEC 2025","ACTUAL"],
        ["IC-006","APEX.HLD","APEX.JV1","STK-001","Unrealised Profit in Inventory","USD","USD",680000,680000,1.00,0.50,"DEC 2025","ACTUAL"],
        ["IC-007","APEX.HLD","APEX.MFG1","DIV-001","Dividend Payment","USD","EUR",900000,828704,1.00,0.60,"DEC 2025","ACTUAL"],
        ["IC-008","APEX.MFG1","APEX.DIST","DIV-004","Dividend Income Received","EUR","EUR",540000,540000,0.60,0.75,"DEC 2025","ACTUAL"],
        ["IC-009","APEX.HLD","APEX.MFG2","GW-001","Goodwill on Acquisition","USD","GBP",4500000,3543307,1.00,0.51,"DEC 2025","ACTUAL"],
        ["IC-010","APEX.FIN","APEX.RETAIL","IC-004","IC Allowance for Doubtful Debt","EUR","AED",320000,1274240,1.00,0.42,"DEC 2025","ACTUAL"],
    ]
    df = pd.DataFrame(rows, columns=REQUIRED_COLS)
    buf = io.BytesIO()
    df.to_csv(buf, index=False)
    return buf.getvalue()

# ─────────────────────────────────────────────────────────────
# ELIMINATION ENGINE
# ─────────────────────────────────────────────────────────────

def compute_elimination(row):
    rule    = row["rule_internal"]
    amt     = row["seller_usd"]
    pcon_s  = row["pcon_seller"]
    pcon_b  = row["pcon_buyer"]
    pown_s  = pcon_s
    pmin_s  = max(0, pcon_s - pown_s)
    min_p   = min(pcon_s, pcon_b)
    rc      = row["rule_code"]
    entries = []

    if rule == "ELIM":
        entries += [
            {"Account": "IC Receivable / Revenue", "Dr/Cr": "Dr", "Amount": -amt * min_p, "Audit": rc},
            {"Account": "IC Payable / Cost",        "Dr/Cr": "Cr", "Amount":  amt * min_p, "Audit": rc},
        ]
    elif rule in ("ELIMR", "ELIMRA"):
        entries += [
            {"Account": "Seller Account", "Dr/Cr": "Dr", "Amount": -amt * min_p, "Audit": rc},
            {"Account": "Offset Account", "Dr/Cr": "Cr", "Amount":  amt * min_p, "Audit": rc},
            {"Account": "Buyer Account",  "Dr/Cr": "Dr", "Amount":  amt * min_p, "Audit": rc + "-B"},
            {"Account": "Offset Account", "Dr/Cr": "Cr", "Amount": -amt * min_p, "Audit": rc + "-B"},
        ]
    elif rule == "CAPI":
        entries += [
            {"Account": "Share Capital",  "Dr/Cr": "Dr", "Amount": -amt * pcon_s, "Audit": rc},
            {"Account": "Group Reserves", "Dr/Cr": "Cr", "Amount":  amt * pown_s, "Audit": rc},
            {"Account": "NCI Reserves",   "Dr/Cr": "Cr", "Amount":  amt * pmin_s, "Audit": rc},
        ]
    elif rule == "RESU":
        entries += [
            {"Account": "Net Income",       "Dr/Cr": "Dr", "Amount": -amt * pcon_s, "Audit": rc},
            {"Account": "Group Net Income", "Dr/Cr": "Cr", "Amount":  amt * pown_s, "Audit": rc},
            {"Account": "NCI Net Income",   "Dr/Cr": "Cr", "Amount":  amt * pmin_s, "Audit": rc},
        ]
    elif rule == "GW":
        entries += [
            {"Account": "Goodwill",           "Dr/Cr": "Dr", "Amount": -amt * pcon_s * pcon_b, "Audit": rc},
            {"Account": "Investment Account", "Dr/Cr": "Cr", "Amount":  amt * pcon_s * pcon_b, "Audit": rc},
            {"Account": "Group Reserves",     "Dr/Cr": "Cr", "Amount": -amt * pown_s,           "Audit": rc},
            {"Account": "NCI Reserves",       "Dr/Cr": "Cr", "Amount": -amt * pmin_s,           "Audit": rc},
        ]
    elif rule == "PINT":
        entries += [
            {"Account": "Investment in Sub", "Dr/Cr": "Dr", "Amount": -amt * pcon_s, "Audit": rc},
            {"Account": "Liaison Account",   "Dr/Cr": "Cr", "Amount":  amt * pcon_s, "Audit": rc},
            {"Account": "Group Reserves",    "Dr/Cr": "Cr", "Amount":  amt * pown_s, "Audit": rc + "-N"},
            {"Account": "NCI Reserves",      "Dr/Cr": "Cr", "Amount":  amt * pmin_s, "Audit": rc + "-N"},
        ]
    elif rule == "DIVP":
        entries += [
            {"Account": "Dividends Paid", "Dr/Cr": "Dr", "Amount": -amt * pcon_s, "Audit": rc},
            {"Account": "Group Reserves", "Dr/Cr": "Cr", "Amount":  amt * pown_s, "Audit": rc},
            {"Account": "NCI Reserves",   "Dr/Cr": "Cr", "Amount":  amt * pmin_s, "Audit": rc},
        ]
    elif rule == "DIVI":
        entries += [
            {"Account": "Dividend Income",  "Dr/Cr": "Dr", "Amount": -amt * pcon_s, "Audit": rc},
            {"Account": "Group Net Income", "Dr/Cr": "Cr", "Amount":  amt * pown_s, "Audit": rc},
            {"Account": "NCI Net Income",   "Dr/Cr": "Cr", "Amount":  amt * pmin_s, "Audit": rc},
        ]
    elif rule == "PSTK":
        entries += [
            {"Account": "Inventory",     "Dr/Cr": "Dr", "Amount": -amt * pcon_s * pcon_b, "Audit": rc},
            {"Account": "COGS/Revenue",  "Dr/Cr": "Cr", "Amount":  amt * pcon_s * pcon_b, "Audit": rc},
        ]
    elif rule == "ELIPROV":
        entries += [
            {"Account": "IC Provision",    "Dr/Cr": "Dr", "Amount": -amt * pcon_s, "Audit": rc},
            {"Account": "Provision P&L",   "Dr/Cr": "Cr", "Amount":  amt * pcon_s, "Audit": rc},
        ]
    elif rule in ("AUCREV", "AUCCOS"):
        pl = "Construction Revenue" if rule == "AUCREV" else "Construction Cost"
        entries += [
            {"Account": "AUC Asset",       "Dr/Cr": "Dr", "Amount": -amt * pcon_s * pcon_b, "Audit": rc},
            {"Account": pl,                "Dr/Cr": "Cr", "Amount":  amt * pcon_s * pcon_b, "Audit": rc},
            {"Account": "AUC Link — BS",   "Dr/Cr": "Dr", "Amount": -amt * pcon_s,           "Audit": rc},
            {"Account": "AUC Link — Contra","Dr/Cr": "Cr","Amount":  amt * pcon_s,           "Audit": rc},
        ]
    else:
        entries += [
            {"Account": f"Account ({rc})",    "Dr/Cr": "Dr", "Amount": -amt * pcon_s, "Audit": rc},
            {"Account": f"Counterpart ({rc})", "Dr/Cr": "Cr", "Amount":  amt * pcon_s, "Audit": rc},
        ]

    for e in entries:
        e["Value"] = "[Elimination]"
    return entries

# ─────────────────────────────────────────────────────────────
# CSS
# ─────────────────────────────────────────────────────────────

st.markdown("""
<style>
  .section-header { font-size:13px;font-weight:700;letter-spacing:.08em;
    text-transform:uppercase;color:#888;margin:18px 0 6px; }
  .hitl-card { border-radius:10px;padding:16px 20px;margin-bottom:12px;border:1px solid #e0e0e0; }
  .hitl-pending  { border-left:4px solid #E8A838;background:#fffbf0; }
  .hitl-approved { border-left:4px solid #1D9E75;background:#f0faf6; }
  .hitl-rejected { border-left:4px solid #D94F3D;background:#fff5f5; }
  .hitl-badge { display:inline-block;padding:3px 12px;border-radius:20px;
    font-size:11px;font-weight:700;letter-spacing:.05em; }
  .badge-pending  { background:#FFF3CD;color:#856404; }
  .badge-approved { background:#D1FAE5;color:#065F46; }
  .badge-rejected { background:#FEE2E2;color:#991B1B; }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────
# LOAD / SEED DATA
# ─────────────────────────────────────────────────────────────

existing = load_transactions_from_db()
if existing.empty:
    seed_df = generate_sample_transactions()
    save_transactions_to_db(seed_df)
    df = seed_df
else:
    df = existing

reviews = load_reviews_from_db()

# ─────────────────────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("## ⚖️ IC Elimination Suite")
    st.caption("Intercompany Consolidation Engine")
    st.divider()

    entity_options = ["All Entities"] + sorted(df["seller"].unique().tolist() +
                      [e for e in df["buyer"].unique().tolist() if e not in df["seller"].unique()])
    entity_options = ["All Entities"] + sorted(set(df["seller"].tolist() + df["buyer"].tolist()))

    def fmt_entity(x):
        if x == "All Entities": return x
        return f"{x} — {ENTITIES[x]['name']}" if x in ENTITIES else x

    sel_entity = st.selectbox("Filter Entity", entity_options, format_func=fmt_entity)
    threshold  = st.slider("Gap Tolerance (%)", 0.0, 5.0, 0.5, 0.1)

    st.divider()
    period_label = st.selectbox("Period", ["DEC 2025", "Q3 2025", "Q2 2025", "Q1 2025", "FY 2024"])
    st.divider()

    # ── File upload ─────────────────────────────────────────
    st.markdown("**Upload IC Transactions**")
    uploaded = st.file_uploader("CSV or Excel", type=["csv", "xlsx"])
    if uploaded:
        parsed_df, err = parse_uploaded_file(uploaded, period_label, "ACTUAL")
        if err:
            st.error(err)
        else:
            if st.button("✅ Load uploaded data", use_container_width=True):
                save_transactions_to_db(parsed_df)
                reset_all_reviews()
                df = parsed_df
                reviews = {}
                st.success(f"Loaded {len(parsed_df)} transactions from upload.")
                st.rerun()

    st.download_button(
        "⬇️ Download sample upload file",
        data=build_sample_csv(),
        file_name="IC_Source_Upload_Sample.csv",
        mime="text/csv",
        use_container_width=True,
    )

    st.divider()
    if st.button("🔄 Reset to sample data", use_container_width=True):
        seed_df = generate_sample_transactions()
        save_transactions_to_db(seed_df)
        reset_all_reviews()
        st.rerun()

# ─────────────────────────────────────────────────────────────
# FILTER
# ─────────────────────────────────────────────────────────────

df = load_transactions_from_db()
reviews = load_reviews_from_db()

filtered = df.copy()
if sel_entity != "All Entities":
    filtered = filtered[(filtered["seller"] == sel_entity) | (filtered["buyer"] == sel_entity)]

filtered["Review Status"] = filtered["id"].map(lambda x: reviews.get(x, {}).get("status", "Pending"))

# ─────────────────────────────────────────────────────────────
# HEADER
# ─────────────────────────────────────────────────────────────

st.markdown("## ⚖️ Intercompany Elimination Engine")
st.markdown(f"**Apex Group · {period_label} · [Elimination] Value** — {len(ELIMINATION_RULES)} consolidation rules · Human-in-the-Loop enabled · SQLite persistence active")

approved_n = sum(1 for v in reviews.values() if v.get("status") == "Approved")
rejected_n = sum(1 for v in reviews.values() if v.get("status") == "Rejected")
pending_n  = len(df) - approved_n - rejected_n

b1, b2, b3, b4 = st.columns(4)
b1.metric("Pending Review", pending_n, delta_color="off")
b2.metric("Approved",       approved_n, delta=f"{approved_n/max(len(df),1)*100:.0f}%")
b3.metric("Rejected",       rejected_n, delta_color="inverse")
b4.metric("Ready to Post",  approved_n,
          delta="✅ Full period approved" if approved_n == len(df) else "Awaiting sign-off")
st.divider()

# ─────────────────────────────────────────────────────────────
# TABS — 6 tabs (removed ROI, Rules Reference, Entity Hierarchy)
# ─────────────────────────────────────────────────────────────

tabs = st.tabs([
    "📊 Dashboard",
    "🔍 IC Matching",
    "⚙️ Elimination Engine",
    "📋 Journal Entries",
    "👤 Review & Approve",
    "📁 Audit Trail",
])

# ════════════════════════════════════════════════════
# TAB 1 — DASHBOARD
# ════════════════════════════════════════════════════
with tabs[0]:
    total_vol       = df["seller_usd"].sum()
    matched_count   = len(df[df["match_status"] == "Matched"])
    exception_count = len(df[df["gap_pct"] > threshold])

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total IC Volume (USD)", f"${total_vol/1e6:.2f}M")
    c2.metric("Transactions",          str(len(df)))
    c3.metric("Matched",               f"{matched_count}/{len(df)}", f"{matched_count/max(len(df),1)*100:.0f}%")
    c4.metric("Exceptions",            str(exception_count), delta=f">{threshold}% gap", delta_color="inverse")

    source_tag = df["source"].iloc[0] if "source" in df.columns else "sample"
    st.caption(f"Data source: **{source_tag}** · Period: {period_label} · Last loaded: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    st.divider()
    col_a, col_b = st.columns(2)

    with col_a:
        st.markdown('<p class="section-header">IC Volume by Category</p>', unsafe_allow_html=True)
        cat_df = df.groupby("category")["seller_usd"].sum().reset_index().sort_values("seller_usd", ascending=True)
        fig = px.bar(cat_df, x="seller_usd", y="category", orientation="h",
                     color="category",
                     color_discrete_map={c: CATEGORY_COLORS.get(c, "#888") for c in cat_df["category"]},
                     labels={"seller_usd": "Amount (USD)", "category": ""})
        fig.update_layout(height=320, showlegend=False, margin=dict(l=0,r=0,t=10,b=10),
                          paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig, use_container_width=True)

    with col_b:
        st.markdown('<p class="section-header">Review Status</p>', unsafe_allow_html=True)
        rev_vals = {"Approved": approved_n, "Pending": pending_n, "Rejected": rejected_n}
        rev_vals = {k: v for k, v in rev_vals.items() if v > 0}
        if rev_vals:
            colors_rev = {"Approved": "#1D9E75", "Pending": "#E8A838", "Rejected": "#D94F3D"}
            fig2 = go.Figure(go.Pie(
                labels=list(rev_vals.keys()), values=list(rev_vals.values()),
                marker_colors=[colors_rev[k] for k in rev_vals],
                hole=0.55, textinfo="label+percent"
            ))
            fig2.update_layout(height=320, showlegend=False, margin=dict(l=0,r=0,t=10,b=10),
                               paper_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig2, use_container_width=True)

    st.markdown('<p class="section-header">Transaction Summary</p>', unsafe_allow_html=True)
    disp = filtered[["id","seller","buyer","rule_code","rule_label","description",
                      "seller_usd","buyer_usd","gap_pct","match_status","Review Status"]].copy()
    disp.columns = ["ID","Seller","Buyer","Rule","Rule Label","Description",
                    "Seller USD","Buyer USD","Gap %","Match","Review"]
    disp["Seller USD"] = disp["Seller USD"].map("${:,.0f}".format)
    disp["Buyer USD"]  = disp["Buyer USD"].map("${:,.0f}".format)
    disp["Gap %"]      = disp["Gap %"].map("{:.2f}%".format)

    def _cs(v):
        return {"Matched":"background-color:#e8f5e9;color:#1A7A4A",
                "Tolerance":"background-color:#fff8e1;color:#A86800",
                "Exception":"background-color:#ffebee;color:#C62828"}.get(v,"")
    def _cr(v):
        return {"Approved":"background-color:#D1FAE5;color:#065F46;font-weight:600",
                "Rejected":"background-color:#FEE2E2;color:#991B1B;font-weight:600",
                "Pending":"background-color:#FFF3CD;color:#856404"}.get(v,"")

    st.dataframe(disp.style.map(_cs, subset=["Match"]).map(_cr, subset=["Review"]),
                 use_container_width=True, height=360)

# ════════════════════════════════════════════════════
# TAB 2 — IC MATCHING
# ════════════════════════════════════════════════════
with tabs[1]:
    st.markdown("### Intercompany Matching Engine")
    st.caption("Bilateral matching between entity-reported and counterparty-reported balances")

    mdf = filtered[["id","seller","buyer","rule_code","seller_usd","buyer_usd","gap_usd","gap_pct","match_status"]].copy()
    mdf["Confidence"] = mdf["gap_pct"].apply(lambda g: f"{max(0, round(100 - g * 20, 1))}%")
    exceptions = mdf[mdf["gap_pct"] > threshold]
    matched    = mdf[mdf["gap_pct"] <= threshold]

    m1, m2, m3 = st.columns(3)
    m1.metric("Auto-Matched",  len(matched))
    m2.metric("Exceptions",    len(exceptions), delta_color="inverse")
    m3.metric("Total Gap USD", f"${mdf['gap_usd'].sum():,.0f}")

    st.divider()
    tm, te = st.tabs(["✅ Matched", "⚠️ Exceptions"])

    with tm:
        md = matched.copy()
        for c in ["seller_usd","buyer_usd","gap_usd"]:
            md[c] = md[c].map("${:,.0f}".format)
        md["gap_pct"] = md["gap_pct"].map("{:.3f}%".format)
        st.dataframe(md, use_container_width=True)

    with te:
        if len(exceptions) > 0:
            for _, row in exceptions.iterrows():
                seller_name = ENTITIES.get(row["seller"], {}).get("name", row["seller"])
                buyer_name  = ENTITIES.get(row["buyer"],  {}).get("name", row["buyer"])
                s_ccy = df[df["id"]==row["id"]]["seller_ccy"].values[0] if len(df[df["id"]==row["id"]]) else ""
                b_ccy = df[df["id"]==row["id"]]["buyer_ccy"].values[0]  if len(df[df["id"]==row["id"]]) else ""
                with st.expander(f"⚠️ {row['id']} — {seller_name} ↔ {buyer_name} — Gap: {row['gap_pct']:.2f}%"):
                    cc1, cc2, cc3 = st.columns(3)
                    cc1.metric("Seller USD", f"${row['seller_usd']:,.0f}")
                    cc2.metric("Buyer USD",  f"${row['buyer_usd']:,.0f}")
                    cc3.metric("Gap USD",    f"${row['gap_usd']:,.0f}")
                    st.info(f"**AI Root Cause:** Gap of {row['gap_pct']:.2f}% on `{row['rule_code']}`. "
                            f"Possible causes: FX timing difference ({s_ccy}→{b_ccy}), "
                            f"period cut-off mismatch, or accrual vs cash basis. "
                            f"Review posting dates and FX rates before elimination.")
        else:
            st.success("All intercompany balances within tolerance. Ready for elimination.")

# ════════════════════════════════════════════════════
# TAB 3 — ELIMINATION ENGINE
# ════════════════════════════════════════════════════
with tabs[2]:
    st.markdown("### Elimination Engine")
    st.caption("Select any transaction to compute elimination journal entries")

    opts = filtered["id"].tolist()
    if not opts:
        st.warning("No transactions match the current filter.")
        st.stop()

    def _fmt(x):
        row_ = filtered[filtered["id"]==x]
        return f"{x} — {row_['description'].values[0]}" if len(row_) > 0 else x

    sel_id  = st.selectbox("Select Transaction", opts, format_func=_fmt)
    sel_row = filtered[filtered["id"] == sel_id].iloc[0]

    r1, r2, r3, r4 = st.columns(4)
    r1.metric("Rule",       sel_row["rule_code"])
    r2.metric("Amount USD", f"${sel_row['seller_usd']:,.0f}")
    r3.metric("Seller",     ENTITIES.get(sel_row["seller"], {}).get("name", sel_row["seller"]))
    r4.metric("Buyer",      ENTITIES.get(sel_row["buyer"],  {}).get("name", sel_row["buyer"]))

    rule_info  = ELIMINATION_RULES.get(sel_row["rule_code"], {})
    rev_status = reviews.get(sel_id, {}).get("status", "Pending")
    rev_color  = {"Approved":"#1D9E75","Rejected":"#D94F3D","Pending":"#E8A838"}.get(rev_status,"#888")
    st.markdown(f'**{rule_info.get("label","—")}** &nbsp; '
                f'<span style="background:{rev_color};color:#fff;padding:2px 10px;'
                f'border-radius:12px;font-size:12px;font-weight:700">{rev_status}</span>',
                unsafe_allow_html=True)
    st.info(rule_info.get("description",""))

    st.divider()
    st.markdown("#### Computed Journal Entries — [Elimination] Value")
    entries  = compute_elimination(sel_row)
    entry_df = pd.DataFrame(entries)
    entry_df["Amount"] = entry_df["Amount"].map("${:,.0f}".format)

    def _drcr(row):
        return ["background-color:#fff4f4"]*len(row) if row["Dr/Cr"]=="Dr" else ["background-color:#f4fff8"]*len(row)

    st.dataframe(entry_df.style.apply(_drcr, axis=1), use_container_width=True)
    st.caption("🔴 Debit | 🟢 Credit | All entries post to [Elimination] value")

    st.divider()
    st.markdown("#### Elimination Gate Conditions")
    g1, g2, g3 = st.columns(3)
    with g1:
        st.markdown("**Blocked if:**")
        st.markdown("- No ICP partner assigned\n- Entities not under same parent\n- Entity IS parent of counterparty")
    with g2:
        st.markdown(f"**PCon (Seller):** {sel_row['pcon_seller']*100:.0f}%")
        st.markdown(f"**PCon (Buyer):** {sel_row['pcon_buyer']*100:.0f}%")
        st.markdown(f"**Effective %:** {min(sel_row['pcon_seller'],sel_row['pcon_buyer'])*100:.0f}%")
    with g3:
        st.markdown(f"**Match Status:** {sel_row['match_status']}")
        st.markdown(f"**Review Status:** {rev_status}")
        st.markdown(f"**Source:** {sel_row.get('source','sample')}")

# ════════════════════════════════════════════════════
# TAB 4 — JOURNAL ENTRIES
# ════════════════════════════════════════════════════
with tabs[3]:
    st.markdown("### All Journal Entries — [Elimination] Value")
    st.caption(f"Complete postings for {period_label} · Apex Group")

    all_entries = []
    for _, row in filtered.iterrows():
        for e in compute_elimination(row):
            all_entries.append({
                "Txn ID":        row["id"],
                "Seller":        ENTITIES.get(row["seller"], {}).get("name", row["seller"]),
                "Buyer":         ENTITIES.get(row["buyer"],  {}).get("name", row["buyer"]),
                "Rule Code":     row["rule_code"],
                "Account":       e["Account"],
                "Value":         e["Value"],
                "Dr/Cr":         e["Dr/Cr"],
                "Amount USD":    e["Amount"],
                "Audit Code":    e["Audit"],
                "Review Status": reviews.get(row["id"], {}).get("status", "Pending"),
            })

    je_df    = pd.DataFrame(all_entries)
    total_dr = je_df[je_df["Dr/Cr"]=="Dr"]["Amount USD"].sum()
    total_cr = je_df[je_df["Dr/Cr"]=="Cr"]["Amount USD"].sum()
    balance  = total_dr + total_cr

    j1, j2, j3 = st.columns(3)
    j1.metric("Total Debits",  f"${abs(total_dr):,.0f}")
    j2.metric("Total Credits", f"${abs(total_cr):,.0f}")
    j3.metric("Balance",       f"${balance:,.0f}",
              delta="✅ Balanced" if abs(balance) < 1 else "⚠️ Out of Balance")

    je_disp = je_df.copy()
    je_disp["Amount USD"] = je_disp["Amount USD"].map("${:,.0f}".format)
    st.dataframe(je_disp, use_container_width=True, height=480)

    buf_je = io.BytesIO()
    je_df.to_excel(buf_je, index=False)
    st.download_button("⬇️ Download Journal Entries (Excel)", buf_je.getvalue(),
                       file_name=f"IC_Eliminations_{period_label.replace(' ','_')}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# ════════════════════════════════════════════════════
# TAB 5 — REVIEW & APPROVE (HITL)
# ════════════════════════════════════════════════════
with tabs[4]:
    st.markdown("### Human-in-the-Loop — Review & Approve")
    st.caption("Every elimination requires explicit sign-off before posting. All decisions persist in SQLite.")

    rv1, rv2, rv3, rv4 = st.columns(4)
    rv1.metric("Total Transactions", len(df))
    rv2.metric("Pending",  pending_n,  delta_color="off")
    rv3.metric("Approved", approved_n, delta=f"{approved_n/max(len(df),1)*100:.0f}% complete")
    rv4.metric("Rejected", rejected_n, delta_color="inverse")

    st.divider()

    # ── Reviewer identity (inline, not sidebar) ──────────────
    ri_col1, ri_col2 = st.columns(2)
    reviewer_name = ri_col1.text_input("Your Name", value="Group Controller", key="rev_name")
    reviewer_role = ri_col2.selectbox("Role",
        ["Group Controller","Regional CFO","Finance Director",
         "Treasury Controller","External Auditor","CFO"], key="rev_role")

    st.divider()

    # ── Bulk actions ─────────────────────────────────────────
    st.markdown("#### Bulk Actions")
    ba1, ba2 = st.columns(2)
    with ba1:
        if st.button("✅ Approve All Matched", use_container_width=True):
            for _, row in df[df["match_status"]=="Matched"].iterrows():
                upsert_review(row["id"], "Approved",
                              f"{reviewer_name} ({reviewer_role})",
                              datetime.now().strftime("%Y-%m-%d %H:%M"),
                              "Bulk approval — all matched transactions")
            st.rerun()
    with ba2:
        if st.button("🔄 Reset All to Pending", use_container_width=True):
            reset_all_reviews()
            st.rerun()

    st.divider()
    filter_rev = st.radio("Show", ["All","Pending","Approved","Rejected"], horizontal=True)

    reviews = load_reviews_from_db()

    # ── Individual review cards ───────────────────────────────
    for _, row in filtered.iterrows():
        txn_id     = row["id"]
        rev_data   = reviews.get(txn_id, {})
        rev_status = rev_data.get("status", "Pending")

        if filter_rev != "All" and rev_status != filter_rev:
            continue

        css_class  = {"Approved":"hitl-approved","Rejected":"hitl-rejected","Pending":"hitl-pending"}.get(rev_status,"hitl-pending")
        badge_cls  = {"Approved":"badge-approved","Rejected":"badge-rejected","Pending":"badge-pending"}.get(rev_status,"badge-pending")
        badge_icon = {"Approved":"✅","Rejected":"❌","Pending":"⏳"}.get(rev_status,"⏳")
        s_name = ENTITIES.get(row["seller"],{}).get("name",row["seller"])
        b_name = ENTITIES.get(row["buyer"],{}).get("name",row["buyer"])

        st.markdown(f"""
<div class="hitl-card {css_class}">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
    <div>
      <strong style="font-size:15px;">{txn_id}</strong> &nbsp;·&nbsp; {row['description']}
      &nbsp;&nbsp;<span class="hitl-badge {badge_cls}">{badge_icon} {rev_status}</span>
    </div>
    <div style="font-size:13px;color:#666;">{row['rule_code']} &nbsp;|&nbsp; {row['rule_label']}</div>
  </div>
  <div style="font-size:13px;color:#555;margin-bottom:4px;">
    <strong>Seller:</strong> {s_name} ({row['seller_ccy']}) &nbsp;→&nbsp;
    <strong>Buyer:</strong> {b_name} ({row['buyer_ccy']})
  </div>
  <div style="font-size:13px;color:#555;">
    <strong>Amount:</strong> ${row['seller_usd']:,.0f} USD &nbsp;|&nbsp;
    <strong>Match:</strong> {row['match_status']} &nbsp;|&nbsp;
    <strong>Gap:</strong> {row['gap_pct']:.2f}%
  </div>
</div>""", unsafe_allow_html=True)

        with st.expander(f"📋 View Entries & Action — {txn_id}"):
            col_je, col_act = st.columns([3, 2])

            with col_je:
                st.markdown("**Proposed Journal Entries**")
                e_df = pd.DataFrame(compute_elimination(row))
                e_df["Amount"] = e_df["Amount"].map("${:,.0f}".format)
                st.dataframe(e_df[["Account","Dr/Cr","Amount","Value","Audit"]],
                             use_container_width=True, height=200)
                st.info(ELIMINATION_RULES.get(row["rule_code"],{}).get("description",""))
                if row["match_status"] == "Exception":
                    st.warning(f"⚠️ Gap of {row['gap_pct']:.2f}% — review carefully before approving.")

            with col_act:
                st.markdown("**Action**")
                if rev_status != "Pending":
                    st.markdown(f"**By:** {rev_data.get('reviewer','—')}")
                    st.markdown(f"**At:** {rev_data.get('ts','—')}")
                    if rev_data.get("comment"):
                        st.markdown(f"*{rev_data['comment']}*")
                    if st.button("🔄 Reset", key=f"rst_{txn_id}"):
                        reset_review(txn_id)
                        st.rerun()
                else:
                    note = st.text_area("Comment", key=f"note_{txn_id}",
                                        placeholder="Optional note...", height=70)
                    apc, rjc = st.columns(2)
                    with apc:
                        if st.button("✅ Approve", key=f"app_{txn_id}", use_container_width=True):
                            upsert_review(txn_id, "Approved",
                                          f"{reviewer_name} ({reviewer_role})",
                                          datetime.now().strftime("%Y-%m-%d %H:%M"),
                                          note or "Approved")
                            st.rerun()
                    with rjc:
                        if st.button("❌ Reject", key=f"rej_{txn_id}", use_container_width=True):
                            upsert_review(txn_id, "Rejected",
                                          f"{reviewer_name} ({reviewer_role})",
                                          datetime.now().strftime("%Y-%m-%d %H:%M"),
                                          note or "Rejected — requires investigation")
                            st.rerun()

    # ── Close readiness ───────────────────────────────────────
    st.divider()
    st.markdown("#### Period Close Readiness")
    reviews = load_reviews_from_db()
    ap_now = sum(1 for v in reviews.values() if v.get("status")=="Approved")
    rj_now = sum(1 for v in reviews.values() if v.get("status")=="Rejected")
    pd_now = len(df) - ap_now - rj_now
    pct    = ap_now / max(len(df), 1) * 100

    st.progress(pct / 100)
    st.caption(f"{pct:.0f}% approved — {pd_now} pending, {rj_now} rejected")

    if pct == 100 and rj_now == 0:
        st.success("✅ All eliminations approved. Period close ready.")
    elif rj_now > 0:
        st.error(f"❌ {rj_now} rejection(s) must be resolved before period close.")
    else:
        st.warning(f"⏳ {pd_now} transaction(s) awaiting review.")

    # Download review log
    rl = []
    for tid, rv in reviews.items():
        r = df[df["id"]==tid]
        if len(r) == 0: continue
        r = r.iloc[0]
        rl.append({"Txn ID":tid,"Description":r["description"],
                   "Seller":r["seller"],"Buyer":r["buyer"],
                   "Rule":r["rule_code"],"Amount":f"${r['seller_usd']:,.0f}",
                   "Match":r["match_status"],"Review":rv.get("status",""),
                   "By":rv.get("reviewer",""),"At":rv.get("ts",""),"Note":rv.get("comment","")})
    if rl:
        rl_df   = pd.DataFrame(rl)
        buf_rl  = io.BytesIO()
        rl_df.to_excel(buf_rl, index=False)
        st.download_button("⬇️ Download Review Log", buf_rl.getvalue(),
                           file_name=f"IC_ReviewLog_{period_label.replace(' ','_')}.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# ════════════════════════════════════════════════════
# TAB 6 — AUDIT TRAIL
# ════════════════════════════════════════════════════
with tabs[5]:
    st.markdown("### Audit Trail")
    st.caption("Full decision log — matching → rule → journal entry → human review → post")

    reviews = load_reviews_from_db()
    audit   = []
    for _, row in filtered.iterrows():
        rv = reviews.get(row["id"], {})
        for e in compute_elimination(row):
            audit.append({
                "Txn ID":      row["id"],
                "Seller":      ENTITIES.get(row["seller"],{}).get("name",row["seller"]),
                "Buyer":       ENTITIES.get(row["buyer"],{}).get("name",row["buyer"]),
                "Rule":        row["rule_code"],
                "Account":     e["Account"],
                "Dr/Cr":       e["Dr/Cr"],
                "Amount USD":  f"${e['Amount']:,.0f}",
                "Value":       e["Value"],
                "Audit Code":  e["Audit"],
                "Review":      rv.get("status","Pending"),
                "Reviewed By": rv.get("reviewer","Awaiting"),
                "At":          rv.get("ts","—"),
                "Comment":     rv.get("comment",""),
            })

    audit_df = pd.DataFrame(audit)
    st.dataframe(audit_df, use_container_width=True, height=460)

    a1, a2, a3, a4 = st.columns(4)
    a1.metric("Total Entries",  len(audit_df))
    a2.metric("Rules Fired",    len(audit_df["Rule"].unique()))
    a3.metric("Approved",       len(audit_df[audit_df["Review"]=="Approved"]))
    a4.metric("Pending",        len(audit_df[audit_df["Review"]=="Pending"]))

    buf_at = io.BytesIO()
    audit_df.to_excel(buf_at, index=False)
    st.download_button("⬇️ Download Audit Trail (Excel)", buf_at.getvalue(),
                       file_name=f"IC_AuditTrail_{period_label.replace(' ','_')}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    st.divider()
    st.markdown("#### Accountability Chain")
    st.markdown("""
| Step | Input | Process | Output | Owner | Gate |
|---|---|---|---|---|---|
| 1 | Entity IC balances | Bilateral matching | Matched / Exception list | System | Auto |
| 2 | Account rule code | Rule determination | Elimination rule code | System | Auto |
| 3 | Rule + amounts | Consolidation rules engine | Proposed journal entries | System | Auto |
| 4 | Proposed journals | **Human review & approval** | Approved / Rejected | **Named Controller** | 👤 HITL |
| 5 | Approved journals | Ledger posting | Posted [Elimination] entries | Finance System | Post HITL |
| 6 | Posted entries | Consolidation proof | Group financial statements | CFO / Auditor | Final |
""")
    st.info("👤 **Step 4 is a hard gate.** No elimination posts without a named, timestamped, persisted approval. All decisions survive browser refresh and session restart.")
