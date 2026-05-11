"""
LangGraph orchestrator for Close Command financial close pipeline.
Wires all six agents into a stateful graph with HITL review gate.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import uuid
from datetime import datetime

from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt

# Try the sqlite checkpointer (requires langgraph-checkpoint-sqlite package);
# fall back to in-memory checkpointer if not installed.
try:
    from langgraph.checkpoint.sqlite import SqliteSaver as _SqliteSaver
    _SQLITE_AVAILABLE = True
except ImportError:
    _SQLITE_AVAILABLE = False
    from langgraph.checkpoint.memory import MemorySaver as _MemorySaver

from close_command.orchestrator.state import (
    CloseCommandState,
    create_initial_state,
    update_state_timestamp,
)
from close_command.agents.ingestion_agent import DataIngestionAgent
from close_command.agents.matching_agent import MatchingAgent
from close_command.agents.elimination_agent import EliminationAgent
from close_command.agents.validation_agent import ValidationAgent
from close_command.agents.review_agent import ReviewAgent
from close_command.agents.output_agent import JournalOutputAgent
from close_command.agents.consolidation_agent import ConsolidationAgent
from close_command.database.persistence import CloseCommandDB

logger = logging.getLogger(__name__)

try:
    from close_command.rag.vectorstore import CloseCommandVectorStore
    from close_command.rag.retriever import CloseCommandRetriever
    from close_command.rag.indexer import CloseCommandIndexer
    _RAG_AVAILABLE = True
except ImportError as _rag_import_err:
    _RAG_AVAILABLE = False
    CloseCommandVectorStore = None  # type: ignore
    CloseCommandRetriever = None  # type: ignore
    CloseCommandIndexer = None  # type: ignore
    logger.warning("RAG components unavailable (chromadb not installed): %s", _rag_import_err)

# ──────────────────────────────────────────────────────────────────────
# Shared infrastructure (singletons per process)
# ──────────────────────────────────────────────────────────────────────

_db = CloseCommandDB("close_command.db")

if _RAG_AVAILABLE:
    _vectorstore = CloseCommandVectorStore()
    _retriever = CloseCommandRetriever(_vectorstore)
    _indexer = CloseCommandIndexer(_vectorstore)
else:
    _vectorstore = None
    _retriever = None  # agents will use their _NullRetriever fallback
    _indexer = None    # output agent will use its _NullIndexer fallback

# Agent instances
_ingestion_agent = DataIngestionAgent(db=_db)
_matching_agent = MatchingAgent(db=_db, retriever=_retriever)
_elimination_agent = EliminationAgent(db=_db, retriever=_retriever)
_validation_agent = ValidationAgent(db=_db, retriever=_retriever)
_review_agent = ReviewAgent(db=_db)
_output_agent = JournalOutputAgent(db=_db, indexer=_indexer)
_consolidation_agent = ConsolidationAgent(db=_db)


# Module-level cache: batch_id -> DataFrame
# DataFrames cannot be stored in LangGraph state (not msgpack serializable).
# The ingestion node reads raw data from here instead of state["raw_data"].
_RAW_DATA_CACHE: dict = {}


# ──────────────────────────────────────────────────────────────────────
# Node functions
# ──────────────────────────────────────────────────────────────────────

def _sanitize_for_checkpoint(obj):
    """
    Recursively convert non-serializable types so that LangGraph's msgpack
    checkpointer can serialize the state:
      - pandas DataFrame  → list of dicts
      - numpy scalar types → Python native int / float / bool
      - datetime objects  → ISO string
    """
    try:
        import pandas as pd
        import numpy as np

        if isinstance(obj, pd.DataFrame):
            return _sanitize_for_checkpoint(obj.to_dict(orient="records"))
        if isinstance(obj, pd.Series):
            return _sanitize_for_checkpoint(obj.tolist())
        if isinstance(obj, dict):
            return {k: _sanitize_for_checkpoint(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [_sanitize_for_checkpoint(i) for i in obj]
        # numpy scalar types
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.bool_):
            return bool(obj)
        if isinstance(obj, np.ndarray):
            return _sanitize_for_checkpoint(obj.tolist())
        # datetime
        if hasattr(obj, "isoformat"):
            return obj.isoformat()
        return obj
    except Exception:
        return obj


def _sanitize_state(state: dict) -> dict:
    """
    Sanitize the full state so every value is msgpack-serializable.
    Converts DataFrames, numpy types, and datetimes recursively.
    """
    import pandas as pd
    sanitized = dict(state)
    # Drop raw_data DataFrame — agents have already consumed it
    if isinstance(sanitized.get("raw_data"), pd.DataFrame):
        sanitized["raw_data"] = None
    # Sanitize all result dicts
    for key in (
        "ingestion_result", "matching_result", "elimination_result",
        "validation_result", "review_result", "output_result", "consolidation_result",
    ):
        if sanitized.get(key) is not None:
            sanitized[key] = _sanitize_for_checkpoint(sanitized[key])
    # Sanitize top-level lists
    for key in ("errors", "escalations"):
        if sanitized.get(key) is not None:
            sanitized[key] = _sanitize_for_checkpoint(sanitized[key])
    return sanitized


def ingest_node(state: CloseCommandState) -> CloseCommandState:
    """Run data ingestion and validation."""
    try:
        state = dict(state)
        state["current_agent"] = "Ingestion"
        batch_id = state.get("batch_id", "")
        logger.info("[ingest_node] batch_id=%s", batch_id)

        # Inject cached DataFrame (never stored in serializable state)
        if batch_id in _RAW_DATA_CACHE:
            state["raw_data"] = _RAW_DATA_CACHE.pop(batch_id)

        state = _ingestion_agent.run(state)
        state = _sanitize_state(state)   # strip any remaining DataFrames
        state = update_state_timestamp(state)
        return state
    except Exception as exc:
        logger.error("[ingest_node] failed: %s", exc)
        state = dict(state)
        state.setdefault("errors", []).append(f"ingest_node: {exc}")
        state["ingestion_result"] = state.get("ingestion_result") or {"status": "FAIL"}
        state = update_state_timestamp(state)
        return state


def match_node(state: CloseCommandState) -> CloseCommandState:
    """Run bilateral IC matching."""
    try:
        state = dict(state)
        state["current_agent"] = "Matching"
        logger.info("[match_node] batch_id=%s", state.get("batch_id"))
        state = _matching_agent.run(state)
        state = _sanitize_state(state)
        state = update_state_timestamp(state)
        return state
    except Exception as exc:
        logger.error("[match_node] failed: %s", exc)
        state = dict(state)
        state.setdefault("errors", []).append(f"match_node: {exc}")
        state = update_state_timestamp(state)
        return state


def eliminate_node(state: CloseCommandState) -> CloseCommandState:
    """Run elimination journal entry generation."""
    try:
        state = dict(state)
        state["current_agent"] = "Elimination"
        logger.info("[eliminate_node] batch_id=%s", state.get("batch_id"))
        state = _elimination_agent.run(state)
        state = _sanitize_state(state)
        state = update_state_timestamp(state)
        return state
    except Exception as exc:
        logger.error("[eliminate_node] failed: %s", exc)
        state = dict(state)
        state.setdefault("errors", []).append(f"eliminate_node: {exc}")
        state = update_state_timestamp(state)
        return state


def validate_node(state: CloseCommandState) -> CloseCommandState:
    """Run validation checks and scoring."""
    try:
        state = dict(state)
        state["current_agent"] = "Validation"
        logger.info("[validate_node] batch_id=%s", state.get("batch_id"))
        state = _validation_agent.run(state)
        state = _sanitize_state(state)
        state = update_state_timestamp(state)
        return state
    except Exception as exc:
        logger.error("[validate_node] failed: %s", exc)
        state = dict(state)
        state.setdefault("errors", []).append(f"validate_node: {exc}")
        state = update_state_timestamp(state)
        return state


def review_node(state: CloseCommandState) -> CloseCommandState:
    """
    Human-in-the-loop review gate.
    Calls review_agent.run() to prepare review cards, then interrupts
    for human input via LangGraph interrupt().
    """
    try:
        state = dict(state)
        state["current_agent"] = "Review"
        logger.info("[review_node] batch_id=%s — preparing review cards", state.get("batch_id"))

        # Prepare review items
        state = _review_agent.run(state)
        state = update_state_timestamp(state)

        # HITL interrupt — execution pauses here until human provides input
        review_result = state.get("review_result", {})
        pending_items = review_result.get("pending_items", [])

        if pending_items:
            logger.info(
                "[review_node] Interrupting for human review — %d items pending",
                len(pending_items),
            )
            human_input = interrupt({
                "action": "review_required",
                "batch_id": state.get("batch_id"),
                "period": state.get("period"),
                "pending_count": len(pending_items),
                "pending_items": pending_items[:10],  # Send first 10 for context
                "close_readiness": review_result.get("close_readiness", {}),
                "message": (
                    f"Human review required for batch {state.get('batch_id')}. "
                    f"{len(pending_items)} item(s) need approval. "
                    "Provide decisions via record_decision() then resume."
                ),
            })

            # Process human input if provided
            if human_input and isinstance(human_input, dict):
                decisions = human_input.get("decisions", [])
                for dec in decisions:
                    try:
                        _review_agent.record_decision(
                            txn_id=dec.get("txn_id", ""),
                            decision=dec.get("decision", "Escalated"),
                            reviewer_name=dec.get("reviewer_name", "Human Reviewer"),
                            reviewer_role=dec.get("reviewer_role", "Controller"),
                            comment=dec.get("comment", ""),
                            batch_id=state.get("batch_id", ""),
                            period=state.get("period", ""),
                        )
                    except Exception as dec_exc:
                        logger.warning("Failed to record decision: %s", dec_exc)

                # Reload state after decisions
                state = _review_agent.run(state)
                state = update_state_timestamp(state)

        return state

    except Exception as exc:
        logger.error("[review_node] failed: %s", exc)
        state = dict(state)
        state.setdefault("errors", []).append(f"review_node: {exc}")
        state = update_state_timestamp(state)
        return state


def output_node(state: CloseCommandState) -> CloseCommandState:
    """Generate final journal output, audit trail, and consolidation proof."""
    try:
        state = dict(state)
        state["current_agent"] = "Output"
        logger.info("[output_node] batch_id=%s", state.get("batch_id"))
        state = _output_agent.run(state)
        state = _sanitize_state(state)   # strip bytes/numpy/DataFrames before checkpoint
        state = update_state_timestamp(state)
        return state
    except Exception as exc:
        logger.error("[output_node] failed: %s", exc)
        state = dict(state)
        state.setdefault("errors", []).append(f"output_node: {exc}")
        state["overall_status"] = "ERROR"
        state = update_state_timestamp(state)
        return state


def consolidate_node(state: CloseCommandState) -> CloseCommandState:
    """Run group consolidation: apply PCon%, eliminations, and produce consolidated statements."""
    state = dict(state)
    state["current_agent"] = "Consolidation"
    state = update_state_timestamp(state)
    try:
        state = _consolidation_agent.run(state)
        state["overall_status"] = "COMPLETE"
    except Exception as e:
        logger.error("[consolidate_node] failed: %s", e)
        state.setdefault("errors", []).append(f"Consolidation error: {str(e)}")
        state["overall_status"] = "ERROR"
    # Must sanitize — ConsolidatedStatement.model_dump() contains datetime fields
    state = _sanitize_state(state)
    state = update_state_timestamp(state)
    return state


def error_node(state: CloseCommandState) -> CloseCommandState:
    """Terminal error handler."""
    try:
        state = dict(state)
        state["current_agent"] = "Error"
        state["overall_status"] = "ERROR"
        errors = state.get("errors", [])
        logger.error("[error_node] Pipeline failed with %d error(s): %s", len(errors), errors)
        state = update_state_timestamp(state)
        return state
    except Exception as exc:
        logger.error("[error_node] internal error: %s", exc)
        return state


def escalate_node(state: CloseCommandState) -> CloseCommandState:
    """Terminal escalation handler."""
    try:
        state = dict(state)
        state["current_agent"] = "Escalate"
        state["overall_status"] = "ESCALATED"
        state["human_review_required"] = True
        escalations = state.get("escalations", [])
        logger.warning(
            "[escalate_node] Pipeline escalated with %d escalation(s): %s",
            len(escalations), [e.get("type") for e in escalations],
        )
        state = update_state_timestamp(state)
        return state
    except Exception as exc:
        logger.error("[escalate_node] internal error: %s", exc)
        return state


# ──────────────────────────────────────────────────────────────────────
# Edge condition functions
# ──────────────────────────────────────────────────────────────────────

def route_after_ingest(state: CloseCommandState) -> str:
    """Route to match or error based on ingestion status."""
    try:
        ingestion_result = state.get("ingestion_result", {})
        status = ingestion_result.get("status", "FAIL")
        errors = state.get("errors", [])

        if errors or status == "FAIL":
            logger.info("[route_after_ingest] -> error (status=%s)", status)
            return "error"

        logger.info("[route_after_ingest] -> match (status=%s)", status)
        return "match"
    except Exception as exc:
        logger.error("[route_after_ingest] routing error: %s", exc)
        return "error"


def route_after_match(state: CloseCommandState) -> str:
    """Route to eliminate or escalate based on matching result."""
    try:
        escalations = state.get("escalations", [])
        errors = state.get("errors", [])

        # Block if FX rates were missing (escalation type)
        fx_escalations = [e for e in escalations if e.get("type") == "MISSING_FX_RATE"]
        if fx_escalations or errors:
            logger.info("[route_after_match] -> escalate (missing FX or errors)")
            return "escalate"

        logger.info("[route_after_match] -> eliminate")
        return "eliminate"
    except Exception as exc:
        logger.error("[route_after_match] routing error: %s", exc)
        return "escalate"


def route_after_eliminate(state: CloseCommandState) -> str:
    """Route to validate or escalate based on elimination result."""
    try:
        elimination_result = state.get("elimination_result", {})
        gate_failure_count = elimination_result.get("gate_failure_count", 0)
        escalations = state.get("escalations", [])

        gate_escalations = [e for e in escalations if e.get("type") == "GATE_FAILURES"]
        if gate_escalations:
            logger.info("[route_after_eliminate] -> escalate (too many gate failures)")
            return "escalate"

        logger.info("[route_after_eliminate] -> validate")
        return "validate"
    except Exception as exc:
        logger.error("[route_after_eliminate] routing error: %s", exc)
        return "escalate"


def route_after_validate(state: CloseCommandState) -> str:
    """Route to review or escalate based on validation result."""
    try:
        validation_result = state.get("validation_result", {})
        recommendation = validation_result.get("recommendation", "BLOCK")
        escalations = state.get("escalations", [])

        # Hard block conditions
        balance_escalations = [e for e in escalations if e.get("type") == "JOURNAL_IMBALANCE"]
        if balance_escalations:
            logger.info("[route_after_validate] -> escalate (journal imbalance)")
            return "escalate"

        continuation_escalations = [e for e in escalations if e.get("type") == "CONTINUATION_CONTROL"]
        if continuation_escalations:
            logger.info("[route_after_validate] -> escalate (continuation control failed)")
            return "escalate"

        # Always go to review — human gate must pass regardless of score
        logger.info("[route_after_validate] -> review (recommendation=%s)", recommendation)
        return "review"
    except Exception as exc:
        logger.error("[route_after_validate] routing error: %s", exc)
        return "escalate"


def route_after_review(state: CloseCommandState) -> str:
    """Route to output or escalate based on review decisions."""
    try:
        review_result = state.get("review_result", {})
        close_readiness = review_result.get("close_readiness", {})
        escalations = state.get("escalations", [])

        # If close is ready → output
        if close_readiness.get("ready", False):
            logger.info("[route_after_review] -> output (close ready)")
            return "output"

        # If there are rejected items → escalate
        rejected = close_readiness.get("rejected_count", 0)
        escalated = close_readiness.get("escalated_count", 0)

        if rejected > 0 or escalated > 0:
            logger.info(
                "[route_after_review] -> escalate (rejected=%d escalated=%d)",
                rejected, escalated,
            )
            return "escalate"

        # Pending items — this shouldn't reach output without all items resolved
        # but if no blocking items, proceed
        blocking = close_readiness.get("blocking_items", [])
        if blocking:
            logger.info("[route_after_review] -> escalate (blocking items: %s)", blocking)
            return "escalate"

        # All pending, none blocking — allow output to proceed (open-loop scenario)
        logger.info("[route_after_review] -> output (no blocking items)")
        return "output"

    except Exception as exc:
        logger.error("[route_after_review] routing error: %s", exc)
        return "escalate"


# ──────────────────────────────────────────────────────────────────────
# Graph construction
# ──────────────────────────────────────────────────────────────────────

def _build_graph() -> object:
    """Build and compile the LangGraph StateGraph."""
    try:
        graph = StateGraph(CloseCommandState)

        # Register nodes
        graph.add_node("ingest", ingest_node)
        graph.add_node("match", match_node)
        graph.add_node("eliminate", eliminate_node)
        graph.add_node("validate", validate_node)
        graph.add_node("review", review_node)
        graph.add_node("output", output_node)
        graph.add_node("consolidate", consolidate_node)
        graph.add_node("error", error_node)
        graph.add_node("escalate", escalate_node)

        # Entry edge
        graph.add_edge(START, "ingest")

        # Conditional edges
        graph.add_conditional_edges(
            "ingest",
            route_after_ingest,
            {"match": "match", "error": "error"},
        )
        graph.add_conditional_edges(
            "match",
            route_after_match,
            {"eliminate": "eliminate", "escalate": "escalate"},
        )
        graph.add_conditional_edges(
            "eliminate",
            route_after_eliminate,
            {"validate": "validate", "escalate": "escalate"},
        )
        graph.add_conditional_edges(
            "validate",
            route_after_validate,
            {"review": "review", "escalate": "escalate"},
        )
        graph.add_conditional_edges(
            "review",
            route_after_review,
            {"output": "output", "escalate": "escalate"},
        )

        # Terminal edges
        graph.add_edge("output", "consolidate")
        graph.add_edge("consolidate", END)
        graph.add_edge("error", END)
        graph.add_edge("escalate", END)

        # Checkpointer — prefer SQLite for persistence, fall back to in-memory
        if _SQLITE_AVAILABLE:
            _is_cloud = os.environ.get("STREAMLIT_SHARING_MODE") or os.environ.get("IS_STREAMLIT_CLOUD")
            _ckpt_dir = "/tmp" if _is_cloud else "."
            _ckpt_path = os.path.join(_ckpt_dir, "close_command_checkpoints.db")
            conn = sqlite3.connect(_ckpt_path, check_same_thread=False)
            checkpointer = _SqliteSaver(conn)
            logger.info("Using SQLite checkpointer")
        else:
            checkpointer = _MemorySaver()
            logger.warning(
                "langgraph-checkpoint-sqlite not installed — using in-memory checkpointer. "
                "Install with: pip install langgraph-checkpoint-sqlite"
            )

        # Compile with HITL interrupt before review
        compiled = graph.compile(
            checkpointer=checkpointer,
            interrupt_before=["review"],
        )

        logger.info("Close Command LangGraph compiled successfully")
        return compiled

    except Exception as exc:
        logger.error("Failed to build LangGraph: %s", exc)
        raise


# Compile at module load
try:
    compiled_graph = _build_graph()
except Exception as _build_exc:
    logger.critical("LangGraph compilation failed at import: %s", _build_exc)
    compiled_graph = None


def get_graph():
    """Return the compiled graph (accessor function)."""
    return compiled_graph


# ──────────────────────────────────────────────────────────────────────
# Pipeline runner
# ──────────────────────────────────────────────────────────────────────

def run_close_pipeline(
    batch_id: str,
    period: str,
    scenario: str,
    raw_data=None,
    source_file: str = "",
    config: dict = None,
) -> dict:
    """
    Create initial state, invoke the graph, return final state.

    Args:
        batch_id:    Unique batch identifier
        period:      Accounting period e.g. "2024-03"
        scenario:    e.g. "ACTUAL" or "BUDGET"
        raw_data:    Optional pandas DataFrame with IC data
        source_file: Optional path to CSV file
        config:      Optional LangGraph config dict (e.g. {"configurable": {"thread_id": "..."}})

    Returns:
        Final state dict after pipeline completion (or interrupt).
    """
    try:
        if not batch_id:
            batch_id = str(uuid.uuid4())

        # Store raw_data in a module-level cache keyed by batch_id so it is
        # never placed inside the LangGraph state (DataFrames are not msgpack
        # serializable and would crash the SQLite checkpointer).
        if raw_data is not None:
            _RAW_DATA_CACHE[batch_id] = raw_data

        initial_state = create_initial_state(
            batch_id=batch_id,
            period=period,
            scenario=scenario,
            raw_data=None,          # keep state serializable
            source_file=source_file,
        )

        if config is None:
            config = {"configurable": {"thread_id": batch_id}}
        elif "configurable" not in config:
            config["configurable"] = {"thread_id": batch_id}
        elif "thread_id" not in config["configurable"]:
            config["configurable"]["thread_id"] = batch_id

        if compiled_graph is None:
            raise RuntimeError("LangGraph was not compiled successfully — check logs")

        logger.info(
            "run_close_pipeline: batch_id=%s period=%s scenario=%s",
            batch_id, period, scenario,
        )

        final_state = compiled_graph.invoke(initial_state, config=config)

        logger.info(
            "run_close_pipeline complete: batch_id=%s status=%s",
            batch_id,
            final_state.get("overall_status", "UNKNOWN"),
        )
        return final_state

    except Exception as exc:
        logger.error("run_close_pipeline failed: %s", exc)
        return {
            "batch_id": batch_id,
            "period": period,
            "scenario": scenario,
            "overall_status": "ERROR",
            "errors": [str(exc)],
            "escalations": [],
        }
