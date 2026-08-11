"""Tests for primary crash-to-corridor assignment construction and validation.

All tests use synthetic geometries created in memory.
No real parquet files are overwritten during testing.
"""

from __future__ import annotations

import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import LineString, MultiLineString, Point

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.assign_crashes_to_corridors import (
    ANALYSIS_CRS,
    SOURCE_CRS,
    generate_candidates_spatial_index,
)
from src.data.build_crash_corridor_assignments import (
    build_primary_crash_assignments,
    validate_primary_assignments,
)


def make_synthetic_test_data():
    """Create synthetic crashes, corridors, and register in memory."""
    # Corridors:
    # HCC001: y=0
    # HCC002: y=30
    # HCC003: y=250 (multipart corridor at y=250 & y=255)
    corridors_gdf = gpd.GeoDataFrame(
        {
            "corridor_id": ["HCC001", "HCC002", "HCC003"],
            "corridor_name": ["Corridor 1", "Corridor 2", "Corridor 3"],
            "geometry": [
                LineString([(0, 0), (1000, 0)]),
                LineString([(0, 30), (1000, 30)]),
                MultiLineString([LineString([(0, 250), (1000, 250)]), LineString([(0, 255), (1000, 255)])]),
            ],
        },
        crs=ANALYSIS_CRS,
    )

    pts_3435 = gpd.GeoDataFrame(
        {
            "crash_record_id": ["C001", "C002", "C003", "C004", "C005", "C006"],
            "geometry": [
                Point(500, 5),   # d1=5, d2=25 -> gap=20 > 10 -> primary_assigned
                Point(500, 11),  # d1=11, d2=19 -> gap=8 <= 10 -> unresolved_tie
                Point(500, 12),  # d1=12, d2=18 -> gap=6 < 10 -> unresolved_tie
                Point(500, 140), # d1=110 to HCC002, d1=110 to HCC003 -> outside_selected_threshold (>100ft)
                Point(0, 0),     # Invalid coordinates
                Point(500, 248), # d1=2 to HCC003 multipart -> primary_assigned
            ],
        },
        crs=ANALYSIS_CRS,
    )
    pts_4326 = pts_3435.to_crs(SOURCE_CRS)

    crashes_df = pd.DataFrame(
        {
            "crash_record_id": ["C001", "C002", "C003", "C004", "C005", "C006"],
            "has_valid_coordinates": [True, True, True, True, False, True],
            "latitude": pts_4326.geometry.y.values,
            "longitude": pts_4326.geometry.x.values,
            "crash_month_start": [pd.Timestamp("2022-01-01")] * 6,
            "severity_kabco": ["O"] * 6,
        }
    )

    register_df = pd.DataFrame(
        {
            "corridor_id": ["HCC001", "HCC002", "HCC003"],
            "corridor_name": ["Corridor 1", "Corridor 2", "Corridor 3"],
        }
    )

    return crashes_df, corridors_gdf, register_df


