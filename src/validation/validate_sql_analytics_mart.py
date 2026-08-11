"""Validate DuckDB SQL analytical layer and feature parity against Python outputs.

Contract: docs/data_quality/cleaning_contract.md, spatial_assignment_contract.md
Config:   config/modeling.yml
Decision: D019 (DuckDB local SQL analytics & Power BI serving layer)

Validates:
1. Executable SQL data-quality reconciliations (21 checks).
2. Exact parity between DuckDB SQL window features and Python pandas features.
3. Exported Power BI history mart (data/processed/power_bi_corridor_history.parquet).
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.build_sql_analytics_mart import (  # noqa: E402
    DB_PATH,
    MART_OUTPUT_PATH,
    SQL_DIR,
    SQL_SCRIPTS,
)

VALIDATION_REPORT_PATH = ROOT / "docs" / "data_quality" / "sql_analytics_mart_validation.json"
RUNS_DIR = ROOT / "docs" / "data_quality" / "sql_analytics_mart_runs"


def _write_json_atomic(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.json")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    tmp.replace(path)


def audit_sql_python_feature_parity(conn: duckdb.DuckDBPyConnection) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Compare SQL window function features with Python pandas features and verify exact parity."""
    parity_checks = []

    # Join Python features view and SQL audit view
    parity_query = """
    SELECT
        f.corridor_id,
        f.crash_month_start,
        -- Lags total_crashes
        f.total_crashes_lag1, a.sql_total_crashes_lag1,
        f.total_crashes_lag3, a.sql_total_crashes_lag3,
        f.total_crashes_lag6, a.sql_total_crashes_lag6,
        f.total_crashes_lag12, a.sql_total_crashes_lag12,
        -- Rolling sums total_crashes
        f.total_crashes_roll_sum3, a.sql_total_crashes_roll_sum3,
        f.total_crashes_roll_sum6, a.sql_total_crashes_roll_sum6,
        f.total_crashes_roll_sum12, a.sql_total_crashes_roll_sum12,
        -- Rolling means total_crashes
        f.total_crashes_roll_mean3, a.sql_total_crashes_roll_mean3,
        f.total_crashes_roll_mean6, a.sql_total_crashes_roll_mean6,
        f.total_crashes_roll_mean12, a.sql_total_crashes_roll_mean12,
        -- Lags ksi_crashes
        f.ksi_crashes_lag1, a.sql_ksi_crashes_lag1,
        f.ksi_crashes_lag3, a.sql_ksi_crashes_lag3,
        f.ksi_crashes_lag6, a.sql_ksi_crashes_lag6,
        f.ksi_crashes_lag12, a.sql_ksi_crashes_lag12,
        -- Rolling sums ksi_crashes
        f.ksi_crashes_roll_sum3, a.sql_ksi_crashes_roll_sum3,
        f.ksi_crashes_roll_sum6, a.sql_ksi_crashes_roll_sum6,
        f.ksi_crashes_roll_sum12, a.sql_ksi_crashes_roll_sum12,
        -- Rolling means ksi_crashes
        f.ksi_crashes_roll_mean3, a.sql_ksi_crashes_roll_mean3,
        f.ksi_crashes_roll_mean6, a.sql_ksi_crashes_roll_mean6,
        f.ksi_crashes_roll_mean12, a.sql_ksi_crashes_roll_mean12
    FROM vw_corridor_month_features f
    JOIN vw_corridor_month_feature_audit a
      ON f.corridor_id = a.corridor_id
     AND f.crash_month_start = a.crash_month_start
    ORDER BY f.corridor_id, f.crash_month_start;
    """

    df_parity = conn.execute(parity_query).df()
    n_rows = len(df_parity)

    lags = ["lag1", "lag3", "lag6", "lag12"]
    sums = ["roll_sum3", "roll_sum6", "roll_sum12"]
    means = ["roll_mean3", "roll_mean6", "roll_mean12"]
    targets = ["total_crashes", "ksi_crashes"]

    mismatched_lags = 0
    mismatched_sums = 0
    max_mean_diff = 0.0
    null_mismatches = 0

    for target in targets:
        for lag in lags:
            py_col = f"{target}_{lag}"
            sql_col = f"sql_{target}_{lag}"

            # Check null position parity
            null_diff = (df_parity[py_col].isna() != df_parity[sql_col].isna()).sum()
            null_mismatches += int(null_diff)

            # Check non-null value match
            valid_mask = df_parity[py_col].notna() & df_parity[sql_col].notna()
            diff = (df_parity.loc[valid_mask, py_col] - df_parity.loc[valid_mask, sql_col]).abs().sum()
            mismatched_lags += int(diff)

        for sm in sums:
            py_col = f"{target}_{sm}"
            sql_col = f"sql_{target}_{sm}"

            null_diff = (df_parity[py_col].isna() != df_parity[sql_col].isna()).sum()
            null_mismatches += int(null_diff)

            valid_mask = df_parity[py_col].notna() & df_parity[sql_col].notna()
            diff = (df_parity.loc[valid_mask, py_col] - df_parity.loc[valid_mask, sql_col]).abs().sum()
            mismatched_sums += int(diff)

        for mn in means:
            py_col = f"{target}_{mn}"
            sql_col = f"sql_{target}_{mn}"

            null_diff = (df_parity[py_col].isna() != df_parity[sql_col].isna()).sum()
            null_mismatches += int(null_diff)

            valid_mask = df_parity[py_col].notna() & df_parity[sql_col].notna()
            if valid_mask.any():
                max_diff_col = (
                    df_parity.loc[valid_mask, py_col] - df_parity.loc[valid_mask, sql_col]
                ).abs().max()
                max_mean_diff = max(max_mean_diff, float(max_diff_col))

    metrics = {
        "matching_rows": n_rows,
        "mismatched_lags": mismatched_lags,
        "mismatched_sums": mismatched_sums,
        "max_mean_diff": round(max_mean_diff, 12),
        "null_mismatches": null_mismatches,
    }

    def _add_check(name: str, severity: str, passed: bool, evidence: str):
        parity_checks.append(
            {
                "check": name,
                "severity": severity,
                "passed": passed,
                "evidence": evidence,
            }
        )

    _add_check(
        "sql_python_feature_matching_rows_4128",
        "CRITICAL",
        n_rows == 4128,
        f"Feature parity audit matching rows: {n_rows:,} (expected 4,128)",
    )
    _add_check(
        "sql_python_lag_parity_zero_mismatch",
        "CRITICAL",
        mismatched_lags == 0,
        f"Mismatched non-null lag values between SQL and Python: {mismatched_lags}",
    )
    _add_check(
        "sql_python_rolling_sum_parity_zero_mismatch",
        "CRITICAL",
        mismatched_sums == 0,
        f"Mismatched non-null rolling sum values: {mismatched_sums}",
    )
    _add_check(
        "sql_python_rolling_mean_parity_max_diff_1e9",
        "CRITICAL",
        max_mean_diff <= 1e-9,
        f"Rolling mean max absolute difference: {max_mean_diff:.12e} (max allowed: 1e-9)",
    )
    _add_check(
        "sql_python_null_position_parity_zero_mismatch",
        "CRITICAL",
        null_mismatches == 0,
        f"Null-position mismatches between SQL and Python: {null_mismatches}",
    )

    return metrics, parity_checks


