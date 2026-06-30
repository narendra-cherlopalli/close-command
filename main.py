"""
Close Command — Streamlit main entry point.
Helios Group — Agentic Financial Close Engine.
"""

import streamlit as st
import pandas as pd
import uuid
from datetime import datetime
import sys
import os
import logging

# Add parent dir to path so close_command package is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── Page config (must be first Streamlit call) ───────────────────────────────
st.set_page_config(
    page_title="Close Command | Helios Chemicals Group",
    page_icon="⚗️",
    layout="wide",
    initial_sidebar_state="expanded",
)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# ── Load secrets: Streamlit Cloud secrets first, then .env ───────────────────
def _load_secrets() -> None:
    """Inject Streamlit Cloud secrets into os.environ so all modules can read them."""
    try:
        for key, val in st.secrets.items():
            if isinstance(val, str) and key not in os.environ:
                os.environ[key] = val
    except Exception:
        pass  # Running locally without secrets.toml — .env already loaded

_load_secrets()

# ── Use /tmp on Streamlit Cloud (ephemeral filesystem) ────────────────────────
_IS_CLOUD = os.environ.get("STREAMLIT_SHARING_MODE") or os.environ.get("IS_STREAMLIT_CLOUD")
_TMP = "/tmp" if _IS_CLOUD else "."

# ── Import backend components ─────────────────────────────────────────────────
try:
    from close_command.database.persistence import CloseCommandDB
    _DB_AVAILABLE = True
except ImportError as e:
    _DB_AVAILABLE = False
    st.error(f"Database module unavailable: {e}")

try:
    from close_command.orchestrator.graph import run_close_pipeline, compiled_graph
    from close_command.orchestrator.state import create_initial_state
    _GRAPH_AVAILABLE = True
except ImportError as e:
    _GRAPH_AVAILABLE = False
    compiled_graph = None
    logger.warning("Graph module unavailable: %s", e)

try:
    from close_command.orchestrator.scheduler import CloseCommandScheduler
    _SCHEDULER_AVAILABLE = True
except ImportError as e:
    _SCHEDULER_AVAILABLE = False
    logger.warning("Scheduler unavailable: %s", e)

try:
    from close_command.rag.vectorstore import CloseCommandVectorStore
    from close_command.rag.retriever import CloseCommandRetriever
    from close_command.rag.indexer import CloseCommandIndexer
    _RAG_AVAILABLE = True
except ImportError:
    _RAG_AVAILABLE = False
    CloseCommandVectorStore = None
    CloseCommandRetriever = None
    CloseCommandIndexer = None

# ── Import UI modules ─────────────────────────────────────────────────────────
try:
    from close_command.ui.dashboard import render_dashboard
    from close_command.ui.pipeline_monitor import render_pipeline_monitor
    from close_command.ui.matching_tab import render_matching_tab
    from close_command.ui.elimination_tab import render_elimination_tab
    from close_command.ui.review_tab import render_review_tab
    from close_command.ui.journal_tab import render_journal_tab
    from close_command.ui.consolidation_tab import render_consolidation_tab
    from close_command.ui.rag_tab import render_rag_tab
    _UI_AVAILABLE = True
except ImportError as e:
    _UI_AVAILABLE = False
    st.error(f"UI module import failed: {e}")

# ── Data layer imports ────────────────────────────────────────────────────────
try:
    from close_command.database.master_data_store import MasterDataStore
    from close_command.ui.master_data_tab import render_master_data_tab
    from close_command.ui.data_import_tab import render_data_import_tab
    _DATA_LAYER_AVAILABLE = True
except ImportError as _dl_exc:
    _DATA_LAYER_AVAILABLE = False
    MasterDataStore = None
    render_master_data_tab = None
    render_data_import_tab = None
    logger.warning("Data layer unavailable: %s", _dl_exc)


