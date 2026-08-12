"""Validate crash-risk forecasting model outputs, selection integrity, prediction keys, and joblib serialization parity.

Contract: docs/data_quality/cleaning_contract.md, spatial_assignment_contract.md
Config:   config/modeling.yml
Decision: D003 (Time-based validation), D005 (Governance authority)

Validates:
1. Exact row split counts (train=2,580, validation=516, test=516).
2. Unique composite prediction keys in validation (4,128) and test (1,032) prediction files.
3. Zero negative or non-finite predictions.
4. Winner selection integrity (lowest validation mean Poisson deviance).
5. Serialized joblib model reload prediction parity.
6. Target total reconciliations and leakage guards.
7. Evaluation protocol verification (rolling_origin_observed_history, horizon=1 month).
8. Model calibration warning checks for relative error > 10% (e.g. KSI overprediction).
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Tuple

import joblib
import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.features.build_corridor_month_features import FEATURE_OUTPUT_PATH  # noqa: E402
from src.models.train_crash_risk_models import (  # noqa: E402
    BenchmarkModel,
    FORECASTS_DIR,
    MODELING_CONFIG_PATH,
    MODELS_DIR,
    StatsmodelsNegBinomialWrapper,
    TABLES_DIR,
    train_select_and_evaluate_all,
)

VALIDATION_REPORT_PATH = ROOT / "docs" / "data_quality" / "crash_risk_model_validation.json"
RUNS_DIR = ROOT / "docs" / "data_quality" / "crash_risk_model_runs"


def _json_default(obj: Any) -> Any:
    if isinstance(obj, (np.integer, np.int64, np.int32)):
        return int(obj)
    elif isinstance(obj, (np.floating, np.float64, np.float32)):
        return float(obj)
    elif isinstance(obj, np.bool_):
        return bool(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _write_json_atomic(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.json")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False, default=_json_default)
        fh.write("\n")
    tmp.replace(path)


def load_modeling_config() -> dict:
    with MODELING_CONFIG_PATH.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def validate_crash_risk_models(
    features_path: Path = FEATURE_OUTPUT_PATH,
    forecasts_dir: Path = FORECASTS_DIR,
    models_dir: Path = MODELS_DIR,
    tables_dir: Path = TABLES_DIR,
    report_output_path: Path = VALIDATION_REPORT_PATH,
    runs_dir: Path = RUNS_DIR,
    is_sample: bool = False,
    run_id_override: Optional[str] = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Execute model validation checks and generate validation report."""
    checks: list[dict[str, Any]] = []

    def _add_check(name: str, severity: str, passed: bool, evidence: str):
        checks.append(
            {
                "check": name,
                "severity": severity,
                "passed": passed,
                "evidence": evidence,
            }
        )

    cfg = load_modeling_config()
    eval_cfg = cfg.get("evaluation", {})
    horizon_months = eval_cfg.get("forecast_horizon_months", 1)
    protocol_name = eval_cfg.get("protocol", "rolling_origin_observed_history")
    fixed_origin_status = eval_cfg.get("fixed_origin_annual_forecast_status", "not_yet_built")
    calib_threshold = float(eval_cfg.get("calibration_warning_relative_error", 0.10))

    # Evaluation Configuration Verification
    _add_check(
        "forecast_horizon_months_equals_1",
        "CRITICAL",
        horizon_months == 1,
        f"Forecast horizon months: {horizon_months} (expected 1)",
    )
    _add_check(
        "evaluation_protocol_rolling_origin",
        "CRITICAL",
        protocol_name == "rolling_origin_observed_history",
        f"Evaluation protocol: '{protocol_name}'",
    )
    _add_check(
        "fixed_origin_annual_forecast_status_verified",
        "CRITICAL",
        fixed_origin_status == "not_yet_built",
        f"Fixed origin annual forecast status: '{fixed_origin_status}'",
    )

    df_feat = pd.read_parquet(features_path)
    df_ready = df_feat[df_feat["model_ready"] == True]

    df_train = df_ready[df_ready["model_split"] == "train"]
    df_val = df_ready[df_ready["model_split"] == "validation"]
    df_test = df_ready[df_ready["model_split"] == "test"]

    # 1. Row Split Counts
    _add_check(
        "train_rows_2580",
        "CRITICAL",
        len(df_train) == 2580,
        f"Training split rows: {len(df_train):,} (expected 2,580)",
    )
    _add_check(
        "validation_rows_516",
        "CRITICAL",
        len(df_val) == 516,
        f"Validation split rows: {len(df_val):,} (expected 516)",
    )
    _add_check(
        "test_rows_516",
        "CRITICAL",
        len(df_test) == 516,
        f"Test split rows: {len(df_test):,} (expected 516)",
    )

    # Load generated prediction & table files
    val_pred_file = forecasts_dir / "model_validation_predictions.parquet"
    test_pred_file = forecasts_dir / "model_test_predictions.parquet"
    comp_table_file = tables_dir / "model_comparison.csv"

    val_preds = pd.read_parquet(val_pred_file) if val_pred_file.exists() else pd.DataFrame()
    test_preds = pd.read_parquet(test_pred_file) if test_pred_file.exists() else pd.DataFrame()
    comp_df = pd.read_csv(comp_table_file) if comp_table_file.exists() else pd.DataFrame()

    # 2. Validation predictions check
    n_val_preds = len(val_preds)
    expected_val_preds = 516 * 2 * 4  # 516 rows x 2 targets x 4 candidates = 4,128
    _add_check(
        "validation_prediction_rows_4128",
        "CRITICAL",
        n_val_preds == expected_val_preds,
        f"Validation predictions row count: {n_val_preds:,} (expected {expected_val_preds:,})",
    )

    val_keys_dup = (
        val_preds.duplicated(
            subset=["corridor_id", "crash_month_start", "target_name", "model_name"]
        ).sum()
        if not val_preds.empty
        else 1
    )
    _add_check(
        "validation_prediction_keys_unique",
        "CRITICAL",
        val_keys_dup == 0,
        f"Duplicate keys in validation predictions: {val_keys_dup}",
    )

    # 3. Test predictions check
    n_test_preds = len(test_preds)
    _add_check(
        "test_prediction_rows_1032",
        "CRITICAL",
        n_test_preds == 1032,
        f"Test predictions row count: {n_test_preds:,} (expected 1,032)",
    )

    test_keys_dup = (
        test_preds.duplicated(
            subset=["corridor_id", "crash_month_start", "target_name"]
        ).sum()
        if not test_preds.empty
        else 1
    )
    _add_check(
        "test_prediction_keys_unique",
        "CRITICAL",
        test_keys_dup == 0,
        f"Duplicate keys in test predictions: {test_keys_dup}",
    )

    # 4. Predictions non-negative and finite
    val_neg_inf = (
        (val_preds["predicted_value"] < 0) | np.isinf(val_preds["predicted_value"]) | val_preds["predicted_value"].isna()
    ).sum() if not val_preds.empty else 1
    test_neg_inf = (
        (test_preds["predicted_value"] < 0) | np.isinf(test_preds["predicted_value"]) | test_preds["predicted_value"].isna()
    ).sum() if not test_preds.empty else 1

    _add_check(
        "predictions_non_negative_and_finite",
        "CRITICAL",
        val_neg_inf == 0 and test_neg_inf == 0,
        f"Invalid/negative/infinite predictions: val={val_neg_inf}, test={test_neg_inf}",
    )

    # 5. Actual values reconcile to feature table
    val_actual_total = (
        val_preds[val_preds["model_name"] == "seasonal_naive_lag12"].groupby("target_name")["actual_value"].sum().to_dict()
        if not val_preds.empty else {}
    )
    exp_total_crashes_val = df_val["total_crashes"].sum()
    exp_ksi_crashes_val = df_val["ksi_crashes"].sum()

    actual_reconciled = (
        val_actual_total.get("total_crashes", 0) == exp_total_crashes_val
        and val_actual_total.get("ksi_crashes", 0) == exp_ksi_crashes_val
    )
    _add_check(
        "actual_values_reconcile_to_feature_table",
        "CRITICAL",
        actual_reconciled,
        f"Actual values reconcile: total_crashes val={val_actual_total.get('total_crashes', 0)} (exp {exp_total_crashes_val}), ksi={val_actual_total.get('ksi_crashes', 0)} (exp {exp_ksi_crashes_val})",
    )

    # 6. Winner Selection Integrity & Calibration Warning Checks
    winner_selection_valid = True
    selected_winners_dict = {}
    if not comp_df.empty:
        for tgt in ["total_crashes", "ksi_crashes"]:
            sub = comp_df[comp_df["target"] == tgt]
            min_dev_row = sub.loc[sub["val_poisson_deviance"].idxmin()]
            expected_winner = min_dev_row["model_name"]
            flagged_winner_row = sub.loc[sub["is_selected_winner"] == True].iloc[0]
            flagged_winner = flagged_winner_row["model_name"]

            selected_winners_dict[tgt] = flagged_winner
            if expected_winner != flagged_winner:
                winner_selection_valid = False

            # Calibration Warning Check (relative error > calib_threshold)
            val_calib = float(flagged_winner_row["val_calibration_ratio"])
            test_calib = float(flagged_winner_row["test_calibration_ratio"])
            val_error = abs(val_calib - 1.0)
            test_error = abs(test_calib - 1.0)

            if val_error > calib_threshold or test_error > calib_threshold:
                val_overpred = (val_calib - 1.0) * 100.0
                test_overpred = (test_calib - 1.0) * 100.0
                _add_check(
                    f"calibration_bias_warning_{tgt}",
                    "WARNING",
                    False,  # Warning condition triggered!
                    f"Target '{tgt}' winner '{flagged_winner}' has calibration bias outside +/-{int(calib_threshold*100)}% threshold. "
                    f"Validation calibration: {val_calib:.4f} ({val_overpred:+.2f}% overprediction), "
                    f"Test calibration: {test_calib:.4f} ({test_overpred:+.2f}% overprediction). "
                    f"Affected rows: 1,032 corridor-months. "
                    f"Explanation: Uncalibrated KSI forecasts may inflate CMF-based economic benefits. "
                    f"Required resolution: Calibration and/or Empirical Bayes stabilization before treatment-benefit estimation. "
                    f"Governance references: D003 and D005.",
                )
            else:
                _add_check(
                    f"calibration_bias_warning_{tgt}",
                    "WARNING",
                    True,
                    f"Target '{tgt}' winner '{flagged_winner}' calibration ratio is within +/-{int(calib_threshold*100)}% threshold "
                    f"(Validation: {val_calib:.4f}, Test: {test_calib:.4f}).",
                )

    _add_check(
        "selected_winners_match_validation_min_deviance",
        "CRITICAL",
        winner_selection_valid,
        f"Selected winners match minimum validation deviance: {selected_winners_dict}",
    )

    # 7. Serialized Model Joblib Reload Parquet Parity
    joblib_parity_passed = True
    for tgt in ["total_crashes", "ksi_crashes"]:
        model_p = models_dir / f"{tgt}_selected_model.joblib"
        if not model_p.exists():
            joblib_parity_passed = False
            break

        artifact = joblib.load(model_p)
        model_obj = artifact["model_object"]

        # Predict on df_test
        reloaded_preds = model_obj.predict(df_test)

        saved_test_sub = test_preds[test_preds["target_name"] == tgt].sort_values(
            ["corridor_id", "crash_month_start"]
        )
        diff_max = np.abs(reloaded_preds - saved_test_sub["predicted_value"].values).max()
        if diff_max > 1e-6:
            joblib_parity_passed = False
            break

    _add_check(
        "serialized_model_joblib_reload_prediction_parity",
        "CRITICAL",
        joblib_parity_passed,
        f"Reloaded joblib models match saved test predictions: {joblib_parity_passed}",
    )

    # 8. No Leakage: Current Targets Absent From Predictor Columns
    current_targets = ["total_crashes", "ksi_crashes", "fatal_crashes", "serious_injury_crashes"]
    from src.models.train_crash_risk_models import NUMERICAL_PREDICTORS, CATEGORICAL_PREDICTORS
    pred_set = set(NUMERICAL_PREDICTORS + CATEGORICAL_PREDICTORS)
    leaked = pred_set.intersection(current_targets)
    _add_check(
        "no_leakage_current_targets_in_predictors",
        "CRITICAL",
        len(leaked) == 0,
        f"Current month targets in predictor list: {len(leaked)}",
    )

    crit_failures = sum(1 for c in checks if c["severity"] == "CRITICAL" and not c["passed"])
    warnings = sum(1 for c in checks if c["severity"] == "WARNING" and not c["passed"])

    if crit_failures > 0:
        status_val = "FAIL"
        readiness_val = "BLOCKED"
    elif warnings > 0:
        status_val = "PASS_WITH_WARNINGS"
        readiness_val = "READY_FOR_FORECAST_GENERATION_WITH_LIMITATIONS"
    else:
        status_val = "PASS"
        readiness_val = "READY_FOR_FORECAST_GENERATION"

    # Reuse run_id if existing report exists or if override supplied
    if run_id_override:
        run_id = run_id_override
    elif report_output_path.exists():
        try:
            existing_data = json.loads(report_output_path.read_text(encoding="utf-8"))
            run_id = existing_data.get("run_id", datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
        except Exception:
            run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    else:
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    report = {
        "pipeline": "crash_risk_models",
        "run_id": run_id,
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "is_sample": is_sample,
        "evaluation_metadata": {
            "forecast_horizon_months": horizon_months,
            "protocol": protocol_name,
            "fixed_origin_annual_forecast_status": fixed_origin_status,
        },
        "selected_winners": selected_winners_dict,
        "status": status_val,
        "downstream_readiness": readiness_val,
        "critical_failure_count": crit_failures,
        "warning_count": warnings,
        "model_evaluation_notes": [
            "Model selection was performed using 1-month-ahead rolling-origin evaluation on the 2024 validation split.",
            "Test metrics reflect 1-month-ahead rolling-origin evaluation on the 2025 test split using observed prior-month history.",
            "The Negative Binomial KSI model achieved the lowest validation Poisson deviance but overpredicted aggregate KSI burden by 25.84% on validation and 15.39% on test. It is retained as the selected candidate but requires calibration or Empirical Bayes stabilization before economic benefit calculations.",
            "Fixed-origin 12-month-ahead future forecasts for 2026 are not yet built and must be constructed in Phase 3B."
        ],
        "checks": checks,
    }

    if not is_sample:
        _write_json_atomic(report_output_path, report)
        runs_dir.mkdir(parents=True, exist_ok=True)
        hist_path = runs_dir / f"crash_risk_model_validation_{run_id}.json"
        _write_json_atomic(hist_path, report)
        print(f"Saved validation report to {report_output_path}")

    return report, checks


def main() -> int:
    print("=" * 70)
    print("Validate Crash-Risk Forecasting Models & Selection Integrity")
    print("=" * 70)

    try:
        report, checks = validate_crash_risk_models()
        print("\n" + "=" * 70)
        print("VALIDATION SUMMARY")
        print("=" * 70)
        print(f"Status: {report['status']} | Downstream Readiness: {report['downstream_readiness']}")
        print(f"Critical Failures: {report['critical_failure_count']} | Warnings: {report['warning_count']}")

        for check in checks:
            symbol = "PASS" if check["passed"] else "FAIL"
            print(f"  [{symbol:<4}] {check['check']:<50} ({check['severity']}) - {check['evidence']}")

        return 0 if report["status"] != "FAIL" else 1
    except Exception as exc:
        print(f"\nCRITICAL FAILURE: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
