from pydantic import BaseModel, Field
from typing import Literal, Optional
from datetime import datetime


class MatchResult(BaseModel):
    txn_id: str
    seller_entity: str
    buyer_entity: str
    rule_code: str
    account: str
    seller_amount: float
    buyer_amount: float
    seller_currency: str
    buyer_currency: str
    seller_usd: float
    buyer_usd: float
    gap_usd: float
    gap_pct: float
    match_status: Literal["Matched", "Not Matched", "FX Diff", "Exception"]
    root_cause: Optional[str] = None
    rag_sources: Optional[list] = None
    period: str
    scenario: str
    batch_id: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class MatchSummary(BaseModel):
    batch_id: str
    total_pairs: int
    matched_count: int
    not_matched_count: int
    fx_diff_count: int
    exception_count: int
    exception_pct: float
    total_seller_usd: float
    total_buyer_usd: float
    total_gap_usd: float
    period: str
    scenario: str
