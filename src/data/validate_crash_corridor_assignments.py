"""Validate primary crash-to-corridor assignments.

Contract: docs/data_quality/spatial_assignment_contract.md
Config:   config/spatial.yml

Validates data/interim/crash_corridor_assignments.parquet against authoritative
contracts, row counts, unique crash keys, 4-category reconciliation, tie handling,
corridor ID validity, and threshold compliance.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.assign_crashes_to_corridors import load_spatial_config  # noqa: E402
from src.data.build_crash_corridor_assignments import (  # noqa: E402
    ASSIGNMENT_OUTPUT_PATH,
    CRASHES_PATH,
    REGISTER_PATH,
    RUNS_DIR,
    SPATIAL_CONFIG_PATH,
    VALIDATION_REPORT_PATH,
    _write_json_atomic,
    validate_primary_assignments,
)


def run_assignment_validation(
    assignment_path: Path = ASSIGNMENT_OUTPUT_PATH,
    crashes_path: Path = CRASHES_PATH,
    register_path: Path = REGISTER_PATH,
    spatial_config_path: Path = SPATIAL_CONFIG_PATH,
    report_output_path: Path = VALIDATION_REPORT_PATH,
    runs_dir: Path = RUNS_DIR,
) -> dict[str, Any]:
    """Run validation checks on primary crash corridor assignments parquet."""
    spatial_config = load_spatial_config(spatial_config_path)
    selected_threshold_feet = float(spatial_config["crash_assignment"]["selected_distance_threshold_feet"])
    threshold_status = str(spatial_config["crash_assignment"]["threshold_status"])

    assignments_df = pd.read_parquet(assignment_path)
    all_crashes = pd.read_parquet(crashes_path, columns=["crash_record_id", "has_valid_coordinates"])
    register_df = pd.read_csv(register_path)

    total_count = len(all_crashes)
    eligible_count = int((all_crashes["has_valid_coordinates"] == True).sum())
    invalid_count = int((all_crashes["has_valid_coordinates"] == False).sum())
    corridor_ids = set(register_df["corridor_id"].unique())
    corridor_count = len(corridor_ids)

    is_sample = len(assignments_df) < total_count

    report, checks = validate_primary_assignments(
        assignments_df,
        total_crash_count=total_count,
        eligible_crash_count=eligible_count,
        invalid_coordinate_count=invalid_count,
        authoritative_register_ids=corridor_ids,
        corridor_count=corridor_count,
        selected_threshold_feet=selected_threshold_feet,
        threshold_status=threshold_status,
        is_sample=is_sample,
    )

    if not is_sample:
        _write_json_atomic(report_output_path, report)
        runs_dir.mkdir(parents=True, exist_ok=True)
        run_id = report.get("run_id", "latest")
        hist_path = runs_dir / f"crash_corridor_assignment_validation_{run_id}.json"
        _write_json_atomic(hist_path, report)
        print(f"Saved validation report to {report_output_path}")

    return report


def main() -> int:
    print("=" * 70)
    print("Validate Primary Crash-to-Corridor Assignments")
    print("=" * 70)

    try:
        report = run_assignment_validation()
        print("\n" + "=" * 70)
        print("VALIDATION SUMMARY")
        print("=" * 70)
        print(f"Status: {report['status']} | Downstream Readiness: {report['downstream_readiness']}")
        print(f"Critical Failures: {report['critical_failure_count']} | Warnings: {report['warning_count']}")

        for check in report["checks"]:
            symbol = "PASS" if check["passed"] else "FAIL"
            print(f"  [{symbol:<4}] {check['check']:<45} ({check['severity']}) - {check['evidence']}")

        return 0 if report["status"] != "FAIL" else 1
    except Exception as exc:
        print(f"\nCRITICAL FAILURE: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
