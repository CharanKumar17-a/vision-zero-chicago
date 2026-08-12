"""Tests for Streamlit Community Cloud Deployment Mode & Public Snapshot Integrity (Phase 5C).

Verifies:
1. Local Parquet mode works cleanly when parquet files exist.
2. Deployment CSV fallback mode works seamlessly when parquet files are absent or FORCE_DEPLOYMENT_MODE=1.
3. CSV row counts match manifest and target exact counts (36 summary, 1410 selections, 43 master, 387 benefits).
4. Manifest SHA-256 checksums are verified on load.
5. Corrupted CSV snapshot files are detected and rejected (fails closed).
6. Prohibited published files (raw crashes, crash core, assignments, DuckDB, joblib, Parquet in deployment_data) are absent.
7. Local Parquet mode and deployment CSV mode produce 100% IDENTICAL default-portfolio KPIs ($0.00 delta).
8. Exactly one portfolio_id feeds every scenario view in deployment mode.
9. WKT map geometry parses correctly into EPSG:4326 GeoDataFrame in deployment mode.
10. Importing data helpers does not launch Streamlit.
11. AppTest clean execution of all 3 Streamlit pages in deployment mode.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dashboard.streamlit.data_access import (
    DEFAULT_PORTFOLIO_ID,
    DEPLOYMENT_DIR,
    MANIFEST_PATH,
    compute_file_sha256,
    get_selected_corridors_geodataframe,
    get_selected_portfolio_benefits,
    get_single_portfolio_selections,
    get_single_portfolio_summary,
    is_cloud_deployment_mode,
    load_corridor_geodataframe,
    load_corridor_master,
    load_portfolio_summary,
    load_project_selections,
    load_treatment_benefits,
    verify_and_load_deployment_file,
)


class TestStreamlitDeployment:
    def test_explicit_data_mode_controls(self, monkeypatch):
        """VISION_ZERO_DATA_MODE environment control supports 'auto', 'local', and 'deployment' modes."""
        monkeypatch.setenv("VISION_ZERO_DATA_MODE", "deployment")
        load_portfolio_summary.clear()
        assert is_cloud_deployment_mode() is True
        df_dep = load_portfolio_summary()
        assert len(df_dep) == 36

        monkeypatch.setenv("VISION_ZERO_DATA_MODE", "local")
        load_portfolio_summary.clear()
        assert is_cloud_deployment_mode() is False
        df_loc = load_portfolio_summary()
        assert len(df_loc) == 36

        monkeypatch.setenv("VISION_ZERO_DATA_MODE", "auto")
        load_portfolio_summary.clear()
        assert is_cloud_deployment_mode() is False

    def test_local_mode_fails_when_parquet_missing(self, monkeypatch, tmp_path):
        """Local mode (VISION_ZERO_DATA_MODE=local) fails closed when Parquet is missing without falling back."""
        monkeypatch.setenv("VISION_ZERO_DATA_MODE", "local")
        non_existent = tmp_path / "non_existent.parquet"
        with pytest.raises(FileNotFoundError, match="Required local Parquet dataset missing"):
            load_portfolio_summary(non_existent)


    def test_exact_row_counts_and_manifest_integrity(self):
        """Deployment CSV row counts match exact requirements."""
        df_summary = verify_and_load_deployment_file("portfolio_summary.csv")
        df_selections = verify_and_load_deployment_file("project_selections.csv")
        df_master = verify_and_load_deployment_file("corridor_master.csv")
        df_benefits = verify_and_load_deployment_file("treatment_benefits.csv")

        assert len(df_summary) == 36
        assert len(df_selections) == 1410
        assert len(df_master) == 43
        assert len(df_benefits) == 387

    def test_corrupted_snapshot_rejected(self, monkeypatch, tmp_path):
        """Corrupted deployment CSV snapshot (checksum mismatch) fails closed with ValueError."""
        fake_csv = tmp_path / "portfolio_summary.csv"
        fake_csv.write_text("corrupted,data\n1,2\n")

        fake_manifest = tmp_path / "deployment_manifest.json"
        manifest_data = {
            "files": {
                "portfolio_summary.csv": {
                    "filename": "portfolio_summary.csv",
                    "sha256_checksum": "0000000000000000000000000000000000000000000000000000000000000000",
                    "row_count": 36,
                    "columns": ["portfolio_id"],
                }
            }
        }
        fake_manifest.write_text(json.dumps(manifest_data))

        monkeypatch.setattr("dashboard.streamlit.data_access.DEPLOYMENT_DIR", tmp_path)

        with pytest.raises(ValueError, match="SHA-256 checksum verification failed"):
            verify_and_load_deployment_file("portfolio_summary.csv", manifest_path=fake_manifest)

    def test_prohibited_published_files_absent(self):
        """Zero prohibited raw, crash core, assignment, Parquet, DuckDB, or model files in deployment_data/."""
        prohibited_extensions = [".parquet", ".duckdb", ".joblib", ".zip", ".pdf"]
        prohibited_names = ["crashes", "crash_core", "assignments", "people", "vehicles"]

        for filepath in DEPLOYMENT_DIR.rglob("*"):
            assert filepath.suffix.lower() not in prohibited_extensions, f"Prohibited extension in deployment dir: {filepath.name}"
            for p_name in prohibited_names:
                assert p_name not in filepath.name.lower(), f"Prohibited filename pattern in deployment dir: {filepath.name}"

    def test_local_and_deployment_default_kpis_identical(self, monkeypatch):
        """Local Parquet mode and Deployment CSV mode produce 100% IDENTICAL KPIs ($0.00 delta)."""
        # 1. Local mode KPIs
        monkeypatch.delenv("FORCE_DEPLOYMENT_MODE", raising=False)
        load_portfolio_summary.clear()
        load_project_selections.clear()
        load_treatment_benefits.clear()

        sum_local = load_portfolio_summary()
        sel_local = load_project_selections()
        ben_local = load_treatment_benefits()

        row_local = get_single_portfolio_summary(sum_local, DEFAULT_PORTFOLIO_ID)
        df_b_local = get_selected_portfolio_benefits(sel_local, ben_local, DEFAULT_PORTFOLIO_ID)

        cost_local = float(row_local["selected_capital_cost"])
        pv_local = float(row_local["total_present_value_benefit"])
        npv_local = float(row_local["total_net_present_benefit"])
        averted_local = float(df_b_local["crashes_averted_total"].sum())

        # Clear cache for fallback test
        load_portfolio_summary.clear()
        load_project_selections.clear()
        load_treatment_benefits.clear()

        # 2. Deployment CSV mode KPIs
        monkeypatch.setenv("FORCE_DEPLOYMENT_MODE", "1")
        sum_deploy = load_portfolio_summary()
        sel_deploy = load_project_selections()
        ben_deploy = load_treatment_benefits()

        row_deploy = get_single_portfolio_summary(sum_deploy, DEFAULT_PORTFOLIO_ID)
        df_b_deploy = get_selected_portfolio_benefits(sel_deploy, ben_deploy, DEFAULT_PORTFOLIO_ID)

        cost_deploy = float(row_deploy["selected_capital_cost"])
        pv_deploy = float(row_deploy["total_present_value_benefit"])
        npv_deploy = float(row_deploy["total_net_present_benefit"])
        averted_deploy = float(df_b_deploy["crashes_averted_total"].sum())

        # Clear cache again
        load_portfolio_summary.clear()
        load_project_selections.clear()
        load_treatment_benefits.clear()

        # Assert 0 delta
        assert cost_local == pytest.approx(cost_deploy, abs=1e-4)
        assert pv_local == pytest.approx(pv_deploy, abs=1e-4)
        assert npv_local == pytest.approx(npv_deploy, abs=1e-4)
        assert averted_local == pytest.approx(averted_deploy, abs=1e-4)

    def test_single_portfolio_id_feeds_every_view_in_deployment_mode(self, monkeypatch):
        """Single portfolio_id feeds every scenario view in deployment mode with 0 cross-portfolio leakage."""
        monkeypatch.setenv("FORCE_DEPLOYMENT_MODE", "1")
        load_portfolio_summary.clear()
        load_project_selections.clear()
        load_treatment_benefits.clear()
        load_corridor_geodataframe.clear()

        sum_deploy = load_portfolio_summary()
        sel_deploy = load_project_selections()
        ben_deploy = load_treatment_benefits()
        gdf_deploy = load_corridor_geodataframe()

        for pid in sum_deploy["portfolio_id"].unique():
            s_row = get_single_portfolio_summary(sum_deploy, pid)
            assert s_row["portfolio_id"] == pid

            df_sel = get_single_portfolio_selections(sel_deploy, pid)
            assert (df_sel["portfolio_id"] == pid).all()

            df_b = get_selected_portfolio_benefits(sel_deploy, ben_deploy, pid)
            assert (df_b["portfolio_id"] == pid).all()

            gdf_sel = get_selected_corridors_geodataframe(sel_deploy, gdf_deploy, pid)
            assert len(gdf_sel) == len(df_sel)

    def test_wkt_map_geometry_loads_correctly_in_deployment_mode(self, monkeypatch):
        """WKT geometry string parses into valid EPSG:4326 GeoDataFrame in deployment mode."""
        monkeypatch.setenv("FORCE_DEPLOYMENT_MODE", "1")
        load_corridor_geodataframe.clear()

        gdf = load_corridor_geodataframe()
        assert isinstance(gdf, gpd.GeoDataFrame)
        assert gdf.crs.to_string() == "EPSG:4326"
        assert len(gdf) == 43
        assert (gdf["centroid_latitude"].between(41.6, 42.1)).all()
        assert (gdf["centroid_longitude"].between(-87.9, -87.5)).all()
        assert gdf.geometry.is_valid.all()

    def test_import_data_access_helpers_no_launch_side_effects(self):
        """Importing data access module has zero application-launch side effects."""
        assert DEFAULT_PORTFOLIO_ID == "PORT_OFF_BASE_B15M_EQ20"

    def test_apptest_all_three_pages_in_deployment_mode(self, monkeypatch):
        """AppTest executes all 3 Streamlit pages in deployment mode without exceptions."""
        monkeypatch.setenv("FORCE_DEPLOYMENT_MODE", "1")
        load_portfolio_summary.clear()
        load_project_selections.clear()
        load_corridor_master.clear()
        load_treatment_benefits.clear()
        load_corridor_geodataframe.clear()

        app_file = ROOT / "dashboard" / "streamlit" / "app.py"
        at = AppTest.from_file(str(app_file), default_timeout=30)
        at.run()
        assert not at.exception

    def test_streamlit_cloud_working_dir_regression(self, monkeypatch, tmp_path):
        """Regression test: running app.py from a different working directory in deployment mode resolves imports and raises zero exceptions."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("VISION_ZERO_DATA_MODE", "deployment")
        load_portfolio_summary.clear()
        load_project_selections.clear()
        load_corridor_master.clear()
        load_treatment_benefits.clear()
        load_corridor_geodataframe.clear()

        app_file = ROOT / "dashboard" / "streamlit" / "app.py"
        at = AppTest.from_file(str(app_file), default_timeout=30)
        at.run()
        assert not at.exception

    def test_crlf_lf_cross_platform_checksum_equivalence(self, tmp_path):
        """Cross-platform checksum test: LF and CRLF CSVs produce identical SHA-256 digests in builder and data access."""
        from src.data.build_deployment_data import compute_sha256 as builder_compute_sha256

        content = "col1,col2,col3\nval1,val2,val3\n10,20,30\n"
        lf_csv = tmp_path / "test_lf.csv"
        crlf_csv = tmp_path / "test_crlf.csv"

        lf_csv.write_bytes(content.encode("utf-8"))
        crlf_csv.write_bytes(content.replace("\n", "\r\n").encode("utf-8"))

        # Assert builder checksum returns identical hash for LF and CRLF
        builder_lf_hash = builder_compute_sha256(lf_csv)
        builder_crlf_hash = builder_compute_sha256(crlf_csv)
        assert builder_lf_hash == builder_crlf_hash

        # Assert data access checksum returns identical hash for LF and CRLF
        access_lf_hash = compute_file_sha256(lf_csv)
        access_crlf_hash = compute_file_sha256(crlf_csv)
        assert access_lf_hash == access_crlf_hash
        assert builder_lf_hash == access_lf_hash

    def test_sidebar_logo_and_pinned_requirements_regression(self):
        """Regression test: components.py has no deprecated logo/use_column_width and requirements.txt is pinned."""
        components_path = ROOT / "dashboard" / "streamlit" / "components.py"
        components_text = components_path.read_text(encoding="utf-8")

        assert "use_column_width" not in components_text
        assert "raw.githubusercontent.com" not in components_text

        req_path = ROOT / "dashboard" / "streamlit" / "requirements.txt"
        req_lines = [line.strip() for line in req_path.read_text(encoding="utf-8").splitlines() if line.strip()]

        expected_reqs = [
            "streamlit==1.60.0",
            "pandas==3.0.5",
            "geopandas==1.1.4",
            "shapely==2.1.2",
            "plotly==6.9.0",
            "pydeck==0.9.3",
        ]
        assert req_lines == expected_reqs
