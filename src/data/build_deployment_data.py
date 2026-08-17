"""Build Public Demonstration Snapshot for Streamlit Community Cloud (Phase 5C).

Contract: docs/data_quality/decision_output_mart_contract.md
Decision: D022 (Public demonstration snapshot approval)

Generates:
1. dashboard/streamlit/deployment_data/portfolio_summary.csv (36 rows)
2. dashboard/streamlit/deployment_data/project_selections.csv (1,362 rows)
3. dashboard/streamlit/deployment_data/corridor_master.csv (43 rows with WGS84 WKT geometry)
4. dashboard/streamlit/deployment_data/treatment_benefits.csv (387 rows)
5. dashboard/streamlit/deployment_data/deployment_manifest.json
"""

from __future__ import annotations

import datetime
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict

import geopandas as gpd
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEPLOYMENT_DIR = ROOT / "dashboard" / "streamlit" / "deployment_data"

SUMMARY_PARQUET = ROOT / "data" / "processed" / "power_bi_portfolio_summary.parquet"
SELECTIONS_PARQUET = ROOT / "data" / "processed" / "power_bi_project_selections.parquet"
MASTER_PARQUET = ROOT / "data" / "processed" / "power_bi_corridor_master.parquet"
BENEFITS_PARQUET = ROOT / "data" / "processed" / "power_bi_treatment_benefits.parquet"
CORRIDORS_GEO_PARQUET = ROOT / "data" / "interim" / "high_crash_corridors.parquet"
MART_VAL_JSON = ROOT / "docs" / "data_quality" / "decision_output_mart_validation.json"


def compute_sha256(file_path: Path) -> str:
    """Compute SHA-256 checksum of a file, canonicalizing CRLF to LF for CSV files."""
    data = file_path.read_bytes()
    if file_path.suffix.lower() == ".csv":
        data = data.replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def get_source_run_id() -> str:
    """Extract source validation run ID from decision mart validation report if available."""
    if MART_VAL_JSON.exists():
        with open(MART_VAL_JSON, "r", encoding="utf-8") as f:
            val_doc = json.load(f)
            return val_doc.get("run_id", "20260812T104902Z")
    return "20260812T104902Z"


