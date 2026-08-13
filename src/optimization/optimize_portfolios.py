"""Optimize Corridor-Treatment Portfolios under Planning Budgets & Equity Floors (Phase 4C).

Contract: docs/data_quality/cleaning_contract.md, spatial_assignment_contract.md
Config:   config/modeling.yml, project.yml
Decision: D001 (Corridor grain), D004 (Analytical scope), D005 (Governance authority), D021 (Economic costs)

Performs MILP portfolio optimization using scipy.optimize.milp:
1. Scenario Panel: Reads 387 candidate rows from Phase 4B panel data/processed/corridor_treatment_benefits.parquet.
2. MILP Solver Formulation:
   - Objective: Maximize total present_value_benefit (c = -present_value_benefit).
   - Constraints:
     a. At most 1 treatment per corridor.
     b. Capital project cost <= budget.
     c. Equity spending >= equity_floor * total capital project cost.
     d. Selected project count >= 1.
3. Repeat-Solve Determinism:
   - Solves each scenario 3 times to verify identical binary selections, portfolio hash, and objective value.
4. Run Groups:
   - A. OFFICIAL: 3 uncertainty scenarios (CONSERVATIVE, BASE, OPTIMISTIC) x 3 budgets ($15M, $25M, $40M) x 3 equity floors (20%, 30%, 40%) = 27 runs.
   - B. BINDING-BUDGET STRESS TEST: BASE uncertainty x 3 budgets ($2M, $4M, $6M) x 3 equity floors (20%, 30%, 40%) = 9 runs.
5. Output Datasets:
   - data/processed/portfolio_scenario_summary.parquet & .csv (36 summary rows)
   - data/processed/portfolio_project_selections.parquet & .csv (1,410 detail rows)
"""

from __future__ import annotations

import hashlib
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd
from scipy.optimize import Bounds, LinearConstraint, milp

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

BENEFITS_PARQUET_PATH = ROOT / "data" / "processed" / "corridor_treatment_benefits.parquet"

SUMMARY_PARQUET_PATH = ROOT / "data" / "processed" / "portfolio_scenario_summary.parquet"
SUMMARY_CSV_PATH = ROOT / "data" / "processed" / "portfolio_scenario_summary.csv"
SELECTIONS_PARQUET_PATH = ROOT / "data" / "processed" / "portfolio_project_selections.parquet"
SELECTIONS_CSV_PATH = ROOT / "data" / "processed" / "portfolio_project_selections.csv"

# Official Scenarios: 3 uncertainty x 3 budgets x 3 equity floors = 27 runs
OFFICIAL_UNCERTAINTIES = ["CONSERVATIVE", "BASE", "OPTIMISTIC"]
OFFICIAL_BUDGETS = [15000000.0, 25000000.0, 40000000.0]
OFFICIAL_EQUITY_FLOORS = [0.20, 0.30, 0.40]

# Stress Scenarios: BASE uncertainty x 3 budgets x 3 equity floors = 9 runs
STRESS_UNCERTAINTIES = ["BASE"]
STRESS_BUDGETS = [2000000.0, 4000000.0, 6000000.0]
STRESS_EQUITY_FLOORS = [0.20, 0.30, 0.40]

# Minimum Benefit-Cost Ratio (BCR) candidate eligibility threshold
# Candidates with BCR < 1.0 are un-economic (costs exceed present value of safety benefits) and are excluded prior to optimization.
# Reference: Decision Log entry D023.
MIN_ELIGIBLE_BCR = 1.0

OFFICIAL_GOVERNANCE_LABELS = "OFFICIAL_BUDGET_SCENARIO; PROVISIONAL_PORTFOLIO_SCENARIO; ENGINEERING_REVIEW_REQUIRED"
STRESS_GOVERNANCE_LABELS = "ANALYST_DEFINED_BINDING_BUDGET_STRESS_TEST; PROVISIONAL_PORTFOLIO_SCENARIO; ENGINEERING_REVIEW_REQUIRED"