class TestPrimaryCrashAssignmentRules:
    def test_single_candidate_assignment(self):
        """Single candidate corridor within 100ft is assigned primary_assigned."""
        corridors = gpd.GeoDataFrame(
            {
                "corridor_id": ["HCC001"],
                "geometry": [LineString([(0, 0), (1000, 0)])],
            },
            crs=ANALYSIS_CRS,
        )
        crashes = gpd.GeoDataFrame({"crash_record_id": ["C001"], "geometry": [Point(500, 25)]}, crs=ANALYSIS_CRS)

        cands = generate_candidates_spatial_index(crashes, corridors, max_threshold_feet=100.0, tie_tolerance_feet=10.0)

        assert len(cands) == 1
        r1 = cands.iloc[0]
        assert r1["corridor_id"] == "HCC001"
        assert pytest.approx(r1["distance_feet"], 0.001) == 25.0
        assert bool(r1["is_tie"]) is False

    def test_nearest_candidate_wins_when_distance_gap_gt_10ft(self):
        """Nearest candidate corridor wins when distance gap > 10 feet."""
        corridors = gpd.GeoDataFrame(
            {
                "corridor_id": ["HCC001", "HCC002"],
                "geometry": [LineString([(0, 0), (1000, 0)]), LineString([(0, 30), (1000, 30)])],
            },
            crs=ANALYSIS_CRS,
        )
        crashes = gpd.GeoDataFrame({"crash_record_id": ["C001"], "geometry": [Point(500, 5)]}, crs=ANALYSIS_CRS)

        cands = generate_candidates_spatial_index(crashes, corridors, max_threshold_feet=100.0, tie_tolerance_feet=10.0)

        assert len(cands) == 2
        r1 = cands[cands["candidate_rank"] == 1].iloc[0]
        r2 = cands[cands["candidate_rank"] == 2].iloc[0]

        assert r1["corridor_id"] == "HCC001"
        assert pytest.approx(r1["distance_feet"], 0.001) == 5.0
        assert pytest.approx(r2["distance_feet"], 0.001) == 25.0
        assert bool(r1["is_tie"]) is False

    def test_exactly_10ft_gap_is_unresolved_tie(self):
        corridors = gpd.GeoDataFrame(
            {
                "corridor_id": ["HCC001", "HCC002"],
                "geometry": [LineString([(0, 0), (1000, 0)]), LineString([(0, 30), (1000, 30)])],
            },
            crs=ANALYSIS_CRS,
        )
        crashes = gpd.GeoDataFrame({"crash_record_id": ["C002"], "geometry": [Point(500, 10)]}, crs=ANALYSIS_CRS)

        cands = generate_candidates_spatial_index(crashes, corridors, max_threshold_feet=100.0, tie_tolerance_feet=10.0)

        assert len(cands) == 2
        r1 = cands[cands["candidate_rank"] == 1].iloc[0]
        r2 = cands[cands["candidate_rank"] == 2].iloc[0]

        assert pytest.approx(r1["distance_feet"], 0.001) == 10.0
        assert pytest.approx(r2["distance_feet"], 0.001) == 20.0
        assert bool(r1["is_tie"]) is True

    def test_gap_below_10ft_is_unresolved_tie(self):
        corridors = gpd.GeoDataFrame(
            {
                "corridor_id": ["HCC001", "HCC002"],
                "geometry": [LineString([(0, 0), (1000, 0)]), LineString([(0, 30), (1000, 30)])],
            },
            crs=ANALYSIS_CRS,
        )
        crashes = gpd.GeoDataFrame({"crash_record_id": ["C003"], "geometry": [Point(500, 12)]}, crs=ANALYSIS_CRS)

        cands = generate_candidates_spatial_index(crashes, corridors, max_threshold_feet=100.0, tie_tolerance_feet=10.0)

        r1 = cands[cands["candidate_rank"] == 1].iloc[0]
        assert bool(r1["is_tie"]) is True

    def test_multipart_corridor_treated_as_one_entity(self):
        corridors = gpd.GeoDataFrame(
            {
                "corridor_id": ["HCC003"],
                "geometry": [MultiLineString([LineString([(0, 250), (1000, 250)]), LineString([(0, 255), (1000, 255)])])],
            },
            crs=ANALYSIS_CRS,
        )
        crashes = gpd.GeoDataFrame({"crash_record_id": ["C006"], "geometry": [Point(500, 248)]}, crs=ANALYSIS_CRS)

        cands = generate_candidates_spatial_index(crashes, corridors, max_threshold_feet=100.0, tie_tolerance_feet=10.0)

        assert len(cands) == 1
        r1 = cands.iloc[0]
        assert r1["corridor_id"] == "HCC003"
        assert pytest.approx(r1["distance_feet"], 0.001) == 2.0

    def test_full_pipeline_reconciliation_and_status_assignment(self, tmp_path):
        crashes_df, corridors_gdf, register_df = make_synthetic_test_data()

        crashes_p = tmp_path / "crashes.parquet"
        corridors_p = tmp_path / "corridors.parquet"
        register_p = tmp_path / "register.csv"
        cand_p = tmp_path / "candidates.parquet"
        report_p = tmp_path / "report.json"
        runs_dir = tmp_path / "runs"

        crashes_df.to_parquet(crashes_p, index=False)
        corridors_gdf.to_parquet(corridors_p, index=False)
        register_df.to_csv(register_p, index=False)

        spatial_config = {
            "crash_assignment": {
                "selected_distance_threshold_feet": 100,
                "threshold_status": "approved_for_modeling",
                "ambiguity": {"tie_tolerance_feet": 10},
            }
        }

        assignments_df, report = build_primary_crash_assignments(
            spatial_config=spatial_config,
            crashes_path=crashes_p,
            corridors_path=corridors_p,
            register_path=register_p,
            output_path=cand_p,
            validation_report_path=report_p,
            runs_dir=runs_dir,
            sample_size=None,
        )

        assert len(assignments_df) == 6
        assert len(assignments_df["crash_record_id"].unique()) == 6

        s_dict = assignments_df.set_index("crash_record_id")["assignment_status"].to_dict()
        c_dict = assignments_df.set_index("crash_record_id")["corridor_id"].to_dict()

        assert s_dict["C001"] == "primary_assigned"
        assert c_dict["C001"] == "HCC001"

        assert s_dict["C002"] == "unresolved_tie"
        assert pd.isna(c_dict["C002"])

        assert s_dict["C003"] == "unresolved_tie"
        assert pd.isna(c_dict["C003"])

        assert s_dict["C004"] == "outside_selected_threshold"
        assert pd.isna(c_dict["C004"])

        assert s_dict["C005"] == "no_valid_coordinates"
        assert pd.isna(c_dict["C005"])

        assert s_dict["C006"] == "primary_assigned"
        assert c_dict["C006"] == "HCC003"

        # Reconciliation sum check
        recon = report["reconciliation"]
        assert recon["reconciliation_diff"] == 0
        assert recon["total_crashes"] == 6

        # Corridor ID null for all non-primary assigned:
        non_primary = assignments_df[assignments_df["assignment_status"] != "primary_assigned"]
        assert non_primary["corridor_id"].isna().all()

        # Deterministic sorting check
        assert list(assignments_df["crash_record_id"]) == sorted(list(assignments_df["crash_record_id"]))


