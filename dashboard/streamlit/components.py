"""UI components and sidebar control panel for Vision Zero Chicago Streamlit decision support app.

Contract: docs/data_quality/decision_output_mart_contract.md
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from dashboard.streamlit.data_access import DEFAULT_PORTFOLIO_ID


def inject_global_css() -> None:
    """Inject global typography and visual consistency CSS.

    Called once from app.py after st.set_page_config(). Establishes a
    consistent typography hierarchy across all four application pages.
    No user-supplied content is embedded — only static CSS rules.
    """
    st.markdown(
        """
        <style>
        /* ── App & page titles ──────────────────────────────────────────── */
        h1 { font-size: 28px !important; font-weight: 700 !important;
             letter-spacing: -0.3px !important; margin-bottom: 0.25rem !important; }
        h2 { font-size: 22px !important; font-weight: 600 !important;
             margin-top: 0.25rem !important; margin-bottom: 0.15rem !important; }

        /* ── Section headings (#### in st.markdown) ─────────────────────── */
        h4 { font-size: 16px !important; font-weight: 600 !important;
             margin-top: 0.75rem !important; margin-bottom: 0.25rem !important; }

        /* ── Body text ──────────────────────────────────────────────────── */
        p, li { font-size: 14px !important; line-height: 1.65 !important; }
        .stMarkdown p { margin-bottom: 0.3rem !important; }

        /* ── Caption / secondary text ───────────────────────────────────── */
        .stCaption, small { font-size: 13px !important; color: #666 !important; }

        /* ── Alert / info / success / warning boxes ─────────────────────── */
        [data-testid="stAlert"] p,
        [data-testid="stAlert"] li { font-size: 14px !important; line-height: 1.65 !important; }

        /* ── KPI metrics ────────────────────────────────────────────────── */
        [data-testid="stMetricValue"] {
            font-size: 26px !important; font-weight: 700 !important; }
        [data-testid="stMetricLabel"] {
            font-size: 13px !important; font-weight: 500 !important;
            text-transform: none !important; }
        [data-testid="stMetricDelta"] { font-size: 12px !important; }

        /* ── Sidebar ────────────────────────────────────────────────────── */
        [data-testid="stSidebar"] label { font-size: 13px !important; }
        [data-testid="stSidebar"] p    { font-size: 13px !important; }
        [data-testid="stSidebarNavLink"] { font-size: 14px !important; }

        /* ── Inline code / badges ───────────────────────────────────────── */
        code { font-size: 12px !important; padding: 1px 4px !important;
               border-radius: 3px !important; }

        /* ── Dataframe headers ──────────────────────────────────────────── */
        .dvn-scroller thead th { font-size: 13px !important; font-weight: 600 !important; }
        .dvn-scroller tbody td { font-size: 13px !important; }

        /* ── Expander labels ────────────────────────────────────────────── */
        [data-testid="stExpander"] summary p { font-size: 14px !important; font-weight: 600 !important; }

        /* ── Divider spacing ────────────────────────────────────────────── */
        hr { margin: 0.75rem 0 !important; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_sidebar_controls(df_summary: pd.DataFrame) -> str:
    """Render decision-first sidebar scenario controls and return exactly one selected portfolio_id."""
    st.sidebar.markdown("### Vision Zero Chicago")
    st.sidebar.caption("Safety capital investment prioritization")
    st.sidebar.title("Scenario Controls")
    st.sidebar.markdown("---")

    # Read diagnostic stress setting from session state
    include_stress = st.session_state.get("sidebar_stress_toggle", False)

    # 1. Planning Budget Ceiling (Policy Constraint #1)
    if include_stress:
        budgets = [2000000.0, 4000000.0, 6000000.0, 15000000.0, 25000000.0, 40000000.0]
    else:
        budgets = [15000000.0, 25000000.0, 40000000.0]

    default_b_val = 15000000.0 if 15000000.0 in budgets else budgets[0]
    selected_b_val = st.sidebar.select_slider(
        "Planning budget ceiling",
        options=budgets,
        value=default_b_val,
        format_func=lambda b: f"${int(b / 1e6)}M" if b >= 1e6 else f"${int(b / 1e3)}k",
    )

    # 2. Equity Spending Floor (Policy Constraint #2)
    equity_floors = [0.20, 0.30, 0.40]
    selected_ef_val = st.sidebar.selectbox(
        "Minimum equity spending floor",
        options=equity_floors,
        index=0,
        format_func=lambda ef: f"{int(round(ef * 100))}%",
    )

    # 3. CMF Uncertainty Scenario (Sensitivity Parameter)
    scenarios = ["BASE", "CONSERVATIVE", "OPTIMISTIC"]
    selected_scen = st.sidebar.radio(
        "CMF uncertainty level",
        options=scenarios,
        index=0,
    )

    # Collapsible Advanced / Diagnostic Section (Issue B)
    with st.sidebar.expander("Diagnostic & Stress Scenarios", expanded=include_stress):
        st.checkbox(
            "Include diagnostic stress budgets ($2M–$6M)",
            value=include_stress,
            key="sidebar_stress_toggle",
            help="Enable analyst diagnostic scenarios with severely constrained budgets ($2M, $4M, $6M) under BASE CMF uncertainty.",
        )

    # Determine run group from budget
    if selected_b_val in [2000000.0, 4000000.0, 6000000.0]:
        target_rg = "BINDING-BUDGET STRESS TEST"
    else:
        target_rg = "OFFICIAL"

    # Match exact portfolio row
    df_match = df_summary[
        (df_summary["run_group"] == target_rg)
        & (df_summary["budget_usd"] == selected_b_val)
        & (df_summary["equity_floor"] == selected_ef_val)
        & (df_summary["uncertainty_scenario"] == selected_scen)
    ]

    if df_match.empty:
        # Fallback to nearest official match if stress combination is unavailable
        df_match = df_summary[
            (df_summary["budget_usd"] == selected_b_val)
            & (df_summary["uncertainty_scenario"] == selected_scen)
        ]

    if df_match.empty:
        selected_pid = DEFAULT_PORTFOLIO_ID
    else:
        selected_pid = df_match.iloc[0]["portfolio_id"]

    # Human-readable scenario descriptor badge
    b_label = f"${int(selected_b_val/1e6)}M" if selected_b_val >= 1e6 else f"${int(selected_b_val/1e3)}k"
    eq_label = f"{int(round(selected_ef_val*100))}%"
    st.sidebar.markdown("---")
    st.sidebar.info(
        f"**Active Scenario**\n\n"
        f"• **Budget:** {b_label}\n"
        f"• **Equity Floor:** {eq_label}\n"
        f"• **CMF Tier:** {selected_scen.title()}"
    )
    st.sidebar.caption(f"Scenario ID: `{selected_pid}`")

    from dashboard.streamlit.data_access import is_cloud_deployment_mode, load_validation_evidence

    if is_cloud_deployment_mode():
        evidence = load_validation_evidence()
        manifest_meta = evidence.get("deployment_manifest", {})
        gen_time = manifest_meta.get("generated_at_utc", "N/A")
        st.sidebar.caption(f"Snapshot: `{gen_time}`")

    try:
        from dashboard.streamlit.analytics import track_scenario_selected
        track_scenario_selected(
            scenario_id=selected_pid,
            budget=float(selected_b_val) if selected_b_val is not None else None,
            equity_floor=float(selected_ef_val) if selected_ef_val is not None else None,
            cmf_scenario=str(selected_scen) if selected_scen is not None else None,
        )
    except Exception:
        pass

    return selected_pid


def render_page_header(page_title: str, subtitle: str | None = None) -> None:
    """Render unified professional header across all application pages."""
    try:
        from dashboard.streamlit.analytics import track_page_view
        track_page_view(page_title)
    except Exception:
        pass

    st.title("Vision Zero Chicago — Safety Capital Investment Prioritization")
    st.subheader(page_title)
    if subtitle:
        st.caption(subtitle)


def render_governance_header_banner(run_group: str, is_official: bool) -> None:
    """Render user-facing scenario note based on run group."""
    if is_official:
        st.info(
            "$15M budget is binding ($14.99M across 39 corridors); $25M/$40M allow full 43-corridor coverage. "
            "All selections require engineering field review."
        )
    else:
        st.warning(
            "Diagnostic stress scenario ($2M–$6M budget constraints). "
            "Planning-level decision support only; does not constitute City policy or project authorization."
        )


def render_engineering_review_banner() -> None:
    """Render engineering field review warning banner."""
    st.warning(
        "Subject to engineering field review and implementation approval before construction scoping."
    )


def render_economic_caveat_banner() -> None:
    """Render economic cost-benefit disclaimer banner."""
    st.warning(
        "Planning-level estimate: Benefits reflect societal crash cost savings from federal guidance, not City financial returns."
    )


def render_governance_footer() -> None:
    """Render standardized concise governance and economic footer across all pages."""
    st.markdown("---")
    st.caption(
        "Planning-level decision support. Requires engineering field review before programming. "
        "Economic values reflect societal cost savings, not City revenues."
    )


def format_currency(val: float) -> str:
    """Format float as USD currency string."""
    return f"${val:,.0f}"


def format_currency_compact(val: float) -> str:
    """Format float as compact planning-level currency string (e.g., $15.0M, $400k)."""
    if pd.isnull(val) or val is None:
        return "N/A"
    abs_val = abs(val)
    if abs_val >= 1e9:
        return f"${val / 1e9:.2f}B"
    if abs_val >= 1e6:
        return f"${val / 1e6:.1f}M"
    if abs_val >= 1e3:
        return f"${val / 1e3:.0f}k"
    return f"${val:,.0f}"


def format_bcr_compact(val: float) -> str:
    """Format Benefit-Cost Ratio rounded to integer or 1-decimal decision relevance (e.g., ~267:1, ~2.7:1)."""
    if pd.isnull(val) or val is None:
        return "N/A"
    if val >= 10:
        return f"~{int(round(val))}:1"
    return f"~{val:.1f}:1"


def format_count_compact(val: float) -> str:
    """Format crash counts rounded to whole numbers with tilde (e.g., ~2,170, ~2,385)."""
    if pd.isnull(val) or val is None:
        return "N/A"
    return f"~{int(round(val)):,}"


def format_ksi_compact(val: float) -> str:
    """Format KSI counts rounded to whole numbers with tilde (e.g., ~48, ~49)."""
    if pd.isnull(val) or val is None:
        return "N/A"
    return f"~{int(round(val))}"


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


def format_engineering_status(status: str | None) -> str:
    """Format engineering feasibility status into standardized descriptive label."""
    if not status or pd.isnull(status):
        return "Engineering review required"
    s = str(status).strip().upper()
    if s in ("UNKNOWN", "REVIEW_REQUIRED"):
        return "Engineering review required"
    if s == "ELIGIBLE":
        return "Eligible (Verified)"
    if s == "NOT_APPLICABLE":
        return "Not applicable"
    return str(status)
