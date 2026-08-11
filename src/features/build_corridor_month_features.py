"""Build leakage-safe corridor-month forecasting features and chronological data splits.

Contract: docs/data_quality/cleaning_contract.md, spatial_assignment_contract.md
Config:   config/modeling.yml, config/project.yml
Decision: D001 (Corridor-month grain), D003 (Time-based validation only), D018 (Warm-up, Train, Validation, Test splits)

Feature calculation rule:
All rolling and lag features shift the target outcome by at least 1 month before computing statistics:
groupby(corridor_id)[target].shift(1).rolling(window)

Target columns: total_crashes, ksi_crashes.
Output parquet: data/processed/corridor_month_features.parquet (4,128 rows).
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MODELING_CONFIG_PATH = ROOT / "config" / "modeling.yml"
PANEL_INPUT_PATH = ROOT / "data" / "processed" / "corridor_month_panel.parquet"
FEATURE_OUTPUT_PATH = ROOT / "data" / "processed" / "corridor_month_features.parquet"
VALIDATION_REPORT_PATH = ROOT / "docs" / "data_quality" / "corridor_month_features_validation.json"
RUNS_DIR = ROOT / "docs" / "data_quality" / "corridor_month_features_runs"


def _write_json_atomic(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.json")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    tmp.replace(path)


def _write_parquet_atomic(path: Path, df: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.parquet")
    df.to_parquet(tmp, index=False)
    tmp.replace(path)


def load_modeling_config(config_path: Optional[Path] = None) -> dict:
    """Load config/modeling.yml."""
    if config_path is None:
        config_path = MODELING_CONFIG_PATH
    with config_path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def compute_leakage_safe_features(
    panel_df: pd.DataFrame,
    modeling_config: dict,
) -> pd.DataFrame:
    """Compute leakage-safe historical lags, rolling statistics, calendar, and split labels."""
    df = panel_df.sort_values(
        by=["corridor_id", "crash_month_start"], ascending=[True, True]
    ).reset_index(drop=True)

    targets = modeling_config["targets"]["all_target_columns"]
    lag_months = modeling_config["features"]["lag_months"]
    rolling_windows = modeling_config["features"]["rolling_windows"]

    # History available count per corridor
    df["history_months_available"] = df.groupby("corridor_id").cumcount()

    # Lags and Rolling Features per target
    for target in targets:
        # Lags: shift(k)
        for k in lag_months:
            df[f"{target}_lag{k}"] = df.groupby("corridor_id")[target].shift(k)

        # Shifted by 1 month for rolling statistics to prevent target leakage
        shifted = df.groupby("corridor_id")[target].shift(1)

        for w in rolling_windows:
            # Trailing rolling mean
            df[f"{target}_roll_mean{w}"] = (
                shifted.groupby(df["corridor_id"])
                .rolling(window=w, min_periods=w)
                .mean()
                .reset_index(level=0, drop=True)
            )

            # Trailing rolling sum
            df[f"{target}_roll_sum{w}"] = (
                shifted.groupby(df["corridor_id"])
                .rolling(window=w, min_periods=w)
                .sum()
                .reset_index(level=0, drop=True)
            )

    # Calendar and trend predictors
    month_val = df["crash_month_start"].dt.month
    year_val = df["crash_month_start"].dt.year

    df["calendar_month"] = month_val
    df["calendar_quarter"] = df["crash_month_start"].dt.quarter
    df["calendar_year_trend"] = year_val - 2018

    df["month_sin"] = np.round(np.sin(2 * np.pi * month_val / 12.0), 6)
    df["month_cos"] = np.round(np.cos(2 * np.pi * month_val / 12.0), 6)

    # Model readiness and Chronological splits
    df["model_ready"] = df["history_months_available"] >= 12

    split_conditions = [
        year_val == 2018,
        (year_val >= 2019) & (year_val <= 2023),
        year_val == 2024,
        year_val == 2025,
    ]
    split_choices = ["warmup", "train", "validation", "test"]
    df["model_split"] = np.select(split_conditions, split_choices, default="unknown")

    return df


def validate_corridor_month_features(
    features_df: pd.DataFrame,
    is_sample: bool = False,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Validate corridor-month features dataframe and return report dict & checks list."""
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

    n_rows = len(features_df)

    # 1. Total row count 4,128
    if not is_sample:
        _add_check(
            "feature_row_count_is_4128",
            "CRITICAL",
            n_rows == 4128,
            f"Feature row count: {n_rows:,} (expected 4,128)",
        )
    else:
        _add_check(
            "feature_row_count_is_4128",
            "WARNING",
            True,
            f"Sample mode active: evaluating sample of {n_rows:,} rows.",
        )

    # 2. Composite key unique
    null_keys = int(
        (features_df["corridor_id"].isna() | features_df["crash_month_start"].isna()).sum()
    )
    dup_keys = int(
        features_df.duplicated(subset=["corridor_id", "crash_month_start"]).sum()
    )
    _add_check(
        "composite_key_unique_and_non_null",
        "CRITICAL",
        null_keys == 0 and dup_keys == 0,
        f"Null composite keys: {null_keys}, Duplicate composite keys: {dup_keys}",
    )

    # 3. Corridor count 43
    n_corridors = features_df["corridor_id"].nunique()
    _add_check(
        "corridor_count_is_43",
        "CRITICAL",
        n_corridors == 43,
        f"Corridor count: {n_corridors} (expected 43)",
    )

    # 4. Months per corridor 96
    months_per_corridor = features_df.groupby("corridor_id")["crash_month_start"].count()
    all_96 = (months_per_corridor == 96).all()
    _add_check(
        "month_count_per_corridor_is_96",
        "CRITICAL",
        bool(all_96),
        f"All corridors have 96 months: {all_96}",
    )

    # 5. Model ready count 3,612
    n_ready = int(features_df["model_ready"].sum())
    if not is_sample:
        _add_check(
            "model_ready_count_is_3612",
            "CRITICAL",
            n_ready == 3612,
            f"Model ready count: {n_ready:,} (expected 3,612)",
        )
    else:
        _add_check(
            "model_ready_count_is_3612",
            "WARNING",
            True,
            f"Sample mode active: model ready count is {n_ready:,}.",
        )

    # 6. Split counts
    split_counts = features_df["model_split"].value_counts().to_dict()
    n_warmup = int(split_counts.get("warmup", 0))
    n_train = int(split_counts.get("train", 0))
    n_val = int(split_counts.get("validation", 0))
    n_test = int(split_counts.get("test", 0))

    if not is_sample:
        splits_valid = (
            n_warmup == 516 and n_train == 2580 and n_val == 516 and n_test == 516
        )
        _add_check(
            "chronological_split_counts_exact",
            "CRITICAL",
            splits_valid,
            f"Splits: warmup={n_warmup}, train={n_train}, val={n_val}, test={n_test} (expected 516/2580/516/516)",
        )
    else:
        _add_check(
            "chronological_split_counts_exact",
            "WARNING",
            True,
            f"Sample mode active: split counts: {split_counts}",
        )

    # 7. Original outcome totals reconciled
    total_crashes_sum = int(features_df["total_crashes"].sum())
    ksi_crashes_sum = int(features_df["ksi_crashes"].sum())
    if not is_sample:
        _add_check(
            "original_outcome_totals_reconciled",
            "CRITICAL",
            total_crashes_sum == 112421 and ksi_crashes_sum == 2297,
            f"Outcome totals: total_crashes={total_crashes_sum:,} (exp 112,421), ksi_crashes={ksi_crashes_sum:,} (exp 2,297)",
        )
    else:
        _add_check(
            "original_outcome_totals_reconciled",
            "WARNING",
            True,
            f"Sample mode active: total_crashes={total_crashes_sum:,}, ksi_crashes={ksi_crashes_sum:,}",
        )

    # 8. Leakage guard shift verification
    # For every row with history >= 1, total_crashes_lag1 must equal previous row's total_crashes
    lag1_check_passed = True
    for cid, group in features_df.groupby("corridor_id"):
        g = group.sort_values("crash_month_start").reset_index(drop=True)
        # Check lag1 equals shift(1)
        expected_lag1 = g["total_crashes"].shift(1)
        actual_lag1 = g["total_crashes_lag1"]
        diff = (expected_lag1.dropna() - actual_lag1.dropna()).abs().sum()
        if diff != 0:
            lag1_check_passed = False
            break

    _add_check(
        "leakage_guard_shift_verified",
        "CRITICAL",
        lag1_check_passed,
        f"Lag-1 matches shifted previous month target: {lag1_check_passed}",
    )

    # 9. No infinite values
    numeric_cols = features_df.select_dtypes(include=[np.number]).columns
    inf_count = int(np.isinf(features_df[numeric_cols]).sum().sum())
    _add_check(
        "no_infinite_values",
        "CRITICAL",
        inf_count == 0,
        f"Infinite values found in features: {inf_count}",
    )

    # 10. Expected null pattern (warmup only for lag/rolling features)
    # For model_ready == True rows, lag1 to lag12 and roll_3/6/12 should have zero nulls
    ready_df = features_df[features_df["model_ready"] == True]
    feature_cols = [
        c for c in features_df.columns
        if ("_lag" in c or "_roll_" in c) and c not in ["total_crashes", "ksi_crashes"]
    ]
    nulls_in_ready = int(ready_df[feature_cols].isna().sum().sum())
    _add_check(
        "expected_null_pattern_warmup_only",
        "CRITICAL",
        nulls_in_ready == 0,
        f"Null values in model-ready predictor rows: {nulls_in_ready}",
    )

    # 11. Deterministic ordering
    sorted_df = features_df.sort_values(
        by=["corridor_id", "crash_month_start"], ascending=[True, True]
    ).reset_index(drop=True)
    is_sorted = features_df[["corridor_id", "crash_month_start"]].equals(
        sorted_df[["corridor_id", "crash_month_start"]]
    )
    _add_check(
        "deterministic_ordering",
        "CRITICAL",
        is_sorted,
        f"Feature table sorted by (corridor_id, crash_month_start): {is_sorted}",
    )

    crit_failures = sum(1 for c in checks if c["severity"] == "CRITICAL" and not c["passed"])
    warnings = sum(1 for c in checks if c["severity"] == "WARNING" and not c["passed"])

    if crit_failures > 0:
        status_val = "FAIL"
        readiness_val = "BLOCKED"
    elif warnings > 0:
        status_val = "PASS_WITH_WARNINGS"
        readiness_val = "READY_FOR_MODEL_TRAINING"
    else:
        status_val = "PASS"
        readiness_val = "READY_FOR_MODEL_TRAINING"

    report = {
        "pipeline": "corridor_month_features",
        "run_id": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "is_sample": is_sample,
        "corridor_count": n_corridors,
        "total_feature_rows": n_rows,
        "model_ready_rows": n_ready,
        "split_counts": {
            "warmup": n_warmup,
            "train": n_train,
            "validation": n_val,
            "test": n_test,
        },
        "target_totals": {
            "total_crashes": total_crashes_sum,
            "ksi_crashes": ksi_crashes_sum,
        },
        "status": status_val,
        "downstream_readiness": readiness_val,
        "critical_failure_count": crit_failures,
        "warning_count": warnings,
        "checks": checks,
    }

    return report, checks


