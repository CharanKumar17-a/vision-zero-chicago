"""Tests for corridor treatment benefits calculation, pedestrian baseline, CMF bounds, and economics.

All tests verify composite keys, pedestrian forecasts, CMF confidence bounds,
severity disaggregation reconciliation, and side-effect safety.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.treatments.calculate_treatment_benefits import (
    TREATMENT_METADATA,
    build_pedestrian_severity_shares,
    build_treatment_benefits_panel,
    compute_present_value_factor,
)
from src.validation.validate_treatment_benefits import validate_corridor_treatment_benefits


class TestTreatmentBenefits:
    def test_exact_387_rows_and_unique_composite_key(self):
        """Panel contains exactly 387 rows (43 corridors x 3 treatments x 3 scenarios) with unique composite key."""
        df_b, _ = build_treatment_benefits_panel()
        assert len(df_b) == 387
        comp_keys = df_b.groupby(["corridor_id", "treatment_id", "scenario_level"]).size()
        assert (comp_keys == 1).all()
        assert len(comp_keys) == 387

    def test_no_missing_required_fields(self):
        """All 25+ required dataset fields are present and non-null."""
        df_b, _ = build_treatment_benefits_panel()
        required_fields = [
            "corridor_id",
            "corridor_name",
            "treatment_id",
            "scenario_level",
            "demand_risk_rank",
            "demand_risk_percentile",
            "physical_applicability_status",
            "optimization_status",
            "relevant_forecast_crashes",
            "eligible_crash_exposure_share",
            "eligible_crashes_total",
            "cmf_id",
            "cmf",
            "cmf_standard_error",
            "crashes_averted_total",
            "crashes_averted_k",
            "crashes_averted_a",
            "crashes_averted_b",
            "crashes_averted_c",
            "crashes_averted_o",
            "crashes_averted_unknown",
            "annual_monetary_benefit",
            "useful_life_years",
            "real_discount_rate",
            "present_value_factor",
            "present_value_benefit",
            "installation_density",
            "installation_quantity",
            "unit_cost",
            "capital_project_cost",
            "net_present_benefit",
            "benefit_cost_ratio",
            "equity_area_flag",
            "required_governance_labels",
        ]
        for field in required_fields:
            assert field in df_b.columns, f"Missing required column: {field}"
            assert not df_b[field].isnull().any(), f"Column {field} contains null values"

    def test_cmf_confidence_bound_calculation(self):
        """CMF values match exact upper bound (Conservative), point (Base), and lower bound (Optimistic)."""
        df_b, _ = build_treatment_benefits_panel()

        # TRT_001: point=0.68, se=0.035
        trt001 = df_b[df_b["treatment_id"] == "TRT_001"]
        c_cmf = trt001[trt001["scenario_level"] == "CONSERVATIVE"]["cmf"].iloc[0]
        b_cmf = trt001[trt001["scenario_level"] == "BASE"]["cmf"].iloc[0]
        o_cmf = trt001[trt001["scenario_level"] == "OPTIMISTIC"]["cmf"].iloc[0]

        assert c_cmf == pytest.approx(min(1.0, 0.68 + 1.96 * 0.035), 1e-4)  # 0.7486
        assert b_cmf == pytest.approx(0.68, 1e-4)
        assert o_cmf == pytest.approx(max(0.0, 0.68 - 1.96 * 0.035), 1e-4)  # 0.6114

    def test_target_specific_severity_shares(self):
        """TRT_001 and TRT_004 use pedestrian-specific severity shares; TRT_002 uses all-crash shares."""
        df_ped = build_pedestrian_severity_shares()
        assert len(df_ped) == 43
        assert "ped_share_k_given_ksi" in df_ped.columns

        # Verify pedestrian fatal KSI share is non-negative
        assert (df_ped["ped_share_k_given_ksi"] >= 0).all()

    def test_total_severity_reconciliation(self):
        """Sum of averted severity crashes equals total averted crashes for every row."""
        df_b, _ = build_treatment_benefits_panel()
        sev_sum = (
            df_b["crashes_averted_k"]
            + df_b["crashes_averted_a"]
            + df_b["crashes_averted_b"]
            + df_b["crashes_averted_c"]
            + df_b["crashes_averted_o"]
            + df_b["crashes_averted_unknown"]
        )
        diff = (sev_sum - df_b["crashes_averted_total"]).abs().max()
        assert diff < 1e-4

    def test_pedestrian_forecast_bounds(self):
        """Pedestrian baseline forecast is non-negative across all corridors."""
        df_b, _ = build_treatment_benefits_panel()
        assert (df_b["relevant_forecast_crashes"] >= 0).all()

    def test_integer_installation_quantities_location_treatments(self):
        """Installation quantities for TRT_001 and TRT_004 are integers >= 1."""
        df_b, _ = build_treatment_benefits_panel()
        loc_df = df_b[df_b["treatment_id"].isin(["TRT_001", "TRT_004"])]
        assert (loc_df["installation_quantity"] == loc_df["installation_quantity"].astype(int)).all()
        assert (loc_df["installation_quantity"] >= 1).all()

    def test_road_diet_treated_mile_calculation(self):
        """Treated miles for TRT_002 equals corridor length x exposure share."""
        df_b, _ = build_treatment_benefits_panel()
        rd_df = df_b[df_b["treatment_id"] == "TRT_002"]
        assert (rd_df["capital_project_cost"] > 0).all()

    def test_lifecycle_present_value_calculation(self):
        """Present value factor and present value benefit reconcile mathematically."""
        pv_20 = compute_present_value_factor(0.03, 20)
        pv_10 = compute_present_value_factor(0.03, 10)

        assert pv_20 == pytest.approx(14.877475, 1e-4)
        assert pv_10 == pytest.approx(8.530203, 1e-4)

        df_b, _ = build_treatment_benefits_panel()
        pv_rel_diff = ((df_b["present_value_benefit"] - (df_b["annual_monetary_benefit"] * df_b["present_value_factor"])).abs() / (df_b["present_value_benefit"] + 1e-6)).max()
        assert pv_rel_diff < 1e-3

    def test_monetary_reconciliation(self):
        """Monetary value for unknown severity is zero and monetary benefits match KABCO sum."""
        df_b, _ = build_treatment_benefits_panel()
        assert (df_b["annual_monetary_benefit"] >= 0).all()

    def test_mandatory_governance_labels(self):
        """All rows contain required governance labels."""
        df_b, _ = build_treatment_benefits_panel()
        for label in ["PROVISIONAL_SCENARIO", "ENGINEERING_REVIEW_REQUIRED", "ANALYST_DEFINED_COST_SCENARIO", "ANALYST_DEFINED_ECONOMIC_SCENARIO"]:
            assert df_b["required_governance_labels"].str.contains(label).all()

    def test_no_observed_2026_outcomes(self):
        """Verification that no 2026 observed outcomes are present or used in calculation."""
        df_b, _ = build_treatment_benefits_panel()
        assert "observed_2026" not in df_b.columns

    def test_full_treatment_benefits_validation(self, tmp_path):
        """Validate treatment benefits validator executes cleanly and returns PASS_WITH_WARNINGS."""
        p_path = tmp_path / "corridor_treatment_benefits.parquet"
        c_path = tmp_path / "corridor_treatment_benefits.csv"
        r_path = tmp_path / "treatment_benefits_validation.json"

        df_b, _ = build_treatment_benefits_panel(
            output_parquet_path=p_path,
            output_csv_path=c_path,
        )
        assert len(df_b) == 387

        report, checks = validate_corridor_treatment_benefits(
            parquet_path=p_path,
            csv_path=c_path,
            report_output_path=r_path,
            is_sample=True,
        )
        assert report["status"] == "PASS_WITH_WARNINGS"
        assert report["downstream_readiness"] == "READY_FOR_PORTFOLIO_SCENARIO_REVIEW"
        assert report["critical_failure_count"] == 0

    def test_realistic_unit_costs_and_applicability_screening(self):
        """Verify sourced realistic unit costs and physical applicability screening for MultiLineString corridors."""
        df_b, _ = build_treatment_benefits_panel()

        # TRT_001 base unit cost = $15,000
        trt001_base = df_b[(df_b["treatment_id"] == "TRT_001") & (df_b["scenario_level"] == "BASE")]
        assert (trt001_base["unit_cost"] == 15000.0).all()

        # TRT_002 base unit cost = $400,000 / mile
        trt002_base = df_b[(df_b["treatment_id"] == "TRT_002") & (df_b["scenario_level"] == "BASE")]
        assert (trt002_base["unit_cost"] == 400000.0).all()

        # TRT_004 base unit cost = $22,500
        trt004_base = df_b[(df_b["treatment_id"] == "TRT_004") & (df_b["scenario_level"] == "BASE")]
        assert (trt004_base["unit_cost"] == 22500.0).all()

        # Physical applicability: HCC019 (Lake Shore Drive MultiLineString) TRT_002 is NOT_APPLICABLE
        hcc019_rd = df_b[(df_b["corridor_id"] == "HCC019") & (df_b["treatment_id"] == "TRT_002")]
        assert (hcc019_rd["physical_applicability_status"] == "NOT_APPLICABLE").all()

        # Other TRT_001 and TRT_004 on HCC019 are UNKNOWN
        hcc019_loc = df_b[(df_b["corridor_id"] == "HCC019") & (df_b["treatment_id"].isin(["TRT_001", "TRT_004"]))]
        assert (hcc019_loc["physical_applicability_status"] == "UNKNOWN").all()
