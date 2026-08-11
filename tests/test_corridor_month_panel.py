"""Tests for corridor-month modeling panel construction and validation.

All tests use synthetic data created in memory.
No real parquet files are overwritten during testing.
"""

from __future__ import annotations

import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import LineString

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.build_corridor_month_panel import (
    aggregate_primary_crashes,
    build_complete_grid,
    build_corridor_month_panel,
    validate_corridor_month_panel,
    validate_input_grains,
)


def make_synthetic_panel_inputs():
    """Create synthetic register, corridor geometries, crashes, and assignments in memory."""
    # 2 corridors: HCC001, HCC002
    register_df = pd.DataFrame(
        {
            "corridor_id": ["HCC001", "HCC002"],
            "corridor_name": ["Devon", "Broadway"],
            "source_group": ["neighborhood", "neighborhood"],
        }
    )

    corridors_gdf = gpd.GeoDataFrame(
        {
            "corridor_id": ["HCC001", "HCC002"],
            "corridor_length_feet": [5280.0, 10560.0],
            "geometry": [LineString([(0, 0), (5280, 0)]), LineString([(0, 0), (10560, 0)])],
        },
        crs="EPSG:3435",
    )

    # 4 synthetic crashes:
    # C001: HCC001, 2018-01-01, K (fatal)
    # C002: HCC001, 2018-01-01, A (incapacitating)
    # C003: HCC002, 2025-12-01, O (no injury)
    # C004: HCC002, 2025-12-01, U (unknown)
    crashes_df = pd.DataFrame(
        {
            "crash_record_id": ["C001", "C002", "C003", "C004"],
            "severity_kabco": ["K", "A", "O", "U"],
            "crash_month_start": pd.to_datetime(
                ["2018-01-01", "2018-01-01", "2025-12-01", "2025-12-01"]
            ),
        }
    )

    assignments_df = pd.DataFrame(
        {
            "crash_record_id": ["C001", "C002", "C003", "C004"],
            "assignment_status": [
                "primary_assigned",
                "primary_assigned",
                "primary_assigned",
                "primary_assigned",
            ],
            "corridor_id": ["HCC001", "HCC001", "HCC002", "HCC002"],
        }
    )

    return register_df, corridors_gdf, crashes_df, assignments_df


