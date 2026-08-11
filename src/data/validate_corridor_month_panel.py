"""Validate corridor-month modeling panel.

Contract: docs/data_quality/cleaning_contract.md, spatial_assignment_contract.md
Config:   config/project.yml

Validates data/processed/corridor_month_panel.parquet against authoritative
contracts, row counts (4,128), composite key uniqueness, 96 months per corridor,
severity reconciliations, KSI derivation, non-negative integer counts, static metadata
completeness, and zero-crash month preservation.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.build_corridor_month_panel import (  # noqa: E402
    PANEL_OUTPUT_PATH,
    REGISTER_PATH,
    RUNS_DIR,
    VALIDATION_REPORT_PATH,
    _write_json_atomic,
    validate_corridor_month_panel,
)


def run_panel_validation(
    panel_path: Path = PANEL_OUTPUT_PATH,
    register_path: Path = REGISTER_PATH,
    report_output_path: Path = VALIDATION_REPORT_PATH,
    runs_dir: Path = RUNS_DIR,
) -> dict[str, Any]:
    """Run validation checks on corridor-month panel Parquet."""
    panel_df = pd.read_parquet(panel_path)
    register_df = pd.read_csv(register_path)
    register_ids = set(register_df["corridor_id"].unique())

    is_sample = len(panel_df) < 4128

    report, checks = validate_corridor_month_panel(panel_df, register_ids, is_sample=is_sample)

    if not is_sample:
        _write_json_atomic(report_output_path, report)
        runs_dir.mkdir(parents=True, exist_ok=True)
        run_id = report.get("run_id", "latest")
        hist_path = runs_dir / f"corridor_month_panel_validation_{run_id}.json"
        _write_json_atomic(hist_path, report)
        print(f"Saved validation report to {report_output_path}")

    return report


def main() -> int:
    print("=" * 70)
    print("Validate Corridor-Month Modeling Panel")
    print("=" * 70)

    try:
        report = run_panel_validation()
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
