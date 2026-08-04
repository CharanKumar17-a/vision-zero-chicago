from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[2]

SOURCES_CONFIG_PATH = ROOT / "config" / "sources.yml"
ACQUISITION_CONFIG_PATH = ROOT / "config" / "acquisition.yml"
REPORT_ROOT = ROOT / "docs" / "data_quality" / "raw_snapshot_validation"


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


def calculate_sha256(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)

    return digest.hexdigest()


def parse_source_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))

    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)

    return parsed


def latest_manifest(
    source_name: str,
    acquisition_config: dict[str, Any],
) -> Path:
    manifest_root = (
        ROOT / acquisition_config["acquisition"]["manifest_root"]
    )
    candidates = sorted(
        manifest_root.glob(f"{source_name}_*_manifest.json")
    )

    if not candidates:
        raise FileNotFoundError(
            f"No acquisition manifest found for {source_name} in "
            f"{manifest_root}"
        )

    return candidates[-1]


def resolve_manifest_path(
    manifest_argument: str | None,
    source_name: str,
    acquisition_config: dict[str, Any],
) -> Path:
    if manifest_argument is None:
        return latest_manifest(source_name, acquisition_config)

    path = Path(manifest_argument)
    if not path.is_absolute():
        path = ROOT / path

    if not path.is_file():
        raise FileNotFoundError(f"Manifest does not exist: {path}")

    return path


def insert_key_batch(
    connection: sqlite3.Connection,
    key_batch: list[tuple[str]],
) -> int:
    if not key_batch:
        return 0

    changes_before = connection.total_changes
    connection.executemany(
        "INSERT OR IGNORE INTO observed_keys (key_value) VALUES (?)",
        key_batch,
    )
    inserted = connection.total_changes - changes_before
    duplicates = len(key_batch) - inserted
    key_batch.clear()

    return duplicates


def build_null_profile(
    null_counts: dict[str, int],
    total_rows: int,
) -> dict[str, dict[str, float | int]]:
    profile: dict[str, dict[str, float | int]] = {}

    for field, null_count in null_counts.items():
        rate = null_count / total_rows if total_rows else 0.0
        profile[field] = {
            "null_count": null_count,
            "null_rate": round(rate, 6),
        }

    return profile


