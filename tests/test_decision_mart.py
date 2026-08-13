"""Tests for Phase 5A Decision-Output Mart for Power BI & Streamlit.

Verifies:
1. Decision mart row counts (36 summary, 1,410 detail selections, 43 corridor master, 387 treatment benefits).
2. Exact numeric reconciliation between summary and detail grains.
3. Source lineage cardinalities (387 source candidate rows, 1,410 selection rows, 0 unmatched, candidate reuse expected across portfolios).
4. Cross-portfolio aggregation guardrails (canonical official rows unique per scenario, single default dashboard portfolio, 27 official rows available for constraint comparison).
5. Spatial serving readiness (WGS84 centroids, WKT linework, EPSG:3435 CRS, corridor_id join key).
6. Independent validator runner status PASS_WITH_WARNINGS.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.build_decision_output_mart import (
    BENEFITS_PARQUET,
    CORRIDOR_MASTER_PARQUET,
    SELECTIONS_PARQUET,
    SUMMARY_PARQUET,
    build_decision_output_mart,
)
from src.validation.validate_decision_output_mart import validate_decision_output_mart


class TestDecisionMart:
    def test_decision_mart_row_counts_and_uniqueness(self):
        """Outputs exist and contain exact expected row counts and unique keys."""
        metrics = build_decision_output_mart()

        assert metrics["summary_rows"] == 36
        assert metrics["selections_rows"] == 1212
        assert metrics["master_rows"] == 43
        assert metrics["benefits_rows"] == 387

        df_summary = pd.read_parquet(SUMMARY_PARQUET)
        df_selections = pd.read_parquet(SELECTIONS_PARQUET)
        df_master = pd.read_parquet(CORRIDOR_MASTER_PARQUET)

        assert df_summary["portfolio_id"].nunique() == 36
        assert df_master["corridor_id"].nunique() == 43
        assert df_selections.duplicated(subset=["portfolio_id", "corridor_id"]).sum() == 0

    def test_decision_mart_exact_reconciliation(self):
        """Summary costs and benefits reconcile exactly to the sum of detail project selections."""
        df_summary = pd.read_parquet(SUMMARY_PARQUET)
        df_selections = pd.read_parquet(SELECTIONS_PARQUET)

        for pid, grp in df_selections.groupby("portfolio_id"):
            s_row = df_summary[df_summary["portfolio_id"] == pid].iloc[0]

            assert pytest.approx(grp["capital_project_cost"].sum(), abs=1e-4) == s_row["selected_capital_cost"]
            assert pytest.approx(grp["present_value_benefit"].sum(), abs=1e-4) == s_row["total_present_value_benefit"]
            assert pytest.approx(grp["net_present_benefit"].sum(), abs=1e-4) == s_row["total_net_present_benefit"]

    def test_cross_portfolio_aggregation_guardrails(self):
        """Costs/benefits aggregate per portfolio_id only; canonical official rows are unique per scenario."""
        df_summary = pd.read_parquet(SUMMARY_PARQUET)

        # 27 official rows remain available for constraint analysis
        official_df = df_summary[df_summary["run_group"] == "OFFICIAL"]
        assert len(official_df) == 27

        # Canonical official rows are unique per scenario level (3 total)
        canonical_official = official_df[official_df["is_canonical_portfolio"]]
        assert len(canonical_official) == 3
        assert canonical_official["scenario_level"].nunique() == 3

        # Single default dashboard portfolio
        default_dash = df_summary[df_summary["is_default_dashboard_portfolio"]]
        assert len(default_dash) == 1
        assert default_dash.iloc[0]["portfolio_id"] == "PORT_OFF_BASE_B15M_EQ20"

        # Equivalence group count
        assert df_summary["portfolio_equivalence_group"].nunique() == 9

    def test_source_lineage_cardinalities_and_candidate_reuse(self):
        """Source key is unique across 387 rows; selection key is unique across 1,212 rows; candidate reuse is expected."""
        df_benefits = pd.read_parquet(BENEFITS_PARQUET)
        df_selections = pd.read_parquet(SELECTIONS_PARQUET)

        # Phase 4B source key uniqueness (387 candidate rows)
        assert len(df_benefits) == 387
        assert df_benefits.duplicated(subset=["corridor_id", "treatment_id", "uncertainty_scenario"]).sum() == 0

        # Phase 5A selection key uniqueness (1,212 selection rows)
        assert len(df_selections) == 1212
        assert df_selections.duplicated(subset=["portfolio_id", "corridor_id"]).sum() == 0

        # Merge lineage check: 100% matched, 0 unmatched, 0 join expansion
        merged = pd.merge(
            df_selections,
            df_benefits,
            on=["corridor_id", "treatment_id", "uncertainty_scenario"],
            how="left",
            suffixes=("_sel", "_src"),
        )
        assert len(merged) == 1212
        assert merged["capital_project_cost_src"].isna().sum() == 0

        # Candidate reuse across portfolio_ids (TRT_002 candidates selected in multiple portfolios)
        candidate_counts = df_selections.groupby(["corridor_id", "treatment_id", "uncertainty_scenario"]).size()
        assert (candidate_counts > 1).any()

    def test_spatial_serving_readiness(self):
        """Master corridor dimension contains WGS84 centroids, WKT linework, EPSG:3435 CRS, and corridor_id join key."""
        df_master = pd.read_parquet(CORRIDOR_MASTER_PARQUET)

        assert len(df_master) == 43
        assert "centroid_latitude" in df_master.columns
        assert "centroid_longitude" in df_master.columns
        assert "geometry_wkt" in df_master.columns
        assert "geometry_crs" in df_master.columns

        assert df_master["centroid_latitude"].notna().all()
        assert df_master["centroid_longitude"].notna().all()
        assert (df_master["geometry_crs"] == "EPSG:3435").all()

    def test_validation_runner_pass_with_warnings(self, tmp_path):
        """Validation runner executes successfully, returning PASS_WITH_WARNINGS and 2 warnings."""
        report = validate_decision_output_mart(
            validation_json_path=tmp_path / "val.json",
            runs_dir_path=tmp_path / "runs",
        )

        assert report["status"] == "PASS_WITH_WARNINGS"
        assert report["critical_failure_count"] == 0
        assert report["warning_count"] == 2

        warning_codes = [w["code"] for w in report["governance_warnings"]]
        assert "WARNING_PROVISIONAL_DECISION_MART_ONLY" in warning_codes
        assert "WARNING_PHYSICAL_APPLICABILITY_UNKNOWN" in warning_codes
