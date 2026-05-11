"""
gen_sample.py
Generates sample_entity_financials.csv for the HCG intercompany reconciliation demo.
"""

import csv
import os

OUTPUT_PATH = r"D:\LanGraph_ChatBot\close_command\sample_entity_financials.csv"

COLUMNS = [
    "line_id", "entity_code", "account_code", "account_description",
    "account_type", "account_category", "is_intercompany", "icp_entity",
    "rule_code", "flow", "amount", "currency", "period", "scenario"
]

PERIOD = "2024-12"
SCENARIO = "Actual"
FLOW = "F00"

rows = []
line_id = 1

def add(entity, acct_code, acct_desc, acct_type, acct_cat, is_ic, icp, rule, amount, currency):
    global line_id
    rows.append({
        "line_id": line_id,
        "entity_code": entity,
        "account_code": acct_code,
        "account_description": acct_desc,
        "account_type": acct_type,
        "account_category": acct_cat,
        "is_intercompany": is_ic,
        "icp_entity": icp,
        "rule_code": rule,
        "flow": FLOW,
        "amount": amount,
        "currency": currency,
        "period": PERIOD,
        "scenario": SCENARIO,
    })
    line_id += 1

# ─────────────────────────────────────────────
# HCG-UK  (GBP)
# ─────────────────────────────────────────────
# Non-IC Revenue
add("HCG-UK","4000","Product Revenue","P&L","Revenue",False,"","",28_500_000,"GBP")
add("HCG-UK","4010","Service Revenue","P&L","Revenue",False,"","",14_200_000,"GBP")
add("HCG-UK","4020","Other Revenue","P&L","Revenue",False,"","",9_800_000,"GBP")
# Non-IC COGS
add("HCG-UK","5000","Cost of Goods Sold","P&L","COGS",False,"","",-18_200_000,"GBP")
add("HCG-UK","5010","Service Delivery Cost","P&L","COGS",False,"","",-6_500_000,"GBP")
# Non-IC OpEx
add("HCG-UK","6000","Selling & Marketing","P&L","OpEx",False,"","",-7_400_000,"GBP")
add("HCG-UK","6010","General & Admin","P&L","OpEx",False,"","",-2_100_000,"GBP")
add("HCG-UK","6020","R&D Expense","P&L","OpEx",False,"","",-3_200_000,"GBP")
# IC P&L – HCG-UK sells to HCG-DE (IC-001, GBP, FX mismatch)
add("HCG-UK","4100","IC Product Revenue – HCG-DE","P&L","Revenue",True,"HCG-DE","IC-001",5_000_000,"GBP")
# IC P&L – HCG-UK sells mgmt services to HCG-US (IC-004)
add("HCG-UK","4110","IC Mgmt Services Revenue – HCG-US","P&L","Revenue",True,"HCG-US","IC-004",1_800_000,"GBP")
# IC P&L – HCG-UK sells royalties to HCG-SG (IC-005, cross-currency FX Diff)
add("HCG-UK","4120","IC Royalty Revenue – HCG-SG","P&L","Revenue",True,"HCG-SG","IC-005",900_000,"GBP")
# IC P&L – SHARED sells services to HCG-UK (IC-001, GBP matched)
add("HCG-UK","5100","IC Service Cost – SHARED","P&L","COGS",True,"SHARED","IC-001",-2_200_000,"GBP")
# Non-IC BS Assets
add("HCG-UK","1000","Trade Receivables","BS","Asset",False,"","",12_400_000,"GBP")
add("HCG-UK","1500","Property Plant & Equipment","BS","Asset",False,"","",45_000_000,"GBP")
add("HCG-UK","1100","Inventory","BS","Asset",False,"","",18_000_000,"GBP")
# IC BS – Receivable from HCG-DE (IC-002)
add("HCG-UK","1600","IC Receivable – HCG-DE","BS","Asset",True,"HCG-DE","IC-002",5_000_000,"GBP")
# IC BS – Receivable from HCG-US (IC-002)
add("HCG-UK","1610","IC Receivable – HCG-US","BS","Asset",True,"HCG-US","IC-002",1_800_000,"GBP")
# IC BS – Receivable from HCG-SG (IC-002)
add("HCG-UK","1620","IC Receivable – HCG-SG","BS","Asset",True,"HCG-SG","IC-002",900_000,"GBP")
# IC BS – Payable to SHARED (IC-002)
add("HCG-UK","2600","IC Payable – SHARED","BS","Liability",True,"SHARED","IC-002",-2_200_000,"GBP")
# Non-IC BS Liabilities
add("HCG-UK","2000","Trade Payables","BS","Liability",False,"","",-8_900_000,"GBP")
add("HCG-UK","2100","Long-term Debt","BS","Liability",False,"","",-15_000_000,"GBP")

