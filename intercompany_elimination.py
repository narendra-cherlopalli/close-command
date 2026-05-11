import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import anthropic
import sqlite3
import uuid
import random
from datetime import datetime, timedelta
from ic_backend import ic_graph

DB_PATH = "chatbot.db"

# ─────────────────────────────────────────────────────────────
# CHAT PERSISTENCE  (uses chatbot.db — separate table from LangGraph)
# ─────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ic_chat_messages (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            thread_id TEXT    NOT NULL,
            title     TEXT,
            role      TEXT    NOT NULL,
            content   TEXT    NOT NULL,
            created_at TEXT   DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    return conn


def load_threads():
    conn = get_db()
    rows = conn.execute(
        "SELECT thread_id, MIN(title) FROM ic_chat_messages GROUP BY thread_id ORDER BY MIN(id)"
    ).fetchall()
    conn.close()
    return [(r[0], r[1] or r[0][:20]) for r in rows]


def load_messages(thread_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT role, content FROM ic_chat_messages WHERE thread_id=? ORDER BY id",
        (thread_id,),
    ).fetchall()
    conn.close()
    return [{"role": r[0], "content": r[1]} for r in rows]


def save_message(thread_id, title, role, content):
    conn = get_db()
    conn.execute(
        "INSERT INTO ic_chat_messages (thread_id, title, role, content) VALUES (?,?,?,?)",
        (thread_id, title, role, content),
    )
    conn.commit()
    conn.close()


def delete_thread(thread_id):
    conn = get_db()
    conn.execute("DELETE FROM ic_chat_messages WHERE thread_id=?", (thread_id,))
    conn.commit()
    conn.close()

st.set_page_config(
    page_title="IC Elimination | Financial Close AI",
    layout="wide",
    page_icon="🏦"
)

# Resolve API key: Streamlit secrets (cloud) → sidebar input (local)
def _resolve_api_key(sidebar_key: str) -> str:
    try:
        return st.secrets["ANTHROPIC_API_KEY"] or sidebar_key
    except Exception:
        return sidebar_key

# ─────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────
ENTITIES = {
    "EBIC":     {"name": "Egyptian Bulk Intermediate Chemicals", "currency": "USD"},
    "SORFERT":  {"name": "Sorfert Algerie",                       "currency": "EUR"},
    "EFC":      {"name": "Egypt Fertilizers Company",             "currency": "USD"},
    "FERTIL":   {"name": "Fertil UAE",                            "currency": "AED"},
    "GMGI":     {"name": "Grand Meadow Group International",      "currency": "USD"},
    "NATPET":   {"name": "National Petrochemical Company",        "currency": "SAR"},
    "EGYCO":    {"name": "Egyptian Chemical Operations",          "currency": "USD"},
    "GULFCHEM": {"name": "Gulf Chemical Holdings",                "currency": "AED"},
}

IC_ACCOUNT_PAIRS = {
    "Trade":    ("Intercompany Sales [4100]",           "Intercompany Purchases [5100]"),
    "Loan":     ("IC Loans Receivable [1800]",          "IC Loans Payable [2800]"),
    "Service":  ("IC Service Revenue [4200]",           "IC Service Expense [5200]"),
    "Royalty":  ("IC Royalties Receivable [4300]",      "IC Service Expense [5200]"),
    "Dividend": ("IC Dividends Income [4500]",          "IC Dividends Paid [3300]"),
}

FX_RATES = {"USD": 1.0, "EUR": 1.08, "AED": 0.272, "SAR": 0.267}

MISMATCH_REASONS = [
    "FX rounding difference",
    "Bank charges deducted by counterparty",
    "Timing difference — different period posting",
    "Partial payment recorded",
    "System migration data mapping error",
]

