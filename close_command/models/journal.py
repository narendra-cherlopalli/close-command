from pydantic import BaseModel, Field
from typing import Literal, Optional
from datetime import datetime
import uuid


class JournalEntry(BaseModel):
    txn_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    seller: str
    buyer: str
    rule_code: str
    account: str
    flow: str = "F00"
    icp: str = ""
    custom3_ccy: str = "USD"
    dr_cr: Literal["Dr", "Cr"]
    amount: float
    amount_usd: float
    value: str = "[Elimination]"
    audit_code: str
    period: str
    scenario: str
    entity_method: str = "GLOBAL"
    pcon: float = 100.0
    pown: float = 100.0
    computed_by: str = "Elimination Agent"
    computed_at: datetime = Field(default_factory=datetime.utcnow)
    gate_status: str = "PENDING"
    nci_applicable: bool = False