# ── Session state initialisation ─────────────────────────────────────────────
def _init_session_state() -> None:
    """Initialise all session state keys with safe defaults."""

    if "pipeline_state" not in st.session_state:
        st.session_state["pipeline_state"] = None

    if "batch_id" not in st.session_state:
        st.session_state["batch_id"] = None

    if "pipeline_running" not in st.session_state:
        st.session_state["pipeline_running"] = False

    if "run_history" not in st.session_state:
        st.session_state["run_history"] = []

    if "replay_batch_id" not in st.session_state:
        st.session_state["replay_batch_id"] = None

    if "hitl_pending" not in st.session_state:
        st.session_state["hitl_pending"] = False

    # DB singleton
    if "db" not in st.session_state:
        if _DB_AVAILABLE:
            try:
                default_db = os.path.join(_TMP, "close_command.db")
                db_path = os.environ.get("CLOSE_COMMAND_DB_PATH", default_db)
                st.session_state["db"] = CloseCommandDB(db_path=db_path)
            except Exception as exc:
                logger.error("DB init failed: %s", exc)
                st.session_state["db"] = None
        else:
            st.session_state["db"] = None

    # VectorStore singleton
    if "vectorstore" not in st.session_state:
        if _RAG_AVAILABLE:
            try:
                default_vs = os.path.join(_TMP, "close_command_vectorstore")
                vs_path = os.environ.get("CLOSE_COMMAND_VECTORSTORE_PATH", default_vs)
                st.session_state["vectorstore"] = CloseCommandVectorStore(persist_directory=vs_path)
            except Exception as exc:
                logger.warning("VectorStore init failed (chromadb may not be installed): %s", exc)
                st.session_state["vectorstore"] = None
        else:
            st.session_state["vectorstore"] = None

    # Retriever singleton
    if "retriever" not in st.session_state:
        if _RAG_AVAILABLE and st.session_state.get("vectorstore"):
            try:
                st.session_state["retriever"] = CloseCommandRetriever(st.session_state["vectorstore"])
            except Exception as exc:
                logger.warning("Retriever init failed: %s", exc)
                st.session_state["retriever"] = None
        else:
            st.session_state["retriever"] = None

    # Indexer singleton
    if "indexer" not in st.session_state:
        if _RAG_AVAILABLE and st.session_state.get("vectorstore"):
            try:
                st.session_state["indexer"] = CloseCommandIndexer(st.session_state["vectorstore"])
            except Exception as exc:
                logger.warning("Indexer init failed: %s", exc)
                st.session_state["indexer"] = None
        else:
            st.session_state["indexer"] = None

    # Scheduler singleton
    if "scheduler" not in st.session_state:
        if _SCHEDULER_AVAILABLE:
            try:
                runner_fn = run_close_pipeline if _GRAPH_AVAILABLE else None
                st.session_state["scheduler"] = CloseCommandScheduler(graph_runner=runner_fn)
            except Exception as exc:
                logger.warning("Scheduler init failed: %s", exc)
                st.session_state["scheduler"] = None
        else:
            st.session_state["scheduler"] = None

    # ── MasterDataStore singleton ─────────────────────────────────────────────
    if "mds" not in st.session_state:
        if _DATA_LAYER_AVAILABLE and st.session_state.get("db"):
            try:
                st.session_state["mds"] = MasterDataStore(
                    st.session_state["db"].conn
                )
            except Exception as exc:
                logger.warning("MasterDataStore init failed: %s", exc)
                st.session_state["mds"] = None
        else:
            st.session_state["mds"] = None

    # ── Pipeline approval gate ────────────────────────────────────────────────
    if "pipeline_approved" not in st.session_state:
        st.session_state["pipeline_approved"] = False
    if "active_import_id" not in st.session_state:
        st.session_state["active_import_id"] = None
    if "approved_period" not in st.session_state:
        st.session_state["approved_period"] = None
    if "approved_scenario" not in st.session_state:
        st.session_state["approved_scenario"] = None


def _parse_uploaded_file(uploaded_file) -> pd.DataFrame | None:
    """Parse an uploaded CSV or Excel file into a DataFrame."""
    if uploaded_file is None:
        return None
    try:
        name = uploaded_file.name.lower()
        if name.endswith(".csv"):
            return pd.read_csv(uploaded_file)
        elif name.endswith((".xlsx", ".xls")):
            return pd.read_excel(uploaded_file)
        else:
            st.error("Unsupported file format. Please upload CSV or Excel.")
            return None
    except Exception as exc:
        st.error(f"Failed to parse uploaded file: {exc}")
        return None


