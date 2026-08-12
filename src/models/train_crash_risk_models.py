"""Train, select, and evaluate transparent corridor-level crash-risk forecasting models.

Contract: docs/data_quality/cleaning_contract.md, spatial_assignment_contract.md
Config:   config/modeling.yml
Decision: D001 (Corridor-month grain), D003 (Time-based validation only), D018 (Chronological splits)

Targets:
1. total_crashes (Primary target)
2. ksi_crashes (Secondary KSI target)

Candidate models per target:
- seasonal_naive_lag12 (Benchmark)
- historical_rolling_mean_12 (Benchmark)
- poisson_regression (scikit-learn PoissonRegressor)
- negative_binomial_glm (statsmodels Negative Binomial GLM)

Selection policy:
Winner selected strictly on validation mean Poisson deviance (2024).
Winning model refitted on train + validation (2019-2024) and evaluated once on test (2025).
"""

from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import joblib
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import PoissonRegressor
from sklearn.metrics import mean_absolute_error, mean_poisson_deviance, root_mean_squared_error
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
import statsmodels.api as sm
import yaml

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FEATURES_PATH = ROOT / "data" / "processed" / "corridor_month_features.parquet"
MODELING_CONFIG_PATH = ROOT / "config" / "modeling.yml"
MODELS_DIR = ROOT / "outputs" / "models"
FORECASTS_DIR = ROOT / "outputs" / "forecasts"
TABLES_DIR = ROOT / "outputs" / "tables"
VALIDATION_REPORT_PATH = ROOT / "docs" / "data_quality" / "crash_risk_model_validation.json"
RUNS_DIR = ROOT / "docs" / "data_quality" / "crash_risk_model_runs"

NUMERICAL_PREDICTORS = [
    "total_crashes_lag1",
    "total_crashes_lag3",
    "total_crashes_lag6",
    "total_crashes_lag12",
    "total_crashes_roll_mean3",
    "total_crashes_roll_mean6",
    "total_crashes_roll_mean12",
    "total_crashes_roll_sum3",
    "total_crashes_roll_sum6",
    "total_crashes_roll_sum12",
    "ksi_crashes_lag1",
    "ksi_crashes_lag3",
    "ksi_crashes_lag6",
    "ksi_crashes_lag12",
    "ksi_crashes_roll_mean3",
    "ksi_crashes_roll_mean6",
    "ksi_crashes_roll_mean12",
    "ksi_crashes_roll_sum3",
    "ksi_crashes_roll_sum6",
    "ksi_crashes_roll_sum12",
    "calendar_year_trend",
    "month_sin",
    "month_cos",
]

CATEGORICAL_PREDICTORS = ["corridor_id", "source_group"]


def load_modeling_config() -> dict:
    with MODELING_CONFIG_PATH.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def calculate_overdispersion_diagnostic(df_train: pd.DataFrame, target: str) -> dict[str, Any]:
    """Calculate mean, variance, variance-to-mean ratio, and zero count percentage for target on training split."""
    vals = df_train[target].astype(float).values
    mean_val = float(np.mean(vals))
    var_val = float(np.var(vals, ddof=1))
    ratio = float(var_val / mean_val) if mean_val > 0 else 0.0
    zero_pct = float((vals == 0).sum() / len(vals) * 100.0)

    return {
        "target": target,
        "n_obs": len(vals),
        "mean": round(mean_val, 4),
        "variance": round(var_val, 4),
        "variance_to_mean_ratio": round(ratio, 4),
        "zero_count_pct": round(zero_pct, 2),
        "is_overdispersed": bool(ratio > 1.5),
    }