# ─────────────────────────────────────────────
# HCG-DE  (EUR)
# ─────────────────────────────────────────────
# Non-IC Revenue
add("HCG-DE","4000","Product Revenue","P&L","Revenue",False,"","",22_000_000,"EUR")
add("HCG-DE","4010","Service Revenue","P&L","Revenue",False,"","",16_500_000,"EUR")
add("HCG-DE","4020","Other Revenue","P&L","Revenue",False,"","",8_700_000,"EUR")
# Non-IC COGS
add("HCG-DE","5000","Cost of Goods Sold","P&L","COGS",False,"","",-14_200_000,"EUR")
add("HCG-DE","5010","Service Delivery Cost","P&L","COGS",False,"","",-4_800_000,"EUR")
# Non-IC OpEx
add("HCG-DE","6000","Selling & Marketing","P&L","OpEx",False,"","",-6_100_000,"EUR")
add("HCG-DE","6010","General & Admin","P&L","OpEx",False,"","",-1_900_000,"EUR")
add("HCG-DE","6020","R&D Expense","P&L","OpEx",False,"","",-2_800_000,"EUR")
# IC P&L – HCG-UK sells to HCG-DE (buyer side, EUR, FX mismatch with GBP 5M)
add("HCG-DE","5100","IC Product Cost – HCG-UK","P&L","COGS",True,"HCG-UK","IC-001",-5_450_000,"EUR")
# IC P&L – HCG-DE sells to HCG-FR (IC-001, EUR matched)
add("HCG-DE","4100","IC Product Revenue – HCG-FR","P&L","Revenue",True,"HCG-FR","IC-001",4_200_000,"EUR")
# IC P&L – HCG-DE sells mgmt services to HCG-NL (IC-004, EUR matched)
add("HCG-DE","4110","IC Mgmt Services Revenue – HCG-NL","P&L","Revenue",True,"HCG-NL","IC-004",1_500_000,"EUR")
# IC P&L – SHARED sells IT to HCG-DE (IC-004, EUR)
add("HCG-DE","5110","IC IT Services Cost – SHARED","P&L","COGS",True,"SHARED","IC-004",-872_000,"EUR")
# Non-IC BS Assets
add("HCG-DE","1000","Trade Receivables","BS","Asset",False,"","",9_800_000,"EUR")
add("HCG-DE","1500","Property Plant & Equipment","BS","Asset",False,"","",38_000_000,"EUR")
# IC BS – Payable to HCG-UK (IC-002)
add("HCG-DE","2600","IC Payable – HCG-UK","BS","Liability",True,"HCG-UK","IC-002",-5_450_000,"EUR")
# IC BS – Receivable from HCG-FR (IC-002)
add("HCG-DE","1600","IC Receivable – HCG-FR","BS","Asset",True,"HCG-FR","IC-002",4_200_000,"EUR")
# IC BS – Receivable from HCG-NL (IC-002)
add("HCG-DE","1610","IC Receivable – HCG-NL","BS","Asset",True,"HCG-NL","IC-002",1_500_000,"EUR")
# IC BS – Payable to SHARED (IC-002)
add("HCG-DE","2610","IC Payable – SHARED","BS","Liability",True,"SHARED","IC-002",-872_000,"EUR")
# Non-IC BS Liabilities
add("HCG-DE","2000","Trade Payables","BS","Liability",False,"","",-7_200_000,"EUR")
add("HCG-DE","2100","Long-term Debt","BS","Liability",False,"","",-20_000_000,"EUR")

