"""Build fixed-origin 2026 corridor crash-risk forecasts and Empirical Bayes benchmark.

Contract: docs/data_quality/cleaning_contract.md, spatial_assignment_contract.md
Config:   config/modeling.yml
Decision: D001 (Corridor-month grain), D003 (Time-based validation), D005 (Governance authority)

Forecast Origin: 2025-12-01
Forecast Window: 2026-01-01 to 2026-12-01 (12 steps)
Grain: 43 corridors x 12 months = 516 rows (monthly), 43 corridors = 43 rows (annual)
"""

from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

import joblib
import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.models.empirical_bayes_ksi import fit_empirical_bayes_ksi  # noqa: E402
from src.models.train_crash_risk_models import (  # noqa: E402
    CATEGORICAL_PREDICTORS,
    NUMERICAL_PREDICTORS,
    StatsmodelsNegBinomialWrapper,
    load_modeling_config,
)

FEATURES_PATH = ROOT / "data" / "processed" / "corridor_month_features.parquet"
MODELING_CONFIG_PATH = ROOT / "config" / "modeling.yml"
VAL_PRED_PATH = ROOT / "outputs" / "forecasts" / "model_validation_predictions.parquet"
PROD_MODEL_PATH = ROOT / "outputs" / "models" / "ksi_crashes_production_model_2026.joblib"
MONTHLY_PARQUET_PATH = ROOT / "outputs" / "forecasts" / "corridor_risk_forecast_2026.parquet"
MONTHLY_CSV_PATH = ROOT / "outputs" / "forecasts" / "corridor_risk_forecast_2026.csv"
ANNUAL_CSV_PATH = ROOT / "outputs" / "forecasts" / "corridor_risk_forecast_2026_annual.csv"


def derive_validation_calibration_metrics(
    val_pred_path: Path = VAL_PRED_PATH,
) -> Tuple[float, float]:
    """Calculate validation-derived KSI calibration metrics from Phase 3A validation predictions.

    Returns:
        (validation_raw_calibration_ratio, ksi_calibration_factor)
        - validation_raw_calibration_ratio = SUM(predicted) / SUM(actual) = 1.258404
        - ksi_calibration_factor = SUM(actual) / SUM(predicted) = 0.794653
    """
    if not val_pred_path.exists():
        raise FileNotFoundError(f"Validation predictions file not found: {val_pred_path}")

    val_preds = pd.read_parquet(val_pred_path)
    sub = val_preds[
        (val_preds["target_name"] == "ksi_crashes")
        & (val_preds["model_name"] == "negative_binomial_glm")
        & (val_preds["model_split"] == "validation")
    ]

    if len(sub) == 0:
        raise ValueError("No matching validation KSI predictions found for negative_binomial_glm")

    sum_actual = float(sub["actual_value"].sum())
    sum_pred = float(sub["predicted_value"].sum())

    if sum_pred <= 0 or sum_actual <= 0:
        raise ValueError("Validation sums for KSI calibration must be strictly positive")

    raw_ratio = float(sum_pred / sum_actual)
    factor = float(sum_actual / sum_pred)
    return raw_ratio, factor


def derive_validation_calibration_factor(
    val_pred_path: Path = VAL_PRED_PATH,
) -> float:
    """Convenience helper returning the multiplicative calibration factor (actual / predicted = 0.794653)."""
    _, factor = derive_validation_calibration_metrics(val_pred_path)
    return factor