def compute_metrics(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    df_meta: Optional[pd.DataFrame] = None,
    pred_floor: float = 1e-6,
) -> dict[str, float]:
    """Calculate MAE, RMSE, Mean Poisson Deviance, Bias, Calibration Ratio, and Corridor Spearman Rank Correlation."""
    y_t = np.asarray(y_true, dtype=float)
    y_p = np.clip(np.asarray(y_pred, dtype=float), pred_floor, None)

    mae = float(mean_absolute_error(y_t, y_p))
    rmse = float(root_mean_squared_error(y_t, y_p))
    poisson_dev = float(mean_poisson_deviance(y_t, y_p))

    actual_sum = float(np.sum(y_t))
    pred_sum = float(np.sum(y_p))
    mean_bias = float(np.mean(y_p - y_t))
    calibration_ratio = float(pred_sum / actual_sum) if actual_sum > 0 else 1.0

    spearman_corr = 0.0
    if df_meta is not None and "corridor_id" in df_meta.columns:
        temp_df = df_meta[["corridor_id"]].copy()
        temp_df["actual"] = y_t
        temp_df["pred"] = y_p
        corr_agg = temp_df.groupby("corridor_id")[["actual", "pred"]].sum()
        if len(corr_agg) > 1:
            res = spearmanr(corr_agg["actual"], corr_agg["pred"])
            spearman_corr = float(res.statistic) if not np.isnan(res.statistic) else 0.0

    return {
        "mae": round(mae, 4),
        "rmse": round(rmse, 4),
        "mean_poisson_deviance": round(poisson_dev, 6),
        "mean_bias": round(mean_bias, 4),
        "calibration_ratio": round(calibration_ratio, 4),
        "spearman_rank_correlation": round(spearman_corr, 4),
        "actual_total": round(actual_sum, 1),
        "predicted_total": round(pred_sum, 1),
    }


sys.modules["src.models.train_crash_risk_models"] = sys.modules[__name__]


class BenchmarkModel:
    """Wrapper for baseline models (seasonal naive & historical rolling mean) to provide standard predict interface."""

    __module__ = "src.models.train_crash_risk_models"

    def __init__(self, model_type: str, target: str):
        self.model_type = model_type
        self.target = target
        self.feature_col = f"{target}_lag12" if model_type == "seasonal_naive_lag12" else f"{target}_roll_mean12"

    def fit(self, X: pd.DataFrame, y: pd.Series) -> BenchmarkModel:
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return X[self.feature_col].fillna(0.0).clip(lower=0.0).values


class StatsmodelsNegBinomialWrapper:
    """Wrapper for statsmodels Negative Binomial GLM with scikit-learn compatible fit/predict interface."""

    __module__ = "src.models.train_crash_risk_models"

    def __init__(self, alpha: float = 1.0):
        self.alpha = alpha
        self.preprocessor: Optional[ColumnTransformer] = None
        self.model_res: Optional[Any] = None
        self.feature_names_in_: List[str] = []

    def _build_preprocessor(self, num_cols: List[str], cat_cols: List[str]) -> ColumnTransformer:
        return ColumnTransformer(
            transformers=[
                ("num", StandardScaler(), num_cols),
                ("cat", OneHotEncoder(drop="first", sparse_output=False, handle_unknown="ignore"), cat_cols),
            ],
            remainder="drop",
        )

    def fit(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        num_cols: List[str] = NUMERICAL_PREDICTORS,
        cat_cols: List[str] = CATEGORICAL_PREDICTORS,
    ) -> StatsmodelsNegBinomialWrapper:
        self.feature_names_in_ = num_cols + cat_cols
        self.preprocessor = self._build_preprocessor(num_cols, cat_cols)
        X_trans = self.preprocessor.fit_transform(X[self.feature_names_in_])
        X_trans_const = sm.add_constant(X_trans, has_constant="add")

        y_vals = y.astype(float).values
        mean_y = float(np.mean(y_vals))
        var_y = float(np.var(y_vals, ddof=1))
        # Estimate alpha dispersion via Method of Moments if var > mean, else fallback to small alpha
        alpha_mom = max(1e-4, (var_y - mean_y) / (mean_y ** 2)) if mean_y > 0 and var_y > mean_y else 0.1
        self.alpha = alpha_mom

        try:
            fam = sm.families.NegativeBinomial(alpha=self.alpha)
            glm = sm.GLM(y_vals, X_trans_const, family=fam)
            self.model_res = glm.fit(maxiter=500)
        except Exception as exc:
            # Fallback to Poisson GLM if NegativeBinomial fitting raises numerical error
            print(f"[WARNING] Negative Binomial fit failed with {exc}, falling back to Poisson GLM.")
            fam = sm.families.Poisson()
            glm = sm.GLM(y_vals, X_trans_const, family=fam)
            self.model_res = glm.fit(maxiter=500)

        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        if self.preprocessor is None or self.model_res is None:
            raise RuntimeError("Model has not been fitted.")
        X_trans = self.preprocessor.transform(X[self.feature_names_in_])
        X_trans_const = sm.add_constant(X_trans, has_constant="add")
        preds = self.model_res.predict(X_trans_const)
        return np.clip(np.asarray(preds, dtype=float), 1e-6, None)


