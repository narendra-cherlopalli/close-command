"""
Data validation utilities for Close Command.
"""

from __future__ import annotations
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd


def validate_csv_columns(df: "pd.DataFrame", required_cols: list[str]) -> tuple[bool, list[str]]:
    """Check that all required columns exist in the dataframe.

    Returns:
        (True, [])               — all columns present
        (False, [missing, ...])  — list of missing column names
    """
    try:
        existing = set(df.columns.tolist())
        missing = [col for col in required_cols if col not in existing]
        return (len(missing) == 0, missing)
    except Exception as exc:
        return (False, [f"ERROR: {exc}"])


def validate_entity_codes(
    df: "pd.DataFrame", entity_col: str
) -> tuple[bool, list[str]]:
    """Validate that all values in entity_col are known entity codes.

    Imports VALID_ENTITY_CODES lazily to avoid circular imports at module load.

    Returns:
        (True, [])                — all codes valid
        (False, [invalid, ...])   — list of invalid/unknown codes found
    """
    try:
        from data.entities import VALID_ENTITY_CODES

        if entity_col not in df.columns:
            return (False, [f"Column '{entity_col}' not found in dataframe"])

        unique_codes: set[str] = set(df[entity_col].dropna().astype(str).unique())
        invalid = sorted(unique_codes - VALID_ENTITY_CODES)
        return (len(invalid) == 0, invalid)
    except Exception as exc:
        return (False, [f"ERROR: {exc}"])


def validate_currency_codes(
    df: "pd.DataFrame", currency_col: str
) -> tuple[bool, list[str]]:
    """Validate that all values in currency_col are supported currency codes.

    Returns:
        (True, [])                — all codes valid
        (False, [invalid, ...])   — list of unsupported currency codes found
    """
    try:
        from data.fx_rates import VALID_CURRENCIES

        if currency_col not in df.columns:
            return (False, [f"Column '{currency_col}' not found in dataframe"])

        unique_ccys: set[str] = set(
            df[currency_col].dropna().astype(str).str.upper().unique()
        )
        invalid = sorted(unique_ccys - VALID_CURRENCIES)
        return (len(invalid) == 0, invalid)
    except Exception as exc:
        return (False, [f"ERROR: {exc}"])


def detect_duplicate_txn_ids(df: "pd.DataFrame", txn_id_col: str) -> list[str]:
    """Return a list of txn_id values that appear more than once in the dataframe.

    Returns an empty list if no duplicates or if the column is missing.
    """
    try:
        if txn_id_col not in df.columns:
            return []
        counts = df[txn_id_col].dropna().astype(str).value_counts()
        duplicates = counts[counts > 1].index.tolist()
        return sorted(duplicates)
    except Exception:
        return []


def compute_data_quality_score(df: "pd.DataFrame", issues: list[str]) -> float:
    """Compute a 0–100 data quality score for a dataframe.

    Scoring breakdown:
        - Start at 100.0
        - Deduct 5 points per issue in the issues list (max 50 deduction)
        - Deduct 1 point per 1% of null values across all cells (max 30 deduction)
        - Deduct 10 points if the dataframe is empty
        - Minimum score is 0.0
    """
    try:
        if df is None or len(df) == 0:
            return 0.0

        score = 100.0

        # Deduct for issues
        issue_deduction = min(len(issues) * 5.0, 50.0)
        score -= issue_deduction

        # Deduct for null/missing values
        total_cells = df.shape[0] * df.shape[1]
        if total_cells > 0:
            null_count = df.isnull().sum().sum()
            null_pct = (null_count / total_cells) * 100
            null_deduction = min(null_pct, 30.0)
            score -= null_deduction

        return max(round(score, 2), 0.0)
    except Exception:
        return 0.0


def is_valid_period(period: str) -> bool:
    """Return True if period matches YYYY-MM or YYYYMM format.

    Valid examples: '2024-03', '202403'
    Invalid examples: '24-03', '2024/03', 'March 2024'
    """
    try:
        period = period.strip()
        # YYYY-MM
        if re.fullmatch(r"\d{4}-\d{2}", period):
            year, month = period.split("-")
            return 1 <= int(month) <= 12
        # YYYYMM
        if re.fullmatch(r"\d{6}", period):
            year = period[:4]
            month = period[4:]
            return 1 <= int(month) <= 12
        return False
    except Exception:
        return False
