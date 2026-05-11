"""
Close Command Orchestrator package.
Exports the compiled graph, pipeline runner, and scheduler.

Imports are kept lazy here to avoid circular or optional-dependency failures
at package load time (e.g. chromadb, APScheduler, LangGraph checkpointer).
Use explicit imports in application entry-points:

    from close_command.orchestrator.state import CloseCommandState
    from close_command.orchestrator.graph import run_close_pipeline
    from close_command.orchestrator.scheduler import CloseCommandScheduler
"""

from close_command.orchestrator.state import (
    CloseCommandState,
    create_initial_state,
    update_state_timestamp,
)

__all__ = [
    "CloseCommandState",
    "create_initial_state",
    "update_state_timestamp",
    # Lazy-loaded on demand:
    "CloseCommandScheduler",
    "compiled_graph",
    "run_close_pipeline",
    "get_graph",
]


def __getattr__(name):
    """Lazy attribute loader for heavy optional dependencies."""
    if name in ("CloseCommandScheduler",):
        from close_command.orchestrator.scheduler import CloseCommandScheduler
        return CloseCommandScheduler
    if name in ("compiled_graph", "run_close_pipeline", "get_graph"):
        from close_command.orchestrator import graph as _graph_module
        return getattr(_graph_module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
