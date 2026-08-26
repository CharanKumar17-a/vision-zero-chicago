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
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.optimization.optimize_portfolios import compute_portfolio_hash, solve_single_milp


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
SPATIAL_SENSITIVITY_VAL_PATH = ROOT / "docs" / "data_quality" / "spatial_sensitivity_report.json"

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

    if SPATIAL_SENSITIVITY_VAL_PATH.exists():
        with open(SPATIAL_SENSITIVITY_VAL_PATH, "r", encoding="utf-8") as f:
            evidence["spatial_sensitivity"] = json.load(f)
    else:
        evidence["spatial_sensitivity"] = {}

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


def get_dynamic_corridors_geodataframe(
    df_selected: pd.DataFrame,
    gdf_corridors: Any,
) -> Any:
    """Filter spatial linework to selected corridors for dynamic scenario results without row expansion."""
    if df_selected.empty:
        return gdf_corridors.iloc[0:0].copy()
    selected_corridors = df_selected["corridor_id"].unique()
    gdf_selected = gdf_corridors[gdf_corridors["corridor_id"].isin(selected_corridors)].copy()
    gdf_merged = gdf_selected.merge(
        df_selected[["corridor_id", "treatment_name", "capital_project_cost", "equity_area_flag", "selected_rank_by_benefit"]],
        on="corridor_id",
        how="inner",
    )
    return gdf_merged


