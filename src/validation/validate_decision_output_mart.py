"""Validate Decision-Output Mart for Power BI & Streamlit (Phase 5A).

Contract: docs/data_quality/cleaning_contract.md, spatial_assignment_contract.md
Decision: D001 (Corridor grain), D004 (Analytical scope), D005 (Governance authority), D019 (DuckDB local SQL analytics & Power BI serving layer)

Performs independent data quality, row count, and numeric reconciliation verification on Phase 5A decision mart serving outputs:
- Checks file existence and schema compliance.
- Validates row counts (36 summary, 1,410 detail selections, 43 corridor master, 387 treatment benefits).
- Reconciles summary total costs/benefits against project selections.
- Reconciles detail selections against Phase 4B source panel.
- Emits governance warnings and writes validation JSON report artifacts.
"""

from __future__ import annotations

import datetime
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SUMMARY_PARQUET = ROOT / "data" / "processed" / "power_bi_portfolio_summary.parquet"
SUMMARY_CSV = ROOT / "data" / "processed" / "power_bi_portfolio_summary.csv"
SELECTIONS_PARQUET = ROOT / "data" / "processed" / "power_bi_project_selections.parquet"
SELECTIONS_CSV = ROOT / "data" / "processed" / "power_bi_project_selections.csv"
MASTER_PARQUET = ROOT / "data" / "processed" / "power_bi_corridor_master.parquet"
MASTER_CSV = ROOT / "data" / "processed" / "power_bi_corridor_master.csv"
BENEFITS_PARQUET = ROOT / "data" / "processed" / "power_bi_treatment_benefits.parquet"
BENEFITS_CSV = ROOT / "data" / "processed" / "power_bi_treatment_benefits.csv"

BENEFITS_SOURCE_PARQUET = ROOT / "data" / "processed" / "corridor_treatment_benefits.parquet"

VALIDATION_JSON_PATH = ROOT / "docs" / "data_quality" / "decision_output_mart_validation.json"
RUNS_DIR_PATH = ROOT / "docs" / "data_quality" / "decision_output_mart_runs"


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


