"""Corridor Explorer Page - Vision Zero Chicago Decision Support App.

Contract: docs/data_quality/decision_output_mart_contract.md
"""

from __future__ import annotations

import geopandas as gpd
import pandas as pd
import pydeck as pdk
import streamlit as st

from dashboard.streamlit.components import (
    format_currency,
    format_percent,
    render_engineering_review_banner,
    render_governance_header_banner,
    render_sidebar_controls,
)
from dashboard.streamlit.data_access import (
    load_corridor_geodataframe,
    load_corridor_master,
    load_portfolio_summary,
    load_project_selections,
    load_treatment_benefits,
    get_selected_corridors_geodataframe,
    get_selected_portfolio_benefits,
    get_single_portfolio_selections,
    get_single_portfolio_summary,
)

st.set_page_config(page_title="Corridor Explorer - Vision Zero Chicago", layout="wide")

st.title("Vision Zero Chicago - Corridor Explorer")
st.markdown("Spatial corridor risk overlay, SVI equity classification, and project candidate drilldown.")

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

render_governance_header_banner(s_row["run_group"], (s_row["run_group"] == "OFFICIAL"))
render_engineering_review_banner()

st.markdown("---")
st.subheader("Selected Portfolio Linework & Centroid Map (EPSG:4326)")

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

# Convert centroids & attributes for PyDeck scatterplot / path layer
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
    get_radius=400,
    pickable=True,
)

deck = pdk.Deck(
    layers=[layer_points],
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

st.caption("Orange markers = High-SVI Equity Priority Areas; Blue markers = Non-Equity Priority Corridors.")

st.markdown("---")
st.subheader("Corridor Detail Inspector")

# Corridor Selector Dropdown
corridor_options = df_sel_benefits["corridor_id"].tolist()
corridor_labels = {
    row["corridor_id"]: f"{row['corridor_id']} - {row['corridor_name']} ({row['treatment_name']})"
    for idx, row in df_sel_benefits.iterrows()
}
selected_cid = st.selectbox(
    "Select Corridor to Inspect",
    options=corridor_options,
    format_func=lambda cid: corridor_labels[cid],
)

# Extract single corridor record
c_row = df_sel_benefits[df_sel_benefits["corridor_id"] == selected_cid].iloc[0]
m_row = df_master[df_master["corridor_id"] == selected_cid].iloc[0]

ic1, ic2, ic3 = st.columns(3)
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
    st.markdown(f"**Annual Crashes Averted:** {c_row['crashes_averted_total']:.2f} / yr (K: {c_row['crashes_averted_k']:.2f}, A: {c_row['crashes_averted_a']:.2f})")
    st.markdown(f"**Physical Applicability:** `:orange[{c_row['physical_applicability_status']} - Review Required]`")

st.markdown("---")
st.subheader("Selected Projects Detail Table & Export")

df_export = df_sel_benefits[[
    "portfolio_id",
    "corridor_id",
    "corridor_name",
    "treatment_id",
    "treatment_name",
    "uncertainty_scenario",
    "capital_project_cost",
    "crashes_averted_total",
    "crashes_averted_k",
    "crashes_averted_a",
    "equity_area_flag",
    "physical_applicability_status",
]].copy()

st.dataframe(
    df_export.style.format({
        "capital_project_cost": "${:,.0f}",
        "crashes_averted_total": "{:,.2f}",
        "crashes_averted_k": "{:,.2f}",
        "crashes_averted_a": "{:,.2f}",
    }),
    use_container_width=True,
    height=300,
)

# Download CSV button for CURRENTLY selected portfolio only
csv_bytes = df_export.to_csv(index=False).encode("utf-8")
st.download_button(
    label=f"Download CSV for Active Portfolio ({portfolio_id})",
    data=csv_bytes,
    file_name=f"vision_zero_portfolio_selections_{portfolio_id}.csv",
    mime="text/csv",
)
