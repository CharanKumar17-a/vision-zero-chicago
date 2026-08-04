from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
import yaml


ROOT = Path(__file__).resolve().parents[2]

SOURCES_CONFIG_PATH = ROOT / "config" / "sources.yml"
ACQUISITION_CONFIG_PATH = ROOT / "config" / "acquisition.yml"
REPORT_PATH = (
    ROOT
    / "docs"
    / "data_quality"
    / "acquisition_contract_validation.json"
)


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as file:
        data = yaml.safe_load(file)

    if not isinstance(data, dict):
        raise ValueError(f"Expected a YAML mapping in {path}")

    return data


def find_duplicates(values: list[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()

    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)

    return sorted(duplicates)


def parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def validate_global_settings(
    acquisition_config: dict[str, Any],
) -> list[str]:
    issues: list[str] = []
    settings = acquisition_config.get("acquisition", {})

    start_text = settings.get("history_start")
    end_text = settings.get("history_end_exclusive")
    batch_size = settings.get("batch_size")

    if not start_text or not end_text:
        issues.append(
            "history_start and history_end_exclusive are required"
        )
    else:
        try:
            start = parse_timestamp(str(start_text))
            end = parse_timestamp(str(end_text))

            if start >= end:
                issues.append(
                    "history_start must be before history_end_exclusive"
                )
        except ValueError as error:
            issues.append(f"Invalid history timestamp: {error}")

    if not isinstance(batch_size, int):
        issues.append("batch_size must be an integer")
    elif not 1 <= batch_size <= 50000:
        issues.append("batch_size must be between 1 and 50000")

    if settings.get("output_format") != "csv.gz":
        issues.append("output_format must be csv.gz")

    if settings.get("preserve_raw_files") is not True:
        issues.append("preserve_raw_files must be true")

    if settings.get("overwrite_existing_files") is not False:
        issues.append("overwrite_existing_files must be false")

    return issues


def fetch_available_fields(
    metadata_url: str,
    timeout_seconds: int,
) -> set[str]:
    response = requests.get(
        metadata_url,
        timeout=timeout_seconds,
        headers={
            "User-Agent": (
                "Vision-Zero-Chicago-Capstone/"
                "acquisition-contract-validator"
            )
        },
    )
    response.raise_for_status()

    metadata = response.json()
    columns = metadata.get("columns", [])

    return {
        column["fieldName"]
        for column in columns
        if column.get("fieldName")
    }


def validate_source(
    source_name: str,
    acquisition_source: dict[str, Any],
    source_catalog: dict[str, Any],
    timeout_seconds: int,
) -> dict[str, Any]:
    issues: list[str] = []

    source_config_key = acquisition_source.get("source_config_key")
    catalog_sources = source_catalog.get("sources", {})

    if source_config_key not in catalog_sources:
        return {
            "status": "FAIL",
            "issues": [
                f"Unknown source_config_key: {source_config_key}"
            ],
        }

    source_config = catalog_sources[source_config_key]

    selected_fields = acquisition_source.get("select_fields", [])
    required_fields = source_config.get("required_fields", [])
    date_field = acquisition_source.get("date_field")
    primary_key = source_config.get("primary_key")
    order_by = acquisition_source.get("order_by", [])

    if not isinstance(selected_fields, list) or not selected_fields:
        issues.append("select_fields must be a non-empty list")
        selected_fields = []

    duplicate_fields = find_duplicates(selected_fields)

    if duplicate_fields:
        issues.append(
            f"Duplicate selected fields: {duplicate_fields}"
        )

    if primary_key not in selected_fields:
        issues.append(
            f"Primary key is not selected: {primary_key}"
        )

    if date_field not in selected_fields:
        issues.append(
            f"Date field is not selected: {date_field}"
        )

    required_not_selected = sorted(
        set(required_fields) - set(selected_fields)
    )

    if required_not_selected:
        issues.append(
            "Required fields not selected: "
            f"{required_not_selected}"
        )

    expected_order = [date_field, primary_key]

    if order_by != expected_order:
        issues.append(
            f"order_by must be exactly {expected_order}"
        )

    metadata_url = source_config.get("metadata_url")

    if not metadata_url:
        issues.append("metadata_url is missing")
        available_fields: set[str] = set()
    else:
        try:
            available_fields = fetch_available_fields(
                metadata_url=metadata_url,
                timeout_seconds=timeout_seconds,
            )
        except (
            requests.RequestException,
            ValueError,
            KeyError,
        ) as error:
            issues.append(
                "Unable to retrieve source metadata: "
                f"{type(error).__name__}: {error}"
            )
            available_fields = set()

    missing_from_live_schema = sorted(
        set(selected_fields) - available_fields
    )

    if available_fields and missing_from_live_schema:
        issues.append(
            "Selected fields missing from live schema: "
            f"{missing_from_live_schema}"
        )

    return {
        "source_name": source_name,
        "source_config_key": source_config_key,
        "primary_key": primary_key,
        "date_field": date_field,
        "selected_field_count": len(selected_fields),
        "available_field_count": len(available_fields),
        "duplicate_selected_fields": duplicate_fields,
        "required_fields_not_selected": required_not_selected,
        "selected_fields_missing_from_live_schema": (
            missing_from_live_schema
        ),
        "issues": issues,
        "status": "PASS" if not issues else "FAIL",
    }


def main() -> int:
    source_catalog = load_yaml(SOURCES_CONFIG_PATH)
    acquisition_config = load_yaml(ACQUISITION_CONFIG_PATH)

    settings = acquisition_config["acquisition"]
    timeout_seconds = int(
        settings.get("request_timeout_seconds", 120)
    )

    global_issues = validate_global_settings(
        acquisition_config
    )

    source_results: dict[str, Any] = {}

    print("Raw-data acquisition contract validation")
    print("-" * 75)

    for source_name, source_config in acquisition_config[
        "sources"
    ].items():
        result = validate_source(
            source_name=source_name,
            acquisition_source=source_config,
            source_catalog=source_catalog,
            timeout_seconds=timeout_seconds,
        )

        source_results[source_name] = result

        print(f"Source: {source_name}")
        print(
            "Selected fields:",
            result.get("selected_field_count", 0),
        )
        print(
            "Available schema fields:",
            result.get("available_field_count", 0),
        )
        print(
            "Missing selected fields:",
            result.get(
                "selected_fields_missing_from_live_schema",
                [],
            ),
        )
        print("Status:", result["status"])
        print("-" * 75)

    overall_pass = (
        not global_issues
        and all(
            result["status"] == "PASS"
            for result in source_results.values()
        )
    )

    report = {
        "validated_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "historical_window": {
            "start": settings["history_start"],
            "end_exclusive": settings[
                "history_end_exclusive"
            ],
        },
        "batch_size": settings["batch_size"],
        "global_issues": global_issues,
        "sources": source_results,
        "overall_status": (
            "PASS" if overall_pass else "FAIL"
        ),
    }

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with REPORT_PATH.open("w", encoding="utf-8") as file:
        json.dump(report, file, indent=2)

    print(
        "Overall acquisition-contract status:",
        report["overall_status"],
    )
    print("Report saved to:", REPORT_PATH)

    if global_issues:
        print("Global issues:", global_issues)

    return 0 if overall_pass else 1


if __name__ == "__main__":
    sys.exit(main())