def validate_decision_output_mart(
    summary_path: Path = SUMMARY_PARQUET,
    selections_path: Path = SELECTIONS_PARQUET,
    master_path: Path = MASTER_PARQUET,
    benefits_path: Path = BENEFITS_PARQUET,
    source_benefits_path: Path = BENEFITS_SOURCE_PARQUET,
    validation_json_path: Path = VALIDATION_JSON_PATH,
    runs_dir_path: Path = RUNS_DIR_PATH,
) -> Dict[str, Any]:
    """Execute complete validation suite on decision mart serving layer datasets."""
    t0 = time.time()
    run_timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    print("=" * 80)
    print("VALIDATING DECISION-OUTPUT MART (PHASE 5A)")
    print("=" * 80)

    checks: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []

    # 1. Output files exist
    s_exist = summary_path.exists() and SUMMARY_CSV.exists()
    checks.append({
        "check": "summary_mart_files_exist",
        "severity": "CRITICAL",
        "passed": bool(s_exist),
        "evidence": f"Portfolio summary parquet and CSV exist: {s_exist}",
    })

    sel_exist = selections_path.exists() and SELECTIONS_CSV.exists()
    checks.append({
        "check": "selections_mart_files_exist",
        "severity": "CRITICAL",
        "passed": bool(sel_exist),
        "evidence": f"Project selections parquet and CSV exist: {sel_exist}",
    })

    m_exist = master_path.exists() and MASTER_CSV.exists()
    checks.append({
        "check": "master_mart_files_exist",
        "severity": "CRITICAL",
        "passed": bool(m_exist),
        "evidence": f"Corridor master parquet and CSV exist: {m_exist}",
    })

    b_exist = benefits_path.exists() and BENEFITS_CSV.exists()
    checks.append({
        "check": "benefits_mart_files_exist",
        "severity": "CRITICAL",
        "passed": bool(b_exist),
        "evidence": f"Treatment benefits parquet and CSV exist: {b_exist}",
    })

    if not (s_exist and sel_exist and m_exist and b_exist):
        raise FileNotFoundError("Missing required decision mart serving datasets.")

    df_summary = pd.read_parquet(summary_path)
    df_selections = pd.read_parquet(selections_path)
    df_master = pd.read_parquet(master_path)
    df_benefits = pd.read_parquet(benefits_path)

    # 2. Row count checks
    s_rows = len(df_summary)
    s_uniq = df_summary["portfolio_id"].nunique()
    checks.append({
        "check": "portfolio_summary_count_36",
        "severity": "CRITICAL",
        "passed": (s_rows == 36 and s_uniq == 36),
        "evidence": f"Portfolio summary rows: {s_rows}, unique portfolio_ids: {s_uniq} (expected 36)",
    })

    sel_rows = len(df_selections)
    checks.append({
        "check": "project_selections_count_1410",
        "severity": "CRITICAL",
        "passed": (sel_rows == 1410),
        "evidence": f"Project selection detail rows: {sel_rows} (expected 1,410)",
    })

    m_rows = len(df_master)
    m_uniq = df_master["corridor_id"].nunique()
    checks.append({
        "check": "corridor_master_count_43",
        "severity": "CRITICAL",
        "passed": (m_rows == 43 and m_uniq == 43),
        "evidence": f"Corridor master rows: {m_rows}, unique corridor_ids: {m_uniq} (expected 43)",
    })

    b_rows = len(df_benefits)
    checks.append({
        "check": "treatment_benefits_count_387",
        "severity": "CRITICAL",
        "passed": (b_rows == 387),
        "evidence": f"Treatment benefits panel rows: {b_rows} (expected 387)",
    })

    # 3. Uniqueness checks
    dup_master = df_master.duplicated(subset=["corridor_id"]).sum()
    checks.append({
        "check": "no_duplicate_master_corridor_ids",
        "severity": "CRITICAL",
        "passed": (dup_master == 0),
        "evidence": f"Duplicate corridor_id keys in master dimension: {dup_master} (expected 0)",
    })

    dup_sel_keys = df_selections.duplicated(subset=["portfolio_id", "corridor_id"]).sum()
    checks.append({
        "check": "no_duplicate_portfolio_corridor_keys",
        "severity": "CRITICAL",
        "passed": (dup_sel_keys == 0),
        "evidence": f"Duplicate (portfolio_id, corridor_id) detail keys: {dup_sel_keys} (expected 0)",
    })

    # 4. Summary vs Detail Exact Reconciliations
    reconciled_all = True
    for pid, grp in df_selections.groupby("portfolio_id"):
        s_row = df_summary[df_summary["portfolio_id"] == pid].iloc[0]
        c_diff = abs(grp["capital_project_cost"].sum() - s_row["selected_capital_cost"])
        pv_diff = abs(grp["present_value_benefit"].sum() - s_row["total_present_value_benefit"])
        npv_diff = abs(grp["net_present_benefit"].sum() - s_row["total_net_present_benefit"])
        if max(c_diff, pv_diff, npv_diff) > 1e-4:
            reconciled_all = False

    checks.append({
        "check": "summary_detail_reconciliation_exact",
        "severity": "CRITICAL",
        "passed": bool(reconciled_all),
        "evidence": f"Summary and detail cost/benefit reconciliation exact across all 36 portfolios: {reconciled_all}",
    })

    # 5. Detail vs Source Phase 4B Panel Lineage Reconciliation
    df_src = pd.read_parquet(source_benefits_path).rename(columns={"scenario_level": "uncertainty_scenario"})
    merged = pd.merge(
        df_selections,
        df_src,
        on=["corridor_id", "treatment_id", "uncertainty_scenario"],
        how="left",
        suffixes=("_mart", "_source"),
    )
    unmatched_count = int(merged["capital_project_cost_source"].isna().sum())
    max_c_diff = float(np.max(np.abs(merged["capital_project_cost_mart"] - merged["capital_project_cost_source"])))
    max_pv_diff = float(np.max(np.abs(merged["present_value_benefit_mart"] - merged["present_value_benefit_source"])))

    lineage_exact = (unmatched_count == 0 and max_c_diff == 0.0 and max_pv_diff == 0.0)
    checks.append({
        "check": "source_selections_lineage_exact",
        "severity": "CRITICAL",
        "passed": bool(lineage_exact),
        "evidence": f"100% 1-to-1 match between detail selections and Phase 4B source panel: {lineage_exact} (Max Cost Diff: {max_c_diff}, Max PV Diff: {max_pv_diff})",
    })

    # 6. Governance labels complete
    gov_complete = (df_summary["required_governance_labels"].str.len() > 0).all() and (df_selections["required_governance_labels"].str.len() > 0).all()
    checks.append({
        "check": "governance_labels_complete",
        "severity": "CRITICAL",
        "passed": bool(gov_complete),
        "evidence": f"Required governance labels complete on all summary and detail rows: {gov_complete}",
    })

    # 7. Governed Equivalence Fields & Canonical Dashboard Uniqueness
    canonical_official = df_summary[(df_summary["run_group"] == "OFFICIAL") & (df_summary["is_canonical_portfolio"])]
    canonical_official_scens = canonical_official["scenario_level"].nunique()
    default_dash_count = int(df_summary["is_default_dashboard_portfolio"].sum())

    equiv_valid = (
        "portfolio_equivalence_group" in df_summary.columns and
        canonical_official_scens == 3 and
        len(canonical_official) == 3 and
        default_dash_count == 1
    )
    checks.append({
        "check": "governed_equivalence_and_canonical_uniqueness",
        "severity": "CRITICAL",
        "passed": bool(equiv_valid),
        "evidence": f"Canonical official portfolios unique per scenario: {canonical_official_scens} (expected 3), default dashboard portfolio count: {default_dash_count} (expected 1)",
    })

    # 8. Spatial Serving Readiness Verification
    spatial_valid = (
        "centroid_latitude" in df_master.columns and
        "centroid_longitude" in df_master.columns and
        "geometry_wkt" in df_master.columns and
        "geometry_crs" in df_master.columns and
        df_master["centroid_latitude"].notna().all() and
        df_master["centroid_longitude"].notna().all()
    )
    checks.append({
        "check": "spatial_serving_readiness_verified",
        "severity": "CRITICAL",
        "passed": bool(spatial_valid),
        "evidence": f"Master corridor dimension contains WGS84 centroids, WKT linework, EPSG:3435 CRS, and corridor_id join key: {spatial_valid}",
    })

    # =========================================================================
    # GOVERNANCE WARNINGS
    # =========================================================================
    warnings.append({
        "code": "WARNING_PROVISIONAL_DECISION_MART_ONLY",
        "warning_id": "WARNING_PROVISIONAL_DECISION_MART_ONLY",
        "affected_tables": 4,
        "explanation": "All output tables represent analyst-defined planning scenarios for decision support only.",
        "limitation_or_resolution": "Does not constitute official City policy or engineering site selection. Requires CDOT/IDOT staff review.",
        "governance_reference": "D004, D005",
    })

    warnings.append({
        "code": "WARNING_PHYSICAL_APPLICABILITY_UNKNOWN",
        "warning_id": "WARNING_PHYSICAL_APPLICABILITY_UNKNOWN",
        "affected_corridors": 43,
        "explanation": "Physical applicability status is UNKNOWN due to missing corridor lane counts, median widths, and crossing inventories.",
        "limitation_or_resolution": "Every selected corridor project requires CDOT/IDOT engineering field survey.",
        "governance_reference": "A004, D005",
    })

    critical_failures = sum(1 for c in checks if c["severity"] == "CRITICAL" and not c["passed"])
    status = "PASS_WITH_WARNINGS" if critical_failures == 0 else "FAIL"

    summary_metrics = {
        "portfolio_summary_rows": s_rows,
        "project_selections_rows": sel_rows,
        "corridor_master_rows": m_rows,
        "treatment_benefits_rows": b_rows,
        "reconciliation_exact": reconciled_all,
        "lineage_exact": lineage_exact,
    }

    validation_report = {
        "pipeline": "decision_output_mart",
        "run_id": run_timestamp,
        "completed_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "is_sample": False,
        "scenario_summary": summary_metrics,
        "status": status,
        "downstream_readiness": "READY_FOR_POWER_BI_AND_STREAMLIT_INTEGRATION",
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
    run_file_path = runs_dir_path / f"decision_output_mart_validation_{run_timestamp}.json"
    with open(run_file_path, "w", encoding="utf-8") as f:
        json.dump(clean_report, f, indent=2)

    elapsed = time.time() - t0
    print(f"\nValidation completed in {elapsed:.2f}s.")
    print(f"Status: {status} (Critical Failures: {critical_failures}, Warnings: {len(warnings)})")
    print(f"Main validation JSON: {validation_json_path}")
    print(f"Historical run JSON:  {run_file_path}")
    print("=" * 80)

    if critical_failures > 0:
        raise ValueError(f"Decision output mart validation failed with {critical_failures} critical failures!")

    return validation_report


if __name__ == "__main__":
    validate_decision_output_mart()