# ─────────────────────────────────────────────────────────────
# SAMPLE DATA
# ─────────────────────────────────────────────────────────────
@st.cache_data
def generate_transactions(seed=42):
    random.seed(seed)
    np.random.seed(seed)

    entities = list(ENTITIES.keys())
    rows = []
    pair_counter = 1

    # Matched pairs (with some having small variances)
    for _ in range(160):
        seller = random.choice(entities)
        buyer = random.choice([e for e in entities if e != seller])
        tx_type = random.choice(list(IC_ACCOUNT_PAIRS.keys()))
        seller_acct, buyer_acct = IC_ACCOUNT_PAIRS[tx_type]

        base_amount = round(random.uniform(50_000, 4_000_000), 2)
        posting_date = datetime(2025, random.randint(1, 3), random.randint(1, 28))
        ref = f"IC-{pair_counter:04d}-{seller[:3]}-{buyer[:3]}"
        pair_id = f"PAIR-{pair_counter:04d}"

        has_variance = random.random() < 0.15
        variance = round(base_amount * random.uniform(0.001, 0.018), 2) if has_variance else 0
        date_offset = random.randint(1, 5) if random.random() < 0.20 else 0
        status = "Mismatch" if (has_variance or date_offset > 0) else "Matched"
        mismatch_reason = random.choice(MISMATCH_REASONS) if status == "Mismatch" else None

        seller_currency = ENTITIES[seller]["currency"]
        buyer_currency = ENTITIES[buyer]["currency"]

        rows.append({
            "tx_id": f"TX-{pair_counter:04d}A",
            "pair_id": pair_id,
            "entity": seller,
            "counterparty": buyer,
            "account": seller_acct,
            "tx_type": tx_type,
            "side": "CR",
            "amount_usd": base_amount,
            "currency": seller_currency,
            "amount_local": round(base_amount / FX_RATES[seller_currency], 2),
            "posting_date": posting_date,
            "period": posting_date.strftime("%Y-%m"),
            "reference": ref,
            "status": status,
            "mismatch_reason": mismatch_reason,
            "variance_usd": variance,
        })
        rows.append({
            "tx_id": f"TX-{pair_counter:04d}B",
            "pair_id": pair_id,
            "entity": buyer,
            "counterparty": seller,
            "account": buyer_acct,
            "tx_type": tx_type,
            "side": "DR",
            "amount_usd": base_amount + variance,
            "currency": buyer_currency,
            "amount_local": round((base_amount + variance) / FX_RATES[buyer_currency], 2),
            "posting_date": posting_date + timedelta(days=date_offset),
            "period": posting_date.strftime("%Y-%m"),
            "reference": ref,
            "status": status,
            "mismatch_reason": mismatch_reason,
            "variance_usd": variance,
        })
        pair_counter += 1

    # Unmatched orphan transactions
    for _ in range(18):
        entity = random.choice(entities)
        counterparty = random.choice([e for e in entities if e != entity])
        amount = round(random.uniform(20_000, 800_000), 2)
        posting_date = datetime(2025, random.randint(1, 3), random.randint(1, 28))
        tx_type = random.choice(list(IC_ACCOUNT_PAIRS.keys()))
        seller_acct, _ = IC_ACCOUNT_PAIRS[tx_type]
        currency = ENTITIES[entity]["currency"]

        rows.append({
            "tx_id": f"TX-{pair_counter:04d}A",
            "pair_id": f"PAIR-{pair_counter:04d}",
            "entity": entity,
            "counterparty": counterparty,
            "account": seller_acct,
            "tx_type": tx_type,
            "side": "CR",
            "amount_usd": amount,
            "currency": currency,
            "amount_local": round(amount / FX_RATES[currency], 2),
            "posting_date": posting_date,
            "period": posting_date.strftime("%Y-%m"),
            "reference": f"IC-{pair_counter:04d}-UNMATCHED",
            "status": "Unmatched",
            "mismatch_reason": "No counterparty entry found in GL",
            "variance_usd": amount,
        })
        pair_counter += 1

    df = pd.DataFrame(rows)
    df["posting_date"] = pd.to_datetime(df["posting_date"])
    return df


def build_eliminations(df):
    matched = df[df["status"] == "Matched"].copy()
    result = []
    for pair_id, grp in matched.groupby("pair_id"):
        if len(grp) == 2:
            cr_row = grp[grp["side"] == "CR"].iloc[0]
            dr_row = grp[grp["side"] == "DR"].iloc[0]
            result.append({
                "pair_id": pair_id,
                "type": cr_row["tx_type"],
                "entity_a": cr_row["entity"],
                "entity_b": dr_row["entity"],
                "elim_dr_account": cr_row["account"],   # reverse the CR
                "elim_cr_account": dr_row["account"],   # reverse the DR
                "amount_usd": cr_row["amount_usd"],
                "period": cr_row["period"],
                "reference": cr_row["reference"],
                "confidence": 99,
            })
    return pd.DataFrame(result)


def df_to_records(df: pd.DataFrame) -> list:
    """Convert DataFrame to JSON-serialisable list of dicts for the LangGraph state."""
    out = df.copy()
    out["posting_date"] = out["posting_date"].dt.strftime("%Y-%m-%d")
    return out.to_dict("records")


def _run_and_capture(graph, input_val, config: dict) -> tuple[list, dict, bool]:
    """
    Stream a LangGraph run and return (events, final_state_dict, is_interrupted).
    Collects state from events directly — avoids relying on get_state after END
    which can return None on some LangGraph versions.
    """
    events = []
    merged: dict = {}

    for event in graph.stream(input_val, config, stream_mode="updates"):
        events.append(event)
        for node, update in event.items():
            if node == "__interrupt__":
                continue
            for k, v in update.items():
                if k == "messages":
                    merged.setdefault("messages", [])
                    merged["messages"] = merged["messages"] + (v if isinstance(v, list) else [v])
                else:
                    merged[k] = v

    # Confirm interrupt/done via get_state; fall back gracefully if values is None
    snap = graph.get_state(config)
    interrupted = bool(snap.next) if snap else False

    # Prefer get_state values (most complete), fall back to merged events
    final_state = {}
    if snap and snap.values:
        final_state = dict(snap.values)
    else:
        final_state = merged

    return events, final_state, interrupted


