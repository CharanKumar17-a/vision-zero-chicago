"""UI components and sidebar control panel for Vision Zero Chicago Streamlit decision support app.

Contract: docs/data_quality/decision_output_mart_contract.md
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard.streamlit.data_access import DEFAULT_PORTFOLIO_ID


def render_sidebar_controls(df_summary: pd.DataFrame) -> str:
    """Render sidebar scenario controls and return exactly one selected portfolio_id."""
    st.sidebar.markdown("### Vision Zero Chicago")
    st.sidebar.caption("Safety Capital Investment Prioritization")
    st.sidebar.title("Portfolio Scenario Control")
    st.sidebar.markdown("---")

    # 1. Run Group Selector
    run_groups = sorted(df_summary["run_group"].unique().tolist())
    # Default to OFFICIAL
    default_rg_idx = run_groups.index("OFFICIAL") if "OFFICIAL" in run_groups else 0
    selected_rg = st.sidebar.selectbox("Run Group", options=run_groups, index=default_rg_idx)

    df_filtered_rg = df_summary[df_summary["run_group"] == selected_rg]

    # 2. CMF Uncertainty Scenario
    scenarios = sorted(df_filtered_rg["uncertainty_scenario"].unique().tolist())
    default_scen_idx = scenarios.index("BASE") if "BASE" in scenarios else 0
    selected_scen = st.sidebar.radio("CMF Uncertainty Level", options=scenarios, index=default_scen_idx)

    df_filtered_scen = df_filtered_rg[df_filtered_rg["uncertainty_scenario"] == selected_scen]

    # 3. Budget Level
    budgets = sorted(df_filtered_scen["budget_usd"].unique().tolist())
    formatted_budgets = [f"${int(b / 1e6)}M" for b in budgets]
    # Default to $15M if present, else first
    default_b_idx = 0
    for idx, b in enumerate(budgets):
        if b == 15000000.0:
            default_b_idx = idx
            break
    selected_b_str = st.sidebar.select_slider("Planning Budget Ceiling", options=formatted_budgets, value=formatted_budgets[default_b_idx])
    selected_b_val = budgets[formatted_budgets.index(selected_b_str)]

    df_filtered_b = df_filtered_scen[df_filtered_scen["budget_usd"] == selected_b_val]

    # 4. Equity Spending Floor
    equity_floors = sorted(df_filtered_b["equity_floor"].unique().tolist())
    formatted_floors = [f"{int(ef * 100)}%" for ef in equity_floors]
    default_ef_idx = 0
    for idx, ef in enumerate(equity_floors):
        if ef == 0.20:
            default_ef_idx = idx
            break
    selected_ef_str = st.sidebar.selectbox("Minimum Equity Spending Floor", options=formatted_floors, index=default_ef_idx)
    selected_ef_val = equity_floors[formatted_floors.index(selected_ef_str)]

    df_final_match = df_filtered_b[df_filtered_b["equity_floor"] == selected_ef_val]

    if df_final_match.empty:
        st.sidebar.warning("Selected combination unavailable. Reverting to default canonical portfolio.")
        selected_pid = DEFAULT_PORTFOLIO_ID
    else:
        selected_pid = df_final_match.iloc[0]["portfolio_id"]

    st.sidebar.markdown("---")
    st.sidebar.caption(f"Active Portfolio ID: **{selected_pid}**")

    from dashboard.streamlit.data_access import is_cloud_deployment_mode, load_validation_evidence

    if is_cloud_deployment_mode():
        evidence = load_validation_evidence()
        manifest_meta = evidence.get("deployment_manifest", {})
        gen_time = manifest_meta.get("generated_at_utc", "N/A")
        st.sidebar.info(f"🌐 **Published Analytical Snapshot**\nGenerated: `{gen_time}`")

    return selected_pid


def render_page_header(page_title: str, subtitle: str | None = None) -> None:
    """Render unified two-level header across all application pages."""
    st.caption("Vision Zero Chicago — Safety Capital Investment Prioritization")
    st.title(page_title)
    if subtitle:
        st.markdown(subtitle)


def render_governance_header_banner(run_group: str, is_official: bool) -> None:
    """Render mandatory governance banner based on run group."""
    if is_official:
        st.info(
            "**OFFICIAL CITY PLANNING SCENARIO**: Under sourced planning-level treatment costs (D024), "
            "the full 43-corridor network costs approx. \\$20.1M (BASE). The \\$15M planning budget is BINDING "
            "(selects ~34 of 43 corridors); \\$25M and \\$40M remain nonbinding (all eligible corridors fit). "
            "Budget and equity scenarios are planning-level, not official City appropriations. "
            "Physical applicability remains UNKNOWN pending engineering field review."
        )
    else:
        st.warning(
            "**ANALYST-DEFINED BINDING-BUDGET DIAGNOSTICS**: This stress scenario represents an analyst-defined "
            "diagnostic scenario under constrained budgets (\\$2M, \\$4M, \\$6M) to evaluate binding constraint mechanics. "
            "Does not constitute official City policy."
        )


def render_engineering_review_banner() -> None:
    """Render mandatory engineering field review warning banner."""
    st.warning(
        "**Engineering review required. Lane counts, median widths and crossing inventories are not yet available.** "
        "Physical applicability status is UNKNOWN across all candidate corridors. Field survey required prior to project programming."
    )


def render_economic_caveat_banner() -> None:
    """Render mandatory economic cost-benefit disclaimer banner."""
    st.warning(
        "**Analyst-defined planning costs and crash-cost assumptions — not an approved City benefit-cost estimate.** "
        "Planning-level estimates from provisional costs and comprehensive crash costs — not expected City project returns."
    )


def format_currency(val: float) -> str:
    """Format float as USD currency string."""
    return f"${val:,.0f}"


def format_percent(val: float) -> str:
    """Format decimal float as percentage string."""
    return f"{val * 100:.2f}%"