def validate_sql_analytics_mart(
    sql_dir: Path = SQL_DIR,
    db_path: Path = DB_PATH,
    mart_path: Path = MART_OUTPUT_PATH,
    report_output_path: Path = VALIDATION_REPORT_PATH,
    runs_dir: Path = RUNS_DIR,
    is_sample: bool = False,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Execute SQL analytics pipeline, validate SQL data quality & parity, and return report dict."""
    conn = duckdb.connect(":memory:")

    # Execute SQL scripts 01..04
    for script_name in SQL_SCRIPTS:
        script_file = sql_dir / script_name
        if not script_file.exists():
            raise FileNotFoundError(f"Missing SQL script: {script_file}")
        conn.execute(script_file.read_text(encoding="utf-8"))

    # Fetch 21 SQL reconciliation values from vw_data_quality_reconciliation
    dq_df = conn.execute("SELECT * FROM vw_data_quality_reconciliation").df()
    dq = dq_df.iloc[0].to_dict()

    # Audit SQL / Python Feature Parity
    parity_metrics, parity_checks = audit_sql_python_feature_parity(conn)

    # Validate Exported Power BI History Mart
    mart_df = pd.read_parquet(mart_path) if mart_path.exists() else pd.DataFrame()
    mart_rows = len(mart_df)
    mart_keys = len(mart_df[["corridor_id", "crash_month_start"]].drop_duplicates()) if not mart_df.empty else 0

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

    # Add 21 SQL DQ checks
    _add_check(
        "sql_total_rows_4128",
        "CRITICAL",
        dq["total_rows"] == 4128,
        f"SQL total rows: {dq['total_rows']:,} (expected 4,128)",
    )
    _add_check(
        "sql_distinct_keys_4128",
        "CRITICAL",
        dq["distinct_keys"] == 4128,
        f"SQL distinct corridor-month keys: {dq['distinct_keys']:,} (expected 4,128)",
    )
    _add_check(
        "sql_duplicate_keys_zero",
        "CRITICAL",
        dq["duplicate_keys"] == 0,
        f"SQL duplicate keys: {dq['duplicate_keys']}",
    )
    _add_check(
        "sql_corridor_count_43",
        "CRITICAL",
        dq["corridor_count"] == 43,
        f"SQL corridor count: {dq['corridor_count']} (expected 43)",
    )
    _add_check(
        "sql_months_per_corridor_96",
        "CRITICAL",
        dq["min_months_per_corridor"] == 96 and dq["max_months_per_corridor"] == 96,
        f"SQL months per corridor: min={dq['min_months_per_corridor']}, max={dq['max_months_per_corridor']} (expected 96)",
    )
    _add_check(
        "sql_min_month_2018_01_01",
        "CRITICAL",
        str(dq["min_month"]).startswith("2018-01-01"),
        f"SQL min month: '{dq['min_month']}' (expected '2018-01-01')",
    )
    _add_check(
        "sql_max_month_2025_12_01",
        "CRITICAL",
        str(dq["max_month"]).startswith("2025-12-01"),
        f"SQL max month: '{dq['max_month']}' (expected '2025-12-01')",
    )
    _add_check(
        "sql_total_crashes_sum_112421",
        "CRITICAL",
        dq["total_crashes_sum"] == 112421,
        f"SQL total_crashes sum: {dq['total_crashes_sum']:,} (expected 112,421)",
    )
    _add_check(
        "sql_ksi_crashes_sum_2297",
        "CRITICAL",
        dq["ksi_crashes_sum"] == 2297,
        f"SQL ksi_crashes sum: {dq['ksi_crashes_sum']:,} (expected 2,297)",
    )
    _add_check(
        "sql_zero_crash_rows_7",
        "WARNING",
        dq["zero_crash_rows"] == 7,
        f"SQL zero-crash corridor-months: {dq['zero_crash_rows']} (expected 7)",
    )
    _add_check(
        "sql_warmup_rows_516",
        "CRITICAL",
        dq["warmup_rows"] == 516,
        f"SQL warmup split rows: {dq['warmup_rows']} (expected 516)",
    )
    _add_check(
        "sql_train_rows_2580",
        "CRITICAL",
        dq["train_rows"] == 2580,
        f"SQL train split rows: {dq['train_rows']} (expected 2,580)",
    )
    _add_check(
        "sql_validation_rows_516",
        "CRITICAL",
        dq["validation_rows"] == 516,
        f"SQL validation split rows: {dq['validation_rows']} (expected 516)",
    )
    _add_check(
        "sql_test_rows_516",
        "CRITICAL",
        dq["test_rows"] == 516,
        f"SQL test split rows: {dq['test_rows']} (expected 516)",
    )
    _add_check(
        "sql_model_ready_rows_3612",
        "CRITICAL",
        dq["model_ready_rows"] == 3612,
        f"SQL model-ready rows: {dq['model_ready_rows']:,} (expected 3,612)",
    )
    _add_check(
        "sql_negative_counts_zero",
        "CRITICAL",
        dq["negative_counts"] == 0,
        f"SQL negative counts: {dq['negative_counts']}",
    )
    _add_check(
        "sql_null_keys_zero",
        "CRITICAL",
        dq["null_keys"] == 0,
        f"SQL null keys: {dq['null_keys']}",
    )
    _add_check(
        "sql_unexpected_splits_zero",
        "CRITICAL",
        dq["unexpected_splits"] == 0,
        f"SQL unexpected split values: {dq['unexpected_splits']}",
    )
    _add_check(
        "sql_ksi_reconciliation_diff_zero",
        "CRITICAL",
        dq["ksi_reconciliation_diff"] == 0,
        f"SQL KSI reconciliation diff: {dq['ksi_reconciliation_diff']}",
    )
    _add_check(
        "sql_severity_reconciliation_diff_zero",
        "CRITICAL",
        dq["severity_reconciliation_diff"] == 0,
        f"SQL severity reconciliation diff: {dq['severity_reconciliation_diff']}",
    )

    # Append Parity Checks
    checks.extend(parity_checks)

    # Exported Power BI Mart Checks
    _add_check(
        "power_bi_mart_rows_4128",
        "CRITICAL",
        mart_rows == 4128,
        f"Exported Power BI mart rows: {mart_rows:,} (expected 4,128)",
    )
    _add_check(
        "power_bi_mart_unique_keys_4128",
        "CRITICAL",
        mart_keys == 4128,
        f"Exported Power BI mart unique keys: {mart_keys:,} (expected 4,128)",
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
        "pipeline": "sql_analytics_mart",
        "run_id": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "duckdb_version": duckdb.__version__,
        "is_sample": is_sample,
        "sql_reconciliation": dq,
        "feature_parity": parity_metrics,
        "power_bi_mart": {
            "row_count": mart_rows,
            "unique_key_count": mart_keys,
        },
        "status": status_val,
        "downstream_readiness": readiness_val,
        "critical_failure_count": crit_failures,
        "warning_count": warnings,
        "checks": checks,
    }

    if not is_sample:
        _write_json_atomic(report_output_path, report)
        runs_dir.mkdir(parents=True, exist_ok=True)
        run_id = report.get("run_id", "latest")
        hist_path = runs_dir / f"sql_analytics_mart_validation_{run_id}.json"
        _write_json_atomic(hist_path, report)
        print(f"Saved validation report to {report_output_path}")

    conn.close()
    return report, checks


def main() -> int:
    print("=" * 70)
    print("Validate DuckDB SQL Analytical Layer & Power BI Mart")
    print("=" * 70)

    try:
        report, checks = validate_sql_analytics_mart()
        print("\n" + "=" * 70)
        print("VALIDATION SUMMARY")
        print("=" * 70)
        print(f"Status: {report['status']} | Downstream Readiness: {report['downstream_readiness']}")
        print(f"Critical Failures: {report['critical_failure_count']} | Warnings: {report['warning_count']}")

        print("\n" + "=" * 70)
        print("EXECUTED SQL RECONCILIATION RESULTS")
        print("=" * 70)
        for check in checks:
            symbol = "PASS" if check["passed"] else "FAIL"
            print(f"  [{symbol:<4}] {check['check']:<45} ({check['severity']}) - {check['evidence']}")

        return 0 if report["status"] != "FAIL" else 1
    except Exception as exc:
        print(f"\nCRITICAL FAILURE: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
