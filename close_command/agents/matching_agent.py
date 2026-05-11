"""
Matching Agent for Close Command.
Performs bilateral IC matching, FX conversion, and root-cause analysis.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Optional

import pandas as pd

from close_command.database.persistence import CloseCommandDB
from close_command.models.matching import MatchResult, MatchSummary

try:
    from close_command.rag.retriever import CloseCommandRetriever as _RetrieverClass
except ImportError:
    _RetrieverClass = None  # type: ignore
from close_command.data.fx_rates import convert_to_usd, FX_RATES, is_valid_currency

logger = logging.getLogger(__name__)


class _NullRetriever:
    """Stub retriever used when chromadb/RAG is unavailable."""

    def retrieve_root_cause(self, entity_pair, rule_code, gap_pct, gap_usd):
        return {"hypothesis": "RAG unavailable — root cause analysis skipped", "confidence": 0.0, "sources": [], "top_cause": "Unknown"}

    def retrieve_elimination_precedent(self, rule_code, entity_method, pcon):
        return {"recommendation": "RAG unavailable", "confidence": 0.0, "sources": []}

    def retrieve_prior_period(self, entity_pair, rule_code, current_period):
        return {"prior_amount_usd": 0.0, "deviation_note": "RAG unavailable", "confidence": 0.0, "sources": []}

    def retrieve_policy(self, rule_code, entity_scope):
        return {"policy_summary": "RAG unavailable", "confidence": 0.0, "sources": []}


class MatchingAgent:
    """Bilateral IC matching with FX conversion and RAG root-cause analysis."""

    def __init__(self, db: CloseCommandDB, retriever=None) -> None:
        self.db = db
        self.retriever = retriever if retriever is not None else _NullRetriever()

    # ──────────────────────────────────────────────────────────────────────
    # Main entry point
    # ──────────────────────────────────────────────────────────────────────

    def run(self, state: dict) -> dict:
        """Run bilateral matching on ingested data. Updates state with matching_result."""
        try:
            ingestion_result = state.get("ingestion_result", {})
            clean_data = ingestion_result.get("clean_data")
            batch_id = ingestion_result.get("batch_id", state.get("batch_id", str(uuid.uuid4())))
            period = ingestion_result.get("period", state.get("period", "2024-03"))
            scenario = ingestion_result.get("scenario", state.get("scenario", "ACTUAL"))

            # clean_data may be a DataFrame or a list of dicts (after checkpoint serialization)
            if clean_data is None:
                logger.warning("No clean data for matching — returning empty result")
                state["matching_result"] = self._empty_matching_result(batch_id, period, scenario)
                return state

            if isinstance(clean_data, pd.DataFrame):
                df = clean_data
            elif isinstance(clean_data, list):
                df = pd.DataFrame(clean_data) if clean_data else pd.DataFrame()
            else:
                df = pd.DataFrame()

            if df.empty:
                logger.warning("No clean data for matching — returning empty result")
                state["matching_result"] = self._empty_matching_result(batch_id, period, scenario)
                return state

            logger.info("MatchingAgent starting: %d rows, batch_id=%s", len(df), batch_id)

            # Check for missing FX rates
            missing_fx: list[str] = []
            for ccy_col in ["seller_currency", "buyer_currency"]:
                if ccy_col in df.columns:
                    for ccy in df[ccy_col].dropna().astype(str).str.upper().unique():
                        if not is_valid_currency(ccy):
                            missing_fx.append(ccy)

            if missing_fx:
                escalation = {
                    "type": "MISSING_FX_RATE",
                    "batch_id": batch_id,
                    "currencies": missing_fx,
                    "reason": f"FX rates missing for currencies: {missing_fx}. Matching blocked.",
                    "timestamp": datetime.utcnow().isoformat(),
                }
                state.setdefault("escalations", []).append(escalation)
                logger.error("Missing FX rates — blocking matching: %s", missing_fx)
                state["matching_result"] = self._empty_matching_result(batch_id, period, scenario)
                return state

            # Run matching
            matched, not_matched, fx_diff, exceptions = self.match_all_pairs(
                df, FX_RATES, threshold=0.005
            )

            all_results = matched + not_matched + fx_diff + exceptions
            summary = self.build_match_summary(batch_id, all_results, period, scenario)

            # Escalation: exception_pct >= 20%
            if summary.exception_pct >= 0.20:
                escalation = {
                    "type": "HIGH_EXCEPTION_RATE",
                    "batch_id": batch_id,
                    "exception_pct": summary.exception_pct,
                    "exception_count": summary.exception_count,
                    "reason": f"Exception rate {summary.exception_pct:.1%} exceeds 20% threshold",
                    "timestamp": datetime.utcnow().isoformat(),
                }
                state.setdefault("escalations", []).append(escalation)
                logger.warning("Escalation: exception_pct=%.1%", summary.exception_pct)

            # Convert MatchResult objects to dicts for state
            def _to_dict(r: MatchResult) -> dict:
                return r.model_dump() if hasattr(r, "model_dump") else dict(r)

            matching_result = {
                "batch_id": batch_id,
                "period": period,
                "scenario": scenario,
                "matched_pairs": [_to_dict(r) for r in matched],
                "not_matched_pairs": [_to_dict(r) for r in not_matched],
                "fx_diff_pairs": [_to_dict(r) for r in fx_diff],
                "exception_pairs": [_to_dict(r) for r in exceptions],
                "all_results": [_to_dict(r) for r in all_results],
                "summary": summary.model_dump() if hasattr(summary, "model_dump") else dict(summary),
            }

            state["matching_result"] = matching_result

            # Persist match results
            try:
                match_dicts = []
                for r in all_results:
                    d = _to_dict(r)
                    if isinstance(d.get("created_at"), datetime):
                        d["created_at"] = d["created_at"].isoformat()
                    match_dicts.append(d)
                self.db.save_match_results(match_dicts)
            except Exception as db_exc:
                logger.warning("Failed to persist match results: %s", db_exc)

            logger.info(
                "MatchingAgent complete: matched=%d not_matched=%d fx_diff=%d exceptions=%d",
                len(matched), len(not_matched), len(fx_diff), len(exceptions),
            )
            return state

        except Exception as exc:
            logger.error("MatchingAgent.run failed: %s", exc)
            state.setdefault("errors", []).append(str(exc))
            state["matching_result"] = self._empty_matching_result(
                state.get("batch_id", ""), state.get("period", ""), state.get("scenario", "")
            )
            return state

    # ──────────────────────────────────────────────────────────────────────
    # Core matching logic
    # ──────────────────────────────────────────────────────────────────────

    def match_all_pairs(
        self, df: pd.DataFrame, fx_rates: dict, threshold: float = 0.005
    ) -> tuple[list, list, list, list]:
        """
        Match all bilateral pairs.
        Returns (matched_pairs, not_matched_pairs, fx_diff_pairs, exception_pairs).
        """
        matched: list[MatchResult] = []
        not_matched: list[MatchResult] = []
        fx_diff: list[MatchResult] = []
        exceptions: list[MatchResult] = []

        try:
            groups = self._group_by_entity_pair(df)

            for group_key, group_df in groups.items():
                seller_entity, buyer_entity, rule_code = group_key

                # Find seller rows (where entity is seller_entity)
                seller_rows = group_df[group_df["seller_entity"] == seller_entity]
                buyer_rows = group_df[group_df["buyer_entity"] == buyer_entity]

                # If no natural split, treat all rows as needing bilateral matching
                if seller_rows.empty or buyer_rows.empty:
                    # Process the rows that exist
                    for _, row in group_df.iterrows():
                        try:
                            result = self._process_single_row(row, seller_entity, buyer_entity, rule_code, fx_rates)
                            self._classify_result(result, matched, not_matched, fx_diff, exceptions)
                        except Exception as row_exc:
                            logger.warning("Failed to process row %s: %s", row.get("txn_id"), row_exc)
                else:
                    # Pair up seller and buyer rows
                    n_pairs = max(len(seller_rows), len(buyer_rows))
                    seller_list = seller_rows.to_dict(orient="records")
                    buyer_list = buyer_rows.to_dict(orient="records")

                    for i in range(n_pairs):
                        seller_row = seller_list[i % len(seller_list)]
                        buyer_row = buyer_list[i % len(buyer_list)]
                        try:
                            result = self.match_bilateral_pair(seller_row, buyer_row)
                            self._classify_result(result, matched, not_matched, fx_diff, exceptions)
                        except Exception as pair_exc:
                            logger.warning(
                                "Failed to match pair %s/%s: %s",
                                seller_row.get("txn_id"), buyer_row.get("txn_id"), pair_exc,
                            )

        except Exception as exc:
            logger.error("match_all_pairs failed: %s", exc)

        return matched, not_matched, fx_diff, exceptions

    def match_bilateral_pair(self, seller_row: dict, buyer_row: dict) -> MatchResult:
        """
        Match one seller row against one buyer row.
        - Cross-currency → FX Diff (never Exception)
        - gap_pct < 0.005 → Matched
        - 0.005 <= gap_pct < 0.02 → Not Matched
        - gap_pct >= 0.02 AND same currency → Exception
        """
        try:
            seller_entity = str(seller_row.get("seller_entity", seller_row.get("entity", "")))
            buyer_entity = str(buyer_row.get("buyer_entity", buyer_row.get("entity", "")))
            rule_code = str(seller_row.get("rule_code", ""))
            account = str(seller_row.get("account", ""))
            period = str(seller_row.get("period", ""))
            scenario = str(seller_row.get("scenario", ""))
            batch_id = str(seller_row.get("batch_id", ""))
            txn_id = str(seller_row.get("txn_id", str(uuid.uuid4())))

            seller_amount = float(seller_row.get("seller_amount", 0) or 0)
            buyer_amount = float(buyer_row.get("buyer_amount", 0) or 0)
            seller_currency = str(seller_row.get("seller_currency", "USD")).upper()
            buyer_currency = str(buyer_row.get("buyer_currency", "USD")).upper()

            # FX conversion
            seller_usd = convert_to_usd(abs(seller_amount), seller_currency)
            buyer_usd = convert_to_usd(abs(buyer_amount), buyer_currency)

            gap_usd = abs(seller_usd - buyer_usd)
            max_usd = max(seller_usd, buyer_usd)
            gap_pct = (gap_usd / max_usd) if max_usd > 0 else 0.0

            # Classification
            is_cross_currency = (seller_currency != buyer_currency)
            if is_cross_currency:
                match_status = "FX Diff"
            elif gap_pct < 0.005:
                match_status = "Matched"
            elif gap_pct < 0.02:
                match_status = "Not Matched"
            else:
                match_status = "Exception"

            # Generate root cause for non-matched
            root_cause: Optional[str] = None
            rag_sources: Optional[list] = None

            if match_status in ("Not Matched", "Exception", "FX Diff"):
                try:
                    entity_pair = f"{seller_entity} vs {buyer_entity}"
                    rc_result = self.generate_root_cause(
                        MatchResult(
                            txn_id=txn_id,
                            seller_entity=seller_entity,
                            buyer_entity=buyer_entity,
                            rule_code=rule_code,
                            account=account,
                            seller_amount=abs(seller_amount),
                            buyer_amount=abs(buyer_amount),
                            seller_currency=seller_currency,
                            buyer_currency=buyer_currency,
                            seller_usd=seller_usd,
                            buyer_usd=buyer_usd,
                            gap_usd=gap_usd,
                            gap_pct=gap_pct,
                            match_status=match_status,
                            period=period,
                            scenario=scenario,
                            batch_id=batch_id,
                        )
                    )
                    root_cause = rc_result
                    rag_sources = []
                except Exception as rc_exc:
                    logger.warning("Root cause generation failed: %s", rc_exc)
                    root_cause = f"Root cause unavailable: {rc_exc}"

            return MatchResult(
                txn_id=txn_id,
                seller_entity=seller_entity,
                buyer_entity=buyer_entity,
                rule_code=rule_code,
                account=account,
                seller_amount=abs(seller_amount),
                buyer_amount=abs(buyer_amount),
                seller_currency=seller_currency,
                buyer_currency=buyer_currency,
                seller_usd=seller_usd,
                buyer_usd=buyer_usd,
                gap_usd=gap_usd,
                gap_pct=gap_pct,
                match_status=match_status,
                root_cause=root_cause,
                rag_sources=rag_sources,
                period=period,
                scenario=scenario,
                batch_id=batch_id,
            )

        except Exception as exc:
            logger.error("match_bilateral_pair failed: %s", exc)
            raise

    def generate_root_cause(self, match_result: MatchResult) -> str:
        """Use RAG retriever to generate root cause hypothesis."""
        try:
            entity_pair = f"{match_result.seller_entity} vs {match_result.buyer_entity}"
            rc_result = self.retriever.retrieve_root_cause(
                entity_pair=entity_pair,
                rule_code=match_result.rule_code,
                gap_pct=match_result.gap_pct,
                gap_usd=match_result.gap_usd,
            )
            hypothesis = rc_result.get("hypothesis", "No hypothesis available")
            return hypothesis
        except Exception as exc:
            logger.warning("generate_root_cause failed: %s", exc)
            return f"Root cause analysis unavailable: {exc}"

    def build_match_summary(
        self, batch_id: str, all_results: list, period: str, scenario: str
    ) -> MatchSummary:
        """Build aggregate summary from all match results."""
        try:
            total = len(all_results)
            matched_count = sum(1 for r in all_results if self._get_status(r) == "Matched")
            not_matched_count = sum(1 for r in all_results if self._get_status(r) == "Not Matched")
            fx_diff_count = sum(1 for r in all_results if self._get_status(r) == "FX Diff")
            exception_count = sum(1 for r in all_results if self._get_status(r) == "Exception")
            exception_pct = exception_count / total if total > 0 else 0.0

            total_seller_usd = sum(self._get_field(r, "seller_usd", 0.0) for r in all_results)
            total_buyer_usd = sum(self._get_field(r, "buyer_usd", 0.0) for r in all_results)
            total_gap_usd = sum(self._get_field(r, "gap_usd", 0.0) for r in all_results)

            return MatchSummary(
                batch_id=batch_id,
                total_pairs=total,
                matched_count=matched_count,
                not_matched_count=not_matched_count,
                fx_diff_count=fx_diff_count,
                exception_count=exception_count,
                exception_pct=exception_pct,
                total_seller_usd=total_seller_usd,
                total_buyer_usd=total_buyer_usd,
                total_gap_usd=total_gap_usd,
                period=period,
                scenario=scenario,
            )
        except Exception as exc:
            logger.error("build_match_summary failed: %s", exc)
            return MatchSummary(
                batch_id=batch_id,
                total_pairs=0,
                matched_count=0,
                not_matched_count=0,
                fx_diff_count=0,
                exception_count=0,
                exception_pct=0.0,
                total_seller_usd=0.0,
                total_buyer_usd=0.0,
                total_gap_usd=0.0,
                period=period,
                scenario=scenario,
            )

    def _group_by_entity_pair(self, df: pd.DataFrame) -> dict:
        """Group transactions by (seller_entity, buyer_entity, rule_code)."""
        try:
            groups = {}
            for _, row in df.iterrows():
                seller = str(row.get("seller_entity", ""))
                buyer = str(row.get("buyer_entity", ""))
                rule = str(row.get("rule_code", ""))
                key = (seller, buyer, rule)
                if key not in groups:
                    groups[key] = []
                groups[key].append(row.to_dict())

            # Convert lists to DataFrames
            return {k: pd.DataFrame(v) for k, v in groups.items()}
        except Exception as exc:
            logger.error("_group_by_entity_pair failed: %s", exc)
            return {}

    # ──────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ──────────────────────────────────────────────────────────────────────

    def _process_single_row(
        self, row, seller_entity: str, buyer_entity: str, rule_code: str, fx_rates: dict
    ) -> MatchResult:
        """Process a single transaction row where we don't have a bilateral pair."""
        row_dict = row.to_dict() if hasattr(row, "to_dict") else dict(row)
        row_dict["seller_entity"] = seller_entity
        row_dict["buyer_entity"] = buyer_entity
        row_dict["rule_code"] = rule_code

        seller_amount = float(row_dict.get("seller_amount", 0) or 0)
        buyer_amount = float(row_dict.get("buyer_amount", 0) or 0)
        seller_currency = str(row_dict.get("seller_currency", "USD")).upper()
        buyer_currency = str(row_dict.get("buyer_currency", "USD")).upper()
        txn_id = str(row_dict.get("txn_id", str(uuid.uuid4())))
        account = str(row_dict.get("account", ""))
        period = str(row_dict.get("period", ""))
        scenario = str(row_dict.get("scenario", ""))
        batch_id = str(row_dict.get("batch_id", ""))

        seller_usd = convert_to_usd(abs(seller_amount), seller_currency)
        buyer_usd = convert_to_usd(abs(buyer_amount), buyer_currency)
        gap_usd = abs(seller_usd - buyer_usd)
        max_usd = max(seller_usd, buyer_usd)
        gap_pct = (gap_usd / max_usd) if max_usd > 0 else 0.0
        is_cross_currency = (seller_currency != buyer_currency)

        if is_cross_currency:
            match_status = "FX Diff"
        elif gap_pct < 0.005:
            match_status = "Matched"
        elif gap_pct < 0.02:
            match_status = "Not Matched"
        else:
            match_status = "Exception"

        return MatchResult(
            txn_id=txn_id,
            seller_entity=seller_entity,
            buyer_entity=buyer_entity,
            rule_code=rule_code,
            account=account,
            seller_amount=abs(seller_amount),
            buyer_amount=abs(buyer_amount),
            seller_currency=seller_currency,
            buyer_currency=buyer_currency,
            seller_usd=seller_usd,
            buyer_usd=buyer_usd,
            gap_usd=gap_usd,
            gap_pct=gap_pct,
            match_status=match_status,
            period=period,
            scenario=scenario,
            batch_id=batch_id,
        )

    def _classify_result(
        self,
        result: MatchResult,
        matched: list,
        not_matched: list,
        fx_diff: list,
        exceptions: list,
    ) -> None:
        if result.match_status == "Matched":
            matched.append(result)
        elif result.match_status == "Not Matched":
            not_matched.append(result)
        elif result.match_status == "FX Diff":
            fx_diff.append(result)
        else:
            exceptions.append(result)

    @staticmethod
    def _get_status(r) -> str:
        if isinstance(r, MatchResult):
            return r.match_status
        return r.get("match_status", "")

    @staticmethod
    def _get_field(r, field: str, default=0.0):
        if isinstance(r, MatchResult):
            return getattr(r, field, default)
        return r.get(field, default)

    def _empty_matching_result(self, batch_id: str, period: str, scenario: str) -> dict:
        return {
            "batch_id": batch_id,
            "period": period,
            "scenario": scenario,
            "matched_pairs": [],
            "not_matched_pairs": [],
            "fx_diff_pairs": [],
            "exception_pairs": [],
            "all_results": [],
            "summary": {
                "batch_id": batch_id,
                "total_pairs": 0,
                "matched_count": 0,
                "not_matched_count": 0,
                "fx_diff_count": 0,
                "exception_count": 0,
                "exception_pct": 0.0,
                "total_seller_usd": 0.0,
                "total_buyer_usd": 0.0,
                "total_gap_usd": 0.0,
                "period": period,
                "scenario": scenario,
            },
        }