def build_corridor_month_features(
    panel_path: Path = PANEL_INPUT_PATH,
    modeling_config_path: Path = MODELING_CONFIG_PATH,
    output_path: Path = FEATURE_OUTPUT_PATH,
    validation_report_path: Path = VALIDATION_REPORT_PATH,
    runs_dir: Path = RUNS_DIR,
    sample_size: Optional[int] = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Build and validate corridor-month features Parquet and JSON validation report."""
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    print(f"Run ID: {run_id}")

    t0_load = time.time()
    panel_df = pd.read_parquet(panel_path)
    modeling_config = load_modeling_config(modeling_config_path)
    t_load = time.time() - t0_load

    is_sample = sample_size is not None
    if is_sample and sample_size is not None:
        panel_df = panel_df.iloc[:sample_size].copy()
        print(f"[SAMPLE MODE] Limiting input panel to sample of {sample_size:,} rows.")

    print(f"Loaded panel in {t_load:.3f}s: {len(panel_df):,} rows.")

    # Compute leakage safe features
    t0_feat = time.time()
    features_df = compute_leakage_safe_features(panel_df, modeling_config)
    t_feat = time.time() - t0_feat
    print(f"Feature computation completed in {t_feat:.3f}s.")

    report, checks = validate_corridor_month_features(features_df, is_sample=is_sample)

    if not is_sample:
        _write_parquet_atomic(output_path, features_df)
        _write_json_atomic(validation_report_path, report)
        runs_dir.mkdir(parents=True, exist_ok=True)
        hist_report_path = runs_dir / f"corridor_month_features_validation_{run_id}.json"
        _write_json_atomic(hist_report_path, report)
        print(f"Saved feature Parquet to {output_path}")
        print(f"Saved validation report to {validation_report_path}")
    else:
        print("[SAMPLE MODE] Skipped overwriting feature Parquet and validation report artifacts.")

    return features_df, report


def main() -> int:
    print("=" * 70)
    print("Build Corridor-Month Forecasting Features (Day 11 Phase 2B)")
    print("=" * 70)

    try:
        df, report = build_corridor_month_features()
        print("\n" + "=" * 70)
        print("FEATURE SUMMARY")
        print("=" * 70)
        print(f"Total Rows              : {report['total_feature_rows']:,}")
        print(f"Corridor Count          : {report['corridor_count']}")
        print(f"Model-Ready Rows        : {report['model_ready_rows']:,}")
        print(f"Splits                  : {report['split_counts']}")
        print(f"Target Totals           : {report['target_totals']}")
        print(f"\nStatus: {report['status']} | Downstream Readiness: {report['downstream_readiness']}")
        print(f"Critical Failures: {report['critical_failure_count']} | Warnings: {report['warning_count']}")

        return 0 if report["status"] != "FAIL" else 1
    except Exception as exc:
        print(f"\nCRITICAL FAILURE: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