# ─────────────────────────────────────────────
# HCG-US  (USD)
# ─────────────────────────────────────────────
# Non-IC Revenue
add("HCG-US","4000","Product Revenue","P&L","Revenue",False,"","",31_000_000,"USD")
add("HCG-US","4010","Service Revenue","P&L","Revenue",False,"","",12_500_000,"USD")
add("HCG-US","4020","Other Revenue","P&L","Revenue",False,"","",7_200_000,"USD")
# Non-IC COGS
add("HCG-US","5000","Cost of Goods Sold","P&L","COGS",False,"","",-19_800_000,"USD")
add("HCG-US","5010","Service Delivery Cost","P&L","COGS",False,"","",-4_100_000,"USD")
# Non-IC OpEx
add("HCG-US","6000","Selling & Marketing","P&L","OpEx",False,"","",-8_200_000,"USD")
add("HCG-US","6010","General & Admin","P&L","OpEx",False,"","",-2_400_000,"USD")
add("HCG-US","6020","R&D Expense","P&L","OpEx",False,"","",-3_600_000,"USD")
# IC P&L – HCG-UK sells mgmt services to HCG-US (buyer side, USD matched)
add("HCG-US","5100","IC Mgmt Services Cost – HCG-UK","P&L","COGS",True,"HCG-UK","IC-004",-2_286_000,"USD")
# IC P&L – HCG-US sells to HCG-AU (IC-001, USD revenue / AUD cost cross-currency)
add("HCG-US","4100","IC Product Revenue – HCG-AU","P&L","Revenue",True,"HCG-AU","IC-001",3_500_000,"USD")
# IC P&L – HCG-US sells royalties to HCG-SG (IC-005, cross-currency)
add("HCG-US","4110","IC Royalty Revenue – HCG-SG","P&L","Revenue",True,"HCG-SG","IC-005",1_200_000,"USD")
# IC P&L – SHARED sells HR to HCG-US (IC-004, USD)
add("HCG-US","5110","IC HR Services Cost – SHARED","P&L","COGS",True,"SHARED","IC-004",-762_000,"USD")
# Non-IC BS Assets
add("HCG-US","1000","Trade Receivables","BS","Asset",False,"","",15_200_000,"USD")
add("HCG-US","1500","Property Plant & Equipment","BS","Asset",False,"","",52_000_000,"USD")
add("HCG-US","1100","Inventory","BS","Asset",False,"","",8_500_000,"USD")
# IC BS – Payable to HCG-UK (IC-002)
add("HCG-US","2600","IC Payable – HCG-UK","BS","Liability",True,"HCG-UK","IC-002",-2_286_000,"USD")
# IC BS – Receivable from HCG-AU (IC-002)
add("HCG-US","1600","IC Receivable – HCG-AU","BS","Asset",True,"HCG-AU","IC-002",3_500_000,"USD")
# IC BS – Receivable from HCG-SG (IC-002)
add("HCG-US","1610","IC Receivable – HCG-SG","BS","Asset",True,"HCG-SG","IC-002",1_200_000,"USD")
# IC BS – Payable to SHARED (IC-002)
add("HCG-US","2610","IC Payable – SHARED","BS","Liability",True,"SHARED","IC-002",-762_000,"USD")
# Non-IC BS Liabilities
add("HCG-US","2000","Trade Payables","BS","Liability",False,"","",-11_200_000,"USD")
add("HCG-US","2100","Long-term Debt","BS","Liability",False,"","",-25_000_000,"USD")

# ─────────────────────────────────────────────
# HCG-SG  (SGD)
# ─────────────────────────────────────────────
# Non-IC Revenue
add("HCG-SG","4000","Product Revenue","P&L","Revenue",False,"","",18_000_000,"SGD")
add("HCG-SG","4010","Service Revenue","P&L","Revenue",False,"","",9_500_000,"SGD")
# Non-IC COGS
add("HCG-SG","5000","Cost of Goods Sold","P&L","COGS",False,"","",-11_200_000,"SGD")
add("HCG-SG","5010","Service Delivery Cost","P&L","COGS",False,"","",-3_100_000,"SGD")
# Non-IC OpEx
add("HCG-SG","6000","Selling & Marketing","P&L","OpEx",False,"","",-4_200_000,"SGD")
add("HCG-SG","6010","General & Admin","P&L","OpEx",False,"","",-900_000,"SGD")
add("HCG-SG","6020","R&D Expense","P&L","OpEx",False,"","",-1_800_000,"SGD")
# IC P&L – HCG-UK sells royalties to HCG-SG (buyer side, SGD FX Diff)
add("HCG-SG","5100","IC Royalty Cost – HCG-UK","P&L","COGS",True,"HCG-UK","IC-005",-1_216_216,"SGD")
# IC P&L – HCG-US sells royalties to HCG-SG (buyer side, SGD FX Diff)
add("HCG-SG","5110","IC Royalty Cost – HCG-US","P&L","COGS",True,"HCG-US","IC-005",-1_621_622,"SGD")
# Non-IC BS Assets
add("HCG-SG","1000","Trade Receivables","BS","Asset",False,"","",6_200_000,"SGD")
add("HCG-SG","1500","Property Plant & Equipment","BS","Asset",False,"","",14_000_000,"SGD")
# IC BS – Payable to HCG-UK (IC-002)
add("HCG-SG","2600","IC Payable – HCG-UK","BS","Liability",True,"HCG-UK","IC-002",-1_216_216,"SGD")
# IC BS – Payable to HCG-US (IC-002)
add("HCG-SG","2610","IC Payable – HCG-US","BS","Liability",True,"HCG-US","IC-002",-1_621_622,"SGD")
# Non-IC BS Liabilities
add("HCG-SG","2000","Trade Payables","BS","Liability",False,"","",-4_500_000,"SGD")
add("HCG-SG","2100","Long-term Debt","BS","Liability",False,"","",-8_000_000,"SGD")

