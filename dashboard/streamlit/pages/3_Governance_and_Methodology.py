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
    render_economic_caveat_banner,
    render_engineering_review_banner,
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

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric("Geometry validation run ID", geom_ev.get("run_id", "N/A"))

with col2:
    st.metric("Optimization run ID", opt_ev.get("run_id", "N/A"))

with col3:
    st.metric("Decision mart run ID", mart_ev.get("run_id", "N/A"))

with col4:
    st.metric("Decision mart status", mart_ev.get("status", "N/A"))

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

st.markdown("""
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

#### Equity definition disclaimer
- **Equity Classification**: Uses CDC/ATSDR Social Vulnerability Index (SVI) 2022 census-tract data as a project-defined planning proxy. This is an analyst-defined planning proxy and does not constitute the City of Chicago's official equity definition.

#### Scenario definitions
- **OFFICIAL (27 runs)**: Approved planning scenario group evaluating \\$15M, \\$25M, and \\$40M planning budgets and 20%, 30%, 40% equity floors across CONSERVATIVE, BASE (Baseline Scenario), and OPTIMISTIC uncertainty. Official \\$15M planning budgets bind strictly under realistic unit costs (\\$14.99M cost, selecting 39 corridors in the Baseline Scenario under D026/D027 Road Diet diversification and screening), while \\$25M and \\$40M budget ceilings allow network-wide coverage.
- **BINDING-BUDGET STRESS TEST (9 runs)**: Analyst-defined diagnostic scenarios evaluating \\$2M, \\$4M, and \\$6M budgets under BASE uncertainty. Stress budgets bind effectively (`EFFECTIVELY_BINDING_NO_ADDITIONAL_CORRIDOR`).

#### Crash severity definitions and analytical denominators
- **All-Severity Crashes**: Comprehensive sum of all police-reported crash severities under the KABCO scale (`K` + `A` + `B` + `C` + `O`).
- **KSI Crashes (Life-Safety Metric)**: Fatal crashes (`K`) plus Serious / Incapacitating injury crashes (`A`). Evaluated as the primary life-safety objective.
- **Minor & Possible Injury Crashes**: Non-incapacitating injury crashes (`B`) and Possible / complaint-of-injury crashes (`C`).
- **Property Damage Only (PDO / O)**: Non-injury property damage crashes.
- **Analytical Denominators**:
  - *Network Baseline*: Evaluated across all 43 candidate high-crash corridors (~78.8 Baseline KSI / yr).
  - *Portfolio Averted Metrics*: Aggregated strictly over the subset of shortlisted corridors funded within each active scenario (e.g., 39 funded corridors in the $15M Baseline Scenario).
""")

render_engineering_review_banner()
render_economic_caveat_banner()
