"""Independently validate the high-crash corridor register.

This script reads the corridor register CSV and the corridor
configuration, performs comprehensive validation checks, and produces
permanent evidence reports.

It never modifies the register CSV, the configuration, or raw data.
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

REGISTER_PATH = (
    ROOT / "data" / "interim" / "high_crash_corridor_register.csv"
)

LATEST_REPORT_PATH = (
    ROOT
    / "docs"
    / "data_quality"
    / "corridor_register_validation.json"
)

HISTORICAL_REPORT_DIR = (
    ROOT
    / "docs"
    / "data_quality"
    / "corridor_register_validation_runs"
)

EXPECTED_CORRIDOR_COUNT = 43
EXPECTED_NEIGHBORHOOD_COUNT = 31
EXPECTED_DOWNTOWN_COUNT = 12

VALID_SOURCE_GROUPS = {"neighborhood", "downtown"}
VALID_CROSS_REFERENCE_PAGES = {27, 28, 29}
VALID_CONFIDENCE_VALUES = {"HIGH", "MEDIUM"}

VALID_EXTRACTION_STATUSES = {
    "verified_first_pass",
    "verified_second_pass",
    "unverified",
}

VALID_GEOMETRY_STATUSES = {
    "pending_construction",
    "constructed",
    "validated",
    "failed",
}

REQUIRED_COLUMNS = [
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

DOCUMENTED_ALIASES = [
    {
        "canonical_name": "Lake Shore Drive",
        "matching_alias": "Lake Shore",
    },
    {
        "canonical_name": "Western Ave/Blvd",
        "matching_alias": "Western",
    },
]


def load_yaml(path: Path) -> dict[str, Any]:
    """Load and validate a YAML mapping."""
    with path.open(encoding="utf-8") as file:
        value = yaml.safe_load(file)
    if not isinstance(value, dict):
        raise ValueError(f"Expected a YAML mapping: {path}")
    return value


def load_register(path: Path) -> list[dict[str, str]]:
    """Load the corridor register CSV."""
    with path.open(encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        return list(reader)


def display_path(path: Path) -> str:
    """Return a display-friendly relative path."""
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def check_row_count(
    rows: list[dict[str, str]],
) -> list[dict[str, Any]]:
    """Check that the register contains exactly 43 rows."""
    checks: list[dict[str, Any]] = []
    count = len(rows)
    checks.append(
        {
            "check": "row_count",
            "expected": EXPECTED_CORRIDOR_COUNT,
            "actual": count,
            "passed": count == EXPECTED_CORRIDOR_COUNT,
            "severity": "critical",
        }
    )
    return checks


def check_required_columns(
    rows: list[dict[str, str]],
) -> list[dict[str, Any]]:
    """Check that all required columns are present."""
    checks: list[dict[str, Any]] = []
    if not rows:
        checks.append(
            {
                "check": "required_columns",
                "passed": False,
                "severity": "critical",
                "detail": "No rows to check",
            }
        )
        return checks

    actual_columns = list(rows[0].keys())
    missing = [
        c for c in REQUIRED_COLUMNS if c not in actual_columns
    ]
    checks.append(
        {
            "check": "required_columns",
            "expected": REQUIRED_COLUMNS,
            "missing": missing,
            "passed": len(missing) == 0,
            "severity": "critical",
        }
    )
    return checks


def check_corridor_ids(
    rows: list[dict[str, str]],
) -> list[dict[str, Any]]:
    """Check corridor ID format, range, and uniqueness."""
    checks: list[dict[str, Any]] = []

    ids = [r.get("corridor_id", "") for r in rows]

    # Uniqueness
    unique_ids = set(ids)
    duplicates = [
        cid for cid in unique_ids if ids.count(cid) > 1
    ]
    checks.append(
        {
            "check": "corridor_id_unique",
            "total": len(ids),
            "distinct": len(unique_ids),
            "duplicates": duplicates,
            "passed": len(duplicates) == 0,
            "severity": "critical",
        }
    )

    # Expected range
    expected_ids = [
        f"HCC{i:03d}"
        for i in range(1, EXPECTED_CORRIDOR_COUNT + 1)
    ]
    missing_ids = [
        eid for eid in expected_ids if eid not in unique_ids
    ]
    extra_ids = [
        cid for cid in unique_ids if cid not in expected_ids
    ]
    checks.append(
        {
            "check": "corridor_id_range",
            "expected_first": "HCC001",
            "expected_last": "HCC043",
            "missing": missing_ids,
            "extra": extra_ids,
            "passed": (
                len(missing_ids) == 0
                and len(extra_ids) == 0
            ),
            "severity": "critical",
        }
    )

    return checks


def check_source_groups(
    rows: list[dict[str, str]],
) -> list[dict[str, Any]]:
    """Check source group counts and number ranges."""
    checks: list[dict[str, Any]] = []

    neighborhood_rows = [
        r
        for r in rows
        if r.get("source_group") == "neighborhood"
    ]
    downtown_rows = [
        r
        for r in rows
        if r.get("source_group") == "downtown"
    ]
    invalid_groups = [
        r.get("source_group", "")
        for r in rows
        if r.get("source_group") not in VALID_SOURCE_GROUPS
    ]

    checks.append(
        {
            "check": "neighborhood_count",
            "expected": EXPECTED_NEIGHBORHOOD_COUNT,
            "actual": len(neighborhood_rows),
            "passed": (
                len(neighborhood_rows)
                == EXPECTED_NEIGHBORHOOD_COUNT
            ),
            "severity": "critical",
        }
    )

    checks.append(
        {
            "check": "downtown_count",
            "expected": EXPECTED_DOWNTOWN_COUNT,
            "actual": len(downtown_rows),
            "passed": (
                len(downtown_rows) == EXPECTED_DOWNTOWN_COUNT
            ),
            "severity": "critical",
        }
    )

    checks.append(
        {
            "check": "valid_source_groups",
            "invalid": invalid_groups,
            "passed": len(invalid_groups) == 0,
            "severity": "critical",
        }
    )

    # Check source number uniqueness within each group
    def check_group_numbers(
        group_rows: list[dict[str, str]],
        group_name: str,
        expected_range: range,
    ) -> list[dict[str, Any]]:
        group_checks: list[dict[str, Any]] = []
        numbers = []
        for r in group_rows:
            try:
                numbers.append(
                    int(r.get("source_corridor_number", "0"))
                )
            except ValueError:
                numbers.append(-1)

        unique_numbers = set(numbers)
        expected_numbers = set(expected_range)

        missing = expected_numbers - unique_numbers
        extra = unique_numbers - expected_numbers

        group_checks.append(
            {
                "check": (
                    f"{group_name}_source_number_range"
                ),
                "expected_min": min(expected_range),
                "expected_max": max(expected_range),
                "missing": sorted(missing),
                "extra": sorted(extra),
                "passed": (
                    len(missing) == 0 and len(extra) == 0
                ),
                "severity": "critical",
            }
        )

        number_counts = {}
        for n in numbers:
            number_counts[n] = number_counts.get(n, 0) + 1
        duplicate_numbers = [
            n for n, c in number_counts.items() if c > 1
        ]

        group_checks.append(
            {
                "check": (
                    f"{group_name}"
                    "_source_number_unique"
                ),
                "duplicates": duplicate_numbers,
                "passed": len(duplicate_numbers) == 0,
                "severity": "critical",
            }
        )

        return group_checks

    checks.extend(
        check_group_numbers(
            neighborhood_rows,
            "neighborhood",
            range(1, 32),
        )
    )
    checks.extend(
        check_group_numbers(
            downtown_rows, "downtown", range(1, 13)
        )
    )

    return checks


def check_no_missing_values(
    rows: list[dict[str, str]],
) -> list[dict[str, Any]]:
    """Check that canonical fields have no missing values."""
    checks: list[dict[str, Any]] = []

    fields_to_check = [
        "corridor_id",
        "corridor_name",
        "street_name",
        "from_street",
        "to_street",
        "source_name",
        "source_page",
        "cross_reference_page",
        "extraction_status",
        "geometry_status",
    ]

    for field in fields_to_check:
        missing_count = sum(
            1
            for r in rows
            if not r.get(field, "").strip()
        )
        checks.append(
            {
                "check": f"no_missing_{field}",
                "missing_count": missing_count,
                "passed": missing_count == 0,
                "severity": "critical",
            }
        )

    return checks


def check_source_page(
    rows: list[dict[str, str]],
) -> list[dict[str, Any]]:
    """Check that all source pages are 9."""
    checks: list[dict[str, Any]] = []

    non_nine = [
        r.get("corridor_id", "?")
        for r in rows
        if r.get("source_page", "").strip() != "9"
    ]

    checks.append(
        {
            "check": "source_page_is_9",
            "non_conforming": non_nine,
            "passed": len(non_nine) == 0,
            "severity": "critical",
        }
    )

    return checks


def check_cross_reference_pages(
    rows: list[dict[str, str]],
) -> list[dict[str, Any]]:
    """Check that cross-reference pages are 27, 28, or 29."""
    checks: list[dict[str, Any]] = []

    invalid = []
    for r in rows:
        try:
            page = int(r.get("cross_reference_page", "0"))
        except ValueError:
            page = -1
        if page not in VALID_CROSS_REFERENCE_PAGES:
            invalid.append(r.get("corridor_id", "?"))

    checks.append(
        {
            "check": "cross_reference_pages_valid",
            "valid_pages": sorted(
                VALID_CROSS_REFERENCE_PAGES
            ),
            "invalid_corridors": invalid,
            "passed": len(invalid) == 0,
            "severity": "critical",
        }
    )

    return checks


def check_statuses(
    rows: list[dict[str, str]],
) -> list[dict[str, Any]]:
    """Check extraction and geometry status values."""
    checks: list[dict[str, Any]] = []

    invalid_extraction = [
        r.get("corridor_id", "?")
        for r in rows
        if r.get("extraction_status", "")
        not in VALID_EXTRACTION_STATUSES
    ]

    checks.append(
        {
            "check": "extraction_status_valid",
            "valid_values": sorted(
                VALID_EXTRACTION_STATUSES
            ),
            "invalid_corridors": invalid_extraction,
            "passed": len(invalid_extraction) == 0,
            "severity": "critical",
        }
    )

    invalid_geometry = [
        r.get("corridor_id", "?")
        for r in rows
        if r.get("geometry_status", "")
        not in VALID_GEOMETRY_STATUSES
    ]

    checks.append(
        {
            "check": "geometry_status_valid",
            "valid_values": sorted(VALID_GEOMETRY_STATUSES),
            "invalid_corridors": invalid_geometry,
            "passed": len(invalid_geometry) == 0,
            "severity": "critical",
        }
    )

    # Every geometry_status must be pending_construction
    non_pending = [
        r.get("corridor_id", "?")
        for r in rows
        if r.get("geometry_status", "")
        != "pending_construction"
    ]

    checks.append(
        {
            "check": "all_geometry_pending_construction",
            "non_conforming": non_pending,
            "passed": len(non_pending) == 0,
            "severity": "critical",
        }
    )

    return checks


def check_config_consistency(
    rows: list[dict[str, str]],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    """Check that register rows match the corridors.yml entries."""
    checks: list[dict[str, Any]] = []

    config_corridors = config.get("corridors", [])
    id_mapping = config.get("id_mapping", {})

    mismatches: list[str] = []

    for i, cc in enumerate(config_corridors):
        group = cc.get("source_group", "")
        num = cc.get("source_corridor_number", 0)

        if group == "neighborhood":
            offset = id_mapping.get(
                "neighborhood_id_offset", 0
            )
        else:
            offset = id_mapping.get("downtown_id_offset", 31)

        expected_id = f"HCC{num + offset:03d}"

        matching_rows = [
            r
            for r in rows
            if r.get("corridor_id") == expected_id
        ]

        if not matching_rows:
            mismatches.append(
                f"{expected_id}: not found in register"
            )
            continue

        reg_row = matching_rows[0]

        for field in [
            "corridor_name",
            "street_name",
            "from_street",
            "to_street",
        ]:
            config_val = str(cc.get(field, ""))
            reg_val = reg_row.get(field, "")
            if config_val != reg_val:
                mismatches.append(
                    f"{expected_id}.{field}: "
                    f"config='{config_val}' "
                    f"register='{reg_val}'"
                )

    checks.append(
        {
            "check": "config_register_consistency",
            "mismatches": mismatches,
            "passed": len(mismatches) == 0,
            "severity": "critical",
        }
    )

    return checks


def check_aliases(
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    """Check that both documented aliases exist in config."""
    checks: list[dict[str, Any]] = []

    config_aliases = config.get("aliases", [])

    for expected in DOCUMENTED_ALIASES:
        found = any(
            a.get("canonical_name")
            == expected["canonical_name"]
            and a.get("matching_alias")
            == expected["matching_alias"]
            for a in config_aliases
        )
        checks.append(
            {
                "check": "alias_documented",
                "canonical_name": expected[
                    "canonical_name"
                ],
                "matching_alias": expected[
                    "matching_alias"
                ],
                "passed": found,
                "severity": "critical",
            }
        )

    return checks


def check_confidence(
    rows: list[dict[str, str]],
) -> list[dict[str, Any]]:
    """Check that confidence values are valid."""
    checks: list[dict[str, Any]] = []

    invalid = [
        r.get("corridor_id", "?")
        for r in rows
        if r.get("confidence", "")
        not in VALID_CONFIDENCE_VALUES
    ]

    checks.append(
        {
            "check": "confidence_valid",
            "valid_values": sorted(
                VALID_CONFIDENCE_VALUES
            ),
            "invalid_corridors": invalid,
            "passed": len(invalid) == 0,
            "severity": "critical",
        }
    )

    return checks


def write_json_atomic(
    path: Path, data: dict[str, Any]
) -> None:
    """Write JSON with atomic directory creation."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, ensure_ascii=False)
        file.write("\n")


