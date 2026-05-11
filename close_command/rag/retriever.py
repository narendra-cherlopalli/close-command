"""
RAG retrieval logic for Close Command.
Provides structured retrieval results for root-cause analysis,
policy lookup, precedent matching, and prior-period comparison.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


class CloseCommandRetriever:
    """Retrieves relevant documents from the Close Command vector store."""

    def __init__(self, vectorstore: Any) -> None:
        """
        Args:
            vectorstore: An instance of CloseCommandVectorStore.
        """
        self.vectorstore = vectorstore

    # ──────────────────────────────────────────────────────────────────────
    # Root cause retrieval
    # ──────────────────────────────────────────────────────────────────────

    def retrieve_root_cause(
        self,
        entity_pair: str,
        rule_code: str,
        gap_pct: float,
        gap_usd: float,
    ) -> dict:
        """Query historical exceptions to suggest root cause for a new gap.

        Args:
            entity_pair: e.g. "HCG-UK vs HCG-DE"
            rule_code:   e.g. "IC-001"
            gap_pct:     Percentage gap between seller and buyer amounts
            gap_usd:     Absolute USD gap

        Returns:
            dict with keys: sources (list[dict]), confidence (float),
            hypothesis (str), top_cause (str)
        """
        try:
            query_text = (
                f"Intercompany exception between {entity_pair} for rule {rule_code} "
                f"with gap of {gap_pct:.2f}% (USD {gap_usd:,.2f}). "
                f"What is the most likely root cause?"
            )

            docs = self.vectorstore.query_historical_exceptions(
                query_text=query_text, n_results=3
            )

            confidence = self.compute_confidence_score(docs)
            hypothesis = self.format_root_cause_hypothesis(
                exception_data={
                    "entity_pair": entity_pair,
                    "rule_code": rule_code,
                    "gap_pct": gap_pct,
                    "gap_usd": gap_usd,
                },
                retrieved_docs=docs,
            )

            top_cause = "Unknown"
            if docs:
                meta = docs[0].get("metadata", {})
                top_cause = meta.get("root_cause", "Unknown")

            return {
                "sources": docs,
                "confidence": confidence,
                "hypothesis": hypothesis,
                "top_cause": top_cause,
                "query": query_text,
                "n_retrieved": len(docs),
            }
        except Exception as exc:
            logger.error("retrieve_root_cause failed: %s", exc)
            return {
                "sources": [],
                "confidence": 0.0,
                "hypothesis": f"Root cause analysis unavailable: {exc}",
                "top_cause": "Unknown",
                "query": "",
                "n_retrieved": 0,
            }

    # ──────────────────────────────────────────────────────────────────────
    # Elimination precedent retrieval
    # ──────────────────────────────────────────────────────────────────────

    def retrieve_elimination_precedent(
        self,
        rule_code: str,
        entity_method: str,
        pcon: float,
    ) -> dict:
        """Query elimination_precedents for similar historical eliminations.

        Args:
            rule_code:     e.g. "EQ-001"
            entity_method: "GLOBAL" or "EQUITY"
            pcon:          Consolidation percentage

        Returns:
            dict with keys: sources (list[dict]), confidence (float),
            recommendation (str)
        """
        try:
            query_text = (
                f"Elimination rule {rule_code} applied using {entity_method} method "
                f"with consolidation percentage {pcon:.1f}%."
            )

            docs = self.vectorstore.query_elimination_precedents(
                query_text=query_text, rule_code=rule_code, n_results=3
            )

            confidence = self.compute_confidence_score(docs)

            recommendation = "No precedent found — apply standard elimination formula."
            if docs:
                best = docs[0]
                meta = best.get("metadata", {})
                recommendation = (
                    f"Closest precedent (similarity {best['similarity']:.2%}): "
                    f"{best.get('document', '')[:200]}"
                )

            return {
                "sources": docs,
                "confidence": confidence,
                "recommendation": recommendation,
                "rule_code": rule_code,
                "entity_method": entity_method,
                "pcon": pcon,
            }
        except Exception as exc:
            logger.error("retrieve_elimination_precedent failed: %s", exc)
            return {
                "sources": [],
                "confidence": 0.0,
                "recommendation": f"Precedent retrieval failed: {exc}",
                "rule_code": rule_code,
                "entity_method": entity_method,
                "pcon": pcon,
            }

    # ──────────────────────────────────────────────────────────────────────
    # Policy retrieval
    # ──────────────────────────────────────────────────────────────────────

    def retrieve_policy(self, rule_code: str, entity_scope: str) -> dict:
        """Query policy_documents for the applicable group accounting policy.

        Args:
            rule_code:    e.g. "IC-003"
            entity_scope: e.g. "HCG-SG GLOBAL 75%"

        Returns:
            dict with keys: sources (list[dict]), confidence (float),
            policy_summary (str)
        """
        try:
            query_text = (
                f"Group accounting policy for elimination rule {rule_code} "
                f"applied to entity scope: {entity_scope}. "
                f"What are the debit and credit accounts, gate conditions, "
                f"and NCI treatment?"
            )

            docs = self.vectorstore.query_policy_documents(
                query_text=query_text, n_results=5
            )

            confidence = self.compute_confidence_score(docs)

            policy_summary = "No policy document found — refer to Group Accounting Manual."
            if docs:
                best = docs[0]
                meta = best.get("metadata", {})
                policy_summary = (
                    f"Policy: {meta.get('title', 'N/A')} "
                    f"(similarity {best['similarity']:.2%}). "
                    f"Category: {meta.get('category', 'N/A')}. "
                    f"Rule: {meta.get('rule_code', 'N/A')}."
                )

            return {
                "sources": docs,
                "confidence": confidence,
                "policy_summary": policy_summary,
                "rule_code": rule_code,
                "entity_scope": entity_scope,
            }
        except Exception as exc:
            logger.error("retrieve_policy failed: %s", exc)
            return {
                "sources": [],
                "confidence": 0.0,
                "policy_summary": f"Policy retrieval failed: {exc}",
                "rule_code": rule_code,
                "entity_scope": entity_scope,
            }

    # ──────────────────────────────────────────────────────────────────────
    # Prior period retrieval
    # ──────────────────────────────────────────────────────────────────────

    def retrieve_prior_period(
        self,
        entity_pair: str,
        rule_code: str,
        current_period: str,
    ) -> dict:
        """Query period_journals for prior-period comparators.

        Args:
            entity_pair:     e.g. "HCG-UK HCG-DE"
            rule_code:       e.g. "IC-001"
            current_period:  e.g. "2024-03" — excluded from results

        Returns:
            dict with keys: sources (list[dict]), confidence (float),
            prior_amount_usd (float), deviation_note (str)
        """
        try:
            query_text = (
                f"Prior period journal entries for intercompany elimination "
                f"between {entity_pair} applying rule {rule_code}."
            )

            # Determine a prior period label (one month back) for the where filter
            prior_period = self._compute_prior_period(current_period)

            docs = self.vectorstore.query_period_journals(
                query_text=query_text, period=prior_period, n_results=3
            )

            confidence = self.compute_confidence_score(docs)

            prior_amount_usd = 0.0
            if docs:
                meta = docs[0].get("metadata", {})
                prior_amount_usd = meta.get("amount_usd", 0.0)

            deviation_note = (
                f"Prior period ({prior_period}) reference amount: "
                f"USD {prior_amount_usd:,.2f}. "
                f"Retrieved {len(docs)} document(s) with confidence {confidence:.2%}."
            )

            return {
                "sources": docs,
                "confidence": confidence,
                "prior_amount_usd": prior_amount_usd,
                "deviation_note": deviation_note,
                "prior_period": prior_period,
                "current_period": current_period,
            }
        except Exception as exc:
            logger.error("retrieve_prior_period failed: %s", exc)
            return {
                "sources": [],
                "confidence": 0.0,
                "prior_amount_usd": 0.0,
                "deviation_note": f"Prior period retrieval failed: {exc}",
                "prior_period": "",
                "current_period": current_period,
            }

    # ──────────────────────────────────────────────────────────────────────
    # Scoring and hypothesis generation
    # ──────────────────────────────────────────────────────────────────────

    def compute_confidence_score(self, results: list[dict]) -> float:
        """Compute a 0–1 confidence score from ChromaDB similarity scores.

        Uses average of per-document similarity values, weighted toward the
        top result (50% weight on rank-1, 30% on rank-2, 20% on rank-3).
        """
        try:
            if not results:
                return 0.0

            weights = [0.5, 0.3, 0.2]
            score = 0.0
            total_weight = 0.0

            for i, doc in enumerate(results[:3]):
                sim = doc.get("similarity", 0.0)
                w = weights[i] if i < len(weights) else 0.1
                score += sim * w
                total_weight += w

            if total_weight == 0:
                return 0.0

            return round(min(score / total_weight, 1.0), 4)
        except Exception as exc:
            logger.error("compute_confidence_score failed: %s", exc)
            return 0.0

    def format_root_cause_hypothesis(
        self, exception_data: dict, retrieved_docs: list[dict]
    ) -> str:
        """Generate a natural language root cause hypothesis.

        Args:
            exception_data: dict with entity_pair, rule_code, gap_pct, gap_usd
            retrieved_docs: list of retrieved historical exception dicts

        Returns:
            A human-readable hypothesis string.
        """
        try:
            entity_pair = exception_data.get("entity_pair", "unknown entities")
            rule_code = exception_data.get("rule_code", "unknown rule")
            gap_pct = exception_data.get("gap_pct", 0.0)
            gap_usd = exception_data.get("gap_usd", 0.0)

            if not retrieved_docs:
                return (
                    f"No historical precedent found for {entity_pair} / {rule_code}. "
                    f"Gap of {gap_pct:.2f}% (USD {gap_usd:,.2f}) requires manual investigation."
                )

            # Extract root causes from top-3 docs
            causes: list[str] = []
            for doc in retrieved_docs[:3]:
                meta = doc.get("metadata", {})
                cause = meta.get("root_cause", "")
                resolution = meta.get("resolution", "")
                sim = doc.get("similarity", 0.0)
                if cause:
                    causes.append(f"'{cause}' (similarity {sim:.2%}, resolution: {resolution})")

            causes_text = "; ".join(causes) if causes else "not determined from history"
            top_cause = retrieved_docs[0].get("metadata", {}).get("root_cause", "unknown")

            hypothesis = (
                f"For {entity_pair} applying rule {rule_code}: "
                f"A gap of {gap_pct:.2f}% (USD {gap_usd:,.2f}) was detected. "
                f"Based on {len(retrieved_docs)} historical exception(s), "
                f"the most likely root cause is '{top_cause}'. "
                f"Historical precedents: {causes_text}. "
                f"Recommended action: verify booking dates, FX rates applied, "
                f"and intercompany confirmation sign-off between entities."
            )
            return hypothesis
        except Exception as exc:
            logger.error("format_root_cause_hypothesis failed: %s", exc)
            return f"Hypothesis generation failed: {exc}"

    # ──────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ──────────────────────────────────────────────────────────────────────

    @staticmethod
    def _compute_prior_period(current_period: str) -> str:
        """Return the period one month before current_period.

        Supports YYYY-MM and YYYYMM formats. Returns empty string on failure.
        """
        try:
            current_period = current_period.strip()
            # Normalise to YYYY-MM
            if re.fullmatch(r"\d{6}", current_period):
                current_period = f"{current_period[:4]}-{current_period[4:]}"

            if not re.fullmatch(r"\d{4}-\d{2}", current_period):
                return ""

            year, month = int(current_period[:4]), int(current_period[5:7])
            if month == 1:
                year -= 1
                month = 12
            else:
                month -= 1
            return f"{year:04d}-{month:02d}"
        except Exception:
            return ""
