from pydantic import BaseModel, Field
from typing import Literal
from datetime import datetime


class ReviewDecision(BaseModel):
    txn_id: str
    decision: Literal["Approved", "Rejected", "Escalated"]
    reviewer_name: str
    reviewer_role: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    comment: str
    gate_status: str
    batch_id: str
    period: str
