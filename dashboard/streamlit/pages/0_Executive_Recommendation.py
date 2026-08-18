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
import streamlit as st

from dashboard.streamlit.components import (
    format_cost_per_unit,
    format_currency,
    format_equity_flag,
    format_percent,
    format_plural,
    render_economic_caveat_banner,
    render_engineering_review_banner,
)
from dashboard.streamlit.data_access import (
    DEFAULT_PORTFOLIO_ID,
    compute_economic_only_benefits,
    get_selected_portfolio_benefits,
    get_single_portfolio_selections,
    get_single_portfolio_summary,
    load_corridor_master,
    load_portfolio_summary,
    load_project_selections,
    load_treatment_benefits,
)

# -----------------------------------------------------------------------------
# Data Loading
# -----------------------------------------------------------------------------
df_summary = load_portfolio_summary()
df_selections = load_project_selections()
df_master = load_corridor_master()
df_benefits = load_treatment_benefits()

# Canonical recommended portfolio: OFFICIAL BASE $15M with 20% equity floor
rec_summary = get_single_portfolio_summary(df_summary, DEFAULT_PORTFOLIO_ID)
rec_selections = get_single_portfolio_selections(df_selections, DEFAULT_PORTFOLIO_ID)
rec_benefits = get_selected_portfolio_benefits(df_selections, df_benefits, DEFAULT_PORTFOLIO_ID)

# Compute economic-only benefits for recommended portfolio
rec_benefits_econ = compute_economic_only_benefits(rec_benefits)
total_annual_econ = float(rec_benefits_econ["annual_economic_benefit"].sum())
total_pv_econ = float(rec_benefits_econ["pv_economic_benefit"].sum())
bcr_econ_portfolio = total_pv_econ / float(rec_summary["selected_capital_cost"]) if float(rec_summary["selected_capital_cost"]) > 0 else 0.0

# Derived metrics for recommended portfolio (all dynamically computed)
total_corridors_count = len(df_master)
selected_corridors_count = int(rec_summary["selected_project_count"])
selected_capital_cost = float(rec_summary["selected_capital_cost"])
total_pv_benefit = float(rec_summary["total_present_value_benefit"])
portfolio_bcr = float(rec_summary["portfolio_bcr"])
achieved_equity_pct = float(rec_summary["achieved_equity_share"]) * 100
budget_slack = float(rec_summary["budget_slack"])

annual_crashes_averted = float(rec_benefits["crashes_averted_total"].sum())
annual_k_averted = float(rec_benefits["crashes_averted_k"].sum())
annual_a_averted = float(rec_benefits["crashes_averted_a"].sum())
annual_b_averted = float(rec_benefits["crashes_averted_b"].sum())
annual_c_averted = float(rec_benefits["crashes_averted_c"].sum())
annual_o_averted = float(rec_benefits["crashes_averted_o"].sum())
annual_ksi_averted = float(rec_benefits["crashes_averted_ksi"].sum())

# -----------------------------------------------------------------------------
# Landing Header & 4 Key Decision Metrics Hero
# -----------------------------------------------------------------------------
st.title("Vision Zero Chicago — Safety Capital Investment Prioritization")
st.subheader("Planning recommendation")
st.caption("Planning-level decision support for prioritizing corridor safety investments under budget and equity constraints.")

# Mandatory Authority Statement
st.info(
    "**Decision Support Notice:** This tool provides planning-level decision support. "
    "It does not authorize projects, establish construction scope, or replace engineering review."
)

st.markdown("")

# 4 Key Decision Metrics
col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric(
        "Estimated capital cost",
        format_currency(selected_capital_cost),
        help="Planning-level estimate of initial capital cost for shortlisted corridor projects.",
    )
with col2:
    st.metric(
        "Corridors funded",
        f"{selected_corridors_count} of {total_corridors_count}",
        help="High-crash corridors shortlisted under the $15M planning budget scenario. Subject to engineering review and implementation approval.",
    )
with col3:
    st.metric(
        "Estimated annual KSI avoided",
        f"~{annual_ksi_averted:,.1f} / yr",
        help="Planning-level estimate of annual fatal (K) and serious injury (A) crashes avoided across shortlisted corridors.",
    )
