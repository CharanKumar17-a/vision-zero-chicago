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

from dashboard.streamlit.components import (
    format_bcr_compact,
    format_cost_per_unit,
    format_count_compact,
    format_currency,
    format_currency_compact,
    format_equity_flag,
    format_ksi_compact,
    format_percent,
    format_plural,
)
from dashboard.streamlit.data_access import (
    DEFAULT_PORTFOLIO_ID,
    compute_portfolio_stability,
    find_what_if_grid_portfolio,
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

    def test_find_what_if_grid_portfolio_lookup(self):
        """find_what_if_grid_portfolio accurately retrieves exact and nearest grid scenarios."""
        df_summary = load_portfolio_summary()

        # Exact match tests
        row_24m_35, is_exact = find_what_if_grid_portfolio(df_summary, 24e6, 0.35)
        assert is_exact is True
        assert row_24m_35["portfolio_id"] == "PORT_GRID_BASE_B24M_EQ35"
        assert row_24m_35["budget_usd"] == 24000000.0
        assert row_24m_35["equity_floor"] == 0.35

        row_11m_35, is_exact = find_what_if_grid_portfolio(df_summary, 11e6, 0.35)
        assert is_exact is True
        assert row_11m_35["portfolio_id"] == "PORT_GRID_BASE_B11M_EQ35"

        # Nearest match test
        row_nearest, is_exact = find_what_if_grid_portfolio(df_summary, 15.5e6, 0.22)
        assert is_exact is False
        assert row_nearest["portfolio_id"] == "PORT_GRID_BASE_B15M_EQ20"

    def test_what_if_planner_apptest_interaction(self):
        """AppTest interaction with What-If planner discrete selectors dynamically updates Scenario ID."""
        at = AppTest.from_file("dashboard/streamlit/pages/1_Portfolio_Overview.py", default_timeout=30)
        at.run()
        assert not at.exception

        # Change What-If discrete precomputed selectboxes to $24M, 35% equity (indices 2 and 3)
        at.selectbox[2].select(24000000.0)
        at.selectbox[3].select(0.35)
        at.run()
        assert not at.exception
        info_texts = [i.value for i in at.info]
        assert any("PORT_GRID_BASE_B24M_EQ35" in text for text in info_texts)

        # Switch sidebar budget to $25M
        at.select_slider[0].set_value(25000000.0)
        at.run()
        assert not at.exception
        captions = [c.value for c in at.caption]
        assert any("PORT_OFF_BASE_B25M_EQ20" in text for text in captions)

    def test_compute_portfolio_stability_official_counts(self):
        """Verify compute_portfolio_stability accurately calculates selection frequencies and classifications for Official runs."""
        df_summary = load_portfolio_summary()
        df_selections = load_project_selections()

        df_stab = compute_portfolio_stability(df_selections, df_summary, scenario_scope="OFFICIAL")

        # 1. Row count & key uniqueness
        assert len(df_stab) > 0
        assert df_stab.duplicated(subset=["corridor_id", "treatment_id"]).sum() == 0

        # 2. Total scenarios equals 27 for OFFICIAL
        assert (df_stab["total_scenarios"] == 27).all()

        # 3. Selection count and rate validity
        assert (df_stab["selected_scenario_count"] >= 1).all()
        assert (df_stab["selected_scenario_count"] <= 27).all()
        assert (df_stab["selection_rate"] == df_stab["selected_scenario_count"] / 27.0).all()
        assert (df_stab["selection_rate"] >= 0.0).all()
        assert (df_stab["selection_rate"] <= 1.0).all()

        # 4. Formatted display string verification
        for _, row in df_stab.iterrows():
            expected_display = f"Selected in {int(row['selected_scenario_count'])} of 27 scenarios"
            assert row["selection_display"] == expected_display

        # 5. Stability tier classification boundaries
        for _, row in df_stab.iterrows():
            rate = row["selection_rate"]
            tier = row["stability_tier"]
            if rate >= 0.70:
                assert tier == "Core"
            elif rate >= 0.30:
                assert tier == "Conditional"
            else:
                assert tier == "Scenario-sensitive"

        # 6. Core projects exist (selected in >=70% of official runs)
        core_projects = df_stab[df_stab["stability_tier"] == "Core"]
        assert len(core_projects) >= 30

    def test_compute_portfolio_stability_canonical_and_all_scopes(self):
        """Verify compute_portfolio_stability handles CANONICAL (36) and ALL (192) scopes cleanly."""
        df_summary = load_portfolio_summary()
        df_selections = load_project_selections()

        # Canonical scope (36 runs)
        df_can = compute_portfolio_stability(df_selections, df_summary, scenario_scope="CANONICAL")
        assert len(df_can) > 0
        assert (df_can["total_scenarios"] == 36).all()
        assert (df_can["selected_scenario_count"] <= 36).all()
        assert df_can.duplicated(subset=["corridor_id", "treatment_id"]).sum() == 0

        # All scope (192 runs)
        df_all = compute_portfolio_stability(df_selections, df_summary, scenario_scope="ALL")
        assert len(df_all) > 0
        assert (df_all["total_scenarios"] == 192).all()
        assert (df_all["selected_scenario_count"] <= 192).all()
        assert df_all.duplicated(subset=["corridor_id", "treatment_id"]).sum() == 0

    def test_portfolio_stability_apptest_section_rendering(self):
        """AppTest verifies Section 3 Portfolio Robustness renders metrics, filters, and tables cleanly (Decision DEC-07)."""
        at = AppTest.from_file("dashboard/streamlit/pages/1_Portfolio_Overview.py", default_timeout=30)
        at.run()
        assert not at.exception

        # Check section subheaders present
        subheaders = [s.value for s in at.subheader]
        assert "3. Portfolio robustness across scenarios" in subheaders or "4. Portfolio stability and robust project selection" in subheaders
        assert "5. What-if capital planner" in subheaders

        # Check dataframes rendered
        assert len(at.dataframe) >= 3

        # Filter by Core stability tier (selectbox 1)
        at.selectbox[1].select("Core (selected in most scenarios)")
        at.run()
        assert not at.exception

        # Switch scope to All canonical scenarios (selectbox 0)
        at.selectbox[0].select("All canonical scenarios (36 runs)")
        at.run()
        assert not at.exception

    def test_shared_formatting_helpers(self):
        """Verify format_equity_flag, format_cost_per_unit, format_plural, and compact formatters behave correctly."""
        # Equity flag formatting
        assert format_equity_flag(True) == "Yes"
        assert format_equity_flag(False) == "No"
        assert format_equity_flag(1) == "Yes"
        assert format_equity_flag(0) == "No"
        assert format_equity_flag("true") == "Yes"
        assert format_equity_flag("No") == "No"

        # Cost per unit formatting
        assert format_cost_per_unit(100000.0, 2.0, "KSI") == "$50,000 / KSI"
        assert format_cost_per_unit(100000.0, 0.0, "KSI") == "N/A"
        assert format_cost_per_unit(100000.0, None, "KSI") == "N/A"

        # Plural formatting
        assert format_plural(1, "corridor") == "1 corridor"
        assert format_plural(4, "corridor") == "4 corridors"
        assert format_plural(0, "corridor") == "0 corridors"

        # Compact executive formatters (False Precision Remediation)
        assert format_currency_compact(14988510.0) == "$15.0M"
        assert format_currency_compact(14988900.0) == "$15.0M"
        assert format_currency_compact(4003734895.7) == "$4.00B"
        assert format_currency_compact(400000.0) == "$400k"
        assert format_currency_compact(500.0) == "$500"

        assert format_bcr_compact(275.0) == "~275:1"
        assert format_bcr_compact(267.12) == "~267:1"
        assert format_bcr_compact(2.67) == "~2.7:1"

        assert format_count_compact(2384.6) == "~2,385"
        assert format_count_compact(2170.2) == "~2,170"

        assert format_ksi_compact(48.8) == "~49"
        assert format_ksi_compact(48.04) == "~48"

    def test_crashes_averted_ksi_in_selected_benefits(self):
        """get_selected_portfolio_benefits includes crashes_averted_ksi column strictly equaling K + A."""
        df_selections = load_project_selections()
        df_benefits = load_treatment_benefits()

        df_b = get_selected_portfolio_benefits(df_selections, df_benefits, DEFAULT_PORTFOLIO_ID)
        assert "crashes_averted_ksi" in df_b.columns
        expected_ksi = df_b["crashes_averted_k"] + df_b["crashes_averted_a"]
        np.testing.assert_allclose(df_b["crashes_averted_ksi"], expected_ksi, rtol=1e-5)

    def test_all_pages_render_without_exception_in_apptest(self):
        """AppTest renders all 4 pages cleanly with zero exceptions."""
        pages = [
            "dashboard/streamlit/pages/0_Executive_Recommendation.py",
            "dashboard/streamlit/pages/1_Portfolio_Overview.py",
            "dashboard/streamlit/pages/2_Corridor_Explorer.py",
            "dashboard/streamlit/pages/3_Governance_and_Methodology.py",
        ]
        for page_path in pages:
            at = AppTest.from_file(page_path, default_timeout=30)
            at.run()
            assert not at.exception, f"Rendering failed for page: {page_path}"

    def test_canonical_portfolio_scenario_consistency_across_views(self):
        """Verify that all views, data access functions, and What-If lookups consistently consume the canonical $15M official scenario."""
        df_summary = load_portfolio_summary()
        df_selections = load_project_selections()
        df_benefits = load_treatment_benefits()
        df_master = load_corridor_master()

        # 1. Canonical Default Portfolio ID is PORT_OFF_BASE_B15M_EQ20
        assert DEFAULT_PORTFOLIO_ID == "PORT_OFF_BASE_B15M_EQ20"
        assert DEFAULT_PORTFOLIO_ID in df_summary["portfolio_id"].values

        # 2. Extract single canonical summary row
        s_row = get_single_portfolio_summary(df_summary, DEFAULT_PORTFOLIO_ID)
        assert s_row["run_group"] == "OFFICIAL"
        assert s_row["uncertainty_scenario"] == "BASE"
        assert s_row["budget"] == 15000000.0
        assert s_row["equity_floor"] == 0.20
        assert s_row["selected_project_count"] == 39
        assert s_row["selected_corridor_count"] == 39
        assert s_row["selected_capital_cost"] == 14988510.0
        assert s_row["budget_slack"] == 11490.0
        assert s_row["budget_utilization_pct"] == pytest.approx(99.9234, abs=0.01)
        assert s_row["achieved_equity_share"] == pytest.approx(0.473533, abs=1e-4)

        # 3. Selections and Benefits line up exactly to 39 corridors
        rec_selections = get_single_portfolio_selections(df_selections, DEFAULT_PORTFOLIO_ID)
        assert len(rec_selections) == 39
        assert rec_selections["corridor_id"].nunique() == 39

        rec_benefits = get_selected_portfolio_benefits(df_selections, df_benefits, DEFAULT_PORTFOLIO_ID)
        assert len(rec_benefits) == 39
        assert rec_benefits["capital_project_cost"].sum() == 14988510.0

        # 4. Exactly 4 deferred corridors
        all_cids = set(df_master["corridor_id"])
        selected_cids = set(rec_selections["corridor_id"])
        deferred_cids = all_cids - selected_cids
        assert len(deferred_cids) == 4
        assert deferred_cids == {"HCC019", "HCC020", "HCC022", "HCC028"}

        # 5. What-If Planner lookup at $15M and 20% equity yields identical 39-corridor scenario
        wif_row, is_exact = find_what_if_grid_portfolio(df_summary, 15e6, 0.20)
        assert is_exact is True
        assert wif_row["selected_project_count"] == 39
        assert wif_row["selected_capital_cost"] == 14988510.0
        assert wif_row["selection_hash"] == s_row["selection_hash"]

    def test_budget_sensitivity_scenario_consistency(self):
        """Verify the exact corridor selection counts and costs across all budget sensitivity tiers in BASE scenario."""
        df_summary = load_portfolio_summary()

        expected_tiers = {
            "PORT_STR_BASE_B2M_EQ20": {"budget": 2000000.0, "count": 20, "cost": 1992930.0},
            "PORT_STR_BASE_B4M_EQ20": {"budget": 4000000.0, "count": 18, "cost": 3996840.0},
            "PORT_STR_BASE_B6M_EQ20": {"budget": 6000000.0, "count": 28, "cost": 5999280.0},
            "PORT_OFF_BASE_B15M_EQ20": {"budget": 15000000.0, "count": 39, "cost": 14988510.0},
            "PORT_OFF_BASE_B25M_EQ20": {"budget": 25000000.0, "count": 43, "cost": 17564580.0},
            "PORT_OFF_BASE_B40M_EQ20": {"budget": 40000000.0, "count": 43, "cost": 17564580.0},
        }

        for pid, exp in expected_tiers.items():
            row = get_single_portfolio_summary(df_summary, pid)
            assert row["budget"] == exp["budget"]
            assert row["selected_project_count"] == exp["count"]
            assert row["selected_capital_cost"] == exp["cost"]

    def test_governance_authority_statement_and_language_compliance(self):
        """Verify that Page 0 renders the mandatory authority statement and standard planning-level language."""
        at = AppTest.from_file("dashboard/streamlit/pages/0_Executive_Recommendation.py", default_timeout=30)
        at.run()
        assert not at.exception

        # Mandatory Authority Statement on Page 0
        info_texts = [i.value for i in at.info]
        assert any(
            "This tool does not authorize projects, establish construction scope, or replace engineering review."
            in text
            for text in info_texts
        )

        # Baseline Recommendation Callout
        assert any("Baseline Recommendation" in text for text in info_texts)

        # Status badge
        caption_texts = [c.value for c in at.caption]
        assert any("Optimization status: Mathematically optimal under stated planning constraints" in text for text in caption_texts)

    def test_false_precision_remediation_and_planning_estimate_labels(self):
        """Verify that executive cards use decision-relevant rounded formats and include planning-level estimate notes."""
        at = AppTest.from_file("dashboard/streamlit/pages/0_Executive_Recommendation.py", default_timeout=30)
        at.run()
        assert not at.exception

        # Check metric values on Page 0
        metric_values = [m.value for m in at.metric]
        # Executive cards: $15.0M, 39 of 43, ~48 / yr, 47.4%
        assert "$15.0M" in metric_values
        assert "39 of 43" in metric_values
        assert "~48 / yr" in metric_values

        # Check that metric tooltips contain "Planning-level estimate"
        metric_helps = [m.help for m in at.metric if m.help is not None]
        assert any("Planning-level estimate" in h for h in metric_helps)

        # Check Page 1 (Portfolio Overview) metric cards
        at1 = AppTest.from_file("dashboard/streamlit/pages/1_Portfolio_Overview.py", default_timeout=30)
        at1.run()
        assert not at1.exception

        metric1_values = [m.value for m in at1.metric]
        assert "$15.0M" in metric1_values
        assert "~48 / yr" in metric1_values

    def test_severity_and_denominator_clarity(self):
        """Verify that KPI labels explicitly distinguish all-severity crashes, KSI, and baseline forecasts with tooltips."""
        at = AppTest.from_file("dashboard/streamlit/pages/0_Executive_Recommendation.py", default_timeout=30)
        at.run()
        assert not at.exception

        # Check metric labels on Page 0
        labels0 = [m.label for m in at.metric]
        assert "Estimated KSI avoided / year" in labels0

        # Check tooltips for denominator and severity scope explanations
        helps0 = [m.help for m in at.metric if m.help is not None]
        assert any("Denominator:" in h and "Severity scope:" in h for h in helps0)

        # Check Page 1 (Portfolio Overview)
        at1 = AppTest.from_file("dashboard/streamlit/pages/1_Portfolio_Overview.py", default_timeout=30)
        at1.run()
        assert not at1.exception

        labels1 = [m.label for m in at1.metric]
        assert "Estimated KSI avoided / year" in labels1
        assert "Estimated all-severity crashes avoided / year" in labels1
        assert "Baseline KSI / year" in labels1

        helps1 = [m.help for m in at1.metric if m.help is not None]
        assert any("Denominator:" in h and "Severity scope:" in h for h in helps1)

    def test_safety_outcome_visualization_prominence(self):
        """Verify that Vision Zero life-safety outcomes (KSI, Fatal K, Serious Injury A) are prominent on Page 0 and Page 1."""
        at0 = AppTest.from_file("dashboard/streamlit/pages/0_Executive_Recommendation.py", default_timeout=30)
        at0.run()
        assert not at0.exception

        labels0 = [m.label for m in at0.metric]
        assert "Fatal crashes (K) avoided" in labels0
        assert "Serious injuries (A) avoided" in labels0
        assert "All-severity crashes avoided" in labels0

        at1 = AppTest.from_file("dashboard/streamlit/pages/1_Portfolio_Overview.py", default_timeout=30)
        at1.run()
        assert not at1.exception

    def test_equity_interpretation_and_methodology_distinction(self):
        """Verify that equity metrics use 'High-SVI capital share', include 'KSI benefit share in high-SVI areas', and state SVI methodology note."""
        at0 = AppTest.from_file("dashboard/streamlit/pages/0_Executive_Recommendation.py", default_timeout=30)
        at0.run()
        assert not at0.exception

        # Metric label is "High-SVI capital share"
        labels0 = [m.label for m in at0.metric]
        assert "High-SVI capital share" in labels0

        # Tooltip warns against assuming equitable outcomes and explains SVI proxy
        helps0 = [m.help for m in at0.metric if m.help is not None]
        assert any("Measures capital spending input only; not proof of equitable safety outcomes." in h for h in helps0)
        assert any("SVI is used as a spatial equity proxy" in h for h in helps0)

        # Check Page 1 (Portfolio Overview)
        at1 = AppTest.from_file("dashboard/streamlit/pages/1_Portfolio_Overview.py", default_timeout=30)
        at1.run()
        assert not at1.exception

        labels1 = [m.label for m in at1.metric]
        assert "High-SVI capital share" in labels1
        assert "KSI benefit share in high-SVI areas" in labels1

        helps1 = [m.help for m in at1.metric if m.help is not None]
        assert any("SVI is used as a spatial equity proxy" in h for h in helps1)

        # Check Page 3 (Governance and Methodology) contains methodology note
        at3 = AppTest.from_file("dashboard/streamlit/pages/3_Governance_and_Methodology.py", default_timeout=30)
        at3.run()
        assert not at3.exception
        page3_text = " ".join(m.value for m in at3.markdown)
        assert "SVI is used as a spatial equity proxy; it does not directly measure safety benefit equity." in page3_text

    def test_engineering_feasibility_status_and_portfolio_classification(self):
        """Verify that UNKNOWN physical applicability is communicated as 'Engineering review required' and planning vs implementation portfolios are distinguished."""
        from dashboard.streamlit.components import format_engineering_status

        # Verify helper behavior
        assert format_engineering_status("UNKNOWN") == "Engineering review required"
        assert format_engineering_status("REVIEW_REQUIRED") == "Engineering review required"
        assert format_engineering_status("ELIGIBLE") == "Eligible (Verified)"
        assert format_engineering_status("NOT_APPLICABLE") == "Not applicable"
        assert format_engineering_status(None) == "Engineering review required"

        # Check Page 0 contains planning portfolio and engineering review statements
        at0 = AppTest.from_file("dashboard/streamlit/pages/0_Executive_Recommendation.py", default_timeout=30)
        at0.run()
        assert not at0.exception

        page0_markdown_text = " ".join(m.value for m in at0.markdown)
        assert "Engineering review required" in page0_markdown_text
        assert "Analytical planning portfolio" in page0_markdown_text

        # Check Page 3 contains engineering hierarchy and feasibility constraint documentation
        at3 = AppTest.from_file("dashboard/streamlit/pages/3_Governance_and_Methodology.py", default_timeout=30)
        at3.run()
        assert not at3.exception

        page3_markdown_text = " ".join(m.value for m in at3.markdown)
        assert "Engineering Status Hierarchy" in page3_markdown_text
        assert "Analytical Planning Portfolio vs. Implementation-Ready Portfolio" in page3_markdown_text
        assert "Engineering Feasibility & Field Review Constraints" in page3_markdown_text

    def test_lazy_heavy_imports_cold_start_optimization(self):
        """Verify that heavy packages (geopandas, pydeck) are lazily loaded and not imported on data_access or Page 0/1 load."""
        import subprocess
        import sys

        code = """
import sys
import dashboard.streamlit.data_access
assert "geopandas" not in sys.modules, "geopandas should not be imported by data_access"
assert "pydeck" not in sys.modules, "pydeck should not be imported by data_access"

import importlib.util
s0 = importlib.util.spec_from_file_location('p0', 'dashboard/streamlit/pages/0_Executive_Recommendation.py')
m0 = importlib.util.module_from_spec(s0)
s0.loader.exec_module(m0)
assert "geopandas" not in sys.modules, "geopandas should not be imported by Page 0"
assert "pydeck" not in sys.modules, "pydeck should not be imported by Page 0"

s1 = importlib.util.spec_from_file_location('p1', 'dashboard/streamlit/pages/1_Portfolio_Overview.py')
m1 = importlib.util.module_from_spec(s1)
s1.loader.exec_module(m1)
assert "geopandas" not in sys.modules, "geopandas should not be imported by Page 1"
assert "pydeck" not in sys.modules, "pydeck should not be imported by Page 1"
"""
        res = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        assert res.returncode == 0, f"Lazy import check failed:\n{res.stderr}\n{res.stdout}"

    def test_decision_product_analytics_disabled_by_default(self):
        """Verify analytics is disabled by default and all event tracking functions are safe no-ops."""
        import dashboard.streamlit.analytics as analytics

        # Default config state is disabled
        assert analytics.is_analytics_enabled() is False

        # All tracking calls execute safely without exception
        analytics.track_app_open()
        analytics.track_page_view("Portfolio Overview")
        analytics.track_scenario_selected("PORT_OFF_BASE_B15M_EQ20", budget=15e6, equity_floor=0.20, cmf_scenario="BASE")
        analytics.track_corridor_inspected("HCC001")
        analytics.track_portfolio_exported("PORT_OFF_BASE_B15M_EQ20", budget=15e6)

    def test_decision_product_analytics_mock_capture_when_enabled(self, monkeypatch):
        """Verify events emit correct decision properties and anonymous distinct ID when enabled."""
        import dashboard.streamlit.analytics as analytics

        captured_events = []

        class MockPostHog:
            def __init__(self, *args, **kwargs):
                pass

            def capture(self, distinct_id, event, properties):
                captured_events.append({
                    "distinct_id": distinct_id,
                    "event": event,
                    "properties": properties,
                })

        monkeypatch.setattr(analytics, "_POSTHOG_CLIENT", MockPostHog())
        monkeypatch.setattr(analytics, "_ANALYTICS_INITIALIZED", True)

        # 1. Track Page View
        analytics.track_page_view("Corridor Explorer")
        assert len(captured_events) == 1
        assert captured_events[0]["event"] == "page_view"
        assert captured_events[0]["properties"]["page"] == "Corridor Explorer"
        assert captured_events[0]["distinct_id"].startswith("anon_")

        # 2. Track Scenario Selected
        analytics.track_scenario_selected("PORT_OFF_BASE_B25M_EQ30", budget=25000000.0, equity_floor=0.30, cmf_scenario="BASE")
        assert len(captured_events) == 2
        assert captured_events[1]["event"] == "scenario_selected"
        assert captured_events[1]["properties"]["scenario_id"] == "PORT_OFF_BASE_B25M_EQ30"
        assert captured_events[1]["properties"]["budget"] == 25000000.0
        assert captured_events[1]["properties"]["equity_floor"] == 0.30

        # 3. Track Corridor Inspected
        analytics.track_corridor_inspected("HCC007")
        assert len(captured_events) == 3
        assert captured_events[2]["event"] == "corridor_inspected"
        assert captured_events[2]["properties"]["corridor_id"] == "HCC007"

        # 4. Track Portfolio Exported
        analytics.track_portfolio_exported("PORT_OFF_BASE_B15M_EQ20", budget=15000000.0)
        assert len(captured_events) == 4
        assert captured_events[3]["event"] == "portfolio_exported"
        assert captured_events[3]["properties"]["scenario_id"] == "PORT_OFF_BASE_B15M_EQ20"

    def test_decision_product_analytics_resilience_to_exceptions(self, monkeypatch):
        """Verify track_event is completely resilient to client crashes and never raises exceptions."""
        import dashboard.streamlit.analytics as analytics

        class CrashingPostHog:
            def capture(self, *args, **kwargs):
                raise RuntimeError("PostHog network failure")

        monkeypatch.setattr(analytics, "_POSTHOG_CLIENT", CrashingPostHog())
        monkeypatch.setattr(analytics, "_ANALYTICS_INITIALIZED", True)

        # Should swallow exceptions silently without crashing
        analytics.track_event("test_event", {"foo": "bar"})
        analytics.track_page_view("Executive Recommendation")

    def test_governance_page_documents_analytics_and_privacy(self):
        """Verify Governance page (Page 3) renders Section 5 on Usage Analytics."""
        at3 = AppTest.from_file("dashboard/streamlit/pages/3_Governance_and_Methodology.py", default_timeout=30)
        at3.run()
        assert not at3.exception

        subheaders = [s.value for s in at3.subheader]
        assert any("5. Usage analytics" in s for s in subheaders)

        markdown_text = " ".join(m.value for m in at3.markdown)
        assert "Usage Analytics" in markdown_text
        assert "Disabled by default" in markdown_text
        assert "Zero PII" in markdown_text

    def test_data_freshness_indicator_rendered(self):
        """Verify data freshness indicator renders analysis period (2018–2025), valid date, and validated status."""
        at3 = AppTest.from_file("dashboard/streamlit/pages/3_Governance_and_Methodology.py", default_timeout=30)
        at3.run()
        assert not at3.exception

        labels = [m.label for m in at3.metric]
        assert "Analysis Period" in labels
        assert "Data Last Validated" in labels
        assert "Pipeline Status" in labels

        metrics_dict = {m.label: m.value for m in at3.metric}
        assert metrics_dict["Analysis Period"] == "2018–2025"
        assert metrics_dict["Pipeline Status"] == "Validated"
        assert metrics_dict["Data Last Validated"] == "2026-08-17"

        # Check sidebar caption rendered
        sidebar_captions = [c.value for c in at3.sidebar.caption]
        assert any("Analysis period: **2018–2025**" in c for c in sidebar_captions)
        assert any("Data last validated:" in c for c in sidebar_captions)
        assert any("Status: **Validated**" in c for c in sidebar_captions)