def _run_pipeline(period: str, scenario: str, uploaded_file=None) -> None:
    """Trigger the close pipeline and store result in session state."""
    db = st.session_state.get("db")

    batch_id = str(uuid.uuid4())[:8]
    st.session_state["batch_id"] = batch_id
    st.session_state["pipeline_running"] = True
    st.session_state["hitl_pending"] = False

    raw_data = None
    source_file = ""
    if uploaded_file is not None:
        raw_data = _parse_uploaded_file(uploaded_file)
        source_file = uploaded_file.name

    # Save batch run record
    if db:
        try:
            db.save_batch_run({
                "batch_id": batch_id,
                "period": period,
                "scenario": scenario,
                "status": "RUNNING",
                "started_at": datetime.utcnow().isoformat(),
            })
        except Exception as exc:
            logger.warning("Could not save batch run: %s", exc)

    try:
        if not _GRAPH_AVAILABLE or compiled_graph is None:
            st.error("Pipeline graph is not available. Check your installation.")
            st.session_state["pipeline_running"] = False
            return

        with st.spinner(f"Running Close Command pipeline for {period} ({scenario})..."):
            final_state = run_close_pipeline(
                batch_id=batch_id,
                period=period,
                scenario=scenario,
                raw_data=raw_data,
                source_file=source_file,
            )

        st.session_state["pipeline_state"] = final_state
        st.session_state["pipeline_running"] = False

        overall_status = final_state.get("overall_status", "UNKNOWN")

        # ── Detect HITL interrupt ──────────────────────────────────────────
        # With interrupt_before=["review"], LangGraph returns the partial state
        # normally (no exception). We detect the pause by inspecting the
        # checkpoint's .next field — any pending node means we're interrupted.
        hitl_detected = False
        if compiled_graph is not None:
            try:
                snap = compiled_graph.get_state(
                    {"configurable": {"thread_id": batch_id}}
                )
                if snap and snap.next:
                    hitl_detected = True
                    # Refresh pipeline_state from the checkpoint so the UI
                    # always shows the most complete picture available.
                    if snap.values:
                        restored = dict(snap.values)
                        restored["overall_status"] = "INTERRUPTED"
                        st.session_state["pipeline_state"] = restored
                        final_state = restored
            except Exception as _snap_exc:
                logger.warning("get_state failed: %s", _snap_exc)

        if not hitl_detected:
            # Fallback: old-style check via review_result
            review_result = final_state.get("review_result") or {}
            if review_result.get("pending_items"):
                hitl_detected = True

        if hitl_detected:
            st.session_state["hitl_pending"] = True
            st.warning(
                "Pipeline paused at the HITL review gate. "
                "Review any exceptions in the **Review & Approve** tab, "
                "then click **Resume Pipeline** in the sidebar."
            )

        if db:
            try:
                db.update_batch_status(batch_id, overall_status)
            except Exception:
                pass

        run_record = {
            "batch_id": batch_id,
            "period": period,
            "scenario": scenario,
            "status": overall_status,
            "started_at": datetime.utcnow().isoformat(),
        }
        st.session_state["run_history"].append(run_record)

    except Exception as exc:
        # Catch LangGraph interrupt or other pipeline errors
        err_msg = str(exc)
        logger.error("Pipeline error: %s", err_msg)

        # If it's an interrupt (HITL), the state is partially complete
        # Try to get latest state from graph checkpoint
        partial_state = {
            "batch_id": batch_id,
            "period": period,
            "scenario": scenario,
            "overall_status": "INTERRUPTED",
            "errors": [err_msg],
            "escalations": [],
            "current_agent": "Review",
            "human_review_required": True,
        }

        # Attempt to retrieve partial state from compiled_graph checkpoint
        if compiled_graph is not None:
            try:
                config = {"configurable": {"thread_id": batch_id}}
                state_snapshot = compiled_graph.get_state(config)
                if state_snapshot and state_snapshot.values:
                    partial_state = dict(state_snapshot.values)
                    partial_state["overall_status"] = "INTERRUPTED"
            except Exception:
                pass

        st.session_state["pipeline_state"] = partial_state
        st.session_state["pipeline_running"] = False
        st.session_state["hitl_pending"] = True

        if db:
            try:
                db.update_batch_status(batch_id, "INTERRUPTED")
            except Exception:
                pass

        st.warning(
            f"Pipeline paused at review gate. "
            "Go to the 'Review & Approve' tab to record decisions, "
            "then click 'Resume Pipeline' to continue."
        )


