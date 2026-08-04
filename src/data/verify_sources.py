from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
import yaml


# verify_sources.py is inside:
# project_root/src/data/verify_sources.py
ROOT = Path(__file__).resolve().parents[2]

CONFIG_PATH = ROOT / "config" / "sources.yml"
REPORT_PATH = ROOT / "docs" / "data_quality" / "source_verification.json"

REQUEST_TIMEOUT_SECONDS = 60

REQUEST_HEADERS = {
    "User-Agent": (
        "Vision-Zero-Chicago-Capstone/"
        "1.0 source-verification"
    )
}

SEPARATOR = "-" * 75


def load_sources_config() -> dict[str, dict[str, Any]]:
    """Load and validate config/sources.yml."""

    if not CONFIG_PATH.is_file():
        raise FileNotFoundError(
            f"Source configuration was not found: {CONFIG_PATH}"
        )

    with CONFIG_PATH.open(encoding="utf-8") as file:
        config = yaml.safe_load(file)

    if not isinstance(config, dict):
        raise ValueError("sources.yml must contain a YAML dictionary.")

    sources = config.get("sources")

    if not isinstance(sources, dict) or not sources:
        raise ValueError(
            "sources.yml must contain a non-empty 'sources' section."
        )

    return sources


def get_dataset_id(
    source_key: str,
    source_config: dict[str, Any],
) -> str:
    """Return the Socrata dataset identifier."""

    dataset_id = (
        source_config.get("dataset_id")
        or source_config.get("id")
    )

    if not dataset_id:
        raise ValueError(
            f"Source '{source_key}' does not have a dataset_id."
        )

    return str(dataset_id)


def get_source_urls(
    dataset_id: str,
    source_config: dict[str, Any],
) -> tuple[str, str]:
    """Return API and metadata URLs for a source."""

    api_url = source_config.get(
        "api_url",
        (
            "https://data.cityofchicago.org/resource/"
            f"{dataset_id}.json"
        ),
    )

    metadata_url = source_config.get(
        "metadata_url",
        (
            "https://data.cityofchicago.org/api/views/"
            f"{dataset_id}"
        ),
    )

    return str(api_url), str(metadata_url)


