"""Build complete 43 x 96 corridor-month modeling panel for Vision Zero Chicago.

Contract: docs/data_quality/cleaning_contract.md, spatial_assignment_contract.md
Config:   config/project.yml, config/cleaning.yml, config/spatial.yml
Decision: D001 (Corridor-month as modeling grain), D002 (43 corridors), D007 (Jan 2018 - Dec 2025 window)

Aggregates primary_assigned crashes (112,421 expected) to the 4,128 corridor-month panel
(43 corridors x 96 months). Zero-crash corridor-months remain present and zero-filled.

Required output:
data/processed/corridor_month_panel.parquet (4,128 rows, unique key: corridor_id + crash_month_start).
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import geopandas as gpd
import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PROJECT_CONFIG_PATH = ROOT / "config" / "project.yml"
CRASHES_PATH = ROOT / "data" / "interim" / "crashes_clean.parquet"
ASSIGNMENT_PATH = ROOT / "data" / "interim" / "crash_corridor_assignments.parquet"
REGISTER_PATH = ROOT / "data" / "interim" / "high_crash_corridor_register.csv"
CORRIDORS_PATH = ROOT / "data" / "interim" / "high_crash_corridors.parquet"

PANEL_OUTPUT_PATH = ROOT / "data" / "processed" / "corridor_month_panel.parquet"
VALIDATION_REPORT_PATH = ROOT / "docs" / "data_quality" / "corridor_month_panel_validation.json"
RUNS_DIR = ROOT / "docs" / "data_quality" / "corridor_month_panel_runs"

COUNT_COLUMNS = [
    "total_crashes",
    "fatal_crashes",
    "serious_injury_crashes",
    "ksi_crashes",
    "moderate_injury_crashes",
    "minor_injury_crashes",
    "property_damage_only_crashes",
    "unknown_severity_crashes",
]


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


def load_project_config(config_path: Optional[Path] = None) -> dict:
    """Load config/project.yml."""
    if config_path is None:
        config_path = PROJECT_CONFIG_PATH
    with config_path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def validate_input_grains(
    all_crashes: pd.DataFrame,
    all_assignments: pd.DataFrame,
    register_df: pd.DataFrame,
    corridors_gdf: gpd.GeoDataFrame,
) -> None:
    """Validate input grains before joining.

    Grains:
    - crashes_clean: 1 row per crash_record_id (877,919)
    - assignments: 1 row per crash_record_id (877,919)
    - register: 1 row per corridor_id (43)
    - corridors: 1 row per corridor_id (43)
    """
    if len(all_crashes) != 877919:
        raise ValueError(f"crashes_clean row count {len(all_crashes)} != expected 877,919")
    if all_crashes["crash_record_id"].duplicated().any() or all_crashes["crash_record_id"].isna().any():
        raise ValueError("crashes_clean primary key crash_record_id is not unique and non-null")

    if len(all_assignments) != 877919:
        raise ValueError(f"crash_corridor_assignments row count {len(all_assignments)} != expected 877,919")
    if all_assignments["crash_record_id"].duplicated().any() or all_assignments["crash_record_id"].isna().any():
        raise ValueError("assignments primary key crash_record_id is not unique and non-null")

    if len(register_df) != 43:
        raise ValueError(f"high_crash_corridor_register row count {len(register_df)} != expected 43")
    if register_df["corridor_id"].duplicated().any() or register_df["corridor_id"].isna().any():
        raise ValueError("corridor register primary key corridor_id is not unique and non-null")

    if len(corridors_gdf) != 43:
        raise ValueError(f"high_crash_corridors row count {len(corridors_gdf)} != expected 43")
    if corridors_gdf["corridor_id"].duplicated().any() or corridors_gdf["corridor_id"].isna().any():
        raise ValueError("corridor geometry primary key corridor_id is not unique and non-null")


def build_complete_grid(
    register_df: pd.DataFrame,
    corridors_gdf: gpd.GeoDataFrame,
    start_date: str = "2018-01-01",
    end_date: str = "2025-12-01",
) -> pd.DataFrame:
    """Build the complete 43 corridors x 96 calendar months grid with static metadata."""
    dates = pd.date_range(start=start_date, end=end_date, freq="MS")
    month_starts = pd.Series(dates, name="crash_month_start")

    # Static metadata prepared per corridor
    meta = register_df[["corridor_id", "corridor_name", "source_group"]].merge(
        corridors_gdf[["corridor_id", "corridor_length_feet"]],
        on="corridor_id",
        how="inner",
    )
    if len(meta) != len(register_df):
        raise ValueError(f"Metadata merge resulted in {len(meta)} rows instead of expected {len(register_df)}.")

    meta["corridor_length_feet"] = meta["corridor_length_feet"].round(3)
    meta["corridor_length_miles"] = (meta["corridor_length_feet"] / 5280.0).round(4)

    # Cartesian product (43 x 96 = 4,128)
    grid = meta.merge(month_starts, how="cross")

    grid["calendar_year"] = grid["crash_month_start"].dt.year
    grid["calendar_month"] = grid["crash_month_start"].dt.month
    grid["calendar_quarter"] = grid["crash_month_start"].dt.quarter

    return grid


def aggregate_primary_crashes(
    all_crashes: pd.DataFrame,
    all_assignments: pd.DataFrame,
    register_corridor_ids: set[str],
    expected_primary_count: Optional[int] = None,
) -> pd.DataFrame:
    """Filter primary_assigned crashes, validate 1:1 join, and aggregate severity counts by corridor-month."""
    primary_assign = all_assignments[
        all_assignments["assignment_status"] == "primary_assigned"
    ].copy()

    if expected_primary_count is not None and len(primary_assign) != expected_primary_count:
        raise ValueError(f"Primary assigned count {len(primary_assign):,} != expected {expected_primary_count:,}")

    # 1:1 Join with clean crashes
    primary = primary_assign[["crash_record_id", "corridor_id"]].merge(
        all_crashes[["crash_record_id", "severity_kabco", "crash_month_start"]],
        on="crash_record_id",
        how="inner",
    )

    if len(primary) != len(primary_assign):
        raise ValueError(
            f"Joined primary crash count {len(primary):,} != primary assignment count {len(primary_assign):,}"
        )

    # Validate corridor IDs and month window
    unknown_corrs = set(primary["corridor_id"].unique()) - register_corridor_ids
    if unknown_corrs:
        raise ValueError(f"Joined primary crashes contain unknown corridor IDs: {unknown_corrs}")

    min_m = primary["crash_month_start"].min()
    max_m = primary["crash_month_start"].max()
    if min_m < pd.Timestamp("2018-01-01") or max_m > pd.Timestamp("2025-12-01"):
        raise ValueError(f"Joined crashes contain month out of range: [{min_m}, {max_m}]")

    # KABCO / U Severity indicators
    primary["fatal_crashes"] = (primary["severity_kabco"] == "K").astype(int)
    primary["serious_injury_crashes"] = (primary["severity_kabco"] == "A").astype(int)
    primary["moderate_injury_crashes"] = (primary["severity_kabco"] == "B").astype(int)
    primary["minor_injury_crashes"] = (primary["severity_kabco"] == "C").astype(int)
    primary["property_damage_only_crashes"] = (primary["severity_kabco"] == "O").astype(int)
    primary["unknown_severity_crashes"] = (primary["severity_kabco"] == "U").astype(int)

    agg = (
        primary.groupby(["corridor_id", "crash_month_start"])[
            [
                "fatal_crashes",
                "serious_injury_crashes",
                "moderate_injury_crashes",
                "minor_injury_crashes",
                "property_damage_only_crashes",
                "unknown_severity_crashes",
            ]
        ]
        .sum()
        .reset_index()
    )

    agg["total_crashes"] = (
        agg["fatal_crashes"]
        + agg["serious_injury_crashes"]
        + agg["moderate_injury_crashes"]
        + agg["minor_injury_crashes"]
        + agg["property_damage_only_crashes"]
        + agg["unknown_severity_crashes"]
    )
    agg["ksi_crashes"] = agg["fatal_crashes"] + agg["serious_injury_crashes"]

    return agg


def validate_corridor_month_panel(
    panel_df: pd.DataFrame,
    authoritative_register_ids: set[str],
    is_sample: bool = False,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Validate corridor-month panel dataframe and return report dict & checks list."""
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

    n_rows = len(panel_df)

    # 1. Total row count 4,128
    if not is_sample:
        _add_check(
            "panel_row_count_is_4128",
            "CRITICAL",
            n_rows == 4128,
            f"Panel row count: {n_rows:,} (expected 4,128)",
        )
    else:
        _add_check(
            "panel_row_count_is_4128",
            "WARNING",
            True,
            f"Sample mode active: evaluating sample of {n_rows:,} rows.",
        )

    # 2. Corridor count 43
    n_corridors = panel_df["corridor_id"].nunique()
    _add_check(
        "corridor_count_is_43",
        "CRITICAL",
        n_corridors == 43,
        f"Corridor count: {n_corridors} (expected 43)",
    )

    # 3. Exactly 96 months per corridor
    months_per_corridor = panel_df.groupby("corridor_id")["crash_month_start"].count()
    all_96 = (months_per_corridor == 96).all()
    _add_check(
        "month_count_per_corridor_is_96",
        "CRITICAL",
        bool(all_96),
        f"All corridors have 96 months: {all_96} (min: {months_per_corridor.min()}, max: {months_per_corridor.max()})",
    )

    # 4. Composite key uniqueness & non-null
    null_keys = int(
        (panel_df["corridor_id"].isna() | panel_df["crash_month_start"].isna()).sum()
    )
    dup_keys = int(
        panel_df.duplicated(subset=["corridor_id", "crash_month_start"]).sum()
    )
    _add_check(
        "composite_key_unique_and_non_null",
        "CRITICAL",
        null_keys == 0 and dup_keys == 0,
        f"Null composite keys: {null_keys}, Duplicate composite keys: {dup_keys}",
    )

    # 5 & 6. Min and max months
    min_m = panel_df["crash_month_start"].min()
    max_m = panel_df["crash_month_start"].max()
    _add_check(
        "min_month_is_2018_01_01",
        "CRITICAL",
        min_m == pd.Timestamp("2018-01-01"),
        f"Minimum crash_month_start: '{min_m}' (expected '2018-01-01')",
    )
    _add_check(
        "max_month_is_2025_12_01",
        "CRITICAL",
        max_m == pd.Timestamp("2025-12-01"),
        f"Maximum crash_month_start: '{max_m}' (expected '2025-12-01')",
    )

    # 7. Global panel total primary crashes reconciles to 112,421
    total_panel_crashes = int(panel_df["total_crashes"].sum())
    if not is_sample:
        _add_check(
            "total_primary_crashes_reconciled_112421",
            "CRITICAL",
            total_panel_crashes == 112421,
            f"Total panel primary crashes: {total_panel_crashes:,} (expected 112,421)",
        )
    else:
        _add_check(
            "total_primary_crashes_reconciled_112421",
            "WARNING",
            True,
            f"Sample mode active: total crashes is {total_panel_crashes:,}.",
        )

    # 8. Row-level severity reconciliation
    row_sev_sum = (
        panel_df["fatal_crashes"]
        + panel_df["serious_injury_crashes"]
        + panel_df["moderate_injury_crashes"]
        + panel_df["minor_injury_crashes"]
        + panel_df["property_damage_only_crashes"]
        + panel_df["unknown_severity_crashes"]
    )
    sev_recon_diff = int((panel_df["total_crashes"] - row_sev_sum).abs().sum())
    _add_check(
        "row_level_severity_reconciliation",
        "CRITICAL",
        sev_recon_diff == 0,
        f"Row-level severity reconciliation diff sum: {sev_recon_diff}",
    )

    # 9. KSI equals fatal plus serious injury
    ksi_expected = panel_df["fatal_crashes"] + panel_df["serious_injury_crashes"]
    ksi_diff = int((panel_df["ksi_crashes"] - ksi_expected).abs().sum())
    _add_check(
        "ksi_crashes_equals_fatal_plus_serious",
        "CRITICAL",
        ksi_diff == 0,
        f"KSI definition diff sum: {ksi_diff}",
    )

    # 10. Non-negative integers for count fields
    neg_counts = 0
    non_int_counts = 0
    for col in COUNT_COLUMNS:
        if (panel_df[col] < 0).any():
            neg_counts += 1
        if not pd.api.types.is_integer_dtype(panel_df[col]):
            non_int_counts += 1

    _add_check(
        "all_count_fields_non_negative_integers",
        "CRITICAL",
        neg_counts == 0 and non_int_counts == 0,
        f"Columns with negative counts: {neg_counts}, non-integer columns: {non_int_counts}",
    )

    # 11. Assigned corridor IDs valid subset of register
    actual_corridors = set(panel_df["corridor_id"].unique())
    unknown_corridors = actual_corridors - authoritative_register_ids
    _add_check(
        "assigned_corridor_ids_valid_subset",
        "CRITICAL",
        len(unknown_corridors) == 0,
        f"Unknown corridor IDs found in panel: {sorted(list(unknown_corridors)) if unknown_corridors else 'none'}",
    )

    # 12. No missing static metadata
    meta_cols = ["corridor_name", "source_group", "corridor_length_feet", "corridor_length_miles"]
    null_meta = int(panel_df[meta_cols].isna().sum().sum())
    _add_check(
        "no_missing_corridor_metadata",
        "CRITICAL",
        null_meta == 0,
        f"Null static corridor metadata cells: {null_meta}",
    )

    # 13. Zero-crash months present
    zero_crash_rows = int((panel_df["total_crashes"] == 0).sum())
    _add_check(
        "zero_crash_months_present",
        "WARNING",
        zero_crash_rows > 0,
        f"Zero-crash corridor-months count: {zero_crash_rows:,} ({zero_crash_rows/n_rows:.1%})",
    )

    # 14. Deterministic ordering check
    sorted_df = panel_df.sort_values(
        by=["corridor_id", "crash_month_start"], ascending=[True, True]
    ).reset_index(drop=True)
    is_sorted = panel_df[["corridor_id", "crash_month_start"]].equals(
        sorted_df[["corridor_id", "crash_month_start"]]
    )
    _add_check(
        "deterministic_ordering",
        "CRITICAL",
        is_sorted,
        f"Panel sorted by (corridor_id, crash_month_start): {is_sorted}",
    )

    crit_failures = sum(1 for c in checks if c["severity"] == "CRITICAL" and not c["passed"])
    warnings = sum(1 for c in checks if c["severity"] == "WARNING" and not c["passed"])

    if crit_failures > 0:
        status_val = "FAIL"
        readiness_val = "BLOCKED"
    elif warnings > 0:
        status_val = "PASS_WITH_WARNINGS"
        readiness_val = "READY_FOR_MODELING"
    else:
        status_val = "PASS"
        readiness_val = "READY_FOR_MODELING"

    severity_totals = {
        col: int(panel_df[col].sum()) for col in COUNT_COLUMNS
    }

    report = {
        "pipeline": "corridor_month_panel",
        "run_id": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "is_sample": is_sample,
        "corridor_count": n_corridors,
        "history_months": 96,
        "total_panel_rows": n_rows,
        "min_month": str(min_m),
        "max_month": str(max_m),
        "zero_crash_months_count": zero_crash_rows,
        "severity_totals": severity_totals,
        "reconciliation": {
            "expected_primary_crashes": 112421,
            "panel_total_crashes": total_panel_crashes,
            "reconciliation_diff": 112421 - total_panel_crashes if not is_sample else 0,
        },
        "status": status_val,
        "downstream_readiness": readiness_val,
        "critical_failure_count": crit_failures,
        "warning_count": warnings,
        "checks": checks,
    }

    return report, checks


