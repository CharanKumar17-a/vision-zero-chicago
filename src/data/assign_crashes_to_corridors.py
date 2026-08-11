"""Spatial-indexed crash-to-corridor candidate generation.

Contract: docs/data_quality/spatial_assignment_contract.md
Config:   config/spatial.yml

Core optimization:
Uses Shapely STRtree spatial indexing with predicate='dwithin' to query candidate
corridors in O(N log M) time instead of full N x M distance matrix generation.

Candidate output columns:
crash_record_id, corridor_id, distance_feet, candidate_rank, candidate_count, is_ambiguous, is_tie.

Deterministic ordering:
distance_feet ascending, corridor_id ascending.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
import yaml
from pyproj import CRS
from shapely.strtree import STRtree

ROOT = Path(__file__).resolve().parents[2]

SOURCE_CRS: str = "EPSG:4326"
ANALYSIS_CRS: str = "EPSG:3435"
DEFAULT_TIE_TOLERANCE_FEET: float = 10.0

CRASH_COLUMNS = [
    "crash_record_id",
    "has_valid_coordinates",
    "latitude",
    "longitude",
    "crash_month_start",
    "severity_kabco",
]


def load_spatial_config(config_path: Optional[Path] = None) -> dict:
    """Load config/spatial.yml."""
    if config_path is None:
        config_path = ROOT / "config" / "spatial.yml"
    with config_path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_eligible_crashes(
    crashes_path: Path,
    source_crs: str = SOURCE_CRS,
    analysis_crs: str = ANALYSIS_CRS,
    sample_size: Optional[int] = None,
) -> tuple[pd.DataFrame, gpd.GeoDataFrame, bool]:
    """Load crash core; return all crashes, eligible spatial GeoDataFrame, and sample flag.

    Parameters
    ----------
    crashes_path:
        Path to crashes_clean.parquet.
    source_crs:
        CRS of lat/lon input (EPSG:4326).
    analysis_crs:
        Target analysis CRS (EPSG:3435).
    sample_size:
        If set, limits eligible crashes to the first N valid-coordinate records.

    Returns
    -------
    all_crashes : pd.DataFrame
        Full crash dataframe loaded from parquet.
    eligible_gdf : gpd.GeoDataFrame
        Valid-coordinate crashes reprojected to analysis_crs (EPSG:3435).
    is_sample : bool
        True if sample_size was applied, False otherwise.
    """
    all_crashes = pd.read_parquet(crashes_path, columns=CRASH_COLUMNS)
    eligible = all_crashes[all_crashes["has_valid_coordinates"]].copy()

    is_sample = False
    if sample_size is not None and len(eligible) > sample_size:
        eligible = eligible.iloc[:sample_size].copy()
        is_sample = True

    geometry = gpd.points_from_xy(eligible["longitude"], eligible["latitude"])
    eligible_gdf = gpd.GeoDataFrame(eligible, geometry=geometry, crs=source_crs)
    eligible_gdf = eligible_gdf.to_crs(analysis_crs)

    return all_crashes, eligible_gdf, is_sample


def load_corridor_geometries(
    corridors_path: Path,
    expected_crs: str = ANALYSIS_CRS,
) -> gpd.GeoDataFrame:
    """Load corridor GeoParquet and verify CRS is EPSG:3435."""
    gdf = gpd.read_parquet(corridors_path)
    if not CRS(gdf.crs).equals(CRS(expected_crs)):
        raise ValueError(
            f"Corridor CRS {gdf.crs} does not match required {expected_crs}. "
            "Contract: reproject_before_distance_calculation."
        )
    return gdf


def generate_candidates_spatial_index(
    crashes_gdf: gpd.GeoDataFrame,
    corridors_gdf: gpd.GeoDataFrame,
    max_threshold_feet: float = 200.0,
    tie_tolerance_feet: float = DEFAULT_TIE_TOLERANCE_FEET,
) -> pd.DataFrame:
    """Generate spatial candidate matches within max_threshold_feet using STRtree indexing.

    Deterministic rank and ordering:
    Sort by (crash_record_id, distance_feet, corridor_id).

    Parameters
    ----------
    crashes_gdf:
        Point GeoDataFrame of crashes in EPSG:3435.
    corridors_gdf:
        Line/MultiLine GeoDataFrame of corridors in EPSG:3435.
    max_threshold_feet:
        Maximum bounding distance to search for candidate matches.
    tie_tolerance_feet:
        Distance difference for tie detection between rank 1 and rank 2.

    Returns
    -------
    pd.DataFrame
        Candidate table with columns:
        crash_record_id, corridor_id, distance_feet, candidate_rank,
        candidate_count, is_ambiguous, is_tie.
    """
    for label, gdf in [("Crashes", crashes_gdf), ("Corridors", corridors_gdf)]:
        if not CRS(gdf.crs).equals(CRS(ANALYSIS_CRS)):
            raise ValueError(
                f"{label} CRS {gdf.crs} must be {ANALYSIS_CRS} for distance computation."
            )

    empty_result = pd.DataFrame(
        columns=[
            "crash_record_id",
            "corridor_id",
            "distance_feet",
            "candidate_rank",
            "candidate_count",
            "is_ambiguous",
            "is_tie",
        ]
    )

    if crashes_gdf.empty or corridors_gdf.empty:
        return empty_result

    corridor_geoms = corridors_gdf.geometry.to_numpy()
    corridor_ids = corridors_gdf["corridor_id"].to_numpy()

    crash_geoms = crashes_gdf.geometry.to_numpy()
    crash_ids = crashes_gdf["crash_record_id"].to_numpy()

    # STRtree query with dwithin predicate
    tree = STRtree(corridor_geoms)
    crash_indices, corridor_indices = tree.query(
        crash_geoms, predicate="dwithin", distance=max_threshold_feet
    )

    if len(crash_indices) == 0:
        return empty_result

    # Exact point-to-linestring distance calculation
    distances = shapely.distance(
        crash_geoms[crash_indices], corridor_geoms[corridor_indices]
    )

    candidates = pd.DataFrame(
        {
            "crash_record_id": crash_ids[crash_indices],
            "corridor_id": corridor_ids[corridor_indices],
            "distance_feet": distances,
        }
    )

    # Filter candidates strictly <= max_threshold_feet and >= 0.0
    candidates = candidates[
        (candidates["distance_feet"] >= 0.0)
        & (candidates["distance_feet"] <= max_threshold_feet)
    ].copy()

    if candidates.empty:
        return empty_result

    # Deterministic sort: crash_record_id, distance_feet, corridor_id
    candidates = candidates.sort_values(
        by=["crash_record_id", "distance_feet", "corridor_id"],
        ascending=[True, True, True],
    ).reset_index(drop=True)

    # Candidate ranking and ambiguity flags
    candidates["candidate_rank"] = (
        candidates.groupby("crash_record_id")["distance_feet"]
        .rank(method="first")
        .astype(int)
    )
    candidates["candidate_count"] = candidates.groupby("crash_record_id")[
        "crash_record_id"
    ].transform("count")
    candidates["is_ambiguous"] = candidates["candidate_count"] > 1

    # Tie detection: d(rank2) - d(rank1) <= tie_tolerance_feet
    rank1 = candidates[candidates["candidate_rank"] == 1][
        ["crash_record_id", "distance_feet"]
    ].rename(columns={"distance_feet": "d_rank1"})
    rank2 = candidates[candidates["candidate_rank"] == 2][
        ["crash_record_id", "distance_feet"]
    ].rename(columns={"distance_feet": "d_rank2"})

    tie_info = rank1.merge(rank2, on="crash_record_id", how="left")
    tie_info["is_crash_tie"] = (
        (tie_info["d_rank2"] - tie_info["d_rank1"]).fillna(float("inf"))
        <= tie_tolerance_feet
    )
    tie_crash_ids: set[str] = set(
        tie_info.loc[tie_info["is_crash_tie"], "crash_record_id"]
    )
    candidates["is_tie"] = candidates["crash_record_id"].isin(tie_crash_ids)

    return candidates.reset_index(drop=True)