def compute_portfolio_hash(selected_keys: List[Tuple[str, str]]) -> str:
    """Compute deterministic SHA-256 hash of selected (corridor_id, treatment_id) tuples."""
    sorted_keys = sorted(selected_keys, key=lambda k: (k[0], k[1]))
    key_str = "|".join([f"{cid}:{tid}" for cid, tid in sorted_keys])
    return hashlib.sha256(key_str.encode("utf-8")).hexdigest()


def solve_single_milp(
    c: np.ndarray,
    costs: np.ndarray,
    equity_flags: np.ndarray,
    corridors: np.ndarray,
    unique_corridors: List[str],
    budget: float,
    equity_floor: float,
) -> Tuple[np.ndarray, int, str]:
    """Execute single scipy.optimize.milp call.

    Objective: Maximize benefit sum(pv_benefit * x) <=> Minimize -sum(pv_benefit * x)
    Constraints:
      1. At most 1 treatment per corridor: sum_{t in corridor_c} x_i <= 1
      2. Capital cost ceiling: sum(cost * x) <= budget
      3. Equity floor: sum(cost * (equity_floor - equity_flag) * x) <= 0
      4. At least 1 project selected: sum(x) >= 1
    """
    n = len(c)

    # 1. Corridor constraint matrix: len(unique_corridors) x n
    A_corr = np.zeros((len(unique_corridors), n))
    for i, corr in enumerate(unique_corridors):
        A_corr[i, corridors == corr] = 1.0

    # 2. Budget constraint matrix: 1 x n
    A_budget = costs.reshape(1, -1)

    # 3. Equity constraint matrix: 1 x n
    # cost * equity_flag * x >= equity_floor * cost * x <=> cost * (equity_floor - equity_flag) * x <= 0
    A_equity = (costs * (equity_floor - equity_flags)).reshape(1, -1)

    # 4. Minimum 1 project constraint: 1 x n
    A_min1 = np.ones((1, n))

    A = np.vstack([A_corr, A_budget, A_equity, A_min1])

    lb = np.concatenate([
        np.full(len(unique_corridors), -np.inf),
        np.array([-np.inf]),
        np.array([-np.inf]),
        np.array([1.0]),
    ])
    ub = np.concatenate([
        np.ones(len(unique_corridors)),
        np.array([budget]),
        np.array([0.0]),
        np.array([np.inf]),
    ])

    constraints = LinearConstraint(A, lb, ub)
    integrality = np.ones(n)  # binary variables
    bounds = Bounds(0, 1)

    res = milp(c=c, integrality=integrality, bounds=bounds, constraints=constraints)
    return res.x, res.status, res.message