class TestCorridorMonthPanelRules:
    def test_complete_43_x_96_grid_construction(self):
        """Build grid for 43 corridors and 96 months produces exactly 4,128 rows."""
        reg = pd.DataFrame(
            {
                "corridor_id": [f"HCC{i:03d}" for i in range(1, 44)],
                "corridor_name": [f"Corridor {i}" for i in range(1, 44)],
                "source_group": ["neighborhood"] * 43,
            }
        )
        geom = gpd.GeoDataFrame(
            {
                "corridor_id": [f"HCC{i:03d}" for i in range(1, 44)],
                "corridor_length_feet": [5000.0] * 43,
                "geometry": [LineString([(0, 0), (5000, 0)])] * 43,
            },
            crs="EPSG:3435",
        )

        grid = build_complete_grid(reg, geom)
        assert len(grid) == 4128
        assert grid["corridor_id"].nunique() == 43
        assert grid.groupby("corridor_id")["crash_month_start"].count().min() == 96

    def test_zero_crash_months_remain_present(self):
        """Zero-crash corridor-months are preserved with 0 counts."""
        reg, geom, crashes, assign = make_synthetic_panel_inputs()
        grid = build_complete_grid(reg, geom)
        agg = aggregate_primary_crashes(crashes, assign, set(reg["corridor_id"]))
        panel = grid.merge(agg, on=["corridor_id", "crash_month_start"], how="left")

        # Zero fill count columns
        count_cols = [
            "total_crashes", "fatal_crashes", "serious_injury_crashes", "ksi_crashes",
            "moderate_injury_crashes", "minor_injury_crashes",
            "property_damage_only_crashes", "unknown_severity_crashes"
        ]
        for col in count_cols:
            panel[col] = panel[col].fillna(0).astype(int)

        # 2 corridors x 96 months = 192 total rows
        assert len(panel) == 192
        zero_rows = panel[panel["total_crashes"] == 0]
        assert len(zero_rows) == 190  # 192 - 2 months with crashes = 190

    def test_composite_key_uniqueness(self):
        """Composite key corridor_id + crash_month_start is unique."""
        reg, geom, crashes, assign = make_synthetic_panel_inputs()
        grid = build_complete_grid(reg, geom)
        assert not grid.duplicated(subset=["corridor_id", "crash_month_start"]).any()

    def test_exactly_96_months_per_corridor(self):
        """Each corridor has exactly 96 calendar months."""
        reg, geom, _, _ = make_synthetic_panel_inputs()
        grid = build_complete_grid(reg, geom)
        m_counts = grid.groupby("corridor_id")["crash_month_start"].count()
        assert (m_counts == 96).all()

    def test_correct_january_2018_and_december_2025_boundaries(self):
        """Grid spans from 2018-01-01 to 2025-12-01 inclusive."""
        reg, geom, _, _ = make_synthetic_panel_inputs()
        grid = build_complete_grid(reg, geom)
        assert grid["crash_month_start"].min() == pd.Timestamp("2018-01-01")
        assert grid["crash_month_start"].max() == pd.Timestamp("2025-12-01")

    def test_one_to_one_crash_assignment_join(self):
        """Aggregation verifies 1:1 join without crash duplication or loss."""
        reg, geom, crashes, assign = make_synthetic_panel_inputs()
        agg = aggregate_primary_crashes(crashes, assign, set(reg["corridor_id"]))
        assert agg["total_crashes"].sum() == 4

    def test_unknown_corridor_ids_fail_validation(self):
        """Assigning a crash to an unknown corridor ID raises ValueError during aggregation."""
        reg, geom, crashes, assign = make_synthetic_panel_inputs()
        assign_bad = assign.copy()
        assign_bad.loc[0, "corridor_id"] = "UNKNOWN_999"

        with pytest.raises(ValueError, match="unknown corridor IDs"):
            aggregate_primary_crashes(crashes, assign_bad, set(reg["corridor_id"]))

    def test_missing_or_invalid_months_fail_validation(self):
        """Joined crash with month outside 2018-2025 range fails validation."""
        reg, geom, crashes, assign = make_synthetic_panel_inputs()
        crashes_bad = crashes.copy()
        crashes_bad.loc[0, "crash_month_start"] = pd.Timestamp("2017-12-01")

        with pytest.raises(ValueError, match="month out of range"):
            aggregate_primary_crashes(crashes_bad, assign, set(reg["corridor_id"]))

    def test_severity_mapping_follows_cleaning_contract(self):
        """Severity mapping correctly separates K, A, B, C, O, U into distinct fields."""
        reg, geom, crashes, assign = make_synthetic_panel_inputs()
        agg = aggregate_primary_crashes(crashes, assign, set(reg["corridor_id"]))

        # HCC001 in 2018-01-01 has 1 K (fatal) and 1 A (serious)
        hcc1_row = agg[
            (agg["corridor_id"] == "HCC001") & (agg["crash_month_start"] == pd.Timestamp("2018-01-01"))
        ].iloc[0]

        assert hcc1_row["fatal_crashes"] == 1
        assert hcc1_row["serious_injury_crashes"] == 1
        assert hcc1_row["moderate_injury_crashes"] == 0
        assert hcc1_row["minor_injury_crashes"] == 0
        assert hcc1_row["property_damage_only_crashes"] == 0
        assert hcc1_row["unknown_severity_crashes"] == 0
        assert hcc1_row["total_crashes"] == 2
        assert hcc1_row["ksi_crashes"] == 2

        # HCC002 in 2025-12-01 has 1 O (property_damage) and 1 U (unknown)
        hcc2_row = agg[
            (agg["corridor_id"] == "HCC002") & (agg["crash_month_start"] == pd.Timestamp("2025-12-01"))
        ].iloc[0]

        assert hcc2_row["fatal_crashes"] == 0
        assert hcc2_row["serious_injury_crashes"] == 0
        assert hcc2_row["property_damage_only_crashes"] == 1
        assert hcc2_row["unknown_severity_crashes"] == 1
        assert hcc2_row["total_crashes"] == 2
        assert hcc2_row["ksi_crashes"] == 0

    def test_severity_categories_reconcile_to_total_crashes(self):
        """For all rows, fatal + serious + moderate + minor + pdo + unknown == total_crashes."""
        reg, geom, crashes, assign = make_synthetic_panel_inputs()
        agg = aggregate_primary_crashes(crashes, assign, set(reg["corridor_id"]))
        grid = build_complete_grid(reg, geom)
        panel = grid.merge(agg, on=["corridor_id", "crash_month_start"], how="left").fillna(0)

        sum_parts = (
            panel["fatal_crashes"]
            + panel["serious_injury_crashes"]
            + panel["moderate_injury_crashes"]
            + panel["minor_injury_crashes"]
            + panel["property_damage_only_crashes"]
            + panel["unknown_severity_crashes"]
        )
        assert (sum_parts == panel["total_crashes"]).all()

    def test_ksi_equals_fatal_plus_serious_injury(self):
        """KSI crashes equal fatal + serious injury crashes."""
        reg, geom, crashes, assign = make_synthetic_panel_inputs()
        agg = aggregate_primary_crashes(crashes, assign, set(reg["corridor_id"]))
        assert (agg["ksi_crashes"] == agg["fatal_crashes"] + agg["serious_injury_crashes"]).all()

    def test_global_panel_total_reconciles_to_primary_assignments(self):
        """Sum of total_crashes across panel equals count of primary assigned crashes."""
        reg, geom, crashes, assign = make_synthetic_panel_inputs()
        agg = aggregate_primary_crashes(crashes, assign, set(reg["corridor_id"]))
        assert agg["total_crashes"].sum() == len(assign[assign["assignment_status"] == "primary_assigned"])

    def test_static_metadata_join_does_not_multiply_rows(self):
        """Merging corridor metadata preserves exact row count (43 per month, 192 total for 2 corridors)."""
        reg, geom, _, _ = make_synthetic_panel_inputs()
        grid = build_complete_grid(reg, geom)
        assert len(grid) == 192

    def test_count_fields_are_non_negative_integers(self):
        """Count fields are non-negative int64 values."""
        reg, geom, crashes, assign = make_synthetic_panel_inputs()
        grid = build_complete_grid(reg, geom)
        agg = aggregate_primary_crashes(crashes, assign, set(reg["corridor_id"]))
        panel = grid.merge(agg, on=["corridor_id", "crash_month_start"], how="left")

        count_cols = [
            "total_crashes", "fatal_crashes", "serious_injury_crashes", "ksi_crashes",
            "moderate_injury_crashes", "minor_injury_crashes",
            "property_damage_only_crashes", "unknown_severity_crashes"
        ]
        for col in count_cols:
            panel[col] = panel[col].fillna(0).astype("int64")
            assert (panel[col] >= 0).all()
            assert pd.api.types.is_integer_dtype(panel[col])

    def test_output_is_deterministically_sorted_by_corridor_id_and_month(self):
        """Output panel is sorted by corridor_id ascending, crash_month_start ascending."""
        reg, geom, _, _ = make_synthetic_panel_inputs()
        grid = build_complete_grid(reg, geom)
        grid_sorted = grid.sort_values(
            by=["corridor_id", "crash_month_start"], ascending=[True, True]
        ).reset_index(drop=True)
        assert grid[["corridor_id", "crash_month_start"]].equals(
            grid_sorted[["corridor_id", "crash_month_start"]]
        )