class TestSampleModeAndValidationProtection:
    def test_sample_mode_does_not_overwrite_full_artifacts(self, tmp_path):
        report_p = tmp_path / "report.json"
        report_p.write_text('{"authoritative": true}', encoding="utf-8")

        crashes_df, corridors_gdf, register_df = make_synthetic_test_data()

        crashes_p = tmp_path / "crashes.parquet"
        corridors_p = tmp_path / "corridors.parquet"
        register_p = tmp_path / "register.csv"
        cand_p = tmp_path / "output.parquet"
        runs_dir = tmp_path / "runs"

        crashes_df.to_parquet(crashes_p, index=False)
        corridors_gdf.to_parquet(corridors_p, index=False)
        register_df.to_csv(register_p, index=False)

        spatial_config = {
            "crash_assignment": {
                "selected_distance_threshold_feet": 100,
                "threshold_status": "approved_for_modeling",
                "ambiguity": {"tie_tolerance_feet": 10},
            }
        }

        assignments_df, report = build_primary_crash_assignments(
            spatial_config=spatial_config,
            crashes_path=crashes_p,
            corridors_path=corridors_p,
            register_path=register_p,
            output_path=cand_p,
            validation_report_path=report_p,
            runs_dir=runs_dir,
            sample_size=3,
        )

        assert report["is_sample"] is True
        saved_report_text = report_p.read_text(encoding="utf-8")
        assert "authoritative" in saved_report_text
        assert not cand_p.exists()

    def test_unknown_corridor_id_fails_validation(self):
        df = pd.DataFrame(
            {
                "crash_record_id": ["C1"],
                "assignment_status": ["primary_assigned"],
                "corridor_id": ["UNKNOWN_999"],
                "distance_feet": [5.0],
                "candidate_count": [1],
                "second_nearest_distance_feet": [None],
                "distance_gap_feet": [None],
                "threshold_feet": [100],
                "tie_tolerance_feet": [10.0],
                "run_id": ["TEST"],
            }
        )

        report, checks = validate_primary_assignments(
            df,
            total_crash_count=1,
            eligible_crash_count=1,
            invalid_coordinate_count=0,
            authoritative_register_ids={"HCC001", "HCC002"},
            corridor_count=2,
            selected_threshold_feet=100.0,
            threshold_status="approved_for_modeling",
            is_sample=True,
        )

        corr_check = next(c for c in checks if c["check"] == "assigned_corridors_valid_register_subset")
        assert corr_check["passed"] is False
        assert corr_check["severity"] == "CRITICAL"
        assert report["status"] == "FAIL"
