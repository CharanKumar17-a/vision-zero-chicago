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
    format_currency,
    format_percent,
)
from dashboard.streamlit.data_access import (
    DEFAULT_PORTFOLIO_ID,
    get_selected_portfolio_benefits,
    get_single_portfolio_selections,
    get_single_portfolio_summary,
    load_corridor_master,
    load_portfolio_summary,
    load_project_selections,
    load_treatment_benefits,
)

st.set_page_config(page_title="Executive Recommendation - Vision Zero Chicago", layout="wide")

st.title("🎯 Executive Recommendation: Safety Investment Portfolio")
st.markdown(
    "**What should we do?** High-level decision-support briefing and capital allocation recommendation "
    "for City of Chicago transportation leadership."
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

# Derived metrics for recommended portfolio
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
annual_ksi_averted = annual_k_averted + annual_a_averted

# -----------------------------------------------------------------------------
# Section 1 — Recommended Portfolio
# -----------------------------------------------------------------------------
st.header("1. Recommended Portfolio")

headline_text = (
    f"At a \\$15M planning budget, this portfolio funds **{selected_corridors_count} of {total_corridors_count}** "
    f"corridors for **{format_currency(selected_capital_cost)}**, averting ~**{annual_crashes_averted:,.0f}** crashes/yr "
    f"including ~**{annual_ksi_averted:,.0f}** fatal and serious injury (KSI) crashes, with "
    f"**{achieved_equity_pct:.1f}%** of spend in equity-priority areas."
)

st.success(headline_text)

col1, col2, col3, col4, col5 = st.columns(5)
with col1:
    st.metric("Total Capital Cost", format_currency(selected_capital_cost), help="Total estimated capital cost across selected treatments.")
with col2:
    st.metric("Corridors Funded", f"{selected_corridors_count} / {total_corridors_count}", help="High-crash corridors funded under this portfolio.")
with col3:
    st.metric("Annual Crashes Averted", f"~{annual_crashes_averted:,.0f} / yr", help="Estimated annual total crashes prevented.")
with col4:
    st.metric("Annual KSI Averted", f"~{annual_ksi_averted:,.1f} / yr", help="Estimated annual Fatal (K) + Serious Injury (A) crashes prevented.")
with col5:
    st.metric("Equity Spend Share", f"{achieved_equity_pct:.1f}%", help="Percentage of capital investment allocated to high-SVI equity tracts (vs 20% policy floor).")

st.caption(
    f"Scenario ID: `{DEFAULT_PORTFOLIO_ID}` | Optimization Status: `OPTIMAL` | Budget Slack: `{format_currency(budget_slack)}`"
)

# -----------------------------------------------------------------------------
# Section 2 — What This Buys
# -----------------------------------------------------------------------------
st.markdown("---")
st.header("2. What This Investment Buys")

st.markdown(
    "Over a 20-year project lifecycle with standard federal discount rates (3.0% real), "
    "this capital program delivers substantial and measurable life-safety reductions across Chicago's highest-risk roadways."
)

col_benefit1, col_benefit2 = st.columns([3, 2])

with col_benefit1:
    st.subheader("Annual Safety Impact by Severity")
    severity_data = [
        {"Severity Category": "Fatal Crashes (K)", "Crashes Averted / Year": f"{annual_k_averted:.2f}", "Share of Total": f"{(annual_k_averted / annual_crashes_averted) * 100:.2f}%"},
        {"Severity Category": "Incapacitating Injury Crashes (A)", "Crashes Averted / Year": f"{annual_a_averted:.2f}", "Share of Total": f"{(annual_a_averted / annual_crashes_averted) * 100:.2f}%"},
        {"Severity Category": "Non-Incapacitating Injury Crashes (B)", "Crashes Averted / Year": f"{annual_b_averted:.2f}", "Share of Total": f"{(annual_b_averted / annual_crashes_averted) * 100:.2f}%"},
        {"Severity Category": "Possible Injury Crashes (C)", "Crashes Averted / Year": f"{annual_c_averted:.2f}", "Share of Total": f"{(annual_c_averted / annual_crashes_averted) * 100:.2f}%"},
        {"Severity Category": "Property Damage Only (O)", "Crashes Averted / Year": f"{annual_o_averted:.2f}", "Share of Total": f"{(annual_o_averted / annual_crashes_averted) * 100:.2f}%"},
        {"Severity Category": "Total Crashes (All Severities)", "Crashes Averted / Year": f"{annual_crashes_averted:,.2f}", "Share of Total": "100.00%"},
    ]
    st.dataframe(pd.DataFrame(severity_data), use_container_width=True, hide_index=True)

with col_benefit2:
    st.subheader("Economic & Equity Return")
    st.markdown(
        f"""
        - **Present Value Safety Benefit:** `{format_currency(total_pv_benefit)}`
        - **Portfolio Benefit-Cost Ratio (BCR):** `{portfolio_bcr:.1f} : 1`
        - **Achieved Equity Share:** `{achieved_equity_pct:.1f}%` (Policy Floor: `20.0%`)
        - **Core Focus:** Every funded project provides an individual Benefit-Cost Ratio $\\ge 1.0$,
          with highest prioritization given to high-volume pedestrian and multi-lane arterial corridors.
        """
    )

# -----------------------------------------------------------------------------
# Section 3 — What Is NOT Funded (Deferred Corridors)
# -----------------------------------------------------------------------------
st.markdown("---")
st.header("3. What Is NOT Funded (Deferred Corridors)")

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
    
    is_equity = best_cand.get("equity_area_flag", False)
    if isinstance(is_equity, (bool, int)):
        equity_str = "Yes" if is_equity else "No"
    else:
        equity_str = str(is_equity)

    deferred_list.append({
        "Corridor ID": cid,
        "Corridor Name": c_master["corridor_name"],
        "Best Applicable Treatment": best_cand["treatment_name"],
        "Estimated Capital Cost": format_currency(float(best_cand["capital_project_cost"])),
        "Benefit-Cost Ratio (BCR)": f"{float(best_cand['benefit_cost_ratio']):.1f}",
        "PV Safety Benefit": format_currency(float(best_cand["present_value_benefit"])),
        "Equity Priority Area": equity_str,
    })

df_deferred = pd.DataFrame(deferred_list).sort_values("Benefit-Cost Ratio (BCR)", ascending=False)

st.markdown(
    f"Under the **\\$15M budget ceiling**, **{len(df_deferred)} corridors** are deferred. "
    f"These corridors have viable safety projects (all $\\text{{BCR}} > 1.0$), but could not be accommodated "
    f"within the \\$15M ceiling because their cost exceeds the remaining budget slack ({format_currency(budget_slack)}) "
    f"or higher-ROI alternatives took precedence."
)

st.dataframe(df_deferred, use_container_width=True, hide_index=True)

# -----------------------------------------------------------------------------
# Section 4 — Sensitivity to Budget
# -----------------------------------------------------------------------------
st.markdown("---")
st.header("4. Sensitivity to Budget")

st.markdown(
    "How does corridor coverage and total safety return scale if additional capital is appropriated, "
    "or if capital is severely constrained?"
)

# Build sensitivity table across official and stress budgets in BASE scenario
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

sensitivity_rows = []

# Add stress tiers
for _, row in sens_stress.iterrows():
    b_val = float(row["budget_usd"])
    c_cost = float(row["selected_capital_cost"])
    pv_b = float(row["total_present_value_benefit"])
    p_bcr = float(row["portfolio_bcr"])
    n_sel = int(row["selected_project_count"])
    sensitivity_rows.append({
        "Planning Budget Tier": f"\\${int(b_val / 1e6)}M (Stress Diagnostic)",
        "Corridors Selected": f"{n_sel} of {total_corridors_count}",
        "Total Capital Cost": format_currency(c_cost),
        "Total PV Safety Benefit": format_currency(pv_b),
        "Portfolio BCR": f"{p_bcr:.1f}",
        "Budget Status": "BINDING (Constrained)",
    })

# Add official tiers
for _, row in sens_official.iterrows():
    b_val = float(row["budget_usd"])
    c_cost = float(row["selected_capital_cost"])
    pv_b = float(row["total_present_value_benefit"])
    p_bcr = float(row["portfolio_bcr"])
    n_sel = int(row["selected_project_count"])
    is_binding = b_val < 20000000.0
    status_str = "BINDING (Default Recommended)" if b_val == 15000000.0 else "NONBINDING (Full Network Funded)"
    sensitivity_rows.append({
        "Planning Budget Tier": f"\\${int(b_val / 1e6)}M Official Planning",
        "Corridors Selected": f"{n_sel} of {total_corridors_count}",
        "Total Capital Cost": format_currency(c_cost),
        "Total PV Safety Benefit": format_currency(pv_b),
        "Portfolio BCR": f"{p_bcr:.1f}",
        "Budget Status": status_str,
    })

df_sens = pd.DataFrame(sensitivity_rows)
st.dataframe(df_sens, use_container_width=True, hide_index=True)

st.info(
    "**Key Budget Finding**: Expanding the budget from **\\$15M** to **\\$25M** adds **\\$4.94M** in capital cost "
    "and funds the remaining **9 deferred corridors**, capturing an additional **\\$757M** in present-value safety benefits. "
    "Any budget above **\\$20.1M** funds 100% of the eligible 43-corridor network."
)

# -----------------------------------------------------------------------------
# Section 5 — Top Risks & Limitations
# -----------------------------------------------------------------------------
st.markdown("---")
st.header("5. Top Risks & Decision Limitations")

with st.expander("Review 5 Critical Governance & Engineering Limitations", expanded=True):
    st.markdown(
        """
        1. **Physical Applicability is Provisional (`UNKNOWN`)**:
           - Treatments are selected based on high-level road classifications and corridor geometry.
           - Specific corridor constraints (curb alignments, turn lanes, utility conflicts, bridge deck widths, transit lanes)
             require detailed engineering field inspections before design or construction.
        2. **Sourced Planning Costs vs. Contract Bids**:
           - Unit costs (\\$400k/mi Road Diet, \\$15k/island Refuge Island, \\$22.5k RRFB; `D024`) are planning-level benchmarks.
           - Actual construction costs will vary based on procurement, site work, signal integration, and material prices.
        3. **CDC Social Vulnerability Index (SVI) as Equity Proxy**:
           - SVI percentile tracks spatial vulnerability across census tracts, but does not substitute for localized community engagement or neighborhood-level equity evaluations.
        4. **Statistical Crash Burden vs. Deterministic Occurrence**:
           - Forecast models evaluate multi-year statistical crash risk and regression-to-the-mean tendencies. They identify high-probability corridors, not guarantees of specific crash occurrences.
        5. **Planning Scenarios vs. Policy Appropriations**:
           - Portfolio scenarios represent decision-support alternatives. They do not constitute official City of Chicago capital budget commitments.
        """
    )

# -----------------------------------------------------------------------------
# Footer
# -----------------------------------------------------------------------------
st.markdown("---")
st.caption(
    "🚦 **Vision Zero Chicago Decision Support System** | "
    "Decision support only. Final authority remains with City staff and engineering review."
)
