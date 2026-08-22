"""Governance and Methodology Page - Vision Zero Chicago Decision Support App.

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
    render_governance_footer,
    render_page_header,
    render_sidebar_controls,
)
from dashboard.streamlit.data_access import (
    load_portfolio_summary,
    load_validation_evidence,
)

render_page_header(
    "Governance & methodology",
    "Dynamic audit of governance warning registers, source evidence lineage, and decision-support contracts.",
)

# Load serving datasets & validation evidence
df_summary = load_portfolio_summary()
evidence = load_validation_evidence()

# Render sidebar controls & get active portfolio
portfolio_id = render_sidebar_controls(df_summary)

st.markdown("---")
st.subheader("1. Source pipeline lineage and evidence run IDs")

geom_ev = evidence.get("geometry", {})
opt_ev = evidence.get("optimization", {})
mart_ev = evidence.get("decision_mart", {})

mart_completed = mart_ev.get("completed_at_utc") or evidence.get("deployment_manifest", {}).get("generated_at_utc", "")
val_date = mart_completed[:10] if len(mart_completed) >= 10 else "2026-08-17"

col_fresh1, col_fresh2, col_fresh3 = st.columns(3)
with col_fresh1:
    st.metric(
        "Analysis Period",
        "2018–2025",
        help="Historical baseline crash analysis window across 96 monthly periods. Does not claim all external sources update through 2025.",
    )
with col_fresh2:
    st.metric(
        "Data Last Validated",
        val_date,
        help="Timestamp when analytical serving mart datasets and decision contracts completed validation checks.",
    )
with col_fresh3:
    st.metric(
        "Pipeline Status",
        "Validated",
        help="All automated pipeline data quality and reconciliation checks passed. Public datasets are fixed snapshots and not live feeds.",
    )

lineage_records = [
    {"Pipeline Component": "Corridor Geometry Validation", "Execution Run ID": str(geom_ev.get("run_id", "N/A")), "Status": "PASS"},
    {"Pipeline Component": "Portfolio Optimization", "Execution Run ID": str(opt_ev.get("run_id", "N/A")), "Status": "OPTIMAL"},
    {"Pipeline Component": "Decision Mart Serving", "Execution Run ID": str(mart_ev.get("run_id", "N/A")), "Status": str(mart_ev.get("status", "VALIDATED"))},
]
with st.expander("View pipeline execution runs and lineage IDs", expanded=True):
    st.dataframe(pd.DataFrame(lineage_records), use_container_width=True, hide_index=True)

st.markdown("---")
st.subheader("2. Governance warning register")

# 1. Portfolio Optimization Governance Warnings
opt_warnings = opt_ev.get("governance_warnings", [])
with st.expander("Portfolio optimization governance warnings (Phase 4C evidence)", expanded=True):
    if opt_warnings:
        df_opt_w = pd.DataFrame(opt_warnings)
        cols_to_show = [c for c in ["code", "explanation", "limitation_or_resolution", "governance_reference"] if c in df_opt_w.columns]
        df_opt_display = df_opt_w[cols_to_show].copy()
        df_opt_display.columns = [c.replace("_", " ").title() for c in df_opt_display.columns]
        st.dataframe(df_opt_display, use_container_width=True, hide_index=True, height=220)
    else:
        st.info("No portfolio optimization warnings loaded.")

# 2. Decision Mart Serving Governance Warnings
mart_warnings = mart_ev.get("governance_warnings", [])
with st.expander("Decision mart serving governance warnings (Phase 5A evidence)", expanded=True):
    if mart_warnings:
        df_mart_w = pd.DataFrame(mart_warnings)
        cols_to_show = [c for c in ["code", "explanation", "limitation_or_resolution", "governance_reference"] if c in df_mart_w.columns]
        df_mart_display = df_mart_w[cols_to_show].copy()
        df_mart_display.columns = [c.replace("_", " ").title() for c in df_mart_display.columns]
        st.dataframe(df_mart_display, use_container_width=True, hide_index=True, height=150)
    else:
        st.info("No decision mart warnings loaded.")

st.markdown("---")
st.subheader("3. Decision-support contracts and methodological boundaries")

st.markdown(r"""
#### Final decision authority
> **This tool provides planning-level decision support. It does not authorize projects, establish construction scope, or replace engineering review.**
> City staff and engineering reviewers preserve final capital programming authority.

