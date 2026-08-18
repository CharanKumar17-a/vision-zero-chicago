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
    format_bcr_compact,
    format_count_compact,
    format_currency,
    format_currency_compact,
    format_equity_flag,
    format_ksi_compact,
    format_percent,
    render_economic_caveat_banner,
    render_engineering_review_banner,
    render_governance_header_banner,
    render_page_header,
    render_sidebar_controls,
)
from dashboard.streamlit.data_access import (
    find_what_if_grid_portfolio,
    get_selected_portfolio_benefits,
    get_single_portfolio_summary,
    load_corridor_master,
    load_portfolio_summary,
    load_project_selections,
    load_treatment_benefits,
)

render_page_header(
    "Portfolio overview",
    "Interactive planning-level decision support for provisional high-crash corridor treatment portfolios.",
)

st.markdown(
    "**How to read this page:** Use the sidebar controls to explore portfolio investment scenarios. "
    "This page summarizes the optimized planning portfolio, funding coverage, estimated safety impacts, and equity distribution."
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
st.subheader("1. Core portfolio metrics")


# Hero KPI Cards (4 primary decision metrics)
col1, col2, col3, col4 = st.columns(4)

total_corridors_count = len(df_master)
annual_ksi = df_sel_benefits["crashes_averted_ksi"].sum()

with col1:
    st.metric(
        "Estimated capital cost",
        format_currency_compact(s_row["selected_capital_cost"]),
        help=f"Planning-level estimate: {format_currency(s_row['selected_capital_cost'])} total initial construction cost for all shortlisted corridor projects.",
    )

with col2:
    st.metric(
        "Corridors funded",
        f"{int(s_row['selected_project_count'])} / {total_corridors_count}",
        help=f"Denominator: {total_corridors_count} candidate corridors in the network. Numerator: {int(s_row['selected_project_count'])} corridors selected for funding. Subject to engineering review.",
    )

with col3:
    st.metric(
        "Estimated KSI avoided / year",
        f"{format_ksi_compact(annual_ksi)} / yr",
        help=f"Denominator: {int(s_row['selected_project_count'])} funded corridors in this scenario. Severity scope: Fatal (K) + Serious injury (A) crashes. Planning-level estimate: ~{annual_ksi:,.1f} KSI avoided / yr.",
    )

with col4:
    st.metric(
        "Achieved equity share",
        format_percent(s_row["achieved_equity_share"]),
        delta=f"Floor: {format_percent(s_row['equity_floor'])}",
        help=f"Denominator: Selected portfolio capital cost ({format_currency(s_row['selected_capital_cost'])}). Numerator: Capital allocated to high-SVI equity priority areas.",
    )

# Secondary Metrics Expander
utilization_ratio = s_row["selected_capital_cost"] / s_row["budget_usd"] if s_row["budget_usd"] > 0 else 0.0
tot_ksi_2026 = df_master["annual_forecast_ksi_crashes_2026"].sum()
tot_averted = df_sel_benefits["crashes_averted_total"].sum()

with st.expander("View secondary metrics and economic indicators", expanded=False):
    sec1, sec2, sec3 = st.columns(3)
    with sec1:
        st.metric("Budget utilization", format_percent(utilization_ratio), help="Selected capital cost divided by planning budget ceiling.")
        st.metric("Estimated all-severity crashes avoided / year", f"{format_count_compact(tot_averted)} / yr", help=f"Denominator: {int(s_row['selected_project_count'])} funded corridors. Severity scope: All police-reported crash severities (K, A, B, C, O). Planning-level estimate: ~{tot_averted:,.1f} crashes avoided / yr.")
    with sec2:
        st.metric("Baseline KSI / year", f"{format_ksi_compact(tot_ksi_2026)} / yr", help=f"Denominator: Entire 43-corridor network. Severity scope: Calibrated 2026 pre-treatment baseline fatal (K) + serious injury (A) crashes (~{tot_ksi_2026:,.1f} KSI / yr).")
        st.metric("Total present value benefit", format_currency_compact(s_row["total_present_value_benefit"]), help=f"Planning-level estimate: {format_currency(s_row['total_present_value_benefit'])} comprehensive 20-year present value benefit.")
    with sec3:
        st.metric("Total net present benefit", format_currency_compact(s_row["total_net_present_benefit"]), help=f"Planning-level estimate: {format_currency(s_row['total_net_present_benefit'])} net present value benefit.")
        st.metric("Portfolio BCR (comprehensive)", format_bcr_compact(s_row["portfolio_bcr"]), help=f"Planning-level estimate: {s_row['portfolio_bcr']:,.1f} : 1 benefit-cost ratio from comprehensive crash costs.")

st.markdown("---")
st.subheader("2. Scenario visual analytics")

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
    st.markdown("#### Estimated annual avoided crashes by severity category")
    sev_data = {
        "Severity category": ["Fatal crashes (K)", "Serious injury crashes (A)", "Minor injury crashes (B)", "Possible injury crashes (C)", "Property damage only crashes (PDO / O)"],
        "Annual avoided crashes": [
            df_sel_benefits["crashes_averted_k"].sum(),
            df_sel_benefits["crashes_averted_a"].sum(),
            df_sel_benefits["crashes_averted_b"].sum(),
            df_sel_benefits["crashes_averted_c"].sum(),
            df_sel_benefits["crashes_averted_o"].sum(),
        ],
    }
    fig_sev = px.bar(
        pd.DataFrame(sev_data),
        x="Severity category",
        y="Annual avoided crashes",
        text_auto=".1f",
        color="Severity category",
        color_discrete_sequence=px.colors.qualitative.Set2,
    )
    fig_sev.update_layout(
        height=320,
        margin=dict(l=20, r=20, t=30, b=20),
        showlegend=False,
        yaxis=dict(title="Annual avoided crashes"),
    )
    st.plotly_chart(fig_sev, use_container_width=True)

st.markdown("---")
st.subheader("3. Selected projects detail register")
st.caption("Planning-level treatment recommendations subject to engineering review and implementation approval.")

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

df_table["equity_area_flag"] = df_table["equity_area_flag"].apply(format_equity_flag)
df_table.columns = [
    "Corridor ID",
    "Corridor Name",
    "Recommended Treatment",
    "Estimated Capital Cost",
    "Estimated All-Severity Crashes Avoided / Yr",
    "Estimated Fatal (K) Avoided / Yr",
    "Estimated Serious Injury (A) Avoided / Yr",
    "Equity Priority Area",
    "Physical Applicability",
]

st.dataframe(
    df_table.style.format({
        "Estimated Capital Cost": "${:,.0f}",
        "Estimated All-Severity Crashes Avoided / Yr": "{:,.2f}",
        "Estimated Fatal (K) Avoided / Yr": "{:,.2f}",
        "Estimated Serious Injury (A) Avoided / Yr": "{:,.2f}",
    }),
    use_container_width=True,
    hide_index=True,
    height=350,
)

st.markdown("---")
st.subheader("4. What-if capital planner")
st.caption("Precomputed illustrative grid; nearest optimized planning portfolio shown. Subject to engineering review and implementation approval.")

st.markdown(
    "Explore how capital allocation and equity requirements respond to custom budget ceilings and equity floors across the precomputed optimization grid."
)

wif_col1, wif_col2 = st.columns(2)
with wif_col1:
    user_budget_m = st.slider(
        "Select custom planning budget ($M)",
        min_value=2,
        max_value=25,
        value=15,
        step=1,
        help="Interactive slider over precomputed budget grid ($2M to $25M in $1M increments)."
    )
with wif_col2:
    user_equity_pct = st.select_slider(
        "Select minimum equity spending floor",
        options=[15, 20, 25, 30, 35, 40],
        value=20,
        format_func=lambda x: f"{x}%",
        help="Select minimum percentage of funding reserved for high-SVI equity priority corridors."
    )

wif_s_row, is_exact = find_what_if_grid_portfolio(
    df_summary=df_summary,
    budget_usd=float(user_budget_m * 1e6),
    equity_floor=float(user_equity_pct / 100.0),
    uncertainty_scenario="BASE",
)

target_portfolio_id = str(wif_s_row["portfolio_id"])
wif_sel_benefits = get_selected_portfolio_benefits(df_selections, df_benefits, target_portfolio_id)

wif_ksi = wif_sel_benefits["crashes_averted_ksi"].sum()

exact_note = "" if is_exact else f" *(Nearest precomputed match shown for ${user_budget_m}M / {user_equity_pct}% equity)*"

st.info(
    f"**Precomputed scenario active:** Budget Ceiling: **${int(wif_s_row['budget_usd']/1e6)}M** | "
    f"Equity Floor: **{int(round(wif_s_row['equity_floor']*100))}%** | "
    f"Scenario ID: `{target_portfolio_id}`{exact_note}"
)

wc1, wc2, wc3, wc4 = st.columns(4)
with wc1:
    st.metric("Estimated capital cost", format_currency_compact(wif_s_row["selected_capital_cost"]), help=f"Planning-level estimate: {format_currency(wif_s_row['selected_capital_cost'])}")
with wc2:
    st.metric("Corridors funded", f"{int(wif_s_row['selected_project_count'])} / {total_corridors_count}")
with wc3:
    st.metric("Estimated KSI avoided / year", f"{format_ksi_compact(wif_ksi)} / yr", help=f"Denominator: {int(wif_s_row['selected_project_count'])} funded corridors in what-if portfolio. Severity scope: Fatal (K) + Serious injury (A) crashes. Planning-level estimate: ~{wif_ksi:,.1f} / yr")
with wc4:
    st.metric("Achieved equity share", format_percent(wif_s_row["achieved_equity_share"]))

wif_table = wif_sel_benefits[[
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
wif_table["equity_area_flag"] = wif_table["equity_area_flag"].apply(format_equity_flag)
wif_table.columns = [
    "Corridor ID",
    "Corridor Name",
    "Recommended Treatment",
    "Estimated Capital Cost",
    "Estimated All-Severity Crashes Avoided / Yr",
    "Estimated Fatal (K) Avoided / Yr",
    "Estimated Serious Injury (A) Avoided / Yr",
    "Equity Priority Area",
    "Physical Applicability",
]

st.dataframe(
    wif_table.style.format({
        "Estimated Capital Cost": "${:,.0f}",
        "Estimated All-Severity Crashes Avoided / Yr": "{:,.2f}",
        "Estimated Fatal (K) Avoided / Yr": "{:,.2f}",
        "Estimated Serious Injury (A) Avoided / Yr": "{:,.2f}",
    }),
    use_container_width=True,
    hide_index=True,
    height=280,
)

csv_data = wif_table.to_csv(index=False).encode("utf-8")
st.download_button(
    label=f"Download what-if portfolio CSV (${int(wif_s_row['budget_usd']/1e6)}M / {int(round(wif_s_row['equity_floor']*100))}% equity)",
    data=csv_data,
    file_name=f"vision_zero_what_if_{target_portfolio_id}.csv",
    mime="text/csv",
)

render_engineering_review_banner()
render_economic_caveat_banner()
