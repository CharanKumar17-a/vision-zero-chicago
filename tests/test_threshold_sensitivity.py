"""Tests for threshold sensitivity evaluation, validation, and sample-mode semantics.

All tests use synthetic geometries created in memory.
No real parquet files are required for testing.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import LineString, Point

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.assign_crashes_to_corridors import (
    ANALYSIS_CRS,
    SOURCE_CRS,
    generate_candidates_spatial_index,
)
from src.data.build_threshold_sensitivity import (
    compute_incremental_distance_bands,
    compute_threshold_metrics,
    run_threshold_sensitivity,
    validate_report,
)

THRESHOLDS = [50, 100, 150, 200]


def make_synthetic_scenario(n_crashes: int = 50, n_corridors: int = 3):
    corridors_gdf = gpd.GeoDataFrame(
        {
            "corridor_id": [f"HCC{i:03d}" for i in range(1, n_corridors + 1)],
            "geometry": [
                LineString([(0, 0), (1000, 0)]),
                LineString([(0, 150), (1000, 150)]),
                LineString([(0, 300), (1000, 300)]),
            ][:n_corridors],
        },
        crs=ANALYSIS_CRS,
    )

    step = 220 / n_crashes
    ys = [i * step for i in range(n_crashes)]
    crash_ids = [f"C{i:04d}" for i in range(n_crashes)]
    points = [Point(500, y) for y in ys]
    crashes_gdf = gpd.GeoDataFrame(
        {"crash_record_id": crash_ids, "geometry": points, "has_valid_coordinates": True},
        crs=ANALYSIS_CRS,
    )
    return crashes_gdf, corridors_gdf


class TestThresholdMonotonicityAndReconciliation:
    def test_all_four_thresholds_evaluated(self):
        crashes_gdf, corridors_gdf = make_synthetic_scenario()
        candidates_full = generate_candidates_spatial_index(crashes_gdf, corridors_gdf, max_threshold_feet=200.0)

        results = []
        prev_matched = None
        for t in THRESHOLDS:
            m = compute_threshold_metrics(
                candidates_full,
                eligible_count=len(crashes_gdf),
                total_count=len(crashes_gdf) + 10,
                invalid_count=10,
                threshold_feet=t,
                prev_matched_count=prev_matched,
            )
            results.append(m)
            prev_matched = m["matched_unique_crashes"]

        assert len(results) == 4
        assert [r["threshold_feet"] for r in results] == THRESHOLDS

    def test_monotonicity_rules(self):
        crashes_gdf, corridors_gdf = make_synthetic_scenario(n_crashes=100)
        candidates_full = generate_candidates_spatial_index(crashes_gdf, corridors_gdf, max_threshold_feet=200.0)

        results = []
        prev_matched = None
        for t in THRESHOLDS:
            m = compute_threshold_metrics(
                candidates_full,
                eligible_count=len(crashes_gdf),
                total_count=len(crashes_gdf),
                invalid_count=0,
                threshold_feet=t,
                prev_matched_count=prev_matched,
            )
            results.append(m)
            prev_matched = m["matched_unique_crashes"]

        for i in range(1, len(results)):
            curr = results[i]
            prev = results[i - 1]

            assert curr["matched_unique_crashes"] >= prev["matched_unique_crashes"]
            assert curr["unmatched_crashes"] <= prev["unmatched_crashes"]
            assert curr["candidate_pair_count"] >= prev["candidate_pair_count"]
            if curr["distance_max_feet"] is not None:
                assert curr["distance_max_feet"] <= curr["threshold_feet"]

    def test_reconciliation_equations(self):
        crashes_gdf, corridors_gdf = make_synthetic_scenario(n_crashes=60)
        candidates_full = generate_candidates_spatial_index(crashes_gdf, corridors_gdf, max_threshold_feet=200.0)

        total_count = 70
        eligible_count = 60
        invalid_count = 10

        for t in THRESHOLDS:
            m = compute_threshold_metrics(
                candidates_full,
                eligible_count=eligible_count,
                total_count=total_count,
                invalid_count=invalid_count,
                threshold_feet=t,
            )
            r = m["reconciliation"]

            assert r["source_reconciliation_diff"] == 0
            assert r["threshold_reconciliation_diff"] == 0
            assert r["matched_breakdown_diff"] == 0
            assert r["valid_coordinate_crashes"] == r["matched_unique_crashes"] + r["unmatched_crashes"]
            assert r["matched_unique_crashes"] == r["single_candidate_crashes"] + r["multiple_candidate_crashes"]


class TestSampleModeSemantics:
    def test_sample_mode_does_not_overwrite_report(self, tmp_path):
        report_path = tmp_path / "threshold_sensitivity_report.json"
        report_path.write_text('{"original": true}', encoding="utf-8")

        crashes_df = pd.DataFrame({
            "crash_record_id": [f"C{i:04d}" for i in range(20)],
            "has_valid_coordinates": [True] * 20,
            "latitude": [41.85] * 20,
            "longitude": [-87.65] * 20,
            "crash_month_start": pd.to_datetime(["2022-01-01"] * 20),
            "severity_kabco": ["O"] * 20,
        })
        crashes_parquet = tmp_path / "crashes_clean.parquet"
        crashes_df.to_parquet(crashes_parquet, index=False)

        corridors_gdf = gpd.GeoDataFrame({
            "corridor_id": ["HCC001"],
            "corridor_name": ["Test Corridor"],
            "geometry": [LineString([(0, 0), (1000, 0)])],
        }, crs=ANALYSIS_CRS)
        corridors_parquet = tmp_path / "high_crash_corridors.parquet"
        corridors_gdf.to_parquet(corridors_parquet, index=False)

        reg_df = pd.DataFrame({"corridor_id": ["HCC001"], "corridor_name": ["Test Corridor"]})
        reg_csv = tmp_path / "register.csv"
        reg_df.to_csv(reg_csv, index=False)

        cand_output = tmp_path / "candidates.parquet"
        runs_dir = tmp_path / "runs"

        report = run_threshold_sensitivity(
            crashes_path=crashes_parquet,
            corridors_path=corridors_parquet,
            register_path=reg_csv,
            candidate_output_path=cand_output,
            sensitivity_report_path=report_path,
            runs_dir=runs_dir,
            sample_size=5,
        )

        assert report["is_sample"] is True
        assert report["sample_size"] == 5
        assert report["eligible_crashes"] == 5

        saved_text = report_path.read_text(encoding="utf-8")
        assert "original" in saved_text


class TestReportValidationChecks:
    def test_duplicate_candidate_key_fails_validation(self):
        crashes_gdf, corridors_gdf = make_synthetic_scenario(n_crashes=5)
        candidates_full = generate_candidates_spatial_index(crashes_gdf, corridors_gdf, max_threshold_feet=200.0)

        dup_row = candidates_full.iloc[0:1].copy()
        candidates_dup = pd.concat([candidates_full, dup_row], ignore_index=True)

        dummy_report = {
            "source_crs": SOURCE_CRS,
            "analysis_crs": ANALYSIS_CRS,
            "thresholds_evaluated_feet": THRESHOLDS,
            "selected_distance_threshold_feet": None,
            "total_crashes": 5,
            "eligible_crashes": 5,
            "invalid_coordinate_crashes": 0,
            "threshold_results": [],
        }

        regs = {"HCC001", "HCC002", "HCC003"}
        checks = validate_report(
            dummy_report,
            candidates_full=candidates_dup,
            configured_thresholds=THRESHOLDS,
            authoritative_register_ids=regs,
            geometry_corridor_ids=regs,
        )

        dup_check = next(c for c in checks if c["check"] == "candidate_keys_unique")
        assert dup_check["passed"] is False
        assert dup_check["severity"] == "CRITICAL"

    def test_unknown_corridor_id_fails_validation(self):
        crashes_gdf, corridors_gdf = make_synthetic_scenario(n_crashes=5)
        candidates_full = generate_candidates_spatial_index(crashes_gdf, corridors_gdf, max_threshold_feet=200.0)

        candidates_bad = candidates_full.copy()
        candidates_bad.loc[0, "corridor_id"] = "UNKNOWN_999"

        dummy_report = {
            "source_crs": SOURCE_CRS,
            "analysis_crs": ANALYSIS_CRS,
            "thresholds_evaluated_feet": THRESHOLDS,
            "selected_distance_threshold_feet": None,
            "total_crashes": 5,
            "eligible_crashes": 5,
            "invalid_coordinate_crashes": 0,
            "threshold_results": [],
        }

        regs = {"HCC001", "HCC002", "HCC003"}
        checks = validate_report(
            dummy_report,
            candidates_full=candidates_bad,
            configured_thresholds=THRESHOLDS,
            authoritative_register_ids=regs,
            geometry_corridor_ids=regs,
        )

        corr_check = next(c for c in checks if c["check"] == "candidate_corridors_subset_of_register")
        assert corr_check["passed"] is False
        assert corr_check["severity"] == "CRITICAL"

    def test_null_key_or_distance_fails_validation(self):
        crashes_gdf, corridors_gdf = make_synthetic_scenario(n_crashes=5)
        candidates_full = generate_candidates_spatial_index(crashes_gdf, corridors_gdf, max_threshold_feet=200.0)

        candidates_null = candidates_full.copy()
        candidates_null.loc[0, "distance_feet"] = None

        dummy_report = {
            "source_crs": SOURCE_CRS,
            "analysis_crs": ANALYSIS_CRS,
            "thresholds_evaluated_feet": THRESHOLDS,
            "selected_distance_threshold_feet": None,
            "total_crashes": 5,
            "eligible_crashes": 5,
            "invalid_coordinate_crashes": 0,
            "threshold_results": [],
        }

        regs = {"HCC001", "HCC002", "HCC003"}
        checks = validate_report(
            dummy_report,
            candidates_full=candidates_null,
            configured_thresholds=THRESHOLDS,
            authoritative_register_ids=regs,
            geometry_corridor_ids=regs,
        )

        null_check = next(c for c in checks if c["check"] == "no_null_candidate_keys_or_distances")
        assert null_check["passed"] is False
        assert null_check["severity"] == "CRITICAL"

    def test_lower_threshold_ambiguity_ignores_outside_candidates(self):
        crashes = gpd.GeoDataFrame({"crash_record_id": ["C1"], "geometry": [Point(500, 40)]}, crs=ANALYSIS_CRS)
        corridors = gpd.GeoDataFrame({
            "corridor_id": ["HCC001", "HCC002"],
            "geometry": [LineString([(0, 0), (1000, 0)]), LineString([(0, 150), (1000, 150)])],
        }, crs=ANALYSIS_CRS)

        candidates = generate_candidates_spatial_index(crashes, corridors, max_threshold_feet=200.0)

        inc_bands = compute_incremental_distance_bands(candidates, eligible_count=1, tie_tolerance_feet=10.0)
        band_0_50 = next(b for b in inc_bands if b["distance_band"] == "0-50 ft")
        assert band_0_50["unique_matched_crashes"] == 1
        assert band_0_50["ambiguity_count"] == 0
        assert band_0_50["ambiguity_rate"] == 0.0

    def test_report_counts_derived_from_checks_list(self, tmp_path):
        crashes_df = pd.DataFrame({
            "crash_record_id": ["C0001"],
            "has_valid_coordinates": [True],
            "latitude": [41.85],
            "longitude": [-87.65],
            "crash_month_start": [pd.Timestamp("2022-01-01")],
            "severity_kabco": ["O"],
        })
        crashes_p = tmp_path / "crashes.parquet"
        crashes_df.to_parquet(crashes_p, index=False)

        corridors_gdf = gpd.GeoDataFrame({
            "corridor_id": ["HCC001"],
            "corridor_name": ["Test"],
            "geometry": [LineString([(0, 0), (1000, 0)])],
        }, crs=ANALYSIS_CRS)
        corridors_p = tmp_path / "corridors.parquet"
        corridors_gdf.to_parquet(corridors_p, index=False)

        reg_df = pd.DataFrame({"corridor_id": ["HCC001"], "corridor_name": ["Test"]})
        reg_p = tmp_path / "register.csv"
        reg_df.to_csv(reg_p, index=False)

        report = run_threshold_sensitivity(
            crashes_path=crashes_p,
            corridors_path=corridors_p,
            register_path=reg_p,
            candidate_output_path=tmp_path / "cand.parquet",
            sensitivity_report_path=tmp_path / "rep.json",
            runs_dir=tmp_path / "runs",
        )

        assert "checks" in report
        checks = report["checks"]
        expected_crit_failures = sum(1 for c in checks if c["severity"] == "CRITICAL" and not c["passed"])
        expected_warnings = sum(1 for c in checks if c["severity"] == "WARNING" and not c["passed"])

        assert report["critical_failure_count"] == expected_crit_failures
        assert report["warning_count"] == expected_warnings


class TestFocusedGovernanceRules:
    def test_non_default_tie_tolerance_changes_classification(self):
        crashes = gpd.GeoDataFrame({"crash_record_id": ["C1"], "geometry": [Point(500, 4)]}, crs=ANALYSIS_CRS)
        corridors = gpd.GeoDataFrame({
            "corridor_id": ["HCC001", "HCC002"],
            "geometry": [LineString([(0, 0), (1000, 0)]), LineString([(0, 12), (1000, 12)])],
        }, crs=ANALYSIS_CRS)

        cand_loose = generate_candidates_spatial_index(crashes, corridors, max_threshold_feet=200.0, tie_tolerance_feet=10.0)
        metrics_loose = compute_threshold_metrics(cand_loose, eligible_count=1, total_count=1, invalid_count=0, threshold_feet=50, tie_tolerance_feet=10.0)
        assert metrics_loose["tie_crashes"] == 1

        cand_strict = generate_candidates_spatial_index(crashes, corridors, max_threshold_feet=200.0, tie_tolerance_feet=1.0)
        metrics_strict = compute_threshold_metrics(cand_strict, eligible_count=1, total_count=1, invalid_count=0, threshold_feet=50, tie_tolerance_feet=1.0)
        assert metrics_strict["tie_crashes"] == 0

    def test_corridor_register_mismatch_fails_validation(self):
        crashes_gdf, corridors_gdf = make_synthetic_scenario(n_crashes=5)
        candidates_full = generate_candidates_spatial_index(crashes_gdf, corridors_gdf, max_threshold_feet=200.0)

        dummy_report = {
            "source_crs": SOURCE_CRS,
            "analysis_crs": ANALYSIS_CRS,
            "thresholds_evaluated_feet": THRESHOLDS,
            "selected_distance_threshold_feet": None,
            "total_crashes": 5,
            "eligible_crashes": 5,
            "invalid_coordinate_crashes": 0,
            "threshold_results": [],
        }

        auth_register = {"HCC001", "HCC002", "HCC003"}
        mismatched_geometry = {"HCC001", "HCC002", "EXTRA_999"}

        checks = validate_report(
            dummy_report,
            candidates_full=candidates_full,
            configured_thresholds=THRESHOLDS,
            authoritative_register_ids=auth_register,
            geometry_corridor_ids=mismatched_geometry,
        )

        match_check = next(c for c in checks if c["check"] == "geometry_corridors_match_register")
        assert match_check["passed"] is False
        assert match_check["severity"] == "CRITICAL"

    def test_recommendation_wording_unproven(self, tmp_path):
        crashes_df = pd.DataFrame({
            "crash_record_id": ["C0001"],
            "has_valid_coordinates": [True],
            "latitude": [41.85],
            "longitude": [-87.65],
            "crash_month_start": [pd.Timestamp("2022-01-01")],
            "severity_kabco": ["O"],
        })
        crashes_p = tmp_path / "crashes.parquet"
        crashes_df.to_parquet(crashes_p, index=False)

        corridors_gdf = gpd.GeoDataFrame({
            "corridor_id": ["HCC001"],
            "corridor_name": ["Test"],
            "geometry": [LineString([(0, 0), (1000, 0)])],
        }, crs=ANALYSIS_CRS)
        corridors_p = tmp_path / "corridors.parquet"
        corridors_gdf.to_parquet(corridors_p, index=False)

        reg_df = pd.DataFrame({"corridor_id": ["HCC001"], "corridor_name": ["Test"]})
        reg_p = tmp_path / "register.csv"
        reg_df.to_csv(reg_p, index=False)

        report = run_threshold_sensitivity(
            crashes_path=crashes_p,
            corridors_path=corridors_p,
            register_path=reg_p,
            candidate_output_path=tmp_path / "cand.parquet",
            sensitivity_report_path=tmp_path / "rep.json",
            runs_dir=tmp_path / "runs",
        )

        just = report["provisional_recommendation"]["justification"]
        assert "not been independently verified" in just
        assert "greater spatial uncertainty" in just
        assert "ROW-boundary crashes" not in just


class TestReportSchemaStatusAndReadiness:
    def test_clean_checks_produces_pass_and_ready(self, tmp_path):
        corridors_gdf = gpd.GeoDataFrame({
            "corridor_id": [f"HCC{i:03d}" for i in range(1, 44)],
            "corridor_name": [f"Corridor {i}" for i in range(1, 44)],
            "geometry": [LineString([(0, i * 20), (1000, i * 20)]) for i in range(1, 44)],
        }, crs=ANALYSIS_CRS)
        corridors_p = tmp_path / "corridors.parquet"
        corridors_gdf.to_parquet(corridors_p, index=False)

        pts_3435 = gpd.GeoDataFrame({
            "geometry": [Point(500, i * 20 + 5) for i in range(1, 44)]
        }, crs=ANALYSIS_CRS).to_crs(SOURCE_CRS)

        crashes_df = pd.DataFrame({
            "crash_record_id": [f"C{i:04d}" for i in range(1, 44)],
            "has_valid_coordinates": [True] * 43,
            "latitude": pts_3435.geometry.y.values,
            "longitude": pts_3435.geometry.x.values,
            "crash_month_start": [pd.Timestamp("2022-01-01")] * 43,
            "severity_kabco": ["O"] * 43,
        })
        crashes_p = tmp_path / "crashes.parquet"
        crashes_df.to_parquet(crashes_p, index=False)

        reg_df = pd.DataFrame({"corridor_id": [f"HCC{i:03d}" for i in range(1, 44)], "corridor_name": [f"Corridor {i}" for i in range(1, 44)]})
        reg_p = tmp_path / "register.csv"
        reg_df.to_csv(reg_p, index=False)

        report = run_threshold_sensitivity(
            crashes_path=crashes_p,
            corridors_path=corridors_p,
            register_path=reg_p,
            candidate_output_path=tmp_path / "cand.parquet",
            sensitivity_report_path=tmp_path / "rep.json",
            runs_dir=tmp_path / "runs",
        )

        assert report["status"] == "PASS"
        assert report["downstream_readiness"] == "READY_FOR_THRESHOLD_REVIEW"
        assert report["critical_failure_count"] == 0
        assert report["warning_count"] == 0

    def test_failed_critical_check_produces_fail_and_blocked(self, tmp_path):
        corridors_gdf = gpd.GeoDataFrame({
            "corridor_id": ["EXTRA_999"] + [f"HCC{i:03d}" for i in range(2, 44)],
            "corridor_name": [f"Corridor {i}" for i in range(1, 44)],
            "geometry": [LineString([(0, i * 20), (1000, i * 20)]) for i in range(1, 44)],
        }, crs=ANALYSIS_CRS)
        corridors_p = tmp_path / "corridors.parquet"
        corridors_gdf.to_parquet(corridors_p, index=False)

        crashes_df = pd.DataFrame({
            "crash_record_id": ["C0001"],
            "has_valid_coordinates": [True],
            "latitude": [41.85],
            "longitude": [-87.65],
            "crash_month_start": [pd.Timestamp("2022-01-01")],
            "severity_kabco": ["O"],
        })
        crashes_p = tmp_path / "crashes.parquet"
        crashes_df.to_parquet(crashes_p, index=False)

        reg_df = pd.DataFrame({"corridor_id": [f"HCC{i:03d}" for i in range(1, 44)], "corridor_name": [f"Corridor {i}" for i in range(1, 44)]})
        reg_p = tmp_path / "register.csv"
        reg_df.to_csv(reg_p, index=False)

        report = run_threshold_sensitivity(
            crashes_path=crashes_p,
            corridors_path=corridors_p,
            register_path=reg_p,
            candidate_output_path=tmp_path / "cand.parquet",
            sensitivity_report_path=tmp_path / "rep.json",
            runs_dir=tmp_path / "runs",
        )

        assert report["status"] == "FAIL"
        assert report["downstream_readiness"] == "BLOCKED"
        assert report["critical_failure_count"] > 0

    def test_failed_warning_only_check_produces_pass_with_warnings(self, tmp_path):
        corridors_gdf = gpd.GeoDataFrame({
            "corridor_id": [f"HCC{i:03d}" for i in range(1, 44)],
            "corridor_name": [f"Corridor {i}" for i in range(1, 44)],
            "geometry": [LineString([(0, 0), (1000, 0)])] * 42 + [LineString([(0, 10000), (1000, 10000)])],
        }, crs=ANALYSIS_CRS)
        corridors_p = tmp_path / "corridors.parquet"
        corridors_gdf.to_parquet(corridors_p, index=False)

        crashes_df = pd.DataFrame({
            "crash_record_id": ["C0001"],
            "has_valid_coordinates": [True],
            "latitude": [41.85],
            "longitude": [-87.65],
            "crash_month_start": [pd.Timestamp("2022-01-01")],
            "severity_kabco": ["O"],
        })
        crashes_p = tmp_path / "crashes.parquet"
        crashes_df.to_parquet(crashes_p, index=False)

        reg_df = pd.DataFrame({"corridor_id": [f"HCC{i:03d}" for i in range(1, 44)], "corridor_name": [f"Corridor {i}" for i in range(1, 44)]})
        reg_p = tmp_path / "register.csv"
        reg_df.to_csv(reg_p, index=False)

        report = run_threshold_sensitivity(
            crashes_path=crashes_p,
            corridors_path=corridors_p,
            register_path=reg_p,
            candidate_output_path=tmp_path / "cand.parquet",
            sensitivity_report_path=tmp_path / "rep.json",
            runs_dir=tmp_path / "runs",
        )

        assert report["status"] == "PASS_WITH_WARNINGS"
        assert report["downstream_readiness"] == "READY_FOR_THRESHOLD_REVIEW"
        assert report["critical_failure_count"] == 0
        assert report["warning_count"] > 0
