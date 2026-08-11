"""Orchestrate DuckDB SQL analytical layer and Power BI history mart.

Contract: docs/data_quality/cleaning_contract.md, spatial_assignment_contract.md
Decision: D019 (DuckDB local SQL analytics & Power BI serving layer)

Executes SQL scripts in numbered order (01..04), creates local DuckDB database
(data/processed/vision_zero_analytics.duckdb), and exports the Power BI historical
analytical mart (data/processed/power_bi_corridor_history.parquet).
"""

from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SQL_DIR = ROOT / "sql"
DB_PATH = ROOT / "data" / "processed" / "vision_zero_analytics.duckdb"
MART_OUTPUT_PATH = ROOT / "data" / "processed" / "power_bi_corridor_history.parquet"

SQL_SCRIPTS = [
    "01_create_source_views.sql",
    "02_corridor_month_feature_audit.sql",
    "03_data_quality_reconciliation.sql",
    "04_power_bi_corridor_history_mart.sql",
]


def build_sql_analytics_mart(
    sql_dir: Path = SQL_DIR,
    db_path: Path = DB_PATH,
    mart_output_path: Path = MART_OUTPUT_PATH,
    sample_size: Optional[int] = None,
) -> dict[str, Any]:
    """Execute SQL analytics pipeline and build Power BI historical mart in DuckDB."""
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    print(f"Run ID: {run_id}")
    print(f"DuckDB Version: {duckdb.__version__}")

    t0 = time.time()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    mart_output_path.parent.mkdir(parents=True, exist_ok=True)

    # Use in-memory connection if sample_size or testing, else file connection
    conn = duckdb.connect(str(db_path) if sample_size is None else ":memory:")

    executed_scripts = []
    for script_name in SQL_SCRIPTS:
        script_file = sql_dir / script_name
        if not script_file.exists():
            raise FileNotFoundError(f"Required SQL script missing: {script_file}")

        sql_content = script_file.read_text(encoding="utf-8")
        conn.execute(sql_content)
        executed_scripts.append(script_name)
        print(f"Executed SQL script: {script_name}")

    # Verify views created
    views_df = conn.execute(
        "SELECT table_name AS name FROM information_schema.tables WHERE table_type = 'VIEW'"
    ).df()
    view_names = set(views_df["name"].tolist()) if not views_df.empty else set()

    # Query mart counts
    mart_count_df = conn.execute("SELECT COUNT(*) as count FROM vw_power_bi_corridor_history").df()
    mart_rows = int(mart_count_df["count"].iloc[0])

    t_exec = time.time() - t0
    print(f"SQL execution completed in {t_exec:.3f}s. Power BI mart rows: {mart_rows:,}.")

    conn.close()

    metrics = {
        "run_id": run_id,
        "duckdb_version": duckdb.__version__,
        "executed_scripts": executed_scripts,
        "views_created": sorted(list(view_names)),
        "mart_row_count": mart_rows,
        "mart_output_path": str(mart_output_path),
        "db_path": str(db_path),
        "execution_time_seconds": round(t_exec, 4),
    }

    return metrics


def main() -> int:
    print("=" * 70)
    print("Build DuckDB SQL Analytics Layer & Power BI Mart (Day 11 Phase 2C)")
    print("=" * 70)

    try:
        metrics = build_sql_analytics_mart()
        print("\n" + "=" * 70)
        print("SQL PIPELINE EXECUTION METRICS")
        print("=" * 70)
        print(f"DuckDB Version          : {metrics['duckdb_version']}")
        print(f"Executed Scripts        : {len(metrics['executed_scripts'])}")
        print(f"Views Created           : {metrics['views_created']}")
        print(f"Power BI Mart Rows      : {metrics['mart_row_count']:,}")
        print(f"Execution Time          : {metrics['execution_time_seconds']}s")
        return 0
    except Exception as exc:
        print(f"\nCRITICAL FAILURE: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