def generate_2026_corridor_risk_forecast(
    features_path: Path = FEATURES_PATH,
    config_path: Path = MODELING_CONFIG_PATH,
    val_pred_path: Path = VAL_PRED_PATH,
    prod_model_path: Path = PROD_MODEL_PATH,
    monthly_parquet_path: Path = MONTHLY_PARQUET_PATH,
    monthly_csv_path: Path = MONTHLY_CSV_PATH,
    annual_csv_path: Path = ANNUAL_CSV_PATH,
    is_sample: bool = False,
) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, Any]]:
    """Generate 12-month recursive 2026 fixed-origin forecasts and Empirical Bayes benchmark."""
    t0 = time.time()
    df_feat = pd.read_parquet(features_path)
    cfg = load_modeling_config()

    # 1. Derive calibration factor and raw ratio from 2024 validation predictions
    raw_calib_ratio, calib_factor = derive_validation_calibration_metrics(val_pred_path)
    print(f"Validation Raw Calibration Ratio: {raw_calib_ratio:.6f} (+{(raw_calib_ratio-1)*100:.2f}% overprediction)")
    print(f"Validation-derived Multiplicative Calibration Factor: {calib_factor:.6f}")

    # 2. Refit production KSI model on all model-ready history (2019-2025, 3,612 rows)
    df_ready = df_feat[df_feat["model_ready"] == True].copy()
    df_hist_train = df_ready[df_ready["model_split"].isin(["train", "validation", "test"])].copy()

    print(f"Refitting production Negative Binomial KSI model on {len(df_hist_train):,} rows (2019-2025)...")
    prod_ksi_model = StatsmodelsNegBinomialWrapper()
    prod_ksi_model.fit(df_hist_train, df_hist_train["ksi_crashes"])

    if not is_sample:
        PROD_MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(
            {
                "production_model_name": "negative_binomial_glm",
                "target": "ksi_crashes",
                "model_object": prod_ksi_model,
                "refitted_row_count": len(df_hist_train),
                "refitted_years": "2019-2025",
                "validation_raw_calibration_ratio": raw_calib_ratio,
                "ksi_calibration_factor": calib_factor,
                "fitted_at_utc": datetime.now(timezone.utc).isoformat(),
            },
            prod_model_path,
        )
        print(f"Saved production model to {prod_model_path}")

    # 3. Build 12-step recursive forecast for 2026 (2026-01-01 to 2026-12-01)
    history_records = df_feat.copy().sort_values(["corridor_id", "crash_month_start"]).reset_index(drop=True)

    forecast_dates = pd.date_range("2026-01-01", "2026-12-01", freq="MS")
    monthly_rows: List[Dict[str, Any]] = []

    corridor_static_meta = (
        df_feat.groupby("corridor_id")
        .agg(
            corridor_name=("corridor_name", "first"),
            source_group=("source_group", "first"),
            corridor_length_feet=("corridor_length_feet", "first"),
            corridor_length_miles=("corridor_length_miles", "first"),
        )
        .to_dict(orient="index")
    )

    corridor_histories: Dict[str, pd.DataFrame] = {}
    for cid, g in history_records.groupby("corridor_id"):
        corridor_histories[cid] = g.sort_values("crash_month_start").reset_index(drop=True)

    for h_step, f_date in enumerate(forecast_dates, start=1):
        month_val = f_date.month
        year_val = f_date.year
        quarter_val = f_date.quarter
        year_trend = year_val - 2018  # 8 for 2026
        sin_val = float(np.round(np.sin(2 * np.pi * month_val / 12.0), 6))
        cos_val = float(np.round(np.cos(2 * np.pi * month_val / 12.0), 6))

        for cid in sorted(corridor_histories.keys()):
            h_df = corridor_histories[cid]
            meta = corridor_static_meta[cid]

            # Total crashes forecast: historical_rolling_mean_12 (mean of preceding 12 monthly total_crashes)
            tot_forecast = float(h_df["total_crashes"].iloc[-12:].mean())

            # Build predictors for KSI model
            tot_vals = h_df["total_crashes"].values
            ksi_vals = h_df["ksi_crashes"].values

            pred_dict: Dict[str, Any] = {
                "corridor_id": cid,
                "source_group": meta["source_group"],
                "corridor_length_feet": meta["corridor_length_feet"],
                "corridor_length_miles": meta["corridor_length_miles"],
                "calendar_month": month_val,
                "calendar_quarter": quarter_val,
                "calendar_year_trend": year_trend,
                "month_sin": sin_val,
                "month_cos": cos_val,
                "total_crashes_lag1": float(tot_vals[-1]),
                "total_crashes_lag3": float(tot_vals[-3]),
                "total_crashes_lag6": float(tot_vals[-6]),
                "total_crashes_lag12": float(tot_vals[-12]),
                "total_crashes_roll_mean3": float(np.mean(tot_vals[-3:])),
                "total_crashes_roll_mean6": float(np.mean(tot_vals[-6:])),
                "total_crashes_roll_mean12": float(np.mean(tot_vals[-12:])),
                "total_crashes_roll_sum3": float(np.sum(tot_vals[-3:])),
                "total_crashes_roll_sum6": float(np.sum(tot_vals[-6:])),
                "total_crashes_roll_sum12": float(np.sum(tot_vals[-12:])),
                "ksi_crashes_lag1": float(ksi_vals[-1]),
                "ksi_crashes_lag3": float(ksi_vals[-3]),
                "ksi_crashes_lag6": float(ksi_vals[-6]),
                "ksi_crashes_lag12": float(ksi_vals[-12]),
                "ksi_crashes_roll_mean3": float(np.mean(ksi_vals[-3:])),
                "ksi_crashes_roll_mean6": float(np.mean(ksi_vals[-6:])),
                "ksi_crashes_roll_mean12": float(np.mean(ksi_vals[-12:])),
                "ksi_crashes_roll_sum3": float(np.sum(ksi_vals[-3:])),
                "ksi_crashes_roll_sum6": float(np.sum(ksi_vals[-6:])),
                "ksi_crashes_roll_sum12": float(np.sum(ksi_vals[-12:])),
            }

            pred_df_row = pd.DataFrame([pred_dict])

            # Predict raw KSI expectation using refitted production model
            raw_ksi_pred = float(prod_ksi_model.predict(pred_df_row)[0])
            calibrated_ksi_pred = float(raw_ksi_pred * calib_factor)

            # Safeguard bound: calibrated KSI <= total crashes forecast
            if calibrated_ksi_pred > tot_forecast:
                calibrated_ksi_pred = tot_forecast

            # Log monthly forecast record
            monthly_rows.append(
                {
                    "corridor_id": cid,
                    "corridor_name": meta["corridor_name"],
                    "forecast_origin": "2025-12-01",
                    "forecast_month": f_date.strftime("%Y-%m-%d"),
                    "forecast_horizon_month": h_step,
                    "forecast_protocol": "fixed_origin_recursive",
                    "total_crashes_forecast": round(tot_forecast, 6),
                    "ksi_crashes_forecast_raw": round(raw_ksi_pred, 6),
                    "validation_raw_calibration_ratio": round(raw_calib_ratio, 6),
                    "ksi_calibration_factor": round(calib_factor, 6),
                    "ksi_crashes_forecast_calibrated": round(calibrated_ksi_pred, 6),
                    "total_model_name": "historical_rolling_mean_12",
                    "ksi_model_name": "negative_binomial_glm",
                    "recursion_policy": "calibrated_prediction_feedback",
                    "is_observed": False,
                }
            )

            # Append generated forecast to ongoing history for next recursive steps
            new_hist_row = pred_dict.copy()
            new_hist_row["crash_month_start"] = f_date
            new_hist_row["corridor_name"] = meta["corridor_name"]
            new_hist_row["total_crashes"] = tot_forecast
            new_hist_row["ksi_crashes"] = calibrated_ksi_pred
            new_hist_row["fatal_crashes"] = 0
            new_hist_row["serious_injury_crashes"] = 0
            new_hist_row["model_ready"] = True
            new_hist_row["model_split"] = "forecast_2026"

            corridor_histories[cid] = pd.concat(
                [h_df, pd.DataFrame([new_hist_row])], ignore_index=True
            )

    df_monthly = pd.DataFrame(monthly_rows)

    # 4. Fit Empirical Bayes benchmark model on 2019-2025 history
    eb_summary, df_eb = fit_empirical_bayes_ksi(df_feat, start_year=2019, end_year=2025)
    print(f"EB Fit Summary: Accepted Optimizer={eb_summary['accepted_optimizer']}, Alpha={eb_summary['alpha']}, Beta={eb_summary['beta']}, Converged={eb_summary['converged']}")

    # 5. Build 43-row Annual Summary table
    annual_rows: List[Dict[str, Any]] = []
    eb_map = df_eb.set_index("corridor_id").to_dict(orient="index")

    monthly_agg = (
        df_monthly.groupby("corridor_id")
        .agg(
            corridor_name=("corridor_name", "first"),
            annual_total_crashes_forecast=("total_crashes_forecast", "sum"),
            annual_ksi_forecast_raw=("ksi_crashes_forecast_raw", "sum"),
            annual_ksi_forecast_calibrated=("ksi_crashes_forecast_calibrated", "sum"),
        )
        .reset_index()
    )

    for _, row in monthly_agg.iterrows():
        cid = row["corridor_id"]
        eb_info = eb_map[cid]

        tot_fc = float(row["annual_total_crashes_forecast"])
        ksi_raw = float(row["annual_ksi_forecast_raw"])
        ksi_cal = float(row["annual_ksi_forecast_calibrated"])
        eb_bm = float(eb_info["eb_annual_historical_ksi_benchmark"])
        phys_len = float(eb_info["corridor_length_miles"])
        eb_exp = float(eb_info["eb_exposure_corridor_mile_years"])

        annual_rows.append(
            {
                "corridor_id": cid,
                "corridor_name": row["corridor_name"],
                "corridor_length_miles": round(phys_len, 4),
                "eb_exposure_corridor_mile_years": round(eb_exp, 4),
                "annual_total_crashes_forecast": round(tot_fc, 4),
                "annual_ksi_forecast_raw": round(ksi_raw, 4),
                "validation_raw_calibration_ratio": round(raw_calib_ratio, 6),
                "ksi_calibration_factor": round(calib_factor, 6),
                "annual_ksi_forecast_calibrated": round(ksi_cal, 4),
                "eb_annual_historical_ksi_benchmark": round(eb_bm, 4),
                "raw_to_calibrated_ksi_difference": round(ksi_cal - ksi_raw, 4),
                "calibrated_model_to_eb_difference": round(ksi_cal - eb_bm, 4),
                "historical_2019_2025_ksi_count": int(eb_info["historical_ksi_count"]),
                "historical_annual_average_ksi": round(float(eb_info["historical_annual_average_ksi"]), 4),
            }
        )

    df_annual = pd.DataFrame(annual_rows)

    # Compute rankings (1 = highest risk)
    df_annual["rank_calibrated_model_forecast"] = (
        df_annual["annual_ksi_forecast_calibrated"].rank(ascending=False, method="min").astype(int)
    )
    df_annual["rank_eb_benchmark"] = (
        df_annual["eb_annual_historical_ksi_benchmark"].rank(ascending=False, method="min").astype(int)
    )

    df_annual = df_annual.sort_values("rank_calibrated_model_forecast").reset_index(drop=True)

    # Export artifacts
    if not is_sample:
        monthly_parquet_path.parent.mkdir(parents=True, exist_ok=True)
        df_monthly.to_parquet(monthly_parquet_path, index=False)
        df_monthly.to_csv(monthly_csv_path, index=False)
        df_annual.to_csv(annual_csv_path, index=False)
        print(f"Saved monthly forecast parquet to {monthly_parquet_path}")
        print(f"Saved monthly forecast CSV to {monthly_csv_path}")
        print(f"Saved annual forecast CSV to {annual_csv_path}")

    exec_time = time.time() - t0
    meta = {
        "execution_time_seconds": round(exec_time, 3),
        "validation_raw_calibration_ratio": round(raw_calib_ratio, 6),
        "ksi_calibration_factor": round(calib_factor, 6),
        "eb_summary": eb_summary,
        "monthly_row_count": len(df_monthly),
        "annual_row_count": len(df_annual),
    }

    return df_monthly, df_annual, meta


