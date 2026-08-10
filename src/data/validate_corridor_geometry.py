"""Independently validate constructed high-crash corridor geometries.

This CLI script loads data/interim/high_crash_corridors.parquet (EPSG:3435)
and data/interim/high_crash_corridors_review.geojson (EPSG:4326), validates all 43
corridor records against spatial quality contract requirements, writes latest
and historical JSON validation reports, and appends issue entries to the issue register.

It never modifies the interim outputs or raw data.
"""

from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import yaml

ROOT = Path(__file__).resolve().parents[2]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.corridor_geometry import INVALID_OBJECTIDS, load_spatial_config  # noqa: E402

SPATIAL_CONFIG_PATH = ROOT / "config" / "spatial.yml"
REGISTER_PATH = ROOT / "data" / "interim" / "high_crash_corridor_register.csv"
PARQUET_INPUT_PATH = ROOT / "data" / "interim" / "high_crash_corridors.parquet"
GEOJSON_INPUT_PATH = ROOT / "data" / "interim" / "high_crash_corridors_review.geojson"

LATEST_REPORT_PATH = ROOT / "docs" / "data_quality" / "corridor_geometry_validation.json"
HISTORICAL_REPORT_DIR = ROOT / "docs" / "data_quality" / "corridor_geometry_runs"
ISSUE_REGISTER_PATH = ROOT / "docs" / "data_quality" / "data_quality_issue_register.csv"


def write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp.json")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    tmp_path.replace(path)


def append_issue_register(
    register_path: Path,
    issues: list[dict[str, Any]],
    run_id: str,
    detected_at: str,
    report_path_str: str,
) -> None:
    if not issues or not register_path.is_file():
        return

    existing_rows = []
    with register_path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        existing_rows = list(reader)

    new_rows = []
    counter = 1
    for issue in issues:
        issue_id = f"DQ-{run_id}-GEOM-{counter:03d}"
        counter += 1
        row = {
            "issue_id": issue_id,
            "run_id": run_id,
            "detected_at_utc": detected_at,
            "pipeline_stage": "corridor_geometry_validation",
            "dataset": "high_crash_corridors",
            "issue_code": issue["code"],
            "severity": issue["severity"],
            "status": "open",
            "affected_rows": str(issue.get("affected_rows", 1)),
            "description": issue["message"],
            "evidence_file": report_path_str,
            "governance_reference": issue.get("governance_reference", "D016"),
            "resolution": issue.get("resolution", ""),
            "closed_at_utc": "",
        }
        new_rows.append(row)

    all_rows = existing_rows + new_rows
    with register_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_rows)


