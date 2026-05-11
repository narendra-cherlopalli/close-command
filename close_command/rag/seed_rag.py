"""
Close Command — RAG Seed Script
Seeds all four ChromaDB collections with realistic Helios Chemicals Group data.

Run once from the project root:
    D:\\LanGraph_ChatBot\\env\\python.exe -m close_command.rag.seed_rag
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger(__name__)


def seed_all(persist_directory: str = "./close_command_vectorstore") -> None:
    from close_command.rag.vectorstore import CloseCommandVectorStore

    logger.info("Initialising VectorStore at: %s", persist_directory)
    vs = CloseCommandVectorStore(persist_directory=persist_directory)

    _seed_policy_documents(vs)
    _seed_historical_exceptions(vs)
    _seed_elimination_precedents(vs)
    _seed_period_journals(vs)

    stats = vs.get_collection_stats()
    logger.info("=" * 60)
    logger.info("Seeding complete. Collection counts:")
    for name, count in stats.items():
        logger.info("  %-35s %d documents", name, count)
    logger.info("=" * 60)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Policy Documents  (elimination rules + entity profiles)
# ─────────────────────────────────────────────────────────────────────────────

def _seed_policy_documents(vs) -> None:
    logger.info("Seeding policy documents ...")
    vs.seed_policy_documents()

    # Extra FX & NCI policy documents
    extra_policies = [
        {
            "doc_id": "policy-fx-001",
            "title": "Group FX Translation Policy",
            "category": "FX_POLICY",
            "rule_code": "FX-001",
            "content": (
                "All intercompany transactions are translated to USD at the spot rate "
                "on the transaction date. Balance sheet items are translated at the "
                "closing rate. P&L items are translated at the average rate for the period. "
                "FX differences arising on IC balances are recognised in Other Comprehensive Income. "
                "Tolerance for IC matching discrepancies due to FX: 2% of the smaller balance."
            ),
        },
        {
            "doc_id": "policy-fx-002",
            "title": "FX Difference Approval Policy",
            "category": "FX_POLICY",
            "rule_code": "FX-002",
            "content": (
                "IC FX differences below 2% gap are automatically approved at close. "
                "Differences between 2% and 5% require controller sign-off. "
                "Differences above 5% require CFO approval and must be escalated. "
                "All FX differences are eliminated via rule FX-001 using the average rate."
            ),
        },
        {
            "doc_id": "policy-nci-001",
            "title": "Non-Controlling Interest Policy",
            "category": "NCI_POLICY",
            "rule_code": "EQ-001",
            "content": (
                "NCI is measured at the proportionate share of the acquiree's net assets. "
                "HCG-SG: pcon 75%, pown 75% — NCI 25%. "
                "HCG-NL: pcon 60%, pown 60% — NCI 40%. "
                "HCG-JP: pcon 40%, pown 40% — NCI 60%. "
                "NCI share of P&L and equity is presented separately in the consolidated statements. "
                "Elimination entries for NCI entities are adjusted by pcon percentage."
            ),
        },
        {
            "doc_id": "policy-ic-001",
            "title": "Intercompany Trading Policy",
            "category": "IC_POLICY",
            "rule_code": "IC-001",
            "content": (
                "All intercompany sales must be recorded at arm's length transfer prices. "
                "IC invoices must be raised within 5 business days of the transaction. "
                "Counterpart entities must confirm receipt and agree balances within 10 business days. "
                "Unresolved IC differences at period close must be escalated to Group Finance."
            ),
        },
        {
            "doc_id": "policy-ic-002",
            "title": "Intercompany Loan Policy",
            "category": "IC_POLICY",
            "rule_code": "IC-006",
            "content": (
                "IC loans must be documented with a formal loan agreement. "
                "Interest rates must reflect arm's length commercial rates. "
                "IC interest income and expense must net to zero at group level. "
                "IC loan balances (IC-003) and interest (IC-006) are eliminated separately."
            ),
        },
    ]

    for doc in extra_policies:
        vs.add_policy_document(doc)
        logger.info("  Indexed policy: %s", doc["title"])

    logger.info("Policy documents seeded.")


# ─────────────────────────────────────────────────────────────────────────────
# 2. Historical Exceptions  (prior period IC mismatches with resolutions)
# ─────────────────────────────────────────────────────────────────────────────

def _seed_historical_exceptions(vs) -> None:
    logger.info("Seeding historical exceptions ...")

    exceptions = [
        {
            "txn_id": "EXC-2024-01-001",
            "seller_entity": "HCG-UK",
            "buyer_entity": "HCG-DE",
            "rule_code": "IC-001",
            "gap_pct": 3.2,
            "gap_usd": 48000.0,
            "root_cause": "Timing difference — HCG-DE recorded invoice in next period due to local accounting cutoff. UK raised invoice on 31 Dec, DE booked 2 Jan.",
            "resolution": "DE accrued the liability at 31 Dec and reversed in January. Both entities agreed balance. Approved by controller.",
            "period": "2024-01",
        },
        {
            "txn_id": "EXC-2024-01-002",
            "seller_entity": "HCG-US",
            "buyer_entity": "HCG-SG",
            "rule_code": "IC-001",
            "gap_pct": 4.7,
            "gap_usd": 112000.0,
            "root_cause": "FX rate difference — US booked at spot rate USD/SGD 1.34, SG booked at bank rate 1.31. Difference of 0.03 on $3.7M transaction.",
            "resolution": "FX-001 elimination applied using average rate. Residual $112K difference posted to OCI FX reserve. Approved by Group Finance.",
            "period": "2024-01",
        },
        {
            "txn_id": "EXC-2024-02-001",
            "seller_entity": "HCG-DE",
            "buyer_entity": "HCG-FR",
            "rule_code": "IC-002",
            "gap_pct": 1.8,
            "gap_usd": 22500.0,
            "root_cause": "Credit note issued by DE after FR submitted their close data. FR had not deducted the credit note from their COGS.",
            "resolution": "FR restated COGS to include credit note deduction. IC balance agreed. Approved.",
            "period": "2024-02",
        },
        {
            "txn_id": "EXC-2024-02-002",
            "seller_entity": "HCG-UK",
            "buyer_entity": "HCG-AU",
            "rule_code": "IC-003",
            "gap_pct": 0.9,
            "gap_usd": 8900.0,
            "root_cause": "Rounding difference in AUD/GBP conversion — AU used mid-market rate, UK used group treasury rate. Sub-1% difference within tolerance.",
            "resolution": "Within 2% FX tolerance. Auto-approved. FX-001 elimination entry posted.",
            "period": "2024-02",
        },
        {
            "txn_id": "EXC-2024-03-001",
            "seller_entity": "HCG-NL",
            "buyer_entity": "HCG-UK",
            "rule_code": "IC-001",
            "gap_pct": 6.1,
            "gap_usd": 185000.0,
            "root_cause": "Disputed invoice — HCG-UK rejected partial shipment of €2.1M chemicals order due to quality issue. NL recognised full revenue, UK booked only 70% as goods received.",
            "resolution": "Escalated to CFO. UK to accrue remaining 30% as goods-in-transit. NL to defer revenue on disputed portion. Adjusted and re-approved next period.",
            "period": "2024-03",
        },
        {
            "txn_id": "EXC-2024-03-002",
            "seller_entity": "HCG-JP",
            "buyer_entity": "HCG-US",
            "rule_code": "IC-005",
            "gap_pct": 2.4,
            "gap_usd": 31000.0,
            "root_cause": "Management fee accrual difference — JP accrued $1.3M management fee, US only accrued $1.27M. Calculation based on different revenue base.",
            "resolution": "Group Finance confirmed correct base is gross revenue ex-IC. US restated accrual. Agreed at $1.3M. Approved.",
            "period": "2024-03",
        },
        {
            "txn_id": "EXC-2024-04-001",
            "seller_entity": "HCG-FR",
            "buyer_entity": "HCG-DE",
            "rule_code": "IC-004",
            "gap_pct": 1.1,
            "gap_usd": 14200.0,
            "root_cause": "Royalty calculation rounding — FR computed royalty on net sales, DE expected gross sales basis. Minor difference within tolerance.",
            "resolution": "Policy clarified: royalties based on net sales. FR calculation correct. DE aligned. Auto-approved within 2% threshold.",
            "period": "2024-04",
        },
        {
            "txn_id": "EXC-2024-05-001",
            "seller_entity": "HCG-UK",
            "buyer_entity": "HCG-JP",
            "rule_code": "IC-001",
            "gap_pct": 5.8,
            "gap_usd": 267000.0,
            "root_cause": "Exchange rate volatility — GBP/JPY moved 4.2% during quarter. UK invoiced at quarter start rate, JP converted at quarter end rate.",
            "resolution": "Escalated. Group treasury confirmed average rate to be used for elimination. FX difference of $267K posted to OCI. CFO approved.",
            "period": "2024-05",
        },
        {
            "txn_id": "EXC-2024-06-001",
            "seller_entity": "HCG-SHARED",
            "buyer_entity": "HCG-SG",
            "rule_code": "IC-005",
            "gap_pct": 3.5,
            "gap_usd": 42000.0,
            "root_cause": "Shared services allocation — SG disputed allocation of IT costs. SHARED charged based on headcount, SG expected FTE basis.",
            "resolution": "Allocation basis confirmed as headcount per Group Services Agreement. SG accepted charge. Approved.",
            "period": "2024-06",
        },
        {
            "txn_id": "EXC-2024-07-001",
            "seller_entity": "HCG-DE",
            "buyer_entity": "HCG-US",
            "rule_code": "IC-006",
            "gap_pct": 0.5,
            "gap_usd": 6500.0,
            "root_cause": "Interest accrual timing — DE accrued interest to 31 Jul, US accrued to 30 Jul. One day difference on €10M IC loan at 3.5% p.a.",
            "resolution": "Within tolerance. Both entities adjusted to 31 Jul. Agreed. Auto-approved.",
            "period": "2024-07",
        },
    ]

    for exc in exceptions:
        vs.add_historical_exception(exc)
        logger.info("  Indexed exception: %s (%s vs %s, %.1f%%)",
                    exc["txn_id"], exc["seller_entity"], exc["buyer_entity"], exc["gap_pct"])

    logger.info("Historical exceptions seeded: %d records", len(exceptions))


# ─────────────────────────────────────────────────────────────────────────────
# 3. Elimination Precedents  (approved journal entries from prior periods)
# ─────────────────────────────────────────────────────────────────────────────

def _seed_elimination_precedents(vs) -> None:
    logger.info("Seeding elimination precedents ...")

    precedents = [
        {
            "txn_id": "PREC-2024-07-001",
            "rule_code": "IC-001",
            "seller": "HCG-UK",
            "buyer": "HCG-DE",
            "account": "IC Revenue / IC COGS",
            "amount_usd": 1500000.0,
            "entity_method": "GLOBAL",
            "pcon": 100.0,
            "period": "2024-07",
            "scenario": "ACTUAL",
        },
        {
            "txn_id": "PREC-2024-07-002",
            "rule_code": "IC-001",
            "seller": "HCG-US",
            "buyer": "HCG-SG",
            "account": "IC Revenue / IC COGS",
            "amount_usd": 2380000.0,
            "entity_method": "GLOBAL",
            "pcon": 75.0,
            "period": "2024-07",
            "scenario": "ACTUAL",
        },
        {
            "txn_id": "PREC-2024-07-003",
            "rule_code": "IC-002",
            "seller": "HCG-DE",
            "buyer": "HCG-FR",
            "account": "IC Revenue / IC COGS",
            "amount_usd": 890000.0,
            "entity_method": "GLOBAL",
            "pcon": 100.0,
            "period": "2024-07",
            "scenario": "ACTUAL",
        },
        {
            "txn_id": "PREC-2024-07-004",
            "rule_code": "IC-003",
            "seller": "HCG-UK",
            "buyer": "HCG-AU",
            "account": "IC Loan Receivable / IC Loan Payable",
            "amount_usd": 5000000.0,
            "entity_method": "GLOBAL",
            "pcon": 100.0,
            "period": "2024-07",
            "scenario": "ACTUAL",
        },
        {
            "txn_id": "PREC-2024-07-005",
            "rule_code": "IC-006",
            "seller": "HCG-DE",
            "buyer": "HCG-US",
            "account": "IC Interest Income / IC Interest Expense",
            "amount_usd": 145833.0,
            "entity_method": "GLOBAL",
            "pcon": 100.0,
            "period": "2024-07",
            "scenario": "ACTUAL",
        },
        {
            "txn_id": "PREC-2024-07-006",
            "rule_code": "IC-005",
            "seller": "HCG-SHARED",
            "buyer": "HCG-SG",
            "account": "IC Management Fee / IC Cost",
            "amount_usd": 1200000.0,
            "entity_method": "GLOBAL",
            "pcon": 75.0,
            "period": "2024-07",
            "scenario": "ACTUAL",
        },
        {
            "txn_id": "PREC-2024-07-007",
            "rule_code": "IC-004",
            "seller": "HCG-FR",
            "buyer": "HCG-DE",
            "account": "IC Royalty Income / IC Royalty Expense",
            "amount_usd": 320000.0,
            "entity_method": "GLOBAL",
            "pcon": 100.0,
            "period": "2024-07",
            "scenario": "ACTUAL",
        },
        {
            "txn_id": "PREC-2024-07-008",
            "rule_code": "EQ-001",
            "seller": "HCG",
            "buyer": "HCG-NL",
            "account": "Investment in Subsidiary / Share Capital",
            "amount_usd": 12000000.0,
            "entity_method": "GLOBAL",
            "pcon": 60.0,
            "period": "2024-07",
            "scenario": "ACTUAL",
        },
        {
            "txn_id": "PREC-2024-07-009",
            "rule_code": "IC-001",
            "seller": "HCG-NL",
            "buyer": "HCG-UK",
            "account": "IC Revenue / IC COGS",
            "amount_usd": 3040000.0,
            "entity_method": "GLOBAL",
            "pcon": 60.0,
            "period": "2024-07",
            "scenario": "ACTUAL",
        },
        {
            "txn_id": "PREC-2024-07-010",
            "rule_code": "IC-001",
            "seller": "HCG-JP",
            "buyer": "HCG-US",
            "account": "IC Revenue / IC COGS",
            "amount_usd": 4600000.0,
            "entity_method": "GLOBAL",
            "pcon": 40.0,
            "period": "2024-07",
            "scenario": "ACTUAL",
        },
        {
            "txn_id": "PREC-2024-06-001",
            "rule_code": "IC-001",
            "seller": "HCG-UK",
            "buyer": "HCG-DE",
            "account": "IC Revenue / IC COGS",
            "amount_usd": 1420000.0,
            "entity_method": "GLOBAL",
            "pcon": 100.0,
            "period": "2024-06",
            "scenario": "ACTUAL",
        },
        {
            "txn_id": "PREC-2024-06-002",
            "rule_code": "IC-005",
            "seller": "HCG-SHARED",
            "buyer": "HCG-JP",
            "account": "IC Management Fee / IC Cost",
            "amount_usd": 480000.0,
            "entity_method": "GLOBAL",
            "pcon": 40.0,
            "period": "2024-06",
            "scenario": "ACTUAL",
        },
    ]

    for prec in precedents:
        vs.add_elimination_precedent(prec)
        logger.info("  Indexed precedent: %s (%s -> %s, %s, $%s)",
                    prec["txn_id"], prec["seller"], prec["buyer"],
                    prec["rule_code"], f"{prec['amount_usd']:,.0f}")

    logger.info("Elimination precedents seeded: %d records", len(precedents))


# ─────────────────────────────────────────────────────────────────────────────
# 4. Period Journals  (completed prior-period close journal entries)
# ─────────────────────────────────────────────────────────────────────────────

def _seed_period_journals(vs) -> None:
    logger.info("Seeding period journals ...")

    journals = [
        # 2024-07 ACTUAL approved journals
        {"txn_id": "JNL-2024-07-001", "seller": "HCG-UK", "buyer": "HCG-DE",
         "rule_code": "IC-001", "account": "IC Revenue", "amount_usd": 1500000.0,
         "period": "2024-07", "scenario": "ACTUAL"},
        {"txn_id": "JNL-2024-07-002", "seller": "HCG-US", "buyer": "HCG-SG",
         "rule_code": "IC-001", "account": "IC Revenue", "amount_usd": 2380000.0,
         "period": "2024-07", "scenario": "ACTUAL"},
        {"txn_id": "JNL-2024-07-003", "seller": "HCG-DE", "buyer": "HCG-FR",
         "rule_code": "IC-002", "account": "IC Revenue", "amount_usd": 890000.0,
         "period": "2024-07", "scenario": "ACTUAL"},
        {"txn_id": "JNL-2024-07-004", "seller": "HCG-UK", "buyer": "HCG-AU",
         "rule_code": "IC-003", "account": "IC Loan Receivable", "amount_usd": 5000000.0,
         "period": "2024-07", "scenario": "ACTUAL"},
        {"txn_id": "JNL-2024-07-005", "seller": "HCG-SHARED", "buyer": "HCG-SG",
         "rule_code": "IC-005", "account": "IC Management Fee", "amount_usd": 1200000.0,
         "period": "2024-07", "scenario": "ACTUAL"},
        {"txn_id": "JNL-2024-07-006", "seller": "HCG-FR", "buyer": "HCG-DE",
         "rule_code": "IC-004", "account": "IC Royalty", "amount_usd": 320000.0,
         "period": "2024-07", "scenario": "ACTUAL"},
        # 2024-06 ACTUAL approved journals
        {"txn_id": "JNL-2024-06-001", "seller": "HCG-UK", "buyer": "HCG-DE",
         "rule_code": "IC-001", "account": "IC Revenue", "amount_usd": 1420000.0,
         "period": "2024-06", "scenario": "ACTUAL"},
        {"txn_id": "JNL-2024-06-002", "seller": "HCG-US", "buyer": "HCG-SG",
         "rule_code": "IC-001", "account": "IC Revenue", "amount_usd": 2100000.0,
         "period": "2024-06", "scenario": "ACTUAL"},
        {"txn_id": "JNL-2024-06-003", "seller": "HCG-DE", "buyer": "HCG-US",
         "rule_code": "IC-006", "account": "IC Interest", "amount_usd": 145833.0,
         "period": "2024-06", "scenario": "ACTUAL"},
        {"txn_id": "JNL-2024-06-004", "seller": "HCG-SHARED", "buyer": "HCG-JP",
         "rule_code": "IC-005", "account": "IC Management Fee", "amount_usd": 480000.0,
         "period": "2024-06", "scenario": "ACTUAL"},
        # 2024-05 ACTUAL approved journals
        {"txn_id": "JNL-2024-05-001", "seller": "HCG-UK", "buyer": "HCG-JP",
         "rule_code": "IC-001", "account": "IC Revenue", "amount_usd": 4600000.0,
         "period": "2024-05", "scenario": "ACTUAL"},
        {"txn_id": "JNL-2024-05-002", "seller": "HCG-NL", "buyer": "HCG-UK",
         "rule_code": "IC-001", "account": "IC Revenue", "amount_usd": 2950000.0,
         "period": "2024-05", "scenario": "ACTUAL"},
        {"txn_id": "JNL-2024-05-003", "seller": "HCG-FR", "buyer": "HCG-AU",
         "rule_code": "IC-002", "account": "IC Revenue", "amount_usd": 760000.0,
         "period": "2024-05", "scenario": "ACTUAL"},
    ]

    for jnl in journals:
        vs.add_period_journal(jnl)
        logger.info("  Indexed journal: %s (%s → %s, %s)",
                    jnl["txn_id"], jnl["seller"], jnl["buyer"], jnl["rule_code"])

    logger.info("Period journals seeded: %d records", len(journals))


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    vs_path = os.environ.get(
        "CLOSE_COMMAND_VECTORSTORE_PATH",
        os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                     "close_command_vectorstore")
    )
    seed_all(persist_directory=vs_path)
