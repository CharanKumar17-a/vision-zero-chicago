"""Portfolio Overview Page - Vision Zero Chicago Decision Support App.

Contract: docs/data_quality/decision_output_mart_contract.md
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add repository root to sys.path so standalone scripts and Streamlit pages resolve dashboard namespace
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from dashboard.streamlit.components import (
    format_currency,
    format_percent,
    render_economic_caveat_banner,
    render_engineering_review_banner,
    render_governance_header_banner,
    render_sidebar_controls,
)
from dashboard.streamlit.data_access import (
    load_corridor_master,
    load_portfolio_summary,
    load_project_selections,
    load_treatment_benefits,
    get_selected_portfolio_benefits,
    get_single_portfolio_selections,
    get_single_portfolio_summary,
)

st.set_page_config(page_title="Portfolio Overview - Vision Zero Chicago", layout="wide")

st.title("Vision Zero Chicago - Portfolio Overview")
st.markdown("Interactive decision support for provisional high-crash corridor treatment portfolios.")

st.info(
    "**Planning Scenario Scope**: Under sourced planning-level treatment costs (D024), "
    "the full 43-corridor network costs approx. \\$20.1M (BASE). The \\$15M planning "
    "budget is BINDING (selects ~34 of 43 corridors); \\$25M and \\$40M remain "
    "nonbinding (all eligible corridors fit). Budget and equity scenarios are "
    "planning-level, not official City budgets. Physical applicability remains "
    "UNKNOWN pending engineering field review."
)

# Load serving datasets
df_summary = load_portfolio_summary()
df_selections = load_project_selections()
df_master = load_corridor_master()
df_benefits = load_treatment_benefits()

# Render sidebar controls & get single selected portfolio_id
portfolio_id = render_sidebar_controls(df_summary)

# Extract single portfolio data
s_row = get_single_portfolio_summary(df_summary, portfolio_id)
df_sel_benefits = get_selected_portfolio_benefits(df_selections, df_benefits, portfolio_id)

is_official = (s_row["run_group"] == "OFFICIAL")
render_governance_header_banner(s_row["run_group"], is_official)

st.markdown("---")
st.subheader("Executive Hero Metrics")

# Hero KPI Cards
col1, col2, col3, col4, col5, col6 = st.columns(6)

with col1:
    st.metric("Selected Projects", f"{int(s_row['selected_project_count'])} / 43")

with col2:
    st.metric("Modeled Capital Cost", format_currency(s_row["selected_capital_cost"]))

with col3:
    st.metric("Budget Utilization", format_percent(s_row["budget_utilization_pct"]))

with col4:
    st.metric("Achieved Equity Share", format_percent(s_row["achieved_equity_share"]), delta=f"Floor: {format_percent(s_row['equity_floor'])}")

with col5:
    tot_ksi_2026 = df_master["annual_forecast_ksi_crashes_2026"].sum()
    st.metric(
        "Calibrated 2026 KSI Forecast",
        f"{tot_ksi_2026:,.1f} / yr",
        help="Forward-looking 2026 model forecast calibrated using empirical validation evidence. Separate from historical Empirical Bayes stability benchmark.",
    )

with col6:
    tot_averted = df_sel_benefits["crashes_averted_total"].sum()
    st.metric(
        "Provisional Crashes Averted",
        f"{tot_averted:,.1f} / yr",
        help="Expected values from the forecast model — not predictions of any individual crash event.",
    )

st.markdown("---")

# Visual Charts Section
c1, c2 = st.columns(2)

with c1:
    st.markdown("#### Capital Cost vs Selected Planning Budget")
    fig_cost = go.Figure()
    fig_cost.add_trace(go.Bar(
        x=["Selected Project Cost"],
        y=[s_row["selected_capital_cost"]],
        name="Selected Capital Cost",
        marker_color="#1f77b4",
    ))
    fig_cost.add_trace(go.Bar(
        x=["Budget Ceiling"],
        y=[s_row["budget_usd"]],
        name="Planning Budget Ceiling",
        marker_color="#d62728",
    ))
    fig_cost.update_layout(barmode="group", height=320, margin=dict(l=20, r=20, t=30, b=20))
    st.plotly_chart(fig_cost, use_container_width=True)

with c2:
    st.markdown("#### Achieved Equity Share vs Required Floor")
    fig_eq = go.Figure()
    fig_eq.add_trace(go.Bar(
        x=["Achieved Spending Share", "Required Equity Floor"],
        y=[s_row["achieved_equity_share"] * 100, s_row["equity_floor"] * 100],
        marker_color=["#2ca02c", "#ff7f0e"],
        text=[f"{s_row['achieved_equity_share']*100:.1f}%", f"{s_row['equity_floor']*100:.1f}%"],
        textposition="auto",
    ))
    fig_eq.update_layout(yaxis_title="Percentage (%)", height=320, margin=dict(l=20, r=20, t=30, b=20))
    st.plotly_chart(fig_eq, use_container_width=True)

c3, c4 = st.columns(2)

with c3:
    st.markdown("#### Selected Project Cost Distribution")
    fig_dist = px.histogram(
        df_sel_benefits,
        x="capital_project_cost",
        nbins=15,
        title="Project Cost Distribution ($)",
        labels={"capital_project_cost": "Capital Project Cost ($)"},
        color_discrete_sequence=["#1f77b4"],
    )
    fig_dist.update_layout(height=320, margin=dict(l=20, r=20, t=30, b=20))
    st.plotly_chart(fig_dist, use_container_width=True)

with c4:
    st.markdown("#### Modeled Averted Crashes by Severity (Annual)")
    sev_data = {
        "Severity": ["Fatal (K)", "Serious Injury (A)", "Minor Injury (B)", "Possible Injury (C)", "Property Damage (O)"],
        "Annual Averted Crashes": [
            df_sel_benefits["crashes_averted_k"].sum(),
            df_sel_benefits["crashes_averted_a"].sum(),
            df_sel_benefits["crashes_averted_b"].sum(),
            df_sel_benefits["crashes_averted_c"].sum(),
            df_sel_benefits["crashes_averted_o"].sum(),
        ],
    }
    fig_sev = px.bar(
        pd.DataFrame(sev_data),
        x="Severity",
        y="Annual Averted Crashes",
        text_auto=".1f",
        color="Severity",
        color_discrete_sequence=px.colors.qualitative.Set2,
    )
    fig_sev.update_layout(height=320, margin=dict(l=20, r=20, t=30, b=20), showlegend=False)
    st.plotly_chart(fig_sev, use_container_width=True)

st.markdown("---")
st.subheader("Selected Projects Detail Register")
st.dataframe(
    df_sel_benefits[[
        "corridor_id",
        "corridor_name",
        "treatment_name",
        "capital_project_cost",
        "crashes_averted_total",
        "crashes_averted_k",
        "crashes_averted_a",
        "equity_area_flag",
        "physical_applicability_status",
    ]].style.format({
        "capital_project_cost": "${:,.0f}",
        "crashes_averted_total": "{:,.2f}",
        "crashes_averted_k": "{:,.2f}",
        "crashes_averted_a": "{:,.2f}",
    }),
    use_container_width=True,
    height=350,
)

st.markdown("---")
# Secondary Economic Scenario Section
st.subheader("Economic Scenario Analysis (Secondary Metrics)")
render_economic_caveat_banner()

ec1, ec2, ec3 = st.columns(3)
with ec1:
    st.metric("Total Present Value Benefit", format_currency(s_row["total_present_value_benefit"]))
with ec2:
    st.metric("Total Net Present Benefit", format_currency(s_row["total_net_present_benefit"]))
with ec3:
    st.metric(
        "Portfolio Benefit-Cost Ratio (BCR)",
        f"{s_row['portfolio_bcr']:,.1f}",
        help="Planning-level estimates from provisional costs and comprehensive crash costs — not expected City project returns.",
    )

render_engineering_review_banner()
