"""Build Corridor Treatment Benefits & Planning-Scenario Economics (Phase 4B).

Contract: docs/data_quality/cleaning_contract.md, spatial_assignment_contract.md
Config:   config/modeling.yml, project.yml
Decision: D001 (Corridor grain), D005 (Governance authority), D020 (Treatment evidence), D021 (Economic costs)

Performs:
1. Grain: 43 corridors x 3 candidate treatments (TRT_001, TRT_002, TRT_004) x 3 composite uncertainty scenarios (CONSERVATIVE, BASE, OPTIMISTIC) = 387 unique rows.
2. 2026 Pedestrian Baseline Forecast using Beta-Binomial conjugate shrinkage (M=50.0).
3. Target-specific severity allocation:
   - TRT_001 & TRT_004: Pedestrian-involved crash severity shares (K, A, B, C, O, U).
   - TRT_002: All-crash severity shares (K, A, B, C, O, U).
4. CMF confidence bounds calculation:
   - CONSERVATIVE: min(1.0, CMF_point + 1.96 * SE)
   - BASE: CMF_point
   - OPTIMISTIC: max(0.0, CMF_point - 1.96 * SE)
5. Capital project cost & quantities calculation:
   - Location treatments (TRT_001 & TRT_004): Qty = max(1, ceil(miles * density)); Cost = Qty * unit_cost.
   - Corridor-mile treatments (TRT_002): Treated_miles = miles * exposure_share; Cost = Treated_miles * unit_cost_per_mile.
6. Lifecycle present value economic valuation:
   - Discount rate: r = 0.03 (3.0%). Useful life: 20 yrs (TRT_001, TRT_002), 10 yrs (TRT_004).
   - PV_factor = (1 - (1 + r)^(-life)) / r.
   - Present Value Benefit = Annual Monetary Benefit * PV_factor.
   - Net Present Benefit = Present Value Benefit - Capital Project Cost.
   - Benefit Cost Ratio = Present Value Benefit / Capital Project Cost.
7. Governance Labels & Status:
   - physical_applicability_status = UNKNOWN
   - optimization_status = PROVISIONAL_SCENARIO_ONLY
   - Labels: PROVISIONAL_SCENARIO; ENGINEERING_REVIEW_REQUIRED; ANALYST_DEFINED_COST_SCENARIO; ANALYST_DEFINED_ECONOMIC_SCENARIO
"""

from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

import geopandas as gpd
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ASSIGNMENTS_PATH = ROOT / "data" / "interim" / "crash_corridor_assignments.parquet"
CRASHES_CLEAN_PATH = ROOT / "data" / "interim" / "crashes_clean.parquet"
READINESS_PATH = ROOT / "data" / "processed" / "corridor_treatment_readiness.parquet"
ANNUAL_FORECAST_PATH = ROOT / "outputs" / "forecasts" / "corridor_risk_forecast_2026_annual.csv"

OUTPUT_PARQUET_PATH = ROOT / "data" / "processed" / "corridor_treatment_benefits.parquet"
OUTPUT_CSV_PATH = ROOT / "data" / "processed" / "corridor_treatment_benefits.csv"

# USDOT BCA Guidance 2024 Per-Crash Values (2024 USD)
CRASH_COSTS_2024 = {
    "K": 15988000.0,  # Fatal
    "A": 1705100.0,   # Suspected Serious Injury
    "B": 384000.0,    # Suspected Minor Injury
    "C": 204600.0,    # Possible Injury
    "O": 18100.0,     # Property Damage Only
    "U": 0.0,         # Unknown Severity (Preserved count, 0 monetary value)
}

