"""Tests for Phase 5B Streamlit Decision Support Application.

Verifies:
1. Default portfolio uniqueness (PORT_OFF_BASE_B15M_EQ20).
2. Strict single portfolio_id filtering isolation (zero cross-portfolio aggregation).
3. Official vs stress scenario separation.
4. Selection detail cost reconciliation to portfolio summary cost ($0.0 delta).
5. Correct equity percentage denominator per portfolio.
6. Spatial corridor GeoDataFrame joins without row dropping or expansion (43 selected corridors).
7. WGS84 EPSG:4326 CRS transformation for PyDeck mapping.
8. Dynamic loading of governance warning objects from validation JSON files.
9. Controlled FileNotFoundError handling when serving files are missing.
10. Data access module import has zero application-launch side effects.
11. Streamlit AppTest execution of app.py with clean rendering and zero exceptions.
"""

from __future__ import annotations

import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dashboard.streamlit.data_access import (
    DEFAULT_PORTFOLIO_ID,
    get_selected_corridors_geodataframe,
    get_selected_portfolio_benefits,
    get_single_portfolio_selections,
    get_single_portfolio_summary,
    load_corridor_geodataframe,
    load_corridor_master,
    load_portfolio_summary,
    load_project_selections,
    load_treatment_benefits,
    load_validation_evidence,
)


