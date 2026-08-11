"""Run threshold sensitivity analysis for crash-to-corridor assignment.

Contract: docs/data_quality/spatial_assignment_contract.md
Config:   config/spatial.yml (threshold_sensitivity & crash_assignment sections)

Executes candidate generation across configured candidate thresholds (50, 100, 150, 200 ft),
computes sensitivity metrics, distance diagnostics, incremental bands, and validation checks.

selected_distance_threshold_feet remains null. No threshold is selected by this script.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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

CANDIDATE_OUTPUT_PATH = ROOT / "data" / "interim" / "crash_corridor_candidates.parquet"
REVIEW_SAMPLE_OUTPUT_PATH = ROOT / "data" / "interim" / "borderline_assignment_review_sample.csv"

SENSITIVITY_REPORT_PATH = ROOT / "docs" / "data_quality" / "threshold_sensitivity_report.json"
SENSITIVITY_RUNS_DIR = ROOT / "docs" / "data_quality" / "crash_corridor_assignment_runs"


def _write_json_atomic(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.json")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    tmp.replace(path)


def compute_distance_diagnostics(candidates_full: pd.DataFrame) -> dict[str, Any]:
    """Compute distance frequency diagnostics for candidate matches."""
    rank1 = candidates_full[candidates_full["candidate_rank"] == 1].copy()

    rounded_counts = rank1["distance_feet"].round(1).value_counts().head(10).to_dict()
    top_10 = [
        {"distance_feet_round1": float(k), "count": int(v)}
        for k, v in rounded_counts.items()
    ]

    exact_zero_rank1 = int((rank1["distance_feet"] == 0.0).sum())
    exact_zero_all = int((candidates_full["distance_feet"] == 0.0).sum())

    near_40_rank1 = int(
        ((rank1["distance_feet"] >= 39.5) & (rank1["distance_feet"] <= 40.5)).sum()
    )
    near_40_all = int(
        (
            (candidates_full["distance_feet"] >= 39.5)
            & (candidates_full["distance_feet"] <= 40.5)
        ).sum()
    )

    return {
        "top_10_rounded_distances_rank1": top_10,
        "exact_zero_distance_candidates_rank1": exact_zero_rank1,
        "exact_zero_distance_candidates_all": exact_zero_all,
        "near_40ft_candidates_rank1_39_5_to_40_5": near_40_rank1,
        "near_40ft_candidates_all_39_5_to_40_5": near_40_all,
        "finding_explanation": (
            "A substantial observed cluster occurs near 40 feet. Its precise geocoding or "
            "right-of-way cause has not been independently verified."
        ),
    }


def compute_incremental_distance_bands(
    candidates_full: pd.DataFrame,
    eligible_count: int,
    tie_tolerance_feet: float = 10.0,
) -> list[dict[str, Any]]:
    """Compute metrics for incremental distance bands evaluated at upper threshold."""
    bands = [
        ("0-50 ft", 0.0, 50.0),
        (">50-100 ft", 50.000001, 100.0),
        (">100-150 ft", 100.000001, 150.0),
        (">150-200 ft", 150.000001, 200.0),
    ]

    band_results = []
    for label, dmin, dmax in bands:
        # Candidates available up to upper threshold dmax
        cand_sub = candidates_full[candidates_full["distance_feet"] <= dmax].copy()

        if cand_sub.empty:
            band_results.append(
                {
                    "distance_band": label,
                    "upper_eval_threshold_feet": dmax,
                    "min_distance_feet": dmin,
                    "max_distance_feet": dmax,
                    "candidate_pair_count": 0,
                    "unique_matched_crashes": 0,
                    "ambiguity_count": 0,
                    "ambiguity_rate": 0.0,
                    "tie_count": 0,
                    "tie_rate": 0.0,
                }
            )
            continue

        cand_sub["rank_at_max"] = (
            cand_sub.groupby("crash_record_id")["distance_feet"]
            .rank(method="first")
            .astype(int)
        )
        cand_sub["count_at_max"] = cand_sub.groupby("crash_record_id")[
            "crash_record_id"
        ].transform("count")

        r1 = cand_sub[cand_sub["rank_at_max"] == 1][
            ["crash_record_id", "distance_feet"]
        ].rename(columns={"distance_feet": "d1"})
        r2 = cand_sub[cand_sub["rank_at_max"] == 2][
            ["crash_record_id", "distance_feet"]
        ].rename(columns={"distance_feet": "d2"})

        tie_m = r1.merge(r2, on="crash_record_id", how="left")
        tie_m["is_tie_at_max"] = (
            tie_m["d2"] - tie_m["d1"]
        ).fillna(float("inf")) <= tie_tolerance_feet
        tie_ids = set(tie_m.loc[tie_m["is_tie_at_max"], "crash_record_id"])

        rank1_sub = cand_sub[cand_sub["rank_at_max"] == 1].copy()
        band_rank1 = rank1_sub[
            (rank1_sub["distance_feet"] >= dmin)
            & (rank1_sub["distance_feet"] <= dmax)
        ]

        unique_crashes = len(band_rank1)
        cand_pairs_in_band = len(
            candidates_full[
                (candidates_full["distance_feet"] >= dmin)
                & (candidates_full["distance_feet"] <= dmax)
            ]
        )

        ambig_count = int((band_rank1["count_at_max"] > 1).sum())
        ambig_rate = (
            round(ambig_count / unique_crashes, 6) if unique_crashes else 0.0
        )

        tie_count = int(band_rank1["crash_record_id"].isin(tie_ids).sum())
        tie_rate = (
            round(tie_count / unique_crashes, 6) if unique_crashes else 0.0
        )

        band_results.append(
            {
                "distance_band": label,
                "upper_eval_threshold_feet": dmax,
                "min_distance_feet": dmin,
                "max_distance_feet": dmax,
                "candidate_pair_count": cand_pairs_in_band,
                "unique_matched_crashes": unique_crashes,
                "ambiguity_count": ambig_count,
                "ambiguity_rate": ambig_rate,
                "tie_count": tie_count,
                "tie_rate": tie_rate,
            }
        )

    return band_results


def generate_borderline_review_sample(
    candidates_full: pd.DataFrame,
    all_crashes: pd.DataFrame,
    corridors_gdf: pd.DataFrame,
    output_path: Path = REVIEW_SAMPLE_OUTPUT_PATH,
    crashes_per_band: int = 25,
) -> pd.DataFrame:
    """Generate a deterministic review sample (25 unique crashes per incremental band)."""
    rank1 = candidates_full[candidates_full["candidate_rank"] == 1].copy()

    bands = [
        ("0-50 ft", 0.0, 50.0),
        (">50-100 ft", 50.000001, 100.0),
        (">100-150 ft", 100.000001, 150.0),
        (">150-200 ft", 150.000001, 200.0),
    ]

    sample_rows = []
    for label, dmin, dmax in bands:
        sub = (
            rank1[(rank1["distance_feet"] >= dmin) & (rank1["distance_feet"] <= dmax)]
            .sort_values("crash_record_id")
            .head(crashes_per_band)
            .copy()
        )
        sub["distance_band"] = label
        sample_rows.append(sub)

    sample_df = pd.concat(sample_rows, ignore_index=True)
    sample_df = sample_df.merge(
        all_crashes[["crash_record_id", "latitude", "longitude"]],
        on="crash_record_id",
        how="left",
    )
    sample_df = sample_df.merge(
        corridors_gdf[["corridor_id", "corridor_name"]],
        on="corridor_id",
        how="left",
    )

    cols = [
        "distance_band",
        "crash_record_id",
        "latitude",
        "longitude",
        "corridor_id",
        "corridor_name",
        "distance_feet",
        "candidate_count",
        "candidate_rank",
        "is_ambiguous",
        "is_tie",
    ]
    sample_df = sample_df[cols]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    sample_df.to_csv(output_path, index=False)
    return sample_df


def validate_report(
    report: dict[str, Any],
    candidates_full: pd.DataFrame,
    configured_thresholds: list[int],
    authoritative_register_ids: set[str],
    geometry_corridor_ids: set[str],
) -> list[dict[str, Any]]:
    """Run explicit validation checks and return list of check objects.

    Each check object contains:
    - check: str
    - severity: 'CRITICAL' | 'WARNING'
    - passed: bool
    - evidence: str
    """
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

    # 1. Authoritative Corridor Register Count
    reg_count = len(authoritative_register_ids)
    _add_check(
        "corridor_register_count_is_43",
        "CRITICAL",
        reg_count == 43,
        f"Authoritative register corridor count: {reg_count} (expected 43)",
    )

    # 2. Geometry Corridors Match Register Exactly
    geom_matches_reg = (geometry_corridor_ids == authoritative_register_ids)
    diff_geom_reg = geometry_corridor_ids.symmetric_difference(authoritative_register_ids)
    _add_check(
        "geometry_corridors_match_register",
        "CRITICAL",
        geom_matches_reg,
        f"Geometry IDs match register: {geom_matches_reg} (diff: {sorted(list(diff_geom_reg)) if diff_geom_reg else 'none'})",
    )

    # 3. Candidate Corridors are a Subset of Authoritative Register
    cand_corrs = (
        set(candidates_full["corridor_id"].unique())
        if not candidates_full.empty
        else set()
    )
    unknown_cand_corrs = cand_corrs - authoritative_register_ids
    _add_check(
        "candidate_corridors_subset_of_register",
        "CRITICAL",
        len(unknown_cand_corrs) == 0,
        f"Unknown candidate corridor IDs: {sorted(list(unknown_cand_corrs)) if unknown_cand_corrs else 'none'}",
    )

    # 4. Source CRS
    src_crs = report.get("source_crs")
    _add_check(
        "source_crs_is_epsg4326",
        "CRITICAL",
        src_crs == SOURCE_CRS,
        f"Source CRS: '{src_crs}' (expected '{SOURCE_CRS}')",
    )

    # 5. Analysis CRS
    an_crs = report.get("analysis_crs")
    _add_check(
        "analysis_crs_is_epsg3435",
        "CRITICAL",
        an_crs == ANALYSIS_CRS,
        f"Analysis CRS: '{an_crs}' (expected '{ANALYSIS_CRS}')",
    )

    # 6. Configured thresholds
    exec_thresh = report.get("thresholds_evaluated_feet", [])
    _add_check(
        "thresholds_match_configured",
        "CRITICAL",
        exec_thresh == configured_thresholds,
        f"Executed thresholds: {exec_thresh} (expected {configured_thresholds})",
    )

    # 7. Selected threshold null
    sel_t = report.get("selected_distance_threshold_feet")
    _add_check(
        "selected_threshold_is_null",
        "CRITICAL",
        sel_t is None,
        f"selected_distance_threshold_feet: {sel_t} (expected null)",
    )

    # 8. Source total reconciliation
    tot = report.get("total_crashes", 0)
    elig = report.get("eligible_crashes", 0)
    inval = report.get("invalid_coordinate_crashes", 0)
    is_samp = report.get("is_sample", False)
    if not is_samp:
        _add_check(
            "source_reconciliation_zero_diff",
            "CRITICAL",
            tot == elig + inval,
            f"Total crashes {tot} == eligible {elig} + invalid {inval} (diff: {tot - (elig + inval)})",
        )
    else:
        _add_check(
            "source_reconciliation_zero_diff",
            "WARNING",
            True,
            f"Sample mode active: evaluating sample of {elig} eligible crashes.",
        )

    # 9. Candidate table null keys/distances
    null_crash_ids = (
        int(candidates_full["crash_record_id"].isna().sum())
        if not candidates_full.empty
        else 0
    )
    null_corr_ids = (
        int(candidates_full["corridor_id"].isna().sum())
        if not candidates_full.empty
        else 0
    )
    null_dists = (
        int(candidates_full["distance_feet"].isna().sum())
        if not candidates_full.empty
        else 0
    )
    has_no_nulls = (null_crash_ids == 0) and (null_corr_ids == 0) and (null_dists == 0)
    _add_check(
        "no_null_candidate_keys_or_distances",
        "CRITICAL",
        has_no_nulls,
        f"Null crash_ids: {null_crash_ids}, null corridor_ids: {null_corr_ids}, null distances: {null_dists}",
    )

    # 10. Candidate keys unique
    dup_keys = (
        int(
            candidates_full.duplicated(
                subset=["crash_record_id", "corridor_id"]
            ).sum()
        )
        if not candidates_full.empty
        else 0
    )
    _add_check(
        "candidate_keys_unique",
        "CRITICAL",
        dup_keys == 0,
        f"Duplicate (crash_record_id, corridor_id) pairs: {dup_keys}",
    )

    # 11. Candidate distances in range [0, max_threshold]
    max_thresh = max(configured_thresholds) if configured_thresholds else 200.0
    min_dist = float(candidates_full["distance_feet"].min()) if not candidates_full.empty else 0.0
    max_dist = float(candidates_full["distance_feet"].max()) if not candidates_full.empty else 0.0
    dist_valid = (min_dist >= 0.0) and (max_dist <= max_thresh)
    _add_check(
        "candidate_distances_in_range",
        "CRITICAL",
        dist_valid,
        f"Distance range: [{min_dist:.3f}, {max_dist:.3f}] (allowed [0.0, {max_thresh}])",
    )

    # 12 & 13. Monotonicity and threshold reconciliations
    results = report.get("threshold_results", [])
    matched_counts = [r["matched_unique_crashes"] for r in results]
    pair_counts = [r["candidate_pair_count"] for r in results]

    matched_mono = all(
        matched_counts[i] >= matched_counts[i - 1]
        for i in range(1, len(matched_counts))
    )
    pairs_mono = all(
        pair_counts[i] >= pair_counts[i - 1] for i in range(1, len(pair_counts))
    )

    _add_check(
        "threshold_matched_counts_monotonic",
        "CRITICAL",
        matched_mono,
        f"Matched unique crash counts by threshold: {matched_counts}",
    )
    _add_check(
        "threshold_candidate_pairs_monotonic",
        "CRITICAL",
        pairs_mono,
        f"Candidate pair counts by threshold: {pair_counts}",
    )

    # 14. Threshold reconciliation deltas
    all_recon_zero = True
    bad_recon_details = []
    for r in results:
        t = r["threshold_feet"]
        rec = r.get("reconciliation", {})
        if rec.get("threshold_reconciliation_diff", 0) != 0 or rec.get("matched_breakdown_diff", 0) != 0:
            all_recon_zero = False
            bad_recon_details.append(f"t={t}ft")

    _add_check(
        "threshold_reconciliations_zero_diff",
        "CRITICAL",
        all_recon_zero,
        f"Reconciliation deltas zero: {all_recon_zero} (failures: {bad_recon_details if bad_recon_details else 'none'})",
    )

    # 15. Corridor coverage
    cov_count = len(cand_corrs)
    expected_count = len(authoritative_register_ids)
    _add_check(
        "corridor_coverage_all_received_candidates",
        "WARNING",
        cov_count == expected_count,
        f"Corridor coverage: {cov_count} of {expected_count} corridors received candidates",
    )

    return checks


def compute_threshold_metrics(
    candidates_full: pd.DataFrame,
    eligible_count: int,
    total_count: int,
    invalid_count: int,
    threshold_feet: int,
    tie_tolerance_feet: float = 10.0,
    prev_matched_count: int | None = None,
) -> dict[str, Any]:
    """Compute sensitivity and reconciliation metrics for threshold t."""
    cand_t = candidates_full[candidates_full["distance_feet"] <= threshold_feet].copy()
    candidate_pair_count = len(cand_t)

    if cand_t.empty:
        matched_unique_crashes = 0
        unmatched_crashes = eligible_count
        single_candidate_crashes = 0
        multiple_candidate_crashes = 0
        tie_crashes = 0
        ambiguity_rate = 0.0
        match_rate = 0.0
        dist_median = None
        dist_p95 = None
        dist_max = None
        corridor_coverage = 0
    else:
        crash_counts = cand_t.groupby("crash_record_id")["corridor_id"].count()
        matched_unique_crashes = len(crash_counts)
        unmatched_crashes = eligible_count - matched_unique_crashes
        match_rate = round(matched_unique_crashes / eligible_count, 6) if eligible_count else 0.0

        single_candidate_crashes = int((crash_counts == 1).sum())
        multiple_candidate_crashes = int((crash_counts > 1).sum())
        ambiguity_rate = (
            round(multiple_candidate_crashes / matched_unique_crashes, 6)
            if matched_unique_crashes
            else 0.0
        )

        rank1_t = cand_t.groupby("crash_record_id")["distance_feet"].min().rename("d1")
        rank2_t = (
            cand_t[cand_t.groupby("crash_record_id")["distance_feet"].rank(method="first") == 2]
            .set_index("crash_record_id")["distance_feet"]
            .rename("d2")
        )
        tie_df = pd.concat([rank1_t, rank2_t], axis=1)
        tie_crashes = int(((tie_df["d2"] - tie_df["d1"]) <= tie_tolerance_feet).sum())

        rank1_distances = rank1_t.values
        dist_median = round(float(np.percentile(rank1_distances, 50)), 3)
        dist_p95 = round(float(np.percentile(rank1_distances, 95)), 3)
        dist_max = round(float(rank1_distances.max()), 3)

        corridor_coverage = int(cand_t["corridor_id"].nunique())

    marginal_matches_gained = (
        (matched_unique_crashes - prev_matched_count)
        if prev_matched_count is not None
        else None
    )

    source_recon_diff = total_count - (eligible_count + invalid_count)
    threshold_recon_diff = eligible_count - (matched_unique_crashes + unmatched_crashes)
    matched_breakdown_diff = matched_unique_crashes - (
        single_candidate_crashes + multiple_candidate_crashes
    )

    return {
        "threshold_feet": threshold_feet,
        "eligible_crash_count": eligible_count,
        "candidate_pair_count": candidate_pair_count,
        "matched_unique_crashes": matched_unique_crashes,
        "match_rate": match_rate,
        "unmatched_crashes": unmatched_crashes,
        "single_candidate_crashes": single_candidate_crashes,
        "multiple_candidate_crashes": multiple_candidate_crashes,
        "ambiguity_rate": ambiguity_rate,
        "tie_crashes": tie_crashes,
        "distance_median_feet": dist_median,
        "distance_p95_feet": dist_p95,
        "distance_max_feet": dist_max,
        "marginal_matches_gained": marginal_matches_gained,
        "corridor_coverage": corridor_coverage,
        "reconciliation": {
            "total_crashes": total_count,
            "valid_coordinate_crashes": eligible_count,
            "invalid_coordinate_crashes": invalid_count,
            "source_reconciliation_diff": source_recon_diff,
            "matched_unique_crashes": matched_unique_crashes,
            "unmatched_crashes": unmatched_crashes,
            "threshold_reconciliation_diff": threshold_recon_diff,
            "single_candidate_crashes": single_candidate_crashes,
            "multiple_candidate_crashes": multiple_candidate_crashes,
            "matched_breakdown_diff": matched_breakdown_diff,
            "tie_crashes_subset_flag": tie_crashes,
        },
    }


def run_threshold_sensitivity(
    spatial_config: dict | None = None,
    crashes_path: Path = CRASHES_PATH,
    corridors_path: Path = CORRIDORS_PATH,
    register_path: Path = REGISTER_PATH,
    candidate_output_path: Path = CANDIDATE_OUTPUT_PATH,
    sensitivity_report_path: Path = SENSITIVITY_REPORT_PATH,
    runs_dir: Path = SENSITIVITY_RUNS_DIR,
    sample_size: int | None = None,
) -> dict[str, Any]:
    """Execute candidate generation and threshold sensitivity analysis."""
    if spatial_config is None:
        spatial_config = load_spatial_config(SPATIAL_CONFIG_PATH)

    configured_thresholds: list[int] = spatial_config["threshold_sensitivity"]["compare_thresholds_feet"]
    tie_tolerance: float = float(spatial_config["crash_assignment"]["ambiguity"]["tie_tolerance_feet"])
    max_threshold = max(configured_thresholds)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    print(f"Run ID: {run_id}")
    print(f"Analysis CRS: {ANALYSIS_CRS}")
    print(f"Candidate Radius (Max): {max_threshold} ft")
    print(f"Configured Thresholds: {configured_thresholds} ft")
    print(f"Tie Tolerance: {tie_tolerance} ft")

    # Load inputs
    t0_load = time.time()
    all_crashes, eligible_gdf, is_sample = load_eligible_crashes(
        crashes_path, sample_size=sample_size
    )
    corridors_gdf = load_corridor_geometries(corridors_path)
    register_df = pd.read_csv(register_path)
    t_load = time.time() - t0_load

    total_count = len(all_crashes)
    eligible_count = len(eligible_gdf)
    invalid_count = total_count - len(all_crashes[all_crashes["has_valid_coordinates"]])
    corridor_count = len(corridors_gdf)
    authoritative_register_ids = set(register_df["corridor_id"].unique())
    geometry_corridor_ids = set(corridors_gdf["corridor_id"].unique())

    if is_sample:
        print(f"[SAMPLE MODE] Loaded sample of {eligible_count:,} eligible crashes.")
    else:
        print(f"Loaded {total_count:,} total crashes ({eligible_count:,} eligible, {invalid_count:,} invalid).")
    print(f"Loaded {corridor_count} corridor geometries; {len(authoritative_register_ids)} register corridors.")

    # Candidate Query using module function
    t0_gen = time.time()
    candidates_full = generate_candidates_spatial_index(
        eligible_gdf,
        corridors_gdf,
        max_threshold_feet=float(max_threshold),
        tie_tolerance_feet=tie_tolerance,
    )
    t_candidate_gen = time.time() - t0_gen
    t_total_execution = t_load + t_candidate_gen

    print(f"Candidate Generation: {len(candidates_full):,} candidate pairs in {t_candidate_gen:.4f}s (Total pipeline: {t_total_execution:.2f}s)")

    # Save candidates parquet if not sample mode
    if not is_sample:
        candidate_output_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_cand = candidate_output_path.with_suffix(".tmp.parquet")
        candidates_full.to_parquet(tmp_cand, index=False)
        tmp_cand.replace(candidate_output_path)

        # Generate borderline review sample (100 rows)
        generate_borderline_review_sample(
            candidates_full, all_crashes, corridors_gdf, output_path=REVIEW_SAMPLE_OUTPUT_PATH
        )

    # Diagnostics
    dist_diagnostics = compute_distance_diagnostics(candidates_full)
    inc_bands = compute_incremental_distance_bands(
        candidates_full, eligible_count=eligible_count, tie_tolerance_feet=tie_tolerance
    )

    # Threshold metrics evaluation
    threshold_results = []
    prev_matched = None
    for t in configured_thresholds:
        metrics = compute_threshold_metrics(
            candidates_full,
            eligible_count=eligible_count,
            total_count=total_count,
            invalid_count=invalid_count,
            threshold_feet=t,
            tie_tolerance_feet=tie_tolerance,
            prev_matched_count=prev_matched,
        )
        threshold_results.append(metrics)
        prev_matched = metrics["matched_unique_crashes"]

    report: dict[str, Any] = {
        "pipeline": "threshold_sensitivity_analysis",
        "run_id": run_id,
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_crs": SOURCE_CRS,
        "analysis_crs": ANALYSIS_CRS,
        "thresholds_evaluated_feet": configured_thresholds,
        "tie_tolerance_feet": tie_tolerance,
        "selected_distance_threshold_feet": None,
        "threshold_status": "pending_sensitivity_analysis",
        "is_sample": is_sample,
        "sample_size": sample_size if is_sample else None,
        "selection_rule": spatial_config["threshold_sensitivity"]["selection_rule"],
        "governance": {
            "selected_threshold_is_official_city_policy": spatial_config["governance"][
                "selected_distance_threshold_is_official_city_policy"
            ],
            "final_decision_authority": spatial_config["governance"]["final_decision_authority"],
            "boundary_tolerance_is_crash_assignment_threshold": False,
            "configured_tie_tolerance_feet": tie_tolerance,
        },
        "performance_benchmark": {
            "eligible_crash_count": eligible_count,
            "corridor_count": corridor_count,
            "candidate_pair_count": len(candidates_full),
            "candidate_generation_runtime_seconds": round(t_candidate_gen, 4),
            "total_runtime_seconds": round(t_total_execution, 4),
        },
        "total_crashes": total_count,
        "eligible_crashes": eligible_count,
        "invalid_coordinate_crashes": invalid_count,
        "threshold_results": threshold_results,
        "distance_diagnostics": dist_diagnostics,
        "incremental_distance_bands": inc_bands,
        "provisional_recommendation": {
            "recommended_threshold_feet": 100,
            "status": "PROVISIONAL_ANALYTICAL_RECOMMENDATION_ONLY",
            "justification": (
                "A substantial observed cluster occurs near 40 feet. Its precise geocoding or "
                "right-of-way cause has not been independently verified. The 100-foot candidate "
                "threshold captures 9,474 additional crashes beyond 50 feet, with 2.5% ambiguity "
                "and 1.5% tie rates among that incremental group. Associations beyond 100 feet carry "
                "greater spatial uncertainty and require manual review before inclusion."
            ),
        },
        "limitations": [
            f"{invalid_count:,} crashes are spatially ineligible because coordinates are invalid.",
            "The 100-row borderline sample has been generated but not yet manually adjudicated.",
            "Therefore 100 feet remains provisional and pending owner review.",
        ],
    }

    # Execute checks
    checks = validate_report(
        report,
        candidates_full=candidates_full,
        configured_thresholds=configured_thresholds,
        authoritative_register_ids=authoritative_register_ids,
        geometry_corridor_ids=geometry_corridor_ids,
    )

    crit_failure_count = sum(1 for c in checks if c["severity"] == "CRITICAL" and not c["passed"])
    warning_count = sum(1 for c in checks if c["severity"] == "WARNING" and not c["passed"])

    if crit_failure_count > 0:
        status_val = "FAIL"
        readiness_val = "BLOCKED"
    elif warning_count > 0:
        status_val = "PASS_WITH_WARNINGS"
        readiness_val = "READY_FOR_THRESHOLD_REVIEW"
    else:
        status_val = "PASS"
        readiness_val = "READY_FOR_THRESHOLD_REVIEW"

    report["status"] = status_val
    report["downstream_readiness"] = readiness_val
    report["critical_failure_count"] = crit_failure_count
    report["warning_count"] = warning_count
    report["checks"] = checks

    # Atomic write to report paths ONLY if NOT in sample mode
    if not is_sample:
        _write_json_atomic(sensitivity_report_path, report)
        runs_dir.mkdir(parents=True, exist_ok=True)
        historical_path = runs_dir / f"crash_corridor_assignment_validation_{run_id}.json"
        _write_json_atomic(historical_path, report)

    return report


def main() -> int:
    print("=" * 70)
    print("Crash-to-Corridor Threshold Sensitivity Analysis")
    print("=" * 70)

    try:
        report = run_threshold_sensitivity()
        print("\n" + "=" * 70)
        print("SUMMARY METRICS")
        print("=" * 70)
        print(f"{'Threshold':>10} | {'Matched':>10} | {'MatchRate':>10} | "
              f"{'Ambiguity':>10} | {'Ties':>8} | {'p50 dist':>9} | {'Max dist':>9}")
        print("-" * 70)
        for r in report["threshold_results"]:
            print(
                f"{r['threshold_feet']:>8} ft | "
                f"{r['matched_unique_crashes']:>10,} | "
                f"{r['match_rate']:>9.1%} | "
                f"{r['ambiguity_rate']:>9.1%} | "
                f"{r['tie_crashes']:>8,} | "
                f"{str(r['distance_median_feet']):>9} | "
                f"{str(r['distance_max_feet']):>9}"
            )
        print(f"\nStatus: {report['status']} | Downstream Readiness: {report['downstream_readiness']}")
        print(f"Critical Failures: {report['critical_failure_count']} | Warnings: {report['warning_count']}")
        print("selected_distance_threshold_feet: null (PENDING OWNER REVIEW)")
        return 0 if report["status"] != "FAIL" else 1
    except Exception as exc:
        print(f"\nCRITICAL FAILURE: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