def main() -> int:
    """Run corridor register validation."""
    print("=" * 65)
    print("Validating high-crash corridor register")
    print("=" * 65)

    run_id = datetime.now(timezone.utc).strftime(
        "%Y%m%dT%H%M%SZ"
    )
    started = datetime.now(timezone.utc)

    # Load inputs
    try:
        config = load_yaml(CORRIDORS_CONFIG_PATH)
    except Exception as exc:
        print(f"FAIL: Cannot load corridor config: {exc}")
        return 1

    if not REGISTER_PATH.is_file():
        print(f"FAIL: Register not found: {REGISTER_PATH}")
        return 1

    try:
        rows = load_register(REGISTER_PATH)
    except Exception as exc:
        print(f"FAIL: Cannot load register: {exc}")
        return 1

    print(f"Register loaded: {len(rows)} rows")

    # Run all checks
    all_checks: list[dict[str, Any]] = []
    all_checks.extend(check_row_count(rows))
    all_checks.extend(check_required_columns(rows))
    all_checks.extend(check_corridor_ids(rows))
    all_checks.extend(check_source_groups(rows))
    all_checks.extend(check_no_missing_values(rows))
    all_checks.extend(check_source_page(rows))
    all_checks.extend(check_cross_reference_pages(rows))
    all_checks.extend(check_statuses(rows))
    all_checks.extend(
        check_config_consistency(rows, config)
    )
    all_checks.extend(check_aliases(config))
    all_checks.extend(check_confidence(rows))

    # Determine status
    critical_failures = [
        c
        for c in all_checks
        if not c["passed"] and c.get("severity") == "critical"
    ]
    warnings = [
        c
        for c in all_checks
        if not c["passed"]
        and c.get("severity") == "warning"
    ]

    if critical_failures:
        status = "FAIL"
    elif warnings:
        status = "PASS_WITH_WARNINGS"
    else:
        status = "PASS"

    completed = datetime.now(timezone.utc)

    # Build report
    report = {
        "pipeline": "corridor_register_validation",
        "run_id": run_id,
        "started_at_utc": started.isoformat(
            timespec="seconds"
        ),
        "completed_at_utc": completed.isoformat(
            timespec="seconds"
        ),
        "status": status,
        "downstream_readiness": (
            "READY_FOR_GEOMETRY_CONSTRUCTION"
            if status == "PASS"
            else "NOT_READY"
        ),
        "register": {
            "path": display_path(REGISTER_PATH),
            "rows": len(rows),
        },
        "summary": {
            "total_checks": len(all_checks),
            "passed": sum(
                1 for c in all_checks if c["passed"]
            ),
            "failed": sum(
                1 for c in all_checks if not c["passed"]
            ),
            "critical_failures": len(critical_failures),
            "warnings": len(warnings),
        },
        "checks": all_checks,
        "governance": {
            "canonical_source_page": 9,
            "cross_reference_pages": [27, 28, 29],
            "raw_files_modified": False,
            "geometry_constructed": False,
            "crashes_assigned": False,
        },
    }

    # Write reports
    historical_report_path = (
        HISTORICAL_REPORT_DIR
        / f"corridor_register_validation_{run_id}.json"
    )
    write_json_atomic(historical_report_path, report)
    write_json_atomic(LATEST_REPORT_PATH, report)

    # Print summary
    print(f"Checks: {len(all_checks)}")
    print(
        f"Passed: {report['summary']['passed']} | "
        f"Failed: {report['summary']['failed']}"
    )
    if critical_failures:
        print(
            f"Critical failures: "
            f"{len(critical_failures)}"
        )
        for cf in critical_failures:
            print(f"  FAIL: {cf['check']}")
    print(f"Status: {status}")
    print(f"Historical: {historical_report_path}")
    print(f"Latest: {LATEST_REPORT_PATH}")
    print("=" * 65)

    return 1 if status == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
