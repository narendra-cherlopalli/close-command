"""
Production-grade Intercompany Elimination — LangGraph multi-agent backend.

Graph flow:
  START → matching → [exception_analyzer →] je_generator
        → INTERRUPT (human review)
        → human_review_router → [exception_analyzer → je_generator → INTERRUPT (loop)]
                               → validator → summarize → END
"""

import os
import sqlite3
from datetime import datetime
from typing import TypedDict, Annotated, Optional

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from langchain_anthropic import ChatAnthropic

DB_PATH = "chatbot.db"
# On Streamlit Community Cloud the filesystem is ephemeral — use in-memory checkpointer.
# Locally, use SQLite so pipeline state survives browser refresh.
_USE_MEMORY = os.getenv("STREAMLIT_CLOUD", "false").lower() == "true"


# ─────────────────────────────────────────────────────────────────────────────
# STATE
# ─────────────────────────────────────────────────────────────────────────────

class ICState(TypedDict):
    messages:          Annotated[list[BaseMessage], add_messages]
    transactions:      list   # serialisable dicts (from DataFrame.to_dict("records"))
    matched_pairs:     list   # high-confidence IC pairs ready for elimination
    exceptions:        list   # mismatches + orphan (unmatched) transactions
    journal_entries:   list   # generated DR/CR elimination lines
    validation_result: dict   # DR=CR balance + completeness check
    period:            str    # e.g. "2025-01"
    human_approved:    Optional[bool]  # None=pending, True=approved, False=rejected
    rejection_reason:  str
    run_summary:       str
    api_key:           str    # use env var / secrets manager in production


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _llm(api_key: str) -> ChatAnthropic:
    return ChatAnthropic(model="claude-sonnet-4-6", api_key=api_key, max_tokens=1024)


def _score_pair(a: dict, b: dict) -> tuple[int, str]:
    """Rule-based match confidence (0-100) with human-readable reasoning."""
    score, reasons = 0, []

    var_pct = abs(a["amount_usd"] - b["amount_usd"]) / max(a["amount_usd"], 1)
    if var_pct == 0:
        score += 50; reasons.append("exact amount")
    elif var_pct < 0.01:
        score += 40; reasons.append(f"{var_pct*100:.2f}% amount var")
    elif var_pct < 0.05:
        score += 25; reasons.append(f"{var_pct*100:.1f}% amount var")

    if a["entity"] == b.get("counterparty") and b["entity"] == a.get("counterparty"):
        score += 30; reasons.append("counterparty confirmed")

    if a.get("reference") and a.get("reference") == b.get("reference"):
        score += 10; reasons.append("reference matches")

    try:
        diff = abs((
            datetime.fromisoformat(str(a["posting_date"])) -
            datetime.fromisoformat(str(b["posting_date"]))
        ).days)
        if diff == 0:   score += 10; reasons.append("same date")
        elif diff <= 3: score += 7;  reasons.append(f"{diff}d date diff")
        elif diff <= 7: score += 3
    except Exception:
        pass

    return min(score, 100), " | ".join(reasons)


# ─────────────────────────────────────────────────────────────────────────────
# NODES
# ─────────────────────────────────────────────────────────────────────────────

def matching_node(state: ICState) -> dict:
    """Group transactions by pair_id and score each pair."""
    groups: dict[str, list] = {}
    for tx in state["transactions"]:
        groups.setdefault(tx.get("pair_id", "UNKNOWN"), []).append(tx)

    matched, exceptions = [], []

    for pair_id, txs in groups.items():
        if len(txs) == 2:
            score, reason = _score_pair(txs[0], txs[1])
            cr = next((t for t in txs if t.get("side") == "CR"), txs[0])
            dr = next((t for t in txs if t.get("side") == "DR"), txs[1])
            record = dict(
                pair_id=pair_id,
                entity_a=cr["entity"], entity_b=dr["entity"],
                tx_a=cr, tx_b=dr,
                amount_usd=cr["amount_usd"],
                tx_type=cr.get("tx_type", "Trade"),
                period=cr.get("period", ""),
                reference=cr.get("reference", ""),
                confidence=score,
                match_reason=reason,
            )
            if score >= 85:
                matched.append(record)
            else:
                record.update(
                    exception_type="Mismatch",
                    variance_usd=abs(txs[0]["amount_usd"] - txs[1]["amount_usd"]),
                )
                exceptions.append(record)
        else:
            for tx in txs:
                exceptions.append(dict(
                    pair_id=pair_id, entity_a=tx["entity"],
                    entity_b=tx.get("counterparty", "Unknown"),
                    tx_a=tx, tx_b=None,
                    amount_usd=tx["amount_usd"],
                    tx_type=tx.get("tx_type", "Trade"),
                    period=tx.get("period", ""),
                    reference=tx.get("reference", ""),
                    confidence=0,
                    exception_type="Unmatched",
                    variance_usd=tx["amount_usd"],
                ))

    return dict(
        messages=[AIMessage(content=(
            f"**Matching complete** — "
            f"{len(matched)} pairs matched ({len(matched)*2} transactions), "
            f"{len(exceptions)} exceptions flagged."
        ))],
        matched_pairs=matched,
        exceptions=exceptions,
    )


