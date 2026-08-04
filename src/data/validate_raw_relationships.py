from __future__ import annotations

import csv
import gzip
import json
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import yaml


ROOT = Path(__file__).resolve().parents[2]

ACQUISITION_CONFIG_PATH = ROOT / "config" / "acquisition.yml"
REPORT_PATH = (
    ROOT
    / "docs"
    / "data_quality"
    / "raw_relationship_validation.json"
)


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as file:
        data = yaml.safe_load(file)

    if not isinstance(data, dict):
        raise ValueError(f"Expected YAML mapping in {path}")

    return data


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in {path}")

    return data


def latest_manifest(
    source_name: str,
    acquisition_config: dict[str, Any],
) -> tuple[Path, dict[str, Any]]:
    manifest_root = (
        ROOT / acquisition_config["acquisition"]["manifest_root"]
    )
    candidates = sorted(
        manifest_root.glob(f"{source_name}_*_manifest.json")
    )

    if not candidates:
        raise FileNotFoundError(
            f"No acquisition manifest found for {source_name}"
        )

    manifest_path = candidates[-1]
    manifest = load_json(manifest_path)

    if manifest.get("status") != "PASS":
        raise ValueError(
            f"Latest {source_name} manifest is not PASS: "
            f"{manifest_path}"
        )

    return manifest_path, manifest


def iter_selected_rows(
    manifest: dict[str, Any],
    required_columns: list[str],
) -> Iterator[tuple[str, ...]]:
    for part in manifest["parts"]:
        part_path = ROOT / part["relative_path"]

        with gzip.open(
            part_path,
            mode="rt",
            encoding="utf-8-sig",
            newline="",
        ) as file:
            reader = csv.DictReader(file)
            fieldnames = set(reader.fieldnames or [])
            missing_columns = set(required_columns) - fieldnames

            if missing_columns:
                raise ValueError(
                    f"{part_path} is missing columns: "
                    f"{sorted(missing_columns)}"
                )

            for row in reader:
                yield tuple(
                    (row.get(column) or "").strip()
                    for column in required_columns
                )


def insert_source_rows(
    connection: sqlite3.Connection,
    table_name: str,
    insert_sql: str,
    rows: Iterator[tuple[str, ...]],
    expected_rows: int,
) -> int:
    batch: list[tuple[str, ...]] = []
    inserted_rows = 0

    print(f"Loading {table_name} relationship fields...")

    for row in rows:
        batch.append(row)

        if len(batch) >= 20000:
            connection.executemany(insert_sql, batch)
            inserted_rows += len(batch)
            batch.clear()

            if inserted_rows % 200000 == 0:
                print(
                    f"{table_name}: {inserted_rows:,}/"
                    f"{expected_rows:,} rows loaded"
                )

    if batch:
        connection.executemany(insert_sql, batch)
        inserted_rows += len(batch)

    connection.commit()

    print(
        f"{table_name}: {inserted_rows:,}/"
        f"{expected_rows:,} rows loaded"
    )

    if inserted_rows != expected_rows:
        raise ValueError(
            f"{table_name} load count mismatch: "
            f"expected={expected_rows}, observed={inserted_rows}"
        )

    return inserted_rows


def scalar(
    connection: sqlite3.Connection,
    query: str,
) -> int | float:
    value = connection.execute(query).fetchone()[0]
    return value if value is not None else 0