class TestSampleModeAndValidationProtection:
    def test_sample_execution_cannot_overwrite_authoritative_evidence(self, tmp_path):
        """Sample mode must not overwrite production parquet or validation report artifacts."""
        report_p = tmp_path / "report.json"
        report_p.write_text('{"authoritative": true}', encoding="utf-8")

        reg, geom, crashes, assign = make_synthetic_panel_inputs()
        crashes_p = tmp_path / "crashes.parquet"
        assign_p = tmp_path / "assign.parquet"
        reg_p = tmp_path / "register.csv"
        geom_p = tmp_path / "corridors.parquet"
        output_p = tmp_path / "panel.parquet"
        runs_dir = tmp_path / "runs"

        crashes.to_parquet(crashes_p, index=False)
        assign.to_parquet(assign_p, index=False)
        reg.to_csv(reg_p, index=False)
        geom.to_parquet(geom_p, index=False)

        panel_df, report = build_corridor_month_panel(
            crashes_path=crashes_p,
            assignment_path=assign_p,
            register_path=reg_p,
            corridors_path=geom_p,
            output_path=output_p,
            validation_report_path=report_p,
            runs_dir=runs_dir,
            sample_size=2,
        )

        assert report["is_sample"] is True
        saved_text = report_p.read_text(encoding="utf-8")
        assert "authoritative" in saved_text
        assert not output_p.exists()
