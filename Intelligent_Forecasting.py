import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
from io import BytesIO
import random
import json

# ─────────────────────────────────────────────────────────────
# PAGE CONFIG
# ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="AI Forecast Command Center",
    page_icon="🔮",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────────────────────
# CUSTOM STYLING
# ─────────────────────────────────────────────────────────────
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

    .block-container { padding-top: 1.5rem; }

    .main-header {
        background: linear-gradient(135deg, #0f172a 0%, #1e3a5f 50%, #0d9488 100%);
        padding: 1.8rem 2rem;
        border-radius: 14px;
        margin-bottom: 1.5rem;
        color: white;
        font-family: 'Inter', sans-serif;
    }
    .main-header h1 {
        font-size: 1.85rem;
        font-weight: 700;
        margin: 0 0 0.3rem 0;
        letter-spacing: -0.5px;
    }
    .main-header p {
        font-size: 0.95rem;
        opacity: 0.88;
        margin: 0;
    }

    .kpi-card {
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 12px;
        padding: 1.2rem 1.4rem;
        text-align: center;
        box-shadow: 0 1px 4px rgba(0,0,0,0.04);
        transition: transform 0.15s ease;
    }
    .kpi-card:hover { transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,0.08); }
    .kpi-label { font-size: 0.78rem; color: #64748b; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; }
    .kpi-value { font-size: 1.65rem; font-weight: 700; color: #0f172a; margin: 0.3rem 0; }
    .kpi-delta-pos { font-size: 0.82rem; color: #059669; font-weight: 600; }
    .kpi-delta-neg { font-size: 0.82rem; color: #dc2626; font-weight: 600; }

    .ai-insight-box {
        background: linear-gradient(135deg, #f0fdfa 0%, #e0f2fe 100%);
        border-left: 4px solid #0d9488;
        border-radius: 0 10px 10px 0;
        padding: 1rem 1.3rem;
        margin: 0.6rem 0;
        font-size: 0.88rem;
        color: #134e4a;
        line-height: 1.55;
    }
    .ai-insight-box strong { color: #0f766e; }

    .anomaly-badge {
        display: inline-block;
        padding: 3px 10px;
        border-radius: 20px;
        font-size: 0.75rem;
        font-weight: 600;
    }
    .anomaly-high { background: #fef2f2; color: #dc2626; border: 1px solid #fca5a5; }
    .anomaly-med { background: #fffbeb; color: #d97706; border: 1px solid #fcd34d; }
    .anomaly-low { background: #f0fdf4; color: #16a34a; border: 1px solid #86efac; }

    .scenario-card {
        border-radius: 10px;
        padding: 1rem 1.2rem;
        margin: 0.4rem 0;
        font-size: 0.88rem;
    }
    .scenario-base { background: #eff6ff; border: 1px solid #93c5fd; color: #1e40af; }
    .scenario-bull { background: #f0fdf4; border: 1px solid #86efac; color: #166534; }
    .scenario-bear { background: #fef2f2; border: 1px solid #fca5a5; color: #991b1b; }

    div[data-testid="stTabs"] button {
        font-weight: 600;
        font-size: 0.9rem;
    }

    .stDownloadButton > button {
        background: #0f172a !important;
        color: white !important;
        border-radius: 8px !important;
        font-weight: 600 !important;
    }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────
# SAMPLE DATA GENERATION
# ─────────────────────────────────────────────────────────────
@st.cache_data
def generate_sample_data(seed=42):
    """Generate 30 months of actuals + 12 months forecast for a multi-entity, multi-cost-centre structure."""
    random.seed(seed)
    np.random.seed(seed)

    entities = [
        "EBIC (Egypt)", "Sorfert (Algeria)", "EFC (Egypt)",
        "Fertil (UAE)", "MENA BV (Netherlands)", "Fertiglobe HQ (UAE)"
    ]

    cost_centres = {
        "Production":       {"base_monthly": 18_500_000, "seasonality": [1.08, 1.05, 1.00, 0.95, 0.92, 0.90, 0.88, 0.90, 0.95, 1.02, 1.08, 1.12], "growth": 0.03},
        "Logistics":        {"base_monthly":  6_200_000, "seasonality": [0.95, 0.95, 1.00, 1.05, 1.08, 1.10, 1.12, 1.10, 1.05, 1.00, 0.95, 0.90], "growth": 0.04},
        "Sales & Marketing":{"base_monthly":  4_800_000, "seasonality": [0.85, 0.90, 1.00, 1.10, 1.15, 1.20, 1.18, 1.15, 1.10, 1.00, 0.90, 0.85], "growth": 0.05},
        "G&A":              {"base_monthly":  3_100_000, "seasonality": [1.00]*12, "growth": 0.02},
        "R&D / Technical":  {"base_monthly":  2_400_000, "seasonality": [1.05, 1.05, 1.00, 0.95, 0.95, 0.90, 0.90, 0.95, 1.00, 1.05, 1.10, 1.10], "growth": 0.03},
        "Energy & Utilities":{"base_monthly": 8_900_000, "seasonality": [1.15, 1.12, 1.05, 0.95, 0.88, 0.82, 0.80, 0.82, 0.90, 1.00, 1.10, 1.18], "growth": 0.06},
    }

    revenue_drivers = {
        "Urea – Domestic":   {"base_monthly": 22_000_000, "seasonality": [0.85, 0.90, 1.05, 1.15, 1.20, 1.18, 1.10, 1.05, 1.00, 0.95, 0.88, 0.82], "growth": 0.04},
        "Urea – Export":     {"base_monthly": 15_000_000, "seasonality": [0.80, 0.85, 1.00, 1.10, 1.20, 1.25, 1.20, 1.15, 1.05, 0.95, 0.85, 0.78], "growth": 0.05},
        "Ammonia – Domestic":{"base_monthly":  9_500_000, "seasonality": [1.00, 1.00, 1.05, 1.08, 1.10, 1.05, 1.00, 0.98, 0.95, 0.95, 1.00, 1.02], "growth": 0.03},
        "Ammonia – Export":  {"base_monthly":  7_200_000, "seasonality": [0.90, 0.92, 1.00, 1.08, 1.15, 1.18, 1.15, 1.10, 1.02, 0.95, 0.88, 0.85], "growth": 0.06},
        "DEF / AdBlue":      {"base_monthly":  3_800_000, "seasonality": [0.95, 0.95, 1.00, 1.05, 1.10, 1.12, 1.10, 1.08, 1.05, 1.00, 0.95, 0.92], "growth": 0.08},
    }

    # Generate 30 months of actuals (Jan 2024 – Jun 2026) + 12 months forecast (Jul 2026 – Jun 2027)
    actual_start = datetime(2024, 1, 1)
    records = []

    for line_type, items in [("Cost", cost_centres), ("Revenue", revenue_drivers)]:
        for item_name, params in items.items():
            for entity in entities:
                entity_scale = random.uniform(0.08, 0.35)
                for m in range(42):  # 30 actuals + 12 forecast
                    month_dt = actual_start + timedelta(days=m * 30)
                    month_dt = datetime(actual_start.year + (actual_start.month + m - 1) // 12,
                                        ((actual_start.month + m - 1) % 12) + 1, 1)
                    month_idx = month_dt.month - 1
                    year_offset = (month_dt.year - 2024)

                    base = params["base_monthly"] * entity_scale
                    seasonal = params["seasonality"][month_idx]
                    growth_factor = (1 + params["growth"]) ** year_offset
                    trend = base * seasonal * growth_factor

                    is_actual = m < 30
                    noise = np.random.normal(1.0, 0.06 if is_actual else 0.03)
                    amount = trend * noise

                    # Budget — set at start of year with 5% optimism bias for revenue, 3% undershoot for cost
                    if line_type == "Revenue":
                        budget_amount = trend * random.uniform(1.02, 1.08)
                    else:
                        budget_amount = trend * random.uniform(0.94, 1.01)

                    # AI forecast (simulated) — tighter than budget, incorporating recent trend
                    ai_forecast = trend * random.uniform(0.97, 1.03)

                    records.append({
                        "Entity": entity,
                        "Line_Type": line_type,
                        "Category": item_name,
                        "Period": month_dt.strftime("%Y-%m"),
                        "Period_Date": month_dt,
                        "Month": month_dt.strftime("%b %Y"),
                        "Is_Actual": is_actual,
                        "Actual": round(amount, 2) if is_actual else None,
                        "Budget": round(budget_amount, 2),
                        "AI_Forecast": round(ai_forecast, 2),
                        "Seasonality_Index": round(seasonal, 3),
                    })

    df = pd.DataFrame(records)

    # ── Inject anomalies (5-8%) into actuals ──
    actual_mask = df["Is_Actual"] == True
    n_anomalies = int(actual_mask.sum() * 0.06)
    anomaly_indices = np.random.choice(df[actual_mask].index, size=n_anomalies, replace=False)

    anomaly_types = ["Spike", "Drop", "Timing Shift", "Reclassification"]
    anomaly_records = []
    for idx in anomaly_indices:
        a_type = random.choice(anomaly_types)
        if a_type == "Spike":
            df.loc[idx, "Actual"] *= random.uniform(1.25, 1.65)
        elif a_type == "Drop":
            df.loc[idx, "Actual"] *= random.uniform(0.45, 0.75)
        elif a_type == "Timing Shift":
            df.loc[idx, "Actual"] *= random.uniform(1.15, 1.40)
        else:
            df.loc[idx, "Actual"] *= random.uniform(0.70, 0.88)

        anomaly_records.append({"index": idx, "type": a_type})

    df["Actual"] = df["Actual"].apply(lambda x: round(x, 2) if pd.notna(x) else x)

    return df, anomaly_records


# ─────────────────────────────────────────────────────────────
# AI ENGINE — SIMULATED INTELLIGENCE
# ─────────────────────────────────────────────────────────────
def detect_anomalies(df, z_threshold=2.0):
    """Detect anomalies in actuals vs budget/forecast using z-score and variance logic."""
    actuals = df[df["Is_Actual"] == True].copy()
    if actuals.empty:
        return pd.DataFrame()

    actuals["Var_vs_Budget_Pct"] = ((actuals["Actual"] - actuals["Budget"]) / actuals["Budget"] * 100).round(2)
    actuals["Var_vs_Forecast_Pct"] = ((actuals["Actual"] - actuals["AI_Forecast"]) / actuals["AI_Forecast"] * 100).round(2)

    # Z-score within each category
    anomalies = []
    for cat in actuals["Category"].unique():
        cat_data = actuals[actuals["Category"] == cat].copy()
        if len(cat_data) < 4:
            continue
        mean_val = cat_data["Actual"].mean()
        std_val = cat_data["Actual"].std()
        if std_val == 0:
            continue
        cat_data["Z_Score"] = ((cat_data["Actual"] - mean_val) / std_val).round(3)
        cat_data["Is_Anomaly"] = cat_data["Z_Score"].abs() > z_threshold

        for _, row in cat_data[cat_data["Is_Anomaly"]].iterrows():
            severity = "High" if abs(row["Z_Score"]) > 3.0 else ("Medium" if abs(row["Z_Score"]) > 2.5 else "Low")
            var_pct = row["Var_vs_Budget_Pct"]
            direction = "above" if var_pct > 0 else "below"

            # Generate NL explanation
            explanation = _generate_anomaly_explanation(row, severity, direction)

            anomalies.append({
                "Period": row["Period"],
                "Entity": row["Entity"],
                "Category": row["Category"],
                "Line_Type": row["Line_Type"],
                "Actual": row["Actual"],
                "Budget": row["Budget"],
                "Var_vs_Budget_%": var_pct,
                "Z_Score": row["Z_Score"],
                "Severity": severity,
                "AI_Explanation": explanation,
                "Confidence": round(min(98, 75 + abs(row["Z_Score"]) * 7), 1),
            })

    return pd.DataFrame(anomalies) if anomalies else pd.DataFrame()


def _generate_anomaly_explanation(row, severity, direction):
    """Generate natural-language anomaly explanation."""
    templates_spike = [
        f"**{row['Category']}** in {row['Entity']} is {abs(row['Var_vs_Budget_Pct']):.1f}% {direction} budget for {row['Period']}. "
        f"Z-score of {abs(row['Z_Score']):.2f} indicates a statistically significant deviation. "
        f"Possible drivers: seasonal demand surge, contract re-pricing, or one-time procurement adjustment.",

        f"Unusual spike detected in **{row['Category']}** ({row['Entity']}, {row['Period']}). "
        f"Actual of ${row['Actual']:,.0f} vs budget ${row['Budget']:,.0f} ({abs(row['Var_vs_Budget_Pct']):.1f}% variance). "
        f"Recommend cross-referencing with PO log and checking for bulk/pre-buy activity.",
    ]
    templates_drop = [
        f"**{row['Category']}** in {row['Entity']} is {abs(row['Var_vs_Budget_Pct']):.1f}% {direction} budget for {row['Period']}. "
        f"This may signal delayed shipments, demand softening, or timing of revenue recognition. "
        f"AI confidence: {min(98, 75 + abs(row['Z_Score']) * 7):.0f}%.",

        f"Below-trend reading in **{row['Category']}** ({row['Entity']}, {row['Period']}). "
        f"Budget assumed ${row['Budget']:,.0f}, actual landed at ${row['Actual']:,.0f}. "
        f"Check for deferred invoicing or inventory build-up.",
    ]
    templates = templates_spike if direction == "above" else templates_drop
    return random.choice(templates)


def generate_variance_commentary(df):
    """Generate top-level NL variance commentary across categories."""
    actuals = df[df["Is_Actual"] == True].copy()
    if actuals.empty:
        return []

    latest_period = actuals["Period"].max()
    latest = actuals[actuals["Period"] == latest_period]

    commentaries = []
    for cat in latest["Category"].unique():
        cat_data = latest[latest["Category"] == cat]
        total_actual = cat_data["Actual"].sum()
        total_budget = cat_data["Budget"].sum()
        var_pct = (total_actual - total_budget) / total_budget * 100

        if abs(var_pct) > 3:
            direction = "exceeded" if var_pct > 0 else "fell short of"
            line_type = cat_data["Line_Type"].iloc[0]
            sentiment = ""
            if line_type == "Revenue":
                sentiment = "favourable" if var_pct > 0 else "unfavourable"
            else:
                sentiment = "unfavourable" if var_pct > 0 else "favourable"

            commentary = (
                f"**{cat}** {direction} budget by **{abs(var_pct):.1f}%** in {latest_period} "
                f"(${total_actual / 1e6:.1f}M actual vs ${total_budget / 1e6:.1f}M budget). "
                f"This is a **{sentiment}** variance. "
            )
            if abs(var_pct) > 10:
                commentary += "⚠️ Variance exceeds 10% — management review recommended."
            commentaries.append({"Category": cat, "Var_%": round(var_pct, 1), "Commentary": commentary, "Sentiment": sentiment})

    return sorted(commentaries, key=lambda x: abs(x["Var_%"]), reverse=True)


def build_scenario_forecast(df, scenario="base"):
    """Build scenario-based forecast adjustments."""
    forecast = df[df["Is_Actual"] == False].copy()
    multipliers = {
        "base":    {"Revenue": 1.00, "Cost": 1.00},
        "bull":    {"Revenue": 1.12, "Cost": 0.97},
        "bear":    {"Revenue": 0.88, "Cost": 1.06},
        "cost_cut":{"Revenue": 1.00, "Cost": 0.85},
    }
    m = multipliers.get(scenario, multipliers["base"])
    forecast["Scenario_Forecast"] = forecast.apply(
        lambda r: round(r["AI_Forecast"] * m[r["Line_Type"]], 2), axis=1
    )
    forecast["Scenario"] = scenario.replace("_", " ").title()
    return forecast


def compute_forecast_accuracy(df):
    """Compute rolling forecast accuracy metrics (simulated AI vs budget)."""
    actuals = df[df["Is_Actual"] == True].copy()
    if actuals.empty:
        return {}

    actuals["Budget_Error"] = ((actuals["Actual"] - actuals["Budget"]).abs() / actuals["Actual"].abs() * 100)
    actuals["AI_Error"] = ((actuals["Actual"] - actuals["AI_Forecast"]).abs() / actuals["Actual"].abs() * 100)

    return {
        "budget_mape": round(actuals["Budget_Error"].mean(), 2),
        "ai_mape": round(actuals["AI_Error"].mean(), 2),
        "budget_median_err": round(actuals["Budget_Error"].median(), 2),
        "ai_median_err": round(actuals["AI_Error"].median(), 2),
        "ai_improvement_pct": round(
            (1 - actuals["AI_Error"].mean() / actuals["Budget_Error"].mean()) * 100, 1
        ) if actuals["Budget_Error"].mean() > 0 else 0,
    }


# ─────────────────────────────────────────────────────────────
# ROI CALCULATOR
# ─────────────────────────────────────────────────────────────
def calculate_roi(manual_hours_monthly, fte_cost_annual, accuracy_improvement_pct, cycle_days_saved):
    ai_hours_monthly = manual_hours_monthly * 0.30  # 70% reduction
    hours_saved_monthly = manual_hours_monthly - ai_hours_monthly
    hourly_rate = fte_cost_annual / (52 * 40)
    monthly_savings = hours_saved_monthly * hourly_rate
    annual_savings = monthly_savings * 12

    error_cost_per_pct = 50_000  # cost of 1% forecast error
    accuracy_savings = accuracy_improvement_pct * error_cost_per_pct

    cycle_time_value = cycle_days_saved * 15_000  # value per day of faster close/forecast

    total_annual_benefit = annual_savings + accuracy_savings + cycle_time_value
    implementation_cost = 180_000  # estimated POC + deployment
    payback_months = (implementation_cost / (total_annual_benefit / 12)) if total_annual_benefit > 0 else 99

    return {
        "manual_hours_monthly": manual_hours_monthly,
        "ai_hours_monthly": round(ai_hours_monthly, 1),
        "hours_saved_monthly": round(hours_saved_monthly, 1),
        "hourly_rate": round(hourly_rate, 2),
        "monthly_savings": round(monthly_savings, 0),
        "annual_labour_savings": round(annual_savings, 0),
        "accuracy_savings": round(accuracy_savings, 0),
        "cycle_time_savings": round(cycle_time_value, 0),
        "total_annual_benefit": round(total_annual_benefit, 0),
        "implementation_cost": implementation_cost,
        "payback_months": round(payback_months, 1),
        "three_year_roi_pct": round(((total_annual_benefit * 3 - implementation_cost) / implementation_cost) * 100, 0),
    }


# ─────────────────────────────────────────────────────────────
# EXPORT HELPER
# ─────────────────────────────────────────────────────────────
def to_excel(dfs_dict):
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for sheet_name, df in dfs_dict.items():
            df.to_excel(writer, sheet_name=sheet_name[:31], index=False)
    return output.getvalue()


# ─────────────────────────────────────────────────────────────
# MAIN APP
# ─────────────────────────────────────────────────────────────
def main():
    # ── Header ──
    st.markdown("""
    <div class="main-header">
        <h1>🔮 AI Forecast Command Center</h1>
        <p>Intelligent FP&A — Driver-Based Forecasting · Anomaly Detection · Scenario Modelling · NL Variance Commentary</p>
    </div>
    """, unsafe_allow_html=True)

    # ── Load data ──
    df, anomaly_seeds = generate_sample_data()

    # ── Sidebar controls ──
    with st.sidebar:
        st.markdown("### ⚙️ Controls")

        selected_entities = st.multiselect(
            "Entities",
            options=df["Entity"].unique().tolist(),
            default=df["Entity"].unique().tolist(),
        )

        selected_categories = st.multiselect(
            "Categories",
            options=df["Category"].unique().tolist(),
            default=df["Category"].unique().tolist(),
        )

        line_type_filter = st.selectbox("Line Type", ["All", "Revenue", "Cost"])

        st.markdown("---")
        st.markdown("### 🎯 AI Settings")
        anomaly_threshold = st.slider("Anomaly Z-Score Threshold", 1.5, 3.5, 2.0, 0.1,
                                       help="Lower = more anomalies detected (higher recall). Higher = only extreme outliers (higher precision).")

        st.markdown("---")
        st.markdown("### 💰 ROI Assumptions")
        manual_hours = st.number_input("Manual FP&A Hours / Month", 80, 400, 160, 10)
        fte_cost = st.number_input("Annual FTE Cost ($)", 60_000, 250_000, 120_000, 5_000)
        accuracy_imp = st.slider("Forecast Accuracy Improvement (%)", 1, 15, 5)
        cycle_days = st.slider("Forecast Cycle Days Saved", 1, 10, 3)

    # ── Filter data ──
    filtered = df[
        (df["Entity"].isin(selected_entities)) &
        (df["Category"].isin(selected_categories))
    ].copy()
    if line_type_filter != "All":
        filtered = filtered[filtered["Line_Type"] == line_type_filter]

    # ── Compute metrics ──
    accuracy = compute_forecast_accuracy(filtered)
    anomalies_df = detect_anomalies(filtered, z_threshold=anomaly_threshold)
    commentaries = generate_variance_commentary(filtered)
    roi = calculate_roi(manual_hours, fte_cost, accuracy_imp, cycle_days)

    # ── KPI Row ──
    k1, k2, k3, k4, k5 = st.columns(5)
    with k1:
        st.markdown(f"""<div class="kpi-card">
            <div class="kpi-label">AI Forecast MAPE</div>
            <div class="kpi-value">{accuracy.get('ai_mape', 0):.1f}%</div>
            <div class="kpi-delta-pos">▼ {accuracy.get('ai_improvement_pct', 0):.0f}% vs Budget</div>
        </div>""", unsafe_allow_html=True)
    with k2:
        st.markdown(f"""<div class="kpi-card">
            <div class="kpi-label">Budget MAPE</div>
            <div class="kpi-value">{accuracy.get('budget_mape', 0):.1f}%</div>
            <div class="kpi-delta-neg">Baseline</div>
        </div>""", unsafe_allow_html=True)
    with k3:
        st.markdown(f"""<div class="kpi-card">
            <div class="kpi-label">Anomalies Detected</div>
            <div class="kpi-value">{len(anomalies_df)}</div>
            <div class="kpi-delta-neg">Threshold Z={anomaly_threshold:.1f}</div>
        </div>""", unsafe_allow_html=True)
    with k4:
        st.markdown(f"""<div class="kpi-card">
            <div class="kpi-label">Variance Alerts</div>
            <div class="kpi-value">{len(commentaries)}</div>
            <div class="kpi-delta-neg">&gt;3% threshold</div>
        </div>""", unsafe_allow_html=True)
    with k5:
        st.markdown(f"""<div class="kpi-card">
            <div class="kpi-label">Annual ROI</div>
            <div class="kpi-value">${roi['total_annual_benefit']:,.0f}</div>
            <div class="kpi-delta-pos">{roi['payback_months']:.0f} mo payback</div>
        </div>""", unsafe_allow_html=True)

    st.markdown("")

    # ── Tabs ──
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📈 Forecast vs Actuals", "🔍 Anomaly Detection", "🎭 Scenario Modelling",
        "💬 AI Commentary", "💰 ROI Dashboard"
    ])

    # ═══════════════════════════════════════════════════════════
    # TAB 1: FORECAST vs ACTUALS
    # ═══════════════════════════════════════════════════════════
    with tab1:
        st.markdown("#### Actuals vs Budget vs AI Forecast — Time Series")

        agg_level = st.radio("Aggregate by", ["Category", "Entity", "Line Type"], horizontal=True, key="agg1")
        agg_col = {"Category": "Category", "Entity": "Entity", "Line Type": "Line_Type"}[agg_level]

        ts_data = filtered.groupby(["Period", agg_col]).agg(
            Actual=("Actual", "sum"),
            Budget=("Budget", "sum"),
            AI_Forecast=("AI_Forecast", "sum"),
        ).reset_index()

        for grp_name in ts_data[agg_col].unique():
            grp = ts_data[ts_data[agg_col] == grp_name].sort_values("Period")
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=grp["Period"], y=grp["Actual"], name="Actual",
                                      line=dict(color="#0f172a", width=2.5), mode="lines+markers", marker=dict(size=4)))
            fig.add_trace(go.Scatter(x=grp["Period"], y=grp["Budget"], name="Budget",
                                      line=dict(color="#94a3b8", width=1.5, dash="dash"), mode="lines"))
            fig.add_trace(go.Scatter(x=grp["Period"], y=grp["AI_Forecast"], name="AI Forecast",
                                      line=dict(color="#0d9488", width=2), mode="lines"))

            # Shade forecast region
            forecast_start = filtered[filtered["Is_Actual"] == False]["Period"].min()
            if forecast_start:
                fig.add_vrect(x0=forecast_start, x1=grp["Period"].max(),
                              fillcolor="rgba(13,148,136,0.06)", line_width=0,
                              annotation_text="Forecast", annotation_position="top left")

            fig.update_layout(
                title=f"{grp_name}", height=360,
                template="plotly_white",
                legend=dict(orientation="h", y=-0.15),
                yaxis_title="Amount ($)",
                margin=dict(l=60, r=20, t=50, b=60),
                yaxis_tickformat="$,.0f",
            )
            st.plotly_chart(fig, use_container_width=True)

        # Accuracy comparison chart
        st.markdown("#### 🎯 Forecast Accuracy: AI vs Traditional Budget")
        acc_col1, acc_col2 = st.columns(2)
        with acc_col1:
            fig_acc = go.Figure(go.Bar(
                x=["Budget MAPE", "AI Forecast MAPE"],
                y=[accuracy.get("budget_mape", 0), accuracy.get("ai_mape", 0)],
                marker_color=["#94a3b8", "#0d9488"],
                text=[f"{accuracy.get('budget_mape', 0):.1f}%", f"{accuracy.get('ai_mape', 0):.1f}%"],
                textposition="outside",
            ))
            fig_acc.update_layout(title="Mean Absolute % Error (MAPE)", height=320, template="plotly_white",
                                  yaxis_title="MAPE %", margin=dict(t=50, b=40))
            st.plotly_chart(fig_acc, use_container_width=True)

        with acc_col2:
            fig_med = go.Figure(go.Bar(
                x=["Budget Median Error", "AI Median Error"],
                y=[accuracy.get("budget_median_err", 0), accuracy.get("ai_median_err", 0)],
                marker_color=["#94a3b8", "#0d9488"],
                text=[f"{accuracy.get('budget_median_err', 0):.1f}%", f"{accuracy.get('ai_median_err', 0):.1f}%"],
                textposition="outside",
            ))
            fig_med.update_layout(title="Median Absolute % Error", height=320, template="plotly_white",
                                  yaxis_title="Error %", margin=dict(t=50, b=40))
            st.plotly_chart(fig_med, use_container_width=True)

    # ═══════════════════════════════════════════════════════════
    # TAB 2: ANOMALY DETECTION
    # ═══════════════════════════════════════════════════════════
    with tab2:
        st.markdown("#### 🔍 AI-Powered Anomaly Detection")
        st.markdown(f"Scanning **{len(filtered[filtered['Is_Actual']==True])}** actual data points with Z-score threshold **{anomaly_threshold}**")

        if not anomalies_df.empty:
            # Summary by severity
            sev_counts = anomalies_df["Severity"].value_counts()
            s1, s2, s3 = st.columns(3)
            with s1:
                st.metric("🔴 High Severity", sev_counts.get("High", 0))
            with s2:
                st.metric("🟡 Medium Severity", sev_counts.get("Medium", 0))
            with s3:
                st.metric("🟢 Low Severity", sev_counts.get("Low", 0))

            # Anomaly scatter
            fig_anom = px.scatter(
                anomalies_df, x="Period", y="Var_vs_Budget_%",
                color="Severity", size="Confidence",
                color_discrete_map={"High": "#dc2626", "Medium": "#d97706", "Low": "#16a34a"},
                hover_data=["Entity", "Category", "Actual", "Budget"],
                title="Anomalies by Period & Variance",
            )
            fig_anom.update_layout(height=400, template="plotly_white")
            st.plotly_chart(fig_anom, use_container_width=True)

            # AI explanations
            st.markdown("#### 🤖 AI Explanations")
            for _, row in anomalies_df.sort_values("Confidence", ascending=False).head(10).iterrows():
                severity_class = {"High": "anomaly-high", "Medium": "anomaly-med", "Low": "anomaly-low"}[row["Severity"]]
                st.markdown(f"""
                <div class="ai-insight-box">
                    <span class="anomaly-badge {severity_class}">{row['Severity']}</span> &nbsp;
                    Confidence: <strong>{row['Confidence']}%</strong><br>
                    {row['AI_Explanation']}
                </div>
                """, unsafe_allow_html=True)

            # Download anomalies
            st.download_button(
                "📥 Export Anomalies to Excel",
                data=to_excel({"Anomalies": anomalies_df}),
                file_name="anomalies_export.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        else:
            st.success("✅ No anomalies detected at the current threshold. Try lowering the Z-score threshold in the sidebar.")

    # ═══════════════════════════════════════════════════════════
    # TAB 3: SCENARIO MODELLING
    # ═══════════════════════════════════════════════════════════
    with tab3:
        st.markdown("#### 🎭 What-If Scenario Simulator")

        scenarios = {
            "Base Case": {"desc": "Current trajectory — no adjustments", "key": "base", "class": "scenario-base"},
            "Bull Case": {"desc": "+12% revenue uplift, 3% cost efficiency", "key": "bull", "class": "scenario-bull"},
            "Bear Case": {"desc": "-12% revenue decline, 6% cost overrun", "key": "bear", "class": "scenario-bear"},
            "Cost Optimisation": {"desc": "Revenue flat, 15% cost reduction", "key": "cost_cut", "class": "scenario-base"},
        }

        for name, info in scenarios.items():
            st.markdown(f"""<div class="scenario-card {info['class']}">
                <strong>{name}</strong>: {info['desc']}
            </div>""", unsafe_allow_html=True)

        st.markdown("")

        # Build all scenario forecasts
        all_scenarios = []
        for name, info in scenarios.items():
            scen = build_scenario_forecast(filtered, scenario=info["key"])
            scen["Scenario_Label"] = name
            all_scenarios.append(scen)
        scenario_df = pd.concat(all_scenarios)

        # Aggregate by period and scenario
        scen_agg = scenario_df.groupby(["Period", "Scenario_Label", "Line_Type"]).agg(
            Forecast=("Scenario_Forecast", "sum"),
        ).reset_index()

        for lt in scen_agg["Line_Type"].unique():
            lt_data = scen_agg[scen_agg["Line_Type"] == lt].sort_values("Period")
            fig_scen = px.line(
                lt_data, x="Period", y="Forecast", color="Scenario_Label",
                color_discrete_map={
                    "Base Case": "#3b82f6", "Bull Case": "#22c55e",
                    "Bear Case": "#ef4444", "Cost Optimisation": "#a855f7"
                },
                title=f"{lt} — Scenario Forecasts",
            )
            fig_scen.update_layout(height=380, template="plotly_white",
                                    yaxis_tickformat="$,.0f",
                                    legend=dict(orientation="h", y=-0.15))
            st.plotly_chart(fig_scen, use_container_width=True)

        # Scenario comparison table
        st.markdown("#### 📊 Annual Scenario Comparison")
        summary_rows = []
        for name, info in scenarios.items():
            scen_data = scenario_df[scenario_df["Scenario_Label"] == name]
            rev = scen_data[scen_data["Line_Type"] == "Revenue"]["Scenario_Forecast"].sum()
            cost = scen_data[scen_data["Line_Type"] == "Cost"]["Scenario_Forecast"].sum()
            margin = rev - cost
            margin_pct = (margin / rev * 100) if rev > 0 else 0
            summary_rows.append({
                "Scenario": name,
                "Revenue ($M)": round(rev / 1e6, 1),
                "Cost ($M)": round(cost / 1e6, 1),
                "Margin ($M)": round(margin / 1e6, 1),
                "Margin %": f"{margin_pct:.1f}%",
            })
        st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)

    # ═══════════════════════════════════════════════════════════
    # TAB 4: AI COMMENTARY
    # ═══════════════════════════════════════════════════════════
    with tab4:
        st.markdown("#### 💬 AI-Generated Variance Commentary")
        st.markdown("Automated natural language explanations for significant budget variances in the latest period.")

        if commentaries:
            for c in commentaries:
                sentiment_icon = "🟢" if c["Sentiment"] == "favourable" else "🔴"
                st.markdown(f"""
                <div class="ai-insight-box">
                    {sentiment_icon} {c['Commentary']}
                </div>
                """, unsafe_allow_html=True)

            # Variance waterfall chart
            st.markdown("#### 📊 Variance Waterfall — Latest Period")
            comm_df = pd.DataFrame(commentaries)
            fig_water = go.Figure(go.Waterfall(
                name="Variance", orientation="v",
                x=comm_df["Category"],
                y=comm_df["Var_%"],
                textposition="outside",
                text=[f"{v:+.1f}%" for v in comm_df["Var_%"]],
                connector={"line": {"color": "#94a3b8"}},
                increasing={"marker": {"color": "#22c55e"}},
                decreasing={"marker": {"color": "#ef4444"}},
            ))
            fig_water.update_layout(title="Budget Variance by Category (%)", height=400, template="plotly_white",
                                     yaxis_title="Variance %")
            st.plotly_chart(fig_water, use_container_width=True)
        else:
            st.success("✅ All categories are within 3% of budget. No significant variances to report.")

        # Category heatmap
        st.markdown("#### 🗓️ Monthly Variance Heatmap")
        actuals_for_heat = filtered[filtered["Is_Actual"] == True].copy()
        if not actuals_for_heat.empty:
            actuals_for_heat["Var_%"] = ((actuals_for_heat["Actual"] - actuals_for_heat["Budget"]) / actuals_for_heat["Budget"] * 100).round(1)
            heat_pivot = actuals_for_heat.groupby(["Category", "Period"])["Var_%"].mean().reset_index()
            heat_pivot = heat_pivot.pivot(index="Category", columns="Period", values="Var_%").fillna(0)

            fig_heat = px.imshow(
                heat_pivot.values,
                labels=dict(x="Period", y="Category", color="Var %"),
                x=heat_pivot.columns.tolist(),
                y=heat_pivot.index.tolist(),
                color_continuous_scale="RdYlGn",
                aspect="auto",
                zmin=-20, zmax=20,
            )
            fig_heat.update_layout(height=400, margin=dict(l=150))
            st.plotly_chart(fig_heat, use_container_width=True)

    # ═══════════════════════════════════════════════════════════
    # TAB 5: ROI DASHBOARD
    # ═══════════════════════════════════════════════════════════
    with tab5:
        st.markdown("#### 💰 ROI Impact — AI-Powered Forecasting vs Manual FP&A")

        r1, r2, r3, r4 = st.columns(4)
        with r1:
            st.metric("Hours Saved / Month", f"{roi['hours_saved_monthly']:.0f} hrs",
                       delta=f"-{roi['manual_hours_monthly'] - roi['hours_saved_monthly']:.0f} hrs AI-assisted")
        with r2:
            st.metric("Annual Labour Savings", f"${roi['annual_labour_savings']:,.0f}")
        with r3:
            st.metric("Accuracy Savings", f"${roi['accuracy_savings']:,.0f}",
                       delta=f"+{accuracy_imp}% accuracy gain")
        with r4:
            st.metric("3-Year ROI", f"{roi['three_year_roi_pct']:.0f}%",
                       delta=f"{roi['payback_months']:.0f} mo payback")

        st.markdown("---")

        roi_c1, roi_c2 = st.columns(2)
        with roi_c1:
            # Savings breakdown donut
            fig_donut = go.Figure(go.Pie(
                labels=["Labour Savings", "Accuracy Savings", "Cycle Time Savings"],
                values=[roi["annual_labour_savings"], roi["accuracy_savings"], roi["cycle_time_savings"]],
                hole=0.55,
                marker_colors=["#0d9488", "#3b82f6", "#8b5cf6"],
                textinfo="label+percent",
            ))
            fig_donut.update_layout(title="Annual Benefit Breakdown", height=380, template="plotly_white",
                                     margin=dict(t=50))
            st.plotly_chart(fig_donut, use_container_width=True)

        with roi_c2:
            # Cumulative ROI timeline
            months = list(range(1, 37))
            cumulative = [roi["total_annual_benefit"] / 12 * m - roi["implementation_cost"] for m in months]
            fig_cum = go.Figure()
            fig_cum.add_trace(go.Scatter(
                x=months, y=cumulative, fill="tozeroy",
                line=dict(color="#0d9488", width=2),
                fillcolor="rgba(13,148,136,0.12)",
            ))
            fig_cum.add_hline(y=0, line_dash="dash", line_color="#94a3b8")
            fig_cum.update_layout(
                title="Cumulative Net Benefit (36 Months)", height=380, template="plotly_white",
                xaxis_title="Month", yaxis_title="Net Benefit ($)", yaxis_tickformat="$,.0f",
            )
            st.plotly_chart(fig_cum, use_container_width=True)

        # Assumptions table
        st.markdown("#### 📋 Assumptions & Inputs")
        assumptions = pd.DataFrame([
            {"Parameter": "Manual FP&A Hours / Month", "Value": f"{roi['manual_hours_monthly']} hrs", "Source": "User input"},
            {"Parameter": "AI-Assisted Hours / Month", "Value": f"{roi['ai_hours_monthly']} hrs", "Source": "70% reduction benchmark"},
            {"Parameter": "FTE Hourly Rate", "Value": f"${roi['hourly_rate']:.2f}/hr", "Source": f"${fte_cost:,} annual / 2,080 hrs"},
            {"Parameter": "Forecast Accuracy Improvement", "Value": f"{accuracy_imp}%", "Source": "User input"},
            {"Parameter": "Cost per 1% Forecast Error", "Value": "$50,000", "Source": "Industry benchmark"},
            {"Parameter": "Forecast Cycle Days Saved", "Value": f"{cycle_days} days", "Source": "User input"},
            {"Parameter": "Value per Day of Faster Forecast", "Value": "$15,000", "Source": "Decision speed premium"},
            {"Parameter": "Implementation Cost", "Value": f"${roi['implementation_cost']:,}", "Source": "Estimated POC + deployment"},
        ])
        st.dataframe(assumptions, use_container_width=True, hide_index=True)

    # ── Master export ──
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 📥 Export")
    actuals_export = filtered[filtered["Is_Actual"] == True].drop(columns=["Period_Date"], errors="ignore")
    forecast_export = filtered[filtered["Is_Actual"] == False].drop(columns=["Period_Date"], errors="ignore")
    export_sheets = {"Actuals": actuals_export, "Forecast": forecast_export}
    if not anomalies_df.empty:
        export_sheets["Anomalies"] = anomalies_df
    if commentaries:
        export_sheets["Commentaries"] = pd.DataFrame(commentaries)

    st.sidebar.download_button(
        "📥 Export Full Analysis",
        data=to_excel(export_sheets),
        file_name="ai_forecast_analysis.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


if __name__ == "__main__":
    main()
