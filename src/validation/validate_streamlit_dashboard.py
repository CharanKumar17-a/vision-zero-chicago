"""Validate Streamlit Decision-Support Dashboard Application (Phase 5B).

Contract: docs/data_quality/decision_output_mart_contract.md
Decision: D001, D004, D005, D019

Executes independent validation suite on Streamlit application components, data access layer,
spatial mapping integration, and evidence lineage.
"""

from __future__ import annotations

import datetime
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dashboard.streamlit.data_access import (
    DEFAULT_PORTFOLIO_ID,
    get_selected_corridors_geodataframe,
    get_single_portfolio_selections,
    get_single_portfolio_summary,
    load_corridor_geodataframe,
    load_portfolio_summary,
    load_project_selections,
    load_validation_evidence,
)

VALIDATION_JSON_PATH = ROOT / "docs" / "data_quality" / "streamlit_dashboard_validation.json"
RUNS_DIR_PATH = ROOT / "docs" / "data_quality" / "streamlit_dashboard_runs"


def sanitize_for_json(obj: Any) -> Any:
    """Recursively convert numpy types to native python primitives."""
    if isinstance(obj, dict):
        return {k: sanitize_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize_for_json(v) for v in obj]
    elif isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    elif isinstance(obj, (np.integer, int)):
        return int(obj)
    elif isinstance(obj, (np.floating, float)):
        return float(obj)
    return obj


