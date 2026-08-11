"""Tests for spatial-indexed crash-to-corridor candidate generation.

All tests use synthetic geometries created in memory.
No real parquet files are required for testing.
"""

from __future__ import annotations

import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from pyproj import CRS
from shapely.geometry import LineString, Point

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.assign_crashes_to_corridors import (
    ANALYSIS_CRS,
    SOURCE_CRS,
    generate_candidates_spatial_index,
    load_eligible_crashes,
)


def make_corridors(corridor_ids: list[str], lines: list[LineString], crs: str = ANALYSIS_CRS) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame({"corridor_id": corridor_ids, "geometry": lines}, crs=crs)


def make_crashes(crash_ids: list[str], points: list[Point], crs: str = ANALYSIS_CRS) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame({"crash_record_id": crash_ids, "geometry": points}, crs=crs)


class TestCrsGuard:
    def test_crashes_must_be_in_analysis_crs(self):
        corridors = make_corridors(["HCC001"], [LineString([(0, 0), (1000, 0)])])
        crashes_4326 = make_crashes(["C1"], [Point(-87.65, 41.85)], crs=SOURCE_CRS)
        with pytest.raises(ValueError, match="EPSG:3435"):
            generate_candidates_spatial_index(crashes_4326, corridors)

    def test_corridors_must_be_in_analysis_crs(self):
        corridors_4326 = make_corridors(["HCC001"], [LineString([(-87.65, 41.85), (-87.66, 41.86)])], crs=SOURCE_CRS)
        crashes = make_crashes(["C1"], [Point(0, 0)])
        with pytest.raises(ValueError, match="EPSG:3435"):
            generate_candidates_spatial_index(crashes, corridors_4326)


class TestSpatialIndexCandidates:
    def test_candidate_generation_with_strtree(self):
        line = LineString([(0, 0), (1000, 0)])
        corridors = make_corridors(["HCC001"], [line])
        points = [Point(500, 50), Point(500, 250)]  # 50ft (candidate) vs 250ft (outside 200ft)
        crashes = make_crashes(["C1", "C2"], points)

        candidates = generate_candidates_spatial_index(crashes, corridors, max_threshold_feet=200.0)

        assert len(candidates) == 1
        assert candidates.iloc[0]["crash_record_id"] == "C1"
        assert candidates.iloc[0]["corridor_id"] == "HCC001"
        assert candidates.iloc[0]["distance_feet"] == pytest.approx(50.0)

    def test_empty_candidates_when_no_crashes_within_threshold(self):
        line = LineString([(0, 0), (1000, 0)])
        corridors = make_corridors(["HCC001"], [line])
        crashes = make_crashes(["C1"], [Point(500, 500)])

        candidates = generate_candidates_spatial_index(crashes, corridors, max_threshold_feet=200.0)
        assert candidates.empty

    def test_deterministic_ordering_and_ranking(self):
        line1 = LineString([(0, 0), (1000, 0)])      # y=0
        line2 = LineString([(0, 80), (1000, 80)])    # y=80
        corridors = make_corridors(["HCC002", "HCC001"], [line2, line1])
        crashes = make_crashes(["C1"], [Point(500, 30)])

        candidates = generate_candidates_spatial_index(crashes, corridors, max_threshold_feet=200.0)

        assert len(candidates) == 2
        rank1 = candidates[candidates["candidate_rank"] == 1].iloc[0]
        rank2 = candidates[candidates["candidate_rank"] == 2].iloc[0]

        assert rank1["corridor_id"] == "HCC001"
        assert rank1["distance_feet"] == pytest.approx(30.0)
        assert rank2["corridor_id"] == "HCC002"
        assert rank2["distance_feet"] == pytest.approx(50.0)
        assert rank1["is_ambiguous"] == True
        assert rank1["candidate_count"] == 2

    def test_tie_detection_within_tolerance(self):
        line1 = LineString([(0, 0), (1000, 0)])     # y=0
        line2 = LineString([(0, 8), (1000, 8)])     # y=8
        corridors = make_corridors(["HCC001", "HCC002"], [line1, line2])
        # Crash at y=4: d(HCC001)=4, d(HCC002)=4 -> tie (diff=0 <= 10ft)
        crashes = make_crashes(["C1"], [Point(500, 4)])

        candidates = generate_candidates_spatial_index(crashes, corridors, max_threshold_feet=200.0, tie_tolerance_feet=10.0)

        assert len(candidates) == 2
        assert bool(candidates["is_tie"].all()) == True

    def test_sample_size_filter(self, tmp_path):
        df = pd.DataFrame({
            "crash_record_id": [f"C{i}" for i in range(10)],
            "has_valid_coordinates": [True] * 10,
            "latitude": [41.85] * 10,
            "longitude": [-87.65] * 10,
            "crash_month_start": pd.to_datetime(["2022-01-01"] * 10),
            "severity_kabco": ["O"] * 10,
        })
        file_path = tmp_path / "crashes.parquet"
        df.to_parquet(file_path, index=False)

        all_df, eligible_gdf, is_sample = load_eligible_crashes(file_path, sample_size=3)
        assert len(all_df) == 10
        assert len(eligible_gdf) == 3
        assert is_sample is True
