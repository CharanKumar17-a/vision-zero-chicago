"""UI components and sidebar control panel for Vision Zero Chicago Streamlit decision support app.

Contract: docs/data_quality/decision_output_mart_contract.md
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from dashboard.streamlit.data_access import DEFAULT_PORTFOLIO_ID


def render_sidebar_controls(df_summary: pd.DataFrame) -> str:
    """Render sidebar scenario controls and return exactly one selected portfolio_id."""
    st.sidebar.markdown("### Vision Zero Chicago")
    st.sidebar.caption("Safety capital investment prioritization")
    st.sidebar.title("Planning scenario controls")
    st.sidebar.markdown("---")

    # 1. Run Group Selector
    run_groups = sorted(df_summary["run_group"].unique().tolist())
    default_rg_idx = run_groups.index("OFFICIAL") if "OFFICIAL" in run_groups else 0
    selected_rg = st.sidebar.selectbox("Scenario run group", options=run_groups, index=default_rg_idx)

    df_filtered_rg = df_summary[df_summary["run_group"] == selected_rg]

    # 2. CMF Uncertainty Scenario
    scenarios = sorted(df_filtered_rg["uncertainty_scenario"].unique().tolist())
    default_scen_idx = scenarios.index("BASE") if "BASE" in scenarios else 0
    selected_scen = st.sidebar.radio("CMF uncertainty level", options=scenarios, index=default_scen_idx)

    df_filtered_scen = df_filtered_rg[df_filtered_rg["uncertainty_scenario"] == selected_scen]

    # 3. Budget Level
    budgets = sorted(df_filtered_scen["budget_usd"].unique().tolist())
    default_b_val = 15000000.0 if 15000000.0 in budgets else budgets[0]
    selected_b_val = st.sidebar.select_slider(
        "Planning budget ceiling",
        options=budgets,
        value=default_b_val,
        format_func=lambda b: f"${int(b / 1e6)}M" if b >= 1e6 else f"${int(b / 1e3)}k",
    )

    df_filtered_b = df_filtered_scen[df_filtered_scen["budget_usd"] == selected_b_val]

    # 4. Equity Spending Floor
    equity_floors = sorted(df_filtered_b["equity_floor"].unique().tolist())
    default_ef_val = 0.20 if 0.20 in equity_floors else equity_floors[0]
    default_ef_idx = equity_floors.index(default_ef_val)
    selected_ef_val = st.sidebar.selectbox(
        "Minimum equity spending floor",
        options=equity_floors,
        index=default_ef_idx,
        format_func=lambda ef: f"{int(round(ef * 100))}%",
    )

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
            "**Official planning scenario (Subject to engineering review and implementation approval)**: "
            "Under sourced planning-level treatment costs (D024), the full 43-corridor network costs approx. "
            "\\$17.5M–\\$18.8M under Road Diet caps (D026/D027). The \\$15M planning budget ceiling is binding "
            "(allocating \\$14.99M of \\$15M in the Baseline Scenario); \\$25M and \\$40M remain nonbinding "
            "(all eligible corridors fit). Budget and equity scenarios provide planning-level decision support "
            "and do not constitute official City appropriations or construction authorizations. "
            "Physical applicability remains UNKNOWN pending engineering field review."
        )
    else:
        st.warning(
            "**Analyst-defined binding-budget diagnostics**: This stress scenario represents an analyst-defined "
            "diagnostic scenario under constrained budgets (\\$2M, \\$4M, \\$6M) to evaluate binding constraint mechanics. "
            "This provides planning-level decision support and does not constitute official City policy or project authorization."
        )


def render_engineering_review_banner() -> None:
    """Render mandatory engineering field review warning banner."""
    st.warning(
        "**Subject to engineering review and implementation approval**: "
        "Lane counts, median widths, and crossing inventories are not yet available in the analytical dataset. "
        "Physical applicability status is UNKNOWN across candidate corridors. "
        "Detailed engineering field review and survey are required prior to project programming or construction scoping."
    )


def render_economic_caveat_banner() -> None:
    """Render mandatory economic cost-benefit disclaimer banner."""
    st.warning(
        "**Planning-level estimate**: Benefits reflect comprehensive crash costs from federal guidance — not expected City financial returns. "
        "All figures provide planning-level decision support and are subject to engineering review and implementation approval."
    )


def format_currency(val: float) -> str:
    """Format float as USD currency string."""
    return f"${val:,.0f}"


def format_percent(val: float) -> str:
    """Format decimal float as percentage string."""
    return f"{val * 100:.1f}%"


def format_equity_flag(val: Any) -> str:
    """Format boolean or numeric equity indicator as 'Yes' or 'No'."""
    if isinstance(val, bool):
        return "Yes" if val else "No"
    if isinstance(val, (int, float)):
        return "Yes" if val > 0 else "No"
    if isinstance(val, str):
        return "Yes" if val.strip().lower() in ("true", "1", "yes", "y") else "No"
    return "No"


def format_cost_per_unit(cost: float, units: float, unit_label: str = "KSI") -> str:
    """Format cost per averted unit with safe zero-division handling."""
    if units is not None and units > 0 and pd.notnull(units) and cost is not None and pd.notnull(cost):
        return f"${cost / units:,.0f} / {unit_label}"
    return "N/A"


def format_plural(count: int, singular: str, plural: str | None = None) -> str:
    """Format count with correct singular or plural noun."""
    noun = singular if count == 1 else (plural or f"{singular}s")
    return f"{count} {noun}"
