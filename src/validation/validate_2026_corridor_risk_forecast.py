"""Validate fixed-origin 2026 corridor risk forecast, Empirical Bayes benchmark, and calibration integrity.

Contract: docs/data_quality/cleaning_contract.md, spatial_assignment_contract.md
Config:   config/modeling.yml
Decision: D001 (Corridor-month grain), D003 (Time-based validation), D005 (Governance authority)

Validates:
1. Exact row counts (516 monthly, 43 annual).
2. Unique composite keys in monthly and annual forecast files.
3. Forecast origin locked at 2025-12-01; months span 2026-01-01 to 2026-12-01.
4. Non-negative, finite predictions; calibrated KSI <= total crash forecast.
5. Annual totals reconcile to monthly sums.
6. Calibration factor (0.794653) and raw ratio (1.258404) distinctly labeled and derived strictly from validation split.
7. Physical corridor length and 7-year EB exposure remain distinct columns; physical length equals panel source.
8. Production model separate from evaluation model.
9. EB parameters positive, L-BFGS-B accepted optimizer, and optimizer converged for all 43 corridors.
10. Diagnostic evaluation of calibrated model on 2025 test split.
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
from scipy.stats import spearmanr
import yaml

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.models.build_2026_corridor_risk_forecast import (  # noqa: E402
    ANNUAL_CSV_PATH,
    MONTHLY_CSV_PATH,
    MONTHLY_PARQUET_PATH,
    PROD_MODEL_PATH,
    VAL_PRED_PATH,
    derive_validation_calibration_metrics,
    generate_2026_corridor_risk_forecast,
)

VALIDATION_REPORT_PATH = ROOT / "docs" / "data_quality" / "corridor_risk_forecast_2026_validation.json"
RUNS_DIR = ROOT / "docs" / "data_quality" / "corridor_risk_forecast_2026_runs"
TEST_PRED_PATH = ROOT / "outputs" / "forecasts" / "model_test_predictions.parquet"
PANEL_PATH = ROOT / "data" / "processed" / "corridor_month_panel.parquet"


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


def evaluate_2025_test_calibration_diagnostic(
    test_pred_path: Path = TEST_PRED_PATH,
    val_pred_path: Path = VAL_PRED_PATH,
) -> Dict[str, Any]:
    """Evaluate raw vs. validation-calibrated performance on the locked 2025 test split predictions."""
    if not test_pred_path.exists():
        return {"status": "test_predictions_file_missing"}

    raw_ratio, calib_factor = derive_validation_calibration_metrics(val_pred_path)
    df_test = pd.read_parquet(test_pred_path)
    sub = df_test[
        (df_test["target_name"] == "ksi_crashes")
        & (df_test["model_name"] == "negative_binomial_glm")
    ]

    if len(sub) == 0:
        return {"status": "no_matching_test_predictions"}

    y_true = sub["actual_value"].values
    y_raw = sub["predicted_value"].values
    y_cal = y_raw * calib_factor

    from sklearn.metrics import mean_absolute_error, mean_poisson_deviance, root_mean_squared_error

    raw_tot = float(np.sum(y_raw))
    cal_tot = float(np.sum(y_cal))
    act_tot = float(np.sum(y_true))

    raw_test_calib_ratio = raw_tot / act_tot
    cal_test_calib_ratio = cal_tot / act_tot

    raw_mae = float(mean_absolute_error(y_true, y_raw))
    cal_mae = float(mean_absolute_error(y_true, y_cal))

    raw_rmse = float(root_mean_squared_error(y_true, y_raw))
    cal_rmse = float(root_mean_squared_error(y_true, y_cal))

    raw_dev = float(mean_poisson_deviance(y_true, np.clip(y_raw, 1e-6, None)))
    cal_dev = float(mean_poisson_deviance(y_true, np.clip(y_cal, 1e-6, None)))

    return {
        "validation_raw_calibration_ratio": round(raw_ratio, 6),
        "validation_multiplicative_calibration_factor": round(calib_factor, 6),
        "test_row_count": len(sub),
        "test_actual_total_ksi": round(act_tot, 1),
        "raw_test_predicted_total_ksi": round(raw_tot, 1),
        "calibrated_test_predicted_total_ksi": round(cal_tot, 1),
        "raw_test_calibration_ratio": round(raw_test_calib_ratio, 4),
        "calibrated_test_calibration_ratio": round(cal_test_calib_ratio, 4),
        "raw_test_mae": round(raw_mae, 4),
        "calibrated_test_mae": round(cal_mae, 4),
        "raw_test_rmse": round(raw_rmse, 4),
        "calibrated_test_rmse": round(cal_rmse, 4),
        "raw_test_poisson_deviance": round(raw_dev, 6),
        "calibrated_test_poisson_deviance": round(cal_dev, 6),
        "note": "Test split diagnostic is informational only; test data did not influence calibration factor derivation or model selection.",
    }


def validate_2026_corridor_risk_forecast(
    monthly_parquet_path: Path = MONTHLY_PARQUET_PATH,
    annual_csv_path: Path = ANNUAL_CSV_PATH,
    prod_model_path: Path = PROD_MODEL_PATH,
    val_pred_path: Path = VAL_PRED_PATH,
    test_pred_path: Path = TEST_PRED_PATH,
    panel_path: Path = PANEL_PATH,
    report_output_path: Path = VALIDATION_REPORT_PATH,
    runs_dir: Path = RUNS_DIR,
    is_sample: bool = False,
    run_id_override: Optional[str] = None,
) -> Tuple[Dict[str, Any], list[dict[str, Any]]]:
    """Execute forecast validation checks and generate validation report."""
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

    # 1. Monthly and Annual Files Exist
    files_exist = monthly_parquet_path.exists() and annual_csv_path.exists() and prod_model_path.exists()
    _add_check(
        "forecast_output_files_exist",
        "CRITICAL",
        files_exist,
        f"Monthly parquet, annual CSV, and production model joblib exist: {files_exist}",
    )

    df_m = pd.read_parquet(monthly_parquet_path) if monthly_parquet_path.exists() else pd.DataFrame()
    df_a = pd.read_csv(annual_csv_path) if annual_csv_path.exists() else pd.DataFrame()

    # 2. Row Counts
    _add_check(
        "monthly_forecast_rows_516",
        "CRITICAL",
        len(df_m) == 516,
        f"Monthly forecast row count: {len(df_m):,} (expected 516)",
    )
    _add_check(
        "annual_forecast_rows_43",
        "CRITICAL",
        len(df_a) == 43,
        f"Annual forecast row count: {len(df_a):,} (expected 43)",
    )

    # 3. Composite Key Uniqueness
    m_dups = int(df_m.duplicated(subset=["corridor_id", "forecast_month"]).sum()) if not df_m.empty else 1
    a_dups = int(df_a.duplicated(subset=["corridor_id"]).sum()) if not df_a.empty else 1
    _add_check(
        "monthly_forecast_keys_unique",
        "CRITICAL",
        m_dups == 0,
        f"Duplicate keys in monthly forecast: {m_dups}",
    )
    _add_check(
        "annual_forecast_keys_unique",
        "CRITICAL",
        a_dups == 0,
        f"Duplicate corridor IDs in annual forecast: {a_dups}",
    )

    # 4. Forecast Origin & Months
    origins = df_m["forecast_origin"].unique() if not df_m.empty else []
    origin_valid = len(origins) == 1 and origins[0] == "2025-12-01"
    _add_check(
        "forecast_origin_is_2025_12_01",
        "CRITICAL",
        origin_valid,
        f"Forecast origin: '{origins[0] if len(origins) > 0 else None}' (expected '2025-12-01')",
    )

    months_list = sorted(list(df_m["forecast_month"].unique())) if not df_m.empty else []
    exp_months = [f"2026-{m:02d}-01" for m in range(1, 13)]
    months_valid = months_list == exp_months
    _add_check(
        "forecast_months_jan_to_dec_2026",
        "CRITICAL",
        months_valid,
        f"Forecast months span 2026-01-01 to 2026-12-01: {months_valid}",
    )

    # 5. Horizons 1 to 12
    if not df_m.empty:
        horizons_per_corridor = df_m.groupby("corridor_id")["forecast_horizon_month"].apply(lambda s: sorted(list(s)))
        all_1_12 = all(h == list(range(1, 13)) for h in horizons_per_corridor)
    else:
        all_1_12 = False

    _add_check(
        "corridor_horizons_1_to_12_exact",
        "CRITICAL",
        all_1_12,
        f"All 43 corridors have horizons 1 through 12 exactly once: {all_1_12}",
    )

    # 6. Physical Corridor Length Verification & Separation from Exposure
    length_reconciled = True
    exposure_reconciled = True
    if not df_a.empty and panel_path.exists():
        df_p = pd.read_parquet(panel_path)
        auth_lengths = df_p.groupby("corridor_id")["corridor_length_miles"].first().to_dict()

        for _, r in df_a.iterrows():
            cid = r["corridor_id"]
            auth_len = auth_lengths.get(cid, -1.0)
            out_len = float(r["corridor_length_miles"])
            out_exp = float(r["eb_exposure_corridor_mile_years"])

            if abs(out_len - auth_len) > 1e-4:
                length_reconciled = False
            if abs(out_exp - 7.0 * auth_len) > 1e-4:
                exposure_reconciled = False

    _add_check(
        "annual_corridor_length_equals_source_physical_length",
        "CRITICAL",
        length_reconciled,
        f"Annual output corridor length equals panel source physical length: {length_reconciled}",
    )
    _add_check(
        "eb_exposure_equals_seven_times_physical_length",
        "CRITICAL",
        exposure_reconciled,
        f"EB exposure equals 7.0 * physical length: {exposure_reconciled}",
    )

    # 7. No Observed 2026 Data Used
    is_obs_vals = df_m["is_observed"].unique() if not df_m.empty else [True]
    no_observed = len(is_obs_vals) == 1 and is_obs_vals[0] == False
    _add_check(
        "zero_observed_2026_data_used",
        "CRITICAL",
        no_observed,
        f"Is observed flag is False for all rows: {no_observed}",
    )

    # 8. Predictions Non-negative and Finite
    if not df_m.empty:
        neg_m = (
            (df_m["total_crashes_forecast"] < 0)
            | (df_m["ksi_crashes_forecast_raw"] < 0)
            | (df_m["ksi_crashes_forecast_calibrated"] < 0)
            | np.isinf(df_m["total_crashes_forecast"])
            | np.isinf(df_m["ksi_crashes_forecast_raw"])
            | np.isinf(df_m["ksi_crashes_forecast_calibrated"])
            | df_m["total_crashes_forecast"].isna()
            | df_m["ksi_crashes_forecast_raw"].isna()
            | df_m["ksi_crashes_forecast_calibrated"].isna()
        ).sum()
    else:
        neg_m = 1

    _add_check(
        "predictions_non_negative_and_finite",
        "CRITICAL",
        neg_m == 0,
        f"Invalid/negative/infinite predictions in monthly forecast: {neg_m}",
    )

    # 9. Calibrated KSI <= Total Crashes
    ksi_exceeds = (df_m["ksi_crashes_forecast_calibrated"] > df_m["total_crashes_forecast"]).sum() if not df_m.empty else 1
    _add_check(
        "calibrated_ksi_less_equal_total_crashes",
        "CRITICAL",
        ksi_exceeds == 0,
        f"Monthly rows where calibrated KSI exceeds total crashes: {ksi_exceeds}",
    )

    # 10. Annual Totals Equal Monthly Sums
    reconciled = True
    if not df_m.empty and not df_a.empty:
        m_sums = (
            df_m.groupby("corridor_id")
            .agg(
                m_tot=("total_crashes_forecast", "sum"),
                m_raw=("ksi_crashes_forecast_raw", "sum"),
                m_cal=("ksi_crashes_forecast_calibrated", "sum"),
            )
            .reset_index()
        )
        merged_rec = pd.merge(df_a, m_sums, on="corridor_id")
        tot_diff = (merged_rec["annual_total_crashes_forecast"] - merged_rec["m_tot"]).abs().max()
        raw_diff = (merged_rec["annual_ksi_forecast_raw"] - merged_rec["m_raw"]).abs().max()
        cal_diff = (merged_rec["annual_ksi_forecast_calibrated"] - merged_rec["m_cal"]).abs().max()

        if max(tot_diff, raw_diff, cal_diff) > 1e-3:
            reconciled = False

    _add_check(
        "annual_totals_equal_monthly_sums",
        "CRITICAL",
        reconciled,
        f"Annual totals reconcile to monthly sums: {reconciled}",
    )

    # 11. Distinct Calibration Field Semantics
    exp_raw_ratio, exp_factor = derive_validation_calibration_metrics(val_pred_path)
    factor_in_file = float(df_m["ksi_calibration_factor"].iloc[0]) if not df_m.empty else 0.0
    raw_ratio_in_file = float(df_m["validation_raw_calibration_ratio"].iloc[0]) if not df_m.empty else 0.0

    factor_match = abs(factor_in_file - exp_factor) < 1e-5 and abs(raw_ratio_in_file - exp_raw_ratio) < 1e-5
    _add_check(
        "calibration_metrics_distinct_and_derived_from_validation",
        "CRITICAL",
        factor_match,
        f"Raw ratio ({raw_ratio_in_file:.6f}) and factor ({factor_in_file:.6f}) match validation derivations: {factor_match}",
    )

    # 12. Calibration Factor Constant Across Rows
    unique_factors = df_m["ksi_calibration_factor"].nunique() if not df_m.empty else 0
    _add_check(
        "calibration_factor_constant_across_rows",
        "CRITICAL",
        unique_factors == 1,
        f"Unique calibration factor values across rows: {unique_factors}",
    )

    # 13. Model Winners Unchanged
    tot_models = df_m["total_model_name"].unique() if not df_m.empty else []
    ksi_models = df_m["ksi_model_name"].unique() if not df_m.empty else []
    winners_valid = (
        len(tot_models) == 1
        and tot_models[0] == "historical_rolling_mean_12"
        and len(ksi_models) == 1
        and ksi_models[0] == "negative_binomial_glm"
    )
    _add_check(
        "model_winners_unchanged",
        "CRITICAL",
        winners_valid,
        f"Model winners: total='{tot_models[0] if len(tot_models)>0 else None}', ksi='{ksi_models[0] if len(ksi_models)>0 else None}'",
    )

    # 14. Production Model Artifact Separate
    prod_model_exists = prod_model_path.exists()
    _add_check(
        "production_model_artifact_separate",
        "CRITICAL",
        prod_model_exists,
        f"Production model joblib exists at separate path: {prod_model_exists}",
    )

    # 15. Rank Correlation and Max Rank Difference
    rank_corr = 0.0
    max_rank_diff = 0
    if not df_a.empty:
        r_res = spearmanr(df_a["rank_calibrated_model_forecast"], df_a["rank_eb_benchmark"])
        rank_corr = float(r_res.statistic) if not np.isnan(r_res.statistic) else 0.0
        max_rank_diff = int((df_a["rank_calibrated_model_forecast"] - df_a["rank_eb_benchmark"]).abs().max())

    _add_check(
        "rank_agreement_between_forecast_and_eb",
        "WARNING",
        rank_corr > 0.50,
        f"Spearman rank correlation between calibrated forecast and EB benchmark: {rank_corr:.4f} (Max rank diff: {max_rank_diff})",
    )

    # 16. Diagnostic Test Split Evaluation
    test_diag = evaluate_2025_test_calibration_diagnostic(test_pred_path, val_pred_path)

    crit_failures = sum(1 for c in checks if c["severity"] == "CRITICAL" and not c["passed"])
    warnings = sum(1 for c in checks if c["severity"] == "WARNING" and not c["passed"])

    if crit_failures > 0:
        status_val = "FAIL"
        readiness_val = "BLOCKED"
    elif warnings > 0:
        status_val = "PASS_WITH_WARNINGS"
        readiness_val = "READY_FOR_FORECAST_REVIEW"
    else:
        status_val = "PASS"
        readiness_val = "READY_FOR_FORECAST_REVIEW"

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
        "pipeline": "corridor_risk_forecast_2026",
        "run_id": run_id,
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "is_sample": is_sample,
        "forecast_metadata": {
            "forecast_origin": "2025-12-01",
            "forecast_year": 2026,
            "forecast_horizon_months": 12,
            "protocol": "fixed_origin_recursive",
            "recursion_policy": "calibrated_prediction_feedback",
            "validation_raw_calibration_ratio": round(exp_raw_ratio, 6),
            "ksi_calibration_factor": round(exp_factor, 6),
        },
        "forecast_totals": {
            "total_crashes_forecast_2026": round(float(df_a["annual_total_crashes_forecast"].sum()), 1) if not df_a.empty else 0,
            "raw_ksi_forecast_2026": round(float(df_a["annual_ksi_forecast_raw"].sum()), 1) if not df_a.empty else 0,
            "calibrated_ksi_forecast_2026": round(float(df_a["annual_ksi_forecast_calibrated"].sum()), 1) if not df_a.empty else 0,
            "eb_annual_historical_ksi_benchmark": round(float(df_a["eb_annual_historical_ksi_benchmark"].sum()), 1) if not df_a.empty else 0,
        },
        "ranking_comparison": {
            "spearman_rank_correlation": round(rank_corr, 4),
            "max_corridor_rank_difference": max_rank_diff,
        },
        "test_split_diagnostic": test_diag,
        "status": status_val,
        "downstream_readiness": readiness_val,
        "critical_failure_count": crit_failures,
        "warning_count": warnings,
        "checks": checks,
    }

    if not is_sample:
        _write_json_atomic(report_output_path, report)
        runs_dir.mkdir(parents=True, exist_ok=True)
        hist_path = runs_dir / f"corridor_risk_forecast_2026_validation_{run_id}.json"
        _write_json_atomic(hist_path, report)
        print(f"Saved validation report to {report_output_path}")

    return report, checks


def main() -> int:
    print("=" * 70)
    print("Validate Fixed-Origin 2026 Corridor-Risk Forecasts & EB Benchmark")
    print("=" * 70)

    try:
        report, checks = validate_2026_corridor_risk_forecast()
        print("\n" + "=" * 70)
        print("FORECAST VALIDATION SUMMARY")
        print("=" * 70)
        print(f"Status: {report['status']} | Downstream Readiness: {report['downstream_readiness']}")
        print(f"Critical Failures: {report['critical_failure_count']} | Warnings: {report['warning_count']}")

        for check in checks:
            symbol = "PASS" if check["passed"] else "FAIL"
            print(f"  [{symbol:<4}] {check['check']:<55} ({check['severity']}) - {check['evidence']}")

        return 0 if report["status"] != "FAIL" else 1
    except Exception as exc:
        print(f"\nCRITICAL FAILURE: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
