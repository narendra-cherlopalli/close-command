"""
LangGraph state definition for Close Command pipeline.
"""

from __future__ import annotations

from typing import TypedDict, Optional, Any
from datetime import datetime


class CloseCommandState(TypedDict):
    batch_id: str
    period: str
    scenario: str
    raw_data: Any
    source_file: str
    ingestion_result: Optional[dict]
    matching_result: Optional[dict]
    elimination_result: Optional[dict]
    validation_result: Optional[dict]
    review_result: Optional[dict]
    output_result: Optional[dict]
    consolidation_result: Optional[dict]
    current_agent: str
    errors: list
    escalations: list
    human_review_required: bool
    period_close_ready: bool
    overall_status: str
    started_at: str
    last_updated: str


def create_initial_state(
    batch_id: str,
    period: str,
    scenario: str,
    raw_data: Any = None,
    source_file: str = "",
) -> CloseCommandState:
    """Create a fresh initial state for a new pipeline run."""
    now = datetime.utcnow().isoformat()
    return CloseCommandState(
        batch_id=batch_id,
        period=period,
        scenario=scenario,
        raw_data=raw_data,
        source_file=source_file,
        ingestion_result=None,
        matching_result=None,
        elimination_result=None,
        validation_result=None,
        review_result=None,
        output_result=None,
        consolidation_result=None,
        current_agent="",
        errors=[],
        escalations=[],
        human_review_required=False,
        period_close_ready=False,
        overall_status="RUNNING",
        started_at=now,
        last_updated=now,
    )


def update_state_timestamp(state: CloseCommandState) -> CloseCommandState:
    """Return a copy of state with last_updated set to now."""
    updated = dict(state)
    updated["last_updated"] = datetime.utcnow().isoformat()
    return CloseCommandState(**updated)