# ─────────────────────────────────────────────
# HCG-FR  (EUR)
# ─────────────────────────────────────────────
# Non-IC Revenue
add("HCG-FR","4000","Product Revenue","P&L","Revenue",False,"","",15_000_000,"EUR")
add("HCG-FR","4010","Service Revenue","P&L","Revenue",False,"","",8_200_000,"EUR")
# Non-IC COGS
add("HCG-FR","5000","Cost of Goods Sold","P&L","COGS",False,"","",-9_800_000,"EUR")
add("HCG-FR","5010","Service Delivery Cost","P&L","COGS",False,"","",-1_200_000,"EUR")
# Non-IC OpEx
add("HCG-FR","6000","Selling & Marketing","P&L","OpEx",False,"","",-4_500_000,"EUR")
add("HCG-FR","6010","General & Admin","P&L","OpEx",False,"","",-1_100_000,"EUR")
add("HCG-FR","6020","R&D Expense","P&L","OpEx",False,"","",-2_200_000,"EUR")
# IC P&L – HCG-DE sells to HCG-FR (buyer side, EUR matched)
add("HCG-FR","5100","IC Product Cost – HCG-DE","P&L","COGS",True,"HCG-DE","IC-001",-4_200_000,"EUR")
# Non-IC BS Assets
add("HCG-FR","1000","Trade Receivables","BS","Asset",False,"","",4_100_000,"EUR")
add("HCG-FR","1500","Property Plant & Equipment","BS","Asset",False,"","",18_000_000,"EUR")
# IC BS – Payable to HCG-DE (IC-002)
add("HCG-FR","2600","IC Payable – HCG-DE","BS","Liability",True,"HCG-DE","IC-002",-4_200_000,"EUR")
# Non-IC BS Liabilities
add("HCG-FR","2000","Trade Payables","BS","Liability",False,"","",-5_600_000,"EUR")
add("HCG-FR","2100","Long-term Debt","BS","Liability",False,"","",-10_000_000,"EUR")

# ─────────────────────────────────────────────
# HCG-NL  (EUR)
# ─────────────────────────────────────────────
# Non-IC Revenue
add("HCG-NL","4000","Product Revenue","P&L","Revenue",False,"","",11_000_000,"EUR")
add("HCG-NL","4010","Service Revenue","P&L","Revenue",False,"","",5_800_000,"EUR")
# Non-IC COGS
add("HCG-NL","5000","Cost of Goods Sold","P&L","COGS",False,"","",-7_200_000,"EUR")
add("HCG-NL","5010","Service Delivery Cost","P&L","COGS",False,"","",-1_800_000,"EUR")
# Non-IC OpEx
add("HCG-NL","6000","Selling & Marketing","P&L","OpEx",False,"","",-3_100_000,"EUR")
add("HCG-NL","6010","General & Admin","P&L","OpEx",False,"","",-700_000,"EUR")
add("HCG-NL","6020","R&D Expense","P&L","OpEx",False,"","",-1_400_000,"EUR")
# IC P&L – HCG-DE sells mgmt services to HCG-NL (buyer side, EUR matched)
add("HCG-NL","5100","IC Mgmt Services Cost – HCG-DE","P&L","COGS",True,"HCG-DE","IC-004",-1_500_000,"EUR")
# Non-IC BS Assets
add("HCG-NL","1000","Trade Receivables","BS","Asset",False,"","",3_200_000,"EUR")
add("HCG-NL","1500","Property Plant & Equipment","BS","Asset",False,"","",12_000_000,"EUR")
# IC BS – Payable to HCG-DE (IC-002)
add("HCG-NL","2600","IC Payable – HCG-DE","BS","Liability",True,"HCG-DE","IC-002",-1_500_000,"EUR")
# Non-IC BS Liabilities
add("HCG-NL","2000","Trade Payables","BS","Liability",False,"","",-3_800_000,"EUR")
add("HCG-NL","2100","Long-term Debt","BS","Liability",False,"","",-6_000_000,"EUR")