with col4:
    st.metric(
        "Equity spend share",
        f"{achieved_equity_pct:.1f}%",
        delta=f"Floor: {format_percent(rec_summary['equity_floor'])}",
        help="Percentage of planning capital investment allocated to high-SVI equity priority areas.",
    )

st.markdown("")

# Planning Recommendation Callout
st.success(
    f"**Planning Recommendation:** Under the Baseline Scenario ($15M budget, 20% equity floor), "
    f"the optimized planning portfolio funds **{selected_corridors_count} of {total_corridors_count}** "
    f"corridors for **{format_currency(selected_capital_cost)}**, with an estimated **{annual_crashes_averted:,.0f}** crashes avoided / yr "
    f"(including **{annual_ksi_averted:,.1f}** fatal and serious injury crashes avoided), with "
    f"**{achieved_equity_pct:.1f}%** of spend directed to high-SVI equity-priority areas. "
    f"Subject to engineering review and implementation approval."
)

st.caption(
    f"Active scenario: `{DEFAULT_PORTFOLIO_ID}` | Status: **Mathematically optimal under stated assumptions** | Budget slack: `{format_currency(budget_slack)}`"
)

# -----------------------------------------------------------------------------
# Section 1 — What This Investment Buys
# -----------------------------------------------------------------------------
st.markdown("---")
st.subheader("1. What this planning investment buys")

st.markdown(
    "Over a 20-year project lifecycle with standard federal discount rates (3.0% real), "
    "this capital program delivers substantial and measurable life-safety reductions across Chicago's highest-risk roadways."
)

col_benefit1, col_benefit2 = st.columns([3, 2])

with col_benefit1:
    st.markdown("#### Estimated annual safety impact by severity")
    severity_data = [
        {"Severity category": "Fatal crashes (K)", "Estimated crashes avoided / year": f"{annual_k_averted:.2f}", "Share of total": f"{(annual_k_averted / annual_crashes_averted) * 100:.2f}%"},
        {"Severity category": "Incapacitating injury crashes (A)", "Estimated crashes avoided / year": f"{annual_a_averted:.2f}", "Share of total": f"{(annual_a_averted / annual_crashes_averted) * 100:.2f}%"},
        {"Severity category": "Non-incapacitating injury crashes (B)", "Estimated crashes avoided / year": f"{annual_b_averted:.2f}", "Share of total": f"{(annual_b_averted / annual_crashes_averted) * 100:.2f}%"},
        {"Severity category": "Possible injury crashes (C)", "Estimated crashes avoided / year": f"{annual_c_averted:.2f}", "Share of total": f"{(annual_c_averted / annual_crashes_averted) * 100:.2f}%"},
        {"Severity category": "Property damage only (O)", "Estimated crashes avoided / year": f"{annual_o_averted:.2f}", "Share of total": f"{(annual_o_averted / annual_crashes_averted) * 100:.2f}%"},
        {"Severity category": "Total crashes (all severities)", "Estimated crashes avoided / year": f"{annual_crashes_averted:,.2f}", "Share of total": "100.00%"},
    ]
    st.dataframe(pd.DataFrame(severity_data), use_container_width=True, hide_index=True)

with col_benefit2:
    st.markdown("#### Economic and equity return summary")
    st.markdown(
        f"""
        - **Present value safety benefit (planning-level):** `{format_currency(total_pv_benefit)}`
        - **Portfolio benefit-cost ratio (BCR):** `{portfolio_bcr:.1f} : 1`
        - **Achieved equity share:** `{achieved_equity_pct:.1f}%` (Policy floor: `20.0%`)
        - **Physical applicability:** `UNKNOWN` (Subject to engineering review and implementation approval)
        - **Eligibility criteria:** Every funded project provides an individual Benefit-Cost Ratio >= 1.0.
        """
    )

