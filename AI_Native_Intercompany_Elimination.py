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
    page_title="IC Elimination Engine — Helios Chemicals Group",
    layout="wide",
    page_icon="⚖️"
)

# ─────────────────────────────────────────────────────────────
# SQLITE — Persistent state layer
# ─────────────────────────────────────────────────────────────

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ic_helios.db")

def init_db():
    con = sqlite3.connect(DB_PATH, timeout=10)
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
            flow TEXT, custom3_ccy TEXT,
            account_code TEXT, account_desc TEXT,
            icp_seller TEXT, icp_buyer TEXT,
            source TEXT DEFAULT 'helios'
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
    con = sqlite3.connect(DB_PATH, timeout=10)
    df = pd.read_sql("SELECT * FROM transactions", con)
    con.close()
    return df

def save_transactions_to_db(df):
    con = sqlite3.connect(DB_PATH, timeout=10)
    df.to_sql("transactions", con, if_exists="replace", index=False)
    con.commit()
    con.close()

def load_reviews_from_db():
    con = sqlite3.connect(DB_PATH, timeout=10)
    rows = con.execute("SELECT txn_id, status, reviewer, review_ts, comment FROM reviews").fetchall()
    con.close()
    return {r[0]: {"status": r[1], "reviewer": r[2], "ts": r[3], "comment": r[4]} for r in rows}

def upsert_review(txn_id, status, reviewer, ts, comment):
    con = sqlite3.connect(DB_PATH, timeout=10)
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
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.execute("DELETE FROM reviews WHERE txn_id=?", (txn_id,))
    con.commit()
    con.close()

def reset_all_reviews():
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.execute("DELETE FROM reviews")
    con.commit()
    con.close()

init_db()

# ─────────────────────────────────────────────────────────────
# HELIOS ENTITIES — sourced from ENTITY_HIERARCHY sheet
# ─────────────────────────────────────────────────────────────

ENTITIES = {
    "HELIOS": {"name": "Helios Chemicals Group",           "method": "HOLDING",      "pcon": 1.00, "pown": 1.00, "currency": "USD"},
    "3046":   {"name": "Helios Mena Chemicals Limited",    "method": "GLOBAL",       "pcon": 1.00, "pown": 1.00, "currency": "USD"},
    "2001":   {"name": "NOVAHOLD",                         "method": "GLOBAL",       "pcon": 1.00, "pown": 1.00, "currency": "USD"},
    "2015":   {"name": "Novahold International Cyprus",    "method": "GLOBAL",       "pcon": 1.00, "pown": 1.00, "currency": "USD"},
    "5001":   {"name": "Delta Chem Industries",            "method": "GLOBAL",       "pcon": 1.00, "pown": 1.00, "currency": "USD"},
    "5004":   {"name": "Austral Nitro SPA",                "method": "GLOBAL",       "pcon": 0.51, "pown": 0.51, "currency": "XAF"},
    "5005":   {"name": "Helios MEPCO",                     "method": "GLOBAL",       "pcon": 1.00, "pown": 1.00, "currency": "USD"},
    "5007":   {"name": "Helios Chemical Trading Ltd",      "method": "GLOBAL",       "pcon": 1.00, "pown": 1.00, "currency": "USD"},
    "5008":   {"name": "Meridian Base Industries",         "method": "GLOBAL",       "pcon": 0.60, "pown": 0.60, "currency": "USD"},
    "5009":   {"name": "Oratech Plant Maintenance",        "method": "GLOBAL",       "pcon": 1.00, "pown": 1.00, "currency": "USD"},
    "5037":   {"name": "Helios Trade Holding BV",          "method": "GLOBAL",       "pcon": 1.00, "pown": 1.00, "currency": "USD"},
    "5038":   {"name": "Helios Trade & Supply BV",         "method": "GLOBAL",       "pcon": 1.00, "pown": 1.00, "currency": "USD"},
    "5062":   {"name": "Pinnacle Engineering LLC",         "method": "GLOBAL",       "pcon": 1.00, "pown": 1.00, "currency": "XOF"},
    "5066":   {"name": "PSK Holding",                      "method": "GLOBAL",       "pcon": 1.00, "pown": 1.00, "currency": "USD"},
    "5067":   {"name": "Amiral Clean Fuels Overseas Ltd",  "method": "GLOBAL",       "pcon": 1.00, "pown": 1.00, "currency": "USD"},
    "5071":   {"name": "Helios Notore Holding Ltd",        "method": "GLOBAL",       "pcon": 1.00, "pown": 1.00, "currency": "USD"},
    "5072":   {"name": "Helios Chemicals plc",             "method": "GLOBAL",       "pcon": 1.00, "pown": 1.00, "currency": "USD"},
    "5073":   {"name": "Helios Distribution Ltd",          "method": "GLOBAL",       "pcon": 1.00, "pown": 1.00, "currency": "USD"},
    "5074":   {"name": "Chemicals Export Holding I Ltd",   "method": "GLOBAL",       "pcon": 1.00, "pown": 1.00, "currency": "USD"},
    "5075":   {"name": "Helios France SAS",                "method": "GLOBAL",       "pcon": 1.00, "pown": 1.00, "currency": "EUR"},
    "5076":   {"name": "Regal Chemicals Industries",       "method": "GLOBAL",       "pcon": 0.42, "pown": 0.42, "currency": "USD"},
    "5083":   {"name": "Helios International Trading LLC", "method": "GLOBAL",       "pcon": 1.00, "pown": 1.00, "currency": "SAR"},
    "4011":   {"name": "Helios Mena",                      "method": "GLOBAL",       "pcon": 1.00, "pown": 1.00, "currency": "EUR"},
    "4030":   {"name": "Chemicals 1 Holding Limited",      "method": "GLOBAL",       "pcon": 1.00, "pown": 1.00, "currency": "USD"},
    "4031":   {"name": "Chemicals 2 Holding Limited",      "method": "GLOBAL",       "pcon": 1.00, "pown": 1.00, "currency": "USD"},
    "4135":   {"name": "Helios Mena BV",                   "method": "GLOBAL",       "pcon": 1.00, "pown": 1.00, "currency": "USD"},
    "4336":   {"name": "Helios Green Investment",          "method": "GLOBAL",       "pcon": 1.00, "pown": 1.00, "currency": "SAR"},
    "4039":   {"name": "Helios Holding Investment Ltd",    "method": "GLOBAL",       "pcon": 1.00, "pown": 1.00, "currency": "USD"},
    "4242":   {"name": "Helios Engineering Services LLC",  "method": "GLOBAL",       "pcon": 1.00, "pown": 1.00, "currency": "USD"},
    "4045":   {"name": "Redpoint Holdings",                "method": "GLOBAL",       "pcon": 1.00, "pown": 1.00, "currency": "USD"},
}

# FX rates to USD — includes all Custom3 CCY codes from metadata
FX_RATES = {
    "USD": 1.0000, "EUR": 1.0800, "GBP": 1.2700,
    "XAF": 0.001667,   # CFA Franc BEAC — 1 USD = 600 XAF (Austral Nitro / Region B)
    "XOF": 0.001527,   # CFA Franc BCEAO — 1 USD = 655 XOF (Pinnacle Engineering / Region C)
    "SAR": 0.2670,     # Saudi Riyal (Helios Green / Gulf entities)
    "CNY": 0.1380,     # Chinese Yuan
    "SGD": 0.7410,     # Singapore Dollar
    "KRW": 0.00074,    # South Korean Won
}

# Cross-currency pairs always have a legitimate FX translation gap.
# These are treated as FX_DIFF status (not Exception) when gap > threshold.
CROSS_CCY_STATUS = "FX_Diff"

# ─────────────────────────────────────────────────────────────
# ELIMINATION RULES — HFM UD3 attribute mapping
# ─────────────────────────────────────────────────────────────

