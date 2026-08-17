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
    st.sidebar.caption("Safety capital investment prioritization")
    st.sidebar.title("Portfolio scenario control")
    st.sidebar.markdown("---")

    # 1. Run Group Selector
    run_groups = sorted(df_summary["run_group"].unique().tolist())
    default_rg_idx = run_groups.index("OFFICIAL") if "OFFICIAL" in run_groups else 0
    selected_rg = st.sidebar.selectbox("Run group", options=run_groups, index=default_rg_idx)

    df_filtered_rg = df_summary[df_summary["run_group"] == selected_rg]

    # 2. CMF Uncertainty Scenario
    scenarios = sorted(df_filtered_rg["uncertainty_scenario"].unique().tolist())
    default_scen_idx = scenarios.index("BASE") if "BASE" in scenarios else 0
    selected_scen = st.sidebar.radio("CMF uncertainty level", options=scenarios, index=default_scen_idx)

    df_filtered_scen = df_filtered_rg[df_filtered_rg["uncertainty_scenario"] == selected_scen]

    # 3. Budget Level
    budgets = sorted(df_filtered_scen["budget_usd"].unique().tolist())
    formatted_budgets = [f"${int(b / 1e6)}M" for b in budgets]
    default_b_idx = 0
    for idx, b in enumerate(budgets):
        if b == 15000000.0:
            default_b_idx = idx
            break
    selected_b_str = st.sidebar.select_slider("Planning budget ceiling", options=formatted_budgets, value=formatted_budgets[default_b_idx])
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
    selected_ef_str = st.sidebar.selectbox("Minimum equity spending floor", options=formatted_floors, index=default_ef_idx)
    selected_ef_val = equity_floors[formatted_floors.index(selected_ef_str)]

    df_final_match = df_filtered_b[df_filtered_b["equity_floor"] == selected_ef_val]

    if df_final_match.empty:
        st.sidebar.warning("Selected combination unavailable. Reverting to default canonical portfolio.")
        selected_pid = DEFAULT_PORTFOLIO_ID
    else:
        selected_pid = df_final_match.iloc[0]["portfolio_id"]

    st.sidebar.markdown("---")
    st.sidebar.caption(f"Active scenario: **{selected_pid}**")

    from dashboard.streamlit.data_access import is_cloud_deployment_mode, load_validation_evidence

    if is_cloud_deployment_mode():
        evidence = load_validation_evidence()
        manifest_meta = evidence.get("deployment_manifest", {})
        gen_time = manifest_meta.get("generated_at_utc", "N/A")
        st.sidebar.info(f"**Published Analytical Snapshot**\nGenerated: `{gen_time}`")

    return selected_pid


def render_page_header(page_title: str, subtitle: str | None = None) -> None:
    """Render unified professional header across all application pages."""
    st.title("Vision Zero Chicago — Safety Capital Investment Prioritization")
    st.subheader(page_title)
    if subtitle:
        st.caption(subtitle)


def render_governance_header_banner(run_group: str, is_official: bool) -> None:
    """Render mandatory governance banner based on run group."""
    if is_official:
        st.info(
            "**Official planning scenario**: Under sourced planning-level treatment costs (D024), "
            "the full 43-corridor network costs approx. \\$20–27M depending on scenario. The \\$15M planning budget is binding "
            "(selects 42 of 43 corridors in BASE); \\$25M and \\$40M remain nonbinding (all eligible corridors fit). "
            "Budget and equity scenarios are planning-level, not official City appropriations. "
            "Physical applicability remains UNKNOWN pending engineering field review."
        )
    else:
        st.warning(
            "**Analyst-defined binding-budget diagnostics**: This stress scenario represents an analyst-defined "
            "diagnostic scenario under constrained budgets (\\$2M, \\$4M, \\$6M) to evaluate binding constraint mechanics. "
            "Does not constitute official City policy."
        )


def render_engineering_review_banner() -> None:
    """Render mandatory engineering field review warning banner."""
    st.warning(
        "**Engineering review required**: Lane counts, median widths, and crossing inventories are not yet available in the analytical dataset. "
        "Physical applicability status is UNKNOWN across candidate corridors. Field survey is required prior to project programming."
    )


def render_economic_caveat_banner() -> None:
    """Render mandatory economic cost-benefit disclaimer banner."""
    st.warning(
        "**Planning-level economic assumptions**: Benefits reflect comprehensive crash costs from federal guidance — not expected City financial returns."
    )


def format_currency(val: float) -> str:
    """Format float as USD currency string."""
    return f"${val:,.0f}"


def format_percent(val: float) -> str:
    """Format decimal float as percentage string."""
    return f"{val * 100:.1f}%"