def build_poisson_pipeline(
    num_cols: List[str] = NUMERICAL_PREDICTORS,
    cat_cols: List[str] = CATEGORICAL_PREDICTORS,
    alpha: float = 1.0,
    random_seed: int = 42,
) -> Pipeline:
    preprocessor = ColumnTransformer(
        transformers=[
            ("num", StandardScaler(), num_cols),
            ("cat", OneHotEncoder(drop="first", sparse_output=False, handle_unknown="ignore"), cat_cols),
        ],
        remainder="drop",
    )
    model = PoissonRegressor(alpha=alpha, max_iter=1000)
    return Pipeline(steps=[("preprocessor", preprocessor), ("regressor", model)])


def train_candidate_model(
    model_name: str,
    target: str,
    X_train: pd.DataFrame,
    y_train: pd.Series,
) -> Any:
    """Instantiate and fit candidate model on training dataset."""
    if model_name == "seasonal_naive_lag12":
        model = BenchmarkModel("seasonal_naive_lag12", target)
        return model.fit(X_train, y_train)

    elif model_name == "historical_rolling_mean_12":
        model = BenchmarkModel("historical_rolling_mean_12", target)
        return model.fit(X_train, y_train)

    elif model_name == "poisson_regression":
        model = build_poisson_pipeline()
        model.fit(X_train, y_train)
        return model

    elif model_name == "negative_binomial_glm":
        model = StatsmodelsNegBinomialWrapper()
        model.fit(X_train, y_train)
        return model

    else:
        raise ValueError(f"Unknown candidate model_name: {model_name}")


