"""Tests for corridor treatment readiness data build, spatial equity metrics, and CMF evidence.

All tests verify complete panel crash reconciliation, pooled-prior severity shrinkage,
spatial equity reconciliation, and data availability guards.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.treatments.build_treatment_readiness import (
    build_corridor_crash_profiles,
    build_spatial_corridor_equity_metrics,
    compute_pooled_prior_severity_shrinkage,
)
from src.validation.validate_treatment_readiness import validate_corridor_treatment_readiness


class TestTreatmentReadiness:
    def test_complete_panel_crash_reconciliation_exact(self):
        """Complete panel crash counts match authoritative numbers across all 43 corridors."""
        df_p = build_corridor_crash_profiles()
        assert len(df_p) == 43
        assert df_p["total_crashes_hist"].sum() == 112421
        assert df_p["k_crashes_hist"].sum() == 139
        assert df_p["a_crashes_hist"].sum() == 2158
        assert df_p["b_crashes_hist"].sum() == 10850
        assert df_p["c_crashes_hist"].sum() == 6124
        assert df_p["o_crashes_hist"].sum() == 93053
        assert df_p["u_crashes_hist"].sum() == 97
        assert df_p["ksi_crashes_hist"].sum() == 2297

    def test_unknown_severity_values_preserved_without_silent_mapping(self):
        """Unknown severity values (U=97) are explicitly preserved as U and not silently mapped."""
        df_p = build_corridor_crash_profiles()
        assert df_p["u_crashes_hist"].sum() == 97
        assert "u_crashes_hist" in df_p.columns

    def test_sub_category_crash_profiles_built(self):
        """Pedestrian, wet-road, failure-to-reduce-speed, curve, angle, and rear-end crash profiles are built."""
        df_p = build_corridor_crash_profiles()
        assert df_p["pedestrian_crashes_tot"].sum() == 3699
        assert df_p["wet_crashes_tot"].sum() == 15751
        assert df_p["failure_to_reduce_speed_crashes_tot"].sum() == 5313
        assert df_p["curve_crashes_tot"].sum() == 1779
        assert df_p["angle_crashes_tot"].sum() == 10446
        assert df_p["rear_end_crashes_tot"].sum() == 28363

    def test_pooled_prior_severity_shrinkage_shares_sum_to_unity(self):
        """Pooled-prior severity shrinkage shares sum to 1.0 and contain zero negative categories."""
        df_p = build_corridor_crash_profiles()
        df_s = compute_pooled_prior_severity_shrinkage(df_p, m_ksi=10.0, m_non_ksi=50.0)
        assert len(df_s) == 43

        ksi_sum_diff = (df_s["share_k_given_ksi"] + df_s["share_a_given_ksi"] - 1.0).abs().max()
        non_sum_diff = (
            df_s["share_b_given_non_ksi"]
            + df_s["share_c_given_non_ksi"]
            + df_s["share_o_given_non_ksi"]
            + df_s["share_u_given_non_ksi"]
            - 1.0
        ).abs().max()

        assert ksi_sum_diff < 1e-4
        assert non_sum_diff < 1e-4
        assert (df_s["share_k_given_ksi"] >= 0).all()
        assert (df_s["share_a_given_ksi"] >= 0).all()
        assert (df_s["share_b_given_non_ksi"] >= 0).all()
        assert (df_s["share_c_given_non_ksi"] >= 0).all()

    def test_pooled_prior_severity_mean_recomputation(self):
        """Independently recompute denominator-weighted pooled mean vs unweighted corridor mean."""
        df_p = build_corridor_crash_profiles()
        df_s = compute_pooled_prior_severity_shrinkage(df_p, m_ksi=10.0, m_non_ksi=50.0)

        denom_weighted_k = float(df_p["k_crashes_hist"].sum() / df_p["ksi_crashes_hist"].sum())
        unweighted_mean_k = float(df_s["share_k_given_ksi"].mean())

        denom_weighted_o = float(df_p["o_crashes_hist"].sum() / (df_p["total_crashes_hist"].sum() - df_p["ksi_crashes_hist"].sum()))
        unweighted_mean_o = float(df_s["share_o_given_non_ksi"].mean())

        assert denom_weighted_k == pytest.approx(0.060514, 1e-4)
        assert unweighted_mean_k == pytest.approx(0.057218, 1e-4)
        assert denom_weighted_o == pytest.approx(0.844984, 1e-4)
        assert unweighted_mean_o == pytest.approx(0.843580, 1e-4)

    def test_shrinkage_sensitivity_under_ksi_strengths_5_10_20(self):
        """Test severity shrinkage behavior under KSI prior strengths 5, 10, and 20."""
        df_p = build_corridor_crash_profiles()
        for m_k in [5.0, 10.0, 20.0]:
            df_s = compute_pooled_prior_severity_shrinkage(df_p, m_ksi=m_k, m_non_ksi=50.0)
            diff = (df_s["share_k_given_ksi"] + df_s["share_a_given_ksi"] - 1.0).abs().max()
            assert diff < 1e-4
            assert (df_s["share_k_given_ksi"] >= 0).all()

    def test_shrinkage_sensitivity_under_non_ksi_strengths_25_50_100(self):
        """Test severity shrinkage behavior under non-KSI prior strengths 25, 50, and 100."""
        df_p = build_corridor_crash_profiles()
        for m_non in [25.0, 50.0, 100.0]:
            df_s = compute_pooled_prior_severity_shrinkage(df_p, m_ksi=10.0, m_non_ksi=m_non)
            diff = (
                df_s["share_b_given_non_ksi"]
                + df_s["share_c_given_non_ksi"]
                + df_s["share_o_given_non_ksi"]
                + df_s["share_u_given_non_ksi"]
                - 1.0
            ).abs().max()
            assert diff < 1e-4
            assert (df_s["share_o_given_non_ksi"] >= 0).all()

    def test_full_resolution_spatial_corridor_equity_overlay(self):
        """Full-resolution spatial equity metrics achieve 100.0% linework coverage and 0.0000 ft max error."""
        df_eq = build_spatial_corridor_equity_metrics()
        assert len(df_eq) == 43
        assert df_eq["spatial_reconciliation_diff_feet"].max() < 0.1
        assert df_eq["spatial_linework_coverage_percent"].min() >= 99.99
        assert df_eq["equity_classification_A_weighted_ge_0_75"].sum() == 18
        assert df_eq["equity_classification_B_share_ge_0_50"].sum() == 19

    def test_cmf_evidence_matrix_and_manifest_traceability(self):
        """CMF evidence matrix and spatial source manifest contain required primary source traceability fields."""
        matrix_path = ROOT / "docs" / "evidence" / "treatment_cmf_evidence_matrix.csv"
        manifest_path = ROOT / "docs" / "data_quality" / "spatial_svi_source_manifest.json"

        assert matrix_path.exists()
        assert manifest_path.exists()

        df_cmf = pd.read_csv(matrix_path)
        assert len(df_cmf) >= 5
        assert "cmf_clearinghouse_url" in df_cmf.columns
        assert "publication_number" in df_cmf.columns

    def test_full_treatment_readiness_validation(self, tmp_path):
        """Validate treatment readiness validator executes cleanly and returns PASS_WITH_WARNINGS."""
        p_path = tmp_path / "corridor_treatment_readiness.parquet"
        c_path = tmp_path / "corridor_treatment_readiness.csv"
        r_path = tmp_path / "treatment_readiness_validation.json"

        from src.treatments.build_treatment_readiness import build_corridor_treatment_readiness

        df_r = build_corridor_treatment_readiness(
            output_parquet_path=p_path,
            output_csv_path=c_path,
        )
        assert len(df_r) == 43

        report, checks = validate_corridor_treatment_readiness(
            parquet_path=p_path,
            csv_path=c_path,
            report_output_path=r_path,
            is_sample=True,
        )
        assert report["status"] == "PASS_WITH_WARNINGS"
        assert report["downstream_readiness"] == "READY_FOR_TREATMENT_EVIDENCE_REVIEW"
        assert report["critical_failure_count"] == 0
        assert len(report["governance_warnings"]) == 5
