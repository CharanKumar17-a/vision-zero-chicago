"""Build the high-crash corridor register CSV from config/corridors.yml.

This script has one responsibility: read the corridor definitions from
the YAML configuration and produce a validated CSV register at
data/interim/high_crash_corridor_register.csv.

It does not construct geometry, modify raw data, or assign crashes.
"""

from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[2]

CORRIDORS_CONFIG_PATH = ROOT / "config" / "corridors.yml"
SPATIAL_CONFIG_PATH = ROOT / "config" / "spatial.yml"

OUTPUT_PATH = ROOT / "data" / "interim" / "high_crash_corridor_register.csv"

REGISTER_COLUMNS = [
    "corridor_id",
    "corridor_name",
    "street_name",
    "from_street",
    "to_street",
    "source_group",
    "source_corridor_number",
    "source_name",
    "source_page",
    "cross_reference_page",
    "confidence",
    "extraction_status",
    "geometry_status",
]


def load_yaml(path: Path) -> dict[str, Any]:
    """Load and validate a YAML mapping."""
    with path.open(encoding="utf-8") as file:
        value = yaml.safe_load(file)
    if not isinstance(value, dict):
        raise ValueError(f"Expected a YAML mapping: {path}")
    return value


def compute_corridor_id(
    source_group: str,
    source_corridor_number: int,
    id_mapping: dict[str, Any],
) -> str:
    """Compute the stable project corridor ID from source numbering."""
    prefix = id_mapping["id_prefix"]
    width = id_mapping["id_width"]

    if source_group == "neighborhood":
        offset = id_mapping["neighborhood_id_offset"]
    elif source_group == "downtown":
        offset = id_mapping["downtown_id_offset"]
    else:
        raise ValueError(
            f"Unknown source_group: {source_group}"
        )

    numeric = source_corridor_number + offset
    return f"{prefix}{numeric:0{width}d}"


def validate_config_structure(
    config: dict[str, Any],
) -> list[str]:
    """Validate the corridors.yml structure before building."""
    errors: list[str] = []

    if "corridors" not in config:
        errors.append("Missing 'corridors' key in config")
        return errors

    if "id_mapping" not in config:
        errors.append("Missing 'id_mapping' key in config")
        return errors

    corridors = config["corridors"]
    if not isinstance(corridors, list):
        errors.append("'corridors' must be a list")
        return errors

    if len(corridors) != 43:
        errors.append(
            f"Expected 43 corridors, found {len(corridors)}"
        )

    required_fields = [
        "source_group",
        "source_corridor_number",
        "corridor_name",
        "street_name",
        "from_street",
        "to_street",
        "source_page",
        "cross_reference_page",
        "confidence",
        "extraction_status",
        "geometry_status",
    ]

    for i, corridor in enumerate(corridors):
        for field in required_fields:
            if field not in corridor or corridor[field] is None:
                errors.append(
                    f"Corridor {i}: missing field '{field}'"
                )

    return errors


def build_register(
    config: dict[str, Any],
) -> list[dict[str, str]]:
    """Build register rows from corridor configuration."""
    corridors = config["corridors"]
    id_mapping = config["id_mapping"]
    source_name = config["source"]["document"]

    rows: list[dict[str, str]] = []

    for corridor in corridors:
        corridor_id = compute_corridor_id(
            source_group=corridor["source_group"],
            source_corridor_number=corridor[
                "source_corridor_number"
            ],
            id_mapping=id_mapping,
        )

        row = {
            "corridor_id": corridor_id,
            "corridor_name": str(corridor["corridor_name"]),
            "street_name": str(corridor["street_name"]),
            "from_street": str(corridor["from_street"]),
            "to_street": str(corridor["to_street"]),
            "source_group": str(corridor["source_group"]),
            "source_corridor_number": str(
                corridor["source_corridor_number"]
            ),
            "source_name": source_name,
            "source_page": str(corridor["source_page"]),
            "cross_reference_page": str(
                corridor["cross_reference_page"]
            ),
            "confidence": str(corridor["confidence"]),
            "extraction_status": str(
                corridor["extraction_status"]
            ),
            "geometry_status": str(
                corridor["geometry_status"]
            ),
        }
        rows.append(row)

    return rows


def write_csv(
    path: Path,
    columns: list[str],
    rows: list[dict[str, str]],
) -> None:
    """Write rows to CSV with atomic directory creation."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    """Build the corridor register and return an exit code."""
    print("=" * 65)
    print("Building high-crash corridor register")
    print("=" * 65)

    try:
        config = load_yaml(CORRIDORS_CONFIG_PATH)
    except Exception as exc:
        print(f"FAIL: Cannot load config: {exc}")
        return 1

    errors = validate_config_structure(config)
    if errors:
        print("FAIL: Configuration validation errors:")
        for error in errors:
            print(f"  - {error}")
        return 1

    print(
        f"Config loaded: {len(config['corridors'])} corridors"
    )

    rows = build_register(config)

    corridor_ids = [r["corridor_id"] for r in rows]
    if len(set(corridor_ids)) != len(corridor_ids):
        print("FAIL: Duplicate corridor IDs detected")
        return 1

    write_csv(OUTPUT_PATH, REGISTER_COLUMNS, rows)

    print(f"Output: {OUTPUT_PATH}")
    print(f"Rows: {len(rows)}")
    print(f"Columns: {len(REGISTER_COLUMNS)}")
    print(f"ID range: {corridor_ids[0]} - {corridor_ids[-1]}")
    print("Status: PASS")
    print("=" * 65)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
