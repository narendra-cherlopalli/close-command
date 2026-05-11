from pydantic import BaseModel, Field
from typing import Literal, Optional
from datetime import datetime


class BalanceResult(BaseModel):
    is_balanced: bool
    total_debits: float
    total_credits: float
    difference: float
    entries_checked: int


class ContinuationResult(BaseModel):
    passed: bool
    structure_changed: bool
    methods_changed: bool
    fx_rates_current: bool
    issues: list[str]


class ValidationResult(BaseModel):
    batch_id: str
    balance_check: bool
    continuation_check: bool
    policy_check: bool
    prior_period_deviation: float
    validation_score: float
    recommendation: Literal["APPROVE", "REVIEW", "BLOCK"]
    issues: list[str]
    balance_result: Optional[dict] = None
    continuation_result: Optional[dict] = None
    validated_at: datetime = Field(default_factory=datetime.utcnow)
