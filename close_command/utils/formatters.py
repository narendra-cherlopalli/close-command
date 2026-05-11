"""
Formatting utilities for Close Command output.
"""

from __future__ import annotations


def format_amount(amount: float, currency: str = "USD") -> str:
    """Return a human-readable amount string, e.g. 'USD 1,234,567.89'."""
    try:
        formatted = f"{amount:,.2f}"
        return f"{currency.upper()} {formatted}"
    except Exception as exc:
        return f"{currency} {amount}"


def format_pct(value: float) -> str:
    """Return a percentage string, e.g. '1.23%'."""
    try:
        return f"{value:.2f}%"
    except Exception:
        return f"{value}%"


def format_gate_status_color(status: str) -> str:
    """Return a hex colour code representing the gate status.

    Colour mapping:
        APPROVED   -> #28a745  (green)
        PENDING    -> #ffc107  (amber)
        REJECTED   -> #dc3545  (red)
        ESCALATED  -> #17a2b8  (blue)
        BLOCKED    -> #dc3545  (red)
        REVIEW     -> #ffc107  (amber)
        *default*  -> #6c757d  (grey)
    """
    try:
        mapping: dict[str, str] = {
            "APPROVED": "#28a745",
            "PENDING": "#ffc107",
            "REJECTED": "#dc3545",
            "ESCALATED": "#17a2b8",
            "BLOCKED": "#dc3545",
            "REVIEW": "#ffc107",
        }
        return mapping.get(status.upper(), "#6c757d")
    except Exception:
        return "#6c757d"


def format_match_status_color(status: str) -> str:
    """Return a hex colour code representing the match status.

    Colour mapping:
        Matched     -> #28a745  (green)
        Not Matched -> #dc3545  (red)
        FX Diff     -> #ffc107  (amber)
        Exception   -> #fd7e14  (orange)
        *default*   -> #6c757d  (grey)
    """
    try:
        mapping: dict[str, str] = {
            "Matched": "#28a745",
            "Not Matched": "#dc3545",
            "FX Diff": "#ffc107",
            "Exception": "#fd7e14",
        }
        return mapping.get(status, "#6c757d")
    except Exception:
        return "#6c757d"


def format_recommendation_badge(rec: str) -> str:
    """Return a coloured text label for the validation recommendation.

    Labels:
        APPROVE -> [✔ APPROVE]  (green ANSI or plain text)
        REVIEW  -> [⚠ REVIEW]   (amber)
        BLOCK   -> [✘ BLOCK]    (red)
    """
    try:
        mapping: dict[str, str] = {
            "APPROVE": "[ APPROVE ]",
            "REVIEW": "[ REVIEW  ]",
            "BLOCK": "[  BLOCK  ]",
        }
        return mapping.get(rec.upper(), f"[ {rec.upper()} ]")
    except Exception:
        return f"[ {rec} ]"


def jlf_row(entry: dict) -> str:
    """Return a semicolon-delimited JLF (Journal Line Format) string for one entry.

    Field order:
        txn_id; period; scenario; seller; buyer; rule_code; account; flow; icp;
        custom3_ccy; dr_cr; amount; amount_usd; value; audit_code;
        entity_method; pcon; pown; gate_status; computed_by; computed_at
    """
    try:
        fields = [
            str(entry.get("txn_id", "")),
            str(entry.get("period", "")),
            str(entry.get("scenario", "")),
            str(entry.get("seller", "")),
            str(entry.get("buyer", "")),
            str(entry.get("rule_code", "")),
            str(entry.get("account", "")),
            str(entry.get("flow", "F00")),
            str(entry.get("icp", "")),
            str(entry.get("custom3_ccy", "USD")),
            str(entry.get("dr_cr", "")),
            str(entry.get("amount", 0.0)),
            str(entry.get("amount_usd", 0.0)),
            str(entry.get("value", "[Elimination]")),
            str(entry.get("audit_code", "")),
            str(entry.get("entity_method", "GLOBAL")),
            str(entry.get("pcon", 100.0)),
            str(entry.get("pown", 100.0)),
            str(entry.get("gate_status", "PENDING")),
            str(entry.get("computed_by", "Elimination Agent")),
            str(entry.get("computed_at", "")),
        ]
        return ";".join(fields)
    except Exception as exc:
        return f"ERROR_FORMATTING_JLF_ROW;{exc}"
