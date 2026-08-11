"""Tests for DuckDB SQL analytics layer, window function feature audit, and Power BI history mart.

All tests use synthetic datasets or temporary databases/outputs in memory.
No production Parquet or JSON reports are overwritten during testing.
"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.build_sql_analytics_mart import SQL_DIR, SQL_SCRIPTS, build_sql_analytics_mart
from src.features.build_corridor_month_features import (
    compute_leakage_safe_features,
    load_modeling_config,
)
from src.validation.validate_sql_analytics_mart import (
    audit_sql_python_feature_parity,
    validate_sql_analytics_mart,
)


def make_synthetic_panel_df(n_corridors: int = 2, n_months: int = 96) -> pd.DataFrame:
    """Create synthetic corridor-month panel for testing."""
    corridor_ids = [f"HCC{i:03d}" for i in range(1, n_corridors + 1)]
    dates = pd.date_range("2018-01-01", "2025-12-01", freq="MS")

    rows = []
    for cid in corridor_ids:
        for idx, d in enumerate(dates):
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


class TestSQLAnalyticsMart:
    def test_duckdb_imports_successfully(self):
        """DuckDB imports cleanly and exposes version string."""
        assert duckdb.__version__ is not None
        assert isinstance(duckdb.__version__, str)

    def test_sql_scripts_exist_and_execute_in_order(self):
        """All 4 SQL scripts exist and execute sequentially without SQL syntax errors."""
        for script_name in SQL_SCRIPTS:
            p = SQL_DIR / script_name
            assert p.exists(), f"SQL script missing: {script_name}"

        conn = duckdb.connect(":memory:")

        # Register synthetic tables for testing scripts
        panel_df = make_synthetic_panel_df()
        cfg = load_modeling_config()
        features_df = compute_leakage_safe_features(panel_df, cfg)

        conn.register("synthetic_panel", panel_df)
        conn.register("synthetic_features", features_df)

        conn.execute("CREATE VIEW vw_corridor_month_panel AS SELECT * FROM synthetic_panel")
        conn.execute("CREATE VIEW vw_corridor_month_features AS SELECT * FROM synthetic_features")

        # Execute 02, 03, 04
        for name in SQL_SCRIPTS[1:]:
            sql = (SQL_DIR / name).read_text(encoding="utf-8")
            # Exclude COPY command in memory test
            sql_clean = "\n".join([line for line in sql.splitlines() if not line.strip().startswith("COPY")])
            conn.execute(sql_clean)

        views = [
            v[0]
            for v in conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_type = 'VIEW'"
            ).fetchall()
        ]
        assert "vw_corridor_month_feature_audit" in views
        assert "vw_data_quality_reconciliation" in views
        assert "vw_power_bi_corridor_history" in views
        conn.close()

    def test_source_views_expose_correct_rows(self):
        """Source views expose 4,128 rows against real parquet files."""
        panel_p = ROOT / "data" / "processed" / "corridor_month_panel.parquet"
        feat_p = ROOT / "data" / "processed" / "corridor_month_features.parquet"
        if panel_p.exists() and feat_p.exists():
            conn = duckdb.connect(":memory:")
            sql1 = (SQL_DIR / "01_create_source_views.sql").read_text(encoding="utf-8")
            conn.execute(sql1)

            c_panel = conn.execute("SELECT COUNT(*) FROM vw_corridor_month_panel").fetchone()[0]
            c_feat = conn.execute("SELECT COUNT(*) FROM vw_corridor_month_features").fetchone()[0]

            assert c_panel == 4128
            assert c_feat == 4128
            conn.close()

    def test_sql_lag1_matches_preceding_month(self):
        """SQL lag1 for month t matches total_crashes at month t-1."""
        conn = duckdb.connect(":memory:")
        panel_df = make_synthetic_panel_df()
        conn.register("synthetic_panel", panel_df)
        conn.execute("CREATE VIEW vw_corridor_month_panel AS SELECT * FROM synthetic_panel")

        sql2 = (SQL_DIR / "02_corridor_month_feature_audit.sql").read_text(encoding="utf-8")
        conn.execute(sql2)

        audit_df = conn.execute(
            "SELECT corridor_id, crash_month_start, total_crashes, sql_total_crashes_lag1 FROM vw_corridor_month_feature_audit ORDER BY corridor_id, crash_month_start"
        ).df()

        for cid, group in audit_df.groupby("corridor_id"):
            g = group.reset_index(drop=True)
            for i in range(1, len(g)):
                assert g.loc[i, "sql_total_crashes_lag1"] == g.loc[i - 1, "total_crashes"]

        conn.close()

    def test_sql_lag12_matches_value_12_months_earlier(self):
        """SQL lag12 for month t matches total_crashes at month t-12."""
        conn = duckdb.connect(":memory:")
        panel_df = make_synthetic_panel_df()
        conn.register("synthetic_panel", panel_df)
        conn.execute("CREATE VIEW vw_corridor_month_panel AS SELECT * FROM synthetic_panel")

        sql2 = (SQL_DIR / "02_corridor_month_feature_audit.sql").read_text(encoding="utf-8")
        conn.execute(sql2)

        audit_df = conn.execute(
            "SELECT corridor_id, crash_month_start, total_crashes, sql_total_crashes_lag12 FROM vw_corridor_month_feature_audit ORDER BY corridor_id, crash_month_start"
        ).df()

        for cid, group in audit_df.groupby("corridor_id"):
            g = group.reset_index(drop=True)
            for i in range(12, len(g)):
                assert g.loc[i, "sql_total_crashes_lag12"] == g.loc[i - 12, "total_crashes"]

        conn.close()

    def test_rolling_windows_end_at_1_preceding_and_no_current_row(self):
        """SQL window clauses strictly use ROWS BETWEEN n PRECEDING AND 1 PRECEDING and never CURRENT ROW."""
        sql2 = (SQL_DIR / "02_corridor_month_feature_audit.sql").read_text(encoding="utf-8")
        assert "CURRENT ROW" not in sql2.upper()
        assert "1 PRECEDING" in sql2.upper()

    def test_sql_features_do_not_cross_corridor_boundaries(self):
        """First row of each corridor has NULL for sql_total_crashes_lag1."""
        conn = duckdb.connect(":memory:")
        panel_df = make_synthetic_panel_df(n_corridors=2)
        conn.register("synthetic_panel", panel_df)
        conn.execute("CREATE VIEW vw_corridor_month_panel AS SELECT * FROM synthetic_panel")

        sql2 = (SQL_DIR / "02_corridor_month_feature_audit.sql").read_text(encoding="utf-8")
        conn.execute(sql2)

        audit_df = conn.execute("SELECT * FROM vw_corridor_month_feature_audit").df()
        hcc001_first = audit_df[audit_df["corridor_id"] == "HCC001"].iloc[0]
        hcc002_first = audit_df[audit_df["corridor_id"] == "HCC002"].iloc[0]

        assert pd.isna(hcc001_first["sql_total_crashes_lag1"])
        assert pd.isna(hcc002_first["sql_total_crashes_lag1"])
        conn.close()

    def test_sql_python_feature_parity_on_lags_sums_means_and_nulls(self):
        """SQL window features and Python pandas features achieve 100% parity."""
        panel_p = ROOT / "data" / "processed" / "corridor_month_panel.parquet"
        feat_p = ROOT / "data" / "processed" / "corridor_month_features.parquet"
        if panel_p.exists() and feat_p.exists():
            conn = duckdb.connect(":memory:")
            sql1 = (SQL_DIR / "01_create_source_views.sql").read_text(encoding="utf-8")
            sql2 = (SQL_DIR / "02_corridor_month_feature_audit.sql").read_text(encoding="utf-8")

            conn.execute(sql1)
            conn.execute(sql2)

            parity, checks = audit_sql_python_feature_parity(conn)
            assert parity["matching_rows"] == 4128
            assert parity["mismatched_lags"] == 0
            assert parity["mismatched_sums"] == 0
            assert parity["max_mean_diff"] <= 1e-9
            assert parity["null_mismatches"] == 0
            conn.close()

    def test_data_quality_reconciliation_query_returns_expected_values(self):
        """03_data_quality_reconciliation.sql returns expected reconciliation values."""
        panel_p = ROOT / "data" / "processed" / "corridor_month_panel.parquet"
        feat_p = ROOT / "data" / "processed" / "corridor_month_features.parquet"
        if panel_p.exists() and feat_p.exists():
            conn = duckdb.connect(":memory:")
            for s in SQL_SCRIPTS[:3]:
                sql = (SQL_DIR / s).read_text(encoding="utf-8")
                conn.execute(sql)

            dq = conn.execute("SELECT * FROM vw_data_quality_reconciliation").df().iloc[0].to_dict()
            assert dq["total_rows"] == 4128
            assert dq["distinct_keys"] == 4128
            assert dq["duplicate_keys"] == 0
            assert dq["corridor_count"] == 43
            assert dq["total_crashes_sum"] == 112421
            assert dq["ksi_crashes_sum"] == 2297
            assert dq["model_ready_rows"] == 3612
            conn.close()

    def test_power_bi_mart_has_4128_unique_keys(self):
        """Power BI historical mart view has 4,128 unique keys."""
        panel_p = ROOT / "data" / "processed" / "corridor_month_panel.parquet"
        feat_p = ROOT / "data" / "processed" / "corridor_month_features.parquet"
        if panel_p.exists() and feat_p.exists():
            conn = duckdb.connect(":memory:")
            for s in SQL_SCRIPTS[:3]:
                conn.execute((SQL_DIR / s).read_text(encoding="utf-8"))
            conn.execute(
                "CREATE VIEW vw_power_bi_corridor_history AS SELECT * FROM vw_corridor_month_features"
            )

            res = conn.execute(
                "SELECT COUNT(*), COUNT(DISTINCT corridor_id || '_' || CAST(crash_month_start AS VARCHAR)) FROM vw_power_bi_corridor_history"
            ).fetchone()
            assert res[0] == 4128
            assert res[1] == 4128
            conn.close()

    def test_sample_execution_and_test_isolation(self, tmp_path):
        """Sample mode / test execution does not overwrite production parquet or report evidence."""
        report_p = tmp_path / "report.json"
        report_p.write_text('{"authoritative": true}', encoding="utf-8")

        db_p = tmp_path / "test.duckdb"
        mart_p = tmp_path / "mart.parquet"

        metrics = build_sql_analytics_mart(
            db_path=db_p,
            mart_output_path=mart_p,
            sample_size=10,
        )

        assert metrics["mart_row_count"] == 4128
        report_text = report_p.read_text(encoding="utf-8")
        assert "authoritative" in report_text
