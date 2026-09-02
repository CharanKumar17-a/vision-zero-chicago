"""Executive Recommendation Page - Vision Zero Chicago Decision Support App.

Target audience: Capital Program Managers and City Leadership.
Written in plain business language with minimal jargon.
All figures derived dynamically at runtime.

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
import plotly.graph_objects as go
import streamlit as st

from dashboard.streamlit.components import (
    format_bcr_compact,
    format_cost_per_unit,
    format_count_compact,
    format_currency,
    format_currency_compact,
    format_equity_flag,
    format_ksi_compact,
    format_percent,
    format_plural,
    render_governance_footer,
    render_governance_header_banner,
    render_page_header,
    render_sidebar_controls,
)
from dashboard.streamlit.data_access import (
    DEFAULT_PORTFOLIO_ID,
    compute_economic_only_benefits,
    evaluate_portfolio_scenario,
    get_selected_portfolio_benefits,
    get_single_portfolio_selections,
    get_single_portfolio_summary,
    load_corridor_master,
    load_portfolio_summary,
    load_project_selections,
    load_treatment_benefits,
)

# -----------------------------------------------------------------------------
# Data Loading & Dynamic Scenario Evaluation
# -----------------------------------------------------------------------------
df_summary = load_portfolio_summary()
df_selections = load_project_selections()
df_master = load_corridor_master()
df_benefits = load_treatment_benefits()

# Render sidebar controls & get active scenario parameters
scenario_params = render_sidebar_controls(df_summary, return_dict=True)

# Dynamically solve active scenario
rec_summary, rec_selections = evaluate_portfolio_scenario(
    budget=scenario_params["budget"],
    equity_floor=scenario_params["equity_floor"],
    cost_case=scenario_params["cost_case"],
    cmf_case=scenario_params["cmf_case"],
    df_benefits=df_benefits,
)
rec_benefits = rec_selections

# Compute economic-only benefits for recommended portfolio
if not rec_benefits.empty:
    rec_benefits_econ = compute_economic_only_benefits(rec_benefits)
    total_annual_econ = float(rec_benefits_econ["annual_economic_benefit"].sum())
    total_pv_econ = float(rec_benefits_econ["pv_economic_benefit"].sum())
else:
    total_annual_econ = 0.0
    total_pv_econ = 0.0
bcr_econ_portfolio = total_pv_econ / float(rec_summary["selected_capital_cost"]) if float(rec_summary["selected_capital_cost"]) > 0 else 0.0

# Derived metrics for recommended portfolio (all dynamically computed)
total_corridors_count = len(df_master)
selected_corridors_count = int(rec_summary["selected_project_count"])
selected_capital_cost = float(rec_summary["selected_capital_cost"])
total_pv_benefit = float(rec_summary["total_present_value_benefit"])
portfolio_bcr = float(rec_summary["portfolio_bcr"])
achieved_equity_pct = float(rec_summary["achieved_equity_share"]) * 100
budget_slack = float(rec_summary["budget_slack"])

annual_crashes_averted = float(rec_benefits["crashes_averted_total"].sum()) if not rec_benefits.empty else 0.0
annual_k_averted = float(rec_benefits["crashes_averted_k"].sum()) if not rec_benefits.empty else 0.0
annual_a_averted = float(rec_benefits["crashes_averted_a"].sum()) if not rec_benefits.empty else 0.0
annual_b_averted = float(rec_benefits["crashes_averted_b"].sum()) if not rec_benefits.empty else 0.0
annual_c_averted = float(rec_benefits["crashes_averted_c"].sum()) if not rec_benefits.empty else 0.0
annual_o_averted = float(rec_benefits["crashes_averted_o"].sum()) if not rec_benefits.empty else 0.0
annual_ksi_averted = float(rec_benefits["crashes_averted_ksi"].sum()) if not rec_benefits.empty else 0.0

if not rec_benefits.empty:
    svi_mask = rec_benefits["equity_area_flag"] == True
    high_svi_ksi = float(rec_benefits[svi_mask]["crashes_averted_ksi"].sum())
    high_svi_cost = float(rec_benefits[svi_mask]["capital_project_cost"].sum())
else:
    high_svi_ksi = 0.0
    high_svi_cost = 0.0
high_svi_ksi_share = (high_svi_ksi / annual_ksi_averted * 100) if annual_ksi_averted > 0 else 0.0
high_svi_capital_share = (high_svi_cost / selected_capital_cost * 100) if selected_capital_cost > 0 else 0.0

# -----------------------------------------------------------------------------
# Landing Header & 4 Key Decision Metrics Hero
# -----------------------------------------------------------------------------
render_page_header(
    "Executive recommendation",
    "Planning-level decision support for prioritizing corridor safety investments under budget and equity constraints.",
)

b_title = f"${int(scenario_params['budget']/1e6)}M" if scenario_params['budget'] >= 1e6 else f"${int(scenario_params['budget']/1e3)}k"
ef_title = f"{int(round(scenario_params['equity_floor']*100))}%"
cost_title = scenario_params['cost_case'].title()
cmf_title = scenario_params['cmf_case'].title()

is_default_baseline = (
    scenario_params["budget"] == 15000000.0
    and scenario_params["equity_floor"] == 0.20
    and scenario_params["cost_case"] == "BASE"
    and scenario_params["cmf_case"] == "BASE"
)
header_tag = "Baseline Recommendation" if is_default_baseline else "Active Planning Scenario"

# Consolidated Executive Recommendation Callout Banner
render_governance_header_banner(
    run_group="OFFICIAL",
    is_official=True,
    scenario_params=scenario_params,
    custom_subtitle=(
        "&dollar;15M budget is binding (&dollar;14.99M allocated across 39 corridors); "
        "&dollar;25M / &dollar;40M allow full 43-corridor coverage. "
        "All selections require engineering field review. "
        "This tool does not authorize projects, establish construction scope, or replace engineering review."
    ),
)

# 4 Key Decision Metrics Hero
col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric(
        "Estimated capital cost",
        format_currency_compact(selected_capital_cost),
        help=f"Planning-level estimate: {format_currency(selected_capital_cost)} initial capital cost across {selected_corridors_count} shortlisted corridors.",
    )
with col2:
    st.metric(
        "Corridors funded",
        f"{selected_corridors_count} of {total_corridors_count}",
        help=f"Denominator: {total_corridors_count} candidate corridors in the high-crash network. Numerator: {selected_corridors_count} corridors funded under {b_title} budget. Subject to engineering review.",
    )
with col3:
    st.metric(
        "Estimated KSI avoided / year",
        f"{format_ksi_compact(annual_ksi_averted)} / yr",
        help=f"Denominator: {selected_corridors_count} shortlisted corridors. Severity scope: Fatal (K) + Serious/Incapacitating injury (A) crashes. Planning-level estimate: ~{annual_ksi_averted:,.1f} KSI avoided / yr.",
    )
with col4:
    st.metric(
        "High-SVI capital share",
        f"{high_svi_capital_share:.1f}%",
        delta=f"Floor: {format_percent(rec_summary['equity_floor'])}",
        help=f"Denominator: Total selected capital cost ({format_currency(selected_capital_cost)}). Numerator: Capital allocated to high-SVI corridors ({format_currency(high_svi_cost)}). Measures capital spending input only; not proof of equitable safety outcomes. SVI is used as a spatial equity proxy.",
    )

st.caption(f"Optimization status: Mathematically optimal under stated planning constraints (&dollar;{selected_capital_cost/1e6:.2f}M of {b_title.replace('$', '&dollar;')} allocated • {format_currency(budget_slack).replace('$', '&dollar;')} budget slack)")

# 2026 pre-treatment baseline context line — makes KSI-avoided figures interpretable
_baseline_total_2026 = float(df_master["annual_forecast_total_crashes_2026"].sum())
_baseline_ksi_2026 = float(df_master["annual_forecast_ksi_crashes_2026"].sum())
st.info(
    f"**2026 pre-treatment network baseline (all 43 corridors, no intervention):** "
    f"~{_baseline_total_2026:,.0f} total crashes / yr · ~{_baseline_ksi_2026:.0f} KSI / yr — "
    f"the forecast starting point that the recommended portfolio acts against.",
    icon="📊",
)

# -----------------------------------------------------------------------------
# Section 1 — What This Investment Buys
# -----------------------------------------------------------------------------
st.markdown("---")
st.subheader("1. What this planning investment buys")

st.markdown(
    "Over a 20-year project lifecycle using a 3.0% real discount-rate assumption, "
    "this capital program delivers substantial life-safety reductions across Chicago's highest-risk roadways. "
    "All figures represent planning-level estimates."
)

# Life-Safety Granular Metrics
ls_col1, ls_col2, ls_col3 = st.columns(3)
with ls_col1:
    st.metric(
        "Fatal crashes (K) avoided",
        f"~{annual_k_averted:.1f} / yr",
        help=f"Denominator: {selected_corridors_count} shortlisted corridors. Exact: {annual_k_averted:.2f} fatal crashes avoided / yr.",
    )
with ls_col2:
    st.metric(
        "Serious injuries (A) avoided",
        f"~{annual_a_averted:.1f} / yr",
        help=f"Denominator: {selected_corridors_count} shortlisted corridors. Exact: {annual_a_averted:.2f} serious injury crashes avoided / yr.",
    )
with ls_col3:
    st.metric(
        "All-severity crashes avoided",
        f"{format_count_compact(annual_crashes_averted)} / yr",
        help=f"Denominator: {selected_corridors_count} shortlisted corridors. Scope: All severities (K, A, B, C, PDO). Exact: {annual_crashes_averted:,.2f} / yr.",
    )


col_benefit1, col_benefit2 = st.columns([3, 2])

with col_benefit1:
    st.markdown("#### Primary life-safety and economic outcomes")
    summary_data = [
        {
            "Outcome Measure": "Vision Zero Life-Safety (Fatalities & Serious Injuries)",
            "Estimated Annual Impact": f"~{annual_ksi_averted:.1f} / yr",
            "Planning Context": f"~{annual_k_averted:.1f} Fatal (K) + ~{annual_a_averted:.1f} Serious Injury (A) avoided",
        },
        {
            "Outcome Measure": "All-Severity Crashes Avoided",
            "Estimated Annual Impact": f"~{int(round(annual_crashes_averted)):,} / yr",
            "Planning Context": f"Across all {selected_corridors_count} funded corridors (incl. minor injury & PDO)",
        },
        {
            "Outcome Measure": "20-Year Lifecycle Safety Benefit",
            "Estimated Annual Impact": f"{format_currency_compact(total_pv_benefit)}",
            "Planning Context": f"{format_currency(total_pv_benefit)} present value at 3.0% real discount",
        },
        {
            "Outcome Measure": "Portfolio benefit-cost ratio (planning-level scenario estimate)",
            "Estimated Annual Impact": f"{format_bcr_compact(portfolio_bcr)}",
            "Planning Context": f"{portfolio_bcr:.1f} : 1 • Planning-level scenario estimate; not an expected realized program return.",
        },
    ]
    st.dataframe(pd.DataFrame(summary_data), width="stretch", hide_index=True)

with col_benefit2:
    st.markdown("#### Economic and equity return summary")
    st.markdown(
        f"""
        - **Present value safety benefit (planning-level estimate):** `{format_currency_compact(total_pv_benefit)}` ({format_currency(total_pv_benefit)})
        - **Portfolio benefit-cost ratio (planning-level scenario estimate):** `{format_bcr_compact(portfolio_bcr)}` ({portfolio_bcr:.1f} : 1; planning-level scenario estimate, not an expected realized program return)
        - **High-SVI capital share (spending equity):** `{high_svi_capital_share:.1f}%` (Policy floor: `{format_percent(rec_summary['equity_floor'])}`)
        - **KSI benefit share in high-SVI areas (safety benefit equity):** `{high_svi_ksi_share:.1f}%` (~{high_svi_ksi:.1f} of ~{annual_ksi_averted:.1f} annual KSI avoided)
        - **Engineering status:** **Engineering review required** (Provisional applicability `UNKNOWN`)
        - **Portfolio classification:** **Analytical planning portfolio** (Subject to engineering review; not yet an implementation-ready portfolio)
        - **Eligibility criteria:** Every funded project provides an individual Benefit-Cost Ratio >= 1.0 (planning-level estimate).
        """
    )

with st.expander("View conservative economic-only cost scenario", expanded=False):
    st.markdown(
        "20-year planning-level estimate using direct tangible economic crash costs; excludes non-market societal valuation. "
        "Using **economic-only crash costs** (FHWA 2025) accounts strictly for direct tangible economic costs "
        "(medical treatment, emergency services, wage loss, property damage) without quality-of-life additions. "
        "Neither is an expected City return; both are planning-level scenario estimates."
    )
    econ_col1, econ_col2, econ_col3 = st.columns(3)
    with econ_col1:
        st.metric(
            "Economic-only 20-year PV benefit",
            format_currency_compact(total_pv_econ),
            help=f"Planning-level estimate: {format_currency(total_pv_econ)} direct tangible economic savings over 20 years at 3.0% real discount.",
        )
    with econ_col2:
        st.metric(
            "Economic-only 20-year BCR",
            f"~{bcr_econ_portfolio:.1f}:1",
            help=f"Planning-level estimate: {bcr_econ_portfolio:.1f} : 1 Benefit-Cost Ratio using direct tangible economic costs only.",
        )
    with econ_col3:
        st.metric(
            "Annual economic savings",
            f"{format_currency_compact(total_annual_econ)} / yr",
            help=f"Planning-level estimate: {format_currency(total_annual_econ)} / yr direct economic crash costs prevented.",
        )

# -----------------------------------------------------------------------------
# Section 2 — Deferred Corridors (Planning Alternatives)
# -----------------------------------------------------------------------------
st.markdown("---")
st.subheader("2. Deferred corridors (planning alternatives)")

selected_ids = set(rec_selections["corridor_id"]) if not rec_selections.empty else set()
all_ids = set(df_master["corridor_id"])
unselected_ids = sorted(list(all_ids - selected_ids))

active_cmf = scenario_params["cmf_case"]
base_benefits = df_benefits[
    (df_benefits["uncertainty_scenario"] == active_cmf)
    if "uncertainty_scenario" in df_benefits.columns
    else (df_benefits["scenario_level"] == active_cmf)
]
unselected_candidates = base_benefits[base_benefits["corridor_id"].isin(unselected_ids)]

deferred_list = []
for cid in unselected_ids:
    c_cands = unselected_candidates[unselected_candidates["corridor_id"] == cid]
    if "physical_applicability_status" in c_cands.columns:
        c_cands_app = c_cands[c_cands["physical_applicability_status"] != "NOT_APPLICABLE"]
        if len(c_cands_app) > 0:
            c_cands = c_cands_app
    if c_cands.empty:
        continue
    best_cand = c_cands.sort_values("benefit_cost_ratio", ascending=False).iloc[0]
    c_master = df_master[df_master["corridor_id"] == cid].iloc[0]

    cand_cost = float(best_cand["capital_project_cost"])
    cand_ksi_averted = float(best_cand["crashes_averted_k"] + best_cand["crashes_averted_a"])
    cand_tot_averted = float(best_cand["crashes_averted_total"])
    cand_bcr = float(best_cand["benefit_cost_ratio"])

    cost_per_ksi_str = format_cost_per_unit(cand_cost, cand_ksi_averted, "KSI")
    cost_per_crash_str = format_cost_per_unit(cand_cost, cand_tot_averted, "crash")
    equity_str = format_equity_flag(best_cand.get("equity_area_flag", False))

    deferred_list.append({
        "Corridor ID": cid,
        "Corridor Name": c_master["corridor_name"],
        "Best Applicable Treatment": best_cand["treatment_name"],
        "Estimated Capital Cost": format_currency(cand_cost),
        "Cost per KSI Avoided": cost_per_ksi_str,
        "Cost per Crash Avoided": cost_per_crash_str,
        "Benefit-Cost Ratio (BCR)": f"{cand_bcr:.1f}",
        "raw_bcr": cand_bcr,
        "PV Safety Benefit (Planning-Level)": format_currency(float(best_cand["present_value_benefit"])),
        "Equity Priority Area": equity_str,
    })

df_deferred = pd.DataFrame(deferred_list).sort_values("raw_bcr", ascending=False) if deferred_list else pd.DataFrame()
display_cols = [c for c in df_deferred.columns if c != "raw_bcr"] if not df_deferred.empty else []

deferred_count_str = format_plural(len(df_deferred), "corridor")
deferred_all_positive_roi = all(float(r["raw_bcr"]) >= 1.0 for _, r in df_deferred.iterrows()) if not df_deferred.empty else True

st.markdown(
    f"Under the **{b_title.replace('$', '&dollar;')} budget ceiling**, **{deferred_count_str}** {'is' if len(df_deferred) == 1 else 'are'} deferred: "
    f"the optimized portfolio exhausts the available budget, and the remaining **{format_currency(budget_slack).replace('$', '&dollar;')}** "
    f"is insufficient to fund those alternatives. "
    f"{'All deferred corridors have positive planning-level BCRs (>1.0)' if deferred_all_positive_roi else 'Viable candidate projects exist'}. "
    "All figures represent planning-level estimates subject to engineering review."
)

if not df_deferred.empty:
    st.dataframe(df_deferred[display_cols], width="stretch", hide_index=True)
else:
    st.success("All 43 candidate corridors are funded under this scenario!")
st.caption(
    "Lower cost per KSI avoided = more efficient at preventing the most severe crashes. "
    "These are planning-level estimates subject to engineering review and implementation approval."
)

# -----------------------------------------------------------------------------
# Section 3 — Sensitivity to Budget & Progression
# -----------------------------------------------------------------------------
st.markdown("---")
st.subheader("3. Budget sensitivity and progression")

st.markdown(
    "How does corridor coverage and total safety return scale if capital is constrained or if additional funds are appropriated? "
    "The progression table below outlines the **'what more money buys'** scaling across budget tiers."
)

progression_budgets = [2000000.0, 4000000.0, 6000000.0, 15000000.0, 25000000.0, 40000000.0]
progression_records = []

for b_val in progression_budgets:
    s_tier, d_tier = evaluate_portfolio_scenario(
        budget=b_val,
        equity_floor=scenario_params["equity_floor"],
        cost_case=scenario_params["cost_case"],
        cmf_case=scenario_params["cmf_case"],
        df_benefits=df_benefits,
    )
    b_str = f"${int(b_val / 1e6)}M" if b_val >= 1e6 else f"${int(b_val / 1e3)}k"
    c_cost = float(s_tier["selected_capital_cost"])
    pv_b = float(s_tier["total_present_value_benefit"])
    p_bcr = float(s_tier["portfolio_bcr"])
    n_sel = int(s_tier["selected_project_count"])
    eq_share = float(s_tier["achieved_equity_share"]) * 100

    if not d_tier.empty:
        p_econ = compute_economic_only_benefits(d_tier)
        pv_econ = float(p_econ["pv_economic_benefit"].sum())
        tot_crashes_av = float(d_tier["crashes_averted_total"].sum())
        ksi_av = float(d_tier["crashes_averted_ksi"].sum())
    else:
        pv_econ, tot_crashes_av, ksi_av = 0.0, 0.0, 0.0

    tier_type = "Diagnostic stress" if b_val < 15e6 else ("Official (binding)" if b_val == 15e6 else "Official (expanded)")

    progression_records.append({
        "Budget Tier": b_str,
        "Scenario Type": tier_type,
        "Corridors Selected": n_sel,
        "Corridor Coverage": f"{n_sel} of {total_corridors_count} ({n_sel/total_corridors_count*100:.0f}%)",
        "Estimated Capital Cost": format_currency(c_cost),
        "Comprehensive PV Benefit": format_currency(pv_b),
        "Economic-Only PV Benefit": format_currency(pv_econ),
        "Estimated Annual Crashes Avoided": f"{tot_crashes_av:,.1f} / yr",
        "Estimated Annual KSI Avoided": f"{ksi_av:,.2f} / yr",
        "Achieved Equity Share": f"{eq_share:.1f}%",
        "Portfolio BCR (Comp)": f"{p_bcr:.1f} : 1",
    })

df_prog = pd.DataFrame(progression_records)

col_sens_tbl, col_sens_chart = st.columns([3, 2])

with col_sens_tbl:
    st.markdown("#### Corridors and safety return by budget tier")
    st.dataframe(
        df_prog[[
            "Budget Tier", "Scenario Type", "Corridor Coverage", "Estimated Capital Cost",
            "Comprehensive PV Benefit", "Estimated Annual KSI Avoided", "Achieved Equity Share"
        ]],
        width="stretch",
        hide_index=True,
    )

with col_sens_chart:
    st.markdown("#### Corridors selected by budget tier")
    import plotly.graph_objects as go
    fig_chart = go.Figure()
    fig_chart.add_trace(go.Bar(
        x=df_prog["Budget Tier"],
        y=df_prog["Corridors Selected"],
        marker_color="#1f77b4",
        text=df_prog["Corridors Selected"],
        textposition="auto",
    ))
    fig_chart.update_layout(
        height=220,
        margin=dict(l=10, r=10, t=25, b=10),
        xaxis=dict(
            title="Budget tier",
            categoryorder="array",
            categoryarray=df_prog["Budget Tier"].tolist(),
        ),
        yaxis=dict(title="Corridors selected", range=[0, 45]),
    )
    st.plotly_chart(fig_chart, width="stretch")

st.info(
    f"**Budget finding (planning-level estimate):** Under {cost_title} costs and {cmf_title} CMFs, "
    f"at the **{b_title.replace('$', '&dollar;')} budget ceiling**, **{selected_corridors_count} of {total_corridors_count} corridors** are shortlisted."
)

# -----------------------------------------------------------------------------
# Section 4 — Decision Boundaries & Governance
# -----------------------------------------------------------------------------
st.markdown("---")
st.subheader("4. Decision boundaries and engineering qualifications")

st.markdown(
    """
    - **Analytical planning portfolio**: This tool generates an analytical planning portfolio based on mathematical optimization, statistical crash risk forecasts, and sourced planning-level treatment costs. All selected treatments carry a provisional engineering status of `UNKNOWN` (*"Engineering review required"*).
    - **Physical applicability**: Lane counts, median widths, and crossing inventories are not yet available in the analytical dataset. Detailed engineering field survey is required prior to capital programming.
    - **Comprehensive crash costs**: Benefits reflect federal comprehensive societal crash costs (USDOT 2024 guidance) and do not represent expected City municipal revenue.
    """
)

# Standardized Consolidated Governance Footer
render_governance_footer()