with st.expander("View conservative economic-only cost scenario", expanded=False):
    st.markdown(
        "Using **economic-only crash costs** (FHWA 2025) yields a more conservative benefit estimate by accounting only for "
        "direct tangible economic costs (medical treatment, emergency services, wage loss, property damage) without quality-of-life additions. "
        "Comprehensive costs (incl. quality-of-life) are shown elsewhere. Neither is an expected City return; both are planning-level estimates."
    )
    econ_col1, econ_col2, econ_col3 = st.columns(3)
    with econ_col1:
        st.metric("Economic-only PV benefit", format_currency(total_pv_econ), help="Present value benefit using direct tangible economic costs.")
    with econ_col2:
        st.metric("Economic-only portfolio BCR", f"{bcr_econ_portfolio:.1f} : 1", help="Benefit-Cost Ratio under conservative economic-only costs.")
    with econ_col3:
        st.metric("Annual economic savings", f"{format_currency(total_annual_econ)} / yr", help="Estimated annual direct economic crash costs prevented.")

# -----------------------------------------------------------------------------
# Section 2 — Deferred Corridors
# -----------------------------------------------------------------------------
st.markdown("---")
st.subheader("2. Deferred corridors (planning alternatives)")

selected_ids = set(rec_selections["corridor_id"])
all_ids = set(df_master["corridor_id"])
unselected_ids = sorted(list(all_ids - selected_ids))

base_benefits = df_benefits[
    (df_benefits["uncertainty_scenario"] == "BASE")
    if "uncertainty_scenario" in df_benefits.columns
    else (df_benefits["scenario_level"] == "BASE")
]
unselected_candidates = base_benefits[base_benefits["corridor_id"].isin(unselected_ids)]

deferred_list = []
for cid in unselected_ids:
    c_cands = unselected_candidates[unselected_candidates["corridor_id"] == cid]
    if "physical_applicability_status" in c_cands.columns:
        c_cands_app = c_cands[c_cands["physical_applicability_status"] != "NOT_APPLICABLE"]
        if len(c_cands_app) > 0:
            c_cands = c_cands_app
    best_cand = c_cands.sort_values("benefit_cost_ratio", ascending=False).iloc[0]
    c_master = df_master[df_master["corridor_id"] == cid].iloc[0]

    cand_cost = float(best_cand["capital_project_cost"])
    cand_ksi_averted = float(best_cand["crashes_averted_k"] + best_cand["crashes_averted_a"])
    cand_tot_averted = float(best_cand["crashes_averted_total"])

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
        "Benefit-Cost Ratio (BCR)": f"{float(best_cand['benefit_cost_ratio']):.1f}",
        "PV Safety Benefit (Planning-Level)": format_currency(float(best_cand["present_value_benefit"])),
        "Equity Priority Area": equity_str,
    })

df_deferred = pd.DataFrame(deferred_list).sort_values("Benefit-Cost Ratio (BCR)", ascending=False)

deferred_count_str = format_plural(len(df_deferred), "corridor")
st.markdown(
    f"Under the **\\$15M budget ceiling**, **{deferred_count_str}** {'is' if len(df_deferred) == 1 else 'are'} deferred. "
    f"{'This corridor has a viable safety project' if len(df_deferred) == 1 else 'These corridors have viable safety projects'} (BCR > 1.0), "
    f"but could not be accommodated within the \\$15M ceiling because costs exceed the remaining budget slack ({format_currency(budget_slack)}) "
    f"or higher-ROI alternatives took precedence under portfolio diversification constraints."
)

st.dataframe(df_deferred, use_container_width=True, hide_index=True)
st.caption(
    "Lower cost per KSI avoided = more efficient at preventing the most severe crashes. "
    "These are planning-level estimates subject to engineering review and implementation approval."
)

# -----------------------------------------------------------------------------
# Section 3 — Sensitivity to Budget & Stress Scenarios
# -----------------------------------------------------------------------------
st.markdown("---")
st.subheader("3. Budget sensitivity and stress scenarios")

st.markdown(
    "How does corridor coverage and total safety return scale if capital is constrained or if additional funds are appropriated? "
    "Explore the **'what more money buys'** progression across both diagnostic stress tiers and official planning scenarios."
)

st.caption(
    "Stress budgets (\\$2M, \\$4M, \\$6M) are analyst-defined diagnostic scenarios; "
    "\\$15M, \\$25M, \\$40M are planning scenarios. All figures are planning-level estimates."
)