def main() -> int:
    print("=" * 70)
    print("Build Fixed-Origin 2026 Corridor-Risk Forecasts & EB Benchmark (Phase 3B)")
    print("=" * 70)

    try:
        df_m, df_a, meta = generate_2026_corridor_risk_forecast()
        print("\n" + "=" * 70)
        print("2026 FORECAST GENERATION SUMMARY")
        print("=" * 70)
        print(f"Monthly Forecast Rows: {len(df_m):,} | Annual Corridor Rows: {len(df_a):,}")
        print(f"Validation Raw Calibration Ratio: {meta['validation_raw_calibration_ratio']:.6f}")
        print(f"Multiplicative Calibration Factor: {meta['ksi_calibration_factor']:.6f}")
        print(f"Total 2026 Crashes Forecast : {df_a['annual_total_crashes_forecast'].sum():.1f}")
        print(f"Total 2026 Raw KSI Forecast : {df_a['annual_ksi_forecast_raw'].sum():.1f}")
        print(f"Total 2026 Calib KSI Forecast: {df_a['annual_ksi_forecast_calibrated'].sum():.1f}")
        print(f"Total EB Annual Benchmark   : {df_a['eb_annual_historical_ksi_benchmark'].sum():.1f}")

        print("\nTop 5 Corridors Under Calibrated KSI Forecast:")
        for idx, r in df_a.head(5).iterrows():
            print(f"  {r['rank_calibrated_model_forecast']}. {r['corridor_id']} ({r['corridor_name']}): "
                  f"Length = {r['corridor_length_miles']:.2f} mi | "
                  f"Calib KSI = {r['annual_ksi_forecast_calibrated']:.2f} | "
                  f"EB Benchmark = {r['eb_annual_historical_ksi_benchmark']:.2f} (Rank {r['rank_eb_benchmark']})")

        return 0
    except Exception as exc:
        print(f"\nCRITICAL FAILURE: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