def exception_analyzer_node(state: ICState) -> dict:
    """LLM-powered root cause analysis for mismatches and orphan transactions."""
    exceptions = state["exceptions"]
    if not exceptions:
        return dict(messages=[AIMessage(content="No exceptions to analyse.")])

    lines = [
        f"- [{e['exception_type']}] {e['entity_a']} ↔ {e.get('entity_b', '—')} | "
        f"{e['tx_type']} | Ref: {e['reference']} | "
        f"${e['amount_usd']:,.0f} | Variance: ${e.get('variance_usd', 0):,.0f}"
        for e in exceptions[:15]
    ]

    prompt = (
        f"You are an IC elimination controller reviewing {len(exceptions)} exceptions "
        f"(showing {min(len(exceptions), 15)}). Provide:\n"
        "1. Root causes grouped by pattern\n"
        "2. Resolution steps for each group\n"
        "3. Which need urgent manual review (high value or compliance risk)\n\n"
        + "\n".join(lines)
        + "\n\nBe concise and actionable."
    )

    try:
        analysis = _llm(state["api_key"]).invoke([HumanMessage(content=prompt)]).content
    except Exception as e:
        analysis = f"LLM analysis unavailable: {e}"

    # Enrich each exception with a quick AI suggestion
    enriched = []
    for exc in exceptions:
        exc = exc.copy()
        var = exc.get("variance_usd", 0)
        if exc["exception_type"] == "Unmatched":
            exc["ai_suggestion"] = "No counterparty entry — verify counterparty has posted; may need cut-off journal."
        elif var > 100_000:
            exc["ai_suggestion"] = "High-value variance — likely FX revaluation or bank fees; confirm with both entities."
        else:
            exc["ai_suggestion"] = "Small variance — probable FX rounding or timing; assess against materiality threshold."
        enriched.append(exc)

    return dict(
        messages=[AIMessage(content=f"**Exception Analysis**\n\n{analysis}")],
        exceptions=enriched,
    )


def je_generator_node(state: ICState) -> dict:
    """Generate structured DR/CR elimination journal entry lines for all matched pairs."""
    entries = []
    for pair in state["matched_pairs"]:
        cr_tx = pair["tx_a"] if pair["tx_a"].get("side") == "CR" else pair["tx_b"]
        dr_tx = pair["tx_b"] if pair["tx_a"].get("side") == "CR" else pair["tx_a"]
        ref  = f"JE-ELIM-{pair['pair_id']}"
        desc = f"Eliminate IC {pair['tx_type']}: {pair['entity_a']} ↔ {pair['entity_b']}"
        base = dict(
            je_ref=ref, pair_id=pair["pair_id"], description=desc,
            amount_usd=pair["amount_usd"], period=pair["period"],
            entities=f"{pair['entity_a']} ↔ {pair['entity_b']}",
            tx_type=pair["tx_type"], confidence=pair["confidence"],
        )
        entries.append({**base, "account": cr_tx.get("account", "IC Account"), "dr_cr": "DR"})
        entries.append({**base, "account": dr_tx.get("account", "IC Account"), "dr_cr": "CR"})

    return dict(
        messages=[AIMessage(content=(
            f"**Journal entries generated** — "
            f"{len(entries)} lines for {len(state['matched_pairs'])} elimination pairs. "
            f"Awaiting human review."
        ))],
        journal_entries=entries,
        human_approved=None,   # reset approval for each new review cycle
    )


