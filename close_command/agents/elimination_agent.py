"""
Elimination Agent for Close Command.
Processes matched IC pairs into double-entry journal eliminations.
Exception pairs are NEVER processed — hard rule.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Optional

from close_command.database.persistence import CloseCommandDB
from close_command.models.journal import JournalEntry

try:
    from close_command.rag.retriever import CloseCommandRetriever as _RetrieverClass
except ImportError:
    _RetrieverClass = None  # type: ignore
from close_command.data.entities import (
    ENTITY_REGISTRY,
    are_under_same_parent,
    is_nci_entity,
    get_pcon,
    get_pown,
    get_entity,
)
from close_command.data.rules import ELIMINATION_RULES
from close_command.data.hierarchy import is_direct_parent

logger = logging.getLogger(__name__)


class _NullRetriever:
    """Stub retriever used when chromadb/RAG is unavailable."""

    def retrieve_elimination_precedent(self, rule_code, entity_method, pcon):
        return {"recommendation": "RAG unavailable", "confidence": 0.5, "sources": []}

    def retrieve_root_cause(self, entity_pair, rule_code, gap_pct, gap_usd):
        return {"hypothesis": "RAG unavailable", "confidence": 0.0, "sources": [], "top_cause": "Unknown"}

    def retrieve_prior_period(self, entity_pair, rule_code, current_period):
        return {"prior_amount_usd": 0.0, "deviation_note": "RAG unavailable", "confidence": 0.0, "sources": []}


class EliminationAgent:
    """Generates double-entry journal eliminations for matched IC pairs."""

    def __init__(self, db: CloseCommandDB, retriever=None) -> None:
        self.db = db
        self.retriever = retriever if retriever is not None else _NullRetriever()

    # ──────────────────────────────────────────────────────────────────────
    # Main entry point
    # ──────────────────────────────────────────────────────────────────────

    def run(self, state: dict) -> dict:
        """Run elimination processing. Updates state with elimination_result."""
        try:
            matching_result = state.get("matching_result", {})
            batch_id = matching_result.get("batch_id", state.get("batch_id", str(uuid.uuid4())))
            period = matching_result.get("period", state.get("period", "2024-03"))
            scenario = matching_result.get("scenario", state.get("scenario", "ACTUAL"))

            matched_pairs = matching_result.get("matched_pairs", [])
            not_matched_pairs = matching_result.get("not_matched_pairs", [])
            fx_diff_pairs = matching_result.get("fx_diff_pairs", [])
            # Exception pairs are NEVER passed to elimination
            # exception_pairs = matching_result.get("exception_pairs", [])  — intentionally excluded

            logger.info(
                "EliminationAgent starting: matched=%d not_matched=%d fx_diff=%d batch_id=%s",
                len(matched_pairs), len(not_matched_pairs), len(fx_diff_pairs), batch_id,
            )

            journal_entries, gate_failures, nci_entries = self.process_all_pairs(
                matched_pairs=matched_pairs,
                not_matched_pairs=not_matched_pairs,
                fx_diff_pairs=fx_diff_pairs,
                entity_hierarchy=ENTITY_REGISTRY,
                period=period,
                scenario=scenario,
                batch_id=batch_id,
            )

            # Escalation: too many gate failures
            if len(gate_failures) > 5:
                escalation = {
                    "type": "GATE_FAILURES",
                    "batch_id": batch_id,
                    "gate_failure_count": len(gate_failures),
                    "reason": f"Gate failures ({len(gate_failures)}) exceed threshold of 5",
                    "timestamp": datetime.utcnow().isoformat(),
                    "details": gate_failures[:10],
                }
                state.setdefault("escalations", []).append(escalation)
                logger.warning("Escalation: %d gate failures exceed threshold", len(gate_failures))

            # Serialise JournalEntry objects
            def _entry_to_dict(e: JournalEntry) -> dict:
                d = e.model_dump() if hasattr(e, "model_dump") else dict(e)
                if isinstance(d.get("computed_at"), datetime):
                    d["computed_at"] = d["computed_at"].isoformat()
                return d

            all_entry_dicts = [_entry_to_dict(e) for e in journal_entries + nci_entries]

            # Persist to DB
            try:
                for entry_dict in all_entry_dicts:
                    entry_dict.setdefault("batch_id", batch_id)
                self.db.save_journal_entries(all_entry_dicts)
            except Exception as db_exc:
                logger.warning("Failed to persist journal entries: %s", db_exc)

            elimination_result = {
                "batch_id": batch_id,
                "period": period,
                "scenario": scenario,
                "journal_entries": all_entry_dicts,
                "gate_failures": gate_failures,
                "nci_entries": [_entry_to_dict(e) for e in nci_entries],
                "total_entries": len(all_entry_dicts),
                "gate_failure_count": len(gate_failures),
                "computation_log": [],
            }

            state["elimination_result"] = elimination_result
            logger.info(
                "EliminationAgent complete: journal_entries=%d gate_failures=%d",
                len(all_entry_dicts), len(gate_failures),
            )
            return state

        except Exception as exc:
            logger.error("EliminationAgent.run failed: %s", exc)
            state.setdefault("errors", []).append(str(exc))
            state["elimination_result"] = {
                "batch_id": state.get("batch_id", ""),
                "period": state.get("period", ""),
                "scenario": state.get("scenario", ""),
                "journal_entries": [],
                "gate_failures": [],
                "nci_entries": [],
                "total_entries": 0,
                "gate_failure_count": 0,
                "computation_log": [str(exc)],
            }
            return state

    # ──────────────────────────────────────────────────────────────────────
    # Core processing
    # ──────────────────────────────────────────────────────────────────────

    def process_all_pairs(
        self,
        matched_pairs: list,
        not_matched_pairs: list,
        fx_diff_pairs: list,
        entity_hierarchy: dict,
        period: str,
        scenario: str,
        batch_id: str,
    ) -> tuple[list, list, list]:
        """
        Process Matched, Not Matched, and FX Diff pairs into journal entries.
        Exception pairs are NEVER processed.
        Returns (journal_entries, gate_failures, nci_entries).
        """
        journal_entries: list[JournalEntry] = []
        gate_failures: list[dict] = []
        nci_entries: list[JournalEntry] = []
        computation_log: list[str] = []

        processable = [
            ("Matched", matched_pairs),
            ("Not Matched", not_matched_pairs),
            ("FX Diff", fx_diff_pairs),
        ]

        for status_label, pairs in processable:
            for pair in pairs:
                try:
                    seller = str(pair.get("seller_entity", ""))
                    buyer = str(pair.get("buyer_entity", ""))
                    rule_code = str(pair.get("rule_code", ""))
                    amount_usd = float(pair.get("seller_usd", 0.0))
                    txn_id = str(pair.get("txn_id", str(uuid.uuid4())))

                    # Gate check
                    gate = self.check_gate_conditions(seller, buyer)
                    gate["rule_code"] = rule_code
                    gate_checks = gate.get("checks", {})
                    # Also check rule code
                    if rule_code not in ELIMINATION_RULES:
                        gate["passed"] = False
                        gate["reason"] = gate.get("reason", "") + f" | Rule {rule_code} not in ELIMINATION_RULES"

                    if not gate["passed"]:
                        gate_failures.append({
                            "txn_id": txn_id,
                            "seller": seller,
                            "buyer": buyer,
                            "rule_code": rule_code,
                            "reason": gate["reason"],
                            "status_label": status_label,
                        })
                        logger.debug("Gate failure for txn %s: %s", txn_id, gate["reason"])
                        continue

                    # Compute elimination entries
                    entries = self.compute_elimination(
                        seller_entity=seller,
                        buyer_entity=buyer,
                        amount_usd=amount_usd,
                        rule_code=rule_code,
                        period=period,
                        scenario=scenario,
                    )

                    # NCI split if applicable
                    seller_entity_data = get_entity(seller)
                    buyer_entity_data = get_entity(buyer)
                    pcon = get_pcon(buyer) if buyer_entity_data else 100.0
                    pown = get_pown(buyer) if buyer_entity_data else 100.0

                    if is_nci_entity(buyer) or is_nci_entity(seller):
                        nci_split = self.apply_nci_split(entries, pcon, pown)
                        nci_entries.extend(nci_split)
                    else:
                        # Standard entries — set pcon/pown
                        for e in entries:
                            e.pcon = pcon
                            e.pown = pown

                    # RAG validation
                    for entry in entries:
                        try:
                            rag_val = self.rag_validate_entry(entry, rule_code)
                            if rag_val.get("confidence", 1.0) < 0.7:
                                computation_log.append(
                                    f"Low RAG confidence {rag_val['confidence']:.2f} "
                                    f"for txn={entry.txn_id} rule={rule_code}: {rag_val.get('notes', '')}"
                                )
                        except Exception as rag_exc:
                            logger.debug("RAG validate failed: %s", rag_exc)

                    journal_entries.extend(entries)

                except Exception as pair_exc:
                    logger.warning("Failed processing pair %s: %s", pair.get("txn_id"), pair_exc)
                    gate_failures.append({
                        "txn_id": pair.get("txn_id", "unknown"),
                        "reason": f"Processing error: {pair_exc}",
                    })

        return journal_entries, gate_failures, nci_entries

    def check_gate_conditions(self, seller: str, buyer: str) -> dict:
        """
        Check gate conditions for an entity pair.
        Returns {"passed": bool, "reason": str, "checks": dict}
        """
        checks: dict[str, bool] = {}
        reasons: list[str] = []

        try:
            # Gate 1: Both entities in ENTITY_REGISTRY
            seller_known = seller in ENTITY_REGISTRY
            buyer_known = buyer in ENTITY_REGISTRY
            checks["seller_known"] = seller_known
            checks["buyer_known"] = buyer_known
            if not seller_known:
                reasons.append(f"Seller '{seller}' not in ENTITY_REGISTRY")
            if not buyer_known:
                reasons.append(f"Buyer '{buyer}' not in ENTITY_REGISTRY")

            # Gate 2: Under same consolidating parent
            same_parent = are_under_same_parent(seller, buyer)
            checks["same_parent"] = same_parent
            if not same_parent:
                reasons.append(f"'{seller}' and '{buyer}' do not share a common parent")

            # Gate 3: Seller must not be direct parent of buyer
            seller_is_parent = is_direct_parent(seller, buyer)
            checks["seller_not_direct_parent"] = not seller_is_parent
            if seller_is_parent:
                reasons.append(f"'{seller}' is a direct parent of '{buyer}' — not a peer IC transaction")

            passed = seller_known and buyer_known and same_parent and not seller_is_parent
            reason = "; ".join(reasons) if reasons else "All gate conditions passed"

            return {"passed": passed, "reason": reason, "checks": checks}

        except Exception as exc:
            logger.warning("check_gate_conditions failed for %s/%s: %s", seller, buyer, exc)
            return {
                "passed": False,
                "reason": f"Gate check error: {exc}",
                "checks": checks,
            }

    def compute_elimination(
        self,
        seller_entity: str,
        buyer_entity: str,
        amount_usd: float,
        rule_code: str,
        period: str,
        scenario: str,
    ) -> list[JournalEntry]:
        """
        Generate exactly 2 journal entries (Dr + Cr) for the elimination.
        Amount is always stored as absolute value.
        """
        try:
            rule = ELIMINATION_RULES.get(rule_code)
            if rule is None:
                raise ValueError(f"Rule '{rule_code}' not found in ELIMINATION_RULES")

            dr_account = rule.get("dr_account", "Intercompany Elimination Dr")
            cr_account = rule.get("cr_account", "Intercompany Elimination Cr")
            audit_code = f"AUD-{rule_code}-{seller_entity}-{buyer_entity}"
            abs_amount = abs(amount_usd)

            entity_data = get_entity(seller_entity) or {}
            entity_method = entity_data.get("entity_method", "GLOBAL")
            pcon = get_pcon(seller_entity)
            pown = get_pown(seller_entity)

            dr_entry = JournalEntry(
                txn_id=f"{audit_code}-DR-{str(uuid.uuid4())[:8]}",
                seller=seller_entity,
                buyer=buyer_entity,
                rule_code=rule_code,
                account=dr_account,
                dr_cr="Dr",
                amount=abs_amount,
                amount_usd=abs_amount,
                audit_code=audit_code,
                period=period,
                scenario=scenario,
                entity_method=entity_method,
                pcon=pcon,
                pown=pown,
                gate_status="PENDING",
                nci_applicable=rule.get("nci_applicable", False),
            )

            cr_entry = JournalEntry(
                txn_id=f"{audit_code}-CR-{str(uuid.uuid4())[:8]}",
                seller=seller_entity,
                buyer=buyer_entity,
                rule_code=rule_code,
                account=cr_account,
                dr_cr="Cr",
                amount=abs_amount,
                amount_usd=abs_amount,
                audit_code=audit_code,
                period=period,
                scenario=scenario,
                entity_method=entity_method,
                pcon=pcon,
                pown=pown,
                gate_status="PENDING",
                nci_applicable=rule.get("nci_applicable", False),
            )

            return [dr_entry, cr_entry]

        except Exception as exc:
            logger.error("compute_elimination failed for %s/%s rule=%s: %s", seller_entity, buyer_entity, rule_code, exc)
            raise

    def apply_nci_split(
        self, entries: list[JournalEntry], pcon: float, pown: float
    ) -> list[JournalEntry]:
        """
        Split entries into group share (pcon%) and NCI share (100-pcon%).
        Returns both group and NCI entries with nci_applicable=True on NCI entries.
        """
        split_entries: list[JournalEntry] = []
        try:
            nci_pct = (100.0 - pcon) / 100.0
            group_pct = pcon / 100.0

            for entry in entries:
                # Group share entry
                group_amount = abs(entry.amount) * group_pct
                group_entry = JournalEntry(
                    txn_id=f"{entry.txn_id}-GRP",
                    seller=entry.seller,
                    buyer=entry.buyer,
                    rule_code=entry.rule_code,
                    account=entry.account,
                    dr_cr=entry.dr_cr,
                    amount=round(group_amount, 2),
                    amount_usd=round(group_amount, 2),
                    audit_code=f"{entry.audit_code}-GRP",
                    period=entry.period,
                    scenario=entry.scenario,
                    entity_method=entry.entity_method,
                    pcon=pcon,
                    pown=pown,
                    gate_status=entry.gate_status,
                    nci_applicable=False,
                )
                split_entries.append(group_entry)

                # NCI share entry (if NCI pct > 0)
                if nci_pct > 0:
                    nci_amount = abs(entry.amount) * nci_pct
                    nci_entry = JournalEntry(
                        txn_id=f"{entry.txn_id}-NCI",
                        seller=entry.seller,
                        buyer=entry.buyer,
                        rule_code=entry.rule_code,
                        account=f"NCI Share — {entry.account}",
                        dr_cr=entry.dr_cr,
                        amount=round(nci_amount, 2),
                        amount_usd=round(nci_amount, 2),
                        audit_code=f"{entry.audit_code}-NCI",
                        period=entry.period,
                        scenario=entry.scenario,
                        entity_method=entry.entity_method,
                        pcon=pcon,
                        pown=pown,
                        gate_status=entry.gate_status,
                        nci_applicable=True,
                    )
                    split_entries.append(nci_entry)

        except Exception as exc:
            logger.error("apply_nci_split failed: %s", exc)
            # Fall back to returning original entries unmodified
            return entries

        return split_entries

    def rag_validate_entry(self, entry: JournalEntry, rule_code: str) -> dict:
        """
        Use RAG to validate a journal entry against precedents.
        Returns {"valid": bool, "confidence": float, "notes": str}.
        """
        try:
            entity_method = entry.entity_method or "GLOBAL"
            pcon = entry.pcon or 100.0
            result = self.retriever.retrieve_elimination_precedent(
                rule_code=rule_code,
                entity_method=entity_method,
                pcon=pcon,
            )
            confidence = result.get("confidence", 0.5)
            recommendation = result.get("recommendation", "No recommendation available")
            valid = confidence >= 0.5

            return {
                "valid": valid,
                "confidence": confidence,
                "notes": recommendation,
            }

        except Exception as exc:
            logger.debug("rag_validate_entry failed: %s", exc)
            return {
                "valid": True,  # Don't block on RAG failure
                "confidence": 0.5,
                "notes": f"RAG validation unavailable: {exc}",
            }