def build_database(
    database_path: Path,
    manifests: dict[str, dict[str, Any]],
) -> sqlite3.Connection:
    connection = sqlite3.connect(database_path)
    connection.execute("PRAGMA journal_mode=OFF")
    connection.execute("PRAGMA synchronous=OFF")
    connection.execute("PRAGMA temp_store=MEMORY")

    connection.executescript(
        """
        CREATE TABLE crashes (
            crash_record_id TEXT NOT NULL PRIMARY KEY,
            crash_date TEXT NOT NULL
        );

        CREATE TABLE vehicles (
            crash_unit_id TEXT NOT NULL PRIMARY KEY,
            crash_record_id TEXT NOT NULL,
            crash_date TEXT NOT NULL
        );

        CREATE TABLE people (
            person_id TEXT NOT NULL PRIMARY KEY,
            crash_record_id TEXT NOT NULL,
            crash_date TEXT NOT NULL
        );
        """
    )

    insert_source_rows(
        connection=connection,
        table_name="crashes",
        insert_sql=(
            "INSERT INTO crashes "
            "(crash_record_id, crash_date) VALUES (?, ?)"
        ),
        rows=iter_selected_rows(
            manifests["crashes"],
            ["crash_record_id", "crash_date"],
        ),
        expected_rows=int(manifests["crashes"]["downloaded_rows"]),
    )

    insert_source_rows(
        connection=connection,
        table_name="vehicles",
        insert_sql=(
            "INSERT INTO vehicles "
            "(crash_unit_id, crash_record_id, crash_date) "
            "VALUES (?, ?, ?)"
        ),
        rows=iter_selected_rows(
            manifests["vehicles"],
            ["crash_unit_id", "crash_record_id", "crash_date"],
        ),
        expected_rows=int(manifests["vehicles"]["downloaded_rows"]),
    )

    insert_source_rows(
        connection=connection,
        table_name="people",
        insert_sql=(
            "INSERT INTO people "
            "(person_id, crash_record_id, crash_date) "
            "VALUES (?, ?, ?)"
        ),
        rows=iter_selected_rows(
            manifests["people"],
            ["person_id", "crash_record_id", "crash_date"],
        ),
        expected_rows=int(manifests["people"]["downloaded_rows"]),
    )

    print("Creating child relationship indexes...")
    connection.execute(
        "CREATE INDEX vehicles_crash_record_id_idx "
        "ON vehicles (crash_record_id)"
    )
    connection.execute(
        "CREATE INDEX people_crash_record_id_idx "
        "ON people (crash_record_id)"
    )
    connection.commit()

    return connection


def calculate_relationship_metrics(
    connection: sqlite3.Connection,
) -> dict[str, Any]:
    crash_rows = int(scalar(connection, "SELECT COUNT(*) FROM crashes"))
    vehicle_rows = int(scalar(connection, "SELECT COUNT(*) FROM vehicles"))
    people_rows = int(scalar(connection, "SELECT COUNT(*) FROM people"))

    vehicle_orphans = int(
        scalar(
            connection,
            """
            SELECT COUNT(*)
            FROM vehicles AS v
            LEFT JOIN crashes AS c
                ON v.crash_record_id = c.crash_record_id
            WHERE c.crash_record_id IS NULL
            """,
        )
    )
    people_orphans = int(
        scalar(
            connection,
            """
            SELECT COUNT(*)
            FROM people AS p
            LEFT JOIN crashes AS c
                ON p.crash_record_id = c.crash_record_id
            WHERE c.crash_record_id IS NULL
            """,
        )
    )

    vehicle_date_mismatches = int(
        scalar(
            connection,
            """
            SELECT COUNT(*)
            FROM vehicles AS v
            INNER JOIN crashes AS c
                ON v.crash_record_id = c.crash_record_id
            WHERE v.crash_date <> c.crash_date
            """,
        )
    )
    people_date_mismatches = int(
        scalar(
            connection,
            """
            SELECT COUNT(*)
            FROM people AS p
            INNER JOIN crashes AS c
                ON p.crash_record_id = c.crash_record_id
            WHERE p.crash_date <> c.crash_date
            """,
        )
    )

    crashes_with_vehicles = int(
        scalar(
            connection,
            """
            SELECT COUNT(DISTINCT v.crash_record_id)
            FROM vehicles AS v
            INNER JOIN crashes AS c
                ON v.crash_record_id = c.crash_record_id
            """,
        )
    )
    crashes_with_people = int(
        scalar(
            connection,
            """
            SELECT COUNT(DISTINCT p.crash_record_id)
            FROM people AS p
            INNER JOIN crashes AS c
                ON p.crash_record_id = c.crash_record_id
            """,
        )
    )

    maximum_units_per_crash = int(
        scalar(
            connection,
            """
            SELECT MAX(unit_count)
            FROM (
                SELECT COUNT(*) AS unit_count
                FROM vehicles
                GROUP BY crash_record_id
            )
            """,
        )
    )
    maximum_people_per_crash = int(
        scalar(
            connection,
            """
            SELECT MAX(person_count)
            FROM (
                SELECT COUNT(*) AS person_count
                FROM people
                GROUP BY crash_record_id
            )
            """,
        )
    )

    return {
        "crash_rows": crash_rows,
        "vehicle_rows": vehicle_rows,
        "people_rows": people_rows,
        "vehicle_orphan_rows": vehicle_orphans,
        "vehicle_join_coverage_rate": round(
            (vehicle_rows - vehicle_orphans) / vehicle_rows,
            8,
        ),
        "people_orphan_rows": people_orphans,
        "people_join_coverage_rate": round(
            (people_rows - people_orphans) / people_rows,
            8,
        ),
        "vehicle_crash_date_mismatches": vehicle_date_mismatches,
        "people_crash_date_mismatches": people_date_mismatches,
        "crashes_with_vehicle_records": crashes_with_vehicles,
        "crashes_without_vehicle_records": (
            crash_rows - crashes_with_vehicles
        ),
        "crash_vehicle_parent_coverage_rate": round(
            crashes_with_vehicles / crash_rows,
            8,
        ),
        "crashes_with_people_records": crashes_with_people,
        "crashes_without_people_records": crash_rows - crashes_with_people,
        "crash_people_parent_coverage_rate": round(
            crashes_with_people / crash_rows,
            8,
        ),
        "maximum_vehicle_units_per_crash": maximum_units_per_crash,
        "maximum_people_per_crash": maximum_people_per_crash,
    }


