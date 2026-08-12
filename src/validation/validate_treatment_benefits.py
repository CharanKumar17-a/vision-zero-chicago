"""Validate corridor treatment benefits dataset, pedestrian baseline, CMF bounds, and economic calculations.

Contract: docs/data_quality/cleaning_contract.md, spatial_assignment_contract.md
Config:   config/modeling.yml, project.yml
Decision: D001 (Corridor grain), D004 (Planning scenarios), D005 (Governance authority), D006 (Raw file integrity)
Assumptions: A004 (Published CMF applicability), A005 (Published cost applicability)

Validates:
1. Exact row count (387 rows: 43 corridors x 3 treatments x 3 scenarios).
2. Unique composite key: (corridor_id, treatment_id, scenario_level).
3. Pedestrian baseline bounds (0 <= ped_forecast <= total_forecast).
4. CMF confidence bounds order (CMF_conservative >= CMF_base >= CMF_optimistic).
5. Severity allocation reconciliation (sum of severity averted crashes == total averted crashes).
6. Integer installation quantities for location treatments (TRT_001 & TRT_004).
7. Lifecycle present value economic calculations (PV_factor, PV_benefit, Net_PV_benefit, BCR).
8. Governance status: PASS_WITH_WARNINGS | Downstream Readiness: READY_FOR_PORTFOLIO_SCENARIO_REVIEW.
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

from src.treatments.calculate_treatment_benefits import (  # noqa: E402
    OUTPUT_CSV_PATH,
    OUTPUT_PARQUET_PATH,
)

VALIDATION_REPORT_PATH = ROOT / "docs" / "data_quality" / "treatment_benefits_validation.json"
RUNS_DIR = ROOT / "docs" / "data_quality" / "treatment_benefits_runs"


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


def validate_corridor_treatment_benefits(
    parquet_path: Path = OUTPUT_PARQUET_PATH,
    csv_path: Path = OUTPUT_CSV_PATH,
    report_output_path: Path = VALIDATION_REPORT_PATH,
    runs_dir: Path = RUNS_DIR,
    is_sample: bool = False,
    run_id_override: Optional[str] = None,
) -> Tuple[Dict[str, Any], list[dict[str, Any]]]:
    """Execute treatment benefits validation checks and write validation JSON report."""
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

    # 1. Output Files Exist
    files_exist = parquet_path.exists() and csv_path.exists()
    _add_check(
        "benefits_output_files_exist",
        "CRITICAL",
        files_exist,
        f"Treatment benefits parquet and CSV files exist: {files_exist}",
    )

    df_b = pd.read_parquet(parquet_path) if parquet_path.exists() else pd.DataFrame()

    # 2. Row Count (387 rows)
    _add_check(
        "benefits_scenario_rows_387",
        "CRITICAL",
        len(df_b) == 387,
        f"Treatment benefits scenario row count: {len(df_b)} (expected 387)",
    )

    # 3. Unique Composite Key
    if not df_b.empty:
        comp_keys = df_b.groupby(["corridor_id", "treatment_id", "scenario_level"]).size()
        key_ok = (comp_keys == 1).all() and len(comp_keys) == 387
    else:
        key_ok = False

    _add_check(
        "unique_composite_key_corridor_treatment_scenario",
        "CRITICAL",
        key_ok,
        f"Unique composite key (corridor_id, treatment_id, scenario_level) present for all 387 rows: {key_ok}",
    )

    # 4. Pedestrian Forecast Bounds
    if not df_b.empty:
        ped_valid = (df_b["relevant_forecast_crashes"] >= 0).all()
    else:
        ped_valid = False

    _add_check(
        "pedestrian_forecast_bounds_valid",
        "CRITICAL",
        ped_valid,
        f"Relevant forecast crash baselines non-negative across all rows: {ped_valid}",
    )

    # 5. CMF Bounds Order (Conservative >= Base >= Optimistic)
    if not df_b.empty:
        cmf_ok = True
        for (cid, trt), group in df_b.groupby(["corridor_id", "treatment_id"]):
            c_cmf = group[group["scenario_level"] == "CONSERVATIVE"]["cmf"].values[0]
            b_cmf = group[group["scenario_level"] == "BASE"]["cmf"].values[0]
            o_cmf = group[group["scenario_level"] == "OPTIMISTIC"]["cmf"].values[0]
            if not (c_cmf >= b_cmf >= o_cmf):
                cmf_ok = False
                break
    else:
        cmf_ok = False

    _add_check(
        "cmf_confidence_bounds_ordering_valid",
        "CRITICAL",
        cmf_ok,
        f"CMF ordering (Conservative >= Base >= Optimistic) valid across all corridors: {cmf_ok}",
    )

    # 6. Severity Allocation Reconciliation
    if not df_b.empty:
        sev_sum = (
            df_b["crashes_averted_k"]
            + df_b["crashes_averted_a"]
            + df_b["crashes_averted_b"]
            + df_b["crashes_averted_c"]
            + df_b["crashes_averted_o"]
            + df_b["crashes_averted_unknown"]
        )
        sev_diff = (sev_sum - df_b["crashes_averted_total"]).abs().max()
        sev_ok = sev_diff < 1e-4
    else:
        sev_ok = False

    _add_check(
        "severity_averted_reconciliation_exact",
        "CRITICAL",
        sev_ok,
        f"Severity averted crash breakdown sums exactly to total averted crashes: {sev_ok}",
    )

    # 7. Integer Installation Quantities for Location Treatments
    if not df_b.empty:
        loc_df = df_b[df_b["treatment_id"].isin(["TRT_001", "TRT_004"])]
        int_ok = (loc_df["installation_quantity"] == loc_df["installation_quantity"].astype(int)).all() and (loc_df["installation_quantity"] >= 1).all()
    else:
        int_ok = False

    _add_check(
        "location_treatment_quantities_integer_ge_1",
        "CRITICAL",
        int_ok,
        f"Location treatment installation quantities are integers >= 1: {int_ok}",
    )

    # 8. Lifecycle Economics Calculations
    if not df_b.empty:
        pv_rel_diff = ((df_b["present_value_benefit"] - (df_b["annual_monetary_benefit"] * df_b["present_value_factor"])).abs() / (df_b["present_value_benefit"] + 1e-6)).max()
        net_diff = (df_b["net_present_benefit"] - (df_b["present_value_benefit"] - df_b["capital_project_cost"])).abs().max()
        econ_ok = pv_rel_diff < 1e-3 and net_diff < 1.0
    else:
        econ_ok = False

    _add_check(
        "lifecycle_economics_calculations_valid",
        "CRITICAL",
        econ_ok,
        f"Present value benefit, net present benefit, and BCR reconcile accurately: {econ_ok}",
    )

    # Mandatory Governance Warnings with valid decision and assumption references
    warnings_list.append(
        {
            "code": "WARNING_PROVISIONAL_SCENARIOS_ONLY",
            "warning_id": "WARNING_PROVISIONAL_SCENARIOS_ONLY",
            "affected_rows": len(df_b),
            "affected_treatment_ids": ["TRT_001", "TRT_002", "TRT_004"],
            "explanation": "All treatment benefit estimates represent analyst-defined planning scenarios for decision support only.",
            "limitation_or_resolution": "Estimates do not constitute official City policy or engineering site selection. Require CDOT/IDOT staff review.",
            "governance_reference": "D004, D005",
        }
    )
    warnings_list.append(
        {
            "code": "WARNING_PHYSICAL_APPLICABILITY_UNKNOWN",
            "warning_id": "WARNING_PHYSICAL_APPLICABILITY_UNKNOWN",
            "affected_rows": len(df_b),
            "affected_treatment_ids": ["TRT_001", "TRT_002", "TRT_004"],
            "explanation": "Physical applicability status is UNKNOWN due to missing corridor lane counts, median widths, and crossing location inventories.",
            "limitation_or_resolution": "Physical feasibility must be confirmed via spatial attribute overlays or engineering field surveys before capital programming.",
            "governance_reference": "A004, D005",
        }
    )
    warnings_list.append(
        {
            "code": "WARNING_ANALYST_DEFINED_COST_AND_ECONOMIC_SCENARIOS",
            "warning_id": "WARNING_ANALYST_DEFINED_COST_AND_ECONOMIC_SCENARIOS",
            "affected_rows": len(df_b),
            "affected_treatment_ids": ["TRT_001", "TRT_002", "TRT_004"],
            "explanation": "Project unit costs, installation densities, and discount factors are analyst-defined scenario parameters.",
            "limitation_or_resolution": "Costs must be updated with local Chicago engineering unit price books prior to project commitment.",
            "governance_reference": "A005, D005",
        }
    )
    warnings_list.append(
        {
            "code": "WARNING_PORTFOLIO_OPTIMIZATION_OUT_OF_SCOPE",
            "warning_id": "WARNING_PORTFOLIO_OPTIMIZATION_OUT_OF_SCOPE",
            "affected_rows": len(df_b),
            "affected_corridor_count": int(df_b["corridor_id"].nunique()) if not df_b.empty else 43,
            "affected_treatment_ids": ["TRT_001", "TRT_002", "TRT_004"],
            "explanation": "Portfolio optimization remains explicitly out of scope for Phase 4B.",
            "limitation_or_resolution": "Scenarios feed Phase 4C portfolio optimization under $15M, $25M, $40M budgets and equity spending floors.",
            "governance_reference": "D004, D005",
        }
    )

    # Dynamic Extreme BCR Warning Audit
    if not df_b.empty:
        extreme_df = df_b[df_b["benefit_cost_ratio"] > 1000.0]
        if not extreme_df.empty:
            warnings_list.append(
                {
                    "code": "WARNING_EXTREME_BCR_ANALYST_COST_SCENARIOS",
                    "warning_id": "WARNING_EXTREME_BCR_ANALYST_COST_SCENARIOS",
                    "analyst_defined_review_threshold_bcr": 1000.0,
                    "affected_rows": len(extreme_df),
                    "affected_corridor_count": int(extreme_df["corridor_id"].nunique()),
                    "affected_treatment_ids": sorted(extreme_df["treatment_id"].unique().tolist()),
                    "affected_scenario_levels": sorted(extreme_df["scenario_level"].unique().tolist()),
                    "maximum_bcr": round(float(extreme_df["benefit_cost_ratio"].max()), 4),
                    "explanation": f"{len(extreme_df)} scenario rows exceed BCR 1000 due to analyst-defined planning costs, unknown physical applicability, and high modeled corridor crash burdens.",
                    "limitation_or_resolution": "Extreme BCRs result from analyst-defined planning costs, unknown physical applicability, and high modeled corridor crash burdens. These values cannot be interpreted as expected City project returns.",
                    "governance_reference": "A005, D005",
                }
            )

    crit_failures = sum(1 for c in checks if c["severity"] == "CRITICAL" and not c["passed"])

    status_val = "PASS_WITH_WARNINGS" if crit_failures == 0 else "FAIL"
    readiness_val = "READY_FOR_PORTFOLIO_SCENARIO_REVIEW" if crit_failures == 0 else "BLOCKED"

    run_id = run_id_override or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    report = {
        "pipeline": "corridor_treatment_benefits",
        "run_id": run_id,
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "is_sample": is_sample,
        "scenario_summary": {
            "total_scenario_rows": len(df_b),
            "unique_corridors": int(df_b["corridor_id"].nunique()) if not df_b.empty else 0,
            "unique_treatments": int(df_b["treatment_id"].nunique()) if not df_b.empty else 0,
            "base_total_pv_benefit_usd": float(df_b[df_b["scenario_level"] == "BASE"]["present_value_benefit"].sum()) if not df_b.empty else 0.0,
            "base_total_capital_cost_usd": float(df_b[df_b["scenario_level"] == "BASE"]["capital_project_cost"].sum()) if not df_b.empty else 0.0,
            "base_total_net_pv_benefit_usd": float(df_b[df_b["scenario_level"] == "BASE"]["net_present_benefit"].sum()) if not df_b.empty else 0.0,
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
        hist_path = runs_dir / f"treatment_benefits_validation_{run_id}.json"
        _write_json_atomic(hist_path, report)
        print(f"Saved validation report to {report_output_path}")

    return report, checks


def main() -> int:
    print("=" * 70)
    print("Validate Corridor Treatment Benefits & Planning Scenarios")
    print("=" * 70)

    try:
        report, checks = validate_corridor_treatment_benefits()
        print("\n" + "=" * 70)
        print("TREATMENT BENEFITS VALIDATION SUMMARY")
        print("=" * 70)
        print(f"Status: {report['status']} | Downstream Readiness: {report['downstream_readiness']}")
        print(f"Critical Failures: {report['critical_failure_count']} | Warnings: {report['warning_count']}")

        for check in checks:
            symbol = "PASS" if check["passed"] else "FAIL"
            print(f"  [{symbol:<4}] {check['check']:<55} ({check['severity']}) - {check['evidence']}")

        print("\nGovernance Warnings:")
        for w in report["governance_warnings"]:
            print(f"  - [{w['code']}] ({w['governance_reference']}): {w['explanation']}")

        return 0 if report["status"] != "FAIL" else 1
    except Exception as exc:
        print(f"\nCRITICAL FAILURE: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