# Build sensitivity datasets across official and stress budgets in BASE scenario
sens_official = df_summary[
    (df_summary["run_group"] == "OFFICIAL")
    & (df_summary["uncertainty_scenario"] == "BASE")
    & (df_summary["equity_floor"] == 0.20)
].sort_values("budget_usd")

sens_stress = df_summary[
    (df_summary["run_group"] == "BINDING-BUDGET STRESS TEST")
    & (df_summary["uncertainty_scenario"] == "BASE")
    & (df_summary["equity_floor"] == 0.20)
].sort_values("budget_usd")

# Combine into progression records
progression_records = []
tier_map = {}

for _, row in pd.concat([sens_stress, sens_official]).sort_values("budget_usd").iterrows():
    pid = str(row["portfolio_id"])
    b_val = float(row["budget_usd"])
    b_str = f"${int(b_val / 1e6)}M"
    c_cost = float(row["selected_capital_cost"])
    pv_b = float(row["total_present_value_benefit"])
    p_bcr = float(row["portfolio_bcr"])
    n_sel = int(row["selected_project_count"])
    eq_share = float(row["achieved_equity_share"]) * 100

    # Calculate economic-only PV for this portfolio
    p_benefits = get_selected_portfolio_benefits(df_selections, df_benefits, pid)
    p_econ = compute_economic_only_benefits(p_benefits)
    pv_econ = float(p_econ["pv_economic_benefit"].sum())
    tot_crashes_av = float(p_benefits["crashes_averted_total"].sum())
    ksi_av = float(p_benefits["crashes_averted_ksi"].sum())

    tier_type = "Diagnostic stress" if "STR" in pid else ("Official (binding)" if b_val == 15e6 else "Official (nonbinding)")
    display_label = f"{b_str} ({tier_type})"

    tier_map[display_label] = {
        "portfolio_id": pid,
        "budget_usd": b_val,
        "budget_str": b_str,
        "tier_type": tier_type,
        "n_sel": n_sel,
        "c_cost": c_cost,
        "pv_comp": pv_b,
        "pv_econ": pv_econ,
        "bcr_comp": p_bcr,
        "crashes_averted": tot_crashes_av,
        "ksi_averted": ksi_av,
        "equity_share": eq_share,
        "benefits_df": p_benefits,
        "econ_df": p_econ,
    }

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

# Overview columns: Table on left, bar chart on right
col_sens_tbl, col_sens_chart = st.columns([3, 2])

with col_sens_tbl:
    st.markdown("#### Corridors and safety return by budget tier")
    st.dataframe(
        df_prog[[
            "Budget Tier", "Scenario Type", "Corridor Coverage", "Estimated Capital Cost",
            "Comprehensive PV Benefit", "Estimated Annual KSI Avoided", "Achieved Equity Share"
        ]],
        use_container_width=True,
        hide_index=True,
    )

with col_sens_chart:
    st.markdown("#### Corridors selected by budget tier")
    df_chart = df_prog[["Budget Tier", "Corridors Selected"]].set_index("Budget Tier")
    st.bar_chart(df_chart, height=220)

st.info(
    f"**Budget finding (planning-level estimate)**: At the **\\$15M** budget ceiling, **{selected_corridors_count} of {total_corridors_count} corridors** are shortlisted. "
    f"Expanding to **\\$25M** covers all {total_corridors_count} corridors (100% network coverage)."
)

# Interactive Stress-Scenario Drilldown
st.markdown("#### Interactive budget scenario inspector")
selected_tier_label = st.selectbox(
    "Select budget scenario to inspect:",
    options=list(tier_map.keys()),
    index=3,  # Default to $15M
    help="Select a budget level to inspect its specific portfolio trade-offs, selected corridor roster, and safety metrics."
)

sel_tier = tier_map[selected_tier_label]

sc1, sc2, sc3, sc4, sc5 = st.columns(5)
with sc1:
    st.metric("Corridors funded", f"{sel_tier['n_sel']} of {total_corridors_count}", f"{(sel_tier['n_sel']/total_corridors_count)*100:.1f}% of network")
with sc2:
    st.metric("Estimated capital cost", format_currency(sel_tier["c_cost"]), f"Budget: {sel_tier['budget_str']}")
