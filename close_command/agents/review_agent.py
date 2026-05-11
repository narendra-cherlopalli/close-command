"""
Review Agent for Close Command — Human-in-the-Loop gate.
Prepares review cards for human decision and loads any existing DB decisions.
This agent does NOT auto-approve anything.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from close_command.database.persistence import CloseCommandDB
from close_command.models.review import ReviewDecision

logger = logging.getLogger(__name__)


class ReviewAgent:
    """HITL gate: builds review cards and loads existing decisions from DB."""

    def __init__(self, db: CloseCommandDB) -> None:
        self.db = db

    # ──────────────────────────────────────────────────────────────────────
    # Main entry point
    # ──────────────────────────────────────────────────────────────────────

    def run(self, state: dict) -> dict:
        """
        Prepare review items and load existing decisions.
        Does NOT auto-approve. Returns state with review_result.
        """
        try:
            matching_result = state.get("matching_result", {})
            elimination_result = state.get("elimination_result", {})
            validation_result = state.get("validation_result", {})

            batch_id = (
                matching_result.get("batch_id")
                or elimination_result.get("batch_id")
                or state.get("batch_id", str(uuid.uuid4()))
            )
            period = (
                matching_result.get("period")
                or elimination_result.get("period")
                or state.get("period", "2024-03")
            )

            logger.info("ReviewAgent preparing review items for batch_id=%s", batch_id)

            # Build review cards
            items_for_review = self.build_review_items(
                matching_result=matching_result,
                elimination_result=elimination_result,
                validation_result=validation_result,
            )

            # Load any existing decisions from DB
            review_result = self.load_review_state(
                batch_id=batch_id,
                items_for_review=items_for_review,
            )

            review_result["batch_id"] = batch_id
            review_result["period"] = period
            review_result["total_items"] = len(items_for_review)

            # Check period close readiness
            readiness = self.check_period_close_readiness(batch_id, items_for_review)
            review_result["close_readiness"] = readiness
            review_result["period_close_ready"] = readiness["ready"]

            state["review_result"] = review_result
            state["human_review_required"] = len(review_result.get("pending_items", [])) > 0

            logger.info(
                "ReviewAgent complete: %d items pending review, close_ready=%s",
                len(review_result.get("pending_items", [])),
                readiness["ready"],
            )
            return state

        except Exception as exc:
            logger.error("ReviewAgent.run failed: %s", exc)
            state.setdefault("errors", []).append(str(exc))
            state["review_result"] = {
                "batch_id": state.get("batch_id", ""),
                "items_for_review": [],
                "pending_items": [],
                "existing_decisions": {},
                "close_readiness": {"ready": False},
                "period_close_ready": False,
                "error": str(exc),
            }
            state["human_review_required"] = True
            return state

    # ──────────────────────────────────────────────────────────────────────
    # Review card builders
    # ──────────────────────────────────────────────────────────────────────

    def build_review_items(
        self,
        matching_result: dict,
        elimination_result: dict,
        validation_result: dict,
    ) -> list[dict]:
        """
        Build review cards for items requiring human review:
        - All Not Matched and Exception pairs
        - Items flagged by validation agent
        - Items with RAG confidence < 0.7
        """
        review_items: list[dict] = []

        try:
            # Not Matched pairs
            not_matched = matching_result.get("not_matched_pairs", [])
            for pair in not_matched:
                card = self._build_review_card(pair, "Not Matched", elimination_result, validation_result)
                review_items.append(card)

            # Exception pairs (always require review — never eliminated)
            exception_pairs = matching_result.get("exception_pairs", [])
            for pair in exception_pairs:
                card = self._build_review_card(pair, "Exception", elimination_result, validation_result)
                card["requires_manual_override"] = True
                review_items.append(card)

            # Items flagged by validation (policy violations, balance issues)
            validation_issues = validation_result.get("issues", [])
            if validation_issues:
                validation_card = {
                    "txn_id": "VALIDATION-AGGREGATE",
                    "match_status": "N/A",
                    "gap_pct": 0.0,
                    "gap_usd": 0.0,
                    "proposed_entries": [],
                    "root_cause": "Validation agent flagged issues requiring review",
                    "validation_notes": validation_issues,
                    "prior_period_comparison": {},
                    "rag_sources": [],
                    "requires_manual_override": False,
                    "card_type": "VALIDATION_FLAG",
                    "recommendation": validation_result.get("recommendation", "BLOCK"),
                    "validation_score": validation_result.get("validation_score", 0.0),
                    "flagged_at": datetime.utcnow().isoformat(),
                }
                review_items.append(validation_card)

            # Journal entries with low RAG confidence — check computation_log
            comp_log = elimination_result.get("computation_log", [])
            for log_entry in comp_log:
                if "Low RAG confidence" in log_entry:
                    low_conf_card = {
                        "txn_id": "RAG-LOW-CONFIDENCE",
                        "match_status": "N/A",
                        "gap_pct": 0.0,
                        "gap_usd": 0.0,
                        "proposed_entries": [],
                        "root_cause": "One or more elimination entries had RAG validation confidence < 0.7",
                        "validation_notes": [log_entry],
                        "prior_period_comparison": {},
                        "rag_sources": [],
                        "requires_manual_override": False,
                        "card_type": "LOW_RAG_CONFIDENCE",
                        "flagged_at": datetime.utcnow().isoformat(),
                    }
                    review_items.append(low_conf_card)
                    break  # One aggregate card is enough

        except Exception as exc:
            logger.error("build_review_items failed: %s", exc)

        return review_items

    def _build_review_card(
        self,
        pair: dict,
        match_status: str,
        elimination_result: dict,
        validation_result: dict,
    ) -> dict:
        """Build a single review card from a match pair."""
        txn_id = str(pair.get("txn_id", str(uuid.uuid4())))

        # Find proposed elimination entries for this txn_id
        all_entries = elimination_result.get("journal_entries", [])
        proposed = [
            e for e in all_entries
            if txn_id in str(e.get("audit_code", "")) or e.get("txn_id", "") == txn_id
        ]

        # Find gate failures for this txn_id
        gate_failures = [
            gf for gf in elimination_result.get("gate_failures", [])
            if gf.get("txn_id") == txn_id
        ]

        # Prior period details from validation
        prior_details = validation_result.get("prior_period_details", {})
        prior_period_comparison = {}
        for detail in prior_details.get("details", []):
            pair_key = f"{pair.get('seller_entity', '')}|{pair.get('buyer_entity', '')}|{pair.get('rule_code', '')}"
            if detail.get("pair", "") == pair_key:
                prior_period_comparison = detail
                break

        return {
            "txn_id": txn_id,
            "match_status": match_status,
            "gap_pct": float(pair.get("gap_pct", 0.0)),
            "gap_usd": float(pair.get("gap_usd", 0.0)),
            "seller_entity": str(pair.get("seller_entity", "")),
            "buyer_entity": str(pair.get("buyer_entity", "")),
            "rule_code": str(pair.get("rule_code", "")),
            "seller_usd": float(pair.get("seller_usd", 0.0)),
            "buyer_usd": float(pair.get("buyer_usd", 0.0)),
            "seller_currency": str(pair.get("seller_currency", "")),
            "buyer_currency": str(pair.get("buyer_currency", "")),
            "proposed_entries": proposed,
            "root_cause": str(pair.get("root_cause", "Not available")),
            "validation_notes": validation_result.get("issues", []),
            "prior_period_comparison": prior_period_comparison,
            "rag_sources": pair.get("rag_sources") or [],
            "gate_failures": gate_failures,
            "requires_manual_override": False,
            "card_type": "MATCH_EXCEPTION",
            "flagged_at": datetime.utcnow().isoformat(),
        }

    def present_review_item(self, txn_id: str, context: dict) -> dict:
        """Return review card dict for display by UI."""
        try:
            return {
                "txn_id": txn_id,
                "context": context,
                "display_title": f"Review Required — Transaction {txn_id}",
                "display_subtitle": f"Match Status: {context.get('match_status', 'Unknown')} | "
                                    f"Gap: {context.get('gap_pct', 0.0):.2%} "
                                    f"(USD {context.get('gap_usd', 0.0):,.2f})",
                "instructions": (
                    "Review the proposed elimination entries and root cause analysis. "
                    "Select Approve, Reject, or Escalate and provide a comment."
                ),
                "available_decisions": ["Approved", "Rejected", "Escalated"],
                "presented_at": datetime.utcnow().isoformat(),
            }
        except Exception as exc:
            logger.warning("present_review_item failed for txn_id=%s: %s", txn_id, exc)
            return {"txn_id": txn_id, "error": str(exc)}

    # ──────────────────────────────────────────────────────────────────────
    # Decision recording
    # ──────────────────────────────────────────────────────────────────────

    def record_decision(
        self,
        txn_id: str,
        decision: str,
        reviewer_name: str,
        reviewer_role: str,
        comment: str,
        batch_id: str,
        period: str,
    ) -> bool:
        """Save ReviewDecision to DB."""
        try:
            gate_status_map = {
                "Approved": "APPROVED",
                "Rejected": "REJECTED",
                "Escalated": "ESCALATED",
            }
            gate_status = gate_status_map.get(decision, "PENDING")

            review_decision = ReviewDecision(
                txn_id=txn_id,
                decision=decision,
                reviewer_name=reviewer_name,
                reviewer_role=reviewer_role,
                timestamp=datetime.utcnow(),
                comment=comment,
                gate_status=gate_status,
                batch_id=batch_id,
                period=period,
            )

            decision_dict = review_decision.model_dump()
            if isinstance(decision_dict.get("timestamp"), datetime):
                decision_dict["timestamp"] = decision_dict["timestamp"].isoformat()

            self.db.save_review_decision(decision_dict)
            logger.info(
                "Decision recorded: txn=%s decision=%s reviewer=%s",
                txn_id, decision, reviewer_name,
            )
            return True

        except Exception as exc:
            logger.error("record_decision failed: %s", exc)
            return False

    # ──────────────────────────────────────────────────────────────────────
    # Period close readiness
    # ──────────────────────────────────────────────────────────────────────

    def check_period_close_readiness(self, batch_id: str, items_for_review: list[dict]) -> dict:
        """Return readiness status for period close."""
        try:
            existing = self.get_existing_decisions(batch_id)

            approved_count = 0
            pending_count = 0
            rejected_count = 0
            escalated_count = 0
            blocking_items: list[str] = []

            for item in items_for_review:
                txn_id = item.get("txn_id", "")
                if txn_id in existing:
                    dec = existing[txn_id]
                    d = dec.get("decision", "")
                    if d == "Approved":
                        approved_count += 1
                    elif d == "Rejected":
                        rejected_count += 1
                        blocking_items.append(txn_id)
                    elif d == "Escalated":
                        escalated_count += 1
                else:
                    pending_count += 1
                    if item.get("requires_manual_override"):
                        blocking_items.append(txn_id)

            ready = (
                pending_count == 0
                and rejected_count == 0
                and escalated_count == 0
            )

            return {
                "ready": ready,
                "approved_count": approved_count,
                "pending_count": pending_count,
                "rejected_count": rejected_count,
                "escalated_count": escalated_count,
                "blocking_items": blocking_items,
            }

        except Exception as exc:
            logger.error("check_period_close_readiness failed: %s", exc)
            return {
                "ready": False,
                "approved_count": 0,
                "pending_count": len(items_for_review),
                "rejected_count": 0,
                "escalated_count": 0,
                "blocking_items": [],
            }

    def get_existing_decisions(self, batch_id: str) -> dict:
        """Load existing review decisions from DB for this batch. Returns txn_id -> decision."""
        try:
            decisions_list = self.db.get_review_decisions(batch_id)
            return {d["txn_id"]: d for d in decisions_list}
        except Exception as exc:
            logger.warning("get_existing_decisions failed: %s", exc)
            return {}

    def load_review_state(self, batch_id: str, items_for_review: list[dict]) -> dict:
        """
        Merge existing DB decisions with pending items.
        Returns review_result dict.
        """
        try:
            existing_decisions = self.get_existing_decisions(batch_id)

            pending_items: list[dict] = []
            decided_items: list[dict] = []

            for item in items_for_review:
                txn_id = item.get("txn_id", "")
                if txn_id in existing_decisions:
                    item_with_decision = dict(item)
                    item_with_decision["existing_decision"] = existing_decisions[txn_id]
                    decided_items.append(item_with_decision)
                else:
                    pending_items.append(item)

            return {
                "items_for_review": items_for_review,
                "pending_items": pending_items,
                "decided_items": decided_items,
                "existing_decisions": existing_decisions,
                "total_items": len(items_for_review),
                "pending_count": len(pending_items),
                "decided_count": len(decided_items),
                "loaded_at": datetime.utcnow().isoformat(),
            }

        except Exception as exc:
            logger.error("load_review_state failed: %s", exc)
            return {
                "items_for_review": items_for_review,
                "pending_items": items_for_review,
                "decided_items": [],
                "existing_decisions": {},
                "total_items": len(items_for_review),
                "pending_count": len(items_for_review),
                "decided_count": 0,
                "loaded_at": datetime.utcnow().isoformat(),
                "error": str(exc),
            }