# Candidate Treatment Metadata & CMF Parameters
TREATMENT_METADATA = {
    "TRT_001": {
        "name": "Pedestrian Refuge Islands & Medians",
        "target": "pedestrian",
        "cmf_id": "175",
        "cmf_point": 0.68,
        "cmf_se": 0.035,
        "useful_life_years": 20,
        "scenarios": {
            "CONSERVATIVE": {"exposure_share": 0.25, "density": 1, "unit_cost": 18000.0},
            "BASE":         {"exposure_share": 0.50, "density": 2, "unit_cost": 15000.0},
            "OPTIMISTIC":   {"exposure_share": 0.75, "density": 3, "unit_cost": 12000.0},
        },
    },
    "TRT_002": {
        "name": "Road Diet (4-to-3 Lane Conversion)",
        "target": "total",
        "cmf_id": "3006",
        "cmf_point": 0.71,
        "cmf_se": 0.026,
        "useful_life_years": 20,
        "scenarios": {
            "CONSERVATIVE": {"exposure_share": 0.50, "density": 1.0, "unit_cost": 480000.0},
            "BASE":         {"exposure_share": 0.75, "density": 1.0, "unit_cost": 400000.0},
            "OPTIMISTIC":   {"exposure_share": 1.00, "density": 1.0, "unit_cost": 320000.0},
        },
    },
    "TRT_004": {
        "name": "RRFB at Uncontrolled Marked Pedestrian Crossing",
        "target": "pedestrian",
        "cmf_id": "9024",
        "cmf_point": 0.53,
        "cmf_se": 0.031,
        "useful_life_years": 10,
        "scenarios": {
            "CONSERVATIVE": {"exposure_share": 0.20, "density": 1, "unit_cost": 27000.0},
            "BASE":         {"exposure_share": 0.40, "density": 2, "unit_cost": 22500.0},
            "OPTIMISTIC":   {"exposure_share": 0.60, "density": 4, "unit_cost": 18000.0},
        },
    },
}

REAL_DISCOUNT_RATE = 0.03  # 3.0% real discount rate


def compute_present_value_factor(rate: float, useful_life: int) -> float:
    """Compute exact annuity present value factor."""
    return float((1.0 - (1.0 + rate) ** (-useful_life)) / rate)