def train_select_and_evaluate_all(
    features_path: Path = FEATURES_PATH,
    config_path: Path = MODELING_CONFIG_PATH,
    is_sample: bool = False,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Train candidates, select winner per target on validation deviance, evaluate on test, export artifacts."""
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    print(f"Run ID: {run_id}")

    df_all = pd.read_parquet(features_path)
    cfg = load_modeling_config()

    targets = cfg["targets"]["all_target_columns"]
    candidate_names = cfg["modeling"]["candidate_models"]
    pred_floor = float(cfg["modeling"]["prediction_floor"])

    # Filter model-ready rows
    df_ready = df_all[df_all["model_ready"] == True].copy()

    df_train = df_ready[df_ready["model_split"] == "train"].copy()
    df_val = df_ready[df_ready["model_split"] == "validation"].copy()
    df_test = df_ready[df_ready["model_split"] == "test"].copy()

    print(f"Dataset split counts: train={len(df_train):,}, validation={len(df_val):,}, test={len(df_test):,}")

    overdispersion_reports = []
    comparison_rows = []
    val_pred_records = []
    test_pred_records = []
    selected_winners = {}

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    FORECASTS_DIR.mkdir(parents=True, exist_ok=True)
    TABLES_DIR.mkdir(parents=True, exist_ok=True)

    for target in targets:
        print(f"\n" + "=" * 50)
        print(f"PROCESSING TARGET: {target}")
        print("=" * 50)

        # 1. Overdispersion Diagnostic
        od_diag = calculate_overdispersion_diagnostic(df_train, target)
        overdispersion_reports.append(od_diag)
        print(f"Training Overdispersion Diagnostic for {target}:")
        print(f"  Mean: {od_diag['mean']}, Variance: {od_diag['variance']}, Ratio: {od_diag['variance_to_mean_ratio']} (Overdispersed: {od_diag['is_overdispersed']})")

        y_train = df_train[target]
        y_val = df_val[target]
        y_test = df_test[target]

        best_candidate = None
        best_val_deviance = float("inf")
        val_candidate_results = {}

        # 2. Evaluate all candidates on Validation Split (2024)
        for cand_name in candidate_names:
            print(f"\n  Fitting Candidate: {cand_name}...")
            model = train_candidate_model(cand_name, target, df_train, y_train)
            val_preds = model.predict(df_val)

            val_metrics = compute_metrics(y_val.values, val_preds, df_meta=df_val, pred_floor=pred_floor)
            val_dev = val_metrics["mean_poisson_deviance"]

            print(f"  Validation Mean Poisson Deviance: {val_dev:.6f} | MAE: {val_metrics['mae']} | Calib: {val_metrics['calibration_ratio']}")

            val_candidate_results[cand_name] = {
                "model": model,
                "metrics": val_metrics,
                "preds": val_preds,
            }

            # Log validation prediction records
            for idx, (_, row) in enumerate(df_val.iterrows()):
                val_pred_records.append(
                    {
                        "corridor_id": row["corridor_id"],
                        "crash_month_start": row["crash_month_start"],
                        "model_split": "validation",
                        "target_name": target,
                        "model_name": cand_name,
                        "actual_value": float(row[target]),
                        "predicted_value": float(val_preds[idx]),
                        "residual": float(val_preds[idx] - row[target]),
                        "selection_status": "candidate",
                    }
                )

            # Check winner selection (lowest validation mean Poisson deviance)
            if val_dev < best_val_deviance:
                best_val_deviance = val_dev
                best_candidate = cand_name

        print(f"\n  ==> WINNER SELECTED FOR {target}: '{best_candidate}' (Val Deviance: {best_val_deviance:.6f})")
        selected_winners[target] = best_candidate

        # Mark selection status for validation predictions
        for rec in val_pred_records:
            if rec["target_name"] == target and rec["model_name"] == best_candidate:
                rec["selection_status"] = "selected_winner"

        # 3. Refit selected winner on Train + Validation (2019-2024) and Evaluate on Test (2025)
        df_train_val = pd.concat([df_train, df_val], axis=0).sort_values(
            by=["corridor_id", "crash_month_start"]
        ).reset_index(drop=True)
        y_train_val = df_train_val[target]

        print(f"  Refitting locked winner '{best_candidate}' on Train+Val ({len(df_train_val):,} rows)...")
        winning_model = train_candidate_model(best_candidate, target, df_train_val, y_train_val)

        test_preds = winning_model.predict(df_test)
        test_metrics = compute_metrics(y_test.values, test_preds, df_meta=df_test, pred_floor=pred_floor)

        print(f"  Locked Test Metrics (2025): Deviance={test_metrics['mean_poisson_deviance']:.6f} | MAE={test_metrics['mae']} | Calib={test_metrics['calibration_ratio']}")

        # Save model joblib artifact
        if not is_sample:
            model_save_path = MODELS_DIR / f"{target}_selected_model.joblib"
            joblib.dump(
                {
                    "target": target,
                    "winning_model_name": best_candidate,
                    "model_object": winning_model,
                    "numerical_predictors": NUMERICAL_PREDICTORS,
                    "categorical_predictors": CATEGORICAL_PREDICTORS,
                    "val_metrics": val_candidate_results[best_candidate]["metrics"],
                    "test_metrics": test_metrics,
                    "fitted_at_utc": datetime.now(timezone.utc).isoformat(),
                },
                model_save_path,
            )
            print(f"  Saved serialized winning model to {model_save_path}")

        # Log test prediction records
        for idx, (_, row) in enumerate(df_test.iterrows()):
            test_pred_records.append(
                {
                    "corridor_id": row["corridor_id"],
                    "crash_month_start": row["crash_month_start"],
                    "model_split": "test",
                    "target_name": target,
                    "model_name": best_candidate,
                    "actual_value": float(row[target]),
                    "predicted_value": float(test_preds[idx]),
                    "residual": float(test_preds[idx] - row[target]),
                    "selection_status": "selected_winner",
                }
            )

        # Build comparison summary table records
        for cand_name in candidate_names:
            v_met = val_candidate_results[cand_name]["metrics"]
            is_winner = cand_name == best_candidate
            t_met = test_metrics if is_winner else {}

            comparison_rows.append(
                {
                    "target": target,
                    "model_name": cand_name,
                    "is_selected_winner": is_winner,
                    "val_row_count": len(df_val),
                    "val_actual_total": v_met["actual_total"],
                    "val_predicted_total": v_met["predicted_total"],
                    "val_mae": v_met["mae"],
                    "val_rmse": v_met["rmse"],
                    "val_poisson_deviance": v_met["mean_poisson_deviance"],
                    "val_mean_bias": v_met["mean_bias"],
                    "val_calibration_ratio": v_met["calibration_ratio"],
                    "val_spearman_rank_corr": v_met["spearman_rank_correlation"],
                    "test_row_count": len(df_test) if is_winner else np.nan,
                    "test_actual_total": t_met.get("actual_total", np.nan),
                    "test_predicted_total": t_met.get("predicted_total", np.nan),
                    "test_mae": t_met.get("mae", np.nan),
                    "test_rmse": t_met.get("rmse", np.nan),
                    "test_poisson_deviance": t_met.get("mean_poisson_deviance", np.nan),
                    "test_mean_bias": t_met.get("mean_bias", np.nan),
                    "test_calibration_ratio": t_met.get("calibration_ratio", np.nan),
                    "test_spearman_rank_corr": t_met.get("spearman_rank_correlation", np.nan),
                }
            )

    df_val_preds = pd.DataFrame(val_pred_records)
    df_test_preds = pd.DataFrame(test_pred_records)
    df_comp = pd.DataFrame(comparison_rows)

    if not is_sample:
        df_val_preds.to_parquet(FORECASTS_DIR / "model_validation_predictions.parquet", index=False)
        df_test_preds.to_parquet(FORECASTS_DIR / "model_test_predictions.parquet", index=False)
        df_comp.to_csv(TABLES_DIR / "model_comparison.csv", index=False)
        print(f"\nSaved prediction and comparison table artifacts to {FORECASTS_DIR} and {TABLES_DIR}")

    report = {
        "pipeline": "crash_risk_models",
        "run_id": run_id,
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "is_sample": is_sample,
        "train_rows": len(df_train),
        "validation_rows": len(df_val),
        "test_rows": len(df_test),
        "overdispersion_diagnostics": overdispersion_reports,
        "selected_winners": selected_winners,
        "comparison_table": comparison_rows,
    }

    return report, df_comp, df_val_preds, df_test_preds


def main() -> int:
    print("=" * 70)
    print("Train, Select & Evaluate Crash-Risk Forecasting Models (Day 12 Phase 3A)")
    print("=" * 70)

    try:
        report, df_comp, df_val_preds, df_test_preds = train_select_and_evaluate_all()

        print("\n" + "=" * 70)
        print("MODEL SELECTION SUMMARY")
        print("=" * 70)
        for target, winner in report["selected_winners"].items():
            print(f"Target: {target:<15} | Selected Winner: {winner}")

        print("\n" + "=" * 70)
        print("VALIDATION & TEST PERFORMANCE METRICS")
        print("=" * 70)
        print(df_comp.to_string(index=False))

        return 0
    except Exception as exc:
        print(f"\nCRITICAL FAILURE: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
