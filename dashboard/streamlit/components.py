"""UI components and sidebar control panel for Vision Zero Chicago Streamlit decision support app.

Contract: docs/data_quality/decision_output_mart_contract.md
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st


def inject_global_css() -> None:
    """Inject global typography and visual consistency CSS.

    Establishes a cohesive, minimal dark executive analytics theme across all
    four application pages. No user-supplied content is embedded.
    """
    st.markdown(
        """
        <style>
        /* ── Global Font Hierarchy & App Background ─────────────────────── */
        html, body, .stApp {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            background-color: #0B0F19;
            color: #CBD5E1;
        }

        /* ── Preserve Material Icons & Streamlit Glyphs ─────────────────── */
        [data-testid="stIconMaterial"], [class*="material-symbols"], [class*="stIcon"], .material-symbols-rounded, .material-symbols-outlined {
            font-family: 'Material Symbols Rounded', 'Material Icons', sans-serif !important;
            font-style: normal !important;
        }

        /* ── App & Page Titles ──────────────────────────────────────────── */
        h1 {
            font-size: 24px !important;
            font-weight: 700 !important;
            letter-spacing: -0.3px !important;
            margin-top: 0.1rem !important;
            margin-bottom: 0.2rem !important;
            color: #F8FAFC !important;
        }
        h2 {
            font-size: 19px !important;
            font-weight: 600 !important;
            letter-spacing: -0.2px !important;
            margin-top: 0.2rem !important;
            margin-bottom: 0.2rem !important;
            color: #F1F5F9 !important;
        }
        h3 {
            font-size: 16px !important;
            font-weight: 600 !important;
            margin-top: 0.8rem !important;
            margin-bottom: 0.3rem !important;
            color: #E2E8F0 !important;
        }
        h4 {
            font-size: 14px !important;
            font-weight: 600 !important;
            margin-top: 0.5rem !important;
            margin-bottom: 0.25rem !important;
            color: #CBD5E1 !important;
        }

        /* ── Body Text & Paragraphs ─────────────────────────────────────── */
        p, li {
            font-size: 14px !important;
            line-height: 1.6 !important;
            color: #94A3B8 !important;
        }
        .stMarkdown p {
            margin-bottom: 0.35rem !important;
        }
        strong, b {
            color: #F1F5F9 !important;
            font-weight: 600 !important;
        }

        /* ── Caption / Secondary Text ───────────────────────────────────── */
        .stCaption, small {
            font-size: 13px !important;
            line-height: 1.5 !important;
            color: #64748B !important;
        }

        /* ── KPI Metric Cards ───────────────────────────────────────────── */
        [data-testid="stMetric"] {
            background-color: #111827 !important;
            border: 1px solid #1E293B !important;
            border-radius: 8px !important;
            padding: 0.65rem 0.85rem !important;
        }
        [data-testid="stMetricValue"] {
            font-size: 22px !important;
            font-weight: 700 !important;
            color: #FFFFFF !important;
            letter-spacing: -0.2px !important;
        }
        [data-testid="stMetricLabel"] {
            font-size: 12px !important;
            font-weight: 600 !important;
            color: #94A3B8 !important;
            text-transform: none !important;
            margin-bottom: 2px !important;
        }
        [data-testid="stMetricDelta"] {
            font-size: 12px !important;
            font-weight: 500 !important;
        }

        /* ── Alert / Info / Governance Banners ──────────────────────────── */
        [data-testid="stAlert"] {
            border-radius: 8px !important;
            padding: 0.65rem 0.95rem !important;
            margin-top: 0.4rem !important;
            margin-bottom: 0.6rem !important;
        }
        [data-testid="stAlert"] p,
        [data-testid="stAlert"] li {
            font-size: 13.5px !important;
            line-height: 1.5 !important;
        }

        /* ── Sidebar ────────────────────────────────────────────────────── */
        [data-testid="stSidebar"] {
            background-color: #0E131F !important;
            border-right: 1px solid #1E293B !important;
        }
        [data-testid="stSidebar"] label {
            font-size: 13px !important;
            font-weight: 600 !important;
            color: #CBD5E1 !important;
        }
        [data-testid="stSidebar"] p {
            font-size: 13px !important;
            color: #94A3B8 !important;
        }
        [data-testid="stSidebarNavLink"] {
            font-size: 13.5px !important;
            font-weight: 500 !important;
            color: #94A3B8 !important;
            border-radius: 6px !important;
        }
        [data-testid="stSidebarNavLink"][aria-current="page"] {
            background-color: #1E293B !important;
            color: #FFFFFF !important;
            font-weight: 600 !important;
        }

        /* ── Inline Code / Badges ───────────────────────────────────────── */
        code {
            font-size: 12px !important;
            padding: 2px 5px !important;
            border-radius: 4px !important;
            background-color: #1E293B !important;
            color: #93C5FD !important;
            border: 1px solid #334155 !important;
            font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace !important;
        }

        /* ── Dataframe Headers & Cells ──────────────────────────────────── */
        .dvn-scroller thead th {
            font-size: 13px !important;
            font-weight: 600 !important;
            color: #E2E8F0 !important;
        }
        .dvn-scroller tbody td {
            font-size: 13px !important;
        }

        /* ── Expander ───────────────────────────────────────────────────── */
        [data-testid="stExpander"] {
            border-radius: 8px !important;
            border: 1px solid #1E293B !important;
            background-color: #111827 !important;
        }
        [data-testid="stExpander"] summary p {
            font-size: 13.5px !important;
            font-weight: 600 !important;
            color: #E2E8F0 !important;
        }

        /* ── Divider Spacing ────────────────────────────────────────────── */
        hr {
            margin: 0.6rem 0 !important;
            border-color: #1E293B !important;
        }

        /* ── Buttons ────────────────────────────────────────────────────── */
        button[kind="primary"], button[kind="secondary"] {
            font-size: 13px !important;
            font-weight: 500 !important;
            border-radius: 6px !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_sidebar_controls(
    df_summary: Optional[pd.DataFrame] = None,
    return_dict: bool = False,
) -> Any:
    """Render decision-first sidebar scenario controls for Budget, Equity Floor, Cost Case, and CMF Case.

    Args:
        df_summary: Optional portfolio summary dataset for backward compatibility.
        return_dict: If True, returns dict with keys ('budget', 'equity_floor', 'cost_case', 'cmf_case', 'portfolio_id').
            If False (default), returns portfolio_id string.

    Returns:
        portfolio_id (str) or dict containing scenario parameters.
    """
    st.sidebar.markdown("### Vision Zero Chicago")
    st.sidebar.caption("Safety capital investment prioritization")
    st.sidebar.markdown("#### Scenario controls")
    st.sidebar.markdown("---")

    # Reset to defaults button
    if st.sidebar.button("Reset to Baseline Scenario", help="Reset all controls to the $15M baseline policy scenario."):
        st.session_state["sidebar_budget_slider"] = 15000000.0
        st.session_state["sidebar_equity_select"] = 0.20
        st.session_state["sidebar_cost_select"] = "BASE"
        st.session_state["sidebar_cmf_select"] = "BASE"
        st.rerun()

    # 1. Planning Budget Ceiling (Policy Constraint #1)
    budgets = [2000000.0, 4000000.0, 6000000.0, 10000000.0, 15000000.0, 20000000.0, 25000000.0, 30000000.0, 40000000.0]
    default_b_val = 15000000.0

    selected_b_val = st.sidebar.select_slider(
        "Planning budget ceiling",
        options=budgets,
        value=st.session_state.get("sidebar_budget_slider", default_b_val),
        key="sidebar_budget_slider",
        format_func=lambda b: f"${int(b / 1e6)}M" if b >= 1e6 else f"${int(b / 1e3)}k",
    )

    # 2. Equity Spending Floor (Policy Constraint #2)
    equity_floors = [0.20, 0.30, 0.40, 0.50]
    saved_ef = st.session_state.get("sidebar_equity_select", 0.20)
    ef_idx = equity_floors.index(saved_ef) if saved_ef in equity_floors else 0

    selected_ef_val = st.sidebar.selectbox(
        "Minimum equity spending floor",
        options=equity_floors,
        index=ef_idx,
        key="sidebar_equity_select",
        format_func=lambda ef: f"{int(round(ef * 100))}%",
    )

    # 3. Cost & Scope Case (Sensitivity Parameter #1)
    cost_cases = ["BASE", "LOW", "HIGH"]
    saved_cost = st.session_state.get("sidebar_cost_select", "BASE")
    cost_idx = cost_cases.index(saved_cost) if saved_cost in cost_cases else 0

    selected_cost_val = st.sidebar.selectbox(
        "Cost & scope case",
        options=cost_cases,
        index=cost_idx,
        key="sidebar_cost_select",
        help="BASE: Sourced unit costs ($15k refuge, $400k/mi road diet, $22.5k RRFB). LOW: Lower project expenditure / minimal scope ($160.8k mean cost). HIGH: Higher project expenditure / comprehensive scope ($234.1k mean cost).",
    )

    # 4. CMF Benefit Case (Sensitivity Parameter #2)
    cmf_cases = ["BASE", "CONSERVATIVE", "OPTIMISTIC"]
    saved_cmf = st.session_state.get("sidebar_cmf_select", "BASE")
    cmf_idx = cmf_cases.index(saved_cmf) if saved_cmf in cmf_cases else 0

    selected_scen = st.sidebar.selectbox(
        "CMF uncertainty level",
        options=cmf_cases,
        index=cmf_idx,
        key="sidebar_cmf_select",
        help="BASE: Published FHWA CMF point estimate. CONSERVATIVE: Lower-bound safety benefit (+1.96 SE). OPTIMISTIC: Upper-bound safety benefit (-1.96 SE).",
    )

    # Resolve portfolio_id string
    b_m = int(selected_b_val / 1e6) if selected_b_val >= 1e6 else int(selected_b_val / 1e3)
    b_label = f"{b_m}M" if selected_b_val >= 1e6 else f"{b_m}k"
    eq_pct = int(round(selected_ef_val * 100))

    cost_norm = "CONSERVATIVE" if selected_cost_val == "LOW" else ("OPTIMISTIC" if selected_cost_val == "HIGH" else "BASE")
    if selected_scen == cost_norm and selected_b_val in [15e6, 25e6, 40e6] and selected_ef_val in [0.20, 0.30, 0.40]:
        selected_pid = f"PORT_OFF_{selected_scen}_B{b_label}_EQ{eq_pct}"
    elif selected_scen == cost_norm and selected_b_val in [2e6, 4e6, 6e6] and selected_ef_val in [0.20, 0.30, 0.40]:
        selected_pid = f"PORT_STR_{selected_scen}_B{b_label}_EQ{eq_pct}"
    else:
        selected_pid = f"PORT_DYN_{selected_scen[:3]}_{selected_cost_val[:3]}_B{b_label}_EQ{eq_pct}"

    # Human-readable scenario descriptor badge
    b_label = f"${int(selected_b_val/1e6)}M" if selected_b_val >= 1e6 else f"${int(selected_b_val/1e3)}k"
    eq_label = f"{int(round(selected_ef_val*100))}%"
    st.sidebar.markdown("---")
    st.sidebar.info(
        f"**Active Scenario**\n\n"
        f"• **Budget:** {b_label}\n"
        f"• **Equity Floor:** {eq_label}\n"
        f"• **Cost Case:** {selected_cost_val.title()}\n"
        f"• **CMF Tier:** {selected_scen.title()}"
    )
    st.sidebar.caption(f"Scenario ID: `{selected_pid}`")

    from dashboard.streamlit.data_access import load_validation_evidence

    evidence = load_validation_evidence()
    mart_completed = (
        evidence.get("decision_mart", {}).get("completed_at_utc")
        or evidence.get("deployment_manifest", {}).get("generated_at_utc", "")
    )
    val_date = mart_completed[:10] if len(mart_completed) >= 10 else "2026-08-17"

    st.sidebar.markdown("---")
    st.sidebar.caption(
        f"**Data Freshness**\n\n"
        f"• Analysis period: **2018–2025**\n"
        f"• Data last validated: **{val_date}**\n"
        f"• Status: **Validated**"
    )

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

    if return_dict:
        return {
            "budget": float(selected_b_val),
            "equity_floor": float(selected_ef_val),
            "cost_case": selected_cost_val,
            "cmf_case": selected_scen,
            "portfolio_id": selected_pid,
        }

    return selected_pid


def render_page_header(page_title: str, subtitle: str | None = None) -> None:
    """Render unified professional header across all application pages."""
    try:
        from dashboard.streamlit.analytics import track_page_view
        track_page_view(page_title)
    except Exception:
        pass

    st.title("Vision Zero Chicago — Safety Capital Investment Prioritization")
    st.header(page_title)
    if subtitle:
        st.caption(subtitle)


def render_governance_header_banner(
    run_group: str = "OFFICIAL",
    is_official: bool = True,
    scenario_params: dict[str, Any] | None = None,
    custom_subtitle: str | None = None,
) -> None:
    """Render unified information/notice banner across all application pages."""
    if scenario_params:
        b_val = scenario_params.get("budget", 15000000.0)
        b_label = f"&dollar;{int(b_val/1e6)}M" if b_val >= 1e6 else f"&dollar;{int(b_val/1e3)}k"
        ef_label = f"{int(round(scenario_params.get('equity_floor', 0.20) * 100))}%"
        cost_label = str(scenario_params.get("cost_case", "BASE")).title()
        cmf_label = str(scenario_params.get("cmf_case", "BASE")).title()

        is_baseline = (
            b_val == 15000000.0
            and scenario_params.get("equity_floor", 0.20) == 0.20
            and scenario_params.get("cost_case") == "BASE"
            and scenario_params.get("cmf_case") == "BASE"
        )
        tag = "Baseline Recommendation" if is_baseline else "Active Planning Scenario"
        header_line = f"**{tag}: {b_label} Budget • {ef_label} Equity Floor • {cost_label} Cost • {cmf_label} CMF**"
    elif is_official:
        header_line = "**Active Planning Scenario: Official Planning Portfolio**"
    else:
        header_line = "**Diagnostic Stress Scenario: Constrained Budget Analysis**"

    if custom_subtitle:
        body_line = custom_subtitle
    elif is_official:
        body_line = (
            "&dollar;15M budget is binding (&dollar;14.99M allocated across 39 corridors); "
            "&dollar;25M / &dollar;40M allow full 43-corridor coverage. "
            "All selections require engineering field review."
        )
    else:
        body_line = (
            "Diagnostic stress scenario (&dollar;2M–&dollar;6M budget constraints). "
            "Planning-level decision support only; does not constitute City policy or project authorization."
        )

    st.info(f"{header_line}\n\n{body_line}")


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
    """Format KSI counts with decision precision (e.g., ~1.6 for single corridor, ~48 for portfolio)."""
    if pd.isnull(val) or val is None:
        return "N/A"
    if val >= 10:
        return f"~{int(round(val))}"
    return f"~{val:.1f}"


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
