"""Data access, manifest validation, and filtering layer for Vision Zero Chicago Streamlit decision support app.

Contract: docs/data_quality/decision_output_mart_contract.md
Decision: D001, D004, D005, D019, D022 (Public deployment snapshot approval)

Supports three explicit data modes controlled by VISION_ZERO_DATA_MODE environment variable:
- 'auto' (default): Uses governed local Parquet if present, falls back to CSV snapshot.
- 'local': Requires governed local Parquet files; fails if missing.
- 'deployment': Requires bundled deployment CSV snapshot; never reads data/processed or data/interim.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]

SUMMARY_PATH = ROOT / "data" / "processed" / "power_bi_portfolio_summary.parquet"
SELECTIONS_PATH = ROOT / "data" / "processed" / "power_bi_project_selections.parquet"
MASTER_PATH = ROOT / "data" / "processed" / "power_bi_corridor_master.parquet"
BENEFITS_PATH = ROOT / "data" / "processed" / "power_bi_treatment_benefits.parquet"
CORRIDORS_GEO_PATH = ROOT / "data" / "interim" / "high_crash_corridors.parquet"

DEPLOYMENT_DIR = ROOT / "dashboard" / "streamlit" / "deployment_data"
MANIFEST_PATH = DEPLOYMENT_DIR / "deployment_manifest.json"

GEOMETRY_VAL_PATH = ROOT / "docs" / "data_quality" / "corridor_geometry_validation.json"
DECISION_MART_VAL_PATH = ROOT / "docs" / "data_quality" / "decision_output_mart_validation.json"
OPTIMIZATION_VAL_PATH = ROOT / "docs" / "data_quality" / "portfolio_optimization_validation.json"

DEFAULT_PORTFOLIO_ID = "PORT_OFF_BASE_B15M_EQ20"


def get_data_mode() -> str:
    """Get active data mode: 'auto' (default), 'local', or 'deployment'."""
    mode = os.environ.get("VISION_ZERO_DATA_MODE", "").strip().lower()
    if not mode:
        if os.environ.get("FORCE_DEPLOYMENT_MODE") == "1":
            return "deployment"
        return "auto"
    if mode in ("auto", "local", "deployment"):
        return mode
    raise ValueError(
        f"Invalid VISION_ZERO_DATA_MODE '{mode}'. Must be 'auto', 'local', or 'deployment'."
    )


def is_cloud_deployment_mode() -> bool:
    """Check if data access is operating in deployment mode."""
    mode = get_data_mode()
    if mode == "deployment":
        return True
    if mode == "local":
        return False
    # auto mode: fallback to deployment if local parquet missing
    return not (
        SUMMARY_PATH.exists()
        and SELECTIONS_PATH.exists()
        and MASTER_PATH.exists()
        and BENEFITS_PATH.exists()
        and CORRIDORS_GEO_PATH.exists()
    )


def compute_file_sha256(filepath: Path) -> str:
    """Compute SHA-256 checksum of a target file, canonicalizing CRLF to LF for CSV files."""
    data = filepath.read_bytes()
    if filepath.suffix.lower() == ".csv":
        data = data.replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def verify_and_load_deployment_file(
    filename: str,
    manifest_path: Path = MANIFEST_PATH,
) -> pd.DataFrame:
    """Verify manifest integrity, checksum, row count, and required columns, then load CSV."""
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"Deployment manifest missing at '{manifest_path}'. "
            "Please run 'python src/data/build_deployment_data.py' to generate public deployment snapshot files."
        )

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    if filename not in manifest.get("files", {}):
        raise ValueError(f"File '{filename}' not declared in deployment manifest.")

    file_meta = manifest["files"][filename]
    filepath = DEPLOYMENT_DIR / filename

    if not filepath.exists():
        raise FileNotFoundError(f"Deployment snapshot file missing: '{filepath.name}'.")

    # 1. SHA-256 Checksum Verification
    actual_checksum = compute_file_sha256(filepath)
    expected_checksum = file_meta["sha256_checksum"]
    if actual_checksum != expected_checksum:
        raise ValueError(
            f"SHA-256 checksum verification failed for '{filename}'. "
            f"Expected {expected_checksum[:12]}..., got {actual_checksum[:12]}... (Corrupted snapshot rejected)."
        )

    # 2. Load CSV
    df = pd.read_csv(filepath)

    # 3. Row Count Verification
    actual_rows = len(df)
    expected_rows = file_meta["row_count"]
    if actual_rows != expected_rows:
        raise ValueError(
            f"Row count mismatch for '{filename}'. Expected {expected_rows}, got {actual_rows}."
        )

    # 4. Required Columns Verification
    missing_cols = [c for c in file_meta["columns"] if c not in df.columns]
    if missing_cols:
        raise ValueError(f"Required columns missing in '{filename}': {missing_cols}")

    return df


@st.cache_data(show_spinner=False)
def load_portfolio_summary(path: Path = SUMMARY_PATH) -> pd.DataFrame:
    """Load portfolio summary mart dataset from Parquet or deployment CSV fallback."""
    mode = get_data_mode()

    if mode == "local":
        if not path.exists():
            raise FileNotFoundError(
                f"Required local Parquet dataset missing: '{path.name}' in local mode."
            )
        return pd.read_parquet(path)

    if mode == "deployment":
        return verify_and_load_deployment_file("portfolio_summary.csv")

    # auto mode
    if path.exists() and not is_cloud_deployment_mode():
        return pd.read_parquet(path)
    if not path.exists() and path != SUMMARY_PATH:
        raise FileNotFoundError(f"Required serving dataset missing: '{path.name}'.")
    return verify_and_load_deployment_file("portfolio_summary.csv")


@st.cache_data(show_spinner=False)
def load_project_selections(path: Path = SELECTIONS_PATH) -> pd.DataFrame:
    """Load project selections detail mart dataset from Parquet or deployment CSV fallback."""
    mode = get_data_mode()

    if mode == "local":
        if not path.exists():
            raise FileNotFoundError(
                f"Required local Parquet dataset missing: '{path.name}' in local mode."
            )
        return pd.read_parquet(path)

    if mode == "deployment":
        return verify_and_load_deployment_file("project_selections.csv")

    # auto mode
    if path.exists() and not is_cloud_deployment_mode():
        return pd.read_parquet(path)
    if not path.exists() and path != SELECTIONS_PATH:
        raise FileNotFoundError(f"Required serving dataset missing: '{path.name}'.")
    return verify_and_load_deployment_file("project_selections.csv")


@st.cache_data(show_spinner=False)
def load_corridor_master(path: Path = MASTER_PATH) -> pd.DataFrame:
    """Load corridor master dimension register dataset from Parquet or deployment CSV fallback."""
    mode = get_data_mode()

    if mode == "local":
        if not path.exists():
            raise FileNotFoundError(
                f"Required local Parquet dataset missing: '{path.name}' in local mode."
            )
        return pd.read_parquet(path)

    if mode == "deployment":
        return verify_and_load_deployment_file("corridor_master.csv")

    # auto mode
    if path.exists() and not is_cloud_deployment_mode():
        return pd.read_parquet(path)
    if not path.exists() and path != MASTER_PATH:
        raise FileNotFoundError(f"Required serving dataset missing: '{path.name}'.")
    return verify_and_load_deployment_file("corridor_master.csv")


@st.cache_data(show_spinner=False)
def load_treatment_benefits(path: Path = BENEFITS_PATH) -> pd.DataFrame:
    """Load candidate treatment benefits panel dataset from Parquet or deployment CSV fallback."""
    mode = get_data_mode()

    if mode == "local":
        if not path.exists():
            raise FileNotFoundError(
                f"Required local Parquet dataset missing: '{path.name}' in local mode."
            )
        return pd.read_parquet(path)

    if mode == "deployment":
        return verify_and_load_deployment_file("treatment_benefits.csv")

    # auto mode
    if path.exists() and not is_cloud_deployment_mode():
        return pd.read_parquet(path)
    if not path.exists() and path != BENEFITS_PATH:
        raise FileNotFoundError(f"Required serving dataset missing: '{path.name}'.")
    return verify_and_load_deployment_file("treatment_benefits.csv")


@st.cache_data(show_spinner=False)
def load_corridor_geodataframe(path: Path = CORRIDORS_GEO_PATH) -> Any:
    """Load spatial linework geometry and re-project to EPSG:4326 WGS84 for mapping."""
    import geopandas as gpd
    from shapely.wkt import loads

    mode = get_data_mode()

    if mode == "local":
        if not path.exists():
            raise FileNotFoundError(f"Required spatial source missing: '{path.name}' in local mode.")
        gdf = gpd.read_parquet(path)
        centroids_3435 = gdf.geometry.centroid
        centroids_4326 = centroids_3435.to_crs(epsg=4326)
        gdf_4326 = gdf.to_crs(epsg=4326)
        gdf_4326["centroid_latitude"] = centroids_4326.y
        gdf_4326["centroid_longitude"] = centroids_4326.x
        return gdf_4326

    if mode == "deployment":
        df_mas = verify_and_load_deployment_file("corridor_master.csv")
        if "geometry_wkt" not in df_mas.columns:
            raise ValueError("Deployment corridor_master.csv missing required 'geometry_wkt' spatial linework column.")
        geometry = df_mas["geometry_wkt"].apply(loads)
        return gpd.GeoDataFrame(df_mas, geometry=geometry, crs="EPSG:4326")

    # auto mode
    if path.exists() and not is_cloud_deployment_mode():
        gdf = gpd.read_parquet(path)
        centroids_3435 = gdf.geometry.centroid
        centroids_4326 = centroids_3435.to_crs(epsg=4326)
        gdf_4326 = gdf.to_crs(epsg=4326)
        gdf_4326["centroid_latitude"] = centroids_4326.y
        gdf_4326["centroid_longitude"] = centroids_4326.x
        return gdf_4326

    if not path.exists() and path != CORRIDORS_GEO_PATH:
        raise FileNotFoundError(f"Required spatial source missing: '{path.name}'.")

    df_mas = verify_and_load_deployment_file("corridor_master.csv")
    if "geometry_wkt" not in df_mas.columns:
        raise ValueError("Deployment corridor_master.csv missing required 'geometry_wkt' spatial linework column.")
    geometry = df_mas["geometry_wkt"].apply(loads)
    return gpd.GeoDataFrame(df_mas, geometry=geometry, crs="EPSG:4326")


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

    if MANIFEST_PATH.exists():
        with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
            evidence["deployment_manifest"] = json.load(f)
    else:
        evidence["deployment_manifest"] = {}

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
    df_merged["crashes_averted_ksi"] = df_merged["crashes_averted_k"] + df_merged["crashes_averted_a"]
    return df_merged



def get_selected_corridors_geodataframe(
    df_selections: pd.DataFrame,
    gdf_corridors: Any,
    portfolio_id: str,
) -> Any:
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


# FHWA 2025 Economic-Only Crash Cost Benchmarks (FHWA safety factsheet 2025: direct tangible costs only)
# Reference: K (Fatal) = $1.61M, A (Incapacitating) = $172K, B (Non-incapacitating) = $44K, C (Possible) = $26K, O (PDO) = $6.3K
ECONOMIC_ONLY_CRASH_COSTS: Dict[str, float] = {
    "K": 1610000.0,
    "A": 172000.0,
    "B": 44000.0,
    "C": 26000.0,
    "O": 6300.0,
}


def compute_economic_only_benefits(
    df_benefits: pd.DataFrame,
    discount_rate: float = 0.03,
    useful_life_years: int = 20,
) -> pd.DataFrame:
    """Compute annual and present-value economic-only benefits and BCR using FHWA 2025 economic-only crash costs.

    Direct tangible costs only (medical, emergency services, wage loss, property damage) without quality-of-life additions.
    Source: FHWA 2025 Economic Cost Guidelines.
    """
    df = df_benefits.copy()
    annual_econ = (
        df["crashes_averted_k"] * ECONOMIC_ONLY_CRASH_COSTS["K"]
        + df["crashes_averted_a"] * ECONOMIC_ONLY_CRASH_COSTS["A"]
        + df["crashes_averted_b"] * ECONOMIC_ONLY_CRASH_COSTS["B"]
        + df["crashes_averted_c"] * ECONOMIC_ONLY_CRASH_COSTS["C"]
        + df["crashes_averted_o"] * ECONOMIC_ONLY_CRASH_COSTS["O"]
    )

    if "present_value_factor" in df.columns:
        pv_factor = df["present_value_factor"]
    else:
        pv_factor = (1.0 - (1.0 + discount_rate) ** (-useful_life_years)) / discount_rate

    df["annual_economic_benefit"] = annual_econ
    df["pv_economic_benefit"] = annual_econ * pv_factor
    df["bcr_economic_only"] = df["pv_economic_benefit"] / df["capital_project_cost"].replace(0, float("nan"))
    return df


def find_what_if_grid_portfolio(
    df_summary: pd.DataFrame,
    budget_usd: float,
    equity_floor: float,
    uncertainty_scenario: str = "BASE",
) -> Tuple[pd.Series, bool]:
    """Find the exact or nearest precomputed What-If Planner grid portfolio.

    Returns:
        Tuple of (portfolio_summary_series, is_exact_match_bool)
    """
    df_grid = df_summary[df_summary["run_group"] == "WHAT-IF PLANNER GRID"]
    if df_grid.empty:
        df_grid = df_summary

    df_scen = df_grid[df_grid["uncertainty_scenario"] == uncertainty_scenario]
    if df_scen.empty:
        df_scen = df_grid

    # 1. Exact match within tolerance
    exact_match = df_scen[
        (df_scen["budget_usd"].sub(budget_usd).abs() < 1.0)
        & (df_scen["equity_floor"].sub(equity_floor).abs() < 1e-3)
    ]
    if not exact_match.empty:
        return exact_match.iloc[0], True

    # 2. Nearest match by |budget - selected| then |floor - selected|
    df_scored = df_scen.copy()
    df_scored["budget_diff"] = df_scored["budget_usd"].sub(budget_usd).abs()
    df_scored["floor_diff"] = df_scored["equity_floor"].sub(equity_floor).abs()
    df_sorted = df_scored.sort_values(by=["budget_diff", "floor_diff"])
    return df_sorted.iloc[0], False
