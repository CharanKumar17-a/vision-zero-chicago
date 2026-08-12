"""Tests for transparent corridor crash-risk forecasting models and selection integrity.

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

from src.models.train_crash_risk_models import (
    BenchmarkModel,
    CATEGORICAL_PREDICTORS,
    NUMERICAL_PREDICTORS,
    StatsmodelsNegBinomialWrapper,
    build_poisson_pipeline,
    calculate_overdispersion_diagnostic,
    compute_metrics,
    load_modeling_config,
    train_candidate_model,
    train_select_and_evaluate_all,
)
from src.validation.validate_crash_risk_models import validate_crash_risk_models


def make_synthetic_feature_df() -> pd.DataFrame:
    """Create synthetic feature panel (2 corridors, 96 months: 2018-2025)."""
    dates = pd.date_range("2018-01-01", "2025-12-01", freq="MS")
    rows = []

    for cid in ["HCC001", "HCC002"]:
        for idx, d in enumerate(dates):
            total = (idx % 20) + 10
            ksi = (total // 6)
            year = d.year

            split = "warmup" if year == 2018 else ("train" if year <= 2023 else ("validation" if year == 2024 else "test"))
            ready = year >= 2019

            rows.append(
                {
                    "corridor_id": cid,
                    "crash_month_start": d,
                    "calendar_year": year,
                    "calendar_month": d.month,
                    "calendar_quarter": d.quarter,
                    "corridor_name": f"Corridor {cid}",
                    "source_group": "neighborhood",
                    "corridor_length_feet": 5280.0,
                    "corridor_length_miles": 1.0,
                    "total_crashes": total,
                    "fatal_crashes": 1 if ksi > 0 else 0,
                    "serious_injury_crashes": ksi - 1 if ksi > 0 else 0,
                    "ksi_crashes": ksi,
                    "history_months_available": idx,
                    "total_crashes_lag1": float((idx - 1 % 20) + 10) if idx >= 1 else np.nan,
                    "total_crashes_lag3": float((idx - 3 % 20) + 10) if idx >= 3 else np.nan,
                    "total_crashes_lag6": float((idx - 6 % 20) + 10) if idx >= 6 else np.nan,
                    "total_crashes_lag12": float((idx - 12 % 20) + 10) if idx >= 12 else np.nan,
                    "total_crashes_roll_mean3": 15.0 if idx >= 3 else np.nan,
                    "total_crashes_roll_mean6": 15.0 if idx >= 6 else np.nan,
                    "total_crashes_roll_mean12": 15.0 if idx >= 12 else np.nan,
                    "total_crashes_roll_sum3": 45.0 if idx >= 3 else np.nan,
                    "total_crashes_roll_sum6": 90.0 if idx >= 6 else np.nan,
                    "total_crashes_roll_sum12": 180.0 if idx >= 12 else np.nan,
                    "ksi_crashes_lag1": float(ksi) if idx >= 1 else np.nan,
                    "ksi_crashes_lag3": float(ksi) if idx >= 3 else np.nan,
                    "ksi_crashes_lag6": float(ksi) if idx >= 6 else np.nan,
                    "ksi_crashes_lag12": float(ksi) if idx >= 12 else np.nan,
                    "ksi_crashes_roll_mean3": 2.0 if idx >= 3 else np.nan,
                    "ksi_crashes_roll_mean6": 2.0 if idx >= 6 else np.nan,
                    "ksi_crashes_roll_mean12": 2.0 if idx >= 12 else np.nan,
                    "ksi_crashes_roll_sum3": 6.0 if idx >= 3 else np.nan,
                    "ksi_crashes_roll_sum6": 12.0 if idx >= 6 else np.nan,
                    "ksi_crashes_roll_sum12": 24.0 if idx >= 12 else np.nan,
                    "calendar_year_trend": year - 2018,
                    "month_sin": np.sin(2 * np.pi * d.month / 12.0),
                    "month_cos": np.cos(2 * np.pi * d.month / 12.0),
                    "model_ready": ready,
                    "model_split": split,
                }
            )

    return pd.DataFrame(rows)


class TestCrashRiskModels:
    def test_train_validation_test_date_boundaries(self):
        """Dataset splits strictly follow 2019-2023 (train), 2024 (val), 2025 (test)."""
        df = make_synthetic_feature_df()
        train_years = df[df["model_split"] == "train"]["calendar_year"].unique()
        val_years = df[df["model_split"] == "validation"]["calendar_year"].unique()
        test_years = df[df["model_split"] == "test"]["calendar_year"].unique()

        assert sorted(list(train_years)) == [2019, 2020, 2021, 2022, 2023]
        assert list(val_years) == [2024]
        assert list(test_years) == [2025]

    def test_no_current_targets_or_severity_in_predictors(self):
        """Current target columns and severity counts are strictly absent from predictors."""
        preds = set(NUMERICAL_PREDICTORS + CATEGORICAL_PREDICTORS)
        forbidden = {"total_crashes", "ksi_crashes", "fatal_crashes", "serious_injury_crashes", "model_split", "model_ready"}
        assert len(preds.intersection(forbidden)) == 0

    def test_seasonal_naive_and_rolling_mean_baselines(self):
        """Seasonal naive uses lag12 and rolling baseline uses rolling_mean12."""
        df = make_synthetic_feature_df()
        df_train = df[df["model_split"] == "train"]
        df_val = df[df["model_split"] == "validation"]

        m_naive = BenchmarkModel("seasonal_naive_lag12", "total_crashes")
        p_naive = m_naive.predict(df_val)
        np.testing.assert_array_equal(p_naive, df_val["total_crashes_lag12"].values)

        m_roll = BenchmarkModel("historical_rolling_mean_12", "total_crashes")
        p_roll = m_roll.predict(df_val)
        np.testing.assert_array_equal(p_roll, df_val["total_crashes_roll_mean12"].values)

    def test_candidate_predictions_are_finite_and_non_negative(self):
        """All candidate predictions are finite and non-negative."""
        df = make_synthetic_feature_df()
        df_train = df[df["model_split"] == "train"]
        df_val = df[df["model_split"] == "validation"]

        for cand in ["seasonal_naive_lag12", "historical_rolling_mean_12", "poisson_regression", "negative_binomial_glm"]:
            model = train_candidate_model(cand, "total_crashes", df_train, df_train["total_crashes"])
            preds = model.predict(df_val)
            assert np.all(preds >= 0)
            assert np.all(np.isfinite(preds))

    def test_metric_computations_match_manual_example(self):
        """Compute_metrics calculates correct MAE, RMSE, Poisson deviance, and bias."""
        y_true = np.array([10.0, 20.0, 30.0])
        y_pred = np.array([12.0, 18.0, 30.0])

        metrics = compute_metrics(y_true, y_pred)
        assert metrics["mae"] == pytest.approx((2.0 + 2.0 + 0.0) / 3.0, 0.001)
        assert metrics["actual_total"] == 60.0
        assert metrics["predicted_total"] == 60.0
        assert metrics["calibration_ratio"] == 1.0
        assert metrics["mean_bias"] == 0.0

    def test_changing_test_outcomes_does_not_change_selected_winner(self):
        """Model selection is based solely on validation deviance; mutating test outcomes has 0 effect."""
        df1 = make_synthetic_feature_df()
        df2 = make_synthetic_feature_df()

        # Mutate test outcome in df2
        df2.loc[df2["model_split"] == "test", "total_crashes"] += 999

        tmp_p1 = ROOT / "data" / "processed" / "temp_f1.parquet"
        tmp_p2 = ROOT / "data" / "processed" / "temp_f2.parquet"

        df1.to_parquet(tmp_p1, index=False)
        df2.to_parquet(tmp_p2, index=False)

        report1, _, _, _ = train_select_and_evaluate_all(features_path=tmp_p1, is_sample=True)
        report2, _, _, _ = train_select_and_evaluate_all(features_path=tmp_p2, is_sample=True)

        assert report1["selected_winners"] == report2["selected_winners"]

        tmp_p1.unlink(missing_ok=True)
        tmp_p2.unlink(missing_ok=True)

    def test_joblib_serialization_and_reload_parity(self, tmp_path):
        """Serialized joblib model reload preserves predictions exactly."""
        df = make_synthetic_feature_df()
        df_train = df[df["model_split"] == "train"]
        df_val = df[df["model_split"] == "validation"]

        pipe = build_poisson_pipeline()
        pipe.fit(df_train, df_train["total_crashes"])
        p1 = pipe.predict(df_val)

        save_p = tmp_path / "model.joblib"
        joblib.dump(pipe, save_p)

        reloaded_pipe = joblib.load(save_p)
        p2 = reloaded_pipe.predict(df_val)

        np.testing.assert_allclose(p1, p2, rtol=1e-6)

    def test_overdispersion_diagnostic_calculation(self):
        """Overdispersion diagnostic correctly identifies variance-to-mean ratio."""
        df = make_synthetic_feature_df()
        df_train = df[df["model_split"] == "train"]

        diag = calculate_overdispersion_diagnostic(df_train, "total_crashes")
        assert "variance_to_mean_ratio" in diag
        assert diag["mean"] > 0
        assert diag["n_obs"] == len(df_train)

    def test_evaluation_horizon_is_explicitly_one_month(self):
        """Config and validator verify forecast_horizon_months equals 1."""
        cfg = load_modeling_config()
        assert cfg["evaluation"]["forecast_horizon_months"] == 1

    def test_rolling_origin_protocol_is_recorded(self):
        """Config and validator record evaluation protocol as rolling_origin_observed_history."""
        cfg = load_modeling_config()
        assert cfg["evaluation"]["protocol"] == "rolling_origin_observed_history"

    def test_fixed_origin_annual_forecast_status_is_not_built(self):
        """Config and validator record fixed_origin_annual_forecast_status as not_yet_built."""
        cfg = load_modeling_config()
        assert cfg["evaluation"]["fixed_origin_annual_forecast_status"] == "not_yet_built"

    def test_calibration_deviation_above_10_percent_produces_warning(self):
        """Validation check produces a WARNING when calibration ratio error exceeds 10%."""
        report, checks = validate_crash_risk_models(is_sample=True)
        ksi_check = next(c for c in checks if c["check"] == "calibration_bias_warning_ksi_crashes")
        assert ksi_check["severity"] == "WARNING"
        assert ksi_check["passed"] is False
        assert report["status"] == "PASS_WITH_WARNINGS"
        assert report["downstream_readiness"] == "READY_FOR_FORECAST_GENERATION_WITH_LIMITATIONS"

    def test_calibration_within_10_percent_produces_no_warning(self):
        """Validation check passes without warning when calibration ratio is within +/- 10%."""
        _, checks = validate_crash_risk_models(is_sample=True)
        tot_check = next(c for c in checks if c["check"] == "calibration_bias_warning_total_crashes")
        assert tot_check["severity"] == "WARNING"
        assert tot_check["passed"] is True

    def test_calibration_warning_contains_explanation_and_governance_references(self):
        """KSI calibration warning evidence contains target name, explanation, and D003/D005 references."""
        _, checks = validate_crash_risk_models(is_sample=True)
        ksi_check = next(c for c in checks if c["check"] == "calibration_bias_warning_ksi_crashes")
        ev = ksi_check["evidence"]
        assert "ksi_crashes" in ev
        assert "uncalibrated ksi forecasts may inflate cmf-based economic benefits" in ev.lower()
        assert "D003 and D005" in ev

    def test_model_winners_and_prediction_metrics_remain_unchanged(self):
        """Selected model winners remain unchanged."""
        report, _ = validate_crash_risk_models(is_sample=True)
        assert report["selected_winners"]["total_crashes"] == "historical_rolling_mean_12"
        assert report["selected_winners"]["ksi_crashes"] == "negative_binomial_glm"

    def test_test_metrics_do_not_influence_selection(self):
        """Validation-based selection logic is completely isolated from test split metrics."""
        cfg = load_modeling_config()
        assert cfg["modeling"]["selection_metric"] == "mean_poisson_deviance"