def _resume_pipeline() -> None:
    """Resume a LangGraph pipeline from checkpoint after HITL decisions."""
    batch_id = st.session_state.get("batch_id")
    db = st.session_state.get("db")

    if not batch_id or compiled_graph is None:
        st.error("No active pipeline to resume.")
        return

    with st.spinner("Resuming pipeline — running Review → Output → Consolidation..."):
        try:
            config = {"configurable": {"thread_id": batch_id}}

            # ── Correct LangGraph resume call ──────────────────────────────
            # For interrupt_before=["review"], pass None to continue from the
            # checkpoint. The review_agent loads DB decisions internally —
            # do NOT pass {"decisions": ...} as that can confuse LangGraph
            # into re-starting the thread instead of resuming it.
            final_state = compiled_graph.invoke(None, config=config)

            # ── Verify and enrich the returned state ───────────────────────
            # get_state gives the authoritative checkpoint snapshot
            snap = compiled_graph.get_state(config)
            if snap and snap.values:
                checkpoint_state = dict(snap.values)
                # Use checkpoint if it has richer data (e.g. consolidation_result)
                if (
                    checkpoint_state.get("consolidation_result") is not None
                    or checkpoint_state.get("output_result") is not None
                ):
                    final_state = checkpoint_state

            st.session_state["pipeline_state"] = final_state
            st.session_state["hitl_pending"] = False
            st.session_state["pipeline_running"] = False

            overall_status = final_state.get("overall_status", "COMPLETE")
            if db:
                try:
                    db.update_batch_status(batch_id, overall_status)
                except Exception:
                    pass

            st.success(f"✅ Pipeline completed with status: **{overall_status}**")
            st.rerun()

        except Exception as exc:
            st.error(f"Failed to resume pipeline: {exc}")
            logger.error("Resume pipeline failed: %s", exc)

            # Try to recover latest checkpoint state even after error
            try:
                config = {"configurable": {"thread_id": batch_id}}
                snap = compiled_graph.get_state(config)
                if snap and snap.values:
                    recovered = dict(snap.values)
                    recovered["overall_status"] = "ERROR"
                    st.session_state["pipeline_state"] = recovered
                    st.rerun()
            except Exception:
                pass


