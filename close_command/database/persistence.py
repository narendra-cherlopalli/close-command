"""
SQLite persistence layer for Close Command.
Manages all tables: journal_entries, review_decisions, match_results,
validation_results, batch_runs, and escalations.
"""

from __future__ import annotations

import sqlite3
import json
import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


class CloseCommandDB:
    """SQLite persistence layer for the Close Command application."""

    def __init__(self, db_path: str = "close_command.db") -> None:
        self.db_path = db_path
        self.init_schema()

    # ──────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ──────────────────────────────────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @staticmethod
    def _row_to_dict(row: sqlite3.Row | None) -> dict | None:
        if row is None:
            return None
        return dict(row)

    @staticmethod
    def _rows_to_list(rows: list[sqlite3.Row]) -> list[dict]:
        return [dict(r) for r in rows]

    @staticmethod
    def _serialize(value: Any) -> str:
        """Serialize lists/dicts to JSON strings for TEXT columns."""
        if isinstance(value, (list, dict)):
            return json.dumps(value)
        return str(value) if value is not None else ""

    # ──────────────────────────────────────────────────────────────────────
    # Schema
    # ──────────────────────────────────────────────────────────────────────

    def init_schema(self) -> None:
        """Create all tables if they do not already exist."""
        ddl_statements = [
            # journal_entries
            """
            CREATE TABLE IF NOT EXISTS journal_entries (
                txn_id          TEXT PRIMARY KEY,
                seller          TEXT NOT NULL,
                buyer           TEXT NOT NULL,
                rule_code       TEXT NOT NULL,
                account         TEXT NOT NULL,
                flow            TEXT DEFAULT 'F00',
                icp             TEXT DEFAULT '',
                custom3_ccy     TEXT DEFAULT 'USD',
                dr_cr           TEXT NOT NULL,
                amount          REAL NOT NULL,
                amount_usd      REAL NOT NULL,
                value           TEXT DEFAULT '[Elimination]',
                audit_code      TEXT NOT NULL,
                period          TEXT NOT NULL,
                scenario        TEXT NOT NULL,
                entity_method   TEXT DEFAULT 'GLOBAL',
                pcon            REAL DEFAULT 100.0,
                pown            REAL DEFAULT 100.0,
                computed_by     TEXT DEFAULT 'Elimination Agent',
                computed_at     TEXT,
                gate_status     TEXT DEFAULT 'PENDING',
                nci_applicable  INTEGER DEFAULT 0,
                batch_id        TEXT,
                created_at      TEXT DEFAULT (datetime('now'))
            )
            """,
            # review_decisions
            """
            CREATE TABLE IF NOT EXISTS review_decisions (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                txn_id          TEXT NOT NULL,
                decision        TEXT NOT NULL,
                reviewer_name   TEXT NOT NULL,
                reviewer_role   TEXT NOT NULL,
                timestamp       TEXT,
                comment         TEXT,
                gate_status     TEXT,
                batch_id        TEXT NOT NULL,
                period          TEXT NOT NULL,
                created_at      TEXT DEFAULT (datetime('now'))
            )
            """,
            # match_results
            """
            CREATE TABLE IF NOT EXISTS match_results (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                txn_id          TEXT NOT NULL,
                seller_entity   TEXT NOT NULL,
                buyer_entity    TEXT NOT NULL,
                rule_code       TEXT NOT NULL,
                account         TEXT NOT NULL,
                seller_amount   REAL,
                buyer_amount    REAL,
                seller_currency TEXT,
                buyer_currency  TEXT,
                seller_usd      REAL,
                buyer_usd       REAL,
                gap_usd         REAL,
                gap_pct         REAL,
                match_status    TEXT NOT NULL,
                root_cause      TEXT,
                rag_sources     TEXT,
                period          TEXT NOT NULL,
                scenario        TEXT NOT NULL,
                batch_id        TEXT NOT NULL,
                created_at      TEXT DEFAULT (datetime('now'))
            )
            """,
            # validation_results
            """
            CREATE TABLE IF NOT EXISTS validation_results (
                id                      INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id                TEXT NOT NULL UNIQUE,
                balance_check           INTEGER DEFAULT 0,
                continuation_check      INTEGER DEFAULT 0,
                policy_check            INTEGER DEFAULT 0,
                prior_period_deviation  REAL DEFAULT 0.0,
                validation_score        REAL DEFAULT 0.0,
                recommendation          TEXT NOT NULL,
                issues                  TEXT,
                balance_result          TEXT,
                continuation_result     TEXT,
                validated_at            TEXT DEFAULT (datetime('now'))
            )
            """,
            # batch_runs
            """
            CREATE TABLE IF NOT EXISTS batch_runs (
                batch_id        TEXT PRIMARY KEY,
                period          TEXT NOT NULL,
                scenario        TEXT NOT NULL,
                status          TEXT DEFAULT 'RUNNING',
                started_at      TEXT DEFAULT (datetime('now')),
                completed_at    TEXT,
                quality_score   REAL DEFAULT 0.0,
                entry_count     INTEGER DEFAULT 0,
                notes           TEXT
            )
            """,
            # escalations
            """
            CREATE TABLE IF NOT EXISTS escalations (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id        TEXT NOT NULL,
                txn_id          TEXT,
                reason          TEXT NOT NULL,
                escalated_at    TEXT DEFAULT (datetime('now')),
                resolved        INTEGER DEFAULT 0,
                resolved_at     TEXT
            )
            """,
        ]

        index_statements = [
            "CREATE INDEX IF NOT EXISTS idx_je_batch ON journal_entries(batch_id)",
            "CREATE INDEX IF NOT EXISTS idx_je_period ON journal_entries(period)",
            "CREATE INDEX IF NOT EXISTS idx_je_gate ON journal_entries(gate_status)",
            "CREATE INDEX IF NOT EXISTS idx_rd_batch ON review_decisions(batch_id)",
            "CREATE INDEX IF NOT EXISTS idx_mr_batch ON match_results(batch_id)",
            "CREATE INDEX IF NOT EXISTS idx_mr_status ON match_results(match_status)",
            "CREATE INDEX IF NOT EXISTS idx_esc_batch ON escalations(batch_id)",
            "CREATE INDEX IF NOT EXISTS idx_esc_resolved ON escalations(resolved)",
        ]

        try:
            with self._connect() as conn:
                for ddl in ddl_statements:
                    conn.execute(ddl)
                for idx in index_statements:
                    conn.execute(idx)
                conn.commit()
            logger.info("Schema initialised successfully at %s", self.db_path)
        except Exception as exc:
            logger.error("Schema initialisation failed: %s", exc)
            raise

    # ──────────────────────────────────────────────────────────────────────
    # Journal Entries
    # ──────────────────────────────────────────────────────────────────────

    def save_journal_entries(self, entries: list[dict]) -> int:
        """Persist a list of journal entry dicts. Returns count inserted."""
        if not entries:
            return 0
        sql = """
            INSERT OR REPLACE INTO journal_entries
                (txn_id, seller, buyer, rule_code, account, flow, icp, custom3_ccy,
                 dr_cr, amount, amount_usd, value, audit_code, period, scenario,
                 entity_method, pcon, pown, computed_by, computed_at,
                 gate_status, nci_applicable, batch_id)
            VALUES
                (:txn_id, :seller, :buyer, :rule_code, :account, :flow, :icp, :custom3_ccy,
                 :dr_cr, :amount, :amount_usd, :value, :audit_code, :period, :scenario,
                 :entity_method, :pcon, :pown, :computed_by, :computed_at,
                 :gate_status, :nci_applicable, :batch_id)
        """
        inserted = 0
        try:
            with self._connect() as conn:
                for entry in entries:
                    row = dict(entry)
                    row.setdefault("flow", "F00")
                    row.setdefault("icp", "")
                    row.setdefault("custom3_ccy", "USD")
                    row.setdefault("value", "[Elimination]")
                    row.setdefault("entity_method", "GLOBAL")
                    row.setdefault("pcon", 100.0)
                    row.setdefault("pown", 100.0)
                    row.setdefault("computed_by", "Elimination Agent")
                    row.setdefault("gate_status", "PENDING")
                    row.setdefault("nci_applicable", 0)
                    row.setdefault("batch_id", None)
                    # Serialize datetime
                    if isinstance(row.get("computed_at"), datetime):
                        row["computed_at"] = row["computed_at"].isoformat()
                    conn.execute(sql, row)
                    inserted += 1
                conn.commit()
            logger.info("Saved %d journal entries", inserted)
        except Exception as exc:
            logger.error("Failed to save journal entries: %s", exc)
            raise
        return inserted

    def get_journal_entries(self, batch_id: str) -> list[dict]:
        """Return all journal entries for a batch."""
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT * FROM journal_entries WHERE batch_id = ? ORDER BY txn_id",
                    (batch_id,),
                ).fetchall()
            return self._rows_to_list(rows)
        except Exception as exc:
            logger.error("get_journal_entries failed: %s", exc)
            return []

    def get_approved_entries(self, batch_id: str) -> list[dict]:
        """Return journal entries with gate_status = 'APPROVED' for a batch."""
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT * FROM journal_entries WHERE batch_id = ? AND gate_status = 'APPROVED'",
                    (batch_id,),
                ).fetchall()
            return self._rows_to_list(rows)
        except Exception as exc:
            logger.error("get_approved_entries failed: %s", exc)
            return []

    def get_period_journals(self, period: str) -> list[dict]:
        """Return all journal entries for a given period across all batches."""
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT * FROM journal_entries WHERE period = ? ORDER BY batch_id, txn_id",
                    (period,),
                ).fetchall()
            return self._rows_to_list(rows)
        except Exception as exc:
            logger.error("get_period_journals failed: %s", exc)
            return []

    # ──────────────────────────────────────────────────────────────────────
    # Review Decisions
    # ──────────────────────────────────────────────────────────────────────

    def save_review_decision(self, decision: dict) -> bool:
        """Persist a single review decision dict. Returns True on success."""
        sql = """
            INSERT INTO review_decisions
                (txn_id, decision, reviewer_name, reviewer_role, timestamp,
                 comment, gate_status, batch_id, period)
            VALUES
                (:txn_id, :decision, :reviewer_name, :reviewer_role, :timestamp,
                 :comment, :gate_status, :batch_id, :period)
        """
        try:
            row = dict(decision)
            if isinstance(row.get("timestamp"), datetime):
                row["timestamp"] = row["timestamp"].isoformat()
            with self._connect() as conn:
                conn.execute(sql, row)
                conn.commit()
            logger.info("Saved review decision for txn_id=%s", row.get("txn_id"))
            return True
        except Exception as exc:
            logger.error("save_review_decision failed: %s", exc)
            return False

    def get_review_decisions(self, batch_id: str) -> list[dict]:
        """Return all review decisions for a batch."""
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT * FROM review_decisions WHERE batch_id = ? ORDER BY id",
                    (batch_id,),
                ).fetchall()
            return self._rows_to_list(rows)
        except Exception as exc:
            logger.error("get_review_decisions failed: %s", exc)
            return []

    # ──────────────────────────────────────────────────────────────────────
    # Match Results
    # ──────────────────────────────────────────────────────────────────────

    def save_match_results(self, results: list[dict]) -> int:
        """Persist match result dicts. Returns count inserted."""
        if not results:
            return 0
        sql = """
            INSERT INTO match_results
                (txn_id, seller_entity, buyer_entity, rule_code, account,
                 seller_amount, buyer_amount, seller_currency, buyer_currency,
                 seller_usd, buyer_usd, gap_usd, gap_pct, match_status,
                 root_cause, rag_sources, period, scenario, batch_id)
            VALUES
                (:txn_id, :seller_entity, :buyer_entity, :rule_code, :account,
                 :seller_amount, :buyer_amount, :seller_currency, :buyer_currency,
                 :seller_usd, :buyer_usd, :gap_usd, :gap_pct, :match_status,
                 :root_cause, :rag_sources, :period, :scenario, :batch_id)
        """
        inserted = 0
        try:
            with self._connect() as conn:
                for result in results:
                    row = dict(result)
                    # Serialize rag_sources list
                    if isinstance(row.get("rag_sources"), list):
                        row["rag_sources"] = json.dumps(row["rag_sources"])
                    conn.execute(sql, row)
                    inserted += 1
                conn.commit()
            logger.info("Saved %d match results", inserted)
        except Exception as exc:
            logger.error("save_match_results failed: %s", exc)
            raise
        return inserted

    # ──────────────────────────────────────────────────────────────────────
    # Validation Results
    # ──────────────────────────────────────────────────────────────────────

    def save_validation_result(self, result: dict) -> bool:
        """Persist a validation result dict. Returns True on success."""
        sql = """
            INSERT OR REPLACE INTO validation_results
                (batch_id, balance_check, continuation_check, policy_check,
                 prior_period_deviation, validation_score, recommendation,
                 issues, balance_result, continuation_result, validated_at)
            VALUES
                (:batch_id, :balance_check, :continuation_check, :policy_check,
                 :prior_period_deviation, :validation_score, :recommendation,
                 :issues, :balance_result, :continuation_result, :validated_at)
        """
        try:
            row = dict(result)
            # Serialize list/dict fields
            for field in ("issues", "balance_result", "continuation_result"):
                if isinstance(row.get(field), (list, dict)):
                    row[field] = json.dumps(row[field])
            if isinstance(row.get("validated_at"), datetime):
                row["validated_at"] = row["validated_at"].isoformat()
            # Convert booleans to ints
            for bfield in ("balance_check", "continuation_check", "policy_check"):
                row[bfield] = int(bool(row.get(bfield, False)))
            with self._connect() as conn:
                conn.execute(sql, row)
                conn.commit()
            logger.info("Saved validation result for batch_id=%s", row.get("batch_id"))
            return True
        except Exception as exc:
            logger.error("save_validation_result failed: %s", exc)
            return False

    # ──────────────────────────────────────────────────────────────────────
    # Batch Runs
    # ──────────────────────────────────────────────────────────────────────

    def save_batch_run(self, batch: dict) -> bool:
        """Persist a batch run record. Returns True on success."""
        sql = """
            INSERT OR REPLACE INTO batch_runs
                (batch_id, period, scenario, status, started_at,
                 completed_at, quality_score, entry_count, notes)
            VALUES
                (:batch_id, :period, :scenario, :status, :started_at,
                 :completed_at, :quality_score, :entry_count, :notes)
        """
        try:
            row = dict(batch)
            row.setdefault("status", "RUNNING")
            row.setdefault("quality_score", 0.0)
            row.setdefault("entry_count", 0)
            row.setdefault("notes", "")
            row.setdefault("completed_at", None)
            for ts_field in ("started_at", "completed_at"):
                if isinstance(row.get(ts_field), datetime):
                    row[ts_field] = row[ts_field].isoformat()
            with self._connect() as conn:
                conn.execute(sql, row)
                conn.commit()
            logger.info("Saved batch run batch_id=%s", row.get("batch_id"))
            return True
        except Exception as exc:
            logger.error("save_batch_run failed: %s", exc)
            return False

    def update_batch_status(self, batch_id: str, status: str) -> bool:
        """Update the status (and completed_at if terminal) of a batch run."""
        try:
            terminal_statuses = {"COMPLETED", "FAILED", "CANCELLED"}
            now_iso = datetime.utcnow().isoformat()
            with self._connect() as conn:
                if status.upper() in terminal_statuses:
                    conn.execute(
                        "UPDATE batch_runs SET status = ?, completed_at = ? WHERE batch_id = ?",
                        (status, now_iso, batch_id),
                    )
                else:
                    conn.execute(
                        "UPDATE batch_runs SET status = ? WHERE batch_id = ?",
                        (status, batch_id),
                    )
                conn.commit()
            logger.info("Updated batch_id=%s to status=%s", batch_id, status)
            return True
        except Exception as exc:
            logger.error("update_batch_status failed: %s", exc)
            return False

    def get_batch_run(self, batch_id: str) -> dict | None:
        """Return the batch run record or None if not found."""
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM batch_runs WHERE batch_id = ?", (batch_id,)
                ).fetchone()
            return self._row_to_dict(row)
        except Exception as exc:
            logger.error("get_batch_run failed: %s", exc)
            return None

    def get_all_batches(self) -> list[dict]:
        """Return all batch run records ordered by started_at descending."""
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT * FROM batch_runs ORDER BY started_at DESC"
                ).fetchall()
            return self._rows_to_list(rows)
        except Exception as exc:
            logger.error("get_all_batches failed: %s", exc)
            return []

    # ──────────────────────────────────────────────────────────────────────
    # Escalations
    # ──────────────────────────────────────────────────────────────────────

    def save_escalation(self, escalation: dict) -> bool:
        """Persist an escalation record. Returns True on success."""
        sql = """
            INSERT INTO escalations (batch_id, txn_id, reason, escalated_at, resolved)
            VALUES (:batch_id, :txn_id, :reason, :escalated_at, :resolved)
        """
        try:
            row = dict(escalation)
            row.setdefault("resolved", 0)
            row.setdefault("txn_id", None)
            if isinstance(row.get("escalated_at"), datetime):
                row["escalated_at"] = row["escalated_at"].isoformat()
            else:
                row.setdefault("escalated_at", datetime.utcnow().isoformat())
            with self._connect() as conn:
                conn.execute(sql, row)
                conn.commit()
            logger.info("Saved escalation for batch_id=%s", row.get("batch_id"))
            return True
        except Exception as exc:
            logger.error("save_escalation failed: %s", exc)
            return False

    def get_pending_escalations(self) -> list[dict]:
        """Return all unresolved escalations."""
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT * FROM escalations WHERE resolved = 0 ORDER BY escalated_at DESC"
                ).fetchall()
            return self._rows_to_list(rows)
        except Exception as exc:
            logger.error("get_pending_escalations failed: %s", exc)
            return []

    def resolve_escalation(self, escalation_id: int) -> bool:
        """Mark an escalation as resolved. Returns True on success."""
        try:
            now_iso = datetime.utcnow().isoformat()
            with self._connect() as conn:
                conn.execute(
                    "UPDATE escalations SET resolved = 1, resolved_at = ? WHERE id = ?",
                    (now_iso, escalation_id),
                )
                conn.commit()
            logger.info("Resolved escalation id=%d", escalation_id)
            return True
        except Exception as exc:
            logger.error("resolve_escalation failed: %s", exc)
            return False