def solve_portfolio_scenario(
    df_scenario: pd.DataFrame,
    portfolio_id: str,
    run_group: str,
    uncertainty_scenario: str,
    budget: float,
    equity_floor: float,
    num_repeat_solves: int = 3,
) -> Tuple[Dict[str, Any], pd.DataFrame]:
    """Formulate, solve with repeat determinism, and summarize single portfolio scenario."""
    df_scen = df_scenario.reset_index(drop=True).copy()
    initial_candidate_count = len(df_scen)
    df_scen = df_scen[df_scen["benefit_cost_ratio"] >= MIN_ELIGIBLE_BCR].reset_index(drop=True)
    excluded_bcr_candidate_count = int(initial_candidate_count - len(df_scen))
    n = len(df_scen)

    c = -df_scen["present_value_benefit"].values
    costs = df_scen["capital_project_cost"].values
    equity_flags = df_scen["equity_area_flag"].values.astype(float)
    corridors = df_scen["corridor_id"].values
    unique_corridors = sorted(list(set(corridors)))

    # Execute Repeat-Solve Determinism Test
    solves_x: List[np.ndarray] = []
    solves_status: List[int] = []
    solves_msg: List[str] = []
    solves_hash: List[str] = []
    solves_obj: List[float] = []

    for _ in range(num_repeat_solves):
        x, status, msg = solve_single_milp(
            c=c,
            costs=costs,
            equity_flags=equity_flags,
            corridors=corridors,
            unique_corridors=unique_corridors,
            budget=budget,
            equity_floor=equity_floor,
        )
        selected_idx = np.where(x > 0.5)[0]
        sel_keys = [(df_scen.iloc[idx]["corridor_id"], df_scen.iloc[idx]["treatment_id"]) for idx in selected_idx]
        p_hash = compute_portfolio_hash(sel_keys)
        obj_val = float(np.sum(df_scen.iloc[selected_idx]["present_value_benefit"].values))

        solves_x.append(x)
        solves_status.append(status)
        solves_msg.append(msg)
        solves_hash.append(p_hash)
        solves_obj.append(obj_val)

    # Verify Repeat-Solve Determinism
    first_hash = solves_hash[0]
    first_obj = solves_obj[0]
    for r_i in range(1, num_repeat_solves):
        if solves_hash[r_i] != first_hash:
            raise RuntimeError(f"Repeat solve hash mismatch for {portfolio_id}: run 0 {first_hash} vs run {r_i} {solves_hash[r_i]}")
        if abs(solves_obj[r_i] - first_obj) > 1e-6:
            raise RuntimeError(f"Repeat solve objective mismatch for {portfolio_id}: run 0 {first_obj} vs run {r_i} {solves_obj[r_i]}")

    final_x = solves_x[0]
    final_status_code = solves_status[0]
    final_msg = solves_msg[0]
    solver_status = "OPTIMAL" if final_status_code == 0 else f"STATUS_{final_status_code}"

    selected_indices = np.where(final_x > 0.5)[0]
    df_selected = df_scen.iloc[selected_indices].copy()

    # Compute rank by present_value_benefit descending within portfolio
    df_selected = df_selected.sort_values(by="present_value_benefit", ascending=False).reset_index(drop=True)
    df_selected["selected_rank_by_benefit"] = np.arange(1, len(df_selected) + 1, dtype=int)

    # Portfolio level metrics
    selected_project_count = len(df_selected)
    selected_corridor_count = df_selected["corridor_id"].nunique()
    selected_capital_cost = float(df_selected["capital_project_cost"].sum())
    budget_slack = float(budget - selected_capital_cost)
    budget_utilization_pct = float((selected_capital_cost / budget) * 100.0)

    equity_spending = float(df_selected[df_selected["equity_area_flag"]]["capital_project_cost"].sum())
    achieved_equity_share = float(equity_spending / selected_capital_cost) if selected_capital_cost > 0 else 0.0

    total_present_value_benefit = float(df_selected["present_value_benefit"].sum())
    total_net_present_benefit = float(df_selected["net_present_benefit"].sum())
    portfolio_bcr = float(total_present_value_benefit / selected_capital_cost) if selected_capital_cost > 0 else 0.0
    maximum_individual_bcr = float(df_selected["benefit_cost_ratio"].max()) if len(df_selected) > 0 else 0.0

    road_diet_df = df_selected[df_selected["treatment_id"] == "TRT_002"]
    road_diet_project_count = len(road_diet_df)
    road_diet_project_share = float(road_diet_project_count / selected_project_count) if selected_project_count > 0 else 0.0
    road_diet_spending_share = float(road_diet_df["capital_project_cost"].sum() / selected_capital_cost) if selected_capital_cost > 0 else 0.0

    physical_applicability_unknown_count = int((df_selected["physical_applicability_status"] == "UNKNOWN").sum())
    portfolio_hash = first_hash

    # Determine budget constraint status
    total_scenario_corridors = len(unique_corridors)
    unselected_corridors = set(unique_corridors) - set(df_selected["corridor_id"].unique())

    if len(unselected_corridors) == 0:
        budget_constraint_status = "NONBINDING_CORRIDOR_CEILING"
    else:
        # Cost of minimum candidate project among unselected corridors
        unselected_df = df_scen[df_scen["corridor_id"].isin(unselected_corridors)]
        min_unselected_cost = float(unselected_df["capital_project_cost"].min())
        if budget_slack < min_unselected_cost - 1e-6:
            budget_constraint_status = "EFFECTIVELY_BINDING_NO_ADDITIONAL_CORRIDOR"
        elif abs(budget_slack) <= 1e-6:
            budget_constraint_status = "BINDING_NUMERIC_TOLERANCE"
        else:
            budget_constraint_status = "SLACK"

    # Determine equity constraint status
    if abs(achieved_equity_share - equity_floor) <= 1e-6:
        equity_constraint_status = "BINDING"
    else:
        equity_constraint_status = "SLACK"

    # Determine limiting constraint
    if budget_constraint_status not in ["NONBINDING_CORRIDOR_CEILING", "SLACK"]:
        limiting_constraint = f"BUDGET ({budget_constraint_status})"
    elif equity_constraint_status == "BINDING":
        limiting_constraint = f"EQUITY ({equity_constraint_status})"
    elif budget_constraint_status == "NONBINDING_CORRIDOR_CEILING":
        limiting_constraint = "NONE (NONBINDING_CORRIDOR_CEILING)"
    else:
        limiting_constraint = "NONE (SLACK)"

    governance_labels = OFFICIAL_GOVERNANCE_LABELS if run_group == "OFFICIAL" else STRESS_GOVERNANCE_LABELS

    summary_dict = {
        "portfolio_id": portfolio_id,
        "run_group": run_group,
        "uncertainty_scenario": uncertainty_scenario,
        "budget": budget,
        "equity_floor": equity_floor,
        "solver_status": solver_status,
        "solver_message": final_msg,
        "objective_name": "total_present_value_benefit",
        "selected_project_count": selected_project_count,
        "selected_corridor_count": selected_corridor_count,
        "selected_capital_cost": selected_capital_cost,
        "budget_slack": budget_slack,
        "budget_utilization_pct": budget_utilization_pct,
        "equity_spending": equity_spending,
        "achieved_equity_share": achieved_equity_share,
        "total_present_value_benefit": total_present_value_benefit,
        "total_net_present_benefit": total_net_present_benefit,
        "portfolio_bcr": portfolio_bcr,
        "maximum_individual_bcr": maximum_individual_bcr,
        "road_diet_project_count": road_diet_project_count,
        "road_diet_project_share": road_diet_project_share,
        "road_diet_spending_share": road_diet_spending_share,
        "physical_applicability_unknown_count": physical_applicability_unknown_count,
        "excluded_bcr_candidate_count": excluded_bcr_candidate_count,
        "portfolio_hash": portfolio_hash,
        "budget_constraint_status": budget_constraint_status,
        "equity_constraint_status": equity_constraint_status,
        "limiting_constraint": limiting_constraint,
        "required_governance_labels": governance_labels,
    }

    # Prepare detail rows
    df_selected["portfolio_id"] = portfolio_id
    df_selected["uncertainty_scenario"] = uncertainty_scenario
    df_selected["evidence_status"] = "DOCUMENTED_CMF_SCENARIO"
    df_selected["required_governance_labels"] = governance_labels

    detail_cols = [
        "portfolio_id",
        "corridor_id",
        "corridor_name",
        "treatment_id",
        "treatment_name",
        "uncertainty_scenario",
        "capital_project_cost",
        "present_value_benefit",
        "net_present_benefit",
        "benefit_cost_ratio",
        "equity_area_flag",
        "physical_applicability_status",
        "evidence_status",
        "selected_rank_by_benefit",
        "required_governance_labels",
    ]
    df_detail = df_selected[detail_cols].copy()

    return summary_dict, df_detail