def build_pedestrian_severity_shares(
    assignments_path: Path = ASSIGNMENTS_PATH,
    crashes_clean_path: Path = CRASHES_CLEAN_PATH,
    m_ksi: float = 10.0,
    m_non_ksi: float = 50.0,
) -> pd.DataFrame:
    """Compute target-specific shrunken severity shares from pedestrian-involved crashes only."""
    df_assign = pd.read_parquet(assignments_path)
    df_crashes = pd.read_parquet(crashes_clean_path)

    primary = df_assign[df_assign["assignment_status"] == "primary_assigned"].copy()
    merged = pd.merge(primary, df_crashes, on="crash_record_id", how="inner")

    ped = merged[merged["first_crash_type"] == "PEDESTRIAN"].copy()

    # Pooled pedestrian severity baselines across all 43 corridors
    tot_k_ped = (ped["severity_kabco"] == "K").sum()
    tot_a_ped = (ped["severity_kabco"] == "A").sum()
    tot_b_ped = (ped["severity_kabco"] == "B").sum()
    tot_c_ped = (ped["severity_kabco"] == "C").sum()
    tot_o_ped = (ped["severity_kabco"] == "O").sum()
    tot_u_ped = (ped["severity_kabco"] == "U").sum()

    tot_ksi_ped = tot_k_ped + tot_a_ped
    tot_non_ped = tot_b_ped + tot_c_ped + tot_o_ped + tot_u_ped

    pooled_p_k_ped = tot_k_ped / tot_ksi_ped if tot_ksi_ped > 0 else 0.080123
    pooled_p_b_ped = tot_b_ped / tot_non_ped if tot_non_ped > 0 else 0.657377
    pooled_p_c_ped = tot_c_ped / tot_non_ped if tot_non_ped > 0 else 0.188197
    pooled_p_o_ped = tot_o_ped / tot_non_ped if tot_non_ped > 0 else 0.154426
    pooled_p_u_ped = tot_u_ped / tot_non_ped if tot_non_ped > 0 else 0.0

    ped_profiles: List[Dict[str, Any]] = []

    for cid, g in ped.groupby("corridor_id"):
        k = int((g["severity_kabco"] == "K").sum())
        a = int((g["severity_kabco"] == "A").sum())
        b = int((g["severity_kabco"] == "B").sum())
        c = int((g["severity_kabco"] == "C").sum())
        o = int((g["severity_kabco"] == "O").sum())
        u = int((g["severity_kabco"] == "U").sum())
        ksi = k + a
        non_ksi = b + c + o + u

        ped_profiles.append(
            {
                "corridor_id": cid,
                "ped_k": k,
                "ped_a": a,
                "ped_b": b,
                "ped_c": c,
                "ped_o": o,
                "ped_u": u,
                "ped_ksi": ksi,
                "ped_non_ksi": non_ksi,
            }
        )

    df_p = pd.DataFrame(ped_profiles)

    # All 43 corridors
    all_cids = pd.DataFrame({"corridor_id": [f"HCC{i:03d}" for i in range(1, 44)]})
    df_p = all_cids.merge(df_p, on="corridor_id", how="left").fillna(0)

    # Shrunken Pedestrian KSI shares
    w_ksi = df_p["ped_ksi"] / (df_p["ped_ksi"] + m_ksi)
    raw_p_k = np.where(df_p["ped_ksi"] > 0, df_p["ped_k"] / df_p["ped_ksi"], pooled_p_k_ped)
    shrunken_p_k = w_ksi * raw_p_k + (1.0 - w_ksi) * pooled_p_k_ped
    shrunken_p_a = 1.0 - shrunken_p_k

    df_p["ped_share_k_given_ksi"] = shrunken_p_k
    df_p["ped_share_a_given_ksi"] = shrunken_p_a

    # Shrunken Pedestrian Non-KSI shares
    w_non = df_p["ped_non_ksi"] / (df_p["ped_non_ksi"] + m_non_ksi)
    raw_p_b = np.where(df_p["ped_non_ksi"] > 0, df_p["ped_b"] / df_p["ped_non_ksi"], pooled_p_b_ped)
    raw_p_c = np.where(df_p["ped_non_ksi"] > 0, df_p["ped_c"] / df_p["ped_non_ksi"], pooled_p_c_ped)
    raw_p_o = np.where(df_p["ped_non_ksi"] > 0, df_p["ped_o"] / df_p["ped_non_ksi"], pooled_p_o_ped)
    raw_p_u = np.where(df_p["ped_non_ksi"] > 0, df_p["ped_u"] / df_p["ped_non_ksi"], pooled_p_u_ped)

    s_b = w_non * raw_p_b + (1.0 - w_non) * pooled_p_b_ped
    s_c = w_non * raw_p_c + (1.0 - w_non) * pooled_p_c_ped
    s_o = w_non * raw_p_o + (1.0 - w_non) * pooled_p_o_ped
    s_u = w_non * raw_p_u + (1.0 - w_non) * pooled_p_u_ped

    s_tot = s_b + s_c + s_o + s_u
    df_p["ped_share_b_given_non_ksi"] = s_b / s_tot
    df_p["ped_share_c_given_non_ksi"] = s_c / s_tot
    df_p["ped_share_o_given_non_ksi"] = s_o / s_tot
    df_p["ped_share_u_given_non_ksi"] = s_u / s_tot

    return df_p