def evaluate_portfolio_scenario(
    budget: float,
    equity_floor: float,
    cost_case: str = "BASE",
    cmf_case: str = "BASE",
    df_benefits: Optional[pd.DataFrame] = None,
) -> Tuple[pd.Series, pd.DataFrame]:
    """Execute dynamic MILP portfolio optimization over frozen candidate benefits and costs.

    Performs fresh solve on every invocation (cache-free) ensuring 0 stale state risk:
    1. Normalizes cost_case ('LOW', 'BASE', 'HIGH') and cmf_case ('CONSERVATIVE', 'BASE', 'OPTIMISTIC').
    2. Builds candidate panel from frozen authoritative data.
    3. Screens physical applicability (NOT_APPLICABLE excluded) and BCR eligibility (BCR >= 1.0 per D023).
    4. Executes scipy.optimize.milp with 1-treatment-per-corridor, budget, equity floor, and 70% Road Diet cap (D026).
    5. Returns fully reconciled summary Series and selected projects DataFrame.
    """
    if df_benefits is None:
        df_benefits = load_treatment_benefits()

    c_upper = str(cost_case).strip().upper()
    if c_upper in ("LOW", "CONSERVATIVE", "MINIMAL"):
        cost_level = "CONSERVATIVE"
    elif c_upper in ("HIGH", "OPTIMISTIC", "COMPREHENSIVE"):
        cost_level = "OPTIMISTIC"
    else:
        cost_level = "BASE"

    m_upper = str(cmf_case).strip().upper()
    if m_upper in ("LOW", "CONSERVATIVE"):
        cmf_level = "CONSERVATIVE"
    elif m_upper in ("HIGH", "OPTIMISTIC"):
        cmf_level = "OPTIMISTIC"
    else:
        cmf_level = "BASE"

    if cmf_level == cost_level:
        df_scen = df_benefits[df_benefits["uncertainty_scenario"] == cmf_level].copy().reset_index(drop=True)
    else:
        df_cmf = df_benefits[df_benefits["uncertainty_scenario"] == cmf_level].copy()
        df_cost = df_benefits[df_benefits["uncertainty_scenario"] == cost_level].copy()
        df_scen = pd.merge(
            df_cmf.drop(columns=["capital_project_cost", "net_present_benefit", "benefit_cost_ratio"], errors="ignore"),
            df_cost[["corridor_id", "treatment_id", "capital_project_cost"]],
            on=["corridor_id", "treatment_id"],
            how="inner",
        )
        df_scen["net_present_benefit"] = df_scen["present_value_benefit"] - df_scen["capital_project_cost"]
        df_scen["benefit_cost_ratio"] = df_scen["present_value_benefit"] / df_scen["capital_project_cost"].replace(0, float("nan"))

    # Applicability screening
    if "physical_applicability_status" in df_scen.columns:
        df_scen = df_scen[df_scen["physical_applicability_status"] != "NOT_APPLICABLE"].reset_index(drop=True)

    # Candidate BCR >= 1.0 eligibility filter (Decision D023)
    df_scen = df_scen[df_scen["benefit_cost_ratio"] >= 1.0].reset_index(drop=True)

    c = -df_scen["present_value_benefit"].values
    costs = df_scen["capital_project_cost"].values
    equity_flags = df_scen["equity_area_flag"].values.astype(float)
    treatment_ids = df_scen["treatment_id"].values
    corridors = df_scen["corridor_id"].values
    unique_corridors = sorted(list(set(corridors)))

    x, status_code, msg = solve_single_milp(
        c=c,
        costs=costs,
        equity_flags=equity_flags,
        treatment_ids=treatment_ids,
        corridors=corridors,
        unique_corridors=unique_corridors,
        budget=budget,
        equity_floor=equity_floor,
    )

    solver_status = "OPTIMAL" if status_code == 0 else f"STATUS_{status_code}"

    b_m = int(budget / 1e6) if budget >= 1e6 else int(budget / 1e3)
    b_label = f"{b_m}M" if budget >= 1e6 else f"{b_m}k"
    eq_pct = int(round(equity_floor * 100))

    if status_code != 0:
        summary = pd.Series({
            "portfolio_id": f"PORT_INFEASIBLE_B{b_label}_EQ{eq_pct}",
            "run_group": "DYNAMIC",
            "uncertainty_scenario": cmf_level,
            "cost_case": cost_level,
            "cmf_case": cmf_level,
            "budget": budget,
            "budget_usd": budget,
            "equity_floor": equity_floor,
            "solver_status": solver_status,
            "solver_message": msg,
            "selected_project_count": 0,
            "selected_corridor_count": 0,
            "selected_capital_cost": 0.0,
            "budget_slack": budget,
            "budget_utilization_pct": 0.0,
            "equity_spending": 0.0,
            "achieved_equity_share": 0.0,
            "total_present_value_benefit": 0.0,
            "total_net_present_benefit": 0.0,
            "portfolio_bcr": 0.0,
            "budget_constraint_status": "INFEASIBLE",
            "equity_constraint_status": "INFEASIBLE",
        })
        return summary, pd.DataFrame()

    selected_indices = np.where(x > 0.5)[0]
    df_selected = df_scen.iloc[selected_indices].copy()
    df_selected = df_selected.sort_values(by="present_value_benefit", ascending=False).reset_index(drop=True)
    df_selected["selected_rank_by_benefit"] = np.arange(1, len(df_selected) + 1, dtype=int)
    if "crashes_averted_ksi" not in df_selected.columns:
        df_selected["crashes_averted_ksi"] = df_selected["crashes_averted_k"] + df_selected["crashes_averted_a"]

    selected_project_count = len(df_selected)
    selected_corridor_count = df_selected["corridor_id"].nunique()
    selected_capital_cost = float(df_selected["capital_project_cost"].sum())
    budget_slack = float(budget - selected_capital_cost)
    budget_utilization_pct = float((selected_capital_cost / budget) * 100.0) if budget > 0 else 0.0

    eq_mask = df_selected["equity_area_flag"] == True
    equity_spending = float(df_selected[eq_mask]["capital_project_cost"].sum())
    achieved_equity_share = float(equity_spending / selected_capital_cost) if selected_capital_cost > 0 else 0.0

    total_present_value_benefit = float(df_selected["present_value_benefit"].sum())
    total_net_present_benefit = float(df_selected["net_present_benefit"].sum())
    portfolio_bcr = float(total_present_value_benefit / selected_capital_cost) if selected_capital_cost > 0 else 0.0

    sel_keys = [(r["corridor_id"], r["treatment_id"]) for _, r in df_selected.iterrows()]
    portfolio_hash = compute_portfolio_hash(sel_keys)

    # Determine constraint status
    unselected_corridors = set(unique_corridors) - set(df_selected["corridor_id"].unique())
    if len(unselected_corridors) == 0:
        budget_constraint_status = "NONBINDING_CORRIDOR_CEILING"
    else:
        unselected_df = df_scen[df_scen["corridor_id"].isin(unselected_corridors)]
        min_unselected_cost = float(unselected_df["capital_project_cost"].min()) if len(unselected_df) > 0 else 0.0
        if budget_slack < min_unselected_cost - 1e-6:
            budget_constraint_status = "EFFECTIVELY_BINDING_NO_ADDITIONAL_CORRIDOR"
        else:
            budget_constraint_status = "SLACK"

    if abs(achieved_equity_share - equity_floor) <= 1e-4:
        equity_constraint_status = "BINDING"
    else:
        equity_constraint_status = "SLACK"

    # Canonical portfolio ID mapping if matching official
    if cmf_level == cost_level and budget in [15e6, 25e6, 40e6] and equity_floor in [0.20, 0.30, 0.40]:
        portfolio_id = f"PORT_OFF_{cmf_level}_B{b_label}_EQ{eq_pct}"
        run_group = "OFFICIAL"
    elif cmf_level == cost_level and budget in [2e6, 4e6, 6e6] and equity_floor in [0.20, 0.30, 0.40]:
        portfolio_id = f"PORT_STR_{cmf_level}_B{b_label}_EQ{eq_pct}"
        run_group = "BINDING-BUDGET STRESS TEST"
    else:
        portfolio_id = f"PORT_DYN_{cmf_level[:3]}_{cost_level[:3]}_B{b_label}_EQ{eq_pct}"
        run_group = "DYNAMIC"

    df_selected["portfolio_id"] = portfolio_id
    df_selected["uncertainty_scenario"] = cmf_level

    summary = pd.Series({
        "portfolio_id": portfolio_id,
        "run_group": run_group,
        "uncertainty_scenario": cmf_level,
        "cost_case": cost_level,
        "cmf_case": cmf_level,
        "budget": budget,
        "budget_usd": budget,
        "equity_floor": equity_floor,
        "solver_status": solver_status,
        "solver_message": msg,
        "selected_project_count": selected_project_count,
        "selected_corridor_count": selected_corridor_count,
        "selected_capital_cost": selected_capital_cost,
        "budget_slack": budget_slack,
        "budget_utilization_pct": budget_utilization_pct,
        "equity_spending": equity_spending,
        "achieved_equity_share": achieved_equity_share,
        "total_present_value_benefit": total_present_value_benefit,
        "total_net_present_benefit": total_net_present_benefit,
        "portfolio_bcr": portfolio_bcr,
        "budget_constraint_status": budget_constraint_status,
        "equity_constraint_status": equity_constraint_status,
        "portfolio_hash": portfolio_hash,
    })

    return summary, df_selected


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