ELIMINATION_RULES = {
    "EQ-001":  {"label": "Equity Split — Group vs Minority",         "category": "Equity",       "description": "Splits equity balance between group and NCI. Posts to Group Reserves (POwn) and NCI Reserves (PMin) at PCon percentages. Used for share capital of Delta Chem, Austral Nitro."},
    "EQ-002":  {"label": "Translation Reserve — Equity",             "category": "Equity",       "description": "Handles FX conversion reserves from equity accounts. Relevant for XAF and XOF entities."},
    "EQ-003":  {"label": "Other Comprehensive Income Split",         "category": "Equity/OCI",   "description": "Allocates OCI between group and NCI portions."},
    "EQ-004":  {"label": "Net Income Allocation — Group vs NCI",     "category": "P&L",          "description": "Allocates current period net income between group and minority interest. Used for Delta Chem retained earnings allocation."},
    "EQ-005":  {"label": "FX Impact on Net Income",                  "category": "P&L/FX",       "description": "Posts FX impact on net income to conversion reserve accounts. Active on XAF and XOF entities."},
    "INV-001": {"label": "Investment Elimination",                   "category": "Investment",   "description": "Eliminates NOVAHOLD's investment in Delta Chem, Austral Nitro, Helios Trade BV, Pinnacle Engineering against subsidiary equity. Posts to [Elimination] at PCon."},
    "INV-002": {"label": "Historic Investment Carry-forward",        "category": "Investment",   "description": "Carries forward prior-period investment eliminations."},
    "IC-001":  {"label": "Standard Intercompany Elimination",        "category": "Intercompany", "description": "Bilateral elimination at Min(PCon). Used for management fees, loan interest, receivables/payables, profit transfers (ecremage), and MTM reversals across Helios entities."},
    "IC-002":  {"label": "Reciprocal IC Elimination",                "category": "Intercompany", "description": "Two-sided elimination: Delta Chem product sales to Helios Trade BV. Seller account eliminated at Min(PCon), buyer account posted to counterparty dimension."},
    "IC-003":  {"label": "Conditional IC Elimination",               "category": "Intercompany", "description": "Fires only when balance > 0. Prevents double elimination on service arrangements."},
    "IC-004":  {"label": "IC Provision Elimination",                 "category": "Intercompany", "description": "Eliminates intragroup allowances for doubtful debts. Used for Helios Group provision against Helios Trade BV balance."},
    "IC-005":  {"label": "Historic IC Provision Carry-forward",      "category": "Intercompany", "description": "Historical carry-forward of IC provision eliminations."},
    "GW-001":  {"label": "Goodwill on Acquisition",                  "category": "Goodwill",     "description": "Goodwill arising on Regal Chemicals Industries acquisition. Calculated at PCon × ICPPCon (0.42 × 1.00 = 0.42). Carrying value 441.2M USD."},
    "GW-002":  {"label": "Historic Goodwill Carry-forward",          "category": "Goodwill",     "description": "Carries forward prior-period goodwill balances."},
    "GW-003":  {"label": "Goodwill Amortisation / Impairment",       "category": "Goodwill",     "description": "Eliminates goodwill depreciation and impairment charges."},
    "GW-004":  {"label": "Historic Goodwill Amortisation",           "category": "Goodwill",     "description": "Historical carry-forward of goodwill amortisation."},
    "DIV-001": {"label": "Paid Dividend Elimination",                "category": "Dividends",    "description": "Eliminates dividends paid by Delta Chem and Austral Nitro to NOVAHOLD. Posts to Group Reserves (POwn) and NCI Reserves (PMin). Austral Nitro NCI = 49%."},
    "DIV-002": {"label": "Scope Variation — Paid Dividends",         "category": "Dividends",    "description": "Reclassifies paid dividend eliminations on scope changes."},
    "DIV-003": {"label": "Withholding Tax FX Adjustment",            "category": "Dividends/FX", "description": "Posts FX movements on withholding tax to conversion reserves."},
    "DIV-004": {"label": "Dividend Income Elimination",              "category": "Dividends",    "description": "Eliminates dividend income received from group subsidiaries."},
    "DIV-005": {"label": "Scope Variation — Dividend Income",        "category": "Dividends",    "description": "Mirrors paid-dividend scope variation on the income side."},
    "DIV-006": {"label": "Dividend Income FX Adjustment",            "category": "Dividends/FX", "description": "Posts FX impact on dividend income to conversion reserves."},
    "STK-001": {"label": "Unrealised Profit in Inventory",           "category": "Stock Margin", "description": "Eliminates unrealised profit embedded in Helios Trade BV's inventory from Delta Chem sales. Applied at PCon_Seller × PCon_Buyer."},
    "STK-002": {"label": "Historic Unrealised Profit Carry-forward", "category": "Stock Margin", "description": "Carries forward unrealised profit elimination."},
    "AUC-001": {"label": "Intragroup Construction Revenue",          "category": "AUC/CapEx",    "description": "Eliminates construction revenue recognised by Helios Engineering Services LLC (4242) on intragroup AUC contracts to Delta Chem. Posts to revenue P&L and BS link account."},
    "AUC-002": {"label": "Historic Construction Revenue",            "category": "AUC/CapEx",    "description": "Historical carry-forward of construction revenue elimination."},
    "AUC-003": {"label": "Intragroup Construction Cost",             "category": "AUC/CapEx",    "description": "Mirror of AUC-001 on the cost side."},
    "AUC-004": {"label": "Historic Construction Cost",               "category": "AUC/CapEx",    "description": "Historical carry-forward of construction cost elimination."},
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

# ─────────────────────────────────────────────────────────────
# HELIOS SOURCE DATA — loaded from IC_SOURCE_UPLOAD sheet
# ─────────────────────────────────────────────────────────────

HELIOS_TRANSACTIONS = [
    # (id, seller, buyer, rule_code, account_code, account_desc,
    #  icp_seller, icp_buyer, flow, custom3_ccy, description,
    #  seller_ccy, buyer_ccy, seller_amt, buyer_amt, pcon_seller, pcon_buyer)
    ("IC-001","2001","5001","INV-001","30150001","Investment in Subsidiaries — Delta Chem",
     "5001","2001","CLO","IC_USD","Investment elimination — NOVAHOLD holding in Delta Chem Industries",
     "USD","USD",2580647846,2580647846,1.00,1.00),
    ("IC-002","2001","5004","INV-001","30150001","Investment in Subsidiaries — Austral Nitro",
     "5004","2001","CLO","IC_USD","Investment elimination — NOVAHOLD holding in Austral Nitro SPA",
     "USD","XAF",361900445,53621265890,1.00,1.00),
    ("IC-003","2001","5038","INV-001","30150001","Investment in Subsidiaries — Helios Trade BV",
     "5038","2001","CLO","IC_USD","Investment elimination — NOVAHOLD holding in Helios Trade & Supply BV",
     "USD","USD",9777162,9777162,1.00,1.00),
    ("IC-004","2001","5062","INV-001","30150001","Investment in Subsidiaries — Pinnacle Engineering",
     "5062","2001","CLO","IC_USD","Investment elimination — NOVAHOLD holding in Pinnacle Engineering LLC",
     "USD","XOF",3499,171402,1.00,1.00),
    ("IC-005","5001","5038","IC-002","50101001","Revenue — Intragroup Chemical Product Sales",
     "5038","5001","INC","IC_USD","IC profit elimination — Delta Chem product sales to Helios Trade",
     "USD","USD",124500000,123125000,1.00,1.00),
    ("IC-006","5001","5038","IC-001","21300001","Trade Receivables — Intercompany",
     "5038","5001","CLO","IC_USD","IC receivable — Delta Chem outstanding from Helios Trade at period end",
     "USD","USD",18750000,18750000,1.00,1.00),
    ("IC-007","5004","HELIOS","IC-001","50101009","Revenue — Profit Transfer / Ecremage",
     "HELIOS","5004","INC","IC_XAF","Profit transfer FY 2025 — Austral Nitro to group (ecremage)",
     "XAF","USD",43604383,3208419,1.00,1.00),
    ("IC-008","HELIOS","5001","IC-001","50900002","Group Management Fee Income",
     "5001","HELIOS","INC","IC_USD","Group management fee — Helios Group charged to Delta Chem",
     "USD","USD",4200000,4200000,1.00,1.00),
    ("IC-009","HELIOS","5004","IC-001","50900002","Group Management Fee Income",
     "5004","HELIOS","INC","IC_XAF","Group management fee — Helios Group charged to Austral Nitro",
     "USD","XAF",1800000,132480000,1.00,1.00),
    ("IC-010","HELIOS","5038","IC-001","50900001","IC Loan Interest Income",
     "5038","HELIOS","INC","IC_USD","IC loan interest — group treasury facility to Helios Trade BV",
     "USD","USD",1250000,1250000,1.00,1.00),
    ("IC-011","5001","2001","DIV-001","30150001","Dividends Paid — Intercompany",
     "2001","5001","DIV","IC_USD","FY 2025 dividend — Delta Chem to NOVAHOLD shareholder",
     "USD","USD",85000000,85000000,1.00,1.00),
    ("IC-012","5004","2001","DIV-001","30150001","Dividends Paid — Intercompany",
     "2001","5004","DIV","IC_XAF","FY 2025 dividend — Austral Nitro to NOVAHOLD (51% share)",
     "XAF","USD",11287863,830566,1.00,1.00),
    ("IC-013","5001","2001","EQ-001","20100001","Share Capital — Ordinary Shares",
     "2001","5001","OPE","IC_USD","Share capital elimination — Delta Chem equity in NOVAHOLD books",
     "USD","USD",320000000,320000000,1.00,1.00),
    ("IC-014","5001","2001","EQ-004","30150001","Retained Earnings — Group",
     "2001","5001","OPE","IC_USD","Net income allocation — Delta Chem retained earnings Group/NCI split",
     "USD","USD",1650000000,1650000000,1.00,1.00),
    ("IC-015","HELIOS","5076","GW-001","21130001","Goodwill on Acquisition — Regal Chemicals",
     "5076","HELIOS","OPE","IC_USD","PPA Goodwill — Regal Chemicals Industries acquisition carrying value",
     "USD","USD",441226924,441226924,1.00,1.00),
    ("IC-016","5038","5001","IC-001","31500001","Trade Payables — Intercompany",
     "5001","5038","CLO","IC_USD","IC payable — Helios Trade outstanding to Delta Chem at period end",
     "USD","USD",18620000,18620000,1.00,1.00),
    ("IC-017","4242","5001","AUC-001","50101005","Construction Revenue — Intragroup AUC",
     "5001","4242","INC","IC_USD","Intragroup AUC revenue — Helios Engineering Services to Delta Chem",
     "USD","USD",2200000,2167000,1.00,1.00),
    ("IC-018","HELIOS","5038","IC-004","31600001","IC Provision — Allowance for Doubtful Debts",
     "5038","HELIOS","CLO","IC_USD","IC provision elimination — group allowance against Helios Trade balance",
     "USD","USD",320000,320000,1.00,1.00),
    ("IC-019","5001","5038","STK-001","21180001","Inventories — Unrealised IC Profit",
     "5038","5001","CLO","IC_USD","Unrealised profit elimination — Delta Chem stock held by Helios Trade",
     "USD","USD",3463440,3463440,1.00,1.00),
    ("IC-020","5073","HELIOS","IC-001","50220026","MTM Losses — Third Party Commitments Reversal",
     "HELIOS","5073","P_Y_ADJ","IC_USD","MTM losses reversal FY2021 — Helios Distribution to group",
     "USD","USD",406222,406222,1.00,1.00),
]

def build_helios_dataframe():
    rows = []
    for t in HELIOS_TRANSACTIONS:
        (txn_id, seller, buyer, rule_code, acc_code, acc_desc,
         icp_seller, icp_buyer, flow, c3_ccy, desc,
         seller_ccy, buyer_ccy, seller_amt, buyer_amt,
         pcon_s, pcon_b) = t

        rc = RULE_MAP.get(rule_code, rule_code)
        if rc not in ELIMINATION_RULES:
            rc = rule_code

        s_usd   = seller_amt * FX_RATES.get(seller_ccy, 1.0)
        b_usd   = buyer_amt  * FX_RATES.get(buyer_ccy,  1.0)
        gap_usd = abs(s_usd - b_usd)
        is_xccy = seller_ccy != buyer_ccy
        # For cross-currency pairs gap is computed in USD after FX conversion
        if is_xccy:
            gap_pct = abs(s_usd - b_usd) / s_usd * 100 if s_usd > 0 else 0
            ms = "Matched" if gap_pct < 0.5 else (CROSS_CCY_STATUS if gap_pct < 5.0 else CROSS_CCY_STATUS)
        else:
            gap_pct = abs(seller_amt - buyer_amt) / seller_amt * 100 if seller_amt > 0 else 0
            ms = "Matched" if gap_pct < 0.5 else ("Not Matched" if gap_pct < 2.0 else "Exception")

        rows.append({
            "id": txn_id, "seller": seller, "buyer": buyer,
            "rule_code": rc, "rule_internal": rc,
            "description": desc,
            "seller_amt": seller_amt, "buyer_amt": buyer_amt,
            "seller_ccy": seller_ccy, "buyer_ccy": buyer_ccy,
            "seller_usd": s_usd, "buyer_usd": b_usd,
            "gap_usd": gap_usd, "gap_pct": gap_pct,
            "match_status": ms,
            "category": ELIMINATION_RULES.get(rc, {}).get("category", "Intercompany"),
            "rule_label": ELIMINATION_RULES.get(rc, {}).get("label", rc),
            "pcon_seller": pcon_s, "pcon_buyer": pcon_b,
            "period": "DEC 2025", "scenario": "ACTUAL",
            "flow": flow, "custom3_ccy": c3_ccy,
            "account_code": acc_code, "account_desc": acc_desc,
            "icp_seller": icp_seller, "icp_buyer": icp_buyer,
            "source": "helios",
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
            # Handle the Helios xlsx format — data starts at row 3 (0-indexed row 2)
            raw = pd.read_excel(uploaded_file, header=None)
            # Find the header row (contains Txn_ID)
            header_row = None
            for i, row in raw.iterrows():
                if "Txn_ID" in row.values:
                    header_row = i
                    break
            if header_row is not None:
                raw.columns = raw.iloc[header_row]
                raw = raw.iloc[header_row+1:].reset_index(drop=True)
                raw = raw[raw["Txn_ID"].notna() & (raw["Txn_ID"] != "TOTAL  (Sum of Seller amounts)")]
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
            return None, f"Unknown rule code '{rc}' on row {r.get('Txn_ID','?')}."

        s_amt = float(r["Seller_Amount"])
        b_amt = float(r["Buyer_Amount"])
        s_ccy = str(r["Seller_CCY"]).upper().strip()
        b_ccy = str(r["Buyer_CCY"]).upper().strip()

        if s_ccy not in FX_RATES:
            return None, f"Unknown currency '{s_ccy}' — add to FX_RATES dictionary."
        if b_ccy not in FX_RATES:
            return None, f"Unknown currency '{b_ccy}' — add to FX_RATES dictionary."

        s_usd   = s_amt * FX_RATES[s_ccy]
        b_usd   = b_amt * FX_RATES[b_ccy]
        is_xccy = s_ccy != b_ccy
        if is_xccy:
            gap_pct = abs(s_usd - b_usd) / s_usd * 100 if s_usd > 0 else 0
            ms = "Matched" if gap_pct < 0.5 else CROSS_CCY_STATUS
        else:
            gap_pct = abs(s_amt - b_amt) / s_amt * 100 if s_amt > 0 else 0
            ms = "Matched" if gap_pct < 0.5 else ("Not Matched" if gap_pct < 2.0 else "Exception")

        seller_code = str(r["Seller_Entity"]).strip()
        buyer_code  = str(r["Buyer_Entity"]).strip()
        pcon_s = float(r["PCon_Seller"])
        pcon_b = float(r["PCon_Buyer"])

        rows.append({
            "id": str(r["Txn_ID"]),
            "seller": seller_code, "buyer": buyer_code,
            "rule_code": rc, "rule_internal": rc,
            "description": str(r["Description"]),
            "seller_amt": s_amt, "buyer_amt": b_amt,
            "seller_ccy": s_ccy, "buyer_ccy": b_ccy,
            "seller_usd": s_usd, "buyer_usd": b_usd,
            "gap_usd": abs(s_usd - b_usd), "gap_pct": gap_pct,
            "match_status": ms,
            "category": ELIMINATION_RULES[rc]["category"],
            "rule_label": ELIMINATION_RULES[rc]["label"],
            "pcon_seller": pcon_s, "pcon_buyer": pcon_b,
            "period": period, "scenario": scenario,
            "flow": str(r.get("Flow","")).strip(),
            "custom3_ccy": str(r.get("Custom3_CCY","")).strip(),
            "account_code": str(r.get("Account_Code","")).strip(),
            "account_desc": str(r.get("Account_Desc","")).strip(),
            "icp_seller": str(r.get("ICP_Seller","")).strip(),
            "icp_buyer": str(r.get("ICP_Buyer","")).strip(),
            "source": "upload",
        })
    return pd.DataFrame(rows), None

def build_sample_csv():
    rows = [
        ["IC-001","ACTUAL","2025","DEC","2001","5001","INV-001",
         "Investment in Subsidiaries — Delta Chem","5001","2001","CLO","IC_USD",
         "Investment elimination — NOVAHOLD in Delta Chem",
         "USD","USD",2580647846,2580647846,1.00,1.00],
        ["IC-005","ACTUAL","2025","DEC","5001","5038","IC-002",
         "Revenue — Intragroup Chemical Product Sales","5038","5001","INC","IC_USD",
         "IC profit elimination — Delta Chem sales to Helios Trade",
         "USD","USD",124500000,123125000,1.00,1.00],
        ["IC-007","ACTUAL","2025","DEC","5004","HELIOS","IC-001",
         "Revenue — Profit Transfer / Ecremage","HELIOS","5004","INC","IC_XAF",
         "Profit transfer FY 2025 — Austral Nitro to group",
         "XAF","USD",43604383,3208419,1.00,1.00],
    ]
    cols = ["Txn_ID","Scenario","Year","Period","Seller_Entity","Buyer_Entity",
            "Rule_Code","Account_Desc","ICP_Seller","ICP_Buyer","Flow","Custom3_CCY",
            "Description","Seller_CCY","Buyer_CCY","Seller_Amount","Buyer_Amount",
            "PCon_Seller","PCon_Buyer"]
    df = pd.DataFrame(rows, columns=cols)
    buf = io.BytesIO()
    df.to_csv(buf, index=False)
    return buf.getvalue()

# ─────────────────────────────────────────────────────────────
# ELIMINATION ENGINE
# ─────────────────────────────────────────────────────────────

def compute_elimination(row):
    rule   = row["rule_internal"]
    amt    = row["seller_usd"]
    pcon_s = row["pcon_seller"]
    pcon_b = row["pcon_buyer"]
    pown_s = pcon_s
    pmin_s = max(0, 1 - pcon_s)  # NCI = 1 - PCon for GLOBAL method
    min_p  = min(pcon_s, pcon_b)
    rc     = row["rule_code"]
    entries = []

    if rule in ("IC-001", "ELIM"):
        entries += [
            {"Account": "IC Receivable / Revenue", "Dr/Cr": "Dr", "Amount": -amt * min_p, "Audit": rc},
            {"Account": "IC Payable / Cost",        "Dr/Cr": "Cr", "Amount":  amt * min_p, "Audit": rc},
        ]
    elif rule in ("IC-002", "ELIMR", "ELIMRA", "IC-003"):
        entries += [
            {"Account": "Seller Account",  "Dr/Cr": "Dr", "Amount": -amt * min_p, "Audit": rc},
            {"Account": "Offset Account",  "Dr/Cr": "Cr", "Amount":  amt * min_p, "Audit": rc},
            {"Account": "Buyer Account",   "Dr/Cr": "Dr", "Amount":  amt * min_p, "Audit": rc + "-B"},
            {"Account": "Offset Account",  "Dr/Cr": "Cr", "Amount": -amt * min_p, "Audit": rc + "-B"},
        ]
    elif rule in ("EQ-001", "CAPI"):
        entries += [
            {"Account": "Share Capital",   "Dr/Cr": "Dr", "Amount": -amt * pcon_s, "Audit": rc},
            {"Account": "Group Reserves",  "Dr/Cr": "Cr", "Amount":  amt * pown_s, "Audit": rc},
            {"Account": "NCI Reserves",    "Dr/Cr": "Cr", "Amount":  amt * pmin_s, "Audit": rc},
        ]
    elif rule in ("EQ-004", "RESU"):
        entries += [
            {"Account": "Net Income",       "Dr/Cr": "Dr", "Amount": -amt * pcon_s, "Audit": rc},
            {"Account": "Group Net Income", "Dr/Cr": "Cr", "Amount":  amt * pown_s, "Audit": rc},
            {"Account": "NCI Net Income",   "Dr/Cr": "Cr", "Amount":  amt * pmin_s, "Audit": rc},
        ]
    elif rule in ("GW-001", "GW"):
        entries += [
            {"Account": "Goodwill",           "Dr/Cr": "Dr", "Amount": -amt * pcon_s * pcon_b, "Audit": rc},
            {"Account": "Investment Account", "Dr/Cr": "Cr", "Amount":  amt * pcon_s * pcon_b, "Audit": rc},
            {"Account": "Group Reserves",     "Dr/Cr": "Cr", "Amount": -amt * pown_s,          "Audit": rc},
            {"Account": "NCI Reserves",       "Dr/Cr": "Cr", "Amount": -amt * pmin_s,          "Audit": rc},
        ]
    elif rule in ("INV-001", "PINT"):
        entries += [
            {"Account": "Investment in Sub", "Dr/Cr": "Dr", "Amount": -amt * pcon_s, "Audit": rc},
            {"Account": "Liaison Account",   "Dr/Cr": "Cr", "Amount":  amt * pcon_s, "Audit": rc},
            {"Account": "Group Reserves",    "Dr/Cr": "Cr", "Amount":  amt * pown_s, "Audit": rc + "-N"},
            {"Account": "NCI Reserves",      "Dr/Cr": "Cr", "Amount":  amt * pmin_s, "Audit": rc + "-N"},
        ]
    elif rule in ("DIV-001", "DIVP"):
        entries += [
            {"Account": "Dividends Paid",  "Dr/Cr": "Dr", "Amount": -amt * pcon_s, "Audit": rc},
            {"Account": "Group Reserves",  "Dr/Cr": "Cr", "Amount":  amt * pown_s, "Audit": rc},
            {"Account": "NCI Reserves",    "Dr/Cr": "Cr", "Amount":  amt * pmin_s, "Audit": rc},
        ]
    elif rule in ("DIV-004", "DIVI"):
        entries += [
            {"Account": "Dividend Income",  "Dr/Cr": "Dr", "Amount": -amt * pcon_s, "Audit": rc},
            {"Account": "Group Net Income", "Dr/Cr": "Cr", "Amount":  amt * pown_s, "Audit": rc},
            {"Account": "NCI Net Income",   "Dr/Cr": "Cr", "Amount":  amt * pmin_s, "Audit": rc},
        ]
    elif rule in ("STK-001", "PSTK"):
        entries += [
            {"Account": "Inventory",    "Dr/Cr": "Dr", "Amount": -amt * pcon_s * pcon_b, "Audit": rc},
            {"Account": "COGS/Revenue", "Dr/Cr": "Cr", "Amount":  amt * pcon_s * pcon_b, "Audit": rc},
        ]
    elif rule in ("IC-004", "ELIPROV"):
        entries += [
            {"Account": "IC Provision",    "Dr/Cr": "Dr", "Amount": -amt * pcon_s, "Audit": rc},
            {"Account": "Provision P&L",   "Dr/Cr": "Cr", "Amount":  amt * pcon_s, "Audit": rc},
        ]
    elif rule in ("AUC-001", "AUCREV", "AUC-003", "AUCCOS"):
        pl = "Construction Revenue" if rule in ("AUC-001","AUCREV") else "Construction Cost"
        entries += [
            {"Account": "AUC Asset",        "Dr/Cr": "Dr", "Amount": -amt * pcon_s * pcon_b, "Audit": rc},
            {"Account": pl,                 "Dr/Cr": "Cr", "Amount":  amt * pcon_s * pcon_b, "Audit": rc},
            {"Account": "AUC Link — BS",    "Dr/Cr": "Dr", "Amount": -amt * pcon_s,          "Audit": rc},
            {"Account": "AUC Link — Contra","Dr/Cr": "Cr", "Amount":  amt * pcon_s,          "Audit": rc},
        ]
    else:
        entries += [
            {"Account": f"Account ({rc})",     "Dr/Cr": "Dr", "Amount": -amt * pcon_s, "Audit": rc},
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
  .meta-chip { display:inline-block;padding:2px 8px;border-radius:10px;
    font-size:11px;font-weight:600;background:#DEEAF1;color:#1F3864;margin:2px; }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────
# LOAD / SEED DATA
# ─────────────────────────────────────────────────────────────

existing = load_transactions_from_db()
if existing.empty:
    seed_df = build_helios_dataframe()
    save_transactions_to_db(seed_df)
    df = seed_df
else:
    df = existing

reviews = load_reviews_from_db()

# ─────────────────────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("## ⚖️ IC Elimination Engine")
    st.caption("Helios Group — Consolidation Suite")
    st.divider()

    all_entities = sorted(set(df["seller"].tolist() + df["buyer"].tolist()))
    entity_opts  = ["All Entities"] + all_entities

    def fmt_entity(x):
        if x == "All Entities": return x
        return f"{x} — {ENTITIES[x]['name']}" if x in ENTITIES else x

    sel_entity = st.selectbox("Filter Entity", entity_opts, format_func=fmt_entity)
    threshold  = st.slider("Gap Threshold (%)", 0.0, 5.0, 0.5, 0.1)

    st.divider()
    period_label = st.selectbox("Period", ["DEC 2025","NOV 2025","SEP 2025","JUN 2025","MAR 2025","DEC 2024"])

    st.divider()
    st.markdown("**Upload IC Transactions**")
    st.caption("Accepts the Helios IC Source Upload format (xlsx or csv)")
    uploaded = st.file_uploader("Upload file", type=["csv","xlsx"])
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
        "⬇️ Download sample upload CSV",
        data=build_sample_csv(),
        file_name="Helios_IC_Source_Sample.csv",
        mime="text/csv",
        use_container_width=True,
    )

    st.divider()
    if st.button("🔄 Reset to Helios sample data", use_container_width=True):
        seed_df = build_helios_dataframe()
        save_transactions_to_db(seed_df)
        reset_all_reviews()
        st.rerun()

# ─────────────────────────────────────────────────────────────
# FILTER
# ─────────────────────────────────────────────────────────────

df      = load_transactions_from_db()
reviews = load_reviews_from_db()

filtered = df.copy()
if sel_entity != "All Entities":
    filtered = filtered[(filtered["seller"]==sel_entity)|(filtered["buyer"]==sel_entity)]

filtered["Review Status"] = filtered["id"].map(lambda x: reviews.get(x,{}).get("status","Pending"))

# ─────────────────────────────────────────────────────────────
# HEADER
# ─────────────────────────────────────────────────────────────

approved_n = sum(1 for v in reviews.values() if v.get("status")=="Approved")
rejected_n = sum(1 for v in reviews.values() if v.get("status")=="Rejected")
pending_n  = len(df) - approved_n - rejected_n

st.markdown("## ⚖️ Financial Close Command Center — AI-powered             Intercompany Elimination")
st.markdown(
    f"**Helios Group · {period_label} · ACTUAL · HUMAN IN THE LOOP enabled"
)

b1,b2,b3,b4 = st.columns(4)
b1.metric("Pending Review", pending_n, delta_color="off")
b2.metric("Approved",       approved_n, delta=f"{approved_n/max(len(df),1)*100:.0f}%")
b3.metric("Rejected",       rejected_n, delta_color="inverse")
b4.metric("Ready to Post",  approved_n,
          delta="✅ Period close ready" if approved_n==len(df) else "Awaiting sign-off")
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
    "📁 Audit Trail",
])

# ════════════════════════════════════════════════════
# TAB 1 — DASHBOARD
# ════════════════════════════════════════════════════
with tabs[0]:
    total_vol        = df["seller_usd"].sum()
    total_txns       = len(df)
    matched_count    = len(df[df["match_status"]=="Matched"])
    notmatched_count = len(df[df["match_status"]=="Not Matched"])
    fxdiff_count     = len(df[df["match_status"]==CROSS_CCY_STATUS])
    exception_count  = len(df[df["match_status"]=="Exception"])

    # The three primary statuses — must sum to total
    primary_sum = matched_count + notmatched_count + exception_count + fxdiff_count

    # ── Top metrics row ──────────────────────────────────────────
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total IC Volume (USD)", f"${total_vol/1e6:.1f}M")
    c2.metric("Total Transactions",    str(total_txns))
    c3.metric("✅ Matched",
              f"{matched_count}",
              delta=f"{matched_count/max(total_txns,1)*100:.0f}% of total")
    c4.metric("🟡 Not Matched",
              f"{notmatched_count + fxdiff_count}",
              delta=f"{(notmatched_count+fxdiff_count)/max(total_txns,1)*100:.0f}% of total",
              delta_color="off")
    c5.metric("🔴 Exception",
              f"{exception_count}",
              delta=f"{exception_count/max(total_txns,1)*100:.0f}% of total",
              delta_color="inverse")

    # ── Status legend ────────────────────────────────────────────
    st.markdown("""
<div style="display:flex;gap:12px;flex-wrap:wrap;margin:8px 0 4px;">
  <div style="background:#e8f5e9;border-left:4px solid #1D9E75;padding:8px 14px;border-radius:6px;flex:1;min-width:180px;">
    <strong style="color:#1A7A4A">✅ Matched</strong><br>
    <span style="font-size:12px;color:#444">Gap &lt; 0.5% — both sides agree within rounding. Ready for elimination.</span>
  </div>
  <div style="background:#FFF3CD;border-left:4px solid #B45309;padding:8px 14px;border-radius:6px;flex:1;min-width:180px;">
    <strong style="color:#B45309">🟡 Not Matched</strong><br>
    <span style="font-size:12px;color:#444">Gap 0.5–2% (same CCY) or FX translation difference (cross-CCY). Proceed to review — controller confirms gap before approval.</span>
  </div>
  <div style="background:#ffebee;border-left:4px solid #C62828;padding:8px 14px;border-radius:6px;flex:1;min-width:180px;">
    <strong style="color:#C62828">🔴 Exception</strong><br>
    <span style="font-size:12px;color:#444">Gap &gt; 2% (same CCY). Blocked from journal — investigate cut-off, accrual basis, or posting error before proceeding.</span>
  </div>
</div>
""", unsafe_allow_html=True)

    # Validation — confirm counts sum to total
    if primary_sum != total_txns:
        st.warning(f"⚠️ Status count mismatch: {primary_sum} categorised vs {total_txns} total. "
                   f"Check for unrecognised match_status values in the database.")

    # Source / period tag
    src = df["source"].iloc[0] if "source" in df.columns else "helios"
    st.caption(
        f"📂 Data source: **{src}** · Period: **{period_label}** · "
        f"Scenario: **ACTUAL** · Group: **Helios Chemicals Group** · "
        f"Currencies in scope: USD, XAF, XOF, EUR, SAR"
    )

    st.divider()
    col_a, col_b = st.columns(2)

    with col_a:
        st.markdown('<p class="section-header">IC Volume by Category (USD)</p>', unsafe_allow_html=True)
        cat_df = df.groupby("category")["seller_usd"].sum().reset_index().sort_values("seller_usd",ascending=True)
        fig = px.bar(cat_df, x="seller_usd", y="category", orientation="h",
                     color="category",
                     color_discrete_map={c:CATEGORY_COLORS.get(c,"#888") for c in cat_df["category"]},
                     labels={"seller_usd":"Amount (USD)","category":""})
        fig.update_layout(height=320,showlegend=False,margin=dict(l=0,r=0,t=10,b=10),
                          paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig, use_container_width=True)

    with col_b:
        st.markdown('<p class="section-header">Review Status</p>', unsafe_allow_html=True)
        rev_vals = {k:v for k,v in {"Approved":approved_n,"Pending":pending_n,"Rejected":rejected_n}.items() if v>0}
        if rev_vals:
            clrs = {"Approved":"#1D9E75","Pending":"#E8A838","Rejected":"#D94F3D"}
            fig2 = go.Figure(go.Pie(
                labels=list(rev_vals.keys()), values=list(rev_vals.values()),
                marker_colors=[clrs[k] for k in rev_vals],
                hole=0.55, textinfo="label+percent"
            ))
            fig2.update_layout(height=320,showlegend=False,margin=dict(l=0,r=0,t=10,b=10),
                               paper_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig2, use_container_width=True)

    # NCI spotlight — entities with minority interest
    st.divider()
    nci_entities = {k:v for k,v in ENTITIES.items() if v["pcon"] < 1.0}
    if nci_entities:
        st.markdown('<p class="section-header">Minority Interest Entities — NCI in scope</p>', unsafe_allow_html=True)
        n1,n2,n3 = st.columns(3)
        cols_nci = [n1,n2,n3]
        for i,(code,info) in enumerate(nci_entities.items()):
            pmin = round((1 - info["pcon"])*100,0)
            cols_nci[i%3].metric(
                f"{code} — {info['name']}",
                f"PCon {info['pcon']*100:.0f}%",
                delta=f"NCI {pmin:.0f}%"
            )

    st.markdown('<p class="section-header">Transaction Summary</p>', unsafe_allow_html=True)
    disp = filtered[["id","seller","buyer","rule_code","rule_label","description",
                      "seller_usd","buyer_usd","gap_pct","match_status","Review Status"]].copy()
    disp.columns = ["ID","Seller","Buyer","Rule","Rule Label","Description",
                    "Seller USD","Buyer USD","Gap %","Match","Review"]
    disp["Seller USD"] = disp["Seller USD"].map("${:,.0f}".format)
    disp["Buyer USD"]  = disp["Buyer USD"].map("${:,.0f}".format)
    disp["Gap %"]      = disp["Gap %"].map("{:.2f}%".format)

    def _cs(v): return {"Matched":"background-color:#e8f5e9;color:#1A7A4A","Not Matched":"background-color:#FFF3CD;color:#B45309","Exception":"background-color:#ffebee;color:#C62828","FX_Diff":"background-color:#E8F4FD;color:#1565C0"}.get(v,"")
    def _cr(v): return {"Approved":"background-color:#D1FAE5;color:#065F46;font-weight:600","Rejected":"background-color:#FEE2E2;color:#991B1B;font-weight:600","Pending":"background-color:#FFF3CD;color:#856404"}.get(v,"")

    st.dataframe(disp.style.map(_cs,subset=["Match"]).map(_cr,subset=["Review"]),
                 use_container_width=True, height=380)

# ════════════════════════════════════════════════════
# TAB 2 — IC MATCHING
# ════════════════════════════════════════════════════
with tabs[1]:
    st.markdown("### Intercompany Matching Engine")
    st.caption("Bilateral matching · Cross-currency pairs (XAF, XOF) converted to USD at closing rate")

    mdf = filtered[["id","seller","buyer","rule_code","seller_ccy","buyer_ccy",
                     "seller_usd","buyer_usd","gap_usd","gap_pct","match_status"]].copy()
    exceptions  = mdf[mdf["match_status"]=="Exception"]
    fxdiffs     = mdf[mdf["match_status"]==CROSS_CCY_STATUS]
    matched     = mdf[mdf["match_status"]=="Matched"]
    not_matched = mdf[mdf["match_status"]=="Not Matched"]

    m1,m2,m3,m4,m5 = st.columns(5)
    m1.metric("Matched",           len(matched))
    m2.metric("Not Matched",       len(not_matched), delta="Small gap — proceed with review", delta_color="off")
    m3.metric("FX Diff (Cross-CCY)", len(fxdiffs),  delta="Translation gap — expected",      delta_color="off")
    m4.metric("Exceptions",        len(exceptions),  delta_color="inverse")
    m5.metric("Total Gap USD",     f"${mdf['gap_usd'].sum():,.0f}")

    st.divider()
    tm, tnm, tfx, te = st.tabs([
        f"✅ Matched ({len(matched)})",
        f"🟡 Not Matched ({len(not_matched)})",
        f"💱 FX Diff ({len(fxdiffs)})",
        f"⚠️ Exceptions ({len(exceptions)})",
    ])

    with tm:
        md = matched.copy()
        for c in ["seller_usd","buyer_usd","gap_usd"]:
            md[c] = md[c].map("${:,.0f}".format)
        md["gap_pct"] = md["gap_pct"].map("{:.3f}%".format)
        if md.empty:
            st.info("No matched transactions in current filter.")
        else:
            st.dataframe(md, use_container_width=True)

    with tnm:
        st.info("🟡 Not Matched transactions have a small same-currency gap above the threshold "
                "but below the Exception level. They can proceed to HITL approval — "
                "the reviewer should confirm the gap is acceptable before signing off.")
        if len(not_matched) > 0:
            for _, row in not_matched.iterrows():
                s_name = ENTITIES.get(row["seller"],{}).get("name", row["seller"])
                b_name = ENTITIES.get(row["buyer"], {}).get("name", row["buyer"])
                with st.expander(f"🟡 {row['id']} — {s_name} ↔ {b_name} — Gap: {row['gap_pct']:.2f}%"):
                    cc1,cc2,cc3 = st.columns(3)
                    cc1.metric("Seller USD", f"${row['seller_usd']:,.0f}")
                    cc2.metric("Buyer USD",  f"${row['buyer_usd']:,.0f}")
                    cc3.metric("Gap USD",    f"${row['gap_usd']:,.0f}")
                    st.warning(f"Gap of {row['gap_pct']:.2f}% — confirm whether this is an "
                               f"accrual timing difference or a cut-off issue. "
                               f"Proceed to approval if acceptable.")
        else:
            st.success("No Not Matched transactions in current filter.")

    with tfx:
        st.info("💱 Cross-currency pairs have amounts in different functional currencies. "
                "The USD gap shown is the FX translation difference — expected and legitimate. "
                "Verify the closing FX rate applied on each side matches the HFM translation rate.")
        if len(fxdiffs) > 0:
            for _,row in fxdiffs.iterrows():
                s_name = ENTITIES.get(row["seller"],{}).get("name",row["seller"])
                b_name = ENTITIES.get(row["buyer"], {}).get("name",row["buyer"])
                with st.expander(f"💱 {row['id']} — {s_name} ({row['seller_ccy']}) ↔ {b_name} ({row['buyer_ccy']}) — FX Gap: ${row['gap_usd']:,.0f}"):
                    cc1,cc2,cc3 = st.columns(3)
                    cc1.metric("Seller USD", f"${row['seller_usd']:,.0f}")
                    cc2.metric("Buyer USD",  f"${row['buyer_usd']:,.0f}")
                    cc3.metric("FX Gap USD", f"${row['gap_usd']:,.0f}")
                    st.markdown(f"**FX pair:** {row['seller_ccy']} / {row['buyer_ccy']}  "
                                f"| **Seller rate:** {FX_RATES.get(row['seller_ccy'],1):.6f}  "
                                f"| **Buyer rate:** {FX_RATES.get(row['buyer_ccy'],1):.6f}")
                    st.caption("This gap is caused by FX translation. "
                               "Confirm both sides use the same HFM closing rate before approval.")
        else:
            st.success("No cross-currency FX differences in current filter.")

    with te:
        if len(exceptions)>0:
            for _,row in exceptions.iterrows():
                s_name = ENTITIES.get(row["seller"],{}).get("name",row["seller"])
                b_name = ENTITIES.get(row["buyer"], {}).get("name",row["buyer"])
                with st.expander(f"⚠️ {row['id']} — {s_name} ↔ {b_name} — Gap: {row['gap_pct']:.2f}%"):
                    cc1,cc2,cc3 = st.columns(3)
                    cc1.metric("Seller USD", f"${row['seller_usd']:,.0f}")
                    cc2.metric("Buyer USD",  f"${row['buyer_usd']:,.0f}")
                    cc3.metric("Gap USD",    f"${row['gap_usd']:,.0f}")
                    st.warning(f"Same-currency gap of {row['gap_pct']:.2f}% — "
                               f"investigate period cut-off mismatch, accrual vs cash basis, "
                               f"or unapproved adjustment before approving elimination.")
        else:
            st.success("No same-currency exceptions. All intercompany balances within tolerance.")

# ════════════════════════════════════════════════════
# TAB 3 — ELIMINATION ENGINE
# ════════════════════════════════════════════════════
with tabs[2]:
    st.markdown("### Elimination Engine")
    st.caption("Select any transaction to compute elimination entries. Rules map to HFM UD3 attribute.")

    opts = filtered["id"].tolist()
    if not opts:
        st.warning("No transactions match the current filter.")
        st.stop()

    def _fmt(x):
        r_ = filtered[filtered["id"]==x]
        return f"{x} — {r_['description'].values[0]}" if len(r_)>0 else x

    sel_id  = st.selectbox("Select Transaction", opts, format_func=_fmt)
    sel_row = filtered[filtered["id"]==sel_id].iloc[0]

    r1,r2,r3,r4 = st.columns(4)
    r1.metric("Rule",       sel_row["rule_code"])
    r2.metric("Amount USD", f"${sel_row['seller_usd']:,.0f}")
    r3.metric("Seller",     ENTITIES.get(sel_row["seller"],{}).get("name",sel_row["seller"]))
    r4.metric("Buyer",      ENTITIES.get(sel_row["buyer"], {}).get("name",sel_row["buyer"]))

    rule_info  = ELIMINATION_RULES.get(sel_row["rule_code"],{})
    rev_status = reviews.get(sel_id,{}).get("status","Pending")
    rev_color  = {"Approved":"#1D9E75","Rejected":"#D94F3D","Pending":"#E8A838"}.get(rev_status,"#888")

    st.markdown(
        f'**{rule_info.get("label","—")}** &nbsp; '
        f'<span style="background:{rev_color};color:#fff;padding:2px 10px;'
        f'border-radius:12px;font-size:12px;font-weight:700">{rev_status}</span>',
        unsafe_allow_html=True
    )
    st.info(rule_info.get("description",""))

    # Metadata fields
    with st.expander("📂 HFM Metadata — Flow, ICP & Account context"):
        m1,m2,m3,m4 = st.columns(4)
        m1.markdown(f"**Flow (Custom1):** `{sel_row.get('flow','—')}`")
        m2.markdown(f"**Custom3 CCY:** `{sel_row.get('custom3_ccy','—')}`")
        m3.markdown(f"**ICP Seller:** `{sel_row.get('icp_seller','—')}`")
        m4.markdown(f"**ICP Buyer:** `{sel_row.get('icp_buyer','—')}`")
        st.markdown(f"**Account:** `{sel_row.get('account_code','—')}` — {sel_row.get('account_desc','—')}")

    st.divider()
    st.markdown("#### Computed Journal Entries — [Elimination] Value")
    entries  = compute_elimination(sel_row)
    edf      = pd.DataFrame(entries)
    # Use absolute values — Dr/Cr column carries the sign direction
    edf["Amount (USD)"] = edf["Amount"].abs().map("${:,.0f}".format)
    edf = edf[["Account","Dr/Cr","Amount (USD)","Value","Audit"]]

    def _drcr(row):
        return ["background-color:#fff4f4;color:#C62828"]*len(row) if row["Dr/Cr"]=="Dr" \
               else ["background-color:#f4fff8;color:#1A7A4A"]*len(row)

    if edf.empty:
        st.warning("No entries computed — check the rule code is recognised.")
    else:
        st.dataframe(edf.style.apply(_drcr, axis=1), use_container_width=True, height=200)
    st.caption("🔴 Dr = Debit | 🟢 Cr = Credit | Amounts shown as absolute values | All entries post to [Elimination] value")

    st.divider()
    g1,g2,g3 = st.columns(3)
    with g1:
        st.markdown("**Elimination Gate Conditions**")
        st.markdown("- ICP must be assigned (not [ICP None])\n- Both entities under same consolidating parent\n- Entity must NOT be direct parent of ICP counterpart")
    with g2:
        st.markdown(f"**PCon (Seller):** {sel_row['pcon_seller']*100:.0f}%")
        st.markdown(f"**PCon (Buyer):** {sel_row['pcon_buyer']*100:.0f}%")
        st.markdown(f"**Effective %:** {min(sel_row['pcon_seller'],sel_row['pcon_buyer'])*100:.0f}%")
        pmin = round((1 - sel_row["pcon_seller"])*100,0)
        if pmin > 0:
            st.markdown(f"**NCI (PMin):** {pmin:.0f}% — minority interest entries generated")
    with g3:
        method = ENTITIES.get(sel_row["seller"],{}).get("method","GLOBAL")
        st.markdown(f"**Consolidation Method:** {method}")
        st.markdown(f"**Match Status:** {sel_row['match_status']}")
        st.markdown(f"**Review Status:** {rev_status}")

# ════════════════════════════════════════════════════
# TAB 4 — JOURNAL ENTRIES
# ════════════════════════════════════════════════════
with tabs[3]:
    st.markdown("### Journal Entries — [Elimination] Value")
    st.caption(f"Only **Approved** transactions post to [Elimination]. Pending and Rejected are withheld. "
               f"Exception transactions require matching resolution before approval is possible.")

    reviews = load_reviews_from_db()

    # ── Gate logic ──────────────────────────────────────────────
    # Gate 1: match status — Exceptions are blocked from journal
    # Gate 2: HITL approval — only Approved transactions post
    POSTABLE_MATCH   = {"Matched", "Not Matched", CROSS_CCY_STATUS}
    BLOCKED_MATCH    = {"Exception"}

    approved_entries = []
    withheld_rows    = []
    blocked_rows     = []

    for _, row in filtered.iterrows():
        txn_id      = row["id"]
        rev_status  = reviews.get(txn_id, {}).get("status", "Pending")
        match_status = row["match_status"]

        if match_status in BLOCKED_MATCH:
            blocked_rows.append({
                "Txn ID": txn_id,
                "Description": row["description"],
                "Rule": row["rule_code"],
                "Match Status": match_status,
                "Gap %": f"{row['gap_pct']:.2f}%",
                "Blocked Reason": "Exception — same-currency gap requires investigation",
            })
        elif rev_status == "Approved":
            for e in compute_elimination(row):
                approved_entries.append({
                    "Txn ID":       txn_id,
                    "Seller":       ENTITIES.get(row["seller"],{}).get("name", row["seller"]),
                    "Buyer":        ENTITIES.get(row["buyer"], {}).get("name", row["buyer"]),
                    "Rule Code":    row["rule_code"],
                    "Flow":         row.get("flow",""),
                    "Account Code": row.get("account_code",""),
                    "Account":      e["Account"],
                    "Value":        e["Value"],
                    "Dr/Cr":        e["Dr/Cr"],
                    "Amount USD":   e["Amount"],
                    "Audit Code":   e["Audit"],
                    "Approved By":  reviews.get(txn_id,{}).get("reviewer",""),
                    "Approved At":  reviews.get(txn_id,{}).get("ts",""),
                })
        else:
            withheld_rows.append({
                "Txn ID": txn_id,
                "Description": row["description"],
                "Rule": row["rule_code"],
                "Match Status": match_status,
                "Review Status": rev_status,
                "Withheld Reason": f"{rev_status} — awaiting controller sign-off" if rev_status == "Pending"
                                   else "Rejected — requires investigation",
            })

    # ── Summary metrics ─────────────────────────────────────────
    je_df = pd.DataFrame(approved_entries) if approved_entries else pd.DataFrame()

    j1,j2,j3,j4,j5 = st.columns(5)
    j1.metric("Approved Txns",   len(reviews) and sum(1 for v in reviews.values() if v.get("status")=="Approved") or 0)
    j2.metric("Withheld (Pending/Rejected)", len(withheld_rows))
    j3.metric("Blocked (Exception)", len(blocked_rows))

    if not je_df.empty:
        total_dr = je_df[je_df["Dr/Cr"]=="Dr"]["Amount USD"].sum()
        total_cr = je_df[je_df["Dr/Cr"]=="Cr"]["Amount USD"].sum()
        balance  = total_dr + total_cr
        j4.metric("Total Debits",  f"${abs(total_dr):,.0f}")
        j5.metric("Balance",       f"${balance:,.0f}",
                  delta="✅ Balanced" if abs(balance)<1 else "⚠️ Out of Balance")
    else:
        j4.metric("Total Debits",  "$0")
        j5.metric("Balance",       "$0", delta="No approved entries yet")

    st.divider()

    # ── Approved journal entries ─────────────────────────────────
    jt1, jt2, jt3 = st.tabs([
        f"✅ Approved Journal ({len(approved_entries)} entries)",
        f"⏳ Withheld ({len(withheld_rows)} transactions)",
        f"🚫 Blocked ({len(blocked_rows)} transactions)",
    ])

    with jt1:
        if je_df.empty:
            st.info("No approved transactions yet. Approve transactions in the Review & Approve tab to generate journal entries.")
        else:
            je_disp = je_df.copy()
            je_disp["Amount USD"] = je_disp["Amount USD"].abs().map("${:,.0f}".format)
            st.dataframe(je_disp, use_container_width=True, height=460)

            buf_je = io.BytesIO()
            je_df.to_excel(buf_je, index=False)
            st.download_button(
                "⬇️ Download Approved Journal (Excel)",
                buf_je.getvalue(),
                file_name=f"Helios_IC_Eliminations_Approved_{period_label.replace(' ','_')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

    with jt2:
        if withheld_rows:
            st.warning("These transactions are ready for elimination but have not been approved. "
                       "Go to Review & Approve to sign them off.")
            wdf = pd.DataFrame(withheld_rows)
            st.dataframe(wdf, use_container_width=True)
        else:
            st.success("No withheld transactions — all postable transactions have been reviewed.")

    with jt3:
        if blocked_rows:
            st.error("These transactions have a same-currency gap above threshold. "
                     "They cannot be approved until the gap is investigated and resolved.")
            bdf = pd.DataFrame(blocked_rows)
            st.dataframe(bdf, use_container_width=True)
        else:
            st.success("No blocked transactions — no same-currency exceptions in current filter.")

# ════════════════════════════════════════════════════
# TAB 5 — REVIEW & APPROVE (HITL)
# ════════════════════════════════════════════════════
with tabs[4]:
    st.markdown("### Human-in-the-Loop — Review & Approve")
    st.caption("Every elimination requires explicit sign-off before posting. Decisions persist in SQLite.")

    rv1,rv2,rv3,rv4 = st.columns(4)
    rv1.metric("Total Transactions", len(df))
    rv2.metric("Pending",  pending_n,  delta_color="off")
    rv3.metric("Approved", approved_n, delta=f"{approved_n/max(len(df),1)*100:.0f}% complete")
    rv4.metric("Rejected", rejected_n, delta_color="inverse")

    st.divider()
    ri1,ri2 = st.columns(2)
    reviewer_name = ri1.text_input("Your Name",  value="Group Controller",   key="rev_name")
    reviewer_role = ri2.selectbox("Role",
        ["Group Controller","Regional CFO","Finance Director",
         "Treasury Controller","External Auditor","CFO"], key="rev_role")

    st.divider()
    st.markdown("#### Bulk Actions")
    ba1,ba2 = st.columns(2)
    with ba1:
        if st.button("✅ Approve All Matched", use_container_width=True):
            for _,row in df[df["match_status"]=="Matched"].iterrows():
                upsert_review(row["id"],"Approved",
                              f"{reviewer_name} ({reviewer_role})",
                              datetime.now().strftime("%Y-%m-%d %H:%M"),
                              "Bulk approval — all matched transactions")
            st.rerun()
    with ba2:
        if st.button("🔄 Reset All to Pending", use_container_width=True):
            reset_all_reviews()
            st.rerun()

    st.divider()
    filter_rev = st.radio("Show",["All","Pending","Approved","Rejected"],horizontal=True)

    reviews = load_reviews_from_db()

    for _,row in filtered.iterrows():
        txn_id     = row["id"]
        rev_data   = reviews.get(txn_id,{})
        rev_status = rev_data.get("status","Pending")
        if filter_rev!="All" and rev_status!=filter_rev:
            continue

        css_class  = {"Approved":"hitl-approved","Rejected":"hitl-rejected","Pending":"hitl-pending"}.get(rev_status,"hitl-pending")
        badge_cls  = {"Approved":"badge-approved","Rejected":"badge-rejected","Pending":"badge-pending"}.get(rev_status,"badge-pending")
        badge_icon = {"Approved":"✅","Rejected":"❌","Pending":"⏳"}.get(rev_status,"⏳")
        s_name = ENTITIES.get(row["seller"],{}).get("name",row["seller"])
        b_name = ENTITIES.get(row["buyer"], {}).get("name",row["buyer"])
        pmin   = round((1-row["pcon_seller"])*100,0)
        nci_tag = f" · NCI {pmin:.0f}%" if pmin > 0 else ""

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
    &nbsp;|&nbsp; <strong>Flow:</strong> {row.get('flow','—')}
    &nbsp;|&nbsp; <strong>Custom3:</strong> {row.get('custom3_ccy','—')}{nci_tag}
  </div>
  <div style="font-size:13px;color:#555;">
    <strong>Amount:</strong> ${row['seller_usd']:,.0f} USD &nbsp;|&nbsp;
    <strong>Match:</strong> {row['match_status']} &nbsp;|&nbsp;
    <strong>Gap:</strong> {row['gap_pct']:.2f}%
    &nbsp;|&nbsp; <strong>Account:</strong> {row.get('account_code','—')}
  </div>
</div>""", unsafe_allow_html=True)

        with st.expander(f"📋 View Entries & Action — {txn_id}"):
            col_je,col_act = st.columns([3,2])
            with col_je:
                st.markdown("**Proposed Journal Entries**")
                e_df = pd.DataFrame(compute_elimination(row))
                e_df["Amount (USD)"] = e_df["Amount"].abs().map("${:,.0f}".format)
                st.dataframe(e_df[["Account","Dr/Cr","Amount (USD)","Value","Audit"]],
                             use_container_width=True, height=200)
                st.info(ELIMINATION_RULES.get(row["rule_code"],{}).get("description",""))
                if row["match_status"]=="Exception":
                    st.warning(f"⚠️ Gap of {row['gap_pct']:.2f}% — review carefully before approving.")
                if row["seller_ccy"] != row["buyer_ccy"]:
                    st.info(f"💱 Cross-currency: {row['seller_ccy']} / {row['buyer_ccy']} — "
                            f"verify closing FX rate applied consistently on both sides.")
            with col_act:
                st.markdown("**Action**")
                if rev_status!="Pending":
                    st.markdown(f"**By:** {rev_data.get('reviewer','—')}")
                    st.markdown(f"**At:** {rev_data.get('ts','—')}")
                    if rev_data.get("comment"):
                        st.markdown(f"*{rev_data['comment']}*")
                    if st.button("🔄 Reset",key=f"rst_{txn_id}"):
                        reset_review(txn_id)
                        st.rerun()
                else:
                    note = st.text_area("Comment",key=f"note_{txn_id}",
                                        placeholder="Optional note...",height=70)
                    apc,rjc = st.columns(2)
                    with apc:
                        if st.button("✅ Approve",key=f"app_{txn_id}",use_container_width=True):
                            upsert_review(txn_id,"Approved",
                                          f"{reviewer_name} ({reviewer_role})",
                                          datetime.now().strftime("%Y-%m-%d %H:%M"),
                                          note or "Approved")
                            st.rerun()
                    with rjc:
                        if st.button("❌ Reject",key=f"rej_{txn_id}",use_container_width=True):
                            upsert_review(txn_id,"Rejected",
                                          f"{reviewer_name} ({reviewer_role})",
                                          datetime.now().strftime("%Y-%m-%d %H:%M"),
                                          note or "Rejected — requires investigation")
                            st.rerun()

    st.divider()
    st.markdown("#### Period Close Readiness")
    reviews  = load_reviews_from_db()
    ap_now   = sum(1 for v in reviews.values() if v.get("status")=="Approved")
    rj_now   = sum(1 for v in reviews.values() if v.get("status")=="Rejected")
    pd_now   = len(df) - ap_now - rj_now
    pct      = ap_now / max(len(df),1) * 100

    st.progress(pct/100)
    st.caption(f"{pct:.0f}% approved — {pd_now} pending, {rj_now} rejected")

    if pct==100 and rj_now==0:
        st.success("✅ All eliminations approved. Period close ready.")
    elif rj_now>0:
        st.error(f"❌ {rj_now} rejection(s) must be resolved before period close.")
    else:
        st.warning(f"⏳ {pd_now} transaction(s) awaiting review.")

    # Download review log
    rl = []
    for tid,rv in reviews.items():
        r = df[df["id"]==tid]
        if len(r)==0: continue
        r = r.iloc[0]
        rl.append({"Txn ID":tid,"Description":r["description"],
                   "Seller":r["seller"],"Buyer":r["buyer"],
                   "Rule":r["rule_code"],"Amount":f"${r['seller_usd']:,.0f}",
                   "Match":r["match_status"],"Review":rv.get("status",""),
                   "By":rv.get("reviewer",""),"At":rv.get("ts",""),"Note":rv.get("comment","")})
    if rl:
        rl_df  = pd.DataFrame(rl)
        buf_rl = io.BytesIO()
        rl_df.to_excel(buf_rl, index=False)
        st.download_button("⬇️ Download Review Log", buf_rl.getvalue(),
                           file_name=f"Helios_ReviewLog_{period_label.replace(' ','_')}.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# ════════════════════════════════════════════════════
# TAB 6 — AUDIT TRAIL
# ════════════════════════════════════════════════════
with tabs[5]:
    st.markdown("### Audit Trail")
    st.caption("Complete decision log — every transaction, every gate, every decision. "
               "Only Approved entries progress to posting.")

    reviews = load_reviews_from_db()
    audit   = []

    for _, row in filtered.iterrows():
        rv           = reviews.get(row["id"], {})
        rev_status   = rv.get("status", "Pending")
        match_status = row["match_status"]

        # Determine gate status
        if match_status in BLOCKED_MATCH:
            gate_status = "🚫 Blocked — Exception"
        elif rev_status == "Approved":
            gate_status = "✅ Approved — Posted"
        elif rev_status == "Rejected":
            gate_status = "❌ Rejected — Withheld"
        else:
            gate_status = "⏳ Pending — Awaiting Review"

        for e in compute_elimination(row):
            audit.append({
                "Txn ID":      row["id"],
                "Seller":      ENTITIES.get(row["seller"],{}).get("name", row["seller"]),
                "Buyer":       ENTITIES.get(row["buyer"], {}).get("name", row["buyer"]),
                "Rule":        row["rule_code"],
                "Flow":        row.get("flow",""),
                "Account":     e["Account"],
                "Dr/Cr":       e["Dr/Cr"],
                "Amount USD":  f"${abs(e['Amount']):,.0f}",
                "Value":       e["Value"],
                "Match":       match_status,
                "Gate Status": gate_status,
                "Reviewed By": rv.get("reviewer", "—"),
                "At":          rv.get("ts", "—"),
                "Comment":     rv.get("comment", ""),
            })

    audit_df = pd.DataFrame(audit)

    # Colour the Gate Status column
    def _gate_colour(v):
        return {
            "✅ Approved — Posted":      "background-color:#D1FAE5;color:#065F46;font-weight:600",
            "❌ Rejected — Withheld":    "background-color:#FEE2E2;color:#991B1B;font-weight:600",
            "⏳ Pending — Awaiting Review": "background-color:#FFF3CD;color:#856404",
            "🚫 Blocked — Exception":    "background-color:#F3E8FF;color:#6B21A8;font-weight:600",
        }.get(v, "")

    a1,a2,a3,a4 = st.columns(4)
    a1.metric("Total Entries",    len(audit_df))
    a2.metric("Rules Fired",      audit_df["Rule"].nunique() if not audit_df.empty else 0)
    a3.metric("Approved Entries", len(audit_df[audit_df["Gate Status"].str.startswith("✅")]) if not audit_df.empty else 0)
    a4.metric("Pending Entries",  len(audit_df[audit_df["Gate Status"].str.startswith("⏳")]) if not audit_df.empty else 0)

    if not audit_df.empty:
        st.dataframe(
            audit_df.style.map(_gate_colour, subset=["Gate Status"]),
            use_container_width=True, height=460
        )
    else:
        st.info("No transactions loaded.")

    buf_at = io.BytesIO()
    audit_df.to_excel(buf_at, index=False)
    st.download_button("⬇️ Download Audit Trail (Excel)", buf_at.getvalue(),
                       file_name=f"Helios_AuditTrail_{period_label.replace(' ','_')}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    st.divider()
    st.markdown("#### Accountability Chain — Helios Chemicals Group")
    st.markdown("""
| Step | Input | Process | Output | Owner | Gate |
|---|---|---|---|---|---|
| 1 | Helios IC Source Upload (xlsx/csv) | Bilateral matching engine | Matched / FX_Diff / Not Matched / Exception | System | Auto |
| 2 | Matched + FX_Diff + Not Matched only | Rule determination (HFM UD3 logic) | Elimination rule code (IC-001, INV-001 etc.) | System | Auto |
| 3 | Rule code + PCon + FX rates | Consolidation rules engine | Proposed [Elimination] journal entries | System | Auto |
| 4 | Proposed journals | **Human review & approval** | Approved / Rejected / Pending | **Named Controller** | 👤 HITL |
| 5 | **Approved journals only** | Ledger posting | Posted [Elimination] entries in HELIOS | Finance System | Hard gate |
| 6 | Posted entries | Consolidation proof | Helios Group financial statements | CFO / External Auditor | Final |
""")
    st.info(
        "👤 **Step 5 is a hard gate.** Only Approved transactions generate journal entries. "
        "Exception transactions are blocked at Step 1 until the gap is resolved. "
        "Pending and Rejected transactions are withheld from the journal download. "
        "All decisions are named, timestamped, and persisted in SQLite."
    )