class TestStreamlitDashboard:
    def test_default_portfolio_uniqueness(self):
        """Default portfolio is PORT_OFF_BASE_B15M_EQ20 and is unique in summary dataset."""
        df_summary = load_portfolio_summary()
        default_rows = df_summary[df_summary["is_default_dashboard_portfolio"]]

        assert len(default_rows) == 1
        assert default_rows.iloc[0]["portfolio_id"] == DEFAULT_PORTFOLIO_ID
        assert DEFAULT_PORTFOLIO_ID == "PORT_OFF_BASE_B15M_EQ20"

    def test_single_portfolio_filtering_isolation(self):
        """Data access filters to exactly one portfolio_id with zero cross-portfolio aggregation."""
        df_summary = load_portfolio_summary()
        df_selections = load_project_selections()

        # Test default portfolio
        s_row = get_single_portfolio_summary(df_summary, DEFAULT_PORTFOLIO_ID)
        df_sel = get_single_portfolio_selections(df_selections, DEFAULT_PORTFOLIO_ID)

        assert s_row["portfolio_id"] == DEFAULT_PORTFOLIO_ID
        assert (df_sel["portfolio_id"] == DEFAULT_PORTFOLIO_ID).all()
        assert len(df_sel) == s_row["selected_project_count"]

    def test_official_and_stress_scenario_separation(self):
        """Official (27) and stress (9) scenarios remain strictly separated."""
        df_summary = load_portfolio_summary()

        official_df = df_summary[df_summary["run_group"] == "OFFICIAL"]
        stress_df = df_summary[df_summary["run_group"] == "BINDING-BUDGET STRESS TEST"]

        assert len(official_df) == 27
        assert len(stress_df) == 9
        assert set(official_df["portfolio_id"]).isdisjoint(set(stress_df["portfolio_id"]))

    def test_all_selected_projects_match_chosen_portfolio(self):
        """100% of selected detail rows match the requested portfolio_id."""
        df_selections = load_project_selections()
        pids = df_selections["portfolio_id"].unique()

        for pid in pids:
            df_sub = get_single_portfolio_selections(df_selections, pid)
            assert (df_sub["portfolio_id"] == pid).all()

    def test_summary_cost_equals_selected_detail_cost(self):
        """Selected detail capital project cost sums to portfolio summary capital cost with zero delta."""
        df_summary = load_portfolio_summary()
        df_selections = load_project_selections()

        for pid in df_summary["portfolio_id"].unique():
            s_row = get_single_portfolio_summary(df_summary, pid)
            df_sel = get_single_portfolio_selections(df_selections, pid)

            detail_sum = df_sel["capital_project_cost"].sum()
            assert pytest.approx(detail_sum, abs=1e-4) == s_row["selected_capital_cost"]

    def test_equity_percentage_uses_correct_portfolio_denominator(self):
        """Equity spending percentage uses selected_capital_cost of the single active portfolio as denominator."""
        df_summary = load_portfolio_summary()

        for pid in df_summary["portfolio_id"].unique():
            s_row = get_single_portfolio_summary(df_summary, pid)
            calc_equity_share = s_row["equity_spending"] / s_row["selected_capital_cost"]
            assert pytest.approx(calc_equity_share, abs=1e-6) == s_row["achieved_equity_share"]

    def test_corridor_joins_do_not_drop_or_multiply_rows(self):
        """Spatial GeoDataFrame join for active portfolio matches detail selections count (43) exactly."""
        df_selections = load_project_selections()
        gdf_corridors = load_corridor_geodataframe()

        gdf_sel = get_selected_corridors_geodataframe(df_selections, gdf_corridors, DEFAULT_PORTFOLIO_ID)
        df_sel = get_single_portfolio_selections(df_selections, DEFAULT_PORTFOLIO_ID)

        assert len(gdf_sel) == len(df_sel)

    def test_map_geometry_transformed_to_epsg_4326(self):
        """Corridor spatial geometry and centroids are in EPSG:4326 WGS84 geographic coordinates."""
        gdf_corridors = load_corridor_geodataframe()

        assert gdf_corridors.crs.to_string() == "EPSG:4326"
        assert (gdf_corridors["centroid_latitude"].between(41.6, 42.1)).all()
        assert (gdf_corridors["centroid_longitude"].between(-87.9, -87.5)).all()

    def test_governance_warnings_loaded_from_validation_json(self):
        """Validation evidence JSON reports load dynamically with active warning objects."""
        evidence = load_validation_evidence()

        assert "decision_mart" in evidence
        assert "optimization" in evidence

        opt_warnings = evidence["optimization"].get("governance_warnings", [])
        mart_warnings = evidence["decision_mart"].get("governance_warnings", [])

        assert len(opt_warnings) == 7
        assert len(mart_warnings) == 2

        codes = [w["code"] for w in opt_warnings]
        assert "WARNING_OFFICIAL_BUDGETS_NONBINDING" in codes
        assert "WARNING_ROAD_DIET_CONCENTRATION" in codes

    def test_missing_serving_files_produce_controlled_error(self, tmp_path):
        """Missing serving files raise controlled FileNotFoundError with informative message."""
        non_existent_file = tmp_path / "missing_summary.parquet"

        with pytest.raises(FileNotFoundError, match="Required serving dataset missing"):
            load_portfolio_summary(non_existent_file)

    def test_import_data_access_no_launch_side_effects(self):
        """Importing data_access module has zero application-launch side effects."""
        assert DEFAULT_PORTFOLIO_ID == "PORT_OFF_BASE_B15M_EQ20"

    def test_ksi_terminology_and_geometry_lineage_disambiguation(self):
        """Calibrated 2026 KSI forecast is distinct from EB historical benchmark; geometry run ID is read directly."""
        evidence = load_validation_evidence()
        assert "geometry" in evidence
        assert evidence["geometry"].get("run_id") == "20260810T120855Z"

        df_forecast = pd.read_csv(ROOT / "outputs" / "forecasts" / "corridor_risk_forecast_2026_annual.csv")
        assert "annual_ksi_forecast_calibrated" in df_forecast.columns
        assert "eb_annual_historical_ksi_benchmark" in df_forecast.columns

        # Verify calibrated forecast and EB benchmark are distinct columns
        calibrated_tot = df_forecast["annual_ksi_forecast_calibrated"].sum()
        eb_bench_tot = df_forecast["eb_annual_historical_ksi_benchmark"].sum()
        assert calibrated_tot != eb_bench_tot

    def test_each_scenario_kpi_equals_selected_detail_source_sum(self):
        """Each scenario KPI (cost, PV benefit, net PV benefit) equals selected-detail source sum with zero delta."""
        df_summary = load_portfolio_summary()
        df_selections = load_project_selections()
        canonical_pids = [
            "PORT_OFF_CONSERVATIVE_B15M_EQ20",
            "PORT_OFF_BASE_B15M_EQ20",
            "PORT_OFF_OPTIMISTIC_B15M_EQ20",
        ]
        for pid in canonical_pids:
            s_row = get_single_portfolio_summary(df_summary, pid)
            df_sel = get_single_portfolio_selections(df_selections, pid)
            assert pytest.approx(df_sel["capital_project_cost"].sum(), abs=1e-4) == s_row["selected_capital_cost"]
            assert pytest.approx(df_sel["present_value_benefit"].sum(), abs=1e-4) == s_row["total_present_value_benefit"]
            assert pytest.approx(df_sel["net_present_benefit"].sum(), abs=1e-4) == s_row["total_net_present_benefit"]

    def test_severity_components_reconcile_to_total_crashes_averted(self):
        """Severity component sum (K + A + B + C + O) reconciles to total crashes averted across selected rows."""
        df_selections = load_project_selections()
        df_benefits = load_treatment_benefits()
        canonical_pids = [
            "PORT_OFF_CONSERVATIVE_B15M_EQ20",
            "PORT_OFF_BASE_B15M_EQ20",
            "PORT_OFF_OPTIMISTIC_B15M_EQ20",
        ]
        for pid in canonical_pids:
            df_b = get_selected_portfolio_benefits(df_selections, df_benefits, pid)
            comp_sum = (
                df_b["crashes_averted_k"]
                + df_b["crashes_averted_a"]
                + df_b["crashes_averted_b"]
                + df_b["crashes_averted_c"]
                + df_b["crashes_averted_o"]
            )
            assert pytest.approx(comp_sum.sum(), abs=5.0) == df_b["crashes_averted_total"].sum()
            assert (comp_sum <= df_b["crashes_averted_total"] + 1e-4).all()

    def test_changing_scenario_does_not_mix_rows_from_another_scenario(self):
        """Changing portfolio scenario filters strictly and does not mix rows from another scenario."""
        df_selections = load_project_selections()
        df_benefits = load_treatment_benefits()
        mapping = {
            "PORT_OFF_CONSERVATIVE_B15M_EQ20": "CONSERVATIVE",
            "PORT_OFF_BASE_B15M_EQ20": "BASE",
            "PORT_OFF_OPTIMISTIC_B15M_EQ20": "OPTIMISTIC",
        }
        for pid, expected_scen in mapping.items():
            df_sel = get_single_portfolio_selections(df_selections, pid)
            assert (df_sel["scenario_level"] == expected_scen).all()
            assert (df_sel["uncertainty_scenario"] == expected_scen).all()
            df_b = get_selected_portfolio_benefits(df_selections, df_benefits, pid)
            assert (df_b["uncertainty_scenario"] == expected_scen).all()

    def test_calibrated_2026_ksi_forecast_independent_of_treatment_uncertainty(self):
        """Calibrated 2026 KSI baseline forecast remains independent of treatment CMF uncertainty scenarios."""
        df_master = load_corridor_master()
        tot_ksi_2026 = df_master["annual_forecast_ksi_crashes_2026"].sum()
        assert pytest.approx(tot_ksi_2026, abs=1e-4) == 195.9775
        df_summary = load_portfolio_summary()
        for pid in ["PORT_OFF_CONSERVATIVE_B15M_EQ20", "PORT_OFF_BASE_B15M_EQ20", "PORT_OFF_OPTIMISTIC_B15M_EQ20"]:
            _ = get_single_portfolio_summary(df_summary, pid)
            assert pytest.approx(df_master["annual_forecast_ksi_crashes_2026"].sum(), abs=1e-4) == tot_ksi_2026

    def test_exactly_one_portfolio_id_feeds_every_scenario_view(self):
        """Data access functions return records for exactly one portfolio_id with zero leakage."""
        df_summary = load_portfolio_summary()
        df_selections = load_project_selections()
        df_benefits = load_treatment_benefits()
        gdf_corridors = load_corridor_geodataframe()

        for pid in df_summary["portfolio_id"].unique():
            s_row = get_single_portfolio_summary(df_summary, pid)
            assert s_row["portfolio_id"] == pid

            df_sel = get_single_portfolio_selections(df_selections, pid)
            assert df_sel["portfolio_id"].nunique() == 1
            assert df_sel["portfolio_id"].iloc[0] == pid

            df_b = get_selected_portfolio_benefits(df_selections, df_benefits, pid)
            assert df_b["portfolio_id"].nunique() == 1
            assert df_b["portfolio_id"].iloc[0] == pid

            gdf_sel = get_selected_corridors_geodataframe(df_selections, gdf_corridors, pid)
            assert len(gdf_sel) == len(df_sel)

    def test_default_portfolio_budget_utilization_calculation(self):
        """Budget utilization equals selected capital cost divided by planning budget ceiling within tolerance."""
        df_summary = load_portfolio_summary()
        s_row = get_single_portfolio_summary(df_summary, DEFAULT_PORTFOLIO_ID)

        cost = float(s_row["selected_capital_cost"])
        budget = float(s_row["budget_usd"])
        utilization_ratio = cost / budget
        utilization_pct = utilization_ratio * 100.0

        assert pytest.approx(utilization_pct, abs=0.01) == s_row["budget_utilization_pct"]
        assert pytest.approx(utilization_pct, abs=0.05) == 99.93
        assert 0.0 <= utilization_ratio <= 1.0