def validate_snapshot(
    source_name: str,
    manifest_path: Path,
    source_catalog: dict[str, Any],
    acquisition_config: dict[str, Any],
) -> tuple[dict[str, Any], Path]:
    manifest = load_json(manifest_path)
    acquisition_source = acquisition_config["sources"][source_name]
    source_key = acquisition_source["source_config_key"]
    source_config = source_catalog["sources"][source_key]

    selected_fields = acquisition_source["select_fields"]
    primary_key = source_config["primary_key"]
    date_field = acquisition_source["date_field"]

    history_start = parse_source_timestamp(
        acquisition_config["acquisition"]["history_start"]
    )
    history_end_exclusive = parse_source_timestamp(
        acquisition_config["acquisition"]["history_end_exclusive"]
    )

    hard_failures: list[str] = []
    limitations: list[str] = []

    if manifest.get("status") != "PASS":
        hard_failures.append(
            f"Manifest status is {manifest.get('status')}, not PASS"
        )

    if manifest.get("source_name") != source_name:
        hard_failures.append(
            "Manifest source does not match the requested source"
        )

    if manifest.get("selected_fields") != selected_fields:
        hard_failures.append(
            "Manifest fields do not match the current acquisition contract"
        )

    snapshot_directory = ROOT / manifest["snapshot_directory"]
    if not snapshot_directory.is_dir():
        hard_failures.append(
            f"Snapshot directory does not exist: {snapshot_directory}"
        )

    manifest_parts = manifest.get("parts", [])
    physical_parts = sorted(snapshot_directory.glob("*.csv.gz"))

    if len(physical_parts) != len(manifest_parts):
        hard_failures.append(
            "Physical part count does not match the manifest: "
            f"physical={len(physical_parts)}, "
            f"manifest={len(manifest_parts)}"
        )

    null_counts = {field: 0 for field in selected_fields}
    total_rows = 0
    missing_primary_keys = 0
    duplicate_primary_keys = 0
    invalid_dates = 0
    dates_outside_window = 0
    minimum_date: datetime | None = None
    maximum_date: datetime | None = None

    coordinate_fields_present = {
        "latitude",
        "longitude",
    }.issubset(selected_fields)
    valid_coordinate_pairs = 0
    missing_coordinate_pairs = 0
    incomplete_coordinate_pairs = 0
    invalid_coordinate_pairs = 0

    part_results: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory(
        prefix="vision_zero_key_validation_"
    ) as temporary_directory:
        database_path = Path(temporary_directory) / "keys.sqlite"
        connection = sqlite3.connect(database_path)
        connection.execute("PRAGMA journal_mode=OFF")
        connection.execute("PRAGMA synchronous=OFF")
        connection.execute(
            "CREATE TABLE observed_keys ("
            "key_value TEXT NOT NULL PRIMARY KEY"
            ")"
        )

        key_batch: list[tuple[str]] = []

        for index, part_record in enumerate(manifest_parts, start=1):
            relative_path = part_record.get("relative_path")
            part_path = ROOT / relative_path
            part_issues: list[str] = []

            if not part_path.is_file():
                part_issues.append("File is missing")
                hard_failures.append(f"Missing raw part: {relative_path}")
                part_results.append(
                    {
                        "part_number": part_record.get("part_number"),
                        "relative_path": relative_path,
                        "status": "FAIL",
                        "issues": part_issues,
                    }
                )
                continue

            observed_size = part_path.stat().st_size
            expected_size = int(part_record.get("compressed_bytes", -1))
            if observed_size != expected_size:
                part_issues.append(
                    f"Compressed size mismatch: expected={expected_size}, "
                    f"observed={observed_size}"
                )

            observed_checksum = calculate_sha256(part_path)
            expected_checksum = part_record.get("sha256")
            if observed_checksum != expected_checksum:
                part_issues.append("SHA-256 checksum mismatch")

            observed_part_rows = 0

            try:
                with gzip.open(
                    part_path,
                    mode="rt",
                    encoding="utf-8-sig",
                    newline="",
                ) as file:
                    reader = csv.DictReader(file)
                    observed_header = reader.fieldnames or []
                    observed_header = [
                        field.lstrip("\ufeff")
                        for field in observed_header
                    ]

                    if observed_header != selected_fields:
                        part_issues.append(
                            "CSV header does not match the acquisition contract"
                        )

                    for row in reader:
                        observed_part_rows += 1
                        total_rows += 1

                        for field in selected_fields:
                            value = row.get(field)
                            if value is None or value.strip() == "":
                                null_counts[field] += 1

                        key_value = (row.get(primary_key) or "").strip()
                        if not key_value:
                            missing_primary_keys += 1
                        else:
                            key_batch.append((key_value,))
                            if len(key_batch) >= 10000:
                                duplicate_primary_keys += insert_key_batch(
                                    connection,
                                    key_batch,
                                )

                        date_value = (row.get(date_field) or "").strip()
                        if date_value:
                            try:
                                parsed_date = parse_source_timestamp(date_value)
                                if minimum_date is None or parsed_date < minimum_date:
                                    minimum_date = parsed_date
                                if maximum_date is None or parsed_date > maximum_date:
                                    maximum_date = parsed_date
                                if not (
                                    history_start
                                    <= parsed_date
                                    < history_end_exclusive
                                ):
                                    dates_outside_window += 1
                            except ValueError:
                                invalid_dates += 1

                        if coordinate_fields_present:
                            latitude_text = (
                                row.get("latitude") or ""
                            ).strip()
                            longitude_text = (
                                row.get("longitude") or ""
                            ).strip()

                            if not latitude_text and not longitude_text:
                                missing_coordinate_pairs += 1
                            elif not latitude_text or not longitude_text:
                                incomplete_coordinate_pairs += 1
                            else:
                                try:
                                    latitude = float(latitude_text)
                                    longitude = float(longitude_text)
                                    if (
                                        -90 <= latitude <= 90
                                        and -180 <= longitude <= 180
                                    ):
                                        valid_coordinate_pairs += 1
                                    else:
                                        invalid_coordinate_pairs += 1
                                except ValueError:
                                    invalid_coordinate_pairs += 1

            except (OSError, UnicodeError, csv.Error) as error:
                part_issues.append(
                    f"Unable to read compressed CSV: "
                    f"{type(error).__name__}: {error}"
                )

            expected_part_rows = int(part_record.get("row_count", -1))
            if observed_part_rows != expected_part_rows:
                part_issues.append(
                    f"Part row-count mismatch: expected={expected_part_rows}, "
                    f"observed={observed_part_rows}"
                )

            if part_issues:
                hard_failures.extend(
                    f"{relative_path}: {issue}" for issue in part_issues
                )

            part_results.append(
                {
                    "part_number": part_record.get("part_number"),
                    "relative_path": relative_path,
                    "expected_rows": expected_part_rows,
                    "observed_rows": observed_part_rows,
                    "expected_compressed_bytes": expected_size,
                    "observed_compressed_bytes": observed_size,
                    "sha256_matches": observed_checksum == expected_checksum,
                    "status": "PASS" if not part_issues else "FAIL",
                    "issues": part_issues,
                }
            )

            print(
                f"Validated part {index:05d}/{len(manifest_parts):05d}: "
                f"{observed_part_rows:,} rows | "
                f"{'PASS' if not part_issues else 'FAIL'}"
            )

        duplicate_primary_keys += insert_key_batch(connection, key_batch)
        connection.commit()
        unique_primary_keys = connection.execute(
            "SELECT COUNT(*) FROM observed_keys"
        ).fetchone()[0]
        connection.close()

    manifest_downloaded_rows = int(manifest.get("downloaded_rows", -1))
    if total_rows != manifest_downloaded_rows:
        hard_failures.append(
            "Total observed rows do not match the manifest: "
            f"observed={total_rows}, manifest={manifest_downloaded_rows}"
        )

    if missing_primary_keys:
        hard_failures.append(
            f"Missing primary keys: {missing_primary_keys}"
        )

    if duplicate_primary_keys:
        hard_failures.append(
            f"Duplicate primary keys: {duplicate_primary_keys}"
        )

    if invalid_dates:
        hard_failures.append(f"Invalid dates: {invalid_dates}")

    if dates_outside_window:
        hard_failures.append(
            f"Dates outside acquisition window: {dates_outside_window}"
        )

    if invalid_coordinate_pairs:
        hard_failures.append(
            f"Invalid coordinate pairs: {invalid_coordinate_pairs}"
        )

    coordinate_profile: dict[str, Any] | None = None
    if coordinate_fields_present:
        coordinate_coverage_rate = (
            valid_coordinate_pairs / total_rows if total_rows else 0.0
        )
        coordinate_profile = {
            "valid_coordinate_pairs": valid_coordinate_pairs,
            "missing_coordinate_pairs": missing_coordinate_pairs,
            "incomplete_coordinate_pairs": incomplete_coordinate_pairs,
            "invalid_coordinate_pairs": invalid_coordinate_pairs,
            "valid_coordinate_coverage_rate": round(
                coordinate_coverage_rate,
                6,
            ),
        }

        if missing_coordinate_pairs or incomplete_coordinate_pairs:
            limitations.append(
                "Rows without complete coordinates cannot be assigned to "
                "corridor geometry without an additional location-recovery "
                "rule or exclusion."
            )

    integrity_status = "PASS" if not hard_failures else "FAIL"
    downstream_readiness = (
        "PASS_WITH_LIMITATIONS" if limitations else "PASS"
    )

    report: dict[str, Any] = {
        "validated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_name": source_name,
        "run_id": manifest.get("run_id"),
        "manifest_path": str(manifest_path.relative_to(ROOT)),
        "snapshot_directory": manifest.get("snapshot_directory"),
        "acquisition_integrity_status": integrity_status,
        "downstream_readiness": downstream_readiness,
        "expected_rows": manifest_downloaded_rows,
        "observed_rows": total_rows,
        "manifest_part_count": len(manifest_parts),
        "physical_part_count": len(physical_parts),
        "primary_key": primary_key,
        "missing_primary_keys": missing_primary_keys,
        "duplicate_primary_keys": duplicate_primary_keys,
        "unique_primary_keys": unique_primary_keys,
        "date_field": date_field,
        "minimum_date": minimum_date.isoformat() if minimum_date else None,
        "maximum_date": maximum_date.isoformat() if maximum_date else None,
        "invalid_dates": invalid_dates,
        "dates_outside_window": dates_outside_window,
        "coordinate_profile": coordinate_profile,
        "null_profile": build_null_profile(null_counts, total_rows),
        "hard_failures": hard_failures,
        "limitations": limitations,
        "parts": part_results,
    }

    report_path = (
        REPORT_ROOT
        / f"{source_name}_{manifest.get('run_id')}_validation.json"
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)

    with report_path.open(
        "w",
        encoding="utf-8",
        newline="\n",
    ) as file:
        json.dump(report, file, indent=2)

    return report, report_path