def validate_corridor_geometries(
    parquet_path: Path = PARQUET_INPUT_PATH,
    geojson_path: Path = GEOJSON_INPUT_PATH,
    latest_report_path: Path = LATEST_REPORT_PATH,
    historical_report_dir: Path = HISTORICAL_REPORT_DIR,
    issue_register_path: Path = ISSUE_REGISTER_PATH,
    spatial_config_path: Path = SPATIAL_CONFIG_PATH,
) -> dict[str, Any]:
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    started = datetime.now(timezone.utc)

    config = load_spatial_config(spatial_config_path)
    geom_cfg = config.get("corridor_geometry", {})

    checks: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []

    # Check input files existence
    if not parquet_path.is_file():
        return {
            "status": "FAIL",
            "downstream_readiness": "NOT_READY",
            "error": f"Parquet file missing: {parquet_path}",
        }
    if not geojson_path.is_file():
        return {
            "status": "FAIL",
            "downstream_readiness": "NOT_READY",
            "error": f"GeoJSON file missing: {geojson_path}",
        }

    gdf_parquet = gpd.read_parquet(parquet_path)
    with geojson_path.open(encoding="utf-8") as f:
        geojson_data = json.load(f)

    # 1. Exact 43-row count check
    p_count = len(gdf_parquet)
    g_count = len(geojson_data.get("features", []))
    passed_count = (p_count == 43) and (g_count == 43)
    checks.append({
        "check": "corridor_count_43",
        "expected": 43,
        "actual_parquet": p_count,
        "actual_geojson": g_count,
        "passed": passed_count,
        "severity": "critical",
    })

    # 2. Exact corridor-ID set reconciliation
    ids = list(gdf_parquet["corridor_id"])
    unique_ids = set(ids)
    expected_ids = {f"HCC{i:03d}" for i in range(1, 44)}
    checks.append({
        "check": "corridor_ids_reconciliation",
        "expected_ids_count": 43,
        "actual_unique_count": len(unique_ids),
        "missing_ids": sorted(list(expected_ids - unique_ids)),
        "extra_ids": sorted(list(unique_ids - expected_ids)),
        "passed": unique_ids == expected_ids,
        "severity": "critical",
    })

    # 3. Missing or duplicate corridor IDs
    checks.append({
        "check": "no_missing_or_duplicate_corridor_ids",
        "total_rows": len(ids),
        "unique_rows": len(unique_ids),
        "has_nulls": any(cid is None or str(cid).strip() == "" for cid in ids),
        "passed": (len(ids) == 43) and (len(unique_ids) == 43),
        "severity": "critical",
    })

    # 4. Geometry presence
    empty_count = sum(1 for g in gdf_parquet["geometry"] if g is None or g.is_empty)
    checks.append({
        "check": "geometry_presence",
        "empty_geometry_count": empty_count,
        "passed": empty_count == 0,
        "severity": "critical",
    })

    # 5. Geometry validity
    invalid_count = sum(1 for g in gdf_parquet["geometry"] if g is not None and not g.is_valid)
    checks.append({
        "check": "geometry_validity",
        "invalid_geometry_count": invalid_count,
        "passed": invalid_count == 0,
        "severity": "critical",
    })

    # 6. CRS verification
    p_crs = str(gdf_parquet.crs)
    g_crs = geojson_data.get("crs", {}).get("properties", {}).get("name", "")
    passed_crs = ("3435" in p_crs)
    checks.append({
        "check": "crs_verification",
        "expected_parquet_crs": "EPSG:3435",
        "actual_parquet_crs": p_crs,
        "passed": passed_crs,
        "severity": "critical",
    })

    # 7. Approved source-name policy
    unapproved_source_name_count = 0
    exception_policies = geom_cfg.get("exception_policies", {})
    for idx, row in gdf_parquet.iterrows():
        cid = row["corridor_id"]
        used_names = set(json.loads(row["source_street_names"]))
        if cid in exception_policies:
            allowed = set(exception_policies[cid].get("allowed_source_names", [])) | set(exception_policies[cid].get("source_names", []))
            if not used_names.issubset(allowed):
                unapproved_source_name_count += 1

    checks.append({
        "check": "approved_source_name_policy",
        "unapproved_count": unapproved_source_name_count,
        "passed": unapproved_source_name_count == 0,
        "severity": "critical",
    })

    # 8. Invalid source-objectid exclusion
    forbidden_used_count = 0
    for idx, row in gdf_parquet.iterrows():
        obj_ids = set(json.loads(row["source_objectids"]))
        if obj_ids & INVALID_OBJECTIDS:
            forbidden_used_count += 1
    checks.append({
        "check": "invalid_source_objectid_exclusion",
        "forbidden_used_count": forbidden_used_count,
        "passed": forbidden_used_count == 0,
        "severity": "critical",
    })

    # 9. Boundary resolution within tolerance
    max_tol = float(geom_cfg.get("boundary_proximity", {}).get("maximum_feet", 200.0))
    exceeds_tol_count = 0
    for idx, row in gdf_parquet.iterrows():
        f_dist = float(row["boundary_from_distance_feet"])
        t_dist = float(row["boundary_to_distance_feet"])
        if f_dist > max_tol or t_dist > max_tol:
            exceeds_tol_count += 1
    checks.append({
        "check": "boundary_resolution_within_tolerance",
        "exceeds_tolerance_count": exceeds_tol_count,
        "max_tolerance_feet": max_tol,
        "passed": exceeds_tol_count == 0,
        "severity": "critical",
    })

    # 10. Source-objectid traceability
    untraceable_count = 0
    for idx, row in gdf_parquet.iterrows():
        obj_ids = json.loads(row["source_objectids"])
        seg_cnt = int(row["source_segment_count"])
        if not obj_ids or seg_cnt <= 0 or len(obj_ids) != seg_cnt:
            untraceable_count += 1
    checks.append({
        "check": "source_objectid_traceability",
        "untraceable_count": untraceable_count,
        "passed": untraceable_count == 0,
        "severity": "critical",
    })

    # 11. Geometry type and multipart policy
    linestring_count = 0
    multilinestring_count = 0
    type_policy_failed = False
    for idx, row in gdf_parquet.iterrows():
        cid = row["corridor_id"]
        g = row["geometry"]
        is_multi = bool(row["is_multipart"])

        if g.geom_type == "LineString":
            linestring_count += 1
            if is_multi or cid == "HCC019":
                type_policy_failed = True
        elif g.geom_type == "MultiLineString":
            multilinestring_count += 1
            if not is_multi or cid != "HCC019":
                type_policy_failed = True
            if len(g.geoms) != 2:
                type_policy_failed = True
        else:
            type_policy_failed = True

    checks.append({
        "check": "geometry_type_and_multipart_policy",
        "linestring_count": linestring_count,
        "multilinestring_count": multilinestring_count,
        "expected_linestring_count": 42,
        "expected_multilinestring_count": 1,
        "passed": (linestring_count == 42) and (multilinestring_count == 1) and (not type_policy_failed),
        "severity": "critical",
    })

    # 12. Length semantics and plausibility
    length_unplausible_count = 0
    for idx, row in gdf_parquet.iterrows():
        c_len = float(row["corridor_length_feet"])
        if c_len < 500.0 or c_len > 60000.0:
            length_unplausible_count += 1
    checks.append({
        "check": "length_semantics_and_plausibility",
        "unplausible_length_count": length_unplausible_count,
        "min_review_feet": 500.0,
        "max_review_feet": 60000.0,
        "passed": length_unplausible_count == 0,
        "severity": "critical",
    })

    # 13. Publication guard
    critical_failures = [c for c in checks if not c["passed"] and c.get("severity") == "critical"]
    checks.append({
        "check": "publication_guard",
        "critical_failure_count": len(critical_failures),
        "passed": len(critical_failures) == 0,
        "severity": "critical",
    })

    # Evaluate Warnings (Exactly 4 expected warnings)
    multipart_rows = [row["corridor_id"] for idx, row in gdf_parquet.iterrows() if row["is_multipart"]]
    if multipart_rows:
        issues.append({
            "code": "multipart_corridor_geometry",
            "severity": "WARNING",
            "affected_rows": len(multipart_rows),
            "message": f"Approved multipart geometry detected for corridor(s): {multipart_rows}.",
            "governance_reference": "D016",
            "resolution": "Preserved two-carriageway MultiLineString geometry as approved Policy B.",
        })

    proximity_rows = [
        row["corridor_id"]
        for idx, row in gdf_parquet.iterrows()
        if float(row["boundary_from_distance_feet"]) > 0.0 or float(row["boundary_to_distance_feet"]) > 0.0
    ]
    if proximity_rows:
        issues.append({
            "code": "boundary_resolved_by_proximity",
            "severity": "WARNING",
            "affected_rows": len(proximity_rows),
            "message": f"Approved boundary proximity tolerance applied for corridor(s): {proximity_rows}.",
            "governance_reference": "D016",
            "resolution": "Resolved Division boundary for HCC019 within 200-foot approved proximity limit.",
        })

    continuation_rows = [
        row["corridor_id"]
        for idx, row in gdf_parquet.iterrows()
        if row["resolution_method"] == "verified_source_continuation"
    ]
    if continuation_rows:
        issues.append({
            "code": "approved_source_continuation",
            "severity": "WARNING",
            "affected_rows": len(continuation_rows),
            "message": f"Approved source-name continuation applied for corridor(s): {continuation_rows}.",
            "governance_reference": "D016",
            "resolution": "Routed across Fairbanks and Columbus source centerlines as approved Policy C.",
        })

    multilevel_rows = [
        row["corridor_id"]
        for idx, row in gdf_parquet.iterrows()
        if row["resolution_method"] == "verified_multilevel_source_family"
    ]
    if multilevel_rows:
        issues.append({
            "code": "approved_multilevel_source_family",
            "severity": "WARNING",
            "affected_rows": len(multilevel_rows),
            "message": f"Approved multilevel source family applied for corridor(s): {multilevel_rows}.",
            "governance_reference": "D016",
            "resolution": "Routed across Wacker upper/lower/ramp/sub source family as approved Policy D.",
        })

    if critical_failures:
        status = "FAIL"
        readiness = "NOT_READY"
    elif issues:
        status = "PASS_WITH_WARNINGS"
        readiness = "READY_WITH_LIMITATIONS"
    else:
        status = "PASS"
        readiness = "READY_FOR_CRASH_ASSIGNMENT"

    completed = datetime.now(timezone.utc)

    report = {
        "pipeline": "corridor_geometry_validation",
        "run_id": run_id,
        "started_at_utc": started.isoformat(timespec="seconds"),
        "completed_at_utc": completed.isoformat(timespec="seconds"),
        "status": status,
        "downstream_readiness": readiness,
        "summary": {
            "total_corridors": len(gdf_parquet),
            "total_checks": len(checks),
            "critical_failures": len(critical_failures),
            "warning_count": len(issues),
        },
        "checks": checks,
        "warnings": issues,
        "governance": {
            "analysis_crs": "EPSG:3435",
            "review_crs": "EPSG:4326",
            "max_proximity_tolerance_feet": max_tol,
            "boundary_tolerance_is_crash_assignment_threshold": False,
            "approved_policy_d016": True,
            "raw_files_modified": False,
            "crashes_assigned": False,
        },
    }

    # Write reports
    historical_report_dir.mkdir(parents=True, exist_ok=True)
    hist_report_path = historical_report_dir / f"corridor_geometry_validation_{run_id}.json"
    write_json_atomic(hist_report_path, report)
    write_json_atomic(latest_report_path, report)

    # Append issues to issue register
    try:
        try:
            rel_path_str = str(hist_report_path.relative_to(ROOT))
        except ValueError:
            rel_path_str = str(hist_report_path)

        append_issue_register(
            register_path=issue_register_path,
            issues=issues,
            run_id=run_id,
            detected_at=started.isoformat(),
            report_path_str=rel_path_str,
        )
    except Exception as exc:
        print(f"WARNING: Could not update issue register: {exc}")

    return report


def main() -> int:
    print("=" * 70)
    print("Validating High-Crash Corridor Geometries")
    print("=" * 70)

    report = validate_corridor_geometries()

    print(f"Status: {report['status']}")
    print(f"Downstream Readiness: {report['downstream_readiness']}")
    print(f"Warnings: {len(report.get('warnings', []))}")
    print(f"Latest Report: {LATEST_REPORT_PATH}")
    print("=" * 70)

    return 1 if report["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