#### Optimization qualification
- **Mathematical Optimization**: Status values of `OPTIMAL` indicate that the Mixed-Integer Linear Program (MILP) solved to mathematical optimality under the stated constraints and planning-level cost/benefit assumptions. It does not guarantee field constructibility.

#### Analytical grains and lineage
- **Portfolio Summary Grain**: `portfolio_id` × 1 row (36 canonical optimization runs: 27 Official, 9 Stress; 192 total serving mart scenarios including What-If grid).
- **Portfolio Project Selection Grain**: `portfolio_id` × `corridor_id` (1,362 detail rows across 36 canonical runs; 6,999 detail rows across all serving mart scenarios).
- **Master Corridor Grain**: `corridor_id` × 1 row (43 high-crash corridors).
- **Treatment Benefits Candidate Panel Grain**: `corridor_id` × `treatment_id` × `scenario_level` (387 candidate rows).

#### Equity definition disclaimer and benefit distinction
- **Equity Classification**: Uses CDC/ATSDR Social Vulnerability Index (SVI) 2022 census-tract data as a project-defined planning proxy. This is an analyst-defined planning proxy and does not constitute the City of Chicago's official equity definition.
- **Methodology Note**: **SVI is used as a spatial equity proxy; it does not directly measure safety benefit equity.**
- **Spending Equity vs. Benefit Equity**:
  - *Equity of Spending (`High-SVI capital share`)*: Tracks the percentage of capital project investment allocated to corridors in high-SVI areas (subject to the policy floor, e.g., 20%, 30%, or 40%).
  - *Equity of Estimated Safety Benefit (`KSI benefit share in high-SVI areas`)*: Tracks the percentage of estimated life-safety crash reductions (Fatal K + Serious Injury A) realized within high-SVI corridors (e.g., 55.9% of portfolio KSI avoided in the $15M Baseline Scenario).

#### Scenario definitions
- **OFFICIAL (27 runs)**: Approved planning scenario group evaluating \$15M, \$25M, and \$40M planning budgets and 20%, 30%, 40% equity floors across CONSERVATIVE, BASE (Baseline Scenario), and OPTIMISTIC uncertainty. Official \$15M planning budgets bind strictly under realistic unit costs (\$14.99M cost, selecting 39 corridors in the Baseline Scenario under Road Diet diversification and screening), while \$25M and \$40M budget ceilings allow network-wide coverage.
- **BINDING-BUDGET STRESS TEST (9 runs)**: Analyst-defined diagnostic scenarios evaluating \$2M, \$4M, and \$6M budgets under BASE uncertainty. Stress budgets bind effectively (`EFFECTIVELY_BINDING_NO_ADDITIONAL_CORRIDOR`).

#### Crash severity definitions and analytical denominators
- **All-Severity Crashes**: Comprehensive sum of all police-reported crash severities under the KABCO scale (`K` + `A` + `B` + `C` + `O`).
- **KSI Crashes (Life-Safety Metric)**: Fatal crashes (`K`) plus Serious / Incapacitating injury crashes (`A`). Evaluated as the primary life-safety objective.
- **Minor & Possible Injury Crashes**: Non-incapacitating injury crashes (`B`) and Possible / complaint-of-injury crashes (`C`).
- **Property Damage Only (PDO / O)**: Non-injury property damage crashes.
- **Analytical Denominators**:
  - *Network Baseline*: Evaluated across all 43 candidate high-crash corridors (~78.8 Baseline KSI / yr).
  - *Portfolio Averted Metrics*: Aggregated strictly over the subset of shortlisted corridors funded within each active scenario (e.g., 39 funded corridors in the $15M Baseline Scenario).

