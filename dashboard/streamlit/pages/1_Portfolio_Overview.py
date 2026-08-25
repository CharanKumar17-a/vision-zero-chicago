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
    format_engineering_status,
    format_equity_flag,
    format_ksi_compact,
    format_percent,
    render_economic_caveat_banner,
    render_engineering_review_banner,
    render_governance_footer,
    render_governance_header_banner,
    render_page_header,
    render_sidebar_controls,
)
from dashboard.streamlit.data_access import (
    compute_portfolio_stability,
    evaluate_portfolio_scenario,
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

# Load serving datasets
df_summary = load_portfolio_summary()
df_selections = load_project_selections()
df_master = load_corridor_master()
df_benefits = load_treatment_benefits()

# Render sidebar controls & get active scenario parameters
scenario_params = render_sidebar_controls(df_summary, return_dict=True)

# Dynamically solve active scenario
s_row, df_sel_benefits = evaluate_portfolio_scenario(
    budget=scenario_params["budget"],
    equity_floor=scenario_params["equity_floor"],
    cost_case=scenario_params["cost_case"],
    cmf_case=scenario_params["cmf_case"],
    df_benefits=df_benefits,
)

is_official = (s_row["run_group"] == "OFFICIAL")
render_governance_header_banner(s_row["run_group"], is_official)

st.markdown("---")
st.subheader("1. Core portfolio metrics")


# Hero KPI Cards (4 primary decision metrics)
col1, col2, col3, col4 = st.columns(4)

total_corridors_count = len(df_master)
annual_ksi = df_sel_benefits["crashes_averted_ksi"].sum()

svi_mask = df_sel_benefits["equity_area_flag"] == True
high_svi_ksi = float(df_sel_benefits[svi_mask]["crashes_averted_ksi"].sum())
high_svi_ksi_share = (high_svi_ksi / annual_ksi * 100) if annual_ksi > 0 else 0.0

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
        "High-SVI capital share",
        format_percent(s_row["achieved_equity_share"]),
        delta=f"Floor: {format_percent(s_row['equity_floor'])}",
        help=f"Denominator: Selected portfolio capital cost ({format_currency(s_row['selected_capital_cost'])}). Numerator: Capital allocated to high-SVI corridors. Measures capital spending input only; not proof of equitable safety outcomes. SVI is used as a spatial equity proxy.",
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
        st.metric("KSI benefit share in high-SVI areas", f"{high_svi_ksi_share:.1f}%", help=f"Denominator: Total annual KSI crashes avoided across funded corridors (~{annual_ksi:.1f}/yr). Numerator: Annual KSI avoided in high-SVI corridors (~{high_svi_ksi:.1f}/yr). SVI is used as a spatial equity proxy; it does not directly measure safety benefit equity.")

# -----------------------------------------------------------------------------
# Section 2 — Selected Projects Detail Register
# -----------------------------------------------------------------------------
st.markdown("---")
st.subheader("2. Selected projects detail register")
st.caption("Analytical planning portfolio; individual project engineering status is provisionally UNKNOWN (Engineering review required). Subject to engineering review and implementation approval.")

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
df_table["physical_applicability_status"] = df_table["physical_applicability_status"].apply(format_engineering_status)
df_table.columns = [
    "Corridor ID",
    "Corridor Name",
    "Recommended Treatment",
    "Estimated Capital Cost",
    "Estimated All-Severity Crashes Avoided / Yr",
    "Estimated Fatal (K) Avoided / Yr",
    "Estimated Serious Injury (A) Avoided / Yr",
    "High-SVI Priority Area",
    "Engineering Status",
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
    height=320,
)

# -----------------------------------------------------------------------------
# Section 3 — Portfolio Robustness Across Scenarios (Decision DEC-07)
# -----------------------------------------------------------------------------
st.markdown("---")
st.subheader("3. Portfolio robustness across scenarios")
st.caption("Cross-scenario selection frequencies from precomputed optimization runs. Identifies robust 'core' investments versus scenario-sensitive projects.")

st.markdown(
    "Analyze how frequently each corridor-treatment project is selected across precomputed optimization scenarios. "
    "Projects consistently selected across varying budgets, equity floors, and CMF uncertainty levels represent robust capital priorities."
)

stab_col1, stab_col2 = st.columns([1, 1])
with stab_col1:
    scope_display = st.selectbox(
        "Scenario scope for stability analysis",
        options=[
            "Official planning scenarios (27 runs)",
            "All canonical scenarios (36 runs)",
            "All precomputed scenarios (192 runs)",
        ],
        index=0,
        help="Select scenario set: Official planning runs ($15M, $25M, $40M), Canonical runs (+ stress tests), or All precomputed mart scenarios (+ What-If grid).",
    )
    scope_key = "OFFICIAL" if "27" in scope_display else ("CANONICAL" if "36" in scope_display else "ALL")

with stab_col2:
    tier_filter = st.selectbox(
        "Filter by stability tier",
        options=[
            "All tiers",
            "Core (selected in most scenarios)",
            "Conditional (selected in some scenarios)",
            "Scenario-sensitive (selected rarely)",
        ],
        index=0,
        help="Filter projects by stability classification tier.",
    )

df_stability = compute_portfolio_stability(df_selections, df_summary, scenario_scope=scope_key)
total_candidates_count = len(df_stability)
total_scenarios_count = int(df_stability["total_scenarios"].iloc[0]) if not df_stability.empty else 0
core_count = int((df_stability["stability_tier"] == "Core").sum())
cond_count = int((df_stability["stability_tier"] == "Conditional").sum())
sens_count = int((df_stability["stability_tier"] == "Scenario-sensitive").sum())

st.caption(f"Stability is evaluated across {total_candidates_count} corridor-treatment candidates selected across the {total_scenarios_count} {scope_display.lower()}.")

sm1, sm2, sm3, sm4 = st.columns(4)
with sm1:
    st.metric("Core candidates", f"{core_count}", help=f"Selected in >=70% of evaluated scenarios ({core_count} of {total_candidates_count} candidates). Robust priority across varying budget ceilings and uncertainty levels.")
with sm2:
    st.metric("Conditional candidates", f"{cond_count}", help=f"Selected in 30%–69% of evaluated scenarios ({cond_count} of {total_candidates_count} candidates). Viable under specific budget or equity floor conditions.")
with sm3:
    st.metric("Scenario-sensitive candidates", f"{sens_count}", help=f"Selected in <30% of evaluated scenarios ({sens_count} of {total_candidates_count} candidates). Narrow viability (e.g. selected only in high-budget or low-cost scenarios).")
with sm4:
    scen_label = "Official scenarios evaluated" if scope_key == "OFFICIAL" else ("Canonical scenarios evaluated" if scope_key == "CANONICAL" else "Precomputed scenarios evaluated")
    st.metric(scen_label, f"{total_scenarios_count}", help=f"Total precomputed optimization scenarios evaluated in {scope_display}.")

if tier_filter.startswith("Core"):
    df_stab_display = df_stability[df_stability["stability_tier"] == "Core"].copy()
elif tier_filter.startswith("Conditional"):
    df_stab_display = df_stability[df_stability["stability_tier"] == "Conditional"].copy()
elif tier_filter.startswith("Scenario-sensitive"):
    df_stab_display = df_stability[df_stability["stability_tier"] == "Scenario-sensitive"].copy()
else:
    df_stab_display = df_stability.copy()

df_stab_table = df_stab_display[[
    "corridor_id",
    "corridor_name",
    "treatment_name",
    "stability_tier",
    "selection_display",
    "selection_rate",
    "equity_area_flag",
    "capital_project_cost",
]].copy()

df_stab_table["equity_area_flag"] = df_stab_table["equity_area_flag"].apply(format_equity_flag)
df_stab_table["selection_rate"] = df_stab_table["selection_rate"].apply(lambda r: f"{r * 100:.1f}%")

df_stab_table.columns = [
    "Corridor ID",
    "Corridor Name",
    "Recommended Treatment",
    "Stability Tier",
    "Scenario Selection Frequency",
    "Selection Rate",
    "High-SVI Priority Area",
    "Estimated Capital Cost",
]

st.dataframe(
    df_stab_table.style.format({
        "Estimated Capital Cost": "${:,.0f}",
    }),
    use_container_width=True,
    hide_index=True,
    height=280,
)

# -----------------------------------------------------------------------------
# Section 4 — Benefit-Cost Efficiency View (Decision DEC-02)
# -----------------------------------------------------------------------------
st.markdown("---")
st.subheader("4. Funded corridors — Benefit-Cost efficiency")
st.caption(
    "Corridors ranked by individual Benefit-Cost Ratio (BCR). "
    "The optimization selects the mathematically optimal portfolio under the stated objective, budget, equity, treatment, and screening constraints."
)

df_eff = df_sel_benefits.copy()
df_eff["bcr_float"] = df_eff["benefit_cost_ratio"].astype(float)
df_eff = df_eff.sort_values("bcr_float", ascending=True)  # Ascending for horizontal bar chart display

colors = ["#276749" if eq else "#1B4F8A" for eq in df_eff["equity_area_flag"]]

fig_bcr = go.Figure()
fig_bcr.add_trace(go.Bar(
    y=df_eff["corridor_name"],
    x=df_eff["bcr_float"],
    orientation="h",
    marker_color=colors,
    text=[f"BCR {bcr:.1f} (${int(c/1e3)}k)" for bcr, c in zip(df_eff["bcr_float"], df_eff["capital_project_cost"])],
    textposition="auto",
))

fig_bcr.update_layout(
    title=dict(
        text="Funded Corridors — Benefit-Cost Efficiency",
        font=dict(size=14),
    ),
    height=max(400, len(df_eff) * 20),
    margin=dict(l=20, r=20, t=40, b=20),
    xaxis=dict(title="Individual Project Benefit-Cost Ratio (BCR)"),
    yaxis=dict(title=""),
)

st.plotly_chart(fig_bcr, use_container_width=True)

# Legend indicator
c_leg1, c_leg2 = st.columns(2)
with c_leg1:
    st.markdown("🟢 **Green bars**: High-SVI Equity Priority Corridors")
with c_leg2:
    st.markdown("🔵 **Blue bars**: Standard Priority Corridors")

with st.expander("Comprehensive severity & economic accounts (Detailed KABCO breakdowns)", expanded=False):
    k_val = float(df_sel_benefits["crashes_averted_k"].sum())
    a_val = float(df_sel_benefits["crashes_averted_a"].sum())
    ksi_val = float(df_sel_benefits["crashes_averted_ksi"].sum())
    b_val = float(df_sel_benefits["crashes_averted_b"].sum())
    c_val = float(df_sel_benefits["crashes_averted_c"].sum())
    o_val = float(df_sel_benefits["crashes_averted_o"].sum())
    tot_val = float(df_sel_benefits["crashes_averted_total"].sum())

    st.markdown("#### Comprehensive annual crash severity breakdown")
    sev_df = pd.DataFrame([
        {"Outcome Tier": "Primary (Life-Safety)", "Severity Category": "Fatal crashes (K)", "Estimated Crashes Avoided / Yr": f"{k_val:.2f}", "Share of Total": f"{(k_val/tot_val)*100:.2f}%"},
        {"Outcome Tier": "Primary (Life-Safety)", "Severity Category": "Serious injury crashes (A)", "Estimated Crashes Avoided / Yr": f"{a_val:.2f}", "Share of Total": f"{(a_val/tot_val)*100:.2f}%"},
        {"Outcome Tier": "Primary (Life-Safety)", "Severity Category": "Combined Vision Zero KSI (K + A)", "Estimated Crashes Avoided / Yr": f"{ksi_val:.2f}", "Share of Total": f"{(ksi_val/tot_val)*100:.2f}%"},
        {"Outcome Tier": "Secondary (Non-Severe)", "Severity Category": "Minor injury crashes (B)", "Estimated Crashes Avoided / Yr": f"{b_val:.2f}", "Share of Total": f"{(b_val/tot_val)*100:.2f}%"},
        {"Outcome Tier": "Secondary (Non-Severe)", "Severity Category": "Possible injury crashes (C)", "Estimated Crashes Avoided / Yr": f"{c_val:.2f}", "Share of Total": f"{(c_val/tot_val)*100:.2f}%"},
        {"Outcome Tier": "Secondary (Property Damage)", "Severity Category": "Property damage only crashes (PDO / O)", "Estimated Crashes Avoided / Yr": f"{o_val:.2f}", "Share of Total": f"{(o_val/tot_val)*100:.2f}%"},
        {"Outcome Tier": "Total", "Severity Category": "All-severity crashes (Total)", "Estimated Crashes Avoided / Yr": f"{tot_val:,.2f}", "Share of Total": "100.00%"},
    ])
    st.dataframe(sev_df, use_container_width=True, hide_index=True)

# -----------------------------------------------------------------------------
# Section 5 — What-If Capital Planner
# -----------------------------------------------------------------------------
st.markdown("---")
st.subheader("5. What-if capital planner")
st.caption("Interactive optimization engine: evaluate alternative capital budgets and equity spending floors under active cost and CMF assumptions.")

st.markdown(
    "Explore how capital allocation, corridor funding rosters, and equity outcomes adjust under different budget ceilings and equity floors."
)

wif_budgets = [
    2000000.0, 3000000.0, 4000000.0, 5000000.0, 6000000.0,
    7000000.0, 8000000.0, 9000000.0, 10000000.0, 11000000.0,
    12000000.0, 13000000.0, 14000000.0, 15000000.0, 16000000.0,
    17000000.0, 18000000.0, 19000000.0, 20000000.0, 21000000.0,
    22000000.0, 23000000.0, 24000000.0, 25000000.0, 30000000.0,
    40000000.0,
]
wif_equities = [0.15, 0.20, 0.25, 0.30, 0.35, 0.40]


default_wb_val = scenario_params["budget"] if scenario_params["budget"] in wif_budgets else 15000000.0
default_wb_idx = wif_budgets.index(default_wb_val)

default_we_val = scenario_params["equity_floor"] if scenario_params["equity_floor"] in wif_equities else 0.20
default_we_idx = wif_equities.index(default_we_val)

wif_col1, wif_col2 = st.columns(2)
with wif_col1:
    user_budget = st.selectbox(
        "Select planning budget ceiling",
        options=wif_budgets,
        index=default_wb_idx,
        key="wif_budget_select",
        format_func=lambda b: f"${int(b / 1e6)}M" if b >= 1e6 else f"${int(b / 1e3)}k",
        help="Select a planning budget ceiling for what-if evaluation ($2M to $40M).",
    )
with wif_col2:
    user_equity = st.selectbox(
        "Select minimum equity spending floor",
        options=wif_equities,
        index=default_we_idx,
        key="wif_equity_select",
        format_func=lambda ef: f"{int(round(ef * 100))}%",
        help="Select minimum percentage of funding reserved for high-SVI equity priority corridors (15% to 50%).",
    )

wif_s_row, wif_sel_benefits = evaluate_portfolio_scenario(
    budget=float(user_budget),
    equity_floor=float(user_equity),
    cost_case=scenario_params["cost_case"],
    cmf_case=scenario_params["cmf_case"],
    df_benefits=df_benefits,
)

target_portfolio_id = str(wif_s_row["portfolio_id"])
wif_ksi = wif_sel_benefits["crashes_averted_ksi"].sum() if not wif_sel_benefits.empty else 0.0

st.info(
    f"**What-If Scenario Evaluated:** Budget Ceiling: **${int(wif_s_row['budget_usd']/1e6)}M** | "
    f"Equity Floor: **{int(round(wif_s_row['equity_floor']*100))}%** | "
    f"Cost: **{scenario_params['cost_case'].title()}** | "
    f"CMF: **{scenario_params['cmf_case'].title()}** | "
    f"Scenario ID: `{target_portfolio_id}`"
)

wc1, wc2, wc3, wc4 = st.columns(4)
with wc1:
    st.metric("Estimated capital cost", format_currency_compact(wif_s_row["selected_capital_cost"]), help=f"Planning-level estimate: {format_currency(wif_s_row['selected_capital_cost'])}")
with wc2:
    st.metric("Corridors funded", f"{int(wif_s_row['selected_project_count'])} / {total_corridors_count}")
with wc3:
    st.metric("Estimated KSI avoided / year", f"{format_ksi_compact(wif_ksi)} / yr", help=f"Denominator: {int(wif_s_row['selected_project_count'])} funded corridors in what-if portfolio. Severity scope: Fatal (K) + Serious injury (A) crashes. Planning-level estimate: ~{wif_ksi:,.1f} / yr")
with wc4:
    st.metric("High-SVI capital share", format_percent(wif_s_row["achieved_equity_share"]), help="Measures capital spending input only; not proof of equitable safety outcomes.")

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
wif_table["physical_applicability_status"] = wif_table["physical_applicability_status"].apply(format_engineering_status)
wif_table.columns = [
    "Corridor ID",
    "Corridor Name",
    "Recommended Treatment",
    "Estimated Capital Cost",
    "Estimated All-Severity Crashes Avoided / Yr",
    "Estimated Fatal (K) Avoided / Yr",
    "Estimated Serious Injury (A) Avoided / Yr",
    "High-SVI Priority Area",
    "Engineering Status",
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
if st.download_button(
    label=f"Download what-if portfolio CSV (${int(wif_s_row['budget_usd']/1e6)}M / {int(round(wif_s_row['equity_floor']*100))}% equity)",
    data=csv_data,
    file_name=f"vision_zero_what_if_{target_portfolio_id}.csv",
    mime="text/csv",
):
    try:
        from dashboard.streamlit.analytics import track_portfolio_exported
        track_portfolio_exported(
            scenario_id=target_portfolio_id,
            budget=float(wif_s_row["budget_usd"]),
        )
    except Exception:
        pass

# Standardized Consolidated Governance Footer (Decision DEC-04)
render_governance_footer()