# ── Sidebar ───────────────────────────────────────────────────────────────────
def _render_sidebar() -> None:
    """Render the main sidebar controls."""
    db = st.session_state.get("db")
    scheduler = st.session_state.get("scheduler")

    with st.sidebar:
        st.markdown("# ⚗️ Close Command")
        st.markdown("**Helios Group**")
        st.divider()

        st.markdown("### New Close Run")

        # Period selector
        periods = [f"{year}-{month:02d}" for year in [2024, 2025] for month in range(1, 13)]
        default_period_idx = periods.index("2024-12") if "2024-12" in periods else 0
        selected_period = st.selectbox("Period:", periods, index=default_period_idx)

        # Scenario
        selected_scenario = st.selectbox("Scenario:", ["Actual", "Budget", "Forecast"])

        # File uploader
        st.info(
            "Accepts full entity financial statements with IC and Non-IC lines. "
            "Auto-detects legacy IC-only format."
        )
        uploaded_file = st.file_uploader(
            "Upload Financial Statements (CSV/Excel)",
            type=["csv", "xlsx"],
            help="Optional — upload entity financial statement data (IC + Non-IC). If omitted, demo data is used.",
        )

        # Sample file download
        try:
            import os
            sample_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "sample_entity_financials.csv",
            )
            if os.path.exists(sample_path):
                with open(sample_path, "rb") as _f:
                    _sample_bytes = _f.read()
                st.download_button(
                    label="Download sample_entity_financials.csv",
                    data=_sample_bytes,
                    file_name="sample_entity_financials.csv",
                    mime="text/csv",
                    help="Download the sample full financial statement CSV to see the expected format.",
                )
        except Exception as _dl_exc:
            logger.warning("Could not load sample file for download: %s", _dl_exc)

        run_disabled = st.session_state.get("pipeline_running", False) or not st.session_state.get("pipeline_approved", False)

        pipeline_approved = st.session_state.get("pipeline_approved", False)
        approved_period   = st.session_state.get("approved_period")
        approved_scenario = st.session_state.get("approved_scenario")

        if pipeline_approved and approved_period:
            st.success(
                f"✅ Data approved for pipeline\n\n"
                f"**{approved_period}** / **{approved_scenario}**"
            )
        else:
            st.warning(
                "⚠️ No data approved yet.\n\n"
                "Import and review data in the **Data Import** tab first."
            )

        if st.button(
            "Run Close Pipeline",
            disabled=run_disabled,
            type="primary",
            help="Import and approve transactional data first." if not pipeline_approved else "",
        ):
            run_period   = approved_period   or selected_period
            run_scenario = approved_scenario or selected_scenario
            _run_pipeline(run_period, run_scenario, None)
            st.rerun()

        if st.session_state.get("pipeline_running"):
            st.info("Pipeline is running...")

        st.divider()

        # HITL resume button
        if st.session_state.get("hitl_pending"):
            st.warning("Pipeline paused at HITL review gate.")
            if st.button("Resume Pipeline", type="primary"):
                _resume_pipeline()

        st.divider()

        # Scheduler status
        st.markdown("### Scheduler")
        if scheduler is not None:
            try:
                next_run = scheduler.get_next_run_time()
                if next_run:
                    st.caption(f"Next scheduled run: {next_run}")
                else:
                    st.caption("No scheduled runs configured.")
            except Exception:
                st.caption("Scheduler status unavailable.")

            if st.button("Schedule Daily Run"):
                try:
                    scheduler.add_daily_close_run(
                        period=selected_period,
                        scenario=selected_scenario,
                        hour=int(os.environ.get("SCHEDULER_DAILY_RUN_HOUR", 6)),
                        minute=int(os.environ.get("SCHEDULER_DAILY_RUN_MINUTE", 0)),
                    )
                    st.success("Daily run scheduled.")
                except Exception as exc:
                    st.error(f"Scheduling failed: {exc}")
        else:
            st.caption("Scheduler not available (APScheduler not installed).")

        st.divider()

        # Recent runs
        run_history = st.session_state.get("run_history", [])
        if run_history:
            st.markdown("### Recent Runs")
            for run in reversed(run_history[-5:]):
                st.caption(
                    f"`{run['batch_id']}` {run['period']} {run['scenario']} — {run['status']}"
                )


# ── Welcome screen ────────────────────────────────────────────────────────────
def _render_welcome() -> None:
    """Render the welcome/onboarding screen when no pipeline has run."""
    st.markdown(
        """
        <h1 style='text-align:center;margin-top:2rem'>⚗️ Close Command</h1>
        <h3 style='text-align:center;color:#888'>Agentic Financial Close Engine — Helios Group</h3>
        """,
        unsafe_allow_html=True,
    )
    st.divider()

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown(
            """
            **Step 1 — Configure**
            - Select the accounting period from the sidebar
            - Choose Actual / Budget / Forecast scenario
            - Optionally upload a trial balance CSV or Excel file
            """
        )
    with col2:
        st.markdown(
            """
            **Step 2 — Run**
            - Click "Run Close Pipeline" to trigger the 6-agent pipeline
            - The pipeline runs: Ingestion → Matching → Elimination → Validation → Review → Output
            - The pipeline pauses at the Review gate for human approval
            """
        )
    with col3:
        st.markdown(
            """
            **Step 3 — Approve & Export**
            - Review intercompany matching results
            - Approve or escalate items in the Review & Approve tab
            - Download JLF, Excel or audit trail from Journal Output tab
            """
        )

    st.divider()
    st.markdown(
        "<p style='text-align:center;color:#aaa'>Run your first close →  use the sidebar on the left</p>",
        unsafe_allow_html=True,
    )


