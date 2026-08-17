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
    render_engineering_review_banner,
    render_governance_header_banner,
    render_page_header,
    render_sidebar_controls,
)
from dashboard.streamlit.data_access import (
    get_selected_portfolio_benefits,
    get_single_portfolio_summary,
    load_corridor_master,
    load_portfolio_summary,
    load_project_selections,
    load_treatment_benefits,
)

render_page_header(
    "Portfolio overview",
    "Interactive decision support for provisional high-crash corridor treatment portfolios.",
)

st.markdown(
    "**How to read this page:** Use the sidebar controls to explore portfolio investment scenarios. "
    "This page summarizes the selected capital program, funding coverage, safety impacts, and equity distribution."
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
st.subheader("Core portfolio metrics")

# Hero KPI Cards (4 primary decision metrics)
col1, col2, col3, col4 = st.columns(4)

annual_k = df_sel_benefits["crashes_averted_k"].sum()
annual_a = df_sel_benefits["crashes_averted_a"].sum()
annual_ksi = annual_k + annual_a

with col1:
    st.metric(
        "Modeled capital cost",
        format_currency(s_row["selected_capital_cost"]),
        help="Total estimated initial construction cost for all selected corridor projects.",
    )

with col2:
    st.metric(
        "Corridors funded",
        f"{int(s_row['selected_project_count'])} / 43",
        help="Count of candidate corridors selected for capital investment in this scenario.",
    )

with col3:
    st.metric(
        "Annual KSI averted",
        f"~{annual_ksi:,.1f} / yr",
        help="Estimated annual fatal (K) and serious injury (A) crashes prevented across funded corridors.",
    )

with col4:
    st.metric(
        "Achieved equity share",
        format_percent(s_row["achieved_equity_share"]),
        delta=f"Floor: {format_percent(s_row['equity_floor'])}",
        help="Percentage of capital investment allocated to high-SVI equity priority areas.",
    )

# Secondary Metrics Expander
utilization_ratio = s_row["selected_capital_cost"] / s_row["budget_usd"] if s_row["budget_usd"] > 0 else 0.0
tot_ksi_2026 = df_master["annual_forecast_ksi_crashes_2026"].sum()
tot_averted = df_sel_benefits["crashes_averted_total"].sum()

with st.expander("View secondary metrics and economic indicators", expanded=False):
    sec1, sec2, sec3 = st.columns(3)
    with sec1:
        st.metric("Budget utilization", format_percent(utilization_ratio), help="Selected capital cost divided by planning budget ceiling.")
        st.metric("Total crashes averted", f"{tot_averted:,.1f} / yr", help="Model-estimated annual reduction in total crashes across funded corridors.")
    with sec2:
        st.metric("2026 baseline KSI forecast", f"{tot_ksi_2026:,.1f} / yr", help="Calibrated 2026 baseline KSI forecast across all 43 corridors.")
        st.metric("Total present value benefit", format_currency(s_row["total_present_value_benefit"]), help="Comprehensive 20-year present value benefit.")
    with sec3:
        st.metric("Total net present benefit", format_currency(s_row["total_net_present_benefit"]), help="Present value benefit minus initial capital cost.")
        st.metric("Portfolio BCR (comprehensive)", f"{s_row['portfolio_bcr']:,.1f} : 1", help="Planning-level benefit-cost ratio from comprehensive crash costs.")

st.markdown("---")

# Visual Charts Section
c1, c2 = st.columns(2)

with c1:
    st.markdown("#### Capital cost versus planning budget ceiling")
    fig_cost = go.Figure()
    fig_cost.add_trace(go.Bar(
        x=["Selected capital cost"],
        y=[s_row["selected_capital_cost"]],
        name="Selected capital cost",
        marker_color="#1f77b4",
        text=[format_currency(s_row["selected_capital_cost"])],
        textposition="auto",
    ))
    fig_cost.add_trace(go.Bar(
        x=["Budget ceiling"],
        y=[s_row["budget_usd"]],
        name="Planning budget ceiling",
        marker_color="#d62728",
        text=[format_currency(s_row["budget_usd"])],
        textposition="auto",
    ))
    fig_cost.update_layout(
        barmode="group",
        height=320,
        margin=dict(l=20, r=20, t=30, b=20),
        yaxis=dict(tickprefix="$", tickformat="~s", title="Capital cost (USD)"),
    )
    st.plotly_chart(fig_cost, use_container_width=True)

with c2:
    st.markdown("#### Achieved equity share versus required floor")
    fig_eq = go.Figure()
    fig_eq.add_trace(go.Bar(
        x=["Achieved spending share", "Required equity floor"],
        y=[s_row["achieved_equity_share"] * 100, s_row["equity_floor"] * 100],
        marker_color=["#2ca02c", "#ff7f0e"],
        text=[f"{s_row['achieved_equity_share']*100:.1f}%", f"{s_row['equity_floor']*100:.1f}%"],
        textposition="auto",
    ))
    fig_eq.update_layout(
        height=320,
        margin=dict(l=20, r=20, t=30, b=20),
        yaxis=dict(ticksuffix="%", title="Spending share (%)"),
    )
    st.plotly_chart(fig_eq, use_container_width=True)

c3, c4 = st.columns(2)

with c3:
    st.markdown("#### Selected project cost distribution")
    fig_dist = px.histogram(
        df_sel_benefits,
        x="capital_project_cost",
        nbins=15,
        labels={"capital_project_cost": "Capital project cost ($)"},
        color_discrete_sequence=["#1f77b4"],
    )
    mean_cost = float(df_sel_benefits["capital_project_cost"].mean())
    median_cost = float(df_sel_benefits["capital_project_cost"].median())
    fig_dist.add_vline(
        x=mean_cost,
        line_dash="dash",
        line_color="#d62728",
        annotation_text=f"Mean: {format_currency(mean_cost)}",
        annotation_position="top right",
    )
    fig_dist.add_vline(
        x=median_cost,
        line_dash="dot",
        line_color="#2ca02c",
        annotation_text=f"Median: {format_currency(median_cost)}",
        annotation_position="top left",
    )
    fig_dist.update_layout(
        height=320,
        margin=dict(l=20, r=20, t=30, b=20),
        xaxis=dict(tickprefix="$", tickformat="~s", title="Capital project cost (USD)"),
        yaxis=dict(title="Corridor count"),
    )
    st.plotly_chart(fig_dist, use_container_width=True)

with c4:
    st.markdown("#### Estimated annual averted crashes by severity")
    sev_data = {
        "Severity": ["Fatal (K)", "Serious injury (A)", "Minor injury (B)", "Possible injury (C)", "Property damage (O)"],
        "Annual averted crashes": [
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
        y="Annual averted crashes",
        text_auto=".1f",
        color="Severity",
        color_discrete_sequence=px.colors.qualitative.Set2,
    )
    fig_sev.update_layout(
        height=320,
        margin=dict(l=20, r=20, t=30, b=20),
        showlegend=False,
        yaxis=dict(title="Annual averted crashes"),
    )
    st.plotly_chart(fig_sev, use_container_width=True)

st.markdown("---")
st.subheader("Selected projects detail register")

df_table = df_sel_benefits[[
    "corridor_id",
    "corridor_name",
    "treatment_name",
    "capital_project_cost",
    "crashes_averted_total",
    "crashes_averted_k",
    "crashes_averted_a",
    "equity_area_flag",
    "physical_applicability_status",
]].copy()

df_table["equity_area_flag"] = df_table["equity_area_flag"].apply(lambda x: "Yes" if x else "No")
df_table.columns = [
    "Corridor ID",
    "Corridor Name",
    "Recommended Treatment",
    "Capital Cost",
    "Total Crashes Averted / Yr",
    "Fatal (K) Averted / Yr",
    "Serious Injury (A) Averted / Yr",
    "Equity Priority Area",
    "Physical Applicability",
]

st.dataframe(
    df_table.style.format({
        "Capital Cost": "${:,.0f}",
        "Total Crashes Averted / Yr": "{:,.2f}",
        "Fatal (K) Averted / Yr": "{:,.2f}",
        "Serious Injury (A) Averted / Yr": "{:,.2f}",
    }),
    use_container_width=True,
    hide_index=True,
    height=350,
)

render_engineering_review_banner()

