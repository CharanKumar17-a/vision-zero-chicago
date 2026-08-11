"""Tests for leakage-safe corridor-month feature calculation and chronological data splits.

All tests use synthetic data created in memory.
No real parquet files are overwritten during testing.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.features.build_corridor_month_features import (
    build_corridor_month_features,
    compute_leakage_safe_features,
    validate_corridor_month_features,
)


def make_synthetic_panel_for_features(n_corridors: int = 2, n_months: int = 96) -> pd.DataFrame:
    """Create synthetic panel with 96 months per corridor (Jan 2018 to Dec 2025)."""
    corridor_ids = [f"HCC{i:03d}" for i in range(1, n_corridors + 1)]
    dates = pd.date_range("2018-01-01", "2025-12-01", freq="MS")

    rows = []
    for cid in corridor_ids:
        for idx, d in enumerate(dates):
            # Synthetic crash pattern: total_crashes = idx + 10, ksi_crashes = (idx + 10) // 5
            total = idx + 10
            ksi = (idx + 10) // 5
            rows.append(
                {
                    "corridor_id": cid,
                    "crash_month_start": d,
                    "calendar_year": d.year,
                    "calendar_month": d.month,
                    "calendar_quarter": d.quarter,
                    "corridor_name": f"Corridor {cid}",
                    "source_group": "neighborhood",
                    "corridor_length_feet": 5280.0,
                    "corridor_length_miles": 1.0,
                    "total_crashes": total,
                    "fatal_crashes": 1 if ksi > 0 else 0,
                    "serious_injury_crashes": ksi - 1 if ksi > 0 else 0,
                    "ksi_crashes": ksi,
                    "moderate_injury_crashes": 2,
                    "minor_injury_crashes": 2,
                    "property_damage_only_crashes": total - ksi - 4 if (total - ksi - 4) >= 0 else 0,
                    "unknown_severity_crashes": 0,
                }
            )

    return pd.DataFrame(rows)


def get_default_test_config() -> dict:
    return {
        "targets": {
            "all_target_columns": ["total_crashes", "ksi_crashes"],
        },
        "features": {
            "lag_months": [1, 3, 6, 12],
            "rolling_windows": [3, 6, 12],
        },
    }


class TestLeakageSafeFeatures:
    def test_predictors_do_not_use_same_month_outcome(self):
        """Changing total_crashes at month t does not alter predictors for month t."""
        panel = make_synthetic_panel_for_features()
        cfg = get_default_test_config()

        feat1 = compute_leakage_safe_features(panel, cfg)

        # Mutate total_crashes at month t=15 for HCC001
        panel_mutated = panel.copy()
        panel_mutated.loc[15, "total_crashes"] += 999

        feat2 = compute_leakage_safe_features(panel_mutated, cfg)

        # Predictors for row 15 (month t) must remain identical between feat1 and feat2
        pred_cols = [
            c for c in feat1.columns
            if c not in ["total_crashes", "ksi_crashes", "fatal_crashes", "serious_injury_crashes",
                         "moderate_injury_crashes", "minor_injury_crashes", "property_damage_only_crashes",
                         "unknown_severity_crashes"]
        ]

        row15_p1 = feat1.loc[15, pred_cols]
        row15_p2 = feat2.loc[15, pred_cols]
        pd.testing.assert_series_equal(row15_p1, row15_p2)

    def test_future_outcomes_do_not_change_earlier_features(self):
        """Mutating a future outcome at t=50 does not change features at t=10."""
        panel = make_synthetic_panel_for_features()
        cfg = get_default_test_config()

        feat1 = compute_leakage_safe_features(panel, cfg)

        panel_mutated = panel.copy()
        panel_mutated.loc[50, "total_crashes"] += 500

        feat2 = compute_leakage_safe_features(panel_mutated, cfg)

        # Row 10 (earlier than 50) must be 100% identical in all predictor columns
        pred_cols = [c for c in feat1.columns if "_lag" in c or "_roll_" in c]
        pd.testing.assert_frame_equal(feat1.loc[:49, pred_cols], feat2.loc[:49, pred_cols])

    def test_lag1_equals_immediately_preceding_month_target(self):
        """total_crashes_lag1 at month t equals total_crashes at month t-1."""
        panel = make_synthetic_panel_for_features()
        cfg = get_default_test_config()
        feat = compute_leakage_safe_features(panel, cfg)

        for cid, group in feat.groupby("corridor_id"):
            g = group.sort_values("crash_month_start").reset_index(drop=True)
            for i in range(1, len(g)):
                assert g.loc[i, "total_crashes_lag1"] == g.loc[i - 1, "total_crashes"]

    def test_lag12_equals_same_corridor_12_months_earlier(self):
        """total_crashes_lag12 at month t equals total_crashes at month t-12."""
        panel = make_synthetic_panel_for_features()
        cfg = get_default_test_config()
        feat = compute_leakage_safe_features(panel, cfg)

        for cid, group in feat.groupby("corridor_id"):
            g = group.sort_values("crash_month_start").reset_index(drop=True)
            for i in range(12, len(g)):
                assert g.loc[i, "total_crashes_lag12"] == g.loc[i - 12, "total_crashes"]

    def test_rolling_means_and_sums_use_shifted_historical_values(self):
        """total_crashes_roll_sum3 at index i equals sum of targets at i-1, i-2, i-3."""
        panel = make_synthetic_panel_for_features()
        cfg = get_default_test_config()
        feat = compute_leakage_safe_features(panel, cfg)

        for cid, group in feat.groupby("corridor_id"):
            g = group.sort_values("crash_month_start").reset_index(drop=True)
            for i in range(3, len(g)):
                expected_sum = g.loc[i - 3 : i - 1, "total_crashes"].sum()
                expected_mean = expected_sum / 3.0
                assert pytest.approx(g.loc[i, "total_crashes_roll_sum3"], 0.001) == expected_sum
                assert pytest.approx(g.loc[i, "total_crashes_roll_mean3"], 0.001) == expected_mean

    def test_features_never_cross_corridor_boundaries(self):
        """First row of each corridor has NaN for lag1 (no cross-corridor leakage)."""
        panel = make_synthetic_panel_for_features(n_corridors=2)
        cfg = get_default_test_config()
        feat = compute_leakage_safe_features(panel, cfg)

        hcc001_first = feat[feat["corridor_id"] == "HCC001"].iloc[0]
        hcc002_first = feat[feat["corridor_id"] == "HCC002"].iloc[0]

        assert pd.isna(hcc001_first["total_crashes_lag1"])
        assert pd.isna(hcc002_first["total_crashes_lag1"])

    def test_january_2019_has_exactly_12_prior_observations(self):
        """January 2019 has history_months_available == 12 and model_ready == True."""
        panel = make_synthetic_panel_for_features()
        cfg = get_default_test_config()
        feat = compute_leakage_safe_features(panel, cfg)

        jan_2019 = feat[feat["crash_month_start"] == pd.Timestamp("2019-01-01")]
        assert len(jan_2019) == 2
        assert (jan_2019["history_months_available"] == 12).all()
        assert (jan_2019["model_ready"] == True).all()

    def test_chronological_splits_and_no_random_split(self):
        """Splits are purely time-partitioned into warmup (2018), train (2019-2023), validation (2024), test (2025)."""
        panel = make_synthetic_panel_for_features()
        cfg = get_default_test_config()
        feat = compute_leakage_safe_features(panel, cfg)

        assert (feat[feat["calendar_year"] == 2018]["model_split"] == "warmup").all()
        assert (feat[(feat["calendar_year"] >= 2019) & (feat["calendar_year"] <= 2023)]["model_split"] == "train").all()
        assert (feat[feat["calendar_year"] == 2024]["model_split"] == "validation").all()
        assert (feat[feat["calendar_year"] == 2025]["model_split"] == "test").all()


class TestSampleModeAndValidationProtection:
    def test_sample_execution_cannot_overwrite_authoritative_evidence(self, tmp_path):
        """Sample mode execution must not overwrite production feature parquet or validation report."""
        report_p = tmp_path / "report.json"
        report_p.write_text('{"authoritative": true}', encoding="utf-8")

        panel = make_synthetic_panel_for_features()
        panel_p = tmp_path / "panel.parquet"
        cfg_p = tmp_path / "modeling.yml"
        out_p = tmp_path / "features.parquet"
        runs_dir = tmp_path / "runs"

        panel.to_parquet(panel_p, index=False)

        cfg_content = """
targets:
  all_target_columns: [total_crashes, ksi_crashes]
features:
  lag_months: [1, 3, 6, 12]
  rolling_windows: [3, 6, 12]
"""
        cfg_p.write_text(cfg_content, encoding="utf-8")

        feat_df, report = build_corridor_month_features(
            panel_path=panel_p,
            modeling_config_path=cfg_p,
            output_path=out_p,
            validation_report_path=report_p,
            runs_dir=runs_dir,
            sample_size=10,
        )

        assert report["is_sample"] is True
        saved_text = report_p.read_text(encoding="utf-8")
        assert "authoritative" in saved_text
        assert not out_p.exists()
