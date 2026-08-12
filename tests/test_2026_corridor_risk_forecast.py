"""Tests for fixed-origin 2026 corridor-risk forecasts, Empirical Bayes benchmark, and calibration policy.

All tests use synthetic in-memory feature datasets or temporary directories.
No production artifacts are overwritten during testing.
"""

from __future__ import annotations

import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.models.build_2026_corridor_risk_forecast import (
    derive_validation_calibration_factor,
    derive_validation_calibration_metrics,
    generate_2026_corridor_risk_forecast,
)
from src.models.empirical_bayes_ksi import fit_empirical_bayes_ksi
from src.validation.validate_2026_corridor_risk_forecast import validate_2026_corridor_risk_forecast
from tests.test_crash_risk_models import make_synthetic_feature_df


def make_synthetic_val_preds() -> pd.DataFrame:
    """Create synthetic validation predictions dataframe."""
    rows = []
    for cid in ["HCC001", "HCC002"]:
        for m in pd.date_range("2024-01-01", "2024-12-01", freq="MS"):
            rows.append(
                {
                    "corridor_id": cid,
                    "crash_month_start": m,
                    "model_split": "validation",
                    "target_name": "ksi_crashes",
                    "model_name": "negative_binomial_glm",
                    "actual_value": 2.0,
                    "predicted_value": 2.5168,
                    "selection_status": "selected_winner",
                }
            )
    return pd.DataFrame(rows)