def run_portfolio_optimization(
    benefits_path: Path = BENEFITS_PARQUET_PATH,
    summary_parquet_path: Path = SUMMARY_PARQUET_PATH,
    summary_csv_path: Path = SUMMARY_CSV_PATH,
    selections_parquet_path: Path = SELECTIONS_PARQUET_PATH,
    selections_csv_path: Path = SELECTIONS_CSV_PATH,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Execute complete Phase 4C portfolio optimization across all 36 runs."""
    t0 = time.time()
    print("=" * 80)
    print("PHASE 4C: PORTFOLIO OPTIMIZATION UNDER PLANNING BUDGETS & EQUITY FLOORS")
    print("=" * 80)

    if not benefits_path.exists():
        raise FileNotFoundError(f"Authoritative Phase 4B panel missing: {benefits_path}")

    df_panel = pd.read_parquet(benefits_path)
    print(f"Loaded Phase 4B panel: {len(df_panel)} rows, {df_panel['corridor_id'].nunique()} corridors.")

    summary_rows: List[Dict[str, Any]] = []
    detail_frames: List[pd.DataFrame] = []

    # 1. OFFICIAL RUNS (27)
    print("\nExecuting Official Run Group (27 runs)...")
    for uncertainty in OFFICIAL_UNCERTAINTIES:
        df_scen = df_panel[df_panel["scenario_level"] == uncertainty]
        for b in OFFICIAL_BUDGETS:
            b_m = int(b / 1e6)
            for eq_f in OFFICIAL_EQUITY_FLOORS:
                eq_pct = int(eq_f * 100)
                portfolio_id = f"PORT_OFF_{uncertainty}_B{b_m}M_EQ{eq_pct}"

                s_dict, d_df = solve_portfolio_scenario(
                    df_scenario=df_scen,
                    portfolio_id=portfolio_id,
                    run_group="OFFICIAL",
                    uncertainty_scenario=uncertainty,
                    budget=b,
                    equity_floor=eq_f,
                )
                summary_rows.append(s_dict)
                detail_frames.append(d_df)

    # 2. STRESS TEST RUNS (9)
    print("Executing Binding-Budget Stress Test Run Group (9 runs)...")
    df_base = df_panel[df_panel["scenario_level"] == "BASE"]
    for b in STRESS_BUDGETS:
        b_m = int(b / 1e6)
        for eq_f in STRESS_EQUITY_FLOORS:
            eq_pct = int(eq_f * 100)
            portfolio_id = f"PORT_STR_BASE_B{b_m}M_EQ{eq_pct}"

            s_dict, d_df = solve_portfolio_scenario(
                df_scenario=df_base,
                portfolio_id=portfolio_id,
                run_group="BINDING-BUDGET STRESS TEST",
                uncertainty_scenario="BASE",
                budget=b,
                equity_floor=eq_f,
            )
            summary_rows.append(s_dict)
            detail_frames.append(d_df)

    df_summary = pd.DataFrame(summary_rows)
    df_selections = pd.concat(detail_frames, ignore_index=True)

    official_excl = int(df_summary[df_summary["run_group"] == "OFFICIAL"]["excluded_bcr_candidate_count"].sum())
    stress_excl = int(df_summary[df_summary["run_group"] == "BINDING-BUDGET STRESS TEST"]["excluded_bcr_candidate_count"].sum())

    # Save outputs
    summary_parquet_path.parent.mkdir(parents=True, exist_ok=True)
    df_summary.to_parquet(summary_parquet_path, index=False)
    df_summary.to_csv(summary_csv_path, index=False)

    selections_parquet_path.parent.mkdir(parents=True, exist_ok=True)
    df_selections.to_parquet(selections_parquet_path, index=False)
    df_selections.to_csv(selections_csv_path, index=False)

    elapsed = time.time() - t0
    print(f"\nCompleted 36 portfolio optimization runs in {elapsed:.2f}s.")
    print(f"Candidate BCR Eligibility Filter (BCR >= {MIN_ELIGIBLE_BCR}): Excluded {official_excl} candidates across 27 official runs, {stress_excl} candidates across 9 stress runs.")
    print(f"Summary dataset: {len(df_summary)} rows -> {summary_parquet_path}")
    print(f"Detail dataset:  {len(df_selections)} rows -> {selections_parquet_path}")
    print("=" * 80)

    return df_summary, df_selections


if __name__ == "__main__":
    run_portfolio_optimization()