def parse_uploaded_file(uploaded_file) -> pd.DataFrame:
    """Parse a user-uploaded IC CSV into the internal DataFrame format."""
    df = pd.read_csv(uploaded_file)

    # Normalise column names: lowercase + underscores
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]

    # Validate required columns
    required = ["reference", "entity", "counterparty", "amount_usd", "posting_date"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    # Parse dates and derive period
    df["posting_date"] = pd.to_datetime(df["posting_date"], dayfirst=False)
    df["period"] = df["posting_date"].dt.strftime("%Y-%m")

    # Derive pair_id from the Reference column (same reference = same IC pair)
    df["pair_id"] = df["reference"].astype(str).apply(lambda r: f"PAIR-{r}")

    # Generate unique tx_id per row
    df["tx_id"] = [f"TX-{i+1:04d}" for i in range(len(df))]

    # Infer DR/CR side from account name
    def _infer_side(account: str) -> str:
        acct = str(account).lower()
        cr_keywords = ["sales", "revenue", "income", "payable", "dividends paid", "royalties receivable"]
        dr_keywords = ["purchases", "expense", "receivable", "loans receivable"]
        if any(k in acct for k in cr_keywords):
            return "CR"
        if any(k in acct for k in dr_keywords):
            return "DR"
        return "CR"  # default

    if "account" not in df.columns:
        df["account"] = "Intercompany Account"
    df["side"] = df["account"].apply(_infer_side)

    # Optional columns — fill with sensible defaults if absent
    if "tx_type" not in df.columns:
        df["tx_type"] = "Trade"
    if "currency" not in df.columns:
        df["currency"] = "USD"
    if "amount_local" not in df.columns:
        df["amount_local"] = df["amount_usd"]
    if "description" not in df.columns:
        df["description"] = df.apply(
            lambda r: f"{r['tx_type']} from {r['entity']} to {r['counterparty']}", axis=1
        )

    # Placeholders filled in by the matching engine later
    df["status"] = "Pending"
    df["mismatch_reason"] = None
    df["variance_usd"] = 0.0

    df["amount_usd"] = pd.to_numeric(df["amount_usd"], errors="coerce").fillna(0.0)
    df["amount_local"] = pd.to_numeric(df["amount_local"], errors="coerce").fillna(0.0)

    return df


# ─────────────────────────────────────────────────────────────
# AI ASSISTANT (Claude API)
# ─────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are a senior financial controller specialising in intercompany (IC) elimination for consolidated financial close under IFRS 10 and US GAAP ASC 810.

You help finance teams:
- Identify IC mismatches and their root causes (FX differences, timing, system gaps)
- Prepare correct elimination journal entries (trading, loans, dividends, services, royalties)
- Understand consolidation rules and common pitfalls
- Accelerate the month-end / quarter-end close cycle

Be precise, reference standards where helpful, and provide concrete journal entry examples. Keep responses concise.

You have access to a real-time summary of the user's IC dataset, which you can reference when answering questions."""


def get_data_context(df):
    total_vol = df["amount_usd"].sum()
    matched_vol = df[df["status"] == "Matched"]["amount_usd"].sum()
    mismatches = (df["status"] == "Mismatch").sum()
    unmatched = (df["status"] == "Unmatched").sum()
    return (
        f"\nCurrent IC Dataset:\n"
        f"- Transactions: {len(df)} across {df['entity'].nunique()} entities\n"
        f"- Total IC volume: ${total_vol:,.0f} USD\n"
        f"- Matched volume: ${matched_vol:,.0f} ({matched_vol/total_vol*100:.1f}%)\n"
        f"- Mismatched rows: {mismatches} | Unmatched (orphan) rows: {unmatched}\n"
        f"- Periods: {', '.join(sorted(df['period'].unique()))}\n"
        f"- Entities: {', '.join(df['entity'].unique())}\n"
    )


def ask_claude(messages, data_context, api_key):
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=SYSTEM_PROMPT + "\n" + data_context,
        messages=messages,
    )
    return response.content[0].text


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────
def main():
    st.title("🏦 Intercompany Elimination Engine")
    st.caption("AI-powered financial close · Automated IC matching · Elimination journal generation · Mismatch resolution")

    # ── Session state init ───────────────────────────────────
    if "ic_thread_id" not in st.session_state:
        st.session_state.ic_thread_id = None
    if "ic_messages" not in st.session_state:
        st.session_state.ic_messages = []
    if "ic_thread_title" not in st.session_state:
        st.session_state.ic_thread_title = None
    # Pipeline state
    if "pipeline_thread" not in st.session_state:
        st.session_state.pipeline_thread = None
    if "pipeline_events" not in st.session_state:
        st.session_state.pipeline_events = []
    if "pipeline_state" not in st.session_state:
        st.session_state.pipeline_state = {}
    if "pipeline_interrupted" not in st.session_state:
        st.session_state.pipeline_interrupted = False
    if "pipeline_complete" not in st.session_state:
        st.session_state.pipeline_complete = False
    if "pipeline_config" not in st.session_state:
        st.session_state.pipeline_config = None

    # ── Sidebar ──────────────────────────────────────────────
    with st.sidebar:
        st.header("⚙️ Controls")

        # ── File upload ──────────────────────────────────────
        st.subheader("📂 Data Source")
        with open("sample_ic_upload.csv", "rb") as f:
            st.download_button(
                "⬇ Download Sample Format (CSV)",
                f, "sample_ic_upload.csv", "text/csv",
                help="Download the template, fill with your IC data, then upload below.",
            )
        uploaded_file = st.file_uploader(
            "Upload IC Transactions (CSV)",
            type=["csv"],
            help="Must match the sample format. See required columns in the download above.",
        )

        upload_error = None
        if uploaded_file:
            try:
                uploaded_df = parse_uploaded_file(uploaded_file)
                st.success(f"Loaded {len(uploaded_df)} rows from {uploaded_file.name}")
            except ValueError as e:
                upload_error = str(e)
                uploaded_df = None
                st.error(f"Upload error: {e}")
        else:
            uploaded_df = None

        st.divider()

        if uploaded_df is not None:
            periods = sorted(uploaded_df["period"].unique().tolist())
        else:
            periods = ["2025-01", "2025-02", "2025-03"]
        period_options = ["All"] + periods
        selected_period = st.selectbox("Period", period_options)
        selected_entities = st.multiselect(
            "Filter Entities", options=list(ENTITIES.keys()), default=list(ENTITIES.keys())
        )
        selected_types = st.multiselect(
            "Transaction Types", options=list(IC_ACCOUNT_PAIRS.keys()), default=list(IC_ACCOUNT_PAIRS.keys())
        )

        st.divider()
        st.subheader("🤖 AI Assistant")
        _sidebar_key = st.text_input("Anthropic API Key", type="password", placeholder="sk-ant-...")
        api_key = _resolve_api_key(_sidebar_key)

        if st.button("➕ New Chat"):
            st.session_state.ic_thread_id = None
            st.session_state.ic_messages = []
            st.session_state.ic_thread_title = None

        st.subheader("My Conversations")
        for thread_id, title in reversed(load_threads()):
            col_btn, col_del = st.columns([4, 1])
            if col_btn.button(title, key=f"ic-thread-{thread_id}"):
                st.session_state.ic_thread_id = thread_id
                st.session_state.ic_thread_title = title
                st.session_state.ic_messages = load_messages(thread_id)
            if col_del.button("🗑", key=f"ic-del-{thread_id}"):
                delete_thread(thread_id)
                if st.session_state.ic_thread_id == thread_id:
                    st.session_state.ic_thread_id = None
                    st.session_state.ic_messages = []
                    st.session_state.ic_thread_title = None
                st.rerun()

        st.divider()
        st.subheader("💰 ROI Assumptions")
        fte_rate = st.number_input("FTE Hourly Rate ($)", value=75, step=5)
        hrs_per_pair = st.number_input("Manual Hrs / Entity Pair / Month", value=2.0, step=0.5)
        num_pairs = st.number_input("Number of Entity Pairs", value=28, step=1)

    # ── Load & filter data ───────────────────────────────────
    if uploaded_df is not None:
        df = uploaded_df.copy()
        st.info(f"Using uploaded file: **{uploaded_file.name}** ({len(df)} transactions)")
    else:
        df = generate_transactions()

    if selected_period != "All":
        df = df[df["period"] == selected_period]
    if selected_entities and "entity" in df.columns:
        df = df[df["entity"].isin(selected_entities)]
    if selected_types and "tx_type" in df.columns:
        df = df[df["tx_type"].isin(selected_types)]

    elim_df = build_eliminations(df)

    # ── KPI row ──────────────────────────────────────────────
    total_vol = df["amount_usd"].sum()
    matched_cnt = (df["status"] == "Matched").sum()
    mismatch_cnt = (df["status"] == "Mismatch").sum()
    unmatched_cnt = (df["status"] == "Unmatched").sum()
    match_rate = matched_cnt / len(df) * 100 if len(df) > 0 else 0

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("IC Volume (USD)", f"${total_vol/1e6:.1f}M")
    c2.metric("Transactions", len(df))
    c3.metric("Match Rate", f"{match_rate:.1f}%", delta=f"+{match_rate-72:.1f}% vs manual")
    c4.metric("Mismatches", mismatch_cnt, delta=f"-{mismatch_cnt}", delta_color="inverse")
    c5.metric("Unmatched", unmatched_cnt, delta=f"{unmatched_cnt} need review", delta_color="inverse")

    st.divider()

    # ── Tabs ─────────────────────────────────────────────────
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "📊 IC Overview",
        "⚙️ Elimination Engine",
        "⚠️ Exceptions",
        "📒 Journal Entries",
        "💰 ROI Dashboard",
        "🔄 IC Close Pipeline",
    ])

    # ── Tab 1: Overview ──────────────────────────────────────
    with tab1:
        col_l, col_r = st.columns(2)

        with col_l:
            st.subheader("IC Volume by Entity")
            ev = df.groupby("entity")["amount_usd"].sum().reset_index().sort_values("amount_usd")
            fig = px.bar(ev, x="amount_usd", y="entity", orientation="h",
                         labels={"amount_usd": "USD", "entity": ""},
                         color="amount_usd", color_continuous_scale="Blues")
            fig.update_layout(coloraxis_showscale=False, height=340)
            st.plotly_chart(fig, use_container_width=True)

        with col_r:
            st.subheader("Status Breakdown")
            sc = df["status"].value_counts().reset_index()
            sc.columns = ["Status", "Count"]
            colors = {"Matched": "#1976D2", "Mismatch": "#F57C00", "Unmatched": "#D32F2F"}
            fig2 = px.pie(sc, values="Count", names="Status",
                          color="Status", color_discrete_map=colors, hole=0.45)
            fig2.update_layout(height=340)
            st.plotly_chart(fig2, use_container_width=True)

        st.subheader("IC Flow Matrix — Seller → Buyer (USD Millions)")
        pivot = (
            df[df["side"] == "CR"]
            .pivot_table(index="entity", columns="counterparty", values="amount_usd", aggfunc="sum", fill_value=0)
        )
        if not pivot.empty:
            fig3 = px.imshow(
                pivot / 1e6, text_auto=".1f", aspect="auto",
                color_continuous_scale="Blues", labels={"color": "USD M"},
            )
            fig3.update_layout(height=380)
            st.plotly_chart(fig3, use_container_width=True)

        st.subheader("Volume by Transaction Type")
        tv = df.groupby(["tx_type", "status"])["amount_usd"].sum().reset_index()
        fig4 = px.bar(tv, x="tx_type", y="amount_usd", color="status",
                      color_discrete_map=colors,
                      labels={"tx_type": "Type", "amount_usd": "USD", "status": "Status"},
                      barmode="stack")
        fig4.update_layout(height=320)
        st.plotly_chart(fig4, use_container_width=True)

    # ── Tab 2: Elimination Engine ─────────────────────────────
    with tab2:
        st.subheader("AI Elimination Matching Engine")

        if elim_df.empty:
            st.info("No fully matched pairs in the current filter selection.")
        else:
            ca, cb, cc = st.columns(3)
            ca.metric("Pairs Ready to Eliminate", len(elim_df))
            cb.metric("Value to Eliminate", f"${elim_df['amount_usd'].sum()/1e6:.1f}M")
            cc.metric("Avg Confidence", f"{elim_df['confidence'].mean():.0f}%")

            display = elim_df.copy()
            display["Amount (USD)"] = display["amount_usd"].apply(lambda x: f"${x:,.0f}")
            st.dataframe(
                display[["pair_id", "type", "entity_a", "entity_b",
                          "elim_dr_account", "elim_cr_account", "Amount (USD)", "confidence", "period"]].rename(columns={
                    "pair_id": "Pair ID", "type": "Type",
                    "entity_a": "Entity A", "entity_b": "Entity B",
                    "elim_dr_account": "Elim DR", "elim_cr_account": "Elim CR",
                    "confidence": "Confidence %", "period": "Period",
                }),
                use_container_width=True, hide_index=True,
                column_config={"Confidence %": st.column_config.ProgressColumn(min_value=0, max_value=100)},
            )
            csv = elim_df.to_csv(index=False)
            st.download_button("⬇ Download Elimination List (CSV)", csv, "eliminations.csv", "text/csv")

    # ── Tab 3: Exceptions ────────────────────────────────────
    with tab3:
        st.subheader("Exceptions & Mismatches")
        exc = df[df["status"].isin(["Mismatch", "Unmatched"])].copy()

        if exc.empty:
            st.success("No exceptions for the current selection.")
        else:
            exc["Variance (USD)"] = exc["variance_usd"].apply(lambda x: f"${x:,.0f}" if x > 0 else "—")
            exc["Risk"] = exc["variance_usd"].apply(
                lambda x: "🔴 High" if x > 100_000 else ("🟡 Medium" if x > 10_000 else "🟢 Low")
            )
            st.dataframe(
                exc[["tx_id", "entity", "counterparty", "account", "amount_usd",
                     "Variance (USD)", "mismatch_reason", "Risk", "posting_date"]].rename(columns={
                    "tx_id": "TX ID", "entity": "Entity", "counterparty": "Counterparty",
                    "account": "Account", "amount_usd": "Amount (USD)",
                    "mismatch_reason": "Root Cause", "posting_date": "Date",
                }),
                use_container_width=True, hide_index=True,
                column_config={"Amount (USD)": st.column_config.NumberColumn(format="$%.0f")},
            )

            st.subheader("Mismatch Root Cause Analysis")
            rc = exc["mismatch_reason"].value_counts().reset_index()
            rc.columns = ["Reason", "Count"]
            fig = px.bar(rc, x="Count", y="Reason", orientation="h",
                         color="Count", color_continuous_scale="Reds")
            fig.update_layout(coloraxis_showscale=False, height=280)
            st.plotly_chart(fig, use_container_width=True)

            csv_exc = exc.to_csv(index=False)
            st.download_button("⬇ Download Exceptions (CSV)", csv_exc, "ic_exceptions.csv", "text/csv")

    # ── Tab 4: Journal Entries ────────────────────────────────
    with tab4:
        st.subheader("Auto-Generated Elimination Journal Entries")

        if elim_df.empty:
            st.info("No matched pairs to generate journal entries for.")
        else:
            je_rows = []
            for _, row in elim_df.iterrows():
                ref = f"JE-ELIM-{row['pair_id']}"
                desc = f"Eliminate IC {row['type']}: {row['entity_a']} ↔ {row['entity_b']}"
                je_rows += [
                    {"JE Ref": ref, "Description": desc, "Account": row["elim_dr_account"],
                     "DR/CR": "DR", "Amount (USD)": row["amount_usd"], "Period": row["period"]},
                    {"JE Ref": ref, "Description": desc, "Account": row["elim_cr_account"],
                     "DR/CR": "CR", "Amount (USD)": row["amount_usd"], "Period": row["period"]},
                ]

            je_df = pd.DataFrame(je_rows)

            dr_total = je_df[je_df["DR/CR"] == "DR"]["Amount (USD)"].sum()
            cr_total = je_df[je_df["DR/CR"] == "CR"]["Amount (USD)"].sum()
            balanced = abs(dr_total - cr_total) < 0.01

            if balanced:
                st.success(f"✅ Balanced — DR = CR = ${dr_total:,.0f}")
            else:
                st.error(f"⚠️ Out of balance: DR ${dr_total:,.0f} vs CR ${cr_total:,.0f}")

            st.dataframe(
                je_df,
                use_container_width=True, hide_index=True,
                column_config={"Amount (USD)": st.column_config.NumberColumn(format="$%.0f")},
            )

            csv_je = je_df.to_csv(index=False)
            st.download_button("⬇ Download Journal Entries (CSV)", csv_je, "elimination_je.csv", "text/csv")

    # ── Tab 5: ROI Dashboard ─────────────────────────────────
    with tab5:
        st.subheader("ROI Impact Dashboard")

        manual_hrs = hrs_per_pair * num_pairs
        ai_hrs = manual_hrs * 0.12
        hrs_saved = manual_hrs - ai_hrs
        monthly_saving = hrs_saved * fte_rate
        annual_saving = monthly_saving * 12
        impl_cost = 120_000
        payback = impl_cost / monthly_saving if monthly_saving > 0 else 0
        roi_3yr = (annual_saving * 3 - impl_cost) / impl_cost * 100 if impl_cost > 0 else 0

        r1, r2, r3, r4 = st.columns(4)
        r1.metric("Annual Cost Savings", f"${annual_saving:,.0f}")
        r2.metric("Hours Saved / Month", f"{hrs_saved:.0f} h", delta=f"{hrs_saved/manual_hrs*100:.0f}% reduction")
        r3.metric("Payback Period", f"{payback:.1f} months")
        r4.metric("3-Year ROI", f"{roi_3yr:.0f}%")

        st.divider()

        col_l, col_r = st.columns(2)

        with col_l:
            fig = go.Figure(go.Waterfall(
                orientation="v",
                measure=["absolute", "relative", "total"],
                x=["Manual Process", "AI Savings", "Residual (Human Review)"],
                y=[manual_hrs, -hrs_saved, ai_hrs],
                decreasing={"marker": {"color": "#4CAF50"}},
                increasing={"marker": {"color": "#F44336"}},
                totals={"marker": {"color": "#1976D2"}},
            ))
            fig.update_layout(title="Monthly Hours: Manual vs AI-Assisted", height=340)
            st.plotly_chart(fig, use_container_width=True)

        with col_r:
            months = list(range(1, 13))
            cumulative = [monthly_saving * m for m in months]
            fig2 = px.area(x=months, y=cumulative,
                           labels={"x": "Month", "y": "Cumulative Savings (USD)"},
                           title="Cumulative 12-Month Savings Projection")
            fig2.update_traces(fill="tozeroy", line_color="#1976D2")
            fig2.update_layout(height=340)
            st.plotly_chart(fig2, use_container_width=True)

        st.subheader("ROI Summary")
        roi_tbl = pd.DataFrame({
            "Metric": [
                "Manual hours / month", "AI-assisted hours / month", "Hours saved / month",
                "Monthly cost saving", "Annual cost saving",
                "Estimated implementation cost", "Payback period", "3-Year ROI",
            ],
            "Value": [
                f"{manual_hrs:.0f} h", f"{ai_hrs:.0f} h", f"{hrs_saved:.0f} h",
                f"${monthly_saving:,.0f}", f"${annual_saving:,.0f}",
                f"${impl_cost:,.0f}", f"{payback:.1f} months", f"{roi_3yr:.0f}%",
            ],
        })
        st.table(roi_tbl)

    # ── Tab 6: IC Close Pipeline ─────────────────────────────
    with tab6:
        st.subheader("🔄 IC Close Pipeline — Multi-Agent LangGraph")
        st.caption(
            "Agents: **Matching** → **Exception Analyser** → **JE Generator** → "
            "**Human Review** (interrupt) → **Validator** → **Summarise**"
        )

        if not api_key:
            st.info("Enter your Anthropic API key in the sidebar to run the pipeline.")
        else:
            NODE_LABELS = {
                "matching":           "🔍 Step 1 — IC Matching",
                "exception_analyzer": "⚠️  Step 2 — Exception Analysis",
                "je_generator":       "📒 Step 3 — Journal Entry Generation",
                "validator":          "✅ Step 4 — Validation",
                "summarize":          "📝 Step 5 — Executive Summary",
            }

            col_run, col_reset = st.columns([2, 1])

            with col_run:
                run_clicked = st.button("▶ Run IC Close Pipeline", type="primary", use_container_width=True)

            with col_reset:
                if st.button("↺ Reset", use_container_width=True):
                    st.session_state.pipeline_thread = None
                    st.session_state.pipeline_events = []
                    st.session_state.pipeline_state = {}
                    st.session_state.pipeline_interrupted = False
                    st.session_state.pipeline_complete = False
                    st.session_state.pipeline_config = None
                    st.rerun()

            if run_clicked:
                thread_id = str(uuid.uuid4())
                config = {"configurable": {"thread_id": thread_id}}
                records = df_to_records(df)
                initial_state = dict(
                    messages=[],
                    transactions=records,
                    matched_pairs=[], exceptions=[],
                    journal_entries=[], validation_result={},
                    period=selected_period if selected_period != "All" else "2025-Q1",
                    human_approved=None, rejection_reason="",
                    run_summary="", api_key=api_key,
                )
                st.session_state.pipeline_thread = thread_id
                st.session_state.pipeline_config = config
                st.session_state.pipeline_events = []
                st.session_state.pipeline_interrupted = False
                st.session_state.pipeline_complete = False

                with st.spinner("Running pipeline agents…"):
                    new_events, final_state, interrupted = _run_and_capture(ic_graph, initial_state, config)
                    st.session_state.pipeline_events.extend(new_events)
                    st.session_state.pipeline_state = final_state
                    st.session_state.pipeline_interrupted = interrupted
                st.rerun()

            # ── Progress log ─────────────────────────────────
            if st.session_state.pipeline_events:
                st.subheader("Pipeline Progress")
                for event in st.session_state.pipeline_events:
                    for node, update in event.items():
                        if node == "__interrupt__":
                            continue
                        label = NODE_LABELS.get(node, f"Node: {node}")
                        with st.expander(f"✅ {label}", expanded=False):
                            for msg in update.get("messages", []):
                                if hasattr(msg, "content"):
                                    st.markdown(msg.content)

            # ── Human review interrupt ────────────────────────
            ps = st.session_state.pipeline_state
            if st.session_state.pipeline_interrupted and not st.session_state.pipeline_complete:
                st.divider()
                st.subheader("👤 Human Review — Approval Required")
                st.warning(
                    "The pipeline is paused after journal entry generation. "
                    "Review the entries below, then **Approve** to post or **Reject** to re-analyse."
                )

                jes      = ps.get("journal_entries", [])
                matched  = ps.get("matched_pairs",   [])
                excepts  = ps.get("exceptions",       [])

                m1, m2, m3 = st.columns(3)
                m1.metric("Pairs to Eliminate",   len(matched))
                m2.metric("JE Lines Generated",   len(jes))
                m3.metric("Exceptions Flagged",   len(excepts))

                if jes:
                    je_preview = pd.DataFrame(jes)
                    dr_total = sum(j["amount_usd"] for j in jes if j["dr_cr"] == "DR")
                    cr_total = sum(j["amount_usd"] for j in jes if j["dr_cr"] == "CR")
                    balanced = abs(dr_total - cr_total) < 0.01

                    if balanced:
                        st.success(f"Pre-check: Balanced — DR = CR = ${dr_total:,.0f}")
                    else:
                        st.error(f"Pre-check: Out of balance — DR ${dr_total:,.0f} vs CR ${cr_total:,.0f}")

                    st.dataframe(
                        je_preview[["je_ref", "description", "account", "dr_cr", "amount_usd", "period"]].rename(columns={
                            "je_ref": "JE Ref", "description": "Description",
                            "account": "Account", "dr_cr": "DR/CR",
                            "amount_usd": "Amount (USD)", "period": "Period",
                        }),
                        use_container_width=True, hide_index=True,
                        column_config={"Amount (USD)": st.column_config.NumberColumn(format="$%.0f")},
                    )

                col_approve, col_reject = st.columns(2)

                with col_approve:
                    if st.button("✅ Approve & Post", type="primary", use_container_width=True):
                        config = st.session_state.pipeline_config
                        ic_graph.update_state(config, {"human_approved": True})
                        with st.spinner("Finalising…"):
                            new_events, final_state, interrupted = _run_and_capture(ic_graph, None, config)
                            st.session_state.pipeline_events.extend(new_events)
                            st.session_state.pipeline_state = final_state
                            st.session_state.pipeline_interrupted = interrupted
                            st.session_state.pipeline_complete = not interrupted
                        st.rerun()

                with col_reject:
                    reason = st.text_input("Rejection reason", placeholder="e.g. FX rates need restatement")
                    if st.button("❌ Reject & Re-analyse", use_container_width=True):
                        config = st.session_state.pipeline_config
                        ic_graph.update_state(config, {
                            "human_approved": False,
                            "rejection_reason": reason or "Rejected by reviewer",
                        })
                        with st.spinner("Re-analysing exceptions…"):
                            new_events, final_state, interrupted = _run_and_capture(ic_graph, None, config)
                            st.session_state.pipeline_events.extend(new_events)
                            st.session_state.pipeline_state = final_state
                            st.session_state.pipeline_interrupted = interrupted
                        st.rerun()

            # ── Final results ─────────────────────────────────
            if st.session_state.pipeline_complete:
                st.divider()
                st.subheader("✅ IC Close Complete")

                ps = st.session_state.pipeline_state or {}
                val = (ps.get("validation_result") or {})
                r1, r2, r3, r4 = st.columns(4)
                r1.metric("Validation", "PASSED" if val.get("passed") else "FAILED")
                r2.metric("Total Eliminated", f"${val.get('dr_total', 0)/1e6:.1f}M")
                r3.metric("Pairs Posted", val.get("pairs_in_je", 0))
                r4.metric("Exceptions", len(ps.get("exceptions", [])))

                summary = ps.get("run_summary", "")
                if summary:
                    st.info(f"**Executive Summary**\n\n{summary}")

                final_jes = ps.get("journal_entries", [])
                if final_jes:
                    csv_final = pd.DataFrame(final_jes).to_csv(index=False)
                    st.download_button(
                        "⬇ Download Final Journal Entries (CSV)",
                        csv_final, "posted_elimination_je.csv", "text/csv",
                    )

    # ── AI Assistant ─────────────────────────────────────────
    st.divider()
    st.subheader("🤖 AI Assistant — IC Elimination Expert")

    if not api_key:
        st.info("Enter your Anthropic API key in the sidebar to chat with the AI assistant.")
        return

    data_ctx = get_data_context(df)

    for msg in st.session_state.ic_messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if prompt := st.chat_input("Ask about eliminations, journal entries, mismatches, IFRS 10…"):
        # Create a new thread on the first message
        if st.session_state.ic_thread_id is None:
            st.session_state.ic_thread_id = str(uuid.uuid4())
            title = prompt.strip()[:40] + ("..." if len(prompt) > 40 else "")
            st.session_state.ic_thread_title = title
        else:
            title = st.session_state.ic_thread_title

        thread_id = st.session_state.ic_thread_id

        st.session_state.ic_messages.append({"role": "user", "content": prompt})
        save_message(thread_id, title, "user", prompt)
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner("Thinking…"):
                try:
                    reply = ask_claude(st.session_state.ic_messages, data_ctx, api_key)
                    st.markdown(reply)
                    st.session_state.ic_messages.append({"role": "assistant", "content": reply})
                    save_message(thread_id, title, "assistant", reply)
                except Exception as e:
                    st.error(f"API error: {e}")


if __name__ == "__main__":
    main()