def validate_streamlit_dashboard(
    validation_json_path: Path = VALIDATION_JSON_PATH,
    runs_dir_path: Path = RUNS_DIR_PATH,
) -> Dict[str, Any]:
    """Execute complete validation suite on Streamlit application components."""
    t0 = time.time()
    run_timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    print("=" * 80)
    print("VALIDATING STREAMLIT DECISION SUPPORT DASHBOARD (PHASE 5B)")
    print("=" * 80)

    checks: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []

    # 1. Dashboard Application Files Exist
    app_files = [
        ROOT / "dashboard" / "streamlit" / "app.py",
        ROOT / "dashboard" / "streamlit" / "data_access.py",
        ROOT / "dashboard" / "streamlit" / "components.py",
        ROOT / "dashboard" / "streamlit" / "pages" / "1_Portfolio_Overview.py",
        ROOT / "dashboard" / "streamlit" / "pages" / "2_Corridor_Explorer.py",
        ROOT / "dashboard" / "streamlit" / "pages" / "3_Governance_and_Methodology.py",
    ]
    all_files_exist = all(f.exists() for f in app_files)
    checks.append({
        "check": "streamlit_app_files_exist",
        "severity": "CRITICAL",
        "passed": bool(all_files_exist),
        "evidence": f"All 6 Streamlit application files exist: {all_files_exist}",
    })

    # 2. Default Portfolio Uniqueness
    df_summary = load_portfolio_summary()
    default_row = get_single_portfolio_summary(df_summary, DEFAULT_PORTFOLIO_ID)
    def_unique = (default_row["portfolio_id"] == DEFAULT_PORTFOLIO_ID and bool(default_row["is_default_dashboard_portfolio"]))
    checks.append({
        "check": "default_portfolio_unique",
        "severity": "CRITICAL",
        "passed": bool(def_unique),
        "evidence": f"Default portfolio '{DEFAULT_PORTFOLIO_ID}' is uniquely marked: {def_unique}",
    })

    # 3. Single Portfolio Filtering Isolation & Cost Reconciliation
    df_selections = load_project_selections()
    df_sel = get_single_portfolio_selections(df_selections, DEFAULT_PORTFOLIO_ID)
    c_diff = abs(df_sel["capital_project_cost"].sum() - default_row["selected_capital_cost"])
    cost_reconciled = (c_diff < 1e-4 and len(df_sel) == default_row["selected_project_count"])
    checks.append({
        "check": "single_portfolio_filtering_and_reconciliation",
        "severity": "CRITICAL",
        "passed": bool(cost_reconciled),
        "evidence": f"Single portfolio selection filtering exact: {cost_reconciled} (Cost diff: ${c_diff:.4f})",
    })

    # 4. Spatial GeoDataFrame Transformation (EPSG:4326)
    gdf_corridors = load_corridor_geodataframe()
    gdf_sel = get_selected_corridors_geodataframe(df_selections, gdf_corridors, DEFAULT_PORTFOLIO_ID)
    spatial_valid = (
        gdf_sel.crs.to_string() == "EPSG:4326" and
        len(gdf_sel) == int(default_row["selected_project_count"]) and
        gdf_sel["centroid_latitude"].notna().all() and
        gdf_sel["centroid_longitude"].notna().all()
    )
    checks.append({
        "check": "spatial_geodataframe_epsg4326_transformation",
        "severity": "CRITICAL",
        "passed": bool(spatial_valid),
        "evidence": f"Spatial linework and centroids transformed to EPSG:4326 without row loss: {spatial_valid}",
    })

    # 5. Dynamic Validation Evidence Loading
    evidence = load_validation_evidence()
    opt_w_count = len(evidence.get("optimization", {}).get("governance_warnings", []))
    mart_w_count = len(evidence.get("decision_mart", {}).get("governance_warnings", []))
    evidence_valid = (opt_w_count == 7 and mart_w_count == 2)
    checks.append({
        "check": "dynamic_validation_evidence_loading",
        "severity": "CRITICAL",
        "passed": bool(evidence_valid),
        "evidence": f"Validation evidence JSONs loaded dynamically (Optimization warnings: {opt_w_count}, Mart warnings: {mart_w_count})",
    })

    # 6. Public Deployment Dataset & Manifest Verification
    deploy_manifest_path = ROOT / "dashboard" / "streamlit" / "deployment_data" / "deployment_manifest.json"
    deploy_valid = False
    if deploy_manifest_path.exists():
        with open(deploy_manifest_path, "r", encoding="utf-8") as f:
            m_data = json.load(f)
        files_dict = m_data.get("files", {})
        counts_ok = (
            files_dict.get("portfolio_summary.csv", {}).get("row_count") == 192
            and files_dict.get("project_selections.csv", {}).get("row_count") > 0
            and files_dict.get("corridor_master.csv", {}).get("row_count") == 43
            and files_dict.get("treatment_benefits.csv", {}).get("row_count") == 387
        )
        deploy_valid = bool(counts_ok and not m_data.get("prohibited_data_included"))
    checks.append({
        "check": "public_deployment_dataset_and_manifest_integrity",
        "severity": "CRITICAL",
        "passed": bool(deploy_valid),
        "evidence": f"Deployment snapshot CSV files and manifest verified without prohibited data: {deploy_valid}",
    })

    # Governance Warnings
    warnings.append({
        "code": "WARNING_PROVISIONAL_DECISION_SUPPORT_APP",
        "warning_id": "WARNING_PROVISIONAL_DECISION_SUPPORT_APP",
        "affected_pages": 3,
        "explanation": "Streamlit application serves analyst-defined decision-support scenarios only.",
        "limitation_or_resolution": "Requires CDOT/IDOT staff engineering review before project programming.",
        "governance_reference": "D004, D005",
    })

    warnings.append({
        "code": "WARNING_PHYSICAL_APPLICABILITY_UNKNOWN",
        "warning_id": "WARNING_PHYSICAL_APPLICABILITY_UNKNOWN",
        "affected_corridors": 43,
        "explanation": "Physical applicability status is UNKNOWN across all displayed project candidates.",
        "limitation_or_resolution": "Field survey required prior to project programming.",
        "governance_reference": "A004, D005",
    })

    critical_failures = sum(1 for c in checks if c["severity"] == "CRITICAL" and not c["passed"])
    status = "PASS_WITH_WARNINGS" if critical_failures == 0 else "FAIL"

    validation_report = {
        "pipeline": "streamlit_decision_support_app",
        "run_id": run_timestamp,
        "completed_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "is_sample": False,
        "app_summary": {
            "pages_count": 3,
            "default_portfolio_id": DEFAULT_PORTFOLIO_ID,
            "selected_project_count": len(df_sel),
            "selected_capital_cost_usd": float(default_row["selected_capital_cost"]),
            "achieved_equity_share": float(default_row["achieved_equity_share"]),
            "spatial_crs": "EPSG:4326",
        },
        "status": status,
        "downstream_readiness": "READY_FOR_LOCAL_SERVED_DEMO",
        "critical_failure_count": critical_failures,
        "warning_count": len(warnings),
        "governance_warnings": warnings,
        "checks": checks,
    }

    clean_report = sanitize_for_json(validation_report)

    validation_json_path.parent.mkdir(parents=True, exist_ok=True)
    with open(validation_json_path, "w", encoding="utf-8") as f:
        json.dump(clean_report, f, indent=2)

    runs_dir_path.mkdir(parents=True, exist_ok=True)
    run_file_path = runs_dir_path / f"streamlit_dashboard_validation_{run_timestamp}.json"
    with open(run_file_path, "w", encoding="utf-8") as f:
        json.dump(clean_report, f, indent=2)

    elapsed = time.time() - t0
    print(f"\nValidation completed in {elapsed:.2f}s.")
    print(f"Status: {status} (Critical Failures: {critical_failures}, Warnings: {len(warnings)})")
    print(f"Main validation JSON: {validation_json_path}")
    print(f"Historical run JSON:  {run_file_path}")
    print("=" * 80)

    if critical_failures > 0:
        raise ValueError(f"Streamlit dashboard validation failed with {critical_failures} critical failures!")

    return validation_report


if __name__ == "__main__":
    validate_streamlit_dashboard()
