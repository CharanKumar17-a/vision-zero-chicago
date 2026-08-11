"""Build primary crash-to-corridor assignments for Vision Zero Chicago.

Contract: docs/data_quality/spatial_assignment_contract.md
Config:   config/spatial.yml (crash_assignment section)
Decision: D017 (Approve 100-foot crash assignment threshold)

Assigns cleaned crashes to at most one primary high-crash corridor using the approved
100-foot distance threshold and 10-foot tie tolerance.

Required audit output:
data/interim/crash_corridor_assignments.parquet (877,919 rows, exactly one row per crash_record_id).
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

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.assign_crashes_to_corridors import (  # noqa: E402
    ANALYSIS_CRS,
    SOURCE_CRS,
    generate_candidates_spatial_index,
    load_corridor_geometries,
    load_eligible_crashes,
    load_spatial_config,
)

SPATIAL_CONFIG_PATH = ROOT / "config" / "spatial.yml"
CRASHES_PATH = ROOT / "data" / "interim" / "crashes_clean.parquet"
CORRIDORS_PATH = ROOT / "data" / "interim" / "high_crash_corridors.parquet"
REGISTER_PATH = ROOT / "data" / "interim" / "high_crash_corridor_register.csv"
ASSIGNMENT_OUTPUT_PATH = ROOT / "data" / "interim" / "crash_corridor_assignments.parquet"
VALIDATION_REPORT_PATH = ROOT / "docs" / "data_quality" / "crash_corridor_assignment_validation.json"
RUNS_DIR = ROOT / "docs" / "data_quality" / "crash_corridor_assignment_runs"


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


def validate_primary_assignments(
    assignments_df: pd.DataFrame,
    total_crash_count: int,
    eligible_crash_count: int,
    invalid_coordinate_count: int,
    authoritative_register_ids: set[str],
    corridor_count: int,
    selected_threshold_feet: float,
    threshold_status: str,
    is_sample: bool = False,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Validate primary crash assignment dataframe and return report dict & checks list."""
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

    n_rows = len(assignments_df)

    # 1. Row count match
    if not is_sample:
        _add_check(
            "total_crash_row_count_is_877919",
            "CRITICAL",
            n_rows == total_crash_count and n_rows == 877919,
            f"Assignment row count: {n_rows:,} (expected {total_crash_count:,})",
        )
    else:
        _add_check(
            "total_crash_row_count_is_877919",
            "WARNING",
            True,
            f"Sample mode active: evaluating sample of {n_rows:,} rows.",
        )

    # 2. Crash record ID unique and non-null
    null_crash_ids = int(assignments_df["crash_record_id"].isna().sum())
    dup_crash_ids = int(assignments_df["crash_record_id"].duplicated().sum())
    _add_check(
        "crash_record_id_unique_and_non_null",
        "CRITICAL",
        null_crash_ids == 0 and dup_crash_ids == 0,
        f"Null crash IDs: {null_crash_ids}, Duplicate crash IDs: {dup_crash_ids}",
    )

    # 3. Valid assignment statuses only
    valid_statuses = {
        "primary_assigned",
        "unresolved_tie",
        "outside_selected_threshold",
        "no_valid_coordinates",
    }
    actual_statuses = set(assignments_df["assignment_status"].unique())
    invalid_statuses = actual_statuses - valid_statuses
    _add_check(
        "valid_assignment_statuses_only",
        "CRITICAL",
        len(invalid_statuses) == 0,
        f"Invalid assignment statuses found: {sorted(list(invalid_statuses)) if invalid_statuses else 'none'}",
    )

    # Status counts
    status_counts = assignments_df["assignment_status"].value_counts().to_dict()
    n_primary = int(status_counts.get("primary_assigned", 0))
    n_tie = int(status_counts.get("unresolved_tie", 0))
    n_outside = int(status_counts.get("outside_selected_threshold", 0))
    n_no_coords = int(status_counts.get("no_valid_coordinates", 0))

    # 4-7. Expected status counts (full mode)
    if not is_sample:
        _add_check(
            "primary_assigned_count_matches_expected",
            "CRITICAL",
            n_primary == 112421,
            f"primary_assigned count: {n_primary:,} (expected 112,421)",
        )
        _add_check(
            "unresolved_tie_count_matches_expected",
            "CRITICAL",
            n_tie == 1803,
            f"unresolved_tie count: {n_tie:,} (expected 1,803)",
        )
        _add_check(
            "outside_threshold_count_matches_expected",
            "CRITICAL",
            n_outside == 756545,
            f"outside_selected_threshold count: {n_outside:,} (expected 756,545)",
        )
        _add_check(
            "no_valid_coordinates_count_matches_expected",
            "CRITICAL",
            n_no_coords == 7150,
            f"no_valid_coordinates count: {n_no_coords:,} (expected 7,150)",
        )
    else:
        for st, c in [("primary_assigned", n_primary), ("unresolved_tie", n_tie), ("outside_selected_threshold", n_outside), ("no_valid_coordinates", n_no_coords)]:
            _add_check(
                f"{st}_count_matches_expected",
                "WARNING",
                True,
                f"Sample mode active: {st} count is {c:,}.",
            )

    # 8. Four-category reconciliation zero diff
    recon_sum = n_primary + n_tie + n_outside + n_no_coords
    _add_check(
        "four_category_reconciliation_zero_diff",
        "CRITICAL",
        recon_sum == n_rows,
        f"Reconciliation sum {recon_sum:,} == total rows {n_rows:,} (diff: {n_rows - recon_sum})",
    )

    # 9. Corridor ID null for non-primary statuses
    non_primary_df = assignments_df[assignments_df["assignment_status"] != "primary_assigned"]
    non_primary_corridor_ids = int(non_primary_df["corridor_id"].notna().sum())
    _add_check(
        "corridor_id_null_for_non_primary_statuses",
        "CRITICAL",
        non_primary_corridor_ids == 0,
        f"Non-primary rows with non-null corridor_id: {non_primary_corridor_ids}",
    )

    # 10. Corridor ID non-null for primary_assigned
    primary_df = assignments_df[assignments_df["assignment_status"] == "primary_assigned"]
    primary_null_corridor_ids = int(primary_df["corridor_id"].isna().sum())
    _add_check(
        "corridor_id_non_null_for_primary_assigned",
        "CRITICAL",
        primary_null_corridor_ids == 0,
        f"Primary assigned rows with null corridor_id: {primary_null_corridor_ids}",
    )

    # 11. Assigned corridor IDs are valid register subset
    assigned_corridors = set(primary_df["corridor_id"].unique()) if not primary_df.empty else set()
    unknown_corridors = assigned_corridors - authoritative_register_ids
    _add_check(
        "assigned_corridors_valid_register_subset",
        "CRITICAL",
        len(unknown_corridors) == 0,
        f"Unknown assigned corridor IDs: {sorted(list(unknown_corridors)) if unknown_corridors else 'none'}",
    )

    # 12. No duplicate primary assignments
    primary_dup_crashes = int(primary_df["crash_record_id"].duplicated().sum())
    _add_check(
        "no_duplicate_primary_assignments",
        "CRITICAL",
        primary_dup_crashes == 0,
        f"Duplicate primary crash assignments: {primary_dup_crashes}",
    )

    # 13. Assigned distances within selected threshold
    if not primary_df.empty:
        min_dist = float(primary_df["distance_feet"].min())
        max_dist = float(primary_df["distance_feet"].max())
        dist_valid = (min_dist >= 0.0) and (max_dist <= selected_threshold_feet)
    else:
        min_dist, max_dist = 0.0, 0.0
        dist_valid = True

    _add_check(
        "assigned_distances_within_selected_threshold",
        "CRITICAL",
        dist_valid,
        f"Assigned distance range: [{min_dist:.3f}, {max_dist:.3f}] ft (max allowed: {selected_threshold_feet} ft)",
    )

    # 14. Selected threshold is 100 ft
    _add_check(
        "selected_threshold_is_100",
        "CRITICAL",
        selected_threshold_feet == 100.0,
        f"selected_distance_threshold_feet: {selected_threshold_feet} (expected 100)",
    )

    # 15. Threshold status is approved_for_modeling
    _add_check(
        "threshold_status_is_approved",
        "CRITICAL",
        threshold_status == "approved_for_modeling",
        f"threshold_status: '{threshold_status}' (expected 'approved_for_modeling')",
    )

    # 16. Corridor coverage (all 43 corridors assigned at least 1 crash)
    assigned_count = len(assigned_corridors)
    _add_check(
        "corridor_coverage_all_43_corridors",
        "WARNING",
        assigned_count == corridor_count,
        f"Corridors with primary assignments: {assigned_count} of {corridor_count}",
    )

    crit_failures = sum(1 for c in checks if c["severity"] == "CRITICAL" and not c["passed"])
    warnings = sum(1 for c in checks if c["severity"] == "WARNING" and not c["passed"])

    if crit_failures > 0:
        status_val = "FAIL"
        readiness_val = "BLOCKED"
    elif warnings > 0:
        status_val = "PASS_WITH_WARNINGS"
        readiness_val = "READY_FOR_MODELING_PANEL"
    else:
        status_val = "PASS"
        readiness_val = "READY_FOR_MODELING_PANEL"

    report = {
        "pipeline": "primary_crash_corridor_assignment",
        "run_id": assignments_df["run_id"].iloc[0] if not assignments_df.empty else datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_crs": SOURCE_CRS,
        "analysis_crs": ANALYSIS_CRS,
        "selected_distance_threshold_feet": selected_threshold_feet,
        "threshold_status": threshold_status,
        "is_sample": is_sample,
        "total_crashes": total_crash_count,
        "eligible_crashes": eligible_crash_count,
        "invalid_coordinate_crashes": invalid_coordinate_count,
        "assignment_counts": {
            "primary_assigned": n_primary,
            "unresolved_tie": n_tie,
            "outside_selected_threshold": n_outside,
            "no_valid_coordinates": n_no_coords,
        },
        "reconciliation": {
            "total_crashes": n_rows,
            "primary_assigned": n_primary,
            "unresolved_tie": n_tie,
            "outside_selected_threshold": n_outside,
            "no_valid_coordinates": n_no_coords,
            "reconciliation_diff": n_rows - recon_sum,
        },
        "status": status_val,
        "downstream_readiness": readiness_val,
        "critical_failure_count": crit_failures,
        "warning_count": warnings,
        "checks": checks,
    }

    return report, checks


