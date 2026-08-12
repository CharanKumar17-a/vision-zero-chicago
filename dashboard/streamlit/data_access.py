"""Data access and filtering layer for Vision Zero Chicago Streamlit decision support app.

Contract: docs/data_quality/decision_output_mart_contract.md
Decision: D001, D004, D005, D019

Loads serving datasets from data/processed/, spatial geometry from data/interim/,
and validation evidence from docs/data_quality/. Guarantees strict single-portfolio filtering.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import geopandas as gpd
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]

SUMMARY_PATH = ROOT / "data" / "processed" / "power_bi_portfolio_summary.parquet"
SELECTIONS_PATH = ROOT / "data" / "processed" / "power_bi_project_selections.parquet"
MASTER_PATH = ROOT / "data" / "processed" / "power_bi_corridor_master.parquet"
BENEFITS_PATH = ROOT / "data" / "processed" / "power_bi_treatment_benefits.parquet"
CORRIDORS_GEO_PATH = ROOT / "data" / "interim" / "high_crash_corridors.parquet"

GEOMETRY_VAL_PATH = ROOT / "docs" / "data_quality" / "corridor_geometry_validation.json"
DECISION_MART_VAL_PATH = ROOT / "docs" / "data_quality" / "decision_output_mart_validation.json"
OPTIMIZATION_VAL_PATH = ROOT / "docs" / "data_quality" / "portfolio_optimization_validation.json"

DEFAULT_PORTFOLIO_ID = "PORT_OFF_BASE_B15M_EQ20"


@st.cache_data(show_spinner=False)
def load_portfolio_summary(path: Path = SUMMARY_PATH) -> pd.DataFrame:
    """Load portfolio summary mart dataset with cached performance."""
    if not path.exists():
        raise FileNotFoundError(
            f"Required serving dataset missing: '{path.name}'. "
            "Please run 'python src/data/build_decision_output_mart.py' to generate decision mart files."
        )
    return pd.read_parquet(path)


@st.cache_data(show_spinner=False)
def load_project_selections(path: Path = SELECTIONS_PATH) -> pd.DataFrame:
    """Load project selections detail mart dataset with cached performance."""
    if not path.exists():
        raise FileNotFoundError(
            f"Required serving dataset missing: '{path.name}'. "
            "Please run 'python src/data/build_decision_output_mart.py' to generate decision mart files."
        )
    return pd.read_parquet(path)


@st.cache_data(show_spinner=False)
def load_corridor_master(path: Path = MASTER_PATH) -> pd.DataFrame:
    """Load corridor master dimension register dataset."""
    if not path.exists():
        raise FileNotFoundError(
            f"Required serving dataset missing: '{path.name}'. "
            "Please run 'python src/data/build_decision_output_mart.py' to generate decision mart files."
        )
    return pd.read_parquet(path)


@st.cache_data(show_spinner=False)
def load_treatment_benefits(path: Path = BENEFITS_PATH) -> pd.DataFrame:
    """Load candidate treatment benefits panel dataset."""
    if not path.exists():
        raise FileNotFoundError(
            f"Required serving dataset missing: '{path.name}'. "
            "Please run 'python src/data/build_decision_output_mart.py' to generate decision mart files."
        )
    return pd.read_parquet(path)


@st.cache_data(show_spinner=False)
def load_corridor_geodataframe(path: Path = CORRIDORS_GEO_PATH) -> gpd.GeoDataFrame:
    """Load spatial linework geometry and re-project to EPSG:4326 WGS84 for mapping."""
    if not path.exists():
        raise FileNotFoundError(f"Required spatial source missing: '{path.name}'.")
    gdf = gpd.read_parquet(path)

    # Calculate accurate centroid in EPSG:3435 projected CRS before converting
    centroids_3435 = gdf.geometry.centroid
    centroids_4326 = centroids_3435.to_crs(epsg=4326)

    gdf_4326 = gdf.to_crs(epsg=4326)
    gdf_4326["centroid_latitude"] = centroids_4326.y
    gdf_4326["centroid_longitude"] = centroids_4326.x
    return gdf_4326


@st.cache_data(show_spinner=False)
def load_validation_evidence() -> Dict[str, Any]:
    """Load committed validation JSON reports dynamically."""
    evidence = {}
    if GEOMETRY_VAL_PATH.exists():
        with open(GEOMETRY_VAL_PATH, "r", encoding="utf-8") as f:
            evidence["geometry"] = json.load(f)
    else:
        evidence["geometry"] = {}

    if DECISION_MART_VAL_PATH.exists():
        with open(DECISION_MART_VAL_PATH, "r", encoding="utf-8") as f:
            evidence["decision_mart"] = json.load(f)
    else:
        evidence["decision_mart"] = {}

    if OPTIMIZATION_VAL_PATH.exists():
        with open(OPTIMIZATION_VAL_PATH, "r", encoding="utf-8") as f:
            evidence["optimization"] = json.load(f)
    else:
        evidence["optimization"] = {}

    return evidence


def get_single_portfolio_summary(df_summary: pd.DataFrame, portfolio_id: str) -> pd.Series:
    """Extract summary row for exactly one portfolio_id."""
    df_match = df_summary[df_summary["portfolio_id"] == portfolio_id]
    if df_match.empty:
        raise ValueError(f"Portfolio ID '{portfolio_id}' not found in summary mart.")
    return df_match.iloc[0]


def get_single_portfolio_selections(df_selections: pd.DataFrame, portfolio_id: str) -> pd.DataFrame:
    """Extract detail project selection rows for exactly one portfolio_id."""
    df_sub = df_selections[df_selections["portfolio_id"] == portfolio_id].copy()
    if df_sub.empty:
        raise ValueError(f"Portfolio ID '{portfolio_id}' not found in project selections detail mart.")
    return df_sub


def get_selected_portfolio_benefits(
    df_selections: pd.DataFrame,
    df_benefits: pd.DataFrame,
    portfolio_id: str,
) -> pd.DataFrame:
    """Join single-portfolio project selections to treatment benefits panel to get averted crashes."""
    df_sel = get_single_portfolio_selections(df_selections, portfolio_id)

    # Merge with benefits panel on corridor_id, treatment_id, uncertainty_scenario
    df_merged = pd.merge(
        df_sel,
        df_benefits[[
            "corridor_id",
            "treatment_id",
            "uncertainty_scenario",
            "crashes_averted_total",
            "crashes_averted_k",
            "crashes_averted_a",
            "crashes_averted_b",
            "crashes_averted_c",
            "crashes_averted_o",
            "annual_monetary_benefit",
            "useful_life_years",
        ]],
        on=["corridor_id", "treatment_id", "uncertainty_scenario"],
        how="left",
    )
    if len(df_merged) != len(df_sel):
        raise ValueError(f"Join expansion detected during benefit panel merge for '{portfolio_id}'.")
    return df_merged


def get_selected_corridors_geodataframe(
    df_selections: pd.DataFrame,
    gdf_corridors: gpd.GeoDataFrame,
    portfolio_id: str,
) -> gpd.GeoDataFrame:
    """Filter spatial linework to selected corridors for exactly one portfolio_id without row expansion."""
    df_sel = get_single_portfolio_selections(df_selections, portfolio_id)
    selected_corridors = df_sel["corridor_id"].unique()

    gdf_selected = gdf_corridors[gdf_corridors["corridor_id"].isin(selected_corridors)].copy()

    # Merge selection metadata
    gdf_merged = gdf_selected.merge(
        df_sel[["corridor_id", "treatment_name", "capital_project_cost", "equity_area_flag", "selected_rank_by_benefit"]],
        on="corridor_id",
        how="inner",
    )
    if len(gdf_merged) != len(df_sel):
        raise ValueError(f"Row count mismatch when creating spatial GeoDataFrame for '{portfolio_id}'.")
    return gdf_merged