def build_corridor_month_panel(
    crashes_path: Path = CRASHES_PATH,
    assignment_path: Path = ASSIGNMENT_PATH,
    register_path: Path = REGISTER_PATH,
    corridors_path: Path = CORRIDORS_PATH,
    output_path: Path = PANEL_OUTPUT_PATH,
    validation_report_path: Path = VALIDATION_REPORT_PATH,
    runs_dir: Path = RUNS_DIR,
    sample_size: Optional[int] = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Build and validate corridor-month panel Parquet and JSON validation report."""
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    print(f"Run ID: {run_id}")

    t0_load = time.time()
    all_crashes = pd.read_parquet(
        crashes_path,
        columns=["crash_record_id", "severity_kabco", "crash_month_start"],
    )
    all_assignments = pd.read_parquet(
        assignment_path,
        columns=["crash_record_id", "assignment_status", "corridor_id"],
    )
    register_df = pd.read_csv(register_path)
    corridors_gdf = gpd.read_parquet(corridors_path)
    t_load = time.time() - t0_load

    is_sample = sample_size is not None
    if is_sample:
        print(f"[SAMPLE MODE] Limiting crashes to sample of {sample_size:,}.")

    print(f"Loaded inputs in {t_load:.3f}s: {len(all_crashes):,} crashes, {len(register_df)} register corridors.")

    if not is_sample:
        validate_input_grains(all_crashes, all_assignments, register_df, corridors_gdf)

    register_ids = set(register_df["corridor_id"].unique())

    # Build 43 x 96 grid
    grid = build_complete_grid(register_df, corridors_gdf)

    # Aggregate primary assigned crashes
    crashes_to_agg = all_crashes
    assignments_to_agg = all_assignments
    if is_sample and sample_size is not None:
        crashes_to_agg = all_crashes.iloc[:sample_size].copy()
        assignments_to_agg = all_assignments[
            all_assignments["crash_record_id"].isin(crashes_to_agg["crash_record_id"])
        ].copy()

    expected_count = 112421 if not is_sample else None
    agg_df = aggregate_primary_crashes(
        crashes_to_agg, assignments_to_agg, register_ids, expected_primary_count=expected_count
    )

    # Left join grid with crash aggregates
    panel_df = grid.merge(agg_df, on=["corridor_id", "crash_month_start"], how="left")

    # Zero fill missing count fields
    for col in COUNT_COLUMNS:
        panel_df[col] = panel_df[col].fillna(0).astype("int64")

    # Sort deterministically
    panel_df = panel_df.sort_values(
        by=["corridor_id", "crash_month_start"], ascending=[True, True]
    ).reset_index(drop=True)

    # Reorder columns logically
    column_order = [
        "corridor_id",
        "crash_month_start",
        "calendar_year",
        "calendar_month",
        "calendar_quarter",
        "corridor_name",
        "source_group",
        "corridor_length_feet",
        "corridor_length_miles",
        "total_crashes",
        "fatal_crashes",
        "serious_injury_crashes",
        "ksi_crashes",
        "moderate_injury_crashes",
        "minor_injury_crashes",
        "property_damage_only_crashes",
        "unknown_severity_crashes",
    ]
    panel_df = panel_df[column_order]

    report, checks = validate_corridor_month_panel(panel_df, register_ids, is_sample=is_sample)

    if not is_sample:
        _write_parquet_atomic(output_path, panel_df)
        _write_json_atomic(validation_report_path, report)
        runs_dir.mkdir(parents=True, exist_ok=True)
        hist_report_path = runs_dir / f"corridor_month_panel_validation_{run_id}.json"
        _write_json_atomic(hist_report_path, report)
        print(f"Saved panel Parquet to {output_path}")
        print(f"Saved validation report to {validation_report_path}")
    else:
        print("[SAMPLE MODE] Skipped overwriting panel Parquet and validation report artifacts.")

    return panel_df, report


def main() -> int:
    print("=" * 70)
    print("Build Corridor-Month Modeling Panel (Day 11 Phase 2A)")
    print("=" * 70)

    try:
        df, report = build_corridor_month_panel()
        print("\n" + "=" * 70)
        print("PANEL SUMMARY")
        print("=" * 70)
        print(f"Total Rows              : {report['total_panel_rows']:,}")
        print(f"Corridor Count          : {report['corridor_count']}")
        print(f"History Months          : {report['history_months']}")
        print(f"Date Range              : {report['min_month']} to {report['max_month']}")
        print(f"Zero-Crash Months       : {report['zero_crash_months_count']:,}")
        print("\nSeverity Totals:")
        for k, v in report["severity_totals"].items():
            print(f"  - {k:<28}: {v:>10,}")
        print(f"\nStatus: {report['status']} | Downstream Readiness: {report['downstream_readiness']}")
        print(f"Critical Failures: {report['critical_failure_count']} | Warnings: {report['warning_count']}")

        return 0 if report["status"] != "FAIL" else 1
    except Exception as exc:
        print(f"\nCRITICAL FAILURE: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