def main() -> int:
    source_catalog = load_yaml(SOURCES_CONFIG_PATH)
    acquisition_config = load_yaml(ACQUISITION_CONFIG_PATH)
    available_sources = list(acquisition_config["sources"])

    parser = argparse.ArgumentParser(
        description=(
            "Validate an acquired raw snapshot against its manifest and "
            "acquisition contract."
        )
    )
    parser.add_argument(
        "--source",
        required=True,
        choices=available_sources,
    )
    parser.add_argument(
        "--manifest",
        help=(
            "Optional manifest path. The latest manifest for the source is "
            "used when omitted."
        ),
    )
    args = parser.parse_args()

    manifest_path = resolve_manifest_path(
        manifest_argument=args.manifest,
        source_name=args.source,
        acquisition_config=acquisition_config,
    )

    print("Raw snapshot validation")
    print("=" * 75)
    print("Source:", args.source)
    print("Manifest:", manifest_path)
    print("=" * 75)

    report, report_path = validate_snapshot(
        source_name=args.source,
        manifest_path=manifest_path,
        source_catalog=source_catalog,
        acquisition_config=acquisition_config,
    )

    print("=" * 75)
    print("Observed rows:", f"{report['observed_rows']:,}")
    print("Missing primary keys:", report["missing_primary_keys"])
    print("Duplicate primary keys:", report["duplicate_primary_keys"])
    print("Invalid dates:", report["invalid_dates"])
    print("Dates outside window:", report["dates_outside_window"])
    print("Minimum date:", report["minimum_date"])
    print("Maximum date:", report["maximum_date"])

    coordinate_profile = report["coordinate_profile"]
    if coordinate_profile:
        print(
            "Valid coordinate coverage:",
            f"{coordinate_profile['valid_coordinate_coverage_rate']:.2%}",
        )
        print(
            "Missing coordinate pairs:",
            coordinate_profile["missing_coordinate_pairs"],
        )
        print(
            "Incomplete coordinate pairs:",
            coordinate_profile["incomplete_coordinate_pairs"],
        )

    print(
        "Acquisition integrity status:",
        report["acquisition_integrity_status"],
    )
    print("Downstream readiness:", report["downstream_readiness"])
    print("Report saved to:", report_path)

    if report["hard_failures"]:
        print("Hard failures:")
        for failure in report["hard_failures"]:
            print("-", failure)

    return 0 if report["acquisition_integrity_status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())