def compute_portfolio_stability(
    df_selections: pd.DataFrame,
    df_summary: pd.DataFrame,
    scenario_scope: str = "OFFICIAL",
) -> pd.DataFrame:
    """Calculate selection frequency and descriptive stability classification across scenarios.

    Grain: corridor_id × treatment_id.

    Args:
        df_selections: Project selections detail dataset.
        df_summary: Portfolio summary dataset.
        scenario_scope: Scenario group filter ('OFFICIAL', 'CANONICAL', or 'ALL').
            - 'OFFICIAL': 27 approved planning scenarios ($15M, $25M, $40M).
            - 'CANONICAL': 36 canonical scenarios (27 official + 9 diagnostic stress).
            - 'ALL': All 192 serving mart scenarios (including 156 What-If grid runs).

    Returns:
        pd.DataFrame containing:
        - corridor_id: Corridor identifier
        - corridor_name: Corridor street name
        - treatment_id: Treatment countermeasure ID
        - treatment_name: Countermeasure description
        - selected_scenario_count: Number of scenarios in which the project is funded
        - total_scenarios: Total count of scenarios in the evaluated scope
        - selection_rate: Proportion of scenarios selecting the project
        - selection_display: Formatted string 'Selected in X of Y scenarios'
        - stability_tier: Descriptive classification ('Core', 'Conditional', 'Scenario-sensitive')
        - equity_area_flag: High-SVI priority area boolean
        - capital_project_cost: Mean project cost across scenarios
    """
    scope_upper = str(scenario_scope).strip().upper()
    if scope_upper == "OFFICIAL":
        target_pids = df_summary[df_summary["run_group"] == "OFFICIAL"]["portfolio_id"].unique()
    elif scope_upper in ("CANONICAL", "CANONICAL_36"):
        target_pids = df_summary[
            df_summary["run_group"].isin(["OFFICIAL", "BINDING-BUDGET STRESS TEST"])
        ]["portfolio_id"].unique()
    elif scope_upper == "ALL":
        target_pids = df_summary["portfolio_id"].unique()
    else:
        matched = df_summary[df_summary["run_group"] == scenario_scope]
        if not matched.empty:
            target_pids = matched["portfolio_id"].unique()
        else:
            target_pids = df_summary[df_summary["run_group"] == "OFFICIAL"]["portfolio_id"].unique()

    total_scenarios = len(target_pids)
    if total_scenarios == 0:
        raise ValueError(f"No scenarios found for scope '{scenario_scope}'.")

    df_sub = df_selections[df_selections["portfolio_id"].isin(target_pids)]
    if df_sub.empty:
        return pd.DataFrame(columns=[
            "corridor_id",
            "corridor_name",
            "treatment_id",
            "treatment_name",
            "selected_scenario_count",
            "total_scenarios",
            "selection_rate",
            "selection_display",
            "stability_tier",
            "equity_area_flag",
            "capital_project_cost",
        ])

    df_agg = (
        df_sub.groupby(["corridor_id", "treatment_id"])
        .agg(
            corridor_name=("corridor_name", "first"),
            treatment_name=("treatment_name", "first"),
            selected_scenario_count=("portfolio_id", "nunique"),
            equity_area_flag=("equity_area_flag", "first"),
            capital_project_cost=("capital_project_cost", "mean"),
        )
        .reset_index()
    )

    df_agg["total_scenarios"] = total_scenarios
    df_agg["selection_rate"] = df_agg["selected_scenario_count"] / total_scenarios
    df_agg["selection_display"] = df_agg.apply(
        lambda r: f"Selected in {int(r['selected_scenario_count'])} of {int(r['total_scenarios'])} scenarios",
        axis=1,
    )

    def _classify_tier(rate: float) -> str:
        if rate >= 0.70:
            return "Core"
        elif rate >= 0.30:
            return "Conditional"
        return "Scenario-sensitive"

    df_agg["stability_tier"] = df_agg["selection_rate"].apply(_classify_tier)
    df_agg = df_agg.sort_values(
        by=["selection_rate", "selected_scenario_count", "capital_project_cost"],
        ascending=[False, False, True],
    ).reset_index(drop=True)

    return df_agg