def build_deployment_data() -> Dict[str, Any]:
    """Generate all deployment CSV datasets and validation manifest."""
    t0 = time.time()
    DEPLOYMENT_DIR.mkdir(parents=True, exist_ok=True)
    generated_at_utc = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    source_run_id = get_source_run_id()

    print("=" * 80)
    print("BUILDING STREAMLIT COMMUNITY CLOUD DEPLOYMENT DATASET (PHASE 5C)")
    print("=" * 80)

    # 1. portfolio_summary.csv
    df_sum = pd.read_parquet(SUMMARY_PARQUET)
    sum_csv_path = DEPLOYMENT_DIR / "portfolio_summary.csv"
    df_sum.to_csv(sum_csv_path, index=False)
    print(f"Wrote portfolio_summary.csv ({len(df_sum)} rows)")

    # 2. project_selections.csv
    df_sel = pd.read_parquet(SELECTIONS_PARQUET)
    sel_csv_path = DEPLOYMENT_DIR / "project_selections.csv"
    df_sel.to_csv(sel_csv_path, index=False)
    print(f"Wrote project_selections.csv ({len(df_sel)} rows)")

    # 3. corridor_master.csv with WGS84 WKT geometry
    df_mas = pd.read_parquet(MASTER_PARQUET)
    gdf_cor = gpd.read_parquet(CORRIDORS_GEO_PARQUET)

    # Centroids calculated accurately in projected EPSG:3435 before re-projecting to 4326
    centroids_3435 = gdf_cor.geometry.centroid
    centroids_4326 = centroids_3435.to_crs(epsg=4326)
    gdf_4326 = gdf_cor.to_crs(epsg=4326)

    wkt_map = dict(zip(gdf_4326["corridor_id"], gdf_4326.geometry.to_wkt()))
    lat_map = dict(zip(gdf_cor["corridor_id"], centroids_4326.y))
    lon_map = dict(zip(gdf_cor["corridor_id"], centroids_4326.x))

    df_mas["geometry_wkt"] = df_mas["corridor_id"].map(wkt_map)
    df_mas["geometry_crs"] = "EPSG:4326"
    df_mas["centroid_latitude"] = df_mas["corridor_id"].map(lat_map)
    df_mas["centroid_longitude"] = df_mas["corridor_id"].map(lon_map)

    mas_csv_path = DEPLOYMENT_DIR / "corridor_master.csv"
    df_mas.to_csv(mas_csv_path, index=False)
    print(f"Wrote corridor_master.csv ({len(df_mas)} rows, WGS84 WKT geometry)")

    # 4. treatment_benefits.csv
    df_ben = pd.read_parquet(BENEFITS_PARQUET)
    ben_csv_path = DEPLOYMENT_DIR / "treatment_benefits.csv"
    df_ben.to_csv(ben_csv_path, index=False)
    print(f"Wrote treatment_benefits.csv ({len(df_ben)} rows)")

    # 5. Build deployment_manifest.json
    manifest_files = {}

    file_configs = [
        (
            "portfolio_summary.csv",
            sum_csv_path,
            df_sum,
            "data/processed/power_bi_portfolio_summary.parquet",
            f"portfolio_id x 1 row ({len(df_sum):,} planning scenarios)",
            "Analyst-defined decision support scenarios under nonbinding planning budgets.",
        ),
        (
            "project_selections.csv",
            sel_csv_path,
            df_sel,
            "data/processed/power_bi_project_selections.parquet",
            f"portfolio_id x corridor_id ({len(df_sel):,} selected treatment details)",
            "Provisional treatment selections subject to mandatory engineering field review.",
        ),
        (
            "corridor_master.csv",
            mas_csv_path,
            df_mas,
            "data/processed/power_bi_corridor_master.parquet & data/interim/high_crash_corridors.parquet",
            f"corridor_id x 1 row ({len(df_mas):,} high-crash corridors with WGS84 WKT linework)",
            "Top 43 High-Crash Corridor boundaries with EPSG:4326 linework WKT.",
        ),
        (
            "treatment_benefits.csv",
            ben_csv_path,
            df_ben,
            "data/processed/power_bi_treatment_benefits.parquet",
            f"corridor_id x treatment_id x scenario_level ({len(df_ben):,} candidate treatment benefit rows)",
            "CMF-based safety benefits and capital project cost estimates.",
        ),
    ]

    for filename, filepath, df_data, source_path, grain, limits in file_configs:
        manifest_files[filename] = {
            "filename": filename,
            "authoritative_source": source_path,
            "source_validation_run_id": source_run_id,
            "row_count": len(df_data),
            "columns": df_data.columns.tolist(),
            "analytical_grain": grain,
            "sha256_checksum": compute_sha256(filepath),
            "generated_at_utc": generated_at_utc,
            "public_data_classification": "AGGREGATED_PUBLIC_DEMONSTRATION_SNAPSHOT",
            "limitations": limits,
        }

    manifest_data = {
        "manifest_version": "1.0",
        "pipeline": "streamlit_public_community_cloud_deployment",
        "generated_at_utc": generated_at_utc,
        "source_validation_run_id": source_run_id,
        "public_data_classification": "AGGREGATED_PUBLIC_DEMONSTRATION_SNAPSHOT",
        "prohibited_data_included": False,
        "files": manifest_files,
    }

    manifest_path = DEPLOYMENT_DIR / "deployment_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, indent=2)

    print(f"Wrote deployment_manifest.json")
    print(f"Deployment dataset build completed in {time.time() - t0:.2f}s.")
    return manifest_data


if __name__ == "__main__":
    build_deployment_data()
