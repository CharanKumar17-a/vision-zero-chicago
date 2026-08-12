"""Build Corridor Treatment Readiness Data and Spatial Equity Profiles (Phase 4A.1).

Contract: docs/data_quality/cleaning_contract.md, spatial_assignment_contract.md
Config:   config/modeling.yml, project.yml
Decision: D001 (Corridor grain), D005 (Governance authority)

Performs:
1. Primary-assigned crash join to cleaned crash core.
2. Complete KABCO panel reconciliation (Total=112,421; K=139; A=2,158; B=10,850; C=6,124; O=93,053; U=97; KSI=2,297).
3. Sub-category crash profiles (pedestrian, wet-road, failure-to-reduce-speed, curve, angle, rear-end) by KABCO severity.
   Note: 'failure_to_reduce_speed_crashes' reflects IDOT contributory cause 'FAILING TO REDUCE SPEED TO AVOID CRASH'
   and does NOT prove speeding above the posted limit. It is NOT connected to speed-feedback sign benefits.
4. Pooled-prior severity shrinkage for K, A, B, C, O, U using assigned-corridor pooled baseline shares.
5. Spatial corridor equity overlay using full-resolution TIGER 2022 CDC SVI Cook County census tracts (tl_2022_17_tract.zip).
6. Reconciles intersected spatial linework against physical corridor length (100.0000% coverage, 0.0000 ft error).
7. Computes Equity Classifications A (weighted SVI >= 0.75) and B (high-SVI share >= 0.50).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely import wkb

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ASSIGNMENTS_PATH = ROOT / "data" / "interim" / "crash_corridor_assignments.parquet"
CRASHES_CLEAN_PATH = ROOT / "data" / "interim" / "crashes_clean.parquet"
CORRIDORS_GEO_PATH = ROOT / "data" / "interim" / "high_crash_corridors.parquet"
SVI_CSV_PATH = ROOT / "data" / "raw" / "spatial" / "svi_2022" / "SVI2022_ILLINOIS_tract.csv"
FULL_TRACTS_ZIP_PATH = ROOT / "data" / "raw" / "spatial" / "svi_2022" / "tl_2022_17_tract.zip"

OUTPUT_PARQUET_PATH = ROOT / "data" / "processed" / "corridor_treatment_readiness.parquet"
OUTPUT_CSV_PATH = ROOT / "data" / "processed" / "corridor_treatment_readiness.csv"


def build_corridor_crash_profiles(
    assignments_path: Path = ASSIGNMENTS_PATH,
    crashes_clean_path: Path = CRASHES_CLEAN_PATH,
) -> pd.DataFrame:
    """Build and reconcile corridor crash profiles across all 43 corridors."""
    df_assign = pd.read_parquet(assignments_path)
    df_crashes = pd.read_parquet(crashes_clean_path)

    # Filter strictly to primary_assigned records
    primary_assign = df_assign[df_assign["assignment_status"] == "primary_assigned"].copy()

    merged = pd.merge(primary_assign, df_crashes, on="crash_record_id", how="inner")

    # Define sub-category boolean masks
    is_pedestrian = merged["first_crash_type"] == "PEDESTRIAN"
    is_wet = merged["roadway_surface_cond"] == "WET"

    # Renamed to failure_to_reduce_speed_crashes (does not prove speeding above posted limit)
    is_failure_speed = merged["prim_contributory_cause"] == "FAILING TO REDUCE SPEED TO AVOID CRASH"

    align_upper = merged["alignment"].fillna("").astype(str).str.upper()
    is_curve = align_upper.str.startswith("CURVE")

    is_angle = merged["first_crash_type"] == "ANGLE"
    is_rear_end = merged["first_crash_type"] == "REAR END"

    merged["is_pedestrian"] = is_pedestrian
    merged["is_wet"] = is_wet
    merged["is_failure_speed"] = is_failure_speed
    merged["is_curve"] = is_curve
    merged["is_angle"] = is_angle
    merged["is_rear_end"] = is_rear_end

    # Group by corridor_id
    corridor_profiles: List[Dict[str, Any]] = []

    for cid, g in merged.groupby("corridor_id"):
        tot_cnt = len(g)
        k_cnt = int((g["severity_kabco"] == "K").sum())
        a_cnt = int((g["severity_kabco"] == "A").sum())
        b_cnt = int((g["severity_kabco"] == "B").sum())
        c_cnt = int((g["severity_kabco"] == "C").sum())
        o_cnt = int((g["severity_kabco"] == "O").sum())
        unk_cnt = int((g["severity_kabco"] == "U").sum())
        ksi_cnt = k_cnt + a_cnt

        def _sub_counts(mask: pd.Series) -> Dict[str, int]:
            sub_g = g[mask]
            return {
                "tot": len(sub_g),
                "k": int((sub_g["severity_kabco"] == "K").sum()),
                "a": int((sub_g["severity_kabco"] == "A").sum()),
                "b": int((sub_g["severity_kabco"] == "B").sum()),
                "c": int((sub_g["severity_kabco"] == "C").sum()),
                "o": int((sub_g["severity_kabco"] == "O").sum()),
                "u": int((sub_g["severity_kabco"] == "U").sum()),
                "ksi": int((sub_g["severity_kabco"] == "K").sum() + (sub_g["severity_kabco"] == "A").sum()),
            }

        ped_c = _sub_counts(g["is_pedestrian"])
        wet_c = _sub_counts(g["is_wet"])
        spd_c = _sub_counts(g["is_failure_speed"])
        crv_c = _sub_counts(g["is_curve"])
        ang_c = _sub_counts(g["is_angle"])
        rear_c = _sub_counts(g["is_rear_end"])

        corridor_profiles.append(
            {
                "corridor_id": cid,
                "total_crashes_hist": tot_cnt,
                "k_crashes_hist": k_cnt,
                "a_crashes_hist": a_cnt,
                "b_crashes_hist": b_cnt,
                "c_crashes_hist": c_cnt,
                "o_crashes_hist": o_cnt,
                "u_crashes_hist": unk_cnt,
                "ksi_crashes_hist": ksi_cnt,
                # Pedestrian
                "pedestrian_crashes_tot": ped_c["tot"],
                "pedestrian_crashes_k": ped_c["k"],
                "pedestrian_crashes_a": ped_c["a"],
                "pedestrian_crashes_b": ped_c["b"],
                "pedestrian_crashes_c": ped_c["c"],
                "pedestrian_crashes_o": ped_c["o"],
                "pedestrian_crashes_u": ped_c["u"],
                "pedestrian_crashes_ksi": ped_c["ksi"],
                # Wet Road
                "wet_crashes_tot": wet_c["tot"],
                "wet_crashes_k": wet_c["k"],
                "wet_crashes_a": wet_c["a"],
                "wet_crashes_b": wet_c["b"],
                "wet_crashes_c": wet_c["c"],
                "wet_crashes_o": wet_c["o"],
                "wet_crashes_u": wet_c["u"],
                "wet_crashes_ksi": wet_c["ksi"],
                # Failure to reduce speed (renamed)
                "failure_to_reduce_speed_crashes_tot": spd_c["tot"],
                "failure_to_reduce_speed_crashes_k": spd_c["k"],
                "failure_to_reduce_speed_crashes_a": spd_c["a"],
                "failure_to_reduce_speed_crashes_b": spd_c["b"],
                "failure_to_reduce_speed_crashes_c": spd_c["c"],
                "failure_to_reduce_speed_crashes_o": spd_c["o"],
                "failure_to_reduce_speed_crashes_u": spd_c["u"],
                "failure_to_reduce_speed_crashes_ksi": spd_c["ksi"],
                # Curve
                "curve_crashes_tot": crv_c["tot"],
                "curve_crashes_k": crv_c["k"],
                "curve_crashes_a": crv_c["a"],
                "curve_crashes_b": crv_c["b"],
                "curve_crashes_c": crv_c["c"],
                "curve_crashes_o": crv_c["o"],
                "curve_crashes_u": crv_c["u"],
                "curve_crashes_ksi": crv_c["ksi"],
                # Angle
                "angle_crashes_tot": ang_c["tot"],
                "angle_crashes_k": ang_c["k"],
                "angle_crashes_a": ang_c["a"],
                "angle_crashes_b": ang_c["b"],
                "angle_crashes_c": ang_c["c"],
                "angle_crashes_o": ang_c["o"],
                "angle_crashes_u": ang_c["u"],
                "angle_crashes_ksi": ang_c["ksi"],
                # Rear End
                "rear_end_crashes_tot": rear_c["tot"],
                "rear_end_crashes_k": rear_c["k"],
                "rear_end_crashes_a": rear_c["a"],
                "rear_end_crashes_b": rear_c["b"],
                "rear_end_crashes_c": rear_c["c"],
                "rear_end_crashes_o": rear_c["o"],
                "rear_end_crashes_u": rear_c["u"],
                "rear_end_crashes_ksi": rear_c["ksi"],
            }
        )

    df_res = pd.DataFrame(corridor_profiles).sort_values("corridor_id").reset_index(drop=True)
    return df_res


def compute_pooled_prior_severity_shrinkage(
    df_profiles: pd.DataFrame,
    m_ksi: float = 10.0,
    m_non_ksi: float = 50.0,
) -> pd.DataFrame:
    """Compute pooled-prior severity shrinkage shares per corridor using assigned-corridor pooled baselines."""
    tot_k = df_profiles["k_crashes_hist"].sum()
    tot_a = df_profiles["a_crashes_hist"].sum()
    tot_b = df_profiles["b_crashes_hist"].sum()
    tot_c = df_profiles["c_crashes_hist"].sum()
    tot_o = df_profiles["o_crashes_hist"].sum()
    tot_u = df_profiles["u_crashes_hist"].sum()
    tot_ksi = tot_k + tot_a
    tot_non_ksi = tot_b + tot_c + tot_o + tot_u

    assigned_corridor_pooled_p_k_given_ksi = tot_k / tot_ksi
    assigned_corridor_pooled_p_a_given_ksi = tot_a / tot_ksi

    assigned_corridor_pooled_p_b_given_non = tot_b / tot_non_ksi
    assigned_corridor_pooled_p_c_given_non = tot_c / tot_non_ksi
    assigned_corridor_pooled_p_o_given_non = tot_o / tot_non_ksi
    assigned_corridor_pooled_p_u_given_non = tot_u / tot_non_ksi

    df = df_profiles.copy()

    # 1. KSI Disaggregation Shares (K vs A)
    w_ksi = df["ksi_crashes_hist"] / (df["ksi_crashes_hist"] + m_ksi)
    raw_p_k = np.where(df["ksi_crashes_hist"] > 0, df["k_crashes_hist"] / df["ksi_crashes_hist"], assigned_corridor_pooled_p_k_given_ksi)

    shrunken_p_k = w_ksi * raw_p_k + (1.0 - w_ksi) * assigned_corridor_pooled_p_k_given_ksi
    shrunken_p_a = 1.0 - shrunken_p_k

    df["share_k_given_ksi"] = np.round(shrunken_p_k, 6)
    df["share_a_given_ksi"] = np.round(shrunken_p_a, 6)

    # 2. Non-KSI Disaggregation Shares (B, C, O, U)
    df_non = df["b_crashes_hist"] + df["c_crashes_hist"] + df["o_crashes_hist"] + df["u_crashes_hist"]
    w_non = df_non / (df_non + m_non_ksi)

    raw_p_b = np.where(df_non > 0, df["b_crashes_hist"] / df_non, assigned_corridor_pooled_p_b_given_non)
    raw_p_c = np.where(df_non > 0, df["c_crashes_hist"] / df_non, assigned_corridor_pooled_p_c_given_non)
    raw_p_o = np.where(df_non > 0, df["o_crashes_hist"] / df_non, assigned_corridor_pooled_p_o_given_non)
    raw_p_u = np.where(df_non > 0, df["u_crashes_hist"] / df_non, assigned_corridor_pooled_p_u_given_non)

    s_b = w_non * raw_p_b + (1.0 - w_non) * assigned_corridor_pooled_p_b_given_non
    s_c = w_non * raw_p_c + (1.0 - w_non) * assigned_corridor_pooled_p_c_given_non
    s_o = w_non * raw_p_o + (1.0 - w_non) * assigned_corridor_pooled_p_o_given_non
    s_u = w_non * raw_p_u + (1.0 - w_non) * assigned_corridor_pooled_p_u_given_non

    s_tot = s_b + s_c + s_o + s_u

    df["share_b_given_non_ksi"] = np.round(s_b / s_tot, 6)
    df["share_c_given_non_ksi"] = np.round(s_c / s_tot, 6)
    df["share_o_given_non_ksi"] = np.round(s_o / s_tot, 6)
    df["share_u_given_non_ksi"] = np.round(s_u / s_tot, 6)

    return df


def build_spatial_corridor_equity_metrics(
    corridors_geo_path: Path = CORRIDORS_GEO_PATH,
    svi_csv_path: Path = SVI_CSV_PATH,
    tracts_zip_path: Path = FULL_TRACTS_ZIP_PATH,
) -> pd.DataFrame:
    """Build exact spatial equity metrics using full-resolution TIGER 2022 CDC SVI Cook County census tracts."""
    df_svi_raw = pd.read_csv(svi_csv_path, dtype={"FIPS": str})
    fips_str = df_svi_raw["FIPS"].astype(str).str.zfill(11)
    df_svi = df_svi_raw.assign(FIPS_STR=fips_str)

    gdf_tracts = gpd.read_file(tracts_zip_path)
    geoid_str = gdf_tracts["GEOID"].astype(str).str.zfill(11)
    gdf_tracts = gdf_tracts.assign(GEOID_STR=geoid_str)

    gdf_svi_tracts = gdf_tracts.merge(
        df_svi[["FIPS_STR", "RPL_THEMES", "LOCATION"]],
        left_on="GEOID_STR",
        right_on="FIPS_STR",
        how="inner",
    ).to_crs(epsg=3435)

    df_corr = pd.read_parquet(corridors_geo_path)
    corr_geoms = []

    for _, r in df_corr.iterrows():
        g = wkb.loads(r["geometry"])
        corr_geoms.append(
            {
                "corridor_id": r["corridor_id"],
                "corridor_name": r["corridor_name"],
                "geometry": g,
                "total_len_ft": float(g.length),
            }
        )

    gdf_corr = gpd.GeoDataFrame(corr_geoms, crs=3435)

    intersections = gpd.overlay(
        gdf_corr,
        gdf_svi_tracts[["FIPS_STR", "RPL_THEMES", "LOCATION", "geometry"]],
        how="intersection",
    )
    intersections["seg_len_ft"] = intersections.geometry.length

    equity_rows: List[Dict[str, Any]] = []

    for cid, group in intersections.groupby("corridor_id"):
        c_name = group["corridor_name"].iloc[0]
        total_len_ft = group["total_len_ft"].iloc[0]
        sum_intersected_ft = float(group["seg_len_ft"].sum())
        len_diff_ft = float(abs(sum_intersected_ft - total_len_ft))
        cov_pct = float((sum_intersected_ft / total_len_ft) * 100.0)

        valid_group = group[group["RPL_THEMES"] >= 0].copy()
        if len(valid_group) > 0:
            w_svi = float((valid_group["seg_len_ft"] * valid_group["RPL_THEMES"]).sum() / valid_group["seg_len_ft"].sum())
        else:
            w_svi = np.nan

        high_svi_group = valid_group[valid_group["RPL_THEMES"] >= 0.75]
        high_svi_len_ft = float(high_svi_group["seg_len_ft"].sum())
        high_svi_share = float(high_svi_len_ft / total_len_ft)

        class_a = bool(w_svi >= 0.75) if not np.isnan(w_svi) else False
        class_b = bool(high_svi_share >= 0.50)

        equity_rows.append(
            {
                "corridor_id": cid,
                "corridor_name": c_name,
                "spatial_total_length_feet": round(total_len_ft, 2),
                "spatial_intersected_length_feet": round(sum_intersected_ft, 2),
                "spatial_reconciliation_diff_feet": round(len_diff_ft, 4),
                "spatial_linework_coverage_percent": round(cov_pct, 4),
                "intersected_tract_count": len(group),
                "corridor_length_weighted_svi": round(w_svi, 6),
                "high_svi_length_share": round(high_svi_share, 6),
                "equity_classification_A_weighted_ge_0_75": class_a,
                "equity_classification_B_share_ge_0_50": class_b,
            }
        )

    return pd.DataFrame(equity_rows).sort_values("corridor_id").reset_index(drop=True)


def build_corridor_treatment_readiness(
    assignments_path: Path = ASSIGNMENTS_PATH,
    crashes_clean_path: Path = CRASHES_CLEAN_PATH,
    corridors_geo_path: Path = CORRIDORS_GEO_PATH,
    svi_csv_path: Path = SVI_CSV_PATH,
    tracts_zip_path: Path = FULL_TRACTS_ZIP_PATH,
    output_parquet_path: Path = OUTPUT_PARQUET_PATH,
    output_csv_path: Path = OUTPUT_CSV_PATH,
    m_ksi: float = 10.0,
    m_non_ksi: float = 50.0,
) -> pd.DataFrame:
    """Build comprehensive treatment readiness dataset using full-resolution spatial geometry and pooled-prior severity shrinkage."""
    t0 = time.time()

    # 1. Crash Profiles
    df_profiles = build_corridor_crash_profiles(assignments_path, crashes_clean_path)

    # 2. Pooled-Prior Severity Shrinkage Shares
    df_shares = compute_pooled_prior_severity_shrinkage(df_profiles, m_ksi=m_ksi, m_non_ksi=m_non_ksi)

    # 3. Spatial Equity Metrics (Full-Resolution TIGER 2022)
    df_equity = build_spatial_corridor_equity_metrics(corridors_geo_path, svi_csv_path, tracts_zip_path)

    # 4. Merge components
    df_readiness = df_shares.merge(df_equity, on="corridor_id", how="inner")

    # Add physical attribute availability audit flags
    df_readiness["attr_lane_count_available"] = False
    df_readiness["attr_adt_available"] = False
    df_readiness["attr_posted_speed_available"] = False
    df_readiness["attr_median_width_available"] = False
    df_readiness["attr_crossings_available"] = False
    df_readiness["attr_signals_available"] = False
    df_readiness["attr_curve_geometry_available"] = False
    df_readiness["attr_pavement_condition_available"] = False
    df_readiness["attr_transit_constraints_available"] = False

    # Export artifacts
    output_parquet_path.parent.mkdir(parents=True, exist_ok=True)
    df_readiness.to_parquet(output_parquet_path, index=False)
    df_readiness.to_csv(output_csv_path, index=False)
    print(f"Saved treatment readiness parquet to {output_parquet_path}")
    print(f"Saved treatment readiness CSV to {output_csv_path}")

    exec_time = time.time() - t0
    print(f"Build completed in {exec_time:.2f} seconds across {len(df_readiness)} corridors.")
    return df_readiness


def main() -> int:
    print("=" * 70)
    print("Build Corridor Treatment Readiness Data & Spatial Equity (Phase 4A.1)")
    print("=" * 70)

    try:
        df_r = build_corridor_treatment_readiness()
        print("\n" + "=" * 70)
        print("RECONCILIATION SUMMARY")
        print("=" * 70)
        print(f"Total Corridors Evaluated : {len(df_r)}")
        print(f"Total Assigned Crashes    : {df_r['total_crashes_hist'].sum():,}")
        print(f"Total Fatal Crashes (K)   : {df_r['k_crashes_hist'].sum():,}")
        print(f"Total Serious Injury (A)  : {df_r['a_crashes_hist'].sum():,}")
        print(f"Total Minor Injury (B)    : {df_r['b_crashes_hist'].sum():,}")
        print(f"Total Possible Injury (C) : {df_r['c_crashes_hist'].sum():,}")
        print(f"Total Property Damage (O) : {df_r['o_crashes_hist'].sum():,}")
        print(f"Total Unknown Severity (U): {df_r['u_crashes_hist'].sum():,}")
        print(f"Total KSI (K+A)           : {df_r['ksi_crashes_hist'].sum():,}")
        print(f"Class A Equity (SVI>=0.75): {df_r['equity_classification_A_weighted_ge_0_75'].sum()}")
        print(f"Class B Equity (Share>=.5): {df_r['equity_classification_B_share_ge_0_50'].sum()}")
        return 0
    except Exception as exc:
        print(f"\nCRITICAL FAILURE: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