def build_primary_crash_assignments(
    spatial_config: Optional[dict] = None,
    crashes_path: Path = CRASHES_PATH,
    corridors_path: Path = CORRIDORS_PATH,
    register_path: Path = REGISTER_PATH,
    output_path: Path = ASSIGNMENT_OUTPUT_PATH,
    validation_report_path: Path = VALIDATION_REPORT_PATH,
    runs_dir: Path = RUNS_DIR,
    sample_size: Optional[int] = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Build primary crash-to-corridor assignment parquet and validation report."""
    if spatial_config is None:
        spatial_config = load_spatial_config(SPATIAL_CONFIG_PATH)

    selected_threshold_feet = float(spatial_config["crash_assignment"]["selected_distance_threshold_feet"])
    threshold_status = str(spatial_config["crash_assignment"]["threshold_status"])
    tie_tolerance_feet = float(spatial_config["crash_assignment"]["ambiguity"]["tie_tolerance_feet"])
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    print(f"Run ID: {run_id}")
    print(f"Selected Distance Threshold: {selected_threshold_feet} ft")
    print(f"Threshold Status: {threshold_status}")
    print(f"Tie Tolerance: {tie_tolerance_feet} ft")

    t0_load = time.time()
    all_crashes, eligible_gdf, is_sample = load_eligible_crashes(
        crashes_path, sample_size=sample_size
    )
    corridors_gdf = load_corridor_geometries(corridors_path)
    register_df = pd.read_csv(register_path)
    t_load = time.time() - t0_load

    total_count = len(all_crashes)
    eligible_count = len(eligible_gdf)
    invalid_count = int((all_crashes["has_valid_coordinates"] == False).sum())
    corridor_count = len(corridors_gdf)
    authoritative_register_ids = set(register_df["corridor_id"].unique())

    print(f"Loaded {total_count:,} total crashes ({eligible_count:,} eligible, {invalid_count:,} invalid coordinates).")
    print(f"Loaded {corridor_count} corridor geometries.")

    # Candidate generation within selected threshold
    t0_cand = time.time()
    candidates_full = generate_candidates_spatial_index(
        eligible_gdf,
        corridors_gdf,
        max_threshold_feet=selected_threshold_feet,
        tie_tolerance_feet=tie_tolerance_feet,
    )
    t_cand = time.time() - t0_cand
    print(f"Generated {len(candidates_full):,} candidate pairs within {selected_threshold_feet}ft in {t_cand:.3f}s.")

    # Process candidate matches to determine primary assignments & ties
    t0_assign = time.time()

    rank1 = candidates_full[candidates_full["candidate_rank"] == 1].copy()
    rank2 = candidates_full[candidates_full["candidate_rank"] == 2].copy()

    rank1_dict = rank1.set_index("crash_record_id")[["corridor_id", "distance_feet", "candidate_count", "is_tie"]].to_dict("index")
    rank2_dict = rank2.set_index("crash_record_id")["distance_feet"].to_dict()

    eligible_crashes_all = all_crashes[all_crashes["has_valid_coordinates"]].copy()
    if is_sample:
        eligible_crashes_all = eligible_crashes_all.iloc[:sample_size].copy()

    assigned_rows = []
    for cid in eligible_crashes_all["crash_record_id"]:
        if cid in rank1_dict:
            r1 = rank1_dict[cid]
            d1 = float(r1["distance_feet"])
            cand_cnt = int(r1["candidate_count"])
            is_tie = bool(r1["is_tie"])

            if cand_cnt >= 2 and cid in rank2_dict:
                d2 = float(rank2_dict[cid])
                gap = round(d2 - d1, 4)
            else:
                d2 = None
                gap = None

            if is_tie:
                status = "unresolved_tie"
                corr_id = None
            else:
                status = "primary_assigned"
                corr_id = str(r1["corridor_id"])

            assigned_rows.append(
                {
                    "crash_record_id": cid,
                    "assignment_status": status,
                    "corridor_id": corr_id,
                    "distance_feet": round(d1, 4),
                    "candidate_count": cand_cnt,
                    "second_nearest_distance_feet": round(d2, 4) if d2 is not None else None,
                    "distance_gap_feet": gap,
                    "threshold_feet": int(selected_threshold_feet),
                    "tie_tolerance_feet": float(tie_tolerance_feet),
                    "run_id": run_id,
                }
            )
        else:
            assigned_rows.append(
                {
                    "crash_record_id": cid,
                    "assignment_status": "outside_selected_threshold",
                    "corridor_id": None,
                    "distance_feet": None,
                    "candidate_count": 0,
                    "second_nearest_distance_feet": None,
                    "distance_gap_feet": None,
                    "threshold_feet": int(selected_threshold_feet),
                    "tie_tolerance_feet": float(tie_tolerance_feet),
                    "run_id": run_id,
                }
            )

    invalid_crashes_df = all_crashes[all_crashes["has_valid_coordinates"] == False]
    for cid in invalid_crashes_df["crash_record_id"]:
        assigned_rows.append(
            {
                "crash_record_id": cid,
                "assignment_status": "no_valid_coordinates",
                "corridor_id": None,
                "distance_feet": None,
                "candidate_count": 0,
                "second_nearest_distance_feet": None,
                "distance_gap_feet": None,
                "threshold_feet": int(selected_threshold_feet),
                "tie_tolerance_feet": float(tie_tolerance_feet),
                "run_id": run_id,
            }
        )

    assignments_df = pd.DataFrame(assigned_rows)
    assignments_df = assignments_df.sort_values("crash_record_id").reset_index(drop=True)
    t_assign = time.time() - t0_assign
    print(f"Primary assignment construction completed in {t_assign:.3f}s. Total rows: {len(assignments_df):,}.")

    report, checks = validate_primary_assignments(
        assignments_df,
        total_crash_count=total_count,
        eligible_crash_count=eligible_count,
        invalid_coordinate_count=invalid_count,
        authoritative_register_ids=authoritative_register_ids,
        corridor_count=corridor_count,
        selected_threshold_feet=selected_threshold_feet,
        threshold_status=threshold_status,
        is_sample=is_sample,
    )

    if not is_sample:
        _write_parquet_atomic(output_path, assignments_df)
        _write_json_atomic(validation_report_path, report)
        runs_dir.mkdir(parents=True, exist_ok=True)
        hist_report_path = runs_dir / f"crash_corridor_assignment_validation_{run_id}.json"
        _write_json_atomic(hist_report_path, report)
        print(f"Saved primary assignments to {output_path}")
        print(f"Saved validation report to {validation_report_path}")
    else:
        print("[SAMPLE MODE] Skipped overwriting parquet and validation report artifacts.")

    return assignments_df, report


def main() -> int:
    print("=" * 70)
    print("Build Primary Crash-to-Corridor Assignments (Day 10 Phase 1C)")
    print("=" * 70)

    try:
        df, report = build_primary_crash_assignments()
        print("\n" + "=" * 70)
        print("ASSIGNMENT RECONCILIATION SUMMARY")
        print("=" * 70)
        counts = report["assignment_counts"]
        print(f"  - primary_assigned           : {counts['primary_assigned']:>10,}")
        print(f"  - unresolved_tie             : {counts['unresolved_tie']:>10,}")
        print(f"  - outside_selected_threshold : {counts['outside_selected_threshold']:>10,}")
        print(f"  - no_valid_coordinates       : {counts['no_valid_coordinates']:>10,}")
        print(f"  ----------------------------------------")
        print(f"  Total Crashes               : {report['total_crashes']:>10,}")
        print(f"\nStatus: {report['status']} | Downstream Readiness: {report['downstream_readiness']}")
        print(f"Critical Failures: {report['critical_failure_count']} | Warnings: {report['warning_count']}")

        return 0 if report["status"] != "FAIL" else 1
    except Exception as exc:
        print(f"\nCRITICAL FAILURE: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
