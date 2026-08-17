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

import geopandas as gpd
import pandas as pd
import pydeck as pdk
import streamlit as st

from dashboard.streamlit.components import (
    format_currency,
    format_percent,
    render_engineering_review_banner,
    render_governance_header_banner,
    render_page_header,
    render_sidebar_controls,
)
from dashboard.streamlit.data_access import (
    compute_economic_only_benefits,
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

# Render sidebar controls & get single selected portfolio_id
portfolio_id = render_sidebar_controls(df_summary)

# Extract single portfolio data & selected spatial GeoDataFrame
s_row = get_single_portfolio_summary(df_summary, portfolio_id)
df_sel_benefits = get_selected_portfolio_benefits(df_selections, df_benefits, portfolio_id)
df_sel_benefits = compute_economic_only_benefits(df_sel_benefits)

render_governance_header_banner(s_row["run_group"], (s_row["run_group"] == "OFFICIAL"))

st.markdown("---")
st.subheader("1. Selected portfolio investment map")

# Visual Map Legend
col_leg1, col_leg2 = st.columns([1, 1])
with col_leg1:
    st.markdown(":orange[■] **High-SVI equity priority areas** (CDC Social Vulnerability Index proxy)")
with col_leg2:
    st.markdown(":blue[■] **Standard priority corridors**")

# Prepare PyDeck map data for selected corridors
gdf_sel = get_selected_corridors_geodataframe(df_selections, gdf_corridors, portfolio_id)

# Merge forecast risk & master attributes onto gdf_sel
gdf_map = gdf_sel.merge(
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

# Prepare GeoJSON FeatureCollection dict for PyDeck GeoJsonLayer street linework
geojson_dict = json.loads(gdf_map.to_json())
for feature in geojson_dict["features"]:
    props = feature["properties"]
    props["color"] = [255, 140, 0] if props.get("equity_area_flag") else [31, 119, 180]
    props["capital_cost"] = float(props.get("capital_project_cost", 0.0))
    props["forecast_total"] = float(props.get("annual_forecast_total_crashes_2026", 0.0))
    props["forecast_ksi"] = float(props.get("annual_forecast_ksi_crashes_2026", 0.0))
    props["svi_score"] = float(props.get("corridor_length_weighted_svi", 0.0))
    props["street_name"] = str(props.get("street_name") or props.get("corridor_name") or "N/A")
    props["from_street"] = str(props.get("from_street") or "N/A")
    props["to_street"] = str(props.get("to_street") or "N/A")

# PyDeck GeoJsonLayer for street linework
layer_lines = pdk.Layer(
    "GeoJsonLayer",
    data=geojson_dict,
    get_line_color="properties.color",
    get_line_width=35,
    width_min_pixels=4,
    pickable=True,
)

# PyDeck ScatterplotLayer for centroid markers
map_data = []
for idx, row in gdf_map.iterrows():
    color = [255, 140, 0] if row["equity_area_flag"] else [31, 119, 180]
    map_data.append({
        "corridor_id": row["corridor_id"],
        "corridor_name": row["corridor_name"],
        "street_name": row.get("street_name", row["corridor_name"]),
        "from_street": row.get("from_street", "N/A"),
        "to_street": row.get("to_street", "N/A"),
        "lat": float(row["centroid_latitude"]),
        "lon": float(row["centroid_longitude"]),
        "treatment_name": row["treatment_name"],
        "capital_cost": float(row["capital_project_cost"]),
        "svi_score": float(row.get("corridor_length_weighted_svi", 0.0)),
        "forecast_total": float(row.get("annual_forecast_total_crashes_2026", 0.0)),
        "forecast_ksi": float(row.get("annual_forecast_ksi_crashes_2026", 0.0)),
        "color": color,
    })

df_pydeck = pd.DataFrame(map_data)

# PyDeck View State centered on Chicago
view_state = pdk.ViewState(
    latitude=df_pydeck["lat"].mean() if not df_pydeck.empty else 41.8781,
    longitude=df_pydeck["lon"].mean() if not df_pydeck.empty else -87.6298,
    zoom=10.5,
    pitch=0,
)

layer_points = pdk.Layer(
    "ScatterplotLayer",
    data=df_pydeck,
    get_position=["lon", "lat"],
    get_color="color",
    get_radius=300,
    pickable=True,
)

deck = pdk.Deck(
    layers=[layer_lines, layer_points],
    initial_view_state=view_state,
    tooltip={
        "html": "<b>Corridor:</b> {corridor_name} ({corridor_id})<br/>"
                "<b>Limits:</b> {from_street} to {to_street}<br/>"
                "<b>Recommended Treatment:</b> {treatment_name}<br/>"
                "<b>Capital Cost:</b> ${capital_cost:,.0f}<br/>"
                "<b>2026 Forecast Crashes:</b> {forecast_total:.1f}/yr (KSI: {forecast_ksi:.1f})<br/>"
                "<b>SVI Weighted Score:</b> {svi_score:.3f}",
        "style": {"backgroundColor": "steelblue", "color": "white"},
    },
)

st.pydeck_chart(deck, use_container_width=True)

st.caption(
    "Note: Equity classification uses CDC/ATSDR Social Vulnerability Index (SVI) as a project-defined planning proxy, "
    "not the City of Chicago's official equity definition."
)

st.markdown("---")
st.subheader("2. Corridor detail inspector")

# Corridor Selector Dropdown
corridor_options = df_sel_benefits["corridor_id"].tolist()
corridor_labels = {
    row["corridor_id"]: f"{row['corridor_id']} — {row['corridor_name']} ({row['treatment_name']})"
    for idx, row in df_sel_benefits.iterrows()
}
selected_cid = st.selectbox(
    "Select corridor to inspect:",
    options=corridor_options,
    format_func=lambda cid: corridor_labels[cid],
)

# Extract single corridor record
c_row = df_sel_benefits[df_sel_benefits["corridor_id"] == selected_cid].iloc[0]
m_row = df_master[df_master["corridor_id"] == selected_cid].iloc[0]

# Compute corridor efficiency metrics
c_cost = float(c_row["capital_project_cost"])
c_ksi_averted = float(c_row["crashes_averted_k"] + c_row["crashes_averted_a"])
c_tot_averted = float(c_row["crashes_averted_total"])
cost_per_ksi_str = format_currency(c_cost / c_ksi_averted) if c_ksi_averted > 0 else "N/A"
cost_per_crash_str = format_currency(c_cost / c_tot_averted) if c_tot_averted > 0 else "N/A"

c_comp_bcr = float(c_row["benefit_cost_ratio"])
c_econ_bcr = float(c_row["bcr_economic_only"]) if "bcr_economic_only" in c_row and pd.notnull(c_row["bcr_economic_only"]) else 0.0

ic1, ic2, ic3, ic4 = st.columns(4)
with ic1:
    st.markdown(f"**Corridor Limits:** {m_row.get('from_street', 'N/A')} to {m_row.get('to_street', 'N/A')}")
    st.markdown(f"**Length:** {m_row['spatial_total_length_miles']:.2f} miles")
    st.markdown(f"**SVI Weighted Index:** {m_row['corridor_length_weighted_svi']:.3f}")
with ic2:
    st.markdown(f"**2026 Forecast Total Crashes:** {m_row['annual_forecast_total_crashes_2026']:.1f} / yr")
    st.markdown(f"**2026 Forecast KSI Crashes:** {m_row['annual_forecast_ksi_crashes_2026']:.1f} / yr")
    st.markdown(f"**Demand Risk Rank:** #{int(m_row['demand_risk_rank_2026'])} of 43")
with ic3:
    st.markdown(f"**Recommended Treatment:** {c_row['treatment_name']}")
    st.markdown(f"**Provisional Capital Cost:** {format_currency(c_row['capital_project_cost'])}")
    st.markdown(f"**Physical Applicability:** `:orange[{c_row['physical_applicability_status']} - Review Required]`")
with ic4:
    st.markdown(f"**Annual Crashes Averted:** {c_tot_averted:.2f} / yr (KSI: {c_ksi_averted:.2f})")
    st.markdown(f"**BCR (Comprehensive):** `{c_comp_bcr:.1f} : 1`")
    st.markdown(f"**BCR (Economic-Only):** `{c_econ_bcr:.1f} : 1`")

st.caption(
    f"Efficiency: Cost per KSI Averted = {cost_per_ksi_str} / KSI | Cost per Crash Averted = {cost_per_crash_str} / crash. "
    "Lower cost per KSI averted indicates higher relative efficiency at preventing the most severe crashes."
)

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

df_export["equity_area_flag"] = df_export["equity_area_flag"].apply(lambda x: "Yes" if x else "No")
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

df_export_display.columns = [
    "Corridor ID",
    "Corridor Name",
    "Recommended Treatment",
    "Capital Cost",
    "BCR (Comp)",
    "BCR (Econ)",
    "Total Crashes Averted / Yr",
    "Fatal (K) Averted / Yr",
    "Serious Injury (A) Averted / Yr",
    "Cost / KSI Averted",
    "Cost / Crash Averted",
    "Equity Priority Area",
    "Physical Applicability",
]

st.dataframe(
    df_export_display.style.format({
        "Capital Cost": "${:,.0f}",
        "BCR (Comp)": "{:,.1f}",
        "BCR (Econ)": "{:,.1f}",
        "Total Crashes Averted / Yr": "{:,.2f}",
        "Fatal (K) Averted / Yr": "{:,.2f}",
        "Serious Injury (A) Averted / Yr": "{:,.2f}",
        "Cost / KSI Averted": "${:,.0f}",
        "Cost / Crash Averted": "${:,.0f}",
    }),
    use_container_width=True,
    hide_index=True,
    height=300,
)

# Download CSV button for CURRENTLY selected portfolio only
csv_bytes = df_export.to_csv(index=False).encode("utf-8")
st.download_button(
    label=f"Download CSV for active scenario ({portfolio_id})",
    data=csv_bytes,
    file_name=f"vision_zero_portfolio_selections_{portfolio_id}.csv",
    mime="text/csv",
)

render_engineering_review_banner()