def main() -> int:
    acquisition_config = load_yaml(ACQUISITION_CONFIG_PATH)

    manifest_paths: dict[str, Path] = {}
    manifests: dict[str, dict[str, Any]] = {}

    for source_name in ("crashes", "vehicles", "people"):
        manifest_path, manifest = latest_manifest(
            source_name,
            acquisition_config,
        )
        manifest_paths[source_name] = manifest_path
        manifests[source_name] = manifest

    print("Raw relationship validation")
    print("=" * 75)
    for source_name, path in manifest_paths.items():
        print(f"{source_name}: {path.name}")
    print("=" * 75)

    interim_root = ROOT / "data" / "interim"
    interim_root.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(
        prefix="raw_relationship_validation_",
        dir=interim_root,
    ) as temporary_directory:
        database_path = Path(temporary_directory) / "relationships.sqlite"
        connection = build_database(database_path, manifests)

        try:
            metrics = calculate_relationship_metrics(connection)
        finally:
            connection.close()

    failures: list[str] = []
    limitations: list[str] = []

    if metrics["vehicle_orphan_rows"]:
        failures.append(
            f"Vehicle orphan rows: {metrics['vehicle_orphan_rows']}"
        )
    if metrics["people_orphan_rows"]:
        failures.append(
            f"People orphan rows: {metrics['people_orphan_rows']}"
        )
    if metrics["vehicle_crash_date_mismatches"]:
        failures.append(
            "Vehicle/crash date mismatches: "
            f"{metrics['vehicle_crash_date_mismatches']}"
        )
    if metrics["people_crash_date_mismatches"]:
        failures.append(
            "People/crash date mismatches: "
            f"{metrics['people_crash_date_mismatches']}"
        )

    if metrics["crashes_without_vehicle_records"]:
        limitations.append(
            "Some crash records have no corresponding vehicle record."
        )
    if metrics["crashes_without_people_records"]:
        limitations.append(
            "Some crash records have no corresponding people record."
        )

    integrity_status = "PASS" if not failures else "FAIL"
    downstream_readiness = (
        "PASS_WITH_LIMITATIONS" if limitations else "PASS"
    )

    report = {
        "validated_at_utc": datetime.now(timezone.utc).isoformat(),
        "manifests": {
            source_name: str(path.relative_to(ROOT))
            for source_name, path in manifest_paths.items()
        },
        "relationship_integrity_status": integrity_status,
        "downstream_readiness": downstream_readiness,
        "metrics": metrics,
        "failures": failures,
        "limitations": limitations,
    }

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with REPORT_PATH.open(
        "w",
        encoding="utf-8",
        newline="\n",
    ) as file:
        json.dump(report, file, indent=2)

    print("=" * 75)
    print("Vehicle orphan rows:", metrics["vehicle_orphan_rows"])
    print("People orphan rows:", metrics["people_orphan_rows"])
    print(
        "Vehicle/crash date mismatches:",
        metrics["vehicle_crash_date_mismatches"],
    )
    print(
        "People/crash date mismatches:",
        metrics["people_crash_date_mismatches"],
    )
    print(
        "Crashes without vehicle records:",
        metrics["crashes_without_vehicle_records"],
    )
    print(
        "Crashes without people records:",
        metrics["crashes_without_people_records"],
    )
    print(
        "Maximum vehicle units per crash:",
        metrics["maximum_vehicle_units_per_crash"],
    )
    print(
        "Maximum people per crash:",
        metrics["maximum_people_per_crash"],
    )
    print("Relationship integrity status:", integrity_status)
    print("Downstream readiness:", downstream_readiness)
    print("Report saved to:", REPORT_PATH)

    if failures:
        print("Failures:")
        for failure in failures:
            print("-", failure)

    if limitations:
        print("Limitations:")
        for limitation in limitations:
            print("-", limitation)

    return 0 if integrity_status == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
