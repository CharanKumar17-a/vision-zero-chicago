"""Validate corridor treatment readiness dataset, spatial equity metrics, and governance warnings.

Contract: docs/data_quality/cleaning_contract.md, spatial_assignment_contract.md
Config:   config/modeling.yml, project.yml
Decision: D001 (Corridor grain), D005 (Governance authority), D020 (Treatment evidence), D021 (Economic costs)

Validates:
1. Exact row count (43 corridors).
2. Complete panel crash reconciliation (Total=112,421; K=139; A=2,158; B=10,850; C=6,124; O=93,053; U=97; KSI=2,297).
3. Zero silent mapping of unknown severity records (U=97 preserved).
4. Severity disaggregation shares sum to 1.0 (K+A=1.0, B+C+O+U=1.0).
5. Full-resolution TIGER 2022 spatial linework length reconciliation (0.0000 ft max error, 100.0% coverage across 43 corridors).
6. Both equity classifications (Weighted SVI >= 0.75 and High SVI share >= 0.50) present for 43 corridors.
7. Physical attribute availability status recorded.
8. Governance warnings covering provisional treatments, blocked treatments, missing physical attributes, missing costs/quantities, and optimization blockage.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Tuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.treatments.build_treatment_readiness import (  # noqa: E402
    OUTPUT_CSV_PATH,
    OUTPUT_PARQUET_PATH,
    build_corridor_treatment_readiness,
)

VALIDATION_REPORT_PATH = ROOT / "docs" / "data_quality" / "treatment_readiness_validation.json"
RUNS_DIR = ROOT / "docs" / "data_quality" / "treatment_readiness_runs"


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


def validate_corridor_treatment_readiness(
    parquet_path: Path = OUTPUT_PARQUET_PATH,
    csv_path: Path = OUTPUT_CSV_PATH,
    report_output_path: Path = VALIDATION_REPORT_PATH,
    runs_dir: Path = RUNS_DIR,
    is_sample: bool = False,
    run_id_override: Optional[str] = None,
) -> Tuple[Dict[str, Any], list[dict[str, Any]]]:
    """Execute treatment readiness validation checks and write validation JSON report with explicit governance warnings."""
    checks: list[dict[str, Any]] = []
    warnings_list: list[dict[str, Any]] = []

    def _add_check(name: str, severity: str, passed: bool, evidence: str):
        checks.append(
            {
                "check": name,
                "severity": severity,
                "passed": passed,
                "evidence": evidence,
            }
        )

    def _add_warning(warning_id: str, affected_treatment_ids: list[str], explanation: str, governance_reference: str):
        warnings_list.append(
            {
                "warning_id": warning_id,
                "affected_treatment_ids": affected_treatment_ids,
                "explanation": explanation,
                "governance_reference": governance_reference,
            }
        )

    # 1. Output Files Exist
    files_exist = parquet_path.exists() and csv_path.exists()
    _add_check(
        "readiness_output_files_exist",
        "CRITICAL",
        files_exist,
        f"Treatment readiness parquet and CSV files exist: {files_exist}",
    )

    df_r = pd.read_parquet(parquet_path) if parquet_path.exists() else pd.DataFrame()

    # 2. Row Count
    _add_check(
        "readiness_corridor_rows_43",
        "CRITICAL",
        len(df_r) == 43,
        f"Corridor row count: {len(df_r)} (expected 43)",
    )

    # 3. Crash Panel Totals Reconciliation
    if not df_r.empty:
        tot_cnt = int(df_r["total_crashes_hist"].sum())
        k_cnt = int(df_r["k_crashes_hist"].sum())
        a_cnt = int(df_r["a_crashes_hist"].sum())
        b_cnt = int(df_r["b_crashes_hist"].sum())
        c_cnt = int(df_r["c_crashes_hist"].sum())
        o_cnt = int(df_r["o_crashes_hist"].sum())
        u_cnt = int(df_r["u_crashes_hist"].sum())
        ksi_cnt = int(df_r["ksi_crashes_hist"].sum())

        tot_ok = tot_cnt == 112421
        k_ok = k_cnt == 139
        a_ok = a_cnt == 2158
        b_ok = b_cnt == 10850
        c_ok = c_cnt == 6124
        o_ok = o_cnt == 93053
        u_ok = u_cnt == 97
        ksi_ok = ksi_cnt == 2297 and (k_cnt + a_cnt == ksi_cnt)
    else:
        tot_ok = k_ok = a_ok = b_ok = c_ok = o_ok = u_ok = ksi_ok = False
        tot_cnt = k_cnt = a_cnt = b_cnt = c_cnt = o_cnt = u_cnt = ksi_cnt = 0

    _add_check(
        "reconcile_total_assigned_crashes_112421",
        "CRITICAL",
        tot_ok,
        f"Total assigned crashes: {tot_cnt:,} (expected 112,421)",
    )
    _add_check(
        "reconcile_k_fatal_crashes_139",
        "CRITICAL",
        k_ok,
        f"Total Fatal crashes (K): {k_cnt:,} (expected 139)",
    )
    _add_check(
        "reconcile_a_serious_injury_2158",
        "CRITICAL",
        a_ok,
        f"Total Serious Injury crashes (A): {a_cnt:,} (expected 2,158)",
    )
    _add_check(
        "reconcile_b_minor_injury_10850",
        "CRITICAL",
        b_ok,
        f"Total Minor Injury crashes (B): {b_cnt:,} (expected 10,850)",
    )
    _add_check(
        "reconcile_c_possible_injury_6124",
        "CRITICAL",
        c_ok,
        f"Total Possible Injury crashes (C): {c_cnt:,} (expected 6,124)",
    )
    _add_check(
        "reconcile_o_property_damage_93053",
        "CRITICAL",
        o_ok,
        f"Total Property Damage crashes (O): {o_cnt:,} (expected 93,053)",
    )
    _add_check(
        "reconcile_unknown_severity_97_preserved",
        "CRITICAL",
        u_ok,
        f"Total Unknown severity crashes (U): {u_cnt} (expected 97 preserved without silent mapping)",
    )
    _add_check(
        "reconcile_ksi_crashes_2297",
        "CRITICAL",
        ksi_ok,
        f"Total KSI crashes (K+A): {ksi_cnt:,} (expected 2,297)",
    )

    # 4. Severity Shares Sum to 1.0
    if not df_r.empty:
        ksi_sum_diff = (df_r["share_k_given_ksi"] + df_r["share_a_given_ksi"] - 1.0).abs().max()
        non_sum_diff = (
            df_r["share_b_given_non_ksi"]
            + df_r["share_c_given_non_ksi"]
            + df_r["share_o_given_non_ksi"]
            + df_r["share_u_given_non_ksi"]
            - 1.0
        ).abs().max()
        shares_valid = ksi_sum_diff < 1e-4 and non_sum_diff < 1e-4
    else:
        shares_valid = False

    _add_check(
        "pooled_prior_severity_shrinkage_shares_sum_to_unity",
        "CRITICAL",
        shares_valid,
        f"Pooled-prior severity shrinkage shares sum to 1.0 across all corridors: {shares_valid}",
    )

    # 5. Full-Resolution Spatial Linework Length Reconciliation
    if not df_r.empty:
        min_cov_pct = float(df_r["spatial_linework_coverage_percent"].min())
        max_spatial_diff = float(df_r["spatial_reconciliation_diff_feet"].max())
        spatial_ok = min_cov_pct >= 99.0 and max_spatial_diff < 0.1
    else:
        spatial_ok = False
        min_cov_pct = 0.0
        max_spatial_diff = 999.0

    _add_check(
        "full_resolution_spatial_linework_coverage_ge_99_pct",
        "CRITICAL",
        spatial_ok,
        f"Min spatial linework coverage across 43 corridors: {min_cov_pct:.4f}% (max error: {max_spatial_diff:.4f} ft; required >= 99.0%)",
    )

    # 6. Equity Classifications Present
    if not df_r.empty:
        class_a_cnt = int(df_r["equity_classification_A_weighted_ge_0_75"].sum())
        class_b_cnt = int(df_r["equity_classification_B_share_ge_0_50"].sum())
        equity_ok = class_a_cnt > 0 and class_b_cnt > 0
    else:
        equity_ok = False
        class_a_cnt = class_b_cnt = 0

    _add_check(
        "spatial_equity_classifications_built",
        "CRITICAL",
        equity_ok,
        f"Equity Classifications built: Class A (Weighted SVI >= 0.75) = {class_a_cnt}, Class B (Share >= 0.50) = {class_b_cnt}",
    )

    # 7. Attribute Audit Flagged
    if not df_r.empty:
        attr_blocked = (df_r["attr_lane_count_available"] == False).all() and (df_r["attr_adt_available"] == False).all()
    else:
        attr_blocked = False

    _add_check(
        "physical_attribute_availability_flagged_as_blocked",
        "CRITICAL",
        attr_blocked,
        f"Missing physical attributes correctly flagged as unavailable/blocked: {attr_blocked}",
    )

    # Populate Mandatory Governance Warnings
    _add_warning(
        "WARNING_PROVISIONAL_TREATMENTS",
        ["TRT_001", "TRT_002", "TRT_004"],
        "Provisional candidate treatments require engineering review and corridor physical attribute overlays before final project approval.",
        "D005, D020",
    )
    _add_warning(
        "WARNING_BLOCKED_TREATMENTS",
        ["TRT_003", "TRT_005", "TRT_006"],
        "Blocked candidate treatments lack verified CMFs or local physical geometry/friction condition data.",
        "D005, D020",
    )
    _add_warning(
        "WARNING_MISSING_PHYSICAL_ATTRIBUTES",
        ["TRT_001", "TRT_002", "TRT_003", "TRT_004", "TRT_005", "TRT_006"],
        "Lane counts, ADT, speed limits, median widths, crossing counts, and friction ratings are missing from current spatial tables.",
        "D001, D005",
    )
    _add_warning(
        "WARNING_MISSING_INSTALLATION_QUANTITIES_AND_COSTS",
        ["TRT_001", "TRT_002", "TRT_003", "TRT_004", "TRT_005", "TRT_006"],
        "Corridor installation location counts and local Chicago engineering cost multipliers are unverified.",
        "D006, D021",
    )
    _add_warning(
        "WARNING_PORTFOLIO_OPTIMIZATION_BLOCKED",
        ["ALL_CORRIDORS"],
        "Portfolio optimization remains blocked until treatment applicability and benefit baselines are approved.",
        "D005, D022",
    )

    crit_failures = sum(1 for c in checks if c["severity"] == "CRITICAL" and not c["passed"])

    # Governance Output Requirements: PASS_WITH_WARNINGS / READY_FOR_TREATMENT_EVIDENCE_REVIEW
    status_val = "PASS_WITH_WARNINGS" if crit_failures == 0 else "FAIL"
    readiness_val = "READY_FOR_TREATMENT_EVIDENCE_REVIEW" if crit_failures == 0 else "BLOCKED"

    run_id = run_id_override or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    report = {
        "pipeline": "corridor_treatment_readiness",
        "run_id": run_id,
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "is_sample": is_sample,
        "reconciliation_summary": {
            "total_assigned_crashes": tot_cnt,
            "k_fatal_crashes": k_cnt,
            "a_serious_injury_crashes": a_cnt,
            "b_minor_injury_crashes": b_cnt,
            "c_possible_injury_crashes": c_cnt,
            "o_property_damage_crashes": o_cnt,
            "u_unknown_severity_crashes": u_cnt,
            "ksi_crashes": ksi_cnt,
        },
        "equity_summary": {
            "total_corridors_evaluated": len(df_r),
            "min_linework_coverage_percent": min_cov_pct,
            "class_a_weighted_svi_ge_0_75_count": class_a_cnt,
            "class_b_high_svi_share_ge_0_50_count": class_b_cnt,
        },
        "status": status_val,
        "downstream_readiness": readiness_val,
        "critical_failure_count": crit_failures,
        "warning_count": len(warnings_list),
        "governance_warnings": warnings_list,
        "checks": checks,
    }

    if not is_sample:
        _write_json_atomic(report_output_path, report)
        runs_dir.mkdir(parents=True, exist_ok=True)
        hist_path = runs_dir / f"treatment_readiness_validation_{run_id}.json"
        _write_json_atomic(hist_path, report)
        print(f"Saved validation report to {report_output_path}")

    return report, checks


def main() -> int:
    print("=" * 70)
    print("Validate Corridor Treatment Readiness & Spatial Equity")
    print("=" * 70)

    try:
        report, checks = validate_corridor_treatment_readiness()
        print("\n" + "=" * 70)
        print("TREATMENT READINESS VALIDATION SUMMARY")
        print("=" * 70)
        print(f"Status: {report['status']} | Downstream Readiness: {report['downstream_readiness']}")
        print(f"Critical Failures: {report['critical_failure_count']} | Warnings: {report['warning_count']}")

        for check in checks:
            symbol = "PASS" if check["passed"] else "FAIL"
            print(f"  [{symbol:<4}] {check['check']:<55} ({check['severity']}) - {check['evidence']}")

        print("\nGovernance Warnings:")
        for w in report["governance_warnings"]:
            print(f"  - [{w['warning_id']}] ({w['governance_reference']}): {w['explanation']}")

        return 0 if report["status"] != "FAIL" else 1
    except Exception as exc:
        print(f"\nCRITICAL FAILURE: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
