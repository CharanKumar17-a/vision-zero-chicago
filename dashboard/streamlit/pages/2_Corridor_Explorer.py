"""Corridor Explorer Page - Vision Zero Chicago Decision Support App.

Contract: docs/data_quality/decision_output_mart_contract.md
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Add repository root to sys.path so standalone scripts and Streamlit pages resolve dashboard namespace
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pandas as pd
import streamlit as st

from dashboard.streamlit.components import (
    format_bcr_compact,
    format_cost_per_unit,
    format_count_compact,
    format_currency,
    format_currency_compact,
    format_engineering_status,
    format_equity_flag,
    format_ksi_compact,
    format_percent,
    render_economic_caveat_banner,
    render_engineering_review_banner,
    render_governance_footer,
    render_governance_header_banner,
    render_page_header,
    render_sidebar_controls,
)
from dashboard.streamlit.data_access import (
    compute_economic_only_benefits,
    evaluate_portfolio_scenario,
    get_selected_corridors_geodataframe,
    get_selected_portfolio_benefits,
    get_single_portfolio_summary,
    load_corridor_geodataframe,
    load_corridor_master,
    load_portfolio_summary,
    load_project_selections,
    load_treatment_benefits,
)

render_page_header(
    "Corridor explorer",
    "Spatial corridor risk overlay, equity classification, and project candidate drilldown.",
)

# Load serving datasets
df_summary = load_portfolio_summary()
df_selections = load_project_selections()
df_master = load_corridor_master()
df_benefits = load_treatment_benefits()
gdf_corridors = load_corridor_geodataframe()

total_corridors_count = len(df_master)

# Render sidebar controls & get active scenario parameters
scenario_params = render_sidebar_controls(df_summary, return_dict=True)

# Dynamically solve active scenario
s_row, df_sel_benefits = evaluate_portfolio_scenario(
    budget=scenario_params["budget"],
    equity_floor=scenario_params["equity_floor"],
    cost_case=scenario_params["cost_case"],
    cmf_case=scenario_params["cmf_case"],
    df_benefits=df_benefits,
)
if not df_sel_benefits.empty:
    df_sel_benefits = compute_economic_only_benefits(df_sel_benefits)

portfolio_id = str(s_row["portfolio_id"])
render_governance_header_banner(
    run_group=s_row["run_group"],
    is_official=(s_row["run_group"] == "OFFICIAL"),
    scenario_params=scenario_params,
)

# -----------------------------------------------------------------------------
# Section 1 — Corridor Detail Inspector (Inspector-First Hierarchy)
# -----------------------------------------------------------------------------
st.markdown("---")
st.subheader("1. Corridor detail inspector")
st.caption("Inspect individual corridor geometry, baseline crash burden, treatment candidates, and optimization decision rationale.")

selected_cids = set(df_sel_benefits["corridor_id"])

# Build 43-corridor selection options with [Selected] / [Deferred] badges
corridor_options = sorted(df_master["corridor_id"].tolist())
corridor_labels = {}
for cid in corridor_options:
    cm = df_master[df_master["corridor_id"] == cid].iloc[0]
    if cid in selected_cids:
        c_sel = df_sel_benefits[df_sel_benefits["corridor_id"] == cid].iloc[0]
        corridor_labels[cid] = f"🟢 [Selected] {cid} — {cm['corridor_name']} ({c_sel['treatment_name']})"
    else:
        corridor_labels[cid] = f"⚪ [Deferred] {cid} — {cm['corridor_name']} (Deferred under ceiling)"

selected_cid = st.selectbox(
    "Select high-crash corridor to inspect (43 candidate corridors):",
    options=corridor_options,
    format_func=lambda cid: corridor_labels[cid],
    index=0,
)

try:
    from dashboard.streamlit.analytics import track_corridor_inspected
    track_corridor_inspected(selected_cid)
except Exception:
    pass

m_row = df_master[df_master["corridor_id"] == selected_cid].iloc[0]
is_selected = selected_cid in selected_cids

# Extract treatment candidates for this corridor
base_benefits_cid = df_benefits[
    (df_benefits["corridor_id"] == selected_cid)
    & (
        (df_benefits["uncertainty_scenario"] == "BASE")
        if "uncertainty_scenario" in df_benefits.columns
        else (df_benefits["scenario_level"] == "BASE")
    )
]

if is_selected:
    c_row = df_sel_benefits[df_sel_benefits["corridor_id"] == selected_cid].iloc[0]
    c_cost = float(c_row["capital_project_cost"])
    c_ksi_averted = float(c_row["crashes_averted_ksi"])
    c_tot_averted = float(c_row["crashes_averted_total"])
    c_comp_bcr = float(c_row["benefit_cost_ratio"])
    c_econ_bcr = float(c_row["bcr_economic_only"]) if "bcr_economic_only" in c_row and pd.notnull(c_row["bcr_economic_only"]) else 0.0
    c_trt = str(c_row["treatment_name"])
    c_status = "SELECTED"
else:
    best_cand = base_benefits_cid.sort_values("benefit_cost_ratio", ascending=False).iloc[0]
    c_cost = float(best_cand["capital_project_cost"])
    c_ksi_averted = float(best_cand["crashes_averted_k"] + best_cand["crashes_averted_a"])
    c_tot_averted = float(best_cand["crashes_averted_total"])
    c_comp_bcr = float(best_cand["benefit_cost_ratio"])
    c_econ_bcr = 0.0
    c_trt = f"{best_cand['treatment_name']} (Candidate)"
    c_status = "DEFERRED"

cost_per_ksi_str = format_cost_per_unit(c_cost, c_ksi_averted, "KSI")
cost_per_crash_str = format_cost_per_unit(c_cost, c_tot_averted, "crash")

st.markdown(f"#### {selected_cid} — {m_row['corridor_name']}")

ic1, ic2, ic3, ic4 = st.columns(4)
with ic1:
    st.markdown(f"• **Corridor Limits:** {m_row.get('from_street', 'N/A')} to {m_row.get('to_street', 'N/A')}")
    st.markdown(f"• **Length:** {m_row['spatial_total_length_miles']:.2f} miles")
    st.markdown(f"• **SVI Weighted Index:** {m_row['corridor_length_weighted_svi']:.3f}")
with ic2:
    st.markdown(f"• **Baseline Total Crashes:** {m_row['annual_forecast_total_crashes_2026']:.1f} / yr")
    st.markdown(f"• **Baseline KSI:** {m_row['annual_forecast_ksi_crashes_2026']:.1f} / yr")
    st.markdown(f"• **Demand Risk Rank:** #{int(m_row['demand_risk_rank_2026'])} of {total_corridors_count}")
with ic3:
    st.markdown(f"• **Recommended Treatment:** {c_trt}")
    st.markdown(f"• **Estimated Capital Cost:** {format_currency_compact(c_cost).replace('$', '&dollar;')} ({format_currency(c_cost).replace('$', '&dollar;')})")
    st.markdown(f"• **Engineering Status:** **Engineering review required** (Provisional status)")
with ic4:
    st.markdown(f"• **Estimated Avoided Crashes:** {format_count_compact(c_tot_averted)} all-severity / yr (KSI: {format_ksi_compact(c_ksi_averted)} / yr)")
    st.markdown(f"• **BCR (Comprehensive):** `{format_bcr_compact(c_comp_bcr)}` ({c_comp_bcr:.1f} : 1)")
    st.markdown(f"• **Portfolio Status:** **{c_status}**")

# Explicit Selection Rationale Note
if is_selected:
    st.info(
        f"**Selection Rationale:** Selected by the active portfolio optimization under the stated budget, equity, treatment, and screening constraints; "
        f"the candidate provides an estimated {c_ksi_averted:.1f} avoided KSI/year at a planning-level BCR of {c_comp_bcr:.1f}:1."
    )
else:
    st.warning(
        f"**Deferred Rationale:** Corridor `{selected_cid}` was deferred under active scenario `{portfolio_id}` because its capital cost "
        f"({format_currency(c_cost).replace('$', '&dollar;')}) exceeds remaining budget slack or higher-efficiency alternatives took precedence. "
        f"Best candidate treatment provides a positive ROI ({c_comp_bcr:.1f}:1) and would be considered under expanded funding."
    )

with st.expander("View all evaluated treatment candidates for this corridor", expanded=False):
    cand_disp = base_benefits_cid[[
        "treatment_name", "capital_project_cost", "benefit_cost_ratio",
        "crashes_averted_total", "crashes_averted_k", "crashes_averted_a",
        "physical_applicability_status"
    ]].copy()
    cand_disp.columns = [
        "Treatment Candidate", "Capital Cost", "BCR",
        "Total Avoided / Yr", "Fatal Avoided / Yr", "Serious Injury Avoided / Yr",
        "Engineering Status"
    ]
    st.dataframe(
        cand_disp.style.format({
            "Capital Cost": "${:,.0f}",
            "BCR": "{:,.1f}",
            "Total Avoided / Yr": "{:,.2f}",
            "Fatal Avoided / Yr": "{:,.2f}",
            "Serious Injury Avoided / Yr": "{:,.2f}",
        }),
        width="stretch",
        hide_index=True,
    )

# -----------------------------------------------------------------------------
# Section 2 — Spatial Investment Map (Full 43 Corridors - Decision DEC-03)
# -----------------------------------------------------------------------------
st.markdown("---")
st.subheader("2. Citywide corridor investment map (43 corridors)")
st.caption("Visualizes all 43 candidate high-crash corridors across Chicago with active portfolio funding status and CDC/ATSDR SVI equity priority areas.")

# Visual Map Legend (Separated Portfolio Status from Interaction State - Issue A)
leg_col1, leg_col2 = st.columns([3, 2])
with leg_col1:
    st.markdown("**Portfolio Funding Status (Under Active Scenario):**")
    l1, l2, l3 = st.columns(3)
    with l1:
        st.markdown("🟢 **Selected (High-SVI)**\n\n*Thick green corridor, priority*")
    with l2:
        st.markdown("🔵 **Selected (Standard)**\n\n*Medium blue corridor, funded*")
    with l3:
        st.markdown("🟠 **Deferred (Candidate)**\n\n*Thinner amber corridor, unselected*")

with leg_col2:
    st.markdown("**Interactive Selection State:**")
    st.markdown(f"🟡 **Inspected Corridor:** `{selected_cid}` — **{m_row['corridor_name']}** (*Highlighted gold line & halo marker*)")

# Prepare full 43-corridor GeoDataFrame
gdf_map = gdf_corridors.merge(
    df_master[[
        "corridor_id",
        "street_name",
        "from_street",
        "to_street",
        "spatial_total_length_miles",
        "corridor_length_weighted_svi",
        "annual_forecast_total_crashes_2026",
        "annual_forecast_ksi_crashes_2026",
    ]],
    on="corridor_id",
    how="left",
)

# Merge selected treatment info
gdf_map = gdf_map.merge(
    df_sel_benefits[["corridor_id", "treatment_name", "capital_project_cost", "equity_area_flag"]],
    on="corridor_id",
    how="left",
)

# Prepare GeoJSON FeatureCollection dict for PyDeck GeoJsonLayer
geojson_dict = json.loads(gdf_map.to_json())
for feature in geojson_dict["features"]:
    props = feature["properties"]
    cid = props.get("corridor_id")
    is_sel = cid in selected_cids
    is_active = (cid == selected_cid)

    if is_active:
        props["color"] = [234, 179, 8]  # Vibrant Gold
        props["width"] = 52
    elif is_sel:
        # High-SVI Green vs Standard Blue
        props["color"] = [22, 101, 52] if props.get("equity_area_flag") else [30, 64, 175]
        props["width"] = 36 if props.get("equity_area_flag") else 30
    else:
        props["color"] = [194, 65, 12]  # Dark Amber (Deferred)
        props["width"] = 20

    props["capital_cost"] = float(props.get("capital_project_cost") or 0.0)
    props["forecast_total"] = float(props.get("annual_forecast_total_crashes_2026") or 0.0)
    props["forecast_ksi"] = float(props.get("annual_forecast_ksi_crashes_2026") or 0.0)
    props["svi_score"] = float(props.get("corridor_length_weighted_svi") or 0.0)
    props["street_name"] = str(props.get("street_name") or props.get("corridor_name") or "N/A")
    props["from_street"] = str(props.get("from_street") or "N/A")
    props["to_street"] = str(props.get("to_street") or "N/A")
    props["treatment_display"] = str(props.get("treatment_name") or "Deferred candidate")
    props["status_display"] = "SELECTED" if is_sel else "DEFERRED"
    props["badge"] = "🟢 SELECTED (HIGH-SVI)" if (is_sel and props.get("equity_area_flag")) else ("🔵 SELECTED (STANDARD)" if is_sel else "🟠 DEFERRED")

# Lazy import pydeck
import pydeck as pdk

layer_lines = pdk.Layer(
    "GeoJsonLayer",
    data=geojson_dict,
    get_line_color="properties.color",
    get_line_width="properties.width",
    width_min_pixels=2,
    pickable=True,
)

# Centroid ScatterplotLayer for all 43 corridors
map_data = []
for idx, row in gdf_map.iterrows():
    cid = row["corridor_id"]
    is_sel = cid in selected_cids
    is_active = (cid == selected_cid)

    if is_active:
        color = [234, 179, 8]  # Gold
        radius = 460
        badge = "🟡 INSPECTED"
    elif is_sel:
        color = [22, 101, 52] if row.get("equity_area_flag") else [30, 64, 175]
        radius = 320 if row.get("equity_area_flag") else 280
        badge = "🟢 SELECTED (HIGH-SVI)" if row.get("equity_area_flag") else "🔵 SELECTED (STANDARD)"
    else:
        color = [194, 65, 12]  # Amber
        radius = 200
        badge = "🟠 DEFERRED"

    map_data.append({
        "corridor_id": cid,
        "corridor_name": row["corridor_name"],
        "street_name": row.get("street_name", row["corridor_name"]),
        "from_street": row.get("from_street", "N/A"),
        "to_street": row.get("to_street", "N/A"),
        "lat": float(row["centroid_latitude"]),
        "lon": float(row["centroid_longitude"]),
        "treatment_name": row.get("treatment_name") or "Deferred candidate",
        "capital_cost": float(row.get("capital_project_cost") or 0.0),
        "svi_score": float(row.get("corridor_length_weighted_svi", 0.0)),
        "forecast_total": float(row.get("annual_forecast_total_crashes_2026", 0.0)),
        "forecast_ksi": float(row.get("annual_forecast_ksi_crashes_2026", 0.0)),
        "status": "SELECTED" if is_sel else "DEFERRED",
        "badge": badge,
        "color": color,
        "radius": radius,
    })

df_pydeck = pd.DataFrame(map_data)

# Frame citywide Chicago corridor network cleanly (Issue A)
view_state = pdk.ViewState(
    latitude=41.855,
    longitude=-87.680,
    zoom=10.2,
    pitch=0,
)

layer_points = pdk.Layer(
    "ScatterplotLayer",
    data=df_pydeck,
    get_position=["lon", "lat"],
    get_color="color",
    get_radius="radius",
    pickable=True,
)

deck = pdk.Deck(
    layers=[layer_lines, layer_points],
    initial_view_state=view_state,
    tooltip={
        "html": "<div style='font-family: -apple-system, BlinkMacSystemFont, sans-serif; padding: 4px 6px; min-width: 200px;'>"
                "<div style='font-size: 13px; font-weight: 700; color: #F8FAFC; margin-bottom: 4px;'>{badge}</div>"
                "<div style='font-size: 13px; font-weight: 600; color: #93C5FD;'>{corridor_id} — {corridor_name}</div>"
                "<hr style='margin: 4px 0; border: none; border-top: 1px solid #475569;'/>"
                "<div style='font-size: 11px; color: #E2E8F0;'><b>Limits:</b> {from_street} to {to_street}</div>"
                "<div style='font-size: 11px; color: #E2E8F0;'><b>Treatment:</b> {treatment_name}</div>"
                "<div style='font-size: 11px; color: #E2E8F0;'><b>Estimated Cost:</b> ${capital_cost:,.0f}</div>"
                "<div style='font-size: 11px; color: #E2E8F0;'><b>2026 Baseline Total:</b> {forecast_total:.1f}/yr (KSI: {forecast_ksi:.1f}/yr)</div>"
                "<div style='font-size: 11px; color: #E2E8F0;'><b>SVI Equity Score:</b> {svi_score:.3f}</div>"
                "</div>",
        "style": {"backgroundColor": "#0F172A", "color": "#F8FAFC", "borderRadius": "6px", "boxShadow": "0 4px 12px rgba(0,0,0,0.4)"},
    },
)

st.pydeck_chart(deck, width="stretch")

# -----------------------------------------------------------------------------
# Section 3 — Selected Projects Export Table
# -----------------------------------------------------------------------------
st.markdown("---")
st.subheader("3. Selected projects export table")

df_export = df_sel_benefits[[
    "portfolio_id",
    "corridor_id",
    "corridor_name",
    "treatment_id",
    "treatment_name",
    "uncertainty_scenario",
    "capital_project_cost",
    "benefit_cost_ratio",
    "bcr_economic_only",
    "crashes_averted_total",
    "crashes_averted_k",
    "crashes_averted_a",
    "equity_area_flag",
    "physical_applicability_status",
]].copy()

df_export["equity_area_flag"] = df_export["equity_area_flag"].apply(format_equity_flag)
df_export["ksi_averted"] = df_export["crashes_averted_k"] + df_export["crashes_averted_a"]
df_export["cost_per_ksi_averted"] = df_export["capital_project_cost"] / df_export["ksi_averted"].replace(0, float("nan"))
df_export["cost_per_crash_averted"] = df_export["capital_project_cost"] / df_export["crashes_averted_total"].replace(0, float("nan"))

df_export_display = df_export[[
    "corridor_id",
    "corridor_name",
    "treatment_name",
    "capital_project_cost",
    "benefit_cost_ratio",
    "bcr_economic_only",
    "crashes_averted_total",
    "crashes_averted_k",
    "crashes_averted_a",
    "cost_per_ksi_averted",
    "cost_per_crash_averted",
    "equity_area_flag",
    "physical_applicability_status",
]].copy()

df_export_display["physical_applicability_status"] = df_export_display["physical_applicability_status"].apply(format_engineering_status)

df_export_display.columns = [
    "Corridor ID",
    "Corridor Name",
    "Recommended Treatment",
    "Estimated Capital Cost",
    "BCR (Comp)",
    "BCR (Econ)",
    "Estimated All-Severity Crashes Avoided / Yr",
    "Estimated Fatal (K) Avoided / Yr",
    "Estimated Serious Injury (A) Avoided / Yr",
    "Cost / KSI Avoided",
    "Cost / All-Severity Crash Avoided",
    "High-SVI Priority Area",
    "Engineering Status",
]

st.dataframe(
    df_export_display.style.format({
        "Estimated Capital Cost": "${:,.0f}",
        "BCR (Comp)": "{:,.1f}",
        "BCR (Econ)": "{:,.1f}",
        "Estimated All-Severity Crashes Avoided / Yr": "{:,.2f}",
        "Estimated Fatal (K) Avoided / Yr": "{:,.2f}",
        "Estimated Serious Injury (A) Avoided / Yr": "{:,.2f}",
        "Cost / KSI Avoided": "${:,.0f}",
        "Cost / All-Severity Crash Avoided": "${:,.0f}",
    }),
    width="stretch",
    hide_index=True,
    height=280,
)

# Download CSV button for CURRENTLY selected portfolio only
csv_bytes = df_export.to_csv(index=False).encode("utf-8")
if st.download_button(
    label=f"Download CSV for active scenario ({portfolio_id})",
    data=csv_bytes,
    file_name=f"vision_zero_portfolio_selections_{portfolio_id}.csv",
    mime="text/csv",
):
    try:
        from dashboard.streamlit.analytics import track_portfolio_exported
        track_portfolio_exported(
            scenario_id=portfolio_id,
            budget=float(s_row["budget_usd"]),
        )
    except Exception:
        pass

# Standardized Consolidated Governance Footer (Decision DEC-04)
render_governance_footer()