def build_treatment_benefits_panel(
    readiness_path: Path = READINESS_PATH,
    annual_forecast_path: Path = ANNUAL_FORECAST_PATH,
    assignments_path: Path = ASSIGNMENTS_PATH,
    crashes_clean_path: Path = CRASHES_CLEAN_PATH,
    output_parquet_path: Path = OUTPUT_PARQUET_PATH,
    output_csv_path: Path = OUTPUT_CSV_PATH,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Build the complete 387-row treatment benefits and planning scenario panel."""
    t0 = time.time()

    df_r = pd.read_parquet(readiness_path)
    df_annual = pd.read_csv(annual_forecast_path)

    # Merge annual total forecast & length miles into readiness dataframe
    df_merged = df_r.merge(
        df_annual[["corridor_id", "corridor_length_miles", "annual_total_crashes_forecast"]],
        on="corridor_id",
        how="inner",
    )

    # 1. Beta-Binomial Pedestrian Share Shrinkage
    tot_hist_crashes = df_merged["total_crashes_hist"].sum()
    tot_ped_crashes = df_merged["pedestrian_crashes_tot"].sum()
    p_pooled_ped = tot_ped_crashes / tot_hist_crashes

    m_ped = 50.0
    alpha = p_pooled_ped * m_ped
    beta = (1.0 - p_pooled_ped) * m_ped

    df_merged["posterior_ped_share"] = (df_merged["pedestrian_crashes_tot"] + alpha) / (
        df_merged["total_crashes_hist"] + alpha + beta
    )
    df_merged["pedestrian_forecast_2026"] = (
        df_merged["annual_total_crashes_forecast"] * df_merged["posterior_ped_share"]
    )

    # Pedestrian reconciliation metrics
    total_2026_forecast = float(df_merged["annual_total_crashes_forecast"].sum())
    ped_2026_forecast = float(df_merged["pedestrian_forecast_2026"].sum())
    forecast_weighted_ped_share = ped_2026_forecast / total_2026_forecast
    abs_diff_pct_points = abs(forecast_weighted_ped_share - p_pooled_ped) * 100.0

    ped_reconciliation_summary = {
        "total_historical_crashes": int(tot_hist_crashes),
        "total_historical_pedestrian_crashes": int(tot_ped_crashes),
        "historical_pooled_pedestrian_share": float(p_pooled_ped),
        "total_2026_crash_forecast": total_2026_forecast,
        "total_2026_pedestrian_forecast": ped_2026_forecast,
        "forecast_weighted_pedestrian_share": forecast_weighted_ped_share,
        "absolute_difference_percentage_points": float(abs_diff_pct_points),
        "warning_triggered": bool(abs_diff_pct_points > 2.0),
    }

    # 2. Pedestrian Target Severity Shares
    df_ped_shares = build_pedestrian_severity_shares(assignments_path, crashes_clean_path)
    df_merged = df_merged.merge(df_ped_shares, on="corridor_id", how="inner")

    # 3. Risk Rank & Percentile Calculation (based on 2026 total crash forecast)
    df_merged = df_merged.sort_values("annual_total_crashes_forecast", ascending=False).reset_index(drop=True)
    df_merged["demand_risk_rank"] = df_merged.index + 1
    df_merged["demand_risk_percentile"] = 1.0 - (df_merged["demand_risk_rank"] - 1.0) / len(df_merged)

    # 4. Physical Applicability Screening (Functional-Class & Geometric Proxy per Decision D027)
    # Road Diet (TRT_002) is NOT_APPLICABLE on:
    # - Divided carriageways (MultiLineString e.g. Lake Shore Drive HCC019)
    # - One-way divided pairs (e.g. Garfield Blvd HCC022)
    # - Multi-level / tiered roadways (e.g. Wacker Drive HCC039)
    # - Downtown collector / local grid segments (HCC033-036, HCC040-043)
    corridors_parquet_path = ROOT / "data" / "interim" / "high_crash_corridors.parquet"
    ineligible_trt002_cids: Set[str] = set()
    if corridors_parquet_path.exists():
        gdf_corridors = gpd.read_parquet(corridors_parquet_path)
        # MultiLineString check (Policy B / divided carriageways)
        ineligible_trt002_cids.update(
            gdf_corridors[gdf_corridors.geometry.geom_type == "MultiLineString"]["corridor_id"]
        )
        # Centerline features from spatial snapshot
        centerline_pages = list((ROOT / "data" / "raw" / "spatial").glob("snapshot_*/chicago_street_center_lines_pages/*"))
        if centerline_pages:
            features_by_id: Dict[str, Dict[str, Any]] = {}
            for cp in centerline_pages:
                try:
                    with open(cp, "r", encoding="utf-8") as f:
                        d_page = json.load(f)
                    for feat in d_page.get("features", []):
                        oid = str(feat["properties"]["objectid"])
                        features_by_id[oid] = feat["properties"]
                except Exception:
                    pass

            for _, r_corr in gdf_corridors.iterrows():
                c_id = r_corr["corridor_id"]
                raw_oids = r_corr.get("source_objectids", [])
                if isinstance(raw_oids, str):
                    try:
                        oids = json.loads(raw_oids)
                    except Exception:
                        oids = []
                else:
                    oids = list(raw_oids) if raw_oids is not None else []

                seg_props = [features_by_id.get(str(o)) for o in oids if str(o) in features_by_id]
                if seg_props:
                    classes = set(p.get("class") for p in seg_props if p and p.get("class"))
                    dirs = set(p.get("dir_travel") for p in seg_props if p and p.get("dir_travel"))
                    tiereds = set(p.get("tiered") for p in seg_props if p and p.get("tiered"))

                    is_class_eligible = any(c in {"2", "3"} for c in classes) and not all(c in {"1", "4", "5", "7"} for c in classes)
                    is_twoway = "B" in dirs
                    is_not_tiered = "Y" not in tiereds

                    if not (is_class_eligible and is_twoway and is_not_tiered):
                        ineligible_trt002_cids.add(c_id)
        else:
            ineligible_trt002_cids.update({"HCC019", "HCC022", "HCC033", "HCC034", "HCC035", "HCC036", "HCC039", "HCC040", "HCC041", "HCC042", "HCC043"})
    else:
        ineligible_trt002_cids = {"HCC019", "HCC022", "HCC033", "HCC034", "HCC035", "HCC036", "HCC039", "HCC040", "HCC041", "HCC042", "HCC043"}

    # 5. Generate 387 Benefit Scenario Rows
    scenario_rows: List[Dict[str, Any]] = []

    for _, row in df_merged.iterrows():
        cid = row["corridor_id"]
        c_name = row["corridor_name"]
        length_miles = float(row["corridor_length_miles"])
        eq_flag = bool(row["equity_classification_A_weighted_ge_0_75"])
        rank = int(row["demand_risk_rank"])
        pctile = float(row["demand_risk_percentile"])

        # All-crash shrunken shares
        share_k_all = float(row["share_k_given_ksi"])
        share_a_all = float(row["share_a_given_ksi"])
        share_b_all = float(row["share_b_given_non_ksi"])
        share_c_all = float(row["share_c_given_non_ksi"])
        share_o_all = float(row["share_o_given_non_ksi"])
        share_u_all = float(row["share_u_given_non_ksi"])

        # Pedestrian shrunken shares
        share_k_ped = float(row["ped_share_k_given_ksi"])
        share_a_ped = float(row["ped_share_a_given_ksi"])
        share_b_ped = float(row["ped_share_b_given_non_ksi"])
        share_c_ped = float(row["ped_share_c_given_non_ksi"])
        share_o_ped = float(row["ped_share_o_given_non_ksi"])
        share_u_ped = float(row["ped_share_u_given_non_ksi"])

        for trt_id, meta in TREATMENT_METADATA.items():
            cmf_p = float(meta["cmf_point"])
            cmf_se = float(meta["cmf_se"])
            life_yrs = int(meta["useful_life_years"])
            pv_fac = compute_present_value_factor(REAL_DISCOUNT_RATE, life_yrs)

            # Determine Physical Applicability Status (Decision D027)
            # TRT_002 is NOT_APPLICABLE on non-arterial, one-way, tiered, or divided corridors.
            # All other eligible treatments remain UNKNOWN pending CDOT engineering field survey.
            if trt_id == "TRT_002" and cid in ineligible_trt002_cids:
                applicability_status = "NOT_APPLICABLE"
            else:
                applicability_status = "UNKNOWN"

            # Target baseline forecast
            if meta["target"] == "pedestrian":
                rel_forecast = float(row["pedestrian_forecast_2026"])
                sh_k, sh_a, sh_b, sh_c, sh_o, sh_u = (
                    share_k_ped, share_a_ped, share_b_ped, share_c_ped, share_o_ped, share_u_ped
                )
            else:
                rel_forecast = float(row["annual_total_crashes_forecast"])
                sh_k, sh_a, sh_b, sh_c, sh_o, sh_u = (
                    share_k_all, share_a_all, share_b_all, share_c_all, share_o_all, share_u_all
                )

            # Target-specific KSI share:
            # Pedestrian treatments use pedestrian-specific KSI proportion (~17.5%)
            # Total-crash treatments use all-crash KSI proportion (~2.0%)
            # This ensures severity allocation matches the crash population being treated.
            if meta["target"] == "pedestrian":
                ped_tot_hist = float(row["pedestrian_crashes_tot"])
                ped_ksi_hist = float(row["pedestrian_crashes_ksi"])
                p_ksi = ped_ksi_hist / ped_tot_hist if ped_tot_hist > 0 else 0.175453
            else:
                p_ksi = float(row["ksi_crashes_hist"]) / float(row["total_crashes_hist"]) if row["total_crashes_hist"] > 0 else 0.020432

            for sc_name, sc_params in meta["scenarios"].items():
                exp_share = float(sc_params["exposure_share"])
                unit_cost = float(sc_params["unit_cost"])
                density = float(sc_params["density"])

                # CMF Confidence Bounds Calculation
                if sc_name == "CONSERVATIVE":
                    cmf_val = min(1.0, cmf_p + 1.96 * cmf_se)
                elif sc_name == "OPTIMISTIC":
                    cmf_val = max(0.0, cmf_p - 1.96 * cmf_se)
                else:  # BASE
                    cmf_val = cmf_p

                elig_crashes = rel_forecast * exp_share
                averted_tot = elig_crashes * (1.0 - cmf_val)

                # Severity allocation of averted crashes (exact double-precision sum)
                av_k = averted_tot * p_ksi * sh_k
                av_a = averted_tot * p_ksi * sh_a
                av_b = averted_tot * (1.0 - p_ksi) * sh_b
                av_c = averted_tot * (1.0 - p_ksi) * sh_c
                av_o = averted_tot * (1.0 - p_ksi) * sh_o
                av_u = averted_tot * (1.0 - p_ksi) * sh_u

                # Exact sum to eliminate float rounding drift
                averted_tot_reconciled = av_k + av_a + av_b + av_c + av_o + av_u

                annual_monetary_ben = (
                    av_k * CRASH_COSTS_2024["K"]
                    + av_a * CRASH_COSTS_2024["A"]
                    + av_b * CRASH_COSTS_2024["B"]
                    + av_c * CRASH_COSTS_2024["C"]
                    + av_o * CRASH_COSTS_2024["O"]
                )

                # Quantities and Capital Cost
                if trt_id == "TRT_002":
                    treated_miles = length_miles * exp_share
                    install_qty = round(treated_miles, 6)
                    cap_cost = treated_miles * unit_cost
                else:
                    install_qty = max(1, math.ceil(length_miles * density))
                    cap_cost = float(install_qty * unit_cost)

                pv_benefit = annual_monetary_ben * pv_fac
                net_pv_benefit = pv_benefit - cap_cost
                bcr = pv_benefit / cap_cost if cap_cost > 0 else 0.0

                scenario_rows.append(
                    {
                        "corridor_id": cid,
                        "corridor_name": c_name,
                        "treatment_id": trt_id,
                        "treatment_name": meta["name"],
                        "scenario_level": sc_name,
                        "demand_risk_rank": rank,
                        "demand_risk_percentile": round(pctile, 6),
                        "physical_applicability_status": applicability_status,
                        "optimization_status": "PROVISIONAL_SCENARIO_ONLY",
                        "relevant_forecast_crashes": round(rel_forecast, 6),
                        "eligible_crash_exposure_share": round(exp_share, 6),
                        "eligible_crashes_total": round(elig_crashes, 6),
                        "cmf_id": meta["cmf_id"],
                        "cmf": round(cmf_val, 6),
                        "cmf_standard_error": round(cmf_se, 6),
                        "crashes_averted_total": round(averted_tot_reconciled, 6),
                        "crashes_averted_k": round(av_k, 6),
                        "crashes_averted_a": round(av_a, 6),
                        "crashes_averted_b": round(av_b, 6),
                        "crashes_averted_c": round(av_c, 6),
                        "crashes_averted_o": round(av_o, 6),
                        "crashes_averted_unknown": round(av_u, 6),
                        "annual_monetary_benefit": round(annual_monetary_ben, 4),
                        "useful_life_years": life_yrs,
                        "real_discount_rate": REAL_DISCOUNT_RATE,
                        "present_value_factor": round(pv_fac, 6),
                        "present_value_benefit": round(pv_benefit, 4),
                        "installation_density": round(density, 6),
                        "installation_quantity": install_qty,
                        "unit_cost": round(unit_cost, 4),
                        "capital_project_cost": round(cap_cost, 4),
                        "net_present_benefit": round(net_pv_benefit, 4),
                        "benefit_cost_ratio": round(bcr, 6),
                        "equity_area_flag": eq_flag,
                        "required_governance_labels": (
                            "PROVISIONAL_SCENARIO; ENGINEERING_REVIEW_REQUIRED; "
                            "ANALYST_DEFINED_COST_SCENARIO; ANALYST_DEFINED_ECONOMIC_SCENARIO"
                        ),
                    }
                )

    df_benefits = pd.DataFrame(scenario_rows).sort_values(["corridor_id", "treatment_id", "scenario_level"]).reset_index(drop=True)

    output_parquet_path.parent.mkdir(parents=True, exist_ok=True)
    df_benefits.to_parquet(output_parquet_path, index=False)
    df_benefits.to_csv(output_csv_path, index=False)

    exec_time = time.time() - t0
    print(f"Saved treatment benefits parquet to {output_parquet_path}")
    print(f"Saved treatment benefits CSV to {output_csv_path}")
    print(f"Built {len(df_benefits)} scenario rows in {exec_time:.2f} seconds.")

    return df_benefits, ped_reconciliation_summary


def main() -> int:
    print("=" * 70)
    print("Build Corridor Treatment Benefits & Planning Scenarios (Phase 4B)")
    print("=" * 70)

    try:
        df_b, ped_summary = build_treatment_benefits_panel()
        print("\n" + "=" * 70)
        print("PEDESTRIAN BASELINE RECONCILIATION SUMMARY")
        print("=" * 70)
        print(f"Historical Pooled Pedestrian Share  : {ped_summary['historical_pooled_pedestrian_share']:.6f}")
        print(f"Total 2026 Total Crash Forecast     : {ped_summary['total_2026_crash_forecast']:,.2f}")
        print(f"Total 2026 Pedestrian Crash Forecast: {ped_summary['total_2026_pedestrian_forecast']:,.2f}")
        print(f"Forecast-Weighted Pedestrian Share  : {ped_summary['forecast_weighted_pedestrian_share']:.6f}")
        print(f"Absolute Difference                 : {ped_summary['absolute_difference_percentage_points']:.4f} percentage points")
        print(f"Warning Triggered                   : {ped_summary['warning_triggered']}")

        print("\n" + "=" * 70)
        print("SCENARIO PANEL RECONCILIATION SUMMARY")
        print("=" * 70)
        print(f"Total Unique Scenario Rows Built    : {len(df_b)} (expected 387)")
        print(f"Base Scenario Total PV Benefit      : ${df_b[df_b['scenario_level']=='BASE']['present_value_benefit'].sum():,.2f}")
        print(f"Base Scenario Total Capital Cost    : ${df_b[df_b['scenario_level']=='BASE']['capital_project_cost'].sum():,.2f}")
        print(f"Base Scenario Total Net PV Benefit  : ${df_b[df_b['scenario_level']=='BASE']['net_present_benefit'].sum():,.2f}")
        return 0
    except Exception as exc:
        print(f"\nCRITICAL FAILURE: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