# ─────────────────────────────────────────────
# HCG-AU  (AUD)
# ─────────────────────────────────────────────
# Non-IC Revenue
add("HCG-AU","4000","Product Revenue","P&L","Revenue",False,"","",14_000_000,"AUD")
add("HCG-AU","4010","Service Revenue","P&L","Revenue",False,"","",5_500_000,"AUD")
# Non-IC COGS
add("HCG-AU","5000","Cost of Goods Sold","P&L","COGS",False,"","",-9_100_000,"AUD")
add("HCG-AU","5010","Service Delivery Cost","P&L","COGS",False,"","",-1_200_000,"AUD")
# Non-IC OpEx
add("HCG-AU","6000","Selling & Marketing","P&L","OpEx",False,"","",-3_800_000,"AUD")
add("HCG-AU","6010","General & Admin","P&L","OpEx",False,"","",-900_000,"AUD")
add("HCG-AU","6020","R&D Expense","P&L","OpEx",False,"","",-1_600_000,"AUD")
# IC P&L – HCG-US sells to HCG-AU (buyer side, AUD FX Diff)
add("HCG-AU","5100","IC Product Cost – HCG-US","P&L","COGS",True,"HCG-US","IC-001",-5_384_615,"AUD")
# Non-IC BS Assets
add("HCG-AU","1000","Trade Receivables","BS","Asset",False,"","",4_800_000,"AUD")
add("HCG-AU","1500","Property Plant & Equipment","BS","Asset",False,"","",22_000_000,"AUD")
# IC BS – Payable to HCG-US (IC-002)
add("HCG-AU","2600","IC Payable – HCG-US","BS","Liability",True,"HCG-US","IC-002",-5_384_615,"AUD")
# Non-IC BS Liabilities
add("HCG-AU","2000","Trade Payables","BS","Liability",False,"","",-4_200_000,"AUD")
add("HCG-AU","2100","Long-term Debt","BS","Liability",False,"","",-9_000_000,"AUD")

# ─────────────────────────────────────────────
# SHARED  (GBP)
# ─────────────────────────────────────────────
# Non-IC COGS
add("SHARED","5000","Cost of Goods Sold","P&L","COGS",False,"","",-1_800_000,"GBP")
# Non-IC OpEx
add("SHARED","6010","General & Admin","P&L","OpEx",False,"","",-1_200_000,"GBP")
add("SHARED","6020","IT Infrastructure","P&L","OpEx",False,"","",-500_000,"GBP")
# IC P&L – SHARED sells services to HCG-UK (IC-001, GBP matched)
add("SHARED","4000","IC Service Revenue – HCG-UK","P&L","Revenue",True,"HCG-UK","IC-001",2_200_000,"GBP")
# IC P&L – SHARED sells IT to HCG-DE (IC-004, GBP revenue)
add("SHARED","4010","IC IT Revenue – HCG-DE","P&L","Revenue",True,"HCG-DE","IC-004",800_000,"GBP")
# IC P&L – SHARED sells HR to HCG-US (IC-004, GBP revenue)
add("SHARED","4020","IC HR Revenue – HCG-US","P&L","Revenue",True,"HCG-US","IC-004",600_000,"GBP")
# Non-IC BS Assets
add("SHARED","1000","Trade Receivables","BS","Asset",False,"","",2_100_000,"GBP")
add("SHARED","1500","Property Plant & Equipment","BS","Asset",False,"","",5_000_000,"GBP")
# IC BS – Receivable from HCG-UK (IC-002)
add("SHARED","1600","IC Receivable – HCG-UK","BS","Asset",True,"HCG-UK","IC-002",2_200_000,"GBP")
# IC BS – Receivable from HCG-DE (IC-002)
add("SHARED","1610","IC Receivable – HCG-DE","BS","Asset",True,"HCG-DE","IC-002",800_000,"GBP")
# IC BS – Receivable from HCG-US (IC-002)
add("SHARED","1620","IC Receivable – HCG-US","BS","Asset",True,"HCG-US","IC-002",600_000,"GBP")
# Non-IC BS Liabilities
add("SHARED","2000","Trade Payables","BS","Liability",False,"","",-1_500_000,"GBP")

# ─────────────────────────────────────────────
# Write CSV
# ─────────────────────────────────────────────
os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)

with open(OUTPUT_PATH, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=COLUMNS)
    writer.writeheader()
    writer.writerows(rows)

print(f"Written {len(rows)} rows to {OUTPUT_PATH}")

# Quick sanity summary
from collections import Counter
entities = Counter(r["entity_code"] for r in rows)
ic_rows  = sum(1 for r in rows if r["is_intercompany"])
print(f"IC rows: {ic_rows}  |  Non-IC rows: {len(rows)-ic_rows}")
print("Rows per entity:")
for ent, cnt in sorted(entities.items()):
    print(f"  {ent}: {cnt}")
