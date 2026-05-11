"""
Data Ingestion Agent for Close Command.
Handles both legacy IC-only format and full entity financial statement format.
Auto-detects format from CSV columns.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Optional

import pandas as pd

from close_command.database.persistence import CloseCommandDB
from close_command.data.entities import ENTITY_REGISTRY, VALID_ENTITY_CODES, get_entity
from close_command.data.fx_rates import convert_to_usd, is_valid_currency, FX_RATES
from close_command.data.rules import ELIMINATION_RULES
from close_command.models.financials import FinancialLine, EntityStatement

logger = logging.getLogger(__name__)

# ── Legacy IC-only format columns ──────────────────────────────────────────────
LEGACY_REQUIRED_COLUMNS = [
    "txn_id",
    "seller_entity",
    "buyer_entity",
    "seller_amount",
    "buyer_amount",
    "seller_currency",
    "buyer_currency",
    "rule_code",
    "account",
    "period",
    "scenario",
]

# ── Full financial statement format columns ─────────────────────────────────────
FULL_REQUIRED_COLUMNS = [
    "line_id",
    "entity_code",
    "account_code",
    "account_description",
    "account_type",
    "account_category",
    "is_intercompany",
    "icp_entity",
    "rule_code",
    "flow",
    "amount",
    "currency",
    "period",
    "scenario",
]

HELIOS_ENTITIES = ["HCG-UK", "HCG-DE", "HCG-US", "HCG-SG", "HCG-FR", "HCG-NL", "HCG-AU", "SHARED"]
SAMPLE_RULE_CODES = ["IC-001", "IC-002", "IC-003", "IC-004", "IC-005", "DIV-001", "INV-001", "AUC-001"]
VALID_CURRENCIES = set(FX_RATES.keys())


def _validate_csv_columns(df: pd.DataFrame, required_cols: list[str]) -> tuple[bool, list[str]]:
    """Check that all required columns exist in the dataframe."""
    try:
        existing = set(df.columns.tolist())
        missing = [col for col in required_cols if col not in existing]
        return (len(missing) == 0, missing)
    except Exception as exc:
        return (False, [f"ERROR: {exc}"])


def _detect_duplicate_txn_ids(df: pd.DataFrame, txn_id_col: str) -> list[str]:
    """Return list of duplicate id values."""
    try:
        if txn_id_col not in df.columns:
            return []
        counts = df[txn_id_col].dropna().astype(str).value_counts()
        return sorted(counts[counts > 1].index.tolist())
    except Exception:
        return []


def _compute_data_quality_score(df: pd.DataFrame, issues: list) -> float:
    """Compute 0-100 quality score."""
    try:
        if df is None or len(df) == 0:
            return 0.0
        score = 100.0
        score -= min(len(issues) * 5.0, 50.0)
        total_cells = df.shape[0] * df.shape[1]
        if total_cells > 0:
            null_pct = (df.isnull().sum().sum() / total_cells) * 100
            score -= min(null_pct, 30.0)
        return max(round(score, 2), 0.0)
    except Exception:
        return 0.0


def _detect_format(df: pd.DataFrame) -> str:
    """
    Detect whether the DataFrame is:
    - 'FULL_FINANCIAL': contains 'account_type' AND 'is_intercompany'
    - 'IC_ONLY': legacy format
    """
    cols = set(df.columns.tolist())
    if "account_type" in cols and "is_intercompany" in cols:
        return "FULL_FINANCIAL"
    return "IC_ONLY"


class DataIngestionAgent:
    """
    Validates and ingests financial data.
    Supports legacy IC-only format and full entity financial statement format.
    """

    def __init__(self, db: CloseCommandDB) -> None:
        self.db = db

    # ──────────────────────────────────────────────────────────────────────
    # Main entry point
    # ──────────────────────────────────────────────────────────────────────

    def run(self, state: dict) -> dict:
        """Main entry: validates and ingests data, updates state with ingestion_result."""
        try:
            batch_id = state.get("batch_id", str(uuid.uuid4()))
            period = state.get("period", "2024-12")
            scenario = state.get("scenario", "Actual")
            source_file = state.get("source_file", "")
            raw_data = state.get("raw_data")

            logger.info("DataIngestionAgent starting batch_id=%s period=%s", batch_id, period)

            # Load data
            if raw_data is not None and isinstance(raw_data, pd.DataFrame):
                df = raw_data.copy()
            elif source_file:
                try:
                    df = pd.read_csv(source_file)
                except Exception as exc:
                    logger.error("Failed to read source_file %s: %s", source_file, exc)
                    df = self._generate_sample_data(period, scenario)
            else:
                logger.info("No raw_data or source_file — generating sample data")
                df = self._generate_sample_data(period, scenario)

            # Detect format
            file_format = _detect_format(df)
            logger.info("DataIngestionAgent detected format: %s", file_format)

            if file_format == "FULL_FINANCIAL":
                return self._run_full_financial(state, df, batch_id, period, scenario)
            else:
                return self._run_legacy_ic_only(state, df, batch_id, period, scenario)

        except Exception as exc:
            logger.error("DataIngestionAgent.run failed: %s", exc)
            state.setdefault("errors", []).append(str(exc))
            state["ingestion_result"] = {
                "clean_data": pd.DataFrame(),
                "non_ic_data": pd.DataFrame(),
                "entity_statements": {},
                "all_lines": pd.DataFrame(),
                "quality_score": 0.0,
                "anomalies": [],
                "rejected_rows": [],
                "status": "FAIL",
                "file_format": "UNKNOWN",
                "batch_id": state.get("batch_id", ""),
                "period": state.get("period", ""),
                "scenario": state.get("scenario", ""),
                "total_lines": 0,
                "ic_lines": 0,
                "non_ic_lines": 0,
                "entities_present": [],
                "issues": [str(exc)],
            }
            return state

    # ──────────────────────────────────────────────────────────────────────
    # Full Financial Statement format handler
    # ──────────────────────────────────────────────────────────────────────

    def _run_full_financial(
        self,
        state: dict,
        df: pd.DataFrame,
        batch_id: str,
        period: str,
        scenario: str,
    ) -> dict:
        """Process FULL_FINANCIAL format data."""
        # 1. Validate required columns
        schema_ok, missing_cols = _validate_csv_columns(df, FULL_REQUIRED_COLUMNS)
        if not schema_ok:
            error_msg = f"Full Financial schema validation failed — missing columns: {missing_cols}"
            logger.error(error_msg)
            state.setdefault("errors", []).append(error_msg)
            state["ingestion_result"] = {
                "clean_data": pd.DataFrame(),
                "non_ic_data": pd.DataFrame(),
                "entity_statements": {},
                "all_lines": pd.DataFrame(),
                "quality_score": 0.0,
                "anomalies": [],
                "rejected_rows": [],
                "status": "FAIL",
                "file_format": "FULL_FINANCIAL",
                "batch_id": batch_id,
                "period": period,
                "scenario": scenario,
                "total_lines": 0,
                "ic_lines": 0,
                "non_ic_lines": 0,
                "entities_present": [],
                "missing_columns": missing_cols,
            }
            return state

        # Normalise is_intercompany to bool
        try:
            df["is_intercompany"] = df["is_intercompany"].apply(
                lambda v: v if isinstance(v, bool) else str(v).strip().lower() in ("true", "1", "yes")
            )
        except Exception:
            pass

        # Ensure icp_entity and rule_code are strings (handle NaN)
        df["icp_entity"] = df["icp_entity"].where(df["icp_entity"].notna(), None)
        df["rule_code"] = df["rule_code"].where(df["rule_code"].notna(), None)

        issues: list[str] = []
        anomalies: list[dict] = []
        rejected_rows: list[dict] = []

        # 2. Validate entity codes
        unknown_entities = []
        for ec in df["entity_code"].dropna().unique():
            if str(ec) not in VALID_ENTITY_CODES:
                unknown_entities.append(str(ec))
        if unknown_entities:
            issues.append(f"Unknown entity codes: {unknown_entities}")

        # 3. Validate currency codes
        unknown_currencies = []
        for cur in df["currency"].dropna().unique():
            if not is_valid_currency(str(cur)):
                unknown_currencies.append(str(cur))
        if unknown_currencies:
            issues.append(f"Unknown currencies: {unknown_currencies}")

        # 4-5. Validate IC lines
        ic_mask = df["is_intercompany"] == True
        ic_rows = df[ic_mask]

        # IC lines missing icp_entity
        missing_icp = ic_rows[ic_rows["icp_entity"].isna() | (ic_rows["icp_entity"].astype(str).str.strip() == "")]
        for _, row in missing_icp.iterrows():
            anomalies.append({
                "line_id": str(row.get("line_id", "")),
                "type": "IC_MISSING_ICP",
                "description": f"IC line {row['line_id']} has no icp_entity",
            })
            issues.append(f"IC line {row['line_id']} missing icp_entity")

        # IC lines missing rule_code
        missing_rule = ic_rows[ic_rows["rule_code"].isna() | (ic_rows["rule_code"].astype(str).str.strip() == "")]
        for _, row in missing_rule.iterrows():
            anomalies.append({
                "line_id": str(row.get("line_id", "")),
                "type": "IC_MISSING_RULE",
                "description": f"IC line {row['line_id']} has no rule_code",
            })
            issues.append(f"IC line {row['line_id']} missing rule_code")

        # icp_entity not in ENTITY_REGISTRY
        ic_known = ic_rows[ic_rows["icp_entity"].notna()]
        bad_icp = ic_known[~ic_known["icp_entity"].astype(str).isin(VALID_ENTITY_CODES)]
        for _, row in bad_icp.iterrows():
            anomalies.append({
                "line_id": str(row.get("line_id", "")),
                "type": "UNKNOWN_ICP_ENTITY",
                "description": f"IC line {row['line_id']} icp_entity '{row['icp_entity']}' not in registry",
            })
            issues.append(f"IC line {row['line_id']} icp_entity '{row['icp_entity']}' unknown")

        # rule_code not in ELIMINATION_RULES
        ic_has_rule = ic_rows[ic_rows["rule_code"].notna()]
        bad_rules = ic_has_rule[~ic_has_rule["rule_code"].astype(str).isin(ELIMINATION_RULES.keys())]
        for _, row in bad_rules.iterrows():
            anomalies.append({
                "line_id": str(row.get("line_id", "")),
                "type": "UNKNOWN_RULE_CODE",
                "description": f"IC line {row['line_id']} rule_code '{row['rule_code']}' not in ELIMINATION_RULES",
            })
            issues.append(f"IC line {row['line_id']} rule_code '{row['rule_code']}' invalid")

        # 6. Convert amounts to USD
        df = df.copy()
        df["amount_usd"] = 0.0
        for idx, row in df.iterrows():
            try:
                ccy = str(row.get("currency", "USD")).upper()
                amt = float(row.get("amount", 0.0) or 0.0)
                df.at[idx, "amount_usd"] = convert_to_usd(amt, ccy)
            except Exception as exc:
                df.at[idx, "amount_usd"] = 0.0
                anomalies.append({
                    "line_id": str(row.get("line_id", "")),
                    "type": "FX_CONVERSION_FAIL",
                    "description": f"FX conversion failed for line {row.get('line_id', '')}: {exc}",
                })

        # 7. Detect orphaned IC lines (seller has IC revenue but no matching buyer line)
        ic_p_and_l = df[(df["is_intercompany"] == True) & (df["account_type"] == "P&L")]
        ic_revenue_lines = ic_p_and_l[ic_p_and_l["account_category"] == "Revenue"]
        ic_cost_lines = ic_p_and_l[ic_p_and_l["account_category"].isin(["COGS", "OpEx"])]

        for _, rev_row in ic_revenue_lines.iterrows():
            seller = str(rev_row["entity_code"])
            buyer = str(rev_row.get("icp_entity", "")) if rev_row.get("icp_entity") else ""
            if not buyer:
                continue
            # Look for matching cost line in buyer entity
            matching = ic_cost_lines[
                (ic_cost_lines["entity_code"] == buyer) &
                (ic_cost_lines["icp_entity"].astype(str) == seller)
            ]
            if len(matching) == 0:
                anomalies.append({
                    "line_id": str(rev_row.get("line_id", "")),
                    "type": "ORPHANED_IC_LINE",
                    "description": (
                        f"IC revenue line {rev_row['line_id']} in {seller} to {buyer} "
                        f"has no matching cost line in {buyer}"
                    ),
                })

        # Reject rows with unknown entity codes
        bad_entity_mask = df["entity_code"].astype(str).isin(unknown_entities)
        if bad_entity_mask.any():
            rejected_rows.extend(df[bad_entity_mask].to_dict(orient="records"))
            df = df[~bad_entity_mask]

        # Reject rows with unknown currencies
        bad_currency_mask = df["currency"].astype(str).isin(unknown_currencies)
        if bad_currency_mask.any():
            rejected_rows.extend(df[bad_currency_mask].to_dict(orient="records"))
            df = df[~bad_currency_mask]

        # Add batch_id column
        df["batch_id"] = batch_id

        # 7. Split into IC and Non-IC data
        ic_data = df[df["is_intercompany"] == True].copy()
        non_ic_data = df[df["is_intercompany"] == False].copy()

        # Transform IC lines into bilateral pair format for matching agent
        ic_pairs = self._build_bilateral_pairs(ic_data, batch_id, period, scenario)

        # 8. Build entity_statements
        entity_statements = self._build_entity_statements(df, batch_id, period, scenario)

        # 9. Compute quality score
        quality_score = _compute_data_quality_score(df, issues)

        # Determine status
        if len(unknown_entities) > 3:
            status = "FAIL"
        elif quality_score < 85:
            status = "PARTIAL"
        else:
            status = "PASS"

        # Escalation check
        if quality_score < 85:
            escalation = {
                "type": "DATA_QUALITY",
                "batch_id": batch_id,
                "quality_score": quality_score,
                "reason": f"Data quality score {quality_score:.1f} below threshold 85",
                "timestamp": datetime.utcnow().isoformat(),
            }
            state.setdefault("escalations", []).append(escalation)
            logger.warning("Escalation: quality_score=%.1f < 85", quality_score)

        entities_present = sorted(df["entity_code"].dropna().unique().tolist())

        ingestion_result = {
            "batch_id": batch_id,
            "file_format": "FULL_FINANCIAL",
            "clean_data": ic_pairs,          # Bilateral pair format — feeds matching pipeline
            "non_ic_data": non_ic_data,       # Non-IC lines
            "entity_statements": entity_statements,
            "all_lines": df,
            "quality_score": quality_score,
            "anomalies": anomalies,
            "rejected_rows": rejected_rows,
            "status": status,
            "total_lines": len(df),
            "ic_lines": len(ic_data),
            "non_ic_lines": len(non_ic_data),
            "entities_present": entities_present,
            "period": period,
            "scenario": scenario,
            "issues": issues,
            "unknown_entities": unknown_entities,
            "unknown_currencies": unknown_currencies,
        }

        state["ingestion_result"] = ingestion_result

        logger.info(
            "DataIngestionAgent (FULL_FINANCIAL) complete: status=%s quality=%.1f "
            "total=%d ic=%d non_ic=%d entities=%d",
            status, quality_score, len(df), len(ic_data), len(non_ic_data), len(entities_present),
        )

        # Persist batch run record
        try:
            with self.db._connect() as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO batch_runs
                        (batch_id, period, scenario, status, quality_score)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (batch_id, period, scenario, status, quality_score),
                )
                conn.commit()
        except Exception as db_exc:
            logger.warning("Failed to persist batch run: %s", db_exc)

        return state

    # ──────────────────────────────────────────────────────────────────────
    # Build EntityStatement objects from dataframe
    # ──────────────────────────────────────────────────────────────────────

    def _build_bilateral_pairs(
        self,
        ic_data: pd.DataFrame,
        batch_id: str,
        period: str,
        scenario: str,
    ) -> pd.DataFrame:
        """
        Transform full-financial IC lines into the bilateral pair format
        expected by the matching agent.

        Full-financial IC lines have:
            entity_code, icp_entity, amount, currency, rule_code, account_category

        The matching agent expects rows with:
            txn_id, seller_entity, buyer_entity,
            seller_amount, buyer_amount,
            seller_currency, buyer_currency,
            rule_code, account, period, scenario, batch_id

        Strategy:
          - Revenue IC lines → seller side
          - COGS/OpEx IC lines → buyer side
          - Match seller and buyer by (entity_code ↔ icp_entity, rule_code)
          - BS IC lines (IC-002 receivables/payables) are skipped here;
            they are handled separately in the BS elimination step.
        """
        try:
            if ic_data is None or ic_data.empty:
                return pd.DataFrame()

            # Only process P&L IC lines for matching (BS handled in elimination)
            pl_ic = ic_data[ic_data["account_type"] == "P&L"].copy() if "account_type" in ic_data.columns else ic_data.copy()

            # Seller side: Revenue IC lines
            revenue_lines = pl_ic[pl_ic["account_category"] == "Revenue"].copy() if "account_category" in pl_ic.columns else pd.DataFrame()
            # Buyer side: COGS or OpEx IC lines
            cost_lines = pl_ic[pl_ic["account_category"].isin(["COGS", "OpEx"])].copy() if "account_category" in pl_ic.columns else pd.DataFrame()

            if revenue_lines.empty and cost_lines.empty:
                logger.warning("_build_bilateral_pairs: no P&L IC revenue or cost lines found")
                return pd.DataFrame()

            pairs = []
            matched_cost_indices = set()

            for _, rev_row in revenue_lines.iterrows():
                seller_entity = str(rev_row.get("entity_code", ""))
                buyer_entity = str(rev_row.get("icp_entity", "")) if rev_row.get("icp_entity") else ""
                rule_code = str(rev_row.get("rule_code", "")) if rev_row.get("rule_code") else ""

                if not buyer_entity:
                    continue

                # Find matching cost line: buyer's entity_code == buyer_entity AND icp_entity == seller
                cost_match = cost_lines[
                    (cost_lines["entity_code"].astype(str) == buyer_entity) &
                    (cost_lines["icp_entity"].astype(str) == seller_entity) &
                    (cost_lines["rule_code"].astype(str) == rule_code)
                ]

                seller_amount = abs(float(rev_row.get("amount", 0) or 0))
                seller_currency = str(rev_row.get("currency", "USD")).upper()
                account = str(rev_row.get("account_description", rev_row.get("account_code", "")))

                if not cost_match.empty:
                    cost_row = cost_match.iloc[0]
                    buyer_amount = abs(float(cost_row.get("amount", 0) or 0))
                    buyer_currency = str(cost_row.get("currency", "USD")).upper()
                    matched_cost_indices.add(cost_match.index[0])
                else:
                    # No matching buyer line — use seller amount as estimate
                    buyer_amount = seller_amount
                    buyer_currency = seller_currency
                    logger.debug(
                        "_build_bilateral_pairs: no cost match for %s->%s rule=%s",
                        seller_entity, buyer_entity, rule_code,
                    )

                pairs.append({
                    "txn_id": str(rev_row.get("line_id", str(uuid.uuid4()))),
                    "seller_entity": seller_entity,
                    "buyer_entity": buyer_entity,
                    "seller_amount": seller_amount,
                    "buyer_amount": buyer_amount,
                    "seller_currency": seller_currency,
                    "buyer_currency": buyer_currency,
                    "rule_code": rule_code,
                    "account": account,
                    "period": str(rev_row.get("period", period)),
                    "scenario": str(rev_row.get("scenario", scenario)),
                    "batch_id": batch_id,
                })

            if not pairs:
                logger.warning("_build_bilateral_pairs: no bilateral pairs could be built")
                return pd.DataFrame()

            result_df = pd.DataFrame(pairs)
            logger.info("_build_bilateral_pairs: built %d bilateral pairs from %d IC lines", len(result_df), len(ic_data))
            return result_df

        except Exception as exc:
            logger.error("_build_bilateral_pairs failed: %s", exc)
            return pd.DataFrame()

    def _build_entity_statements(
        self,
        df: pd.DataFrame,
        batch_id: str,
        period: str,
        scenario: str,
    ) -> dict[str, dict]:
        """Build EntityStatement for each entity in the dataframe."""
        entity_statements: dict[str, dict] = {}

        for entity_code in df["entity_code"].dropna().unique():
            entity_df = df[df["entity_code"] == entity_code]
            entity_info = get_entity(str(entity_code)) or {}
            entity_currency = entity_info.get("currency", "USD")

            lines: list[FinancialLine] = []
            for _, row in entity_df.iterrows():
                try:
                    ic_flag = bool(row.get("is_intercompany", False))
                    icp = row.get("icp_entity")
                    rc = row.get("rule_code")
                    line = FinancialLine(
                        line_id=str(row.get("line_id", "")),
                        entity_code=str(row.get("entity_code", "")),
                        account_code=str(row.get("account_code", "")),
                        account_description=str(row.get("account_description", "")),
                        account_type=str(row.get("account_type", "P&L")),
                        account_category=str(row.get("account_category", "")),
                        is_intercompany=ic_flag,
                        icp_entity=str(icp) if icp and str(icp) != "nan" else None,
                        rule_code=str(rc) if rc and str(rc) != "nan" else None,
                        flow=str(row.get("flow", "F00")),
                        amount=float(row.get("amount", 0.0) or 0.0),
                        currency=str(row.get("currency", "USD")),
                        amount_usd=float(row.get("amount_usd", 0.0) or 0.0),
                        period=str(row.get("period", period)),
                        scenario=str(row.get("scenario", scenario)),
                        batch_id=batch_id,
                    )
                    lines.append(line)
                except Exception as line_exc:
                    logger.warning("Could not build FinancialLine for row: %s", line_exc)

            # Compute totals from lines (amounts in USD)
            def _sum_cat(cat: str, ic_flag_filter: Optional[bool] = None) -> float:
                total = 0.0
                for ln in lines:
                    cat_match = ln.account_category == cat
                    ic_match = (ic_flag_filter is None) or (ln.is_intercompany == ic_flag_filter)
                    if cat_match and ic_match:
                        total += ln.amount_usd
                return total

            def _sum_account_type_cat(atype: str, cat: str) -> float:
                total = 0.0
                for ln in lines:
                    if ln.account_type == atype and ln.account_category == cat:
                        total += ln.amount_usd
                return total

            total_revenue = abs(_sum_account_type_cat("P&L", "Revenue"))
            total_cogs = abs(_sum_account_type_cat("P&L", "COGS"))
            total_opex = abs(_sum_account_type_cat("P&L", "OpEx"))
            total_assets = abs(_sum_account_type_cat("BS", "Assets"))
            total_liabilities = abs(_sum_account_type_cat("BS", "Liabilities"))
            total_equity = abs(_sum_account_type_cat("BS", "Equity"))

            ic_lines_only = [ln for ln in lines if ln.is_intercompany]
            ic_revenue = abs(sum(
                ln.amount_usd for ln in ic_lines_only
                if ln.account_type == "P&L" and ln.account_category == "Revenue"
            ))
            ic_costs = abs(sum(
                ln.amount_usd for ln in ic_lines_only
                if ln.account_type == "P&L" and ln.account_category in ("COGS", "OpEx")
            ))
            ic_receivables = abs(sum(
                ln.amount_usd for ln in ic_lines_only
                if ln.account_type == "BS" and ln.account_category == "Assets"
            ))
            ic_payables = abs(sum(
                ln.amount_usd for ln in ic_lines_only
                if ln.account_type == "BS" and ln.account_category == "Liabilities"
            ))

            stmt = EntityStatement(
                entity_code=str(entity_code),
                period=period,
                scenario=scenario,
                batch_id=batch_id,
                lines=lines,
                total_revenue=round(total_revenue, 2),
                total_cogs=round(total_cogs, 2),
                total_opex=round(total_opex, 2),
                total_assets=round(total_assets, 2),
                total_liabilities=round(total_liabilities, 2),
                total_equity=round(total_equity, 2),
                ic_revenue=round(ic_revenue, 2),
                ic_costs=round(ic_costs, 2),
                ic_receivables=round(ic_receivables, 2),
                ic_payables=round(ic_payables, 2),
                currency=entity_currency,
            )
            # Store as dict for JSON-serialisability across state
            entity_statements[str(entity_code)] = stmt.model_dump()

        return entity_statements

    # ──────────────────────────────────────────────────────────────────────
    # Legacy IC-only format handler
    # ──────────────────────────────────────────────────────────────────────

    def _run_legacy_ic_only(
        self,
        state: dict,
        df: pd.DataFrame,
        batch_id: str,
        period: str,
        scenario: str,
    ) -> dict:
        """Process legacy IC-only format — preserves existing behaviour."""
        # Validate schema
        schema_ok, missing_cols = _validate_csv_columns(df, LEGACY_REQUIRED_COLUMNS)
        if not schema_ok:
            error_msg = f"Schema validation failed — missing columns: {missing_cols}"
            logger.error(error_msg)
            state.setdefault("errors", []).append(error_msg)
            ingestion_result = {
                "clean_data": pd.DataFrame(),
                "non_ic_data": pd.DataFrame(),
                "entity_statements": {},
                "all_lines": pd.DataFrame(),
                "quality_score": 0.0,
                "anomalies": [],
                "rejected_rows": [],
                "status": "FAIL",
                "file_format": "IC_ONLY",
                "batch_id": batch_id,
                "period": period,
                "scenario": scenario,
                "total_lines": 0,
                "ic_lines": 0,
                "non_ic_lines": 0,
                "entities_present": [],
                "missing_columns": missing_cols,
            }
            state["ingestion_result"] = ingestion_result
            return state

        issues: list[str] = []
        unknown_entities = self.check_entity_codes(df)
        unknown_currencies = self.check_currency_codes(df)
        duplicates = self.detect_duplicates(df)
        anomalies = self.flag_anomalies(df)

        if unknown_entities:
            issues.append(f"Unknown entities: {unknown_entities}")
        if unknown_currencies:
            issues.append(f"Unknown currencies: {unknown_currencies}")
        if duplicates:
            issues.append(f"Duplicate txn_ids: {duplicates}")
        for a in anomalies:
            issues.append(f"Anomaly [{a['type']}] txn={a.get('txn_id', '')}: {a['description']}")

        # Filter clean data
        rejected_rows: list[dict] = []
        clean_df = df.copy()

        if duplicates:
            mask_dup = df["txn_id"].isin(duplicates)
            rejected_rows.extend(df[mask_dup].to_dict(orient="records"))
            clean_df = clean_df[~clean_df["txn_id"].isin(duplicates)]

        if unknown_entities:
            mask_ent = (
                clean_df["seller_entity"].isin(unknown_entities)
                | clean_df["buyer_entity"].isin(unknown_entities)
            )
            rejected_rows.extend(clean_df[mask_ent].to_dict(orient="records"))
            clean_df = clean_df[~mask_ent]

        quality_score = self.compute_quality_score(clean_df, issues)

        if len(unknown_entities) > 3 or duplicates:
            status = "FAIL"
        elif quality_score < 85:
            status = "PARTIAL"
        else:
            status = "PASS"

        if quality_score < 85:
            escalation = {
                "type": "DATA_QUALITY",
                "batch_id": batch_id,
                "quality_score": quality_score,
                "reason": f"Data quality score {quality_score:.1f} below threshold 85",
                "timestamp": datetime.utcnow().isoformat(),
            }
            state.setdefault("escalations", []).append(escalation)

        ingestion_result = {
            "batch_id": batch_id,
            "file_format": "IC_ONLY",
            "clean_data": clean_df,
            "non_ic_data": pd.DataFrame(),
            "entity_statements": {},
            "all_lines": clean_df,
            "quality_score": quality_score,
            "anomalies": anomalies,
            "rejected_rows": rejected_rows,
            "status": status,
            "total_lines": len(df),
            "ic_lines": len(clean_df),
            "non_ic_lines": 0,
            "entities_present": sorted(
                set(clean_df["seller_entity"].dropna().unique().tolist()) |
                set(clean_df["buyer_entity"].dropna().unique().tolist())
            ),
            "period": period,
            "scenario": scenario,
            "total_rows": len(df),
            "clean_rows": len(clean_df),
            "unknown_entities": unknown_entities,
            "unknown_currencies": unknown_currencies,
            "duplicates": duplicates,
            "issues": issues,
        }

        state["ingestion_result"] = ingestion_result

        logger.info(
            "DataIngestionAgent (IC_ONLY) complete: status=%s quality=%.1f clean_rows=%d",
            status, quality_score, len(clean_df),
        )

        try:
            with self.db._connect() as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO batch_runs
                        (batch_id, period, scenario, status, quality_score)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (batch_id, period, scenario, status, quality_score),
                )
                conn.commit()
        except Exception as db_exc:
            logger.warning("Failed to persist batch run: %s", db_exc)

        return state

    # ──────────────────────────────────────────────────────────────────────
    # Validation helpers (legacy format)
    # ──────────────────────────────────────────────────────────────────────

    def validate_schema(self, df: pd.DataFrame) -> tuple[bool, list[str]]:
        """Check required columns are present (legacy format)."""
        try:
            return _validate_csv_columns(df, LEGACY_REQUIRED_COLUMNS)
        except Exception as exc:
            return (False, [f"Schema check error: {exc}"])

    def check_entity_codes(self, df: pd.DataFrame) -> list[str]:
        """Return list of unknown entity codes found in seller_entity or buyer_entity."""
        try:
            seller_codes = set(df["seller_entity"].dropna().astype(str).unique())
            buyer_codes = set(df["buyer_entity"].dropna().astype(str).unique())
            all_codes = seller_codes | buyer_codes
            unknown = sorted(all_codes - VALID_ENTITY_CODES)
            return unknown
        except Exception as exc:
            logger.warning("check_entity_codes failed: %s", exc)
            return []

    def check_currency_codes(self, df: pd.DataFrame) -> list[str]:
        """Return list of unknown currency codes."""
        try:
            seller_ccys = set(df["seller_currency"].dropna().astype(str).str.upper().unique())
            buyer_ccys = set(df["buyer_currency"].dropna().astype(str).str.upper().unique())
            all_ccys = seller_ccys | buyer_ccys
            unknown = sorted(all_ccys - VALID_CURRENCIES)
            return unknown
        except Exception as exc:
            logger.warning("check_currency_codes failed: %s", exc)
            return []

    def detect_duplicates(self, df: pd.DataFrame) -> list[str]:
        """Return duplicate txn_ids."""
        try:
            return _detect_duplicate_txn_ids(df, "txn_id")
        except Exception as exc:
            logger.warning("detect_duplicates failed: %s", exc)
            return []

    def flag_anomalies(self, df: pd.DataFrame) -> list[dict]:
        """Return anomaly dicts for legacy format."""
        anomalies: list[dict] = []
        try:
            for _, row in df.iterrows():
                txn_id = str(row.get("txn_id", ""))
                try:
                    seller_amt = float(row.get("seller_amount", 0) or 0)
                    buyer_amt = float(row.get("buyer_amount", 0) or 0)
                except (TypeError, ValueError):
                    seller_amt = 0.0
                    buyer_amt = 0.0

                if seller_amt == 0 and buyer_amt == 0:
                    anomalies.append({
                        "txn_id": txn_id,
                        "type": "ZERO_AMOUNTS",
                        "description": "Both seller_amount and buyer_amount are zero",
                    })

                seller = str(row.get("seller_entity", ""))
                buyer = str(row.get("buyer_entity", ""))
                if seller and buyer and seller == buyer:
                    anomalies.append({
                        "txn_id": txn_id,
                        "type": "SELF_TRADE",
                        "description": f"Seller and buyer are the same entity: {seller}",
                    })

                if abs(seller_amt) > 1_000_000_000 or abs(buyer_amt) > 1_000_000_000:
                    anomalies.append({
                        "txn_id": txn_id,
                        "type": "EXTREME_AMOUNT",
                        "description": f"Amount exceeds 1 billion threshold: seller={seller_amt}, buyer={buyer_amt}",
                    })

                if seller_amt < 0 or buyer_amt < 0:
                    anomalies.append({
                        "txn_id": txn_id,
                        "type": "NEGATIVE_AMOUNT",
                        "description": f"Negative amount detected: seller={seller_amt}, buyer={buyer_amt}",
                    })

        except Exception as exc:
            logger.warning("flag_anomalies failed: %s", exc)
        return anomalies

    def compute_quality_score(self, df: pd.DataFrame, issues: list) -> float:
        """Compute 0-100 quality score."""
        try:
            return _compute_data_quality_score(df, issues)
        except Exception as exc:
            logger.warning("compute_quality_score failed: %s", exc)
            return 0.0

    # ──────────────────────────────────────────────────────────────────────
    # Sample data generator — full financial statement format
    # ──────────────────────────────────────────────────────────────────────

    def _generate_sample_data(self, period: str, scenario: str) -> pd.DataFrame:
        """
        Generate 120+ rows of realistic full financial statement data
        covering all 8 entities with IC and Non-IC lines.
        """
        rows = []
        line_counter = 1

        def nxt() -> str:
            nonlocal line_counter
            lid = f"GEN-{line_counter:04d}"
            line_counter += 1
            return lid

        # Entity config: code, currency, non_ic revenues, cogs_scale, opex_scale
        entities = [
            ("HCG-UK", "GBP", [-18500000, -9200000, -3400000, -1800000], [8900000, 3200000, 2100000], [1450000, 2300000, 980000]),
            ("HCG-DE", "EUR", [-14800000, -7600000, -4200000], [7200000, 2800000], [1600000, 1900000]),
            ("HCG-US", "USD", [-22000000, -11500000, -5200000, -3100000], [10500000, 4800000, 1900000], [2400000, 3100000]),
            ("HCG-SG", "SGD", [-18000000, -8500000, -4200000], [9200000, 2800000], [1900000, 2400000]),
            ("HCG-FR", "EUR", [-12500000, -6200000, -2100000], [6800000, 2400000], [1300000, 1600000]),
            ("HCG-NL", "EUR", [-9800000, -5400000, -3100000], [5200000, 1800000], [1200000, 1500000]),
            ("HCG-AU", "AUD", [-16500000, -7800000, -3200000], [8900000, 2600000], [1800000, 2100000]),
            ("SHARED", "GBP", [-800000, -600000, -400000], [350000], [280000, 120000]),
        ]

        account_categories = ["Revenue", "COGS", "COGS", "OpEx", "OpEx"]

        for entity_code, currency, revenues, cogs_list, opex_list in entities:
            # Non-IC Revenue lines
            for i, amt in enumerate(revenues):
                rows.append({
                    "line_id": nxt(),
                    "entity_code": entity_code,
                    "account_code": f"REV-{i+1:03d}",
                    "account_description": f"External Revenue Line {i+1}",
                    "account_type": "P&L",
                    "account_category": "Revenue",
                    "is_intercompany": False,
                    "icp_entity": "",
                    "rule_code": "",
                    "flow": "F00",
                    "amount": amt,
                    "currency": currency,
                    "period": period,
                    "scenario": scenario,
                })

            # Non-IC COGS lines
            for i, amt in enumerate(cogs_list):
                rows.append({
                    "line_id": nxt(),
                    "entity_code": entity_code,
                    "account_code": f"COGS-{i+1:03d}",
                    "account_description": f"Cost of Goods Sold {i+1}",
                    "account_type": "P&L",
                    "account_category": "COGS",
                    "is_intercompany": False,
                    "icp_entity": "",
                    "rule_code": "",
                    "flow": "F00",
                    "amount": amt,
                    "currency": currency,
                    "period": period,
                    "scenario": scenario,
                })

            # Non-IC OpEx lines
            for i, amt in enumerate(opex_list):
                rows.append({
                    "line_id": nxt(),
                    "entity_code": entity_code,
                    "account_code": f"OPEX-{i+1:03d}",
                    "account_description": f"Operating Expense {i+1}",
                    "account_type": "P&L",
                    "account_category": "OpEx",
                    "is_intercompany": False,
                    "icp_entity": "",
                    "rule_code": "",
                    "flow": "F00",
                    "amount": amt,
                    "currency": currency,
                    "period": period,
                    "scenario": scenario,
                })

            # Non-IC BS lines
            cash_amt = abs(revenues[0]) * 0.15
            ppe_amt = abs(revenues[0]) * 1.5
            rows.append({
                "line_id": nxt(),
                "entity_code": entity_code,
                "account_code": "BS-CASH",
                "account_description": "Cash and Cash Equivalents",
                "account_type": "BS",
                "account_category": "Assets",
                "is_intercompany": False,
                "icp_entity": "",
                "rule_code": "",
                "flow": "F00",
                "amount": cash_amt,
                "currency": currency,
                "period": period,
                "scenario": scenario,
            })
            rows.append({
                "line_id": nxt(),
                "entity_code": entity_code,
                "account_code": "BS-PPE",
                "account_description": "Property Plant and Equipment",
                "account_type": "BS",
                "account_category": "Assets",
                "is_intercompany": False,
                "icp_entity": "",
                "rule_code": "",
                "flow": "F00",
                "amount": ppe_amt,
                "currency": currency,
                "period": period,
                "scenario": scenario,
            })
            rows.append({
                "line_id": nxt(),
                "entity_code": entity_code,
                "account_code": "BS-LIB",
                "account_description": "Trade Payables",
                "account_type": "BS",
                "account_category": "Liabilities",
                "is_intercompany": False,
                "icp_entity": "",
                "rule_code": "",
                "flow": "F00",
                "amount": -abs(revenues[0]) * 0.12,
                "currency": currency,
                "period": period,
                "scenario": scenario,
            })

        # IC bilateral pairs: seller has IC revenue, buyer has IC cost
        ic_pairs = [
            # (seller, buyer, amount, seller_ccy, buyer_ccy, rule, with_mismatch, is_fx_diff)
            ("HCG-UK", "HCG-DE", 5000000, "GBP", "GBP", "IC-001", False, False),
            ("HCG-UK", "HCG-AU", 1200000, "GBP", "GBP", "IC-004", False, False),
            ("HCG-UK", "HCG-US", 2800000, "GBP", "GBP", "IC-005", False, False),
            ("HCG-UK", "HCG-SG", 4250000, "GBP", "GBP", "IC-001", True, False),    # small mismatch
            ("HCG-DE", "HCG-FR", 3500000, "EUR", "EUR", "IC-001", False, False),
            ("HCG-DE", "HCG-NL", 2250000, "EUR", "EUR", "IC-001", True, False),    # small mismatch
            ("HCG-US", "HCG-AU", 2600000, "USD", "USD", "IC-001", False, False),
            ("HCG-SG", "HCG-AU", 1500000, "SGD", "SGD", "IC-001", False, False),
            # FX diff pair: GBP seller, USD buyer
            ("SHARED", "HCG-UK", 800000, "GBP", "GBP", "IC-004", False, False),
            ("SHARED", "HCG-DE", 650000, "EUR", "EUR", "IC-004", False, False),
            ("SHARED", "HCG-FR", 420000, "EUR", "EUR", "IC-004", False, False),
            ("SHARED", "HCG-NL", 380000, "EUR", "EUR", "IC-004", False, False),
            ("SHARED", "HCG-SG", 720000, "SGD", "SGD", "IC-004", False, False),
            # Cross-currency IC pair
            ("HCG-UK", "HCG-FR", 850000, "GBP", "EUR", "IC-005", False, True),    # FX diff
        ]

        for seller, buyer, amt, s_ccy, b_ccy, rule, mismatch, fx_diff in ic_pairs:
            # Seller: IC revenue (negative)
            rows.append({
                "line_id": nxt(),
                "entity_code": seller,
                "account_code": f"IC-REV-{nxt()}",
                "account_description": f"IC Revenue to {buyer}",
                "account_type": "P&L",
                "account_category": "Revenue",
                "is_intercompany": True,
                "icp_entity": buyer,
                "rule_code": rule,
                "flow": "F00",
                "amount": -amt,
                "currency": s_ccy,
                "period": period,
                "scenario": scenario,
            })
            # IC receivable in seller BS
            rows.append({
                "line_id": nxt(),
                "entity_code": seller,
                "account_code": f"IC-REC-{nxt()}",
                "account_description": f"IC Receivable from {buyer}",
                "account_type": "BS",
                "account_category": "Assets",
                "is_intercompany": True,
                "icp_entity": buyer,
                "rule_code": "IC-002",
                "flow": "F00",
                "amount": amt,
                "currency": s_ccy,
                "period": period,
                "scenario": scenario,
            })

            # Buyer: IC cost (positive) — with optional mismatch or FX diff
            buyer_amt = amt
            buyer_ccy = b_ccy
            if mismatch:
                buyer_amt = round(amt * 1.012, 0)   # 1.2% gap
            if fx_diff:
                buyer_ccy = b_ccy   # different currency already set

            rows.append({
                "line_id": nxt(),
                "entity_code": buyer,
                "account_code": f"IC-COST-{nxt()}",
                "account_description": f"IC Cost from {seller}",
                "account_type": "P&L",
                "account_category": "COGS",
                "is_intercompany": True,
                "icp_entity": seller,
                "rule_code": rule,
                "flow": "F00",
                "amount": buyer_amt,
                "currency": buyer_ccy,
                "period": period,
                "scenario": scenario,
            })
            # IC payable in buyer BS
            rows.append({
                "line_id": nxt(),
                "entity_code": buyer,
                "account_code": f"IC-PAY-{nxt()}",
                "account_description": f"IC Payable to {seller}",
                "account_type": "BS",
                "account_category": "Liabilities",
                "is_intercompany": True,
                "icp_entity": seller,
                "rule_code": "IC-002",
                "flow": "F00",
                "amount": -buyer_amt,
                "currency": buyer_ccy,
                "period": period,
                "scenario": scenario,
            })

        return pd.DataFrame(rows)
