"""
Validation Agent for Close Command.
Checks journal balance, audit references, continuation controls,
prior-period comparison, and policy compliance.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from close_command.database.persistence import CloseCommandDB
from close_command.models.validation import ValidationResult, BalanceResult, ContinuationResult

try:
    from close_command.rag.retriever import CloseCommandRetriever as _RetrieverClass
except ImportError:
    _RetrieverClass = None  # type: ignore
from close_command.data.rules import ELIMINATION_RULES

logger = logging.getLogger(__name__)


class _NullRetriever:
    """Stub retriever used when chromadb/RAG is unavailable."""

    def retrieve_prior_period(self, entity_pair, rule_code, current_period):
        return {"prior_amount_usd": 0.0, "deviation_note": "RAG unavailable", "confidence": 0.0, "sources": []}

    def retrieve_policy(self, rule_code, entity_scope):
        return {"policy_summary": "RAG unavailable", "confidence": 0.0, "sources": []}

    def retrieve_elimination_precedent(self, rule_code, entity_method, pcon):
        return {"recommendation": "RAG unavailable", "confidence": 0.5, "sources": []}


class ValidationAgent:
    """Validates journal entries and produces a scored recommendation."""

    def __init__(self, db: CloseCommandDB, retriever=None) -> None:
        self.db = db
        self.retriever = retriever if retriever is not None else _NullRetriever()

    # ──────────────────────────────────────────────────────────────────────
    # Main entry point
    # ──────────────────────────────────────────────────────────────────────

    def run(self, state: dict) -> dict:
        """Validate journal entries. Updates state with validation_result."""
        try:
            elimination_result = state.get("elimination_result", {})
            batch_id = elimination_result.get("batch_id", state.get("batch_id", str(uuid.uuid4())))
            period = elimination_result.get("period", state.get("period", "2024-03"))
            scenario = elimination_result.get("scenario", state.get("scenario", "ACTUAL"))
            journal_entries = elimination_result.get("journal_entries", [])

            logger.info(
                "ValidationAgent starting: %d entries batch_id=%s", len(journal_entries), batch_id
            )

            issues: list[str] = []

            # 1. Journal balance check
            balance_result = self.check_journal_balance(journal_entries)
            balance_ok = balance_result.is_balanced
            if not balance_ok:
                issues.append(
                    f"Journal out of balance: Dr={balance_result.total_debits:.2f} "
                    f"Cr={balance_result.total_credits:.2f} diff={balance_result.difference:.2f}"
                )
                # Hard block — escalate immediately
                escalation = {
                    "type": "JOURNAL_IMBALANCE",
                    "batch_id": batch_id,
                    "dr_total": balance_result.total_debits,
                    "cr_total": balance_result.total_credits,
                    "difference": balance_result.difference,
                    "reason": "Journal entries are out of balance — hard block required",
                    "timestamp": datetime.utcnow().isoformat(),
                }
                state.setdefault("escalations", []).append(escalation)
                logger.error("Hard block: journal out of balance diff=%.4f", balance_result.difference)

            # 2. Audit reference check
            audit_check = self.verify_audit_references(journal_entries)
            if not audit_check["passed"]:
                issues.append(f"Audit references missing on {audit_check['missing_count']} entries")

            # 3. Continuation control
            continuation_result = self.run_continuation_control(batch_id, period)
            continuation_ok = continuation_result.passed
            if not continuation_ok:
                for cont_issue in continuation_result.issues:
                    issues.append(f"Continuation control: {cont_issue}")
                escalation = {
                    "type": "CONTINUATION_CONTROL",
                    "batch_id": batch_id,
                    "issues": continuation_result.issues,
                    "reason": "Continuation control check failed",
                    "timestamp": datetime.utcnow().isoformat(),
                }
                state.setdefault("escalations", []).append(escalation)
                logger.warning("Continuation control failed: %s", continuation_result.issues)

            # 4. Prior period comparison
            prior_period_result = self.rag_compare_prior_period(journal_entries, period)
            deviation_pct = prior_period_result.get("deviation_pct", 0.0)
            flagged_pairs = prior_period_result.get("flagged_pairs", [])
            if deviation_pct > 10.0:
                issues.append(
                    f"Prior period deviation {deviation_pct:.1f}% exceeds 10% threshold. "
                    f"Flagged pairs: {flagged_pairs}"
                )
                escalation = {
                    "type": "PRIOR_PERIOD_DEVIATION",
                    "batch_id": batch_id,
                    "deviation_pct": deviation_pct,
                    "flagged_pairs": flagged_pairs,
                    "reason": f"Prior period deviation {deviation_pct:.1f}% exceeds threshold",
                    "timestamp": datetime.utcnow().isoformat(),
                }
                state.setdefault("escalations", []).append(escalation)

            # 5. Policy compliance
            policy_result = self.check_policy_compliance(journal_entries)
            policy_ok = policy_result["passed"]
            if not policy_ok:
                for violation in policy_result.get("violations", []):
                    issues.append(f"Policy violation: {violation}")

            # 6. Validation score
            score = self.compute_validation_score(
                balance_ok=balance_ok,
                continuation_ok=continuation_ok,
                policy_ok=policy_ok,
                deviation_pct=deviation_pct,
            )

            # 7. Recommendation
            recommendation = self.determine_recommendation(score, issues)

            # Build ValidationResult
            validation_result_model = ValidationResult(
                batch_id=batch_id,
                balance_check=balance_ok,
                continuation_check=continuation_ok,
                policy_check=policy_ok,
                prior_period_deviation=deviation_pct,
                validation_score=score,
                recommendation=recommendation,
                issues=issues,
                balance_result=balance_result.model_dump() if hasattr(balance_result, "model_dump") else dict(balance_result),
                continuation_result=continuation_result.model_dump() if hasattr(continuation_result, "model_dump") else dict(continuation_result),
            )

            validation_result = validation_result_model.model_dump()
            validation_result["period"] = period
            validation_result["scenario"] = scenario
            validation_result["prior_period_details"] = prior_period_result
            validation_result["policy_details"] = policy_result
            validation_result["audit_check"] = audit_check

            state["validation_result"] = validation_result

            # Persist
            try:
                self.db.save_validation_result(validation_result)
            except Exception as db_exc:
                logger.warning("Failed to persist validation result: %s", db_exc)

            logger.info(
                "ValidationAgent complete: score=%.2f recommendation=%s issues=%d",
                score, recommendation, len(issues),
            )
            return state

        except Exception as exc:
            logger.error("ValidationAgent.run failed: %s", exc)
            state.setdefault("errors", []).append(str(exc))
            state["validation_result"] = {
                "batch_id": state.get("batch_id", ""),
                "balance_check": False,
                "continuation_check": False,
                "policy_check": False,
                "prior_period_deviation": 0.0,
                "validation_score": 0.0,
                "recommendation": "BLOCK",
                "issues": [str(exc)],
            }
            return state

    # ──────────────────────────────────────────────────────────────────────
    # Validation methods
    # ──────────────────────────────────────────────────────────────────────

    def check_journal_balance(self, entries: list[dict]) -> BalanceResult:
        """Sum all Dr and Cr entries. Balanced if |dr_total - cr_total| < 0.01."""
        try:
            total_debits = 0.0
            total_credits = 0.0

            for entry in entries:
                dr_cr = str(entry.get("dr_cr", "")).strip()
                amount = float(entry.get("amount_usd", entry.get("amount", 0)) or 0)
                abs_amount = abs(amount)
                if dr_cr == "Dr":
                    total_debits += abs_amount
                elif dr_cr == "Cr":
                    total_credits += abs_amount

            difference = abs(total_debits - total_credits)
            is_balanced = difference < 0.01

            return BalanceResult(
                is_balanced=is_balanced,
                total_debits=round(total_debits, 2),
                total_credits=round(total_credits, 2),
                difference=round(difference, 4),
                entries_checked=len(entries),
            )

        except Exception as exc:
            logger.error("check_journal_balance failed: %s", exc)
            return BalanceResult(
                is_balanced=False,
                total_debits=0.0,
                total_credits=0.0,
                difference=9999.0,
                entries_checked=0,
            )

    def verify_audit_references(self, entries: list[dict]) -> dict:
        """Check every entry has a non-empty audit_code."""
        try:
            missing_count = 0
            for entry in entries:
                audit_code = str(entry.get("audit_code", "")).strip()
                if not audit_code:
                    missing_count += 1

            return {
                "passed": missing_count == 0,
                "missing_count": missing_count,
                "entries_checked": len(entries),
            }
        except Exception as exc:
            logger.warning("verify_audit_references failed: %s", exc)
            return {"passed": False, "missing_count": -1, "entries_checked": 0}

    def run_continuation_control(self, batch_id: str, period: str) -> ContinuationResult:
        """
        Check continuation control conditions.
        - structure_changed: True if entity list differs from last batch
        - methods_changed: True if any entity method changed
        - fx_rates_current: Always True (rates loaded fresh each run)
        """
        issues: list[str] = []
        structure_changed = False
        methods_changed = False
        fx_rates_current = True

        try:
            # Look up previous batch to compare
            try:
                prev_entries = self._get_previous_period_entries(period)
                if prev_entries:
                    # Check if entity set changed
                    current_entities = set()
                    try:
                        from close_command.data.entities import VALID_ENTITY_CODES
                        current_entities = VALID_ENTITY_CODES
                    except Exception:
                        pass

                    prev_entities = set(
                        e.get("seller", "") for e in prev_entries
                    ) | set(e.get("buyer", "") for e in prev_entries)
                    prev_entities.discard("")

                    if current_entities and prev_entities and current_entities != prev_entities:
                        new_entities = current_entities - prev_entities
                        removed_entities = prev_entities - current_entities
                        if new_entities or removed_entities:
                            structure_changed = True
                            issues.append(
                                f"Entity structure changed: new={new_entities}, removed={removed_entities}"
                            )

                    # Check entity methods
                    prev_methods = {e.get("seller", ""): e.get("entity_method", "GLOBAL") for e in prev_entries}
                    try:
                        from close_command.data.entities import ENTITY_REGISTRY
                        for code, data in ENTITY_REGISTRY.items():
                            current_method = data.get("entity_method", "GLOBAL")
                            prev_method = prev_methods.get(code)
                            if prev_method and prev_method != current_method:
                                methods_changed = True
                                issues.append(
                                    f"Entity method changed for {code}: {prev_method} -> {current_method}"
                                )
                    except Exception:
                        pass

            except Exception as lookup_exc:
                logger.debug("Could not retrieve previous period for continuation check: %s", lookup_exc)
                # First run — no issues
                structure_changed = False
                methods_changed = False

            passed = not (structure_changed or methods_changed)
            if not passed and not issues:
                issues.append("Continuation control check failed — review entity or method changes")

            return ContinuationResult(
                passed=passed,
                structure_changed=structure_changed,
                methods_changed=methods_changed,
                fx_rates_current=fx_rates_current,
                issues=issues,
            )

        except Exception as exc:
            logger.error("run_continuation_control failed: %s", exc)
            return ContinuationResult(
                passed=False,
                structure_changed=False,
                methods_changed=False,
                fx_rates_current=True,
                issues=[f"Continuation control error: {exc}"],
            )

    def rag_compare_prior_period(self, entries: list[dict], period: str) -> dict:
        """
        For each unique entity_pair + rule_code, query period_journals collection.
        Compute average deviation% from prior period.
        """
        try:
            if not entries:
                return {"deviation_pct": 0.0, "flagged_pairs": [], "details": []}

            # Group entries by entity_pair + rule_code
            pair_groups: dict[str, list[dict]] = {}
            for entry in entries:
                seller = str(entry.get("seller", ""))
                buyer = str(entry.get("buyer", ""))
                rule = str(entry.get("rule_code", ""))
                key = f"{seller}|{buyer}|{rule}"
                if key not in pair_groups:
                    pair_groups[key] = []
                pair_groups[key].append(entry)

            details: list[dict] = []
            flagged_pairs: list[str] = []
            total_deviation = 0.0
            n_pairs = 0

            for pair_key, pair_entries in pair_groups.items():
                try:
                    parts = pair_key.split("|")
                    entity_pair = f"{parts[0]} {parts[1]}" if len(parts) >= 2 else pair_key
                    rule_code = parts[2] if len(parts) >= 3 else ""

                    # Query RAG for prior period
                    prior_result = self.retriever.retrieve_prior_period(
                        entity_pair=entity_pair,
                        rule_code=rule_code,
                        current_period=period,
                    )

                    prior_amount = prior_result.get("prior_amount_usd", 0.0)
                    current_amount = sum(
                        abs(float(e.get("amount_usd", e.get("amount", 0)) or 0))
                        for e in pair_entries
                    )

                    if prior_amount > 0:
                        deviation_pct = abs(current_amount - prior_amount) / prior_amount * 100
                    else:
                        deviation_pct = 0.0

                    total_deviation += deviation_pct
                    n_pairs += 1

                    detail = {
                        "pair": pair_key,
                        "current_amount_usd": round(current_amount, 2),
                        "prior_amount_usd": round(prior_amount, 2),
                        "deviation_pct": round(deviation_pct, 2),
                    }
                    details.append(detail)

                    if deviation_pct > 10.0:
                        flagged_pairs.append(pair_key)

                except Exception as pair_exc:
                    logger.debug("Prior period comparison failed for pair %s: %s", pair_key, pair_exc)

            avg_deviation = total_deviation / n_pairs if n_pairs > 0 else 0.0

            return {
                "deviation_pct": round(avg_deviation, 2),
                "flagged_pairs": flagged_pairs,
                "details": details,
            }

        except Exception as exc:
            logger.warning("rag_compare_prior_period failed: %s", exc)
            return {"deviation_pct": 0.0, "flagged_pairs": [], "details": []}

    def check_policy_compliance(self, entries: list[dict]) -> dict:
        """
        Verify each entry's rule_code is in ELIMINATION_RULES.
        Verify pcon values are within valid range (0-100).
        """
        try:
            violations: list[str] = []

            for entry in entries:
                txn_id = str(entry.get("txn_id", ""))
                rule_code = str(entry.get("rule_code", ""))
                pcon = entry.get("pcon", None)

                if rule_code and rule_code not in ELIMINATION_RULES:
                    violations.append(f"txn={txn_id}: Unknown rule_code '{rule_code}'")

                if pcon is not None:
                    try:
                        pcon_val = float(pcon)
                        if not (0.0 <= pcon_val <= 100.0):
                            violations.append(
                                f"txn={txn_id}: pcon={pcon_val} is outside valid range [0, 100]"
                            )
                    except (TypeError, ValueError):
                        violations.append(f"txn={txn_id}: pcon '{pcon}' is not a valid number")

            return {
                "passed": len(violations) == 0,
                "violations": violations,
                "entries_checked": len(entries),
            }

        except Exception as exc:
            logger.warning("check_policy_compliance failed: %s", exc)
            return {"passed": False, "violations": [str(exc)], "entries_checked": 0}

    def compute_validation_score(
        self,
        balance_ok: bool,
        continuation_ok: bool,
        policy_ok: bool,
        deviation_pct: float,
    ) -> float:
        """
        Weighted score:
        balance 40%, continuation 30%, policy 20%, deviation 10%
        """
        try:
            balance_score = 1.0 if balance_ok else 0.0
            continuation_score = 1.0 if continuation_ok else 0.0
            policy_score = 1.0 if policy_ok else 0.0

            # Deviation score: 100% if 0%, degrading linearly to 0% at 50%+ deviation
            dev_score = max(0.0, 1.0 - (deviation_pct / 50.0))

            weighted = (
                balance_score * 0.40
                + continuation_score * 0.30
                + policy_score * 0.20
                + dev_score * 0.10
            )

            return round(weighted, 4)

        except Exception as exc:
            logger.warning("compute_validation_score failed: %s", exc)
            return 0.0

    def determine_recommendation(self, score: float, issues: list) -> str:
        """
        score >= 0.85 and no critical issues → APPROVE
        score >= 0.65 → REVIEW
        else → BLOCK
        """
        try:
            critical_issues = [
                i for i in issues
                if any(keyword in i.lower() for keyword in ["balance", "imbalance", "block"])
            ]

            if score >= 0.85 and not critical_issues:
                return "APPROVE"
            elif score >= 0.65:
                return "REVIEW"
            else:
                return "BLOCK"

        except Exception as exc:
            logger.warning("determine_recommendation failed: %s", exc)
            return "BLOCK"

    # ──────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ──────────────────────────────────────────────────────────────────────

    def _get_previous_period_entries(self, period: str) -> list[dict]:
        """Retrieve journal entries from the most recent previous period."""
        try:
            # Parse period to find the prior period
            if "-" in period:
                year, month = period.split("-")
                month_num = int(month)
                year_num = int(year)
            else:
                year_num = int(period[:4])
                month_num = int(period[4:])

            if month_num == 1:
                prior_month = 12
                prior_year = year_num - 1
            else:
                prior_month = month_num - 1
                prior_year = year_num

            prior_period = f"{prior_year}-{prior_month:02d}"

            with self.db._connect() as conn:
                rows = conn.execute(
                    "SELECT * FROM journal_entries WHERE period = ? LIMIT 100",
                    (prior_period,),
                ).fetchall()
                return [dict(r) for r in rows]

        except Exception as exc:
            logger.debug("_get_previous_period_entries failed: %s", exc)
            return []
