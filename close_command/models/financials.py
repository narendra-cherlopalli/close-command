"""
Financial statement data models for Close Command.
Supports full entity-level financial statements with IC and Non-IC lines.
"""

from pydantic import BaseModel, Field
from typing import Literal, Optional
from datetime import datetime, timezone


class FinancialLine(BaseModel):
    """One line from an entity financial statement."""
    line_id: str
    entity_code: str
    account_code: str
    account_description: str
    account_type: Literal["P&L", "BS"]          # P&L or Balance Sheet
    account_category: str                         # Revenue, COGS, OpEx, Assets, Liabilities, Equity
    is_intercompany: bool                         # True = IC line, False = Non-IC
    icp_entity: Optional[str] = None             # Counterpart entity code (IC lines only)
    rule_code: Optional[str] = None              # Elimination rule (IC lines only)
    flow: str = "F00"
    amount: float                                 # Local currency amount (signed: positive=Dr, negative=Cr)
    currency: str
    amount_usd: float = 0.0                      # Computed by ingestion agent
    period: str
    scenario: str
    batch_id: str


class EntityStatement(BaseModel):
    """Complete financial statement for one entity in one period."""
    entity_code: str
    period: str
    scenario: str
    batch_id: str
    lines: list[FinancialLine]
    total_revenue: float = 0.0
    total_cogs: float = 0.0
    total_opex: float = 0.0
    total_assets: float = 0.0
    total_liabilities: float = 0.0
    total_equity: float = 0.0
    ic_revenue: float = 0.0
    ic_costs: float = 0.0
    ic_receivables: float = 0.0
    ic_payables: float = 0.0
    currency: str = "USD"


class ConsolidatedStatement(BaseModel):
    """Group consolidated P&L and Balance Sheet after eliminations."""
    period: str
    scenario: str
    batch_id: str
    # P&L
    gross_revenue: float = 0.0           # Sum of all entity revenues (pre-elim)
    ic_revenue_eliminated: float = 0.0   # IC revenue eliminated
    net_revenue: float = 0.0             # After elimination
    gross_cogs: float = 0.0
    ic_cogs_eliminated: float = 0.0
    net_cogs: float = 0.0
    gross_opex: float = 0.0
    net_opex: float = 0.0
    ebit: float = 0.0
    nci_share: float = 0.0
    group_profit: float = 0.0
    # Balance Sheet
    gross_assets: float = 0.0
    ic_assets_eliminated: float = 0.0
    net_assets: float = 0.0
    gross_liabilities: float = 0.0
    ic_liabilities_eliminated: float = 0.0
    net_liabilities: float = 0.0
    net_equity: float = 0.0
    # Proof
    balance_sheet_balanced: bool = False
    entity_contributions: dict = Field(default_factory=dict)
    elimination_summary: dict = Field(default_factory=dict)
    # ISO string — datetime objects are not msgpack-serializable in LangGraph checkpoints
    generated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