def human_review_router_node(state: ICState) -> dict:
    """
    No-op node used purely as an interrupt point.
    The graph pauses BEFORE this node runs (interrupt_before=["human_review_router"]).
    After the human sets human_approved via update_state(), the graph resumes here
    and the conditional edge routes to validator (approved) or exception_analyzer (rejected).
    """
    return {}


def validator_node(state: ICState) -> dict:
    """Verify DR = CR and that all matched pairs have JE coverage."""
    jes = state["journal_entries"]
    dr  = sum(j["amount_usd"] for j in jes if j["dr_cr"] == "DR")
    cr  = sum(j["amount_usd"] for j in jes if j["dr_cr"] == "CR")
    balanced  = abs(dr - cr) < 0.01
    n_je_pairs = len(set(j["pair_id"] for j in jes))
    expected   = len(state["matched_pairs"])

    result = dict(
        balanced=balanced, dr_total=dr, cr_total=cr,
        variance=abs(dr - cr),
        complete=n_je_pairs == expected,
        pairs_expected=expected, pairs_in_je=n_je_pairs,
        passed=balanced and n_je_pairs == expected,
    )

    if result["passed"]:
        msg = f"**Validation PASSED** — DR = CR = ${dr:,.0f} | {expected} pairs fully covered."
    else:
        issues = []
        if not balanced:        issues.append(f"balance variance ${result['variance']:,.2f}")
        if not result["complete"]: issues.append(f"pairs {n_je_pairs}/{expected}")
        msg = f"**Validation FAILED** — {'; '.join(issues)}."

    return dict(messages=[AIMessage(content=msg)], validation_result=result)


def summarize_node(state: ICState) -> dict:
    """LLM-generated executive close summary for CFO / Controller sign-off."""
    val = state.get("validation_result", {})
    prompt = (
        "Write a 3-sentence executive IC elimination close summary:\n"
        f"- Period: {state.get('period', 'Current')}\n"
        f"- Matched pairs: {len(state['matched_pairs'])}\n"
        f"- Exceptions requiring review: {len(state['exceptions'])}\n"
        f"- JE lines posted: {len(state['journal_entries'])}\n"
        f"- Total eliminated: ${val.get('dr_total', 0):,.0f} USD\n"
        f"- Validation: {'PASSED' if val.get('passed') else 'FAILED'}\n"
        "Suitable for CFO/Controller sign-off email."
    )
    try:
        summary = _llm(state["api_key"]).invoke([HumanMessage(content=prompt)]).content
    except Exception as e:
        summary = f"Summary unavailable: {e}"

    return dict(messages=[AIMessage(content=f"**Close Summary**\n\n{summary}")], run_summary=summary)


# ─────────────────────────────────────────────────────────────────────────────
# ROUTING
# ─────────────────────────────────────────────────────────────────────────────

def _route_after_matching(state: ICState) -> str:
    return "exception_analyzer" if state["exceptions"] else "je_generator"


def _route_after_human_review(state: ICState) -> str:
    if state.get("human_approved") is True:
        return "validator"
    return "exception_analyzer"   # rejected — re-analyse and re-generate


# ─────────────────────────────────────────────────────────────────────────────
# GRAPH
# ─────────────────────────────────────────────────────────────────────────────

def build_ic_graph():
    if _USE_MEMORY:
        checkpointer = MemorySaver()
    else:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        checkpointer = SqliteSaver(conn=conn)

    g = StateGraph(ICState)
    g.add_node("matching",            matching_node)
    g.add_node("exception_analyzer",  exception_analyzer_node)
    g.add_node("je_generator",        je_generator_node)
    g.add_node("human_review_router", human_review_router_node)
    g.add_node("validator",           validator_node)
    g.add_node("summarize",           summarize_node)

    g.add_edge(START, "matching")
    g.add_conditional_edges("matching", _route_after_matching, {
        "exception_analyzer": "exception_analyzer",
        "je_generator":       "je_generator",
    })
    g.add_edge("exception_analyzer", "je_generator")
    g.add_edge("je_generator",       "human_review_router")
    g.add_conditional_edges("human_review_router", _route_after_human_review, {
        "validator":          "validator",
        "exception_analyzer": "exception_analyzer",
    })
    g.add_edge("validator",  "summarize")
    g.add_edge("summarize",  END)

    return g.compile(
        checkpointer=checkpointer,
        interrupt_before=["human_review_router"],
    )


ic_graph = build_ic_graph()
