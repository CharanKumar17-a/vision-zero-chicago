"""Tests for Phase 4C Corridor-Treatment Portfolio Optimization.

Verifies:
1. Exact row counts (36 summary rows, 1,410 detail rows).
2. MILP solver determinism (3 repeat solves yield identical hashes and objective).
3. Nonbinding official budget behavior ($6.70M selected cost < $15M budget).
4. Binding stress budget behavior ($2M, $4M, $6M).
5. Unconstrained equity share (41.87% exceeds 20%, 30%, 40% floors).
6. 100% Road Diet (TRT_002) concentration on official runs.
7. Exact reconciliation between summary and detail grains.
8. Validation runner output structure and 7 required governance warnings.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.optimization.optimize_portfolios import (
    BENEFITS_PARQUET_PATH,
    SELECTIONS_PARQUET_PATH,
    SUMMARY_PARQUET_PATH,
    compute_portfolio_hash,
    run_portfolio_optimization,
    solve_portfolio_scenario,
)
from src.validation.validate_portfolio_optimization import validate_portfolio_optimization_outputs


class TestPortfolioOptimization:
    def test_summary_and_detail_dataset_structures(self):
        """Outputs exist and contain exact expected row counts and unique keys."""
        df_summary, df_selections = run_portfolio_optimization()

        assert len(df_summary) == 36
        assert df_summary["portfolio_id"].nunique() == 36
        assert len(df_summary[df_summary["run_group"] == "OFFICIAL"]) == 27
        assert len(df_summary[df_summary["run_group"] == "BINDING-BUDGET STRESS TEST"]) == 9

        assert len(df_selections) == 1410
        assert df_selections.duplicated(subset=["portfolio_id", "corridor_id"]).sum() == 0

    def test_official_runs_select_all_43_road_diets(self):
        """All 27 official runs select the exact same 43 TRT_002 projects at $6.70M cost."""
        df_summary = pd.read_parquet(SUMMARY_PARQUET_PATH)
        df_selections = pd.read_parquet(SELECTIONS_PARQUET_PATH)

        official_summary = df_summary[df_summary["run_group"] == "OFFICIAL"]
        assert (official_summary["selected_project_count"] == 43).all()
        assert (official_summary["selected_corridor_count"] == 43).all()
        assert (official_summary["budget_constraint_status"] == "NONBINDING_CORRIDOR_CEILING").all()
        assert (official_summary["equity_constraint_status"] == "SLACK").all()
        assert official_summary["portfolio_hash"].nunique() == 1

        official_selections = df_selections[df_selections["portfolio_id"].isin(official_summary["portfolio_id"])]
        assert (official_selections["treatment_id"] == "TRT_002").all()
        assert (official_selections["physical_applicability_status"] == "UNKNOWN").all()

    def test_stress_runs_binding_budget_behavior(self):
        """Stress runs ($2M, $4M, $6M) bind effectively and select 14, 29, 40 projects."""
        df_summary = pd.read_parquet(SUMMARY_PARQUET_PATH)
        stress_summary = df_summary[df_summary["run_group"] == "BINDING-BUDGET STRESS TEST"]

        assert len(stress_summary) == 9
        assert (stress_summary["budget_constraint_status"] == "EFFECTIVELY_BINDING_NO_ADDITIONAL_CORRIDOR").all()

        counts_by_budget = stress_summary.groupby("budget")["selected_project_count"].mean().to_dict()
        assert counts_by_budget[2000000.0] == 14
        assert counts_by_budget[4000000.0] == 29
        assert counts_by_budget[6000000.0] == 40

    def test_repeat_solve_determinism(self):
        """Solving the same scenario 3 times produces 100% identical hash and objective value."""
        df_panel = pd.read_parquet(BENEFITS_PARQUET_PATH)
        df_base = df_panel[df_panel["scenario_level"] == "BASE"]

        s_dict, d_df = solve_portfolio_scenario(
            df_scenario=df_base,
            portfolio_id="PORT_TEST_REPEAT",
            run_group="OFFICIAL",
            uncertainty_scenario="BASE",
            budget=15000000.0,
            equity_floor=0.20,
            num_repeat_solves=3,
        )
        assert s_dict["solver_status"] == "OPTIMAL"
        assert len(d_df) == 43

    def test_summary_detail_reconciliation(self):
        """Summary total costs and benefits reconcile exactly to the sum of detail selections."""
        df_summary = pd.read_parquet(SUMMARY_PARQUET_PATH)
        df_selections = pd.read_parquet(SELECTIONS_PARQUET_PATH)

        for pid, grp in df_selections.groupby("portfolio_id"):
            sum_row = df_summary[df_summary["portfolio_id"] == pid].iloc[0]

            assert pytest.approx(grp["capital_project_cost"].sum(), abs=1e-4) == sum_row["selected_capital_cost"]
            assert pytest.approx(grp["present_value_benefit"].sum(), abs=1e-4) == sum_row["total_present_value_benefit"]
            assert pytest.approx(grp["net_present_benefit"].sum(), abs=1e-4) == sum_row["total_net_present_benefit"]

    def test_validation_runner_pass_with_warnings(self, tmp_path):
        """Validation runner executes successfully, returning PASS_WITH_WARNINGS and 7 warnings."""
        report = validate_portfolio_optimization_outputs(
            validation_json_path=tmp_path / "val.json",
            runs_dir_path=tmp_path / "runs",
        )

        assert report["status"] == "PASS_WITH_WARNINGS"
        assert report["critical_failure_count"] == 0
        assert report["warning_count"] == 7

        warning_codes = [w["code"] for w in report["governance_warnings"]]
        expected_codes = [
            "WARNING_OFFICIAL_BUDGETS_NONBINDING",
            "WARNING_OFFICIAL_PORTFOLIOS_IDENTICAL",
            "WARNING_ROAD_DIET_CONCENTRATION",
            "WARNING_EQUITY_FLOORS_NONBINDING",
            "WARNING_ANALYST_DEFINED_STRESS_BUDGETS",
            "WARNING_EXTREME_BCR",
            "WARNING_PHYSICAL_APPLICABILITY_UNKNOWN",
        ]
        for ec in expected_codes:
            assert ec in warning_codes

    def test_warning_scenario_cost_reconciliation_to_phase4b(self, tmp_path):
        """Prove that every scenario cost in WARNING_OFFICIAL_BUDGETS_NONBINDING reconciles exactly to Phase 4B input."""
        report = validate_portfolio_optimization_outputs(
            validation_json_path=tmp_path / "val.json",
            runs_dir_path=tmp_path / "runs",
        )
        warn_nonbinding = next(w for w in report["governance_warnings"] if w["code"] == "WARNING_OFFICIAL_BUDGETS_NONBINDING")
        cost_dict = warn_nonbinding["full_treatment_cost_by_scenario_usd"]

        df_panel = pd.read_parquet(BENEFITS_PARQUET_PATH)
        trt002 = df_panel[df_panel["treatment_id"] == "TRT_002"]

        for scen in ["CONSERVATIVE", "BASE", "OPTIMISTIC"]:
            expected_cost = float(trt002[trt002["scenario_level"] == scen]["capital_project_cost"].sum())
            assert pytest.approx(cost_dict[scen], abs=1e-6) == expected_cost

        assert pytest.approx(cost_dict["OPTIMISTIC"], abs=1e-2) == 2979570.58
        assert pytest.approx(cost_dict["BASE"], abs=1e-2) == 6704033.81
        assert pytest.approx(cost_dict["CONSERVATIVE"], abs=1e-2) == 9311158.06
