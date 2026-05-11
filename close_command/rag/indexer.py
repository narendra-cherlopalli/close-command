"""
Document indexing for Close Command RAG layer.
Handles indexing of resolved exceptions, completed periods,
elimination entries, and bulk historical seeding.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


class CloseCommandIndexer:
    """Indexes documents into the Close Command vector store."""

    def __init__(self, vectorstore: Any) -> None:
        """
        Args:
            vectorstore: An instance of CloseCommandVectorStore.
        """
        self.vectorstore = vectorstore

    # ──────────────────────────────────────────────────────────────────────
    # Index resolved exception
    # ──────────────────────────────────────────────────────────────────────

    def index_resolved_exception(
        self, match_result: dict, resolution: str
    ) -> bool:
        """Index a resolved match exception as a historical precedent.

        Args:
            match_result: dict containing match result fields
            resolution:   Human-readable resolution description

        Returns:
            True on success, False on failure.
        """
        try:
            exception_data = {
                "txn_id": match_result.get("txn_id") or str(uuid.uuid4()),
                "seller_entity": match_result.get("seller_entity", ""),
                "buyer_entity": match_result.get("buyer_entity", ""),
                "rule_code": match_result.get("rule_code", ""),
                "gap_pct": match_result.get("gap_pct", 0.0),
                "gap_usd": match_result.get("gap_usd", 0.0),
                "match_status": match_result.get("match_status", "Exception"),
                "root_cause": match_result.get("root_cause", "unknown"),
                "resolution": resolution,
                "period": match_result.get("period", ""),
                "scenario": match_result.get("scenario", ""),
                "batch_id": match_result.get("batch_id", ""),
            }
            self.vectorstore.add_historical_exception(exception_data)
            logger.info(
                "Indexed resolved exception txn_id=%s", exception_data["txn_id"]
            )
            return True
        except Exception as exc:
            logger.error("index_resolved_exception failed: %s", exc)
            return False

    # ──────────────────────────────────────────────────────────────────────
    # Index completed period
    # ──────────────────────────────────────────────────────────────────────

    def index_completed_period(
        self,
        batch_id: str,
        journal_entries: list[dict],
        period: str,
    ) -> int:
        """Index all journal entries from a completed period into period_journals.

        Args:
            batch_id:        The batch identifier for this period's run
            journal_entries: List of journal entry dicts
            period:          e.g. "2024-03"

        Returns:
            Number of entries successfully indexed.
        """
        indexed = 0
        for entry in journal_entries:
            try:
                journal_data = dict(entry)
                journal_data["period"] = period
                journal_data["batch_id"] = batch_id
                # Ensure txn_id present
                if not journal_data.get("txn_id"):
                    journal_data["txn_id"] = str(uuid.uuid4())
                self.vectorstore.add_period_journal(journal_data)
                indexed += 1
            except Exception as exc:
                logger.warning(
                    "Failed to index journal entry %s: %s",
                    entry.get("txn_id", "unknown"),
                    exc,
                )
        logger.info(
            "Indexed %d/%d journal entries for period %s",
            indexed,
            len(journal_entries),
            period,
        )
        return indexed

    # ──────────────────────────────────────────────────────────────────────
    # Index elimination entries
    # ──────────────────────────────────────────────────────────────────────

    def index_elimination_entries(self, entries: list[dict]) -> int:
        """Index elimination journal entries as precedents.

        Args:
            entries: List of journal entry dicts (APPROVED eliminations)

        Returns:
            Number of entries successfully indexed.
        """
        indexed = 0
        for entry in entries:
            try:
                self.vectorstore.add_elimination_precedent(entry)
                indexed += 1
            except Exception as exc:
                logger.warning(
                    "Failed to index elimination precedent %s: %s",
                    entry.get("txn_id", "unknown"),
                    exc,
                )
        logger.info("Indexed %d elimination precedents", indexed)
        return indexed

    # ──────────────────────────────────────────────────────────────────────
    # Refresh policy index
    # ──────────────────────────────────────────────────────────────────────

    def refresh_policy_index(self) -> int:
        """Re-seed the policy_documents collection with all current rules and entities.

        Returns:
            Number of documents indexed.
        """
        try:
            from data.rules import ELIMINATION_RULES
            from data.entities import ENTITY_REGISTRY

            count_before = self.vectorstore.get_collection_stats().get(
                "policy_documents", 0
            )
            self.vectorstore.seed_policy_documents()
            count_after = self.vectorstore.get_collection_stats().get(
                "policy_documents", 0
            )
            delta = count_after - count_before
            logger.info(
                "Policy index refreshed: %d -> %d documents (%+d)",
                count_before,
                count_after,
                delta,
            )
            return count_after
        except Exception as exc:
            logger.error("refresh_policy_index failed: %s", exc)
            return 0

    # ──────────────────────────────────────────────────────────────────────
    # Bulk historical seed
    # ──────────────────────────────────────────────────────────────────────

    def bulk_seed_historical_data(self) -> None:
        """Seed 20 realistic historical exception records for Helios entities."""
        HISTORICAL_EXCEPTIONS = [
            {
                "txn_id": "hist-exc-001",
                "seller_entity": "HCG-UK",
                "buyer_entity": "HCG-DE",
                "rule_code": "IC-001",
                "gap_pct": 3.2,
                "gap_usd": 48_200.0,
                "match_status": "Not Matched",
                "root_cause": "Timing difference — seller booked in Dec, buyer booked in Jan",
                "resolution": "Buyer re-posted entry to Dec period; gap eliminated",
                "period": "2023-12",
                "scenario": "Actual",
                "batch_id": "HIST-BATCH-001",
            },
            {
                "txn_id": "hist-exc-002",
                "seller_entity": "HCG-US",
                "buyer_entity": "HCG-AU",
                "rule_code": "IC-002",
                "gap_pct": 1.8,
                "gap_usd": 22_500.0,
                "match_status": "FX Diff",
                "root_cause": "FX rate mismatch — seller used month-end rate, buyer used average rate",
                "resolution": "Standardised to month-end rate per Group FX Policy; FX diff posted to OCI",
                "period": "2023-11",
                "scenario": "Actual",
                "batch_id": "HIST-BATCH-001",
            },
            {
                "txn_id": "hist-exc-003",
                "seller_entity": "HCG-DE",
                "buyer_entity": "HCG-FR",
                "rule_code": "IC-004",
                "gap_pct": 0.5,
                "gap_usd": 5_000.0,
                "match_status": "FX Diff",
                "root_cause": "Rounding on EUR amounts due to ERP precision limit",
                "resolution": "Auto-resolved with rounding elimination entry below materiality threshold",
                "period": "2023-10",
                "scenario": "Actual",
                "batch_id": "HIST-BATCH-002",
            },
            {
                "txn_id": "hist-exc-004",
                "seller_entity": "HCG-UK",
                "buyer_entity": "HCG-SG",
                "rule_code": "STK-001",
                "gap_pct": 12.4,
                "gap_usd": 187_000.0,
                "match_status": "Exception",
                "root_cause": "Unrealised margin not reversed — stock transfer from UK to SG in transit at period end",
                "resolution": "In-transit stock identified and adjustment raised; NCI share retained",
                "period": "2023-09",
                "scenario": "Actual",
                "batch_id": "HIST-BATCH-002",
            },
            {
                "txn_id": "hist-exc-005",
                "seller_entity": "SHARED",
                "buyer_entity": "HCG-NL",
                "rule_code": "IC-004",
                "gap_pct": 2.1,
                "gap_usd": 14_300.0,
                "match_status": "Not Matched",
                "root_cause": "Management fee invoice not received by HCG-NL before period close",
                "resolution": "Accrual raised in HCG-NL; IC confirmation obtained retrospectively",
                "period": "2023-08",
                "scenario": "Actual",
                "batch_id": "HIST-BATCH-003",
            },
            {
                "txn_id": "hist-exc-006",
                "seller_entity": "HCG-US",
                "buyer_entity": "HCG-SG",
                "rule_code": "IC-005",
                "gap_pct": 5.7,
                "gap_usd": 63_400.0,
                "match_status": "Exception",
                "root_cause": "Royalty rate applied differently — US used 4.5%, SG used 4.0%",
                "resolution": "Rate corrected to 4.5% per IP licence agreement; SG re-posted",
                "period": "2023-07",
                "scenario": "Actual",
                "batch_id": "HIST-BATCH-003",
            },
            {
                "txn_id": "hist-exc-007",
                "seller_entity": "HCG-DE",
                "buyer_entity": "HCG-NL",
                "rule_code": "INV-001",
                "gap_pct": 0.8,
                "gap_usd": 9_800.0,
                "match_status": "FX Diff",
                "root_cause": "EUR/USD FX translation difference on intercompany loan balance",
                "resolution": "FX difference posted to FCTR; confirmed below materiality threshold",
                "period": "2023-06",
                "scenario": "Actual",
                "batch_id": "HIST-BATCH-004",
            },
            {
                "txn_id": "hist-exc-008",
                "seller_entity": "HCG",
                "buyer_entity": "HCG-UK",
                "rule_code": "EQ-002",
                "gap_pct": 0.0,
                "gap_usd": 0.0,
                "match_status": "Matched",
                "root_cause": "None",
                "resolution": "Clean match — dividend elimination complete",
                "period": "2023-06",
                "scenario": "Actual",
                "batch_id": "HIST-BATCH-004",
            },
            {
                "txn_id": "hist-exc-009",
                "seller_entity": "HCG-AU",
                "buyer_entity": "HCG-US",
                "rule_code": "IC-001",
                "gap_pct": 4.9,
                "gap_usd": 31_200.0,
                "match_status": "Exception",
                "root_cause": "Goods shipped FOB — HCG-AU recognised revenue but HCG-US had not received goods",
                "resolution": "HCG-US posted accrued receipt; goods confirmed received within 3 days",
                "period": "2023-05",
                "scenario": "Actual",
                "batch_id": "HIST-BATCH-005",
            },
            {
                "txn_id": "hist-exc-010",
                "seller_entity": "HCG-UK",
                "buyer_entity": "HCG-FR",
                "rule_code": "AUC-001",
                "gap_pct": 7.3,
                "gap_usd": 245_000.0,
                "match_status": "Exception",
                "root_cause": "Construction contract billed at 60% completion but recipient only recognised 55%",
                "resolution": "Completion certificate obtained; percentage aligned to 60%; AUC adjusted",
                "period": "2023-04",
                "scenario": "Actual",
                "batch_id": "HIST-BATCH-005",
            },
            {
                "txn_id": "hist-exc-011",
                "seller_entity": "HCG-US",
                "buyer_entity": "HCG-DE",
                "rule_code": "IC-003",
                "gap_pct": 9.1,
                "gap_usd": 112_000.0,
                "match_status": "Exception",
                "root_cause": "Inventory margin elimination missed for slow-moving SKUs transferred in Q4",
                "resolution": "Slow-moving inventory identified; margin reversal posted; policy updated",
                "period": "2023-03",
                "scenario": "Actual",
                "batch_id": "HIST-BATCH-006",
            },
            {
                "txn_id": "hist-exc-012",
                "seller_entity": "SHARED",
                "buyer_entity": "HCG-AU",
                "rule_code": "IC-004",
                "gap_pct": 1.3,
                "gap_usd": 8_200.0,
                "match_status": "FX Diff",
                "root_cause": "AUD/GBP rate variance — shared services billed in GBP, AU recorded in AUD at different rate",
                "resolution": "Billing currency standardised to AUD per regional policy",
                "period": "2023-02",
                "scenario": "Actual",
                "batch_id": "HIST-BATCH-006",
            },
            {
                "txn_id": "hist-exc-013",
                "seller_entity": "HCG-DE",
                "buyer_entity": "HCG-SG",
                "rule_code": "IC-005",
                "gap_pct": 3.6,
                "gap_usd": 28_900.0,
                "match_status": "Not Matched",
                "root_cause": "Singapore entity did not accrue royalty — finance team error",
                "resolution": "Accrual posted by HCG-SG CFO; NCI adjustment applied at 75%",
                "period": "2023-01",
                "scenario": "Actual",
                "batch_id": "HIST-BATCH-007",
            },
            {
                "txn_id": "hist-exc-014",
                "seller_entity": "HCG-UK",
                "buyer_entity": "HCG-US",
                "rule_code": "INV-002",
                "gap_pct": 2.2,
                "gap_usd": 17_500.0,
                "match_status": "FX Diff",
                "root_cause": "Interest rate applied at different precision — UK used 4.125%, US used 4.13%",
                "resolution": "Rate standardised to 4.125% per facility agreement schedule",
                "period": "2022-12",
                "scenario": "Actual",
                "batch_id": "HIST-BATCH-007",
            },
            {
                "txn_id": "hist-exc-015",
                "seller_entity": "HCG",
                "buyer_entity": "HCG-SG",
                "rule_code": "DIV-002",
                "gap_pct": 0.0,
                "gap_usd": 0.0,
                "match_status": "Matched",
                "root_cause": "None",
                "resolution": "NCI dividend elimination posted correctly at 25% NCI share",
                "period": "2022-12",
                "scenario": "Actual",
                "batch_id": "HIST-BATCH-008",
            },
            {
                "txn_id": "hist-exc-016",
                "seller_entity": "HCG-FR",
                "buyer_entity": "HCG-NL",
                "rule_code": "IC-002",
                "gap_pct": 6.8,
                "gap_usd": 41_700.0,
                "match_status": "Exception",
                "root_cause": "HCG-NL paid invoice early — balance cleared in books but HCG-FR still showed receivable",
                "resolution": "Confirm payment applied to correct invoice; receivable cleared",
                "period": "2022-11",
                "scenario": "Actual",
                "batch_id": "HIST-BATCH-008",
            },
            {
                "txn_id": "hist-exc-017",
                "seller_entity": "HCG-US",
                "buyer_entity": "HCG-AU",
                "rule_code": "STK-002",
                "gap_pct": 11.2,
                "gap_usd": 93_000.0,
                "match_status": "Exception",
                "root_cause": "Upstream stock margin not adjusted — AU sold goods back to US without margin reversal",
                "resolution": "Upstream margin calculated at parent% only; NCI correction applied",
                "period": "2022-10",
                "scenario": "Actual",
                "batch_id": "HIST-BATCH-009",
            },
            {
                "txn_id": "hist-exc-018",
                "seller_entity": "HCG-DE",
                "buyer_entity": "HCG-FR",
                "rule_code": "AUC-003",
                "gap_pct": 0.9,
                "gap_usd": 7_800.0,
                "match_status": "FX Diff",
                "root_cause": "Depreciation adjusted in EUR but not retranslated at closing rate",
                "resolution": "Depreciation retranslated at EUR/USD closing rate; FCTR posted",
                "period": "2022-09",
                "scenario": "Actual",
                "batch_id": "HIST-BATCH-009",
            },
            {
                "txn_id": "hist-exc-019",
                "seller_entity": "HCG",
                "buyer_entity": "HCG-DE",
                "rule_code": "GW-002",
                "gap_pct": 0.0,
                "gap_usd": 0.0,
                "match_status": "Matched",
                "root_cause": "None",
                "resolution": "Goodwill impairment posted correctly; no group adjustment required",
                "period": "2022-09",
                "scenario": "Actual",
                "batch_id": "HIST-BATCH-010",
            },
            {
                "txn_id": "hist-exc-020",
                "seller_entity": "HCG-UK",
                "buyer_entity": "HCG-NL",
                "rule_code": "IC-001",
                "gap_pct": 15.0,
                "gap_usd": 320_000.0,
                "match_status": "Exception",
                "root_cause": "Large one-off contract not confirmed by HCG-NL controller before close",
                "resolution": "Escalated to Group CFO; confirmation obtained; NCI adjustment at 60%",
                "period": "2022-06",
                "scenario": "Actual",
                "batch_id": "HIST-BATCH-010",
            },
        ]

        seeded = 0
        for exc in HISTORICAL_EXCEPTIONS:
            try:
                self.vectorstore.add_historical_exception(exc)
                seeded += 1
            except Exception as e:
                logger.warning("Failed to seed exception %s: %s", exc.get("txn_id"), e)

        logger.info("Bulk seeded %d historical exceptions", seeded)