# ── Main app ──────────────────────────────────────────────────────────────────
def main() -> None:
    """Main Streamlit application entry point."""
    _init_session_state()

    db = st.session_state.get("db")
    vectorstore = st.session_state.get("vectorstore")
    indexer = st.session_state.get("indexer")
    pipeline_state = st.session_state.get("pipeline_state")
    mds = st.session_state.get("mds")
    current_user = st.session_state.get("current_user", "user")

    _render_sidebar()

    # ── Ten-tab interface ─────────────────────────────────────────────────
    tab0a, tab0b, tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8 = st.tabs([
        "⚙️ Master Data",
        "📥 Data Import & Review",
        "📊 Command Center",
        "🔄 Pipeline Monitor",
        "🔗 IC Matching",
        "📐 Elimination Engine",
        "✅ Review & Approve",
        "📄 Journal Output",
        "📈 Consolidated Statements",
        "🧠 RAG Knowledge Base",
    ])

    if not _UI_AVAILABLE:
        st.error("UI modules failed to import. Check console for details.")
        return

    with tab0a:
        if _DATA_LAYER_AVAILABLE and mds:
            try:
                render_master_data_tab(mds, current_user=current_user)
            except Exception as exc:
                st.error(f"Master Data tab error: {exc}")
                logger.exception("Master Data tab error")
        else:
            st.error(
                "Data layer unavailable. Ensure "
                "close_command/database/master_data_store.py and "
                "close_command/ui/master_data_tab.py are installed."
            )

    with tab0b:
        if _DATA_LAYER_AVAILABLE and mds:
            try:
                render_data_import_tab(mds, current_user=current_user)
            except Exception as exc:
                st.error(f"Data Import tab error: {exc}")
                logger.exception("Data Import tab error")
        else:
            st.error("Data layer unavailable.")

    # Only show pipeline tabs if a run has happened — but keep data tabs always visible
    if pipeline_state is None:
        with tab1:
            _render_welcome()
        return

    with tab1:
        try:
            render_dashboard(db, pipeline_state)
        except Exception as exc:
            st.error(f"Dashboard render error: {exc}")
            logger.exception("Dashboard render error")

    with tab2:
        try:
            render_pipeline_monitor(db, pipeline_state)
        except Exception as exc:
            st.error(f"Pipeline monitor render error: {exc}")
            logger.exception("Pipeline monitor render error")

    with tab3:
        try:
            render_matching_tab(pipeline_state)
        except Exception as exc:
            st.error(f"Matching tab render error: {exc}")
            logger.exception("Matching tab render error")

    with tab4:
        try:
            render_elimination_tab(pipeline_state)
        except Exception as exc:
            st.error(f"Elimination tab render error: {exc}")
            logger.exception("Elimination tab render error")

    with tab5:
        try:
            render_review_tab(pipeline_state, db)
        except Exception as exc:
            st.error(f"Review tab render error: {exc}")
            logger.exception("Review tab render error")

        # HITL prompt if pipeline is paused at review gate
        if st.session_state.get("hitl_pending"):
            st.divider()
            st.info(
                "The pipeline is paused at the review gate. "
                "Record your decisions above, then click 'Resume Pipeline' in the sidebar."
            )

    with tab6:
        try:
            render_journal_tab(pipeline_state, db)
        except Exception as exc:
            st.error(f"Journal tab render error: {exc}")
            logger.exception("Journal tab render error")

    with tab7:
        try:
            render_consolidation_tab(pipeline_state)
        except Exception as exc:
            st.error(f"Consolidated statements render error: {exc}")
            logger.exception("Consolidated statements render error")

    with tab8:
        try:
            render_rag_tab(vectorstore, indexer)
        except Exception as exc:
            st.error(f"RAG tab render error: {exc}")
            logger.exception("RAG tab render error")


if __name__ == "__main__":
    main()