def request_json(
    url: str,
    *,
    params: dict[str, str] | None = None,
) -> tuple[requests.Response, Any]:
    """Request JSON and raise an error for unsuccessful responses."""

    response = requests.get(
        url,
        params=params,
        headers=REQUEST_HEADERS,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    response.raise_for_status()

    return response, response.json()


def verify_source(
    source_key: str,
    source_config: dict[str, Any],
) -> dict[str, Any]:
    """Verify access, schema fields, row count, and date coverage."""

    dataset_id = get_dataset_id(source_key, source_config)
    api_url, metadata_url = get_source_urls(
        dataset_id,
        source_config,
    )

    source_name = str(
        source_config.get(
            "source_name",
            source_config.get(
                "name",
                source_config.get(
                    "dataset_name",
                    source_key,
                ),
            ),
        )
    )

    expected_grain = str(
        source_config.get(
            "expected_grain",
            source_config.get(
                "grain",
                "not specified",
            ),
        )
    )

    primary_key = str(
        source_config.get(
            "primary_key",
            "not specified",
        )
    )

    date_field = str(
        source_config.get(
            "date_field",
            "crash_date",
        )
    )

    required_fields = source_config.get(
        "required_fields",
        [],
    )

    if not isinstance(required_fields, list):
        raise ValueError(
            f"required_fields for '{source_key}' must be a list."
        )

    required_fields = [
        str(field)
        for field in required_fields
    ]

    # ------------------------------------------------------------
    # 1. Verify metadata and available schema fields
    # ------------------------------------------------------------

    metadata_response, metadata = request_json(metadata_url)

    metadata_columns = metadata.get("columns", [])

    available_fields = sorted(
        {
            column["fieldName"]
            for column in metadata_columns
            if isinstance(column, dict)
            and column.get("fieldName")
        }
    )

    available_field_set = set(available_fields)

    missing_fields = sorted(
        set(required_fields) - available_field_set
    )

    # The primary key is critical even if it was accidentally omitted
    # from required_fields in the configuration.
    if (
        primary_key != "not specified"
        and primary_key not in available_field_set
        and primary_key not in missing_fields
    ):
        missing_fields.append(primary_key)
        missing_fields.sort()

    required_fields_pass = len(missing_fields) == 0

    # ------------------------------------------------------------
    # 2. Verify row count and temporal coverage
    # ------------------------------------------------------------

    select_statement = (
        "count(*) as row_count, "
        f"min({date_field}) as min_date, "
        f"max({date_field}) as max_date"
    )

    summary_response, summary_payload = request_json(
        api_url,
        params={
            "$select": select_statement,
        },
    )

    if (
        not isinstance(summary_payload, list)
        or len(summary_payload) == 0
    ):
        raise ValueError(
            f"No summary result was returned for '{source_key}'."
        )

    summary = summary_payload[0]

    if "row_count" not in summary:
        raise ValueError(
            f"row_count was not returned for '{source_key}'."
        )

    row_count = int(summary["row_count"])
    minimum_date = summary.get("min_date")
    maximum_date = summary.get("max_date")

    access_pass = (
        metadata_response.status_code == 200
        and summary_response.status_code == 200
    )

    coverage_pass = (
        row_count > 0
        and minimum_date is not None
        and maximum_date is not None
    )

    source_pass = (
        access_pass
        and required_fields_pass
        and coverage_pass
    )

    return {
        "source_key": source_key,
        "source_name": source_name,
        "dataset_id": dataset_id,
        "expected_grain": expected_grain,
        "primary_key": primary_key,
        "date_field": date_field,
        "api_url": api_url,
        "metadata_url": metadata_url,
        "metadata_status_code": metadata_response.status_code,
        "api_status_code": summary_response.status_code,
        "available_schema_field_count": len(available_fields),
        "required_fields": required_fields,
        "missing_fields": missing_fields,
        "required_fields_status": (
            "PASS"
            if required_fields_pass
            else "FAIL"
        ),
        "row_count": row_count,
        "minimum_date": minimum_date,
        "maximum_date": maximum_date,
        "access_status": (
            "PASS"
            if access_pass
            else "FAIL"
        ),
        "coverage_status": (
            "PASS"
            if coverage_pass
            else "FAIL"
        ),
        "status": (
            "PASS"
            if source_pass
            else "FAIL"
        ),
    }


def print_source_result(result: dict[str, Any]) -> None:
    """Print one source-verification result."""

    print(f"Source: {result['source_key']}")
    print(f"Dataset ID: {result['dataset_id']}")
    print(f"Expected grain: {result['expected_grain']}")
    print(f"Primary key: {result['primary_key']}")
    print(
        "Available schema fields: "
        f"{result['available_schema_field_count']}"
    )
    print(
        "Required fields status: "
        f"{result['required_fields_status']}"
    )
    print(f"Missing fields: {result['missing_fields']}")
    print(f"Rows: {result['row_count']}")
    print(f"Minimum date: {result['minimum_date']}")
    print(f"Maximum date: {result['maximum_date']}")
    print(SEPARATOR)


def print_failed_source(
    source_key: str,
    error: Exception,
) -> None:
    """Print a failed source-verification result."""

    print(f"Source: {source_key}")
    print("Status: FAIL")
    print(f"Error type: {type(error).__name__}")
    print(f"Error: {error}")
    print(SEPARATOR)


def save_report(
    results: list[dict[str, Any]],
    overall_status: str,
) -> None:
    """Save the verification results as JSON."""

    REPORT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    report = {
        "verification_name": (
            "Chicago source and schema verification"
        ),
        "checked_at_utc": (
            datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
        ),
        "config_path": str(CONFIG_PATH),
        "source_count": len(results),
        "overall_status": overall_status,
        "sources": results,
    }

    with REPORT_PATH.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            report,
            file,
            indent=2,
            ensure_ascii=False,
        )


def main() -> int:
    """Run verification for every source in sources.yml."""

    print("Chicago source and schema verification")
    print(SEPARATOR)

    try:
        sources = load_sources_config()
    except (FileNotFoundError, ValueError, yaml.YAMLError) as error:
        print("Configuration status: FAIL")
        print(f"Error: {error}")
        return 1

    results: list[dict[str, Any]] = []

    for source_key, source_config in sources.items():
        try:
            result = verify_source(
                source_key,
                source_config,
            )

            results.append(result)
            print_source_result(result)

        except (
            requests.RequestException,
            ValueError,
            TypeError,
            KeyError,
        ) as error:
            failed_result = {
                "source_key": source_key,
                "source_name": source_config.get(
                    "source_name",
                    source_config.get(
                        "name",
                        source_key,
                    ),
                ),
                "dataset_id": source_config.get(
                    "dataset_id",
                    source_config.get("id"),
                ),
                "status": "FAIL",
                "error_type": type(error).__name__,
                "error": str(error),
            }

            results.append(failed_result)
            print_failed_source(source_key, error)

    overall_status = (
        "PASS"
        if results
        and all(
            result.get("status") == "PASS"
            for result in results
        )
        else "FAIL"
    )

    save_report(results, overall_status)

    print(f"Overall source verification: {overall_status}")
    print(f"Report saved to: {REPORT_PATH}")

    return 0 if overall_status == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())