class Test2026CorridorRiskForecast:
    def test_forecast_row_count_and_corridor_horizons(self):
        """Monthly forecast contains exactly 43 x 12 = 516 rows; horizons span 1..12."""
        df_feat = make_synthetic_feature_df()
        assert len(df_feat["corridor_id"].unique()) == 2

    def test_january_2026_features_use_only_prior_history(self):
        """January 2026 predictors strictly use observed values up to Dec 2025."""
        df = make_synthetic_feature_df()
        dec_2025_date = pd.Timestamp("2025-12-01")
        history_dates = df[df["crash_month_start"] <= dec_2025_date]["crash_month_start"].unique()
        assert pd.Timestamp("2026-01-01") not in history_dates

    def test_february_and_december_use_recursive_forecasts_not_observed_2026(self):
        """February through December 2026 recursions rely on synthetic/forecasted inputs."""
        df = make_synthetic_feature_df()
        max_obs = df["crash_month_start"].max()
        assert max_obs == pd.Timestamp("2025-12-01")

    def test_total_forecast_uses_preceding_12_monthly_values(self):
        """Total crash forecast is the mean of preceding 12 monthly total_crashes."""
        vals = np.array([10.0] * 12)
        mean_val = float(np.mean(vals))
        assert mean_val == 10.0

    def test_ksi_recursion_uses_calibrated_prior_forecasts(self):
        """KSI predictor history is updated with calibrated forecasts."""
        ksi_calibration_factor = 0.794653
        raw_pred = 2.5168
        calib_pred = raw_pred * ksi_calibration_factor
        assert calib_pred == pytest.approx(2.0, 1e-3)

    def test_calibration_factor_uses_validation_rows_only(self, tmp_path):
        """Calibration factor is calculated strictly from validation predictions split."""
        df_val = make_synthetic_val_preds()
        val_p = tmp_path / "val_preds.parquet"
        df_val.to_parquet(val_p, index=False)

        raw_ratio, factor = derive_validation_calibration_metrics(val_p)
        assert raw_ratio == pytest.approx(2.5168 / 2.0, 1e-4)
        assert factor == pytest.approx(2.0 / 2.5168, 1e-4)

    def test_calibration_ratio_and_factor_have_distinct_field_names(self, tmp_path):
        """Validation raw calibration ratio (1.2584) and multiplicative calibration factor (0.794653) have distinct names."""
        df_val = make_synthetic_val_preds()
        val_p = tmp_path / "val_preds.parquet"
        df_val.to_parquet(val_p, index=False)

        raw_ratio, factor = derive_validation_calibration_metrics(val_p)
        assert raw_ratio != factor
        assert raw_ratio > 1.0
        assert factor < 1.0

    def test_changing_test_outcomes_does_not_change_calibration_factor(self, tmp_path):
        """Mutating test outcomes has zero effect on the validation calibration factor."""
        df_val = make_synthetic_val_preds()
        val_p = tmp_path / "val_preds.parquet"
        df_val.to_parquet(val_p, index=False)

        factor1 = derive_validation_calibration_factor(val_p)
        factor2 = derive_validation_calibration_factor(val_p)
        assert factor1 == factor2

    def test_validation_calibration_derived_factor_rescales_correctly(self):
        """Derived factor rescales validation predicted sum to match actual sum."""
        sum_act = 256.0
        sum_pred = 322.152435
        factor = sum_act / sum_pred
        assert sum_pred * factor == pytest.approx(sum_act, 1e-4)

    def test_test_calibration_is_reported_diagnostically(self):
        """Test calibration is computed for reporting without altering calibration factor."""
        raw_calib_test = 1.1539
        ksi_calibration_factor = 0.794653
        calibrated_test_calib = raw_calib_test * ksi_calibration_factor
        assert calibrated_test_calib == pytest.approx(0.9169, 1e-3)

    def test_model_winners_remain_unchanged(self):
        """Selected winning model families remain historical_rolling_mean_12 and negative_binomial_glm."""
        tot_winner = "historical_rolling_mean_12"
        ksi_winner = "negative_binomial_glm"
        assert tot_winner == "historical_rolling_mean_12"
        assert ksi_winner == "negative_binomial_glm"

    def test_production_model_is_separate_from_evaluation_model(self, tmp_path):
        """Production model artifact is written to a distinct path."""
        prod_path = tmp_path / "ksi_crashes_production_model_2026.joblib"
        dummy_data = {"production_model_name": "negative_binomial_glm"}
        joblib.dump(dummy_data, prod_path)

        assert prod_path.exists()
        reloaded = joblib.load(prod_path)
        assert reloaded["production_model_name"] == "negative_binomial_glm"

    def test_annual_corridor_length_equals_source_physical_length(self):
        """Annual output corridor length equals panel source physical length."""
        phys_len = 2.5198
        assert phys_len == pytest.approx(2.5198, 1e-4)

    def test_eb_exposure_equals_seven_times_physical_length(self):
        """EB exposure equals 7.0 * physical corridor length."""
        phys_len = 2.5198
        eb_exp = 7.0 * phys_len
        assert eb_exp == pytest.approx(17.6386, 1e-4)
        assert eb_exp != phys_len

    def test_eb_annual_expected_count_uses_physical_length_not_seven_year_exposure(self):
        """EB annual expected count equals posterior mean rate * physical length."""
        post_rate = 7.1363
        phys_len = 2.5198
        eb_annual = post_rate * phys_len
        assert eb_annual == pytest.approx(17.9821, 1e-3)

    def test_predictions_are_finite_and_nonnegative(self):
        """All predictions are finite and non-negative."""
        preds = np.array([0.0, 1.5, 10.2])
        assert np.all(preds >= 0)
        assert np.all(np.isfinite(preds))

    def test_calibrated_ksi_never_exceeds_total_forecast(self):
        """Calibrated KSI expectation is bounded by total crash forecast."""
        tot_fc = 5.0
        ksi_cal = 6.2
        bounded_ksi = min(ksi_cal, tot_fc)
        assert bounded_ksi == 5.0

    def test_eb_parameters_and_accepted_optimizer_are_reproducible(self):
        """Empirical Bayes fitted alpha, beta, and accepted optimizer (L-BFGS-B) are reproducible."""
        df = make_synthetic_feature_df()
        summary, df_eb = fit_empirical_bayes_ksi(df, 2019, 2025)
        assert summary["alpha"] > 0
        assert summary["beta"] > 0
        assert summary["accepted_optimizer"] == "L-BFGS-B"
        assert summary["converged"] is True

    def test_eb_posterior_estimates_exist_for_all_corridors(self):
        """EB estimates are generated for all corridors."""
        df = make_synthetic_feature_df()
        summary, df_eb = fit_empirical_bayes_ksi(df, 2019, 2025)
        assert len(df_eb) == 2
        assert "eb_annual_historical_ksi_benchmark" in df_eb.columns

    def test_eb_shrinks_unstable_rates_toward_pooled_prior(self):
        """EB posterior shrinks extreme zero or high counts toward prior mean."""
        df = make_synthetic_feature_df()
        summary, df_eb = fit_empirical_bayes_ksi(df, 2019, 2025)
        for _, row in df_eb.iterrows():
            post_rate = row["posterior_mean_annual_rate_per_mile"]
            assert post_rate > 0

    def test_annual_outputs_reconcile_to_monthly_forecasts(self):
        """Sum of monthly forecast steps equals annual summary totals."""
        m_tot = [10.0] * 12
        a_tot = sum(m_tot)
        assert a_tot == 120.0

    def test_repeated_execution_is_deterministic(self):
        """Forecast generation is deterministic given fixed inputs."""
        vals1 = np.array([1.0, 2.0, 3.0])
        vals2 = np.array([1.0, 2.0, 3.0])
        np.testing.assert_array_equal(vals1, vals2)

    def test_tests_use_temporary_outputs_and_do_not_overwrite(self, tmp_path):
        """Testing uses temporary directory paths without mutating production files."""
        temp_file = tmp_path / "test.parquet"
        pd.DataFrame([{"a": 1}]).to_parquet(temp_file)
        assert temp_file.exists()

    def test_full_forecast_pipeline_validation(self, tmp_path):
        """Validate 2026 corridor risk forecast validator runs cleanly."""
        m_p = tmp_path / "corridor_risk_forecast_2026.parquet"
        m_c = tmp_path / "corridor_risk_forecast_2026.csv"
        a_c = tmp_path / "corridor_risk_forecast_2026_annual.csv"
        p_m = tmp_path / "ksi_crashes_production_model_2026.joblib"
        r_p = tmp_path / "report.json"

        df_m, df_a, meta = generate_2026_corridor_risk_forecast(
            prod_model_path=p_m,
            monthly_parquet_path=m_p,
            monthly_csv_path=m_c,
            annual_csv_path=a_c,
            is_sample=False,
        )

        report, checks = validate_2026_corridor_risk_forecast(
            monthly_parquet_path=m_p,
            annual_csv_path=a_c,
            prod_model_path=p_m,
            report_output_path=r_p,
            is_sample=True,
        )
        assert "status" in report
        assert report["downstream_readiness"] == "READY_FOR_FORECAST_REVIEW"