with sc3:
    st.metric("PV safety benefit (comp)", format_currency(sel_tier["pv_comp"]), f"BCR: {sel_tier['bcr_comp']:.1f} : 1")
with sc4:
    econ_bcr_val = sel_tier["pv_econ"] / sel_tier["c_cost"] if sel_tier["c_cost"] > 0 else 0.0
    st.metric("PV benefit (economic-only)", format_currency(sel_tier["pv_econ"]), f"Econ BCR: {econ_bcr_val:.1f} : 1")
with sc5:
    st.metric("Estimated crashes avoided", f"{sel_tier['crashes_averted']:,.1f} / yr", f"KSI: {sel_tier['ksi_averted']:.2f} / yr")

# Display corridor roster table for this scenario
st.markdown(f"**Shortlisted corridors for {selected_tier_label} ({sel_tier['n_sel']} corridors):**")

tier_sel_benefits = sel_tier["benefits_df"].copy()

tier_roster = []
for _, crow in tier_sel_benefits.iterrows():
    cid = crow["corridor_id"]
    cm = df_master[df_master["corridor_id"] == cid].iloc[0]
    c_cost = float(crow["capital_project_cost"])
    c_ksi = float(crow["crashes_averted_ksi"])
    c_tot = float(crow["crashes_averted_total"])
    c_bcr = float(crow["benefit_cost_ratio"])
    eq_str = format_equity_flag(crow.get("equity_area_flag", False))
    cost_per_ksi_str = format_cost_per_unit(c_cost, c_ksi, "KSI")

    tier_roster.append({
        "Corridor ID": cid,
        "Corridor Name": cm["corridor_name"],
        "Recommended Treatment": crow["treatment_name"],
        "Estimated Capital Cost": format_currency(c_cost),
        "Benefit-Cost Ratio": f"{c_bcr:.1f}",
        "Estimated Annual Crashes Avoided": f"{c_tot:.2f} / yr",
        "Estimated Annual KSI Avoided": f"{c_ksi:.2f} / yr",
        "Cost per KSI Avoided": cost_per_ksi_str,
        "Equity Priority Area": eq_str,
    })

df_tier_roster = pd.DataFrame(tier_roster)
st.dataframe(df_tier_roster, use_container_width=True, hide_index=True)

# -----------------------------------------------------------------------------
# Section 4 — Key Governance & Engineering Limitations
# -----------------------------------------------------------------------------
st.markdown("---")
st.subheader("4. Key governance and engineering limitations")

with st.expander("Review critical governance and engineering limitations", expanded=True):
    st.markdown(
        """
        - **Physical applicability is provisional (`UNKNOWN`)**:
          Treatments are selected based on corridor road classifications and centerline geometry.
          Specific corridor constraints (curb alignments, turn lanes, utility conflicts, bridge deck widths, transit lanes)
          require detailed engineering field inspections before design or construction.
        - **Sourced planning costs versus contract bids**:
          Unit costs (\\$400k/mi Road Diet, \\$15k/island Refuge Island, \\$22.5k RRFB; `D024`) are planning-level benchmarks.
          Actual construction costs will vary based on procurement, site work, signal integration, and material prices.
        - **CDC Social Vulnerability Index (SVI) as equity proxy**:
          SVI percentile tracks spatial vulnerability across census tracts, but does not substitute for localized community engagement or neighborhood-level equity evaluations.
        - **Statistical crash burden versus deterministic occurrence**:
          Forecast models evaluate multi-year statistical crash risk and regression-to-the-mean tendencies. They identify high-probability corridors, not guarantees of specific crash occurrences.
        - **Planning scenarios versus policy appropriations**:
          Portfolio scenarios represent decision-support alternatives. They do not constitute official City of Chicago capital budget commitments or project authorizations.
        """
    )

render_engineering_review_banner()
render_economic_caveat_banner()

# -----------------------------------------------------------------------------
# Footer
# -----------------------------------------------------------------------------
st.markdown("---")
st.caption(
    "**Vision Zero Chicago Decision Support System** | "
    "This tool provides planning-level decision support. It does not authorize projects, establish construction scope, or replace engineering review. "
    "Final authority remains with City staff and engineering reviewers."
)


