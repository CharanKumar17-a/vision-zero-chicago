"""Orchestrate DuckDB SQL Decision-Output Mart for Power BI & Streamlit (Phase 5A).

Contract: docs/data_quality/cleaning_contract.md, spatial_assignment_contract.md
Decision: D019 (DuckDB local SQL analytics & Power BI serving layer)

Executes sql/05_create_decision_mart_views.sql in DuckDB (data/processed/vision_zero_analytics.duckdb),
verifies view row counts, and exports decision-support serving layer datasets to data/processed/.
"""

from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import duckdb
import geopandas as gpd
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SQL_FILE = ROOT / "sql" / "05_create_decision_mart_views.sql"
DB_PATH = ROOT / "data" / "processed" / "vision_zero_analytics.duckdb"
CORRIDORS_GEO_PATH = ROOT / "data" / "interim" / "high_crash_corridors.parquet"

SUMMARY_PARQUET = ROOT / "data" / "processed" / "power_bi_portfolio_summary.parquet"
SUMMARY_CSV = ROOT / "data" / "processed" / "power_bi_portfolio_summary.csv"
SELECTIONS_PARQUET = ROOT / "data" / "processed" / "power_bi_project_selections.parquet"
SELECTIONS_CSV = ROOT / "data" / "processed" / "power_bi_project_selections.csv"
CORRIDOR_MASTER_PARQUET = ROOT / "data" / "processed" / "power_bi_corridor_master.parquet"
CORRIDOR_MASTER_CSV = ROOT / "data" / "processed" / "power_bi_corridor_master.csv"
BENEFITS_PARQUET = ROOT / "data" / "processed" / "power_bi_treatment_benefits.parquet"
BENEFITS_CSV = ROOT / "data" / "processed" / "power_bi_treatment_benefits.csv"


def prepare_spatial_corridor_df(corridors_geo_path: Path = CORRIDORS_GEO_PATH) -> pd.DataFrame:
    """Extract governed geometry, WKT representation, CRS, and centroids in WGS84."""
    gdf = gpd.read_parquet(corridors_geo_path)
    centroids_3435 = gdf.geometry.centroid
    centroids_4326 = centroids_3435.to_crs(epsg=4326)

    df_spatial = pd.DataFrame({
        "corridor_id": gdf["corridor_id"],
        "centroid_latitude": centroids_4326.y,
        "centroid_longitude": centroids_4326.x,
        "geometry_wkt": gdf.geometry.apply(lambda g: g.wkt),
        "geometry_crs": "EPSG:3435",
    })
    return df_spatial


def build_decision_output_mart(
    sql_file: Path = SQL_FILE,
    db_path: Path = DB_PATH,
    corridors_geo_path: Path = CORRIDORS_GEO_PATH,
    in_memory: bool = False,
) -> Dict[str, Any]:
    """Execute SQL decision mart views and export serving layer datasets."""
    t0 = time.time()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    print("=" * 80)
    print("BUILDING DECISION-OUTPUT MART FOR POWER BI & STREAMLIT (PHASE 5A)")
    print("=" * 80)

    if not sql_file.exists():
        raise FileNotFoundError(f"Required SQL file missing: {sql_file}")

    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(db_path) if not in_memory else ":memory:")

    # Register spatial corridor metadata view in DuckDB
    df_spatial = prepare_spatial_corridor_df(corridors_geo_path)
    conn.register("temp_corridor_spatial", df_spatial)

    sql_script = sql_file.read_text(encoding="utf-8")
    conn.execute(sql_script)

    # Query row counts from created views
    summary_count = int(conn.execute("SELECT COUNT(*) FROM vw_power_bi_portfolio_summary").fetchone()[0])
    selections_count = int(conn.execute("SELECT COUNT(*) FROM vw_power_bi_project_selections").fetchone()[0])
    master_count = int(conn.execute("SELECT COUNT(*) FROM vw_power_bi_corridor_master").fetchone()[0])
    benefits_count = int(conn.execute("SELECT COUNT(*) FROM vw_power_bi_treatment_benefits").fetchone()[0])

    # Export datasets
    df_summary = conn.execute("SELECT * FROM vw_power_bi_portfolio_summary").df()
    df_selections = conn.execute("SELECT * FROM vw_power_bi_project_selections").df()
    df_master = conn.execute("SELECT * FROM vw_power_bi_corridor_master").df()
    df_benefits = conn.execute("SELECT * FROM vw_power_bi_treatment_benefits").df()

    df_summary.to_parquet(SUMMARY_PARQUET, index=False)
    df_summary.to_csv(SUMMARY_CSV, index=False)

    df_selections.to_parquet(SELECTIONS_PARQUET, index=False)
    df_selections.to_csv(SELECTIONS_CSV, index=False)

    df_master.to_parquet(CORRIDOR_MASTER_PARQUET, index=False)
    df_master.to_csv(CORRIDOR_MASTER_CSV, index=False)

    df_benefits.to_parquet(BENEFITS_PARQUET, index=False)
    df_benefits.to_csv(BENEFITS_CSV, index=False)

    conn.close()
    elapsed = time.time() - t0

    print(f"Decision mart built successfully in {elapsed:.2f}s.")
    print(f"Portfolio Summary Rows:   {summary_count:5d} -> {SUMMARY_PARQUET}")
    print(f"Project Selections Rows:  {selections_count:5d} -> {SELECTIONS_PARQUET}")
    print(f"Corridor Master Rows:     {master_count:5d} -> {CORRIDOR_MASTER_PARQUET}")
    print(f"Treatment Benefits Rows:  {benefits_count:5d} -> {BENEFITS_PARQUET}")
    print("=" * 80)

    metrics = {
        "run_id": run_id,
        "summary_rows": summary_count,
        "selections_rows": selections_count,
        "master_rows": master_count,
        "benefits_rows": benefits_count,
        "elapsed_seconds": round(elapsed, 4),
    }
    return metrics


if __name__ == "__main__":
    build_decision_output_mart()
