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
> **City staff and engineering reviewers preserve final authority.**
> The Vision Zero Chicago decision-support system provides transparent, reproducible analytical findings to inform planning. It does not automatically approve or program projects.

#### Analytical grains and lineage
- **Portfolio Summary Grain**: `portfolio_id` × 1 row (36 runs total: 27 Official, 9 Stress).
- **Portfolio Project Selection Grain**: `portfolio_id` × `corridor_id` (1,362 detail rows across 36 runs).
- **Master Corridor Grain**: `corridor_id` × 1 row (43 high-crash corridors).
- **Treatment Benefits Candidate Panel Grain**: `corridor_id` × `treatment_id` × `scenario_level` (387 candidate rows).

#### Equity definition disclaimer
- **Equity Classification**: Uses CDC/ATSDR Social Vulnerability Index (SVI) 2022 census-tract data as a project-defined planning proxy. This is an analyst-defined planning proxy and does not constitute the City of Chicago's official equity definition.

#### Scenario definitions
- **OFFICIAL (27 runs)**: Scenarios evaluating \\$15M, \\$25M, and \\$40M planning budgets and 20%, 30%, 40% equity floors across CONSERVATIVE, BASE, and OPTIMISTIC uncertainty. Official \\$15M planning budgets bind strictly under realistic unit costs (\\$14.99M cost, selecting 42 corridors in BASE scenario), while \\$25M and \\$40M budget ceilings allow network-wide coverage.
- **BINDING-BUDGET STRESS TEST (9 runs)**: Analyst-defined diagnostic scenarios evaluating \\$2M, \\$4M, and \\$6M budgets under BASE uncertainty. Stress budgets bind effectively (`EFFECTIVELY_BINDING_NO_ADDITIONAL_CORRIDOR`).

#### Model horizon and threshold policy
- **Risk Horizon**: 2026 Annual Crash Forecast (Beta-Binomial conjugate shrinkage, Empirical Bayes KSI calibration).
- **Corridor Inclusion**: Top 43 High-Crash Corridors (Tier 1 & Tier 2).
- **Capital Discounting**: Real discount rate 3.0%, 20-year useful life for Road Diet (`TRT_002`) and Location Treatments (`TRT_001`, `TRT_004`).
""")

render_engineering_review_banner()