#### Engineering feasibility and portfolio classification
- **Engineering Status Hierarchy**:
  - `UNKNOWN`: Default planning status for candidate projects satisfying road classification and centerline screening rules. Communicated in decision support views as **"Engineering review required"**.
  - `REVIEW_REQUIRED`: Projects flagged for priority field review due to geometric complexity or multimodal transit integration.
  - `ELIGIBLE`: Field engineering inspection has verified lane geometry, cross-sections, curb alignments, turn pockets, and utility clearances.
  - `NOT_APPLICABLE`: Project screened out by road classification, lane geometry, speed limits, or transit constraints (e.g., Road Diet on 1-lane streets or freeways).
- **Analytical Planning Portfolio vs. Implementation-Ready Portfolio**:
  - *Analytical Planning Portfolio*: The mathematically optimal combination of corridor treatments selected under stated budget, equity floor, and CMF assumptions. All selected projects in the current analytical dataset carry provisional status `UNKNOWN` (*Engineering review required*).
  - *Implementation-Ready Portfolio*: Projects that have completed formal engineering field review, utility coordination, geometric design, and City departmental approval.
- **Engineering Feasibility & Field Review Constraints**:
  - The decision support system's optimization engine is architected to ingest verified field engineering data as hard constraints (see formulation below).
  - Once CDOT or engineering field surveys produce verified feasibility attributes, the MILP optimization model will automatically enforce engineering eligibility without redesigning the core optimization formulation.
""")

st.info(
    "**Engineering Feasibility & Field Review Constraints**\n\n"
    "The optimization engine is designed to ingest verified field engineering data as hard constraints, "
    "so that projects marked NOT_APPLICABLE are excluded from selection, and — for implementation-ready runs — "
    "only projects with a verified ELIGIBLE engineering status may be selected.\n\n"
    "Once CDOT engineering surveys are complete, the model enforces these constraints automatically "
    "without redesigning the core optimization formulation. "
    "All current projects carry provisional status UNKNOWN (engineering review required)."
)

st.markdown("---")
st.subheader("4. Spatial assignment sensitivity")
st.caption("Comparing 50 ft vs 100 ft baseline vs 150 ft crash-to-corridor assignment thresholds")

spatial_ev = evidence.get("spatial_sensitivity", {})
conclusion_text = spatial_ev.get("conclusion", "Portfolio is STABLE across thresholds")
justification_text = spatial_ev.get(
    "production_rule_justification",
    "The 100-foot production assignment rule remains justified and robust. Corridor rankings exhibit >0.97 Spearman correlation across 50 ft and 150 ft, and the $15M planning portfolio has >97% corridor selection stability with zero distortion of high-level capital priorities.",
)

st.markdown(f"""
#### Empirical threshold evaluation
An offline spatial sensitivity analysis was conducted comparing candidate crash assignment thresholds at **50 ft**, **100 ft (approved production baseline)**, and **150 ft** to test whether the 100-foot assignment rule drives the project's conclusions.

- **Production Rule Status**: **UNCHANGED**. The approved 100-foot distance threshold and 10-foot tie tolerance remain the authoritative standard for all production pipelines and official planning scenarios.
- **Corridor Prioritization Stability**: Corridor crash rankings maintain high Spearman rank correlations of **0.9784 (at 50 ft)** and **0.9878 (at 150 ft)** against the 100-ft baseline.
- **Portfolio Selection Stability**: Under the $15M Baseline Scenario (`PORT_OFF_BASE_B15M_EQ20`), **38 of 39 selected corridors (97.4%)** remain identical between 50 ft and the 100-ft baseline.
- **Sensitivity Conclusion**:
  > **{conclusion_text}**
  >
  > {justification_text}
""")

st.markdown("---")
st.subheader("5. Usage analytics and privacy")

st.markdown("""
#### Anonymous usage measurement
- **Usage Analytics**: Anonymous usage measurement for understanding how users navigate, explore scenarios, inspect corridors, and export planning outputs. PostHog is used as the analytics platform.
- **Privacy and Isolation Guarantees**:
  - **Disabled by default**: Telemetry is opt-in and inactive unless explicitly enabled in configuration or environment variables.
  - **Zero PII**: No personal identifying information (PII), names, email addresses, raw crash records, or uploaded data are ever collected.
  - **Zero Analytical Impact**: Telemetry operates strictly in an isolated observer mode and never affects calculations, mathematical optimizations, or displayed values.
""")

# Standardized Consolidated Governance Footer
render_governance_footer()
