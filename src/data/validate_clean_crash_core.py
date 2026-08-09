"""Run an independent deep validation of crashes_clean.parquet.

The script reads the cleaned Parquet dataset in batches, independently
recomputes important derived fields, reconciles the results with the Day 5
cleaning report, records data-quality issues, and produces permanent evidence.

It never modifies the cleaned Parquet dataset.
"""

from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import yaml


ROOT = Path(__file__).resolve().parents[2]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.crash_validation import (  # noqa: E402
    configured_output_columns,
    validate_batch,
)


CLEANING_CONFIG_PATH = ROOT / "config" / "cleaning.yml"
PROJECT_CONFIG_PATH = ROOT / "config" / "project.yml"


ADDITIVE_METRICS = (
    "rows",
    "missing_primary_keys",
    "duplicate_primary_keys_within_batch",
    "invalid_crash_dates",
    "dates_outside_historical_window",
    "crash_year_mismatches",
    "crash_month_start_mismatches",
    "severity_kabco_mismatches",
    "coordinate_status_mismatches",
    "coordinate_valid_flag_mismatches",
    "valid_coordinate_rows",
    "blank_or_unknown_severity_rows",
    "invalid_indicator_values",
    "negative_injury_value_rows",
    "injury_reconciliation_mismatches",
    "crash_hour_mismatches",
    "crash_day_of_week_mismatches",
    "crash_month_mismatches",
)


DEFAULT_ISSUE_REGISTER_FIELDS = (
    "issue_id",
    "detected_at_utc",
    "run_id",
    "stage",
    "dataset",
    "issue_code",
    "severity",
    "affected_rows",
    "affected_rate",
    "message",
    "governance_reference",
    "report_path",
    "status",
)


def load_yaml(path: Path) -> dict[str, Any]:
    """Load and validate a YAML mapping."""

    with path.open(encoding="utf-8") as file:
        data = yaml.safe_load(file)

    if not isinstance(data, dict):
        raise ValueError(f"Expected a YAML mapping in {path}")

    return data


def utc_now() -> datetime:
    """Return the current timezone-aware UTC timestamp."""

    return datetime.now(timezone.utc)


def make_run_id(timestamp: datetime) -> str:
    """Create a sortable validation run identifier."""

    return timestamp.strftime("%Y%m%dT%H%M%SZ")


def project_path(relative_path: str) -> Path:
    """Resolve a configured project-relative path."""

    return ROOT / Path(relative_path)


def relative_project_path(path: Path) -> str:
    """Return a portable project-relative path."""

    return str(path.relative_to(ROOT)).replace("\\", "/")


def write_json_atomic(
    path: Path,
    payload: dict[str, Any],
) -> None:
    """Write JSON without exposing a partially written report."""

    path.parent.mkdir(parents=True, exist_ok=True)

    temporary_path = path.with_suffix(path.suffix + ".tmp")

    temporary_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    temporary_path.replace(path)


def expected_type_families(
    cleaning: dict[str, Any],
) -> dict[str, str]:
    """Build broad expected Parquet type families."""

    expected: dict[str, str] = {}

    for column in cleaning["schema"]["datetime_columns"]:
        expected[column] = "datetime"

    for column in cleaning["schema"]["string_columns"]:
        expected[column] = "string"

    for column in cleaning["schema"]["nullable_integer_columns"]:
        expected[column] = "integer"

    for column in cleaning["schema"]["nullable_float_columns"]:
        expected[column] = "float"

    for column, definition in cleaning["derived_columns"].items():
        expected[column] = definition["type"]

    return expected


def arrow_type_matches(
    arrow_type: pa.DataType,
    expected_family: str,
) -> bool:
    """Check an Arrow type against a broad configured family."""

    if expected_family == "string":
        return (
            pa.types.is_string(arrow_type)
            or pa.types.is_large_string(arrow_type)
        )

    if expected_family == "integer":
        return pa.types.is_integer(arrow_type)

    if expected_family == "float":
        return pa.types.is_floating(arrow_type)

    if expected_family == "datetime":
        return (
            pa.types.is_timestamp(arrow_type)
            or pa.types.is_date(arrow_type)
        )

    if expected_family == "boolean":
        return pa.types.is_boolean(arrow_type)

    return True


def inspect_parquet_schema(
    parquet_file: pq.ParquetFile,
    cleaning: dict[str, Any],
) -> dict[str, Any]:
    """Compare the actual Parquet schema with the contract."""

    schema = parquet_file.schema_arrow
    actual_columns = list(schema.names)
    expected_columns = configured_output_columns(cleaning)

    missing_columns = sorted(
        set(expected_columns) - set(actual_columns)
    )

    unexpected_columns = sorted(
        set(actual_columns) - set(expected_columns)
    )

    expected_families = expected_type_families(cleaning)
    type_mismatches: list[dict[str, str]] = []

    for column, expected_family in expected_families.items():
        if column not in actual_columns:
            continue

        actual_type = schema.field(column).type

        if not arrow_type_matches(actual_type, expected_family):
            type_mismatches.append(
                {
                    "column": column,
                    "expected_family": expected_family,
                    "actual_type": str(actual_type),
                }
            )

    return {
        "expected_column_count": len(expected_columns),
        "actual_column_count": len(actual_columns),
        "expected_columns": expected_columns,
        "actual_columns": actual_columns,
        "missing_columns": missing_columns,
        "unexpected_columns": unexpected_columns,
        "type_mismatches": type_mismatches,
        "status": (
            "PASS"
            if not (
                missing_columns
                or unexpected_columns
                or type_mismatches
            )
            else "FAIL"
        ),
    }


def empty_metrics(
    cleaning: dict[str, Any],
) -> dict[str, Any]:
    """Create an empty aggregate metric structure."""

    metrics: dict[str, Any] = {
        metric: 0
        for metric in ADDITIVE_METRICS
    }

    metrics["scanned_rows"] = 0
    metrics["global_duplicate_primary_key_rows"] = 0
    metrics["global_duplicate_primary_key_values"] = 0
    metrics["valid_coordinate_coverage"] = None
    metrics["invalid_coordinate_rows"] = 0
    metrics["coordinate_status_counts"] = {}

    metrics["numeric_range_warning_counts"] = {
        column: 0
        for column in cleaning["numeric_quality_ranges"]
    }

    return metrics


def add_batch_metrics(
    aggregate: dict[str, Any],
    batch_metrics: dict[str, Any],
) -> None:
    """Add one batch result to the complete-dataset metrics."""

    for metric in ADDITIVE_METRICS:
        aggregate[metric] += int(batch_metrics[metric])

    for status, count in batch_metrics[
        "coordinate_status_counts"
    ].items():
        aggregate["coordinate_status_counts"][status] = (
            aggregate["coordinate_status_counts"].get(status, 0)
            + int(count)
        )

    for column, count in batch_metrics[
        "numeric_range_warning_counts"
    ].items():
        aggregate["numeric_range_warning_counts"][column] += int(
            count
        )


def scan_clean_parquet(
    parquet_file: pq.ParquetFile,
    cleaning: dict[str, Any],
    project: dict[str, Any],
) -> dict[str, Any]:
    """Scan the complete Parquet dataset in controlled batches."""

    metrics = empty_metrics(cleaning)

    validation_config = cleaning["deep_validation"]
    batch_size = int(validation_config["batch_size"])

    history_start = project["analysis"]["history_start"]
    history_end = project["analysis"]["history_end"]

    primary_key = cleaning["dataset"]["output"]["primary_key"]
    required_columns = configured_output_columns(cleaning)

    all_primary_keys: list[pd.Series] = []

    total_batches = (
        parquet_file.metadata.num_rows + batch_size - 1
    ) // batch_size

    for batch_number, record_batch in enumerate(
        parquet_file.iter_batches(
            batch_size=batch_size,
            columns=required_columns,
        ),
        start=1,
    ):
        frame = record_batch.to_pandas()

        batch_metrics = validate_batch(
            frame=frame,
            cleaning=cleaning,
            history_start=history_start,
            history_end=history_end,
        )

        add_batch_metrics(metrics, batch_metrics)

        all_primary_keys.append(
            frame[primary_key].astype("string")
        )

        print(
            f"Validated batch {batch_number:02d}/"
            f"{total_batches:02d}: "
            f"{len(frame):,} rows"
        )

    metrics["scanned_rows"] = metrics["rows"]

    if all_primary_keys:
        primary_keys = pd.concat(
            all_primary_keys,
            ignore_index=True,
        )

        non_missing_keys = primary_keys.dropna()

        duplicate_mask = non_missing_keys.duplicated(
            keep=False
        )

        metrics["global_duplicate_primary_key_rows"] = int(
            duplicate_mask.sum()
        )

        metrics["global_duplicate_primary_key_values"] = int(
            non_missing_keys.loc[duplicate_mask].nunique()
        )

    if metrics["rows"] > 0:
        metrics["valid_coordinate_coverage"] = (
            metrics["valid_coordinate_rows"]
            / metrics["rows"]
        )

    metrics["invalid_coordinate_rows"] = (
        metrics["rows"] - metrics["valid_coordinate_rows"]
    )

    return metrics


def compare_with_cleaning_report(
    cleaning_report_path: Path,
    metrics: dict[str, Any],
    parquet_metadata: dict[str, Any],
) -> dict[str, Any]:
    """Reconcile deep-validation results with Day 5 evidence."""

    mismatches: list[str] = []

    if not cleaning_report_path.is_file():
        return {
            "status": "FAIL",
            "mismatches": [
                "Day 5 cleaning report was not found."
            ],
        }

    report = json.loads(
        cleaning_report_path.read_text(encoding="utf-8")
    )

    cleaning_metrics = report.get("metrics", {})

    comparisons = (
        (
            "output_rows",
            cleaning_metrics.get("output_rows"),
            metrics["rows"],
        ),
        (
            "output_columns",
            cleaning_metrics.get("output_columns"),
            parquet_metadata["column_count"],
        ),
        (
            "missing_primary_keys",
            cleaning_metrics.get("missing_primary_keys"),
            metrics["missing_primary_keys"],
        ),
        (
            "duplicate_primary_keys",
            cleaning_metrics.get("duplicate_primary_keys"),
            metrics["global_duplicate_primary_key_rows"],
        ),
        (
            "invalid_crash_dates",
            cleaning_metrics.get("invalid_crash_dates"),
            metrics["invalid_crash_dates"],
        ),
        (
            "dates_outside_historical_window",
            cleaning_metrics.get(
                "dates_outside_historical_window"
            ),
            metrics["dates_outside_historical_window"],
        ),
    )

    for name, cleaning_value, deep_value in comparisons:
        if cleaning_value is None:
            continue

        if int(cleaning_value) != int(deep_value):
            mismatches.append(
                f"{name}: cleaning={cleaning_value}, "
                f"deep_validation={deep_value}"
            )

    cleaning_coverage = cleaning_metrics.get(
        "valid_coordinate_coverage"
    )

    deep_coverage = metrics.get("valid_coordinate_coverage")

    if (
        cleaning_coverage is not None
        and deep_coverage is not None
        and abs(
            float(cleaning_coverage) - float(deep_coverage)
        )
        > 1e-12
    ):
        mismatches.append(
            "valid_coordinate_coverage: "
            f"cleaning={cleaning_coverage}, "
            f"deep_validation={deep_coverage}"
        )

    deep_issue_counts = {
        "blank_severity": metrics[
            "blank_or_unknown_severity_rows"
        ],
        "invalid_coordinate": metrics[
            "invalid_coordinate_rows"
        ],
    }

    for column, count in metrics[
        "numeric_range_warning_counts"
    ].items():
        deep_issue_counts[
            f"numeric_range_warning:{column}_outside_range"
        ] = count

    for issue in report.get("issues", []):
        issue_code = issue.get("issue_code")

        if issue_code not in deep_issue_counts:
            continue

        cleaning_count = int(issue.get("affected_rows", 0))
        deep_count = int(deep_issue_counts[issue_code])

        if cleaning_count != deep_count:
            mismatches.append(
                f"{issue_code}: cleaning={cleaning_count}, "
                f"deep_validation={deep_count}"
            )

    if report.get("published_output") is not True:
        mismatches.append(
            "Day 5 report does not confirm output publication."
        )

    return {
        "status": "PASS" if not mismatches else "FAIL",
        "cleaning_report_status": report.get("status"),
        "cleaning_report_published_output": report.get(
            "published_output"
        ),
        "mismatches": mismatches,
    }


def issue(
    code: str,
    severity: str,
    affected_rows: int,
    total_rows: int,
    message: str,
    governance_reference: str,
) -> dict[str, Any]:
    """Create a standardized issue record."""

    affected_rate = (
        affected_rows / total_rows
        if total_rows > 0
        else None
    )

    return {
        "issue_code": code,
        "severity": severity,
        "affected_rows": int(affected_rows),
        "affected_rate": affected_rate,
        "message": message,
        "governance_reference": governance_reference,
    }


def build_issues(
    schema_report: dict[str, Any],
    parquet_metadata: dict[str, Any],
    metrics: dict[str, Any],
    reconciliation: dict[str, Any],
) -> list[dict[str, Any]]:
    """Classify validation findings into errors and warnings."""

    issues: list[dict[str, Any]] = []
    total_rows = metrics["rows"]

    schema_problem_count = (
        len(schema_report["missing_columns"])
        + len(schema_report["unexpected_columns"])
        + len(schema_report["type_mismatches"])
    )

    if schema_problem_count:
        issues.append(
            issue(
                code="schema_contract_mismatch",
                severity="ERROR",
                affected_rows=schema_problem_count,
                total_rows=total_rows,
                message=(
                    "The Parquet schema does not exactly match the "
                    "configured cleaning contract."
                ),
                governance_reference="cleaning contract",
            )
        )

    if metrics["scanned_rows"] != parquet_metadata["row_count"]:
        issues.append(
            issue(
                code="parquet_scan_row_count_mismatch",
                severity="ERROR",
                affected_rows=abs(
                    metrics["scanned_rows"]
                    - parquet_metadata["row_count"]
                ),
                total_rows=parquet_metadata["row_count"],
                message=(
                    "The number of scanned rows does not match "
                    "Parquet metadata."
                ),
                governance_reference="cleaning contract",
            )
        )

    critical_metrics = {
        "missing_primary_key": metrics[
            "missing_primary_keys"
        ],
        "duplicate_primary_key": metrics[
            "global_duplicate_primary_key_rows"
        ],
        "invalid_crash_date": metrics[
            "invalid_crash_dates"
        ],
        "crash_date_outside_historical_window": metrics[
            "dates_outside_historical_window"
        ],
        "crash_year_mismatch": metrics[
            "crash_year_mismatches"
        ],
        "crash_month_start_mismatch": metrics[
            "crash_month_start_mismatches"
        ],
        "severity_kabco_mismatch": metrics[
            "severity_kabco_mismatches"
        ],
        "coordinate_status_mismatch": metrics[
            "coordinate_status_mismatches"
        ],
        "coordinate_valid_flag_mismatch": metrics[
            "coordinate_valid_flag_mismatches"
        ],
    }

    for code, count in critical_metrics.items():
        if count:
            issues.append(
                issue(
                    code=code,
                    severity="ERROR",
                    affected_rows=count,
                    total_rows=total_rows,
                    message=(
                        "A critical clean-dataset contract rule "
                        "was violated."
                    ),
                    governance_reference="cleaning contract",
                )
            )

    if reconciliation["status"] != "PASS":
        issues.append(
            issue(
                code="cleaning_report_reconciliation_mismatch",
                severity="ERROR",
                affected_rows=len(
                    reconciliation["mismatches"]
                ),
                total_rows=total_rows,
                message="; ".join(
                    reconciliation["mismatches"]
                ),
                governance_reference="D010",
            )
        )

    warning_metrics = {
        "blank_or_unknown_severity": (
            metrics["blank_or_unknown_severity_rows"],
            "Some crashes have unknown KABCO severity.",
            "severity contract",
        ),
        "invalid_coordinate": (
            metrics["invalid_coordinate_rows"],
            (
                "Some crashes cannot be used for spatial "
                "corridor assignment."
            ),
            "A009",
        ),
        "invalid_indicator_value": (
            metrics["invalid_indicator_values"],
            "Unexpected indicator values were preserved.",
            "cleaning contract",
        ),
        "negative_injury_value": (
            metrics["negative_injury_value_rows"],
            "Negative injury counts were detected.",
            "cleaning contract",
        ),
        "injury_reconciliation_mismatch": (
            metrics["injury_reconciliation_mismatches"],
            (
                "Injury components do not reconcile with "
                "injuries_total."
            ),
            "cleaning contract",
        ),
        "crash_hour_mismatch": (
            metrics["crash_hour_mismatches"],
            "crash_hour does not agree with crash_date.",
            "cleaning contract",
        ),
        "crash_day_of_week_mismatch": (
            metrics["crash_day_of_week_mismatches"],
            (
                "crash_day_of_week does not agree with "
                "crash_date."
            ),
            "cleaning contract",
        ),
        "crash_month_mismatch": (
            metrics["crash_month_mismatches"],
            "crash_month does not agree with crash_date.",
            "cleaning contract",
        ),
    }

    for code, (
        count,
        message,
        governance_reference,
    ) in warning_metrics.items():
        if count:
            issues.append(
                issue(
                    code=code,
                    severity="WARNING",
                    affected_rows=count,
                    total_rows=total_rows,
                    message=message,
                    governance_reference=governance_reference,
                )
            )

    for column, count in metrics[
        "numeric_range_warning_counts"
    ].items():
        if count:
            issues.append(
                issue(
                    code=(
                        f"numeric_range_warning:"
                        f"{column}_outside_range"
                    ),
                    severity="WARNING",
                    affected_rows=count,
                    total_rows=total_rows,
                    message=(
                        f"{column} contains values outside the "
                        "configured plausibility range."
                    ),
                    governance_reference="D011",
                )
            )

    return issues


def determine_status(
    issues: list[dict[str, Any]],
) -> tuple[str, str]:
    """Determine run status and downstream readiness."""

    if any(
        finding["severity"] == "ERROR"
        for finding in issues
    ):
        return "FAIL", "BLOCKED"

    if any(
        finding["severity"] == "WARNING"
        for finding in issues
    ):
        return "PASS_WITH_WARNINGS", "READY_WITH_LIMITATIONS"

    return "PASS", "READY"


def append_issue_register(
    register_path: Path,
    report: dict[str, Any],
    report_path: Path,
) -> None:
    """Append validation findings using the existing CSV schema."""

    if not report["issues"]:
        return

    register_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames: list[str]

    if register_path.is_file() and register_path.stat().st_size > 0:
        with register_path.open(
            encoding="utf-8-sig",
            newline="",
        ) as file:
            reader = csv.DictReader(file)
            fieldnames = list(
                reader.fieldnames
                or DEFAULT_ISSUE_REGISTER_FIELDS
            )
    else:
        fieldnames = list(DEFAULT_ISSUE_REGISTER_FIELDS)

    file_exists = (
        register_path.is_file()
        and register_path.stat().st_size > 0
    )

    with register_path.open(
        "a",
        encoding="utf-8",
        newline="",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames,
            extrasaction="ignore",
        )

        if not file_exists:
            writer.writeheader()

        for position, finding in enumerate(
            report["issues"],
            start=1,
        ):
            values = {
                "issue_id": (
                    f"{report['run_id']}_DEEP_"
                    f"{position:03d}"
                ),
                "detected_at_utc": report["checked_at_utc"],
                "run_id": report["run_id"],
                "stage": "deep_validation",
                "pipeline_stage": "deep_validation",
                "dataset": "crashes_clean",
                "issue_code": finding["issue_code"],
                "severity": finding["severity"],
                "affected_rows": finding["affected_rows"],
                "affected_rate": finding["affected_rate"],
                "message": finding["message"],
                "governance_reference": finding[
                    "governance_reference"
                ],
                "report_path": relative_project_path(
                    report_path
                ),
                "status": "open",
            }

            writer.writerow(
                {
                    field: values.get(field, "")
                    for field in fieldnames
                }
            )


def create_failure_report(
    run_id: str,
    checked_at: str,
    error: Exception,
) -> dict[str, Any]:
    """Create evidence for an unexpected validator failure."""

    return {
        "validation_name": (
            "Vision Zero Chicago crash-core deep validation"
        ),
        "run_id": run_id,
        "checked_at_utc": checked_at,
        "status": "FAIL",
        "downstream_readiness": "BLOCKED",
        "input_dataset": (
            "data/interim/crashes_clean.parquet"
        ),
        "input_modified": False,
        "issues": [
            {
                "issue_code": "validator_runtime_error",
                "severity": "ERROR",
                "affected_rows": 0,
                "affected_rate": None,
                "message": str(error),
                "governance_reference": "D010",
            }
        ],
        "error_type": type(error).__name__,
        "error": str(error),
        "decision_boundary": (
            "Final project selection remains with the City "
            "and engineering teams."
        ),
    }


def run_validation() -> tuple[
    dict[str, Any],
    Path,
    Path,
    Path,
]:
    """Run the complete deep validation."""

    started_at = utc_now()
    run_id = make_run_id(started_at)
    checked_at = started_at.isoformat()

    cleaning = load_yaml(CLEANING_CONFIG_PATH)
    project = load_yaml(PROJECT_CONFIG_PATH)

    deep_config = cleaning["deep_validation"]

    parquet_path = project_path(
        cleaning["dataset"]["output"]["path"]
    )

    if not parquet_path.is_file():
        raise FileNotFoundError(
            f"Clean Parquet dataset not found: {parquet_path}"
        )

    parquet_file = pq.ParquetFile(parquet_path)

    parquet_metadata = {
        "path": relative_project_path(parquet_path),
        "row_count": parquet_file.metadata.num_rows,
        "column_count": parquet_file.metadata.num_columns,
        "row_group_count": parquet_file.metadata.num_row_groups,
        "file_size_bytes": parquet_path.stat().st_size,
    }

    print("Crash-core deep validation")
    print("=" * 75)
    print(f"Input: {parquet_metadata['path']}")
    print(
        f"Parquet rows: "
        f"{parquet_metadata['row_count']:,}"
    )
    print(
        f"Parquet columns: "
        f"{parquet_metadata['column_count']}"
    )
    print(
        f"Parquet row groups: "
        f"{parquet_metadata['row_group_count']}"
    )
    print("=" * 75)

    schema_report = inspect_parquet_schema(
        parquet_file,
        cleaning,
    )

    if schema_report["missing_columns"]:
        metrics = empty_metrics(cleaning)
    else:
        metrics = scan_clean_parquet(
            parquet_file=parquet_file,
            cleaning=cleaning,
            project=project,
        )

    cleaning_report_path = project_path(
        cleaning["evidence"]["latest_report_path"]
    )

    if deep_config["compare_to_cleaning_report"]:
        reconciliation = compare_with_cleaning_report(
            cleaning_report_path=cleaning_report_path,
            metrics=metrics,
            parquet_metadata=parquet_metadata,
        )
    else:
        reconciliation = {
            "status": "NOT_REQUESTED",
            "mismatches": [],
        }

    issues = build_issues(
        schema_report=schema_report,
        parquet_metadata=parquet_metadata,
        metrics=metrics,
        reconciliation=reconciliation,
    )

    status, readiness = determine_status(issues)

    completed_at = utc_now()

    report = {
        "validation_name": (
            "Vision Zero Chicago crash-core deep validation"
        ),
        "run_id": run_id,
        "checked_at_utc": checked_at,
        "completed_at_utc": completed_at.isoformat(),
        "duration_seconds": (
            completed_at - started_at
        ).total_seconds(),
        "status": status,
        "downstream_readiness": readiness,
        "input_dataset": relative_project_path(parquet_path),
        "input_modified": False,
        "expected_grain": "one row per recorded crash",
        "primary_key": cleaning[
            "dataset"
        ]["output"]["primary_key"],
        "parquet_metadata": parquet_metadata,
        "schema_validation": schema_report,
        "metrics": metrics,
        "cleaning_report_reconciliation": reconciliation,
        "issues": issues,
        "decision_boundary": (
            "This validation determines technical readiness. "
            "Final project selection remains with the City "
            "and engineering teams."
        ),
    }

    latest_report_path = project_path(
        deep_config["latest_report_path"]
    )

    historical_report_path = (
        project_path(deep_config["report_directory"])
        / f"crash_core_deep_validation_{run_id}.json"
    )

    issue_register_path = project_path(
        cleaning["evidence"]["issue_register_path"]
    )

    return (
        report,
        latest_report_path,
        historical_report_path,
        issue_register_path,
    )


def main() -> int:
    """Run validation, persist evidence, and return an exit code."""

    started_at = utc_now()
    fallback_run_id = make_run_id(started_at)
    fallback_checked_at = started_at.isoformat()

    try:
        (
            report,
            latest_report_path,
            historical_report_path,
            issue_register_path,
        ) = run_validation()

    except Exception as error:
        report = create_failure_report(
            run_id=fallback_run_id,
            checked_at=fallback_checked_at,
            error=error,
        )

        try:
            cleaning = load_yaml(CLEANING_CONFIG_PATH)
            deep_config = cleaning["deep_validation"]

            latest_report_path = project_path(
                deep_config["latest_report_path"]
            )

            historical_report_path = (
                project_path(
                    deep_config["report_directory"]
                )
                / (
                    "crash_core_deep_validation_"
                    f"{fallback_run_id}.json"
                )
            )

            issue_register_path = project_path(
                cleaning["evidence"][
                    "issue_register_path"
                ]
            )
        except Exception:
            latest_report_path = (
                ROOT
                / "docs"
                / "data_quality"
                / "crash_core_deep_validation.json"
            )

            historical_report_path = (
                ROOT
                / "docs"
                / "data_quality"
                / "deep_validation_runs"
                / (
                    "crash_core_deep_validation_"
                    f"{fallback_run_id}.json"
                )
            )

            issue_register_path = (
                ROOT
                / "docs"
                / "data_quality"
                / "data_quality_issue_register.csv"
            )

    write_json_atomic(historical_report_path, report)
    write_json_atomic(latest_report_path, report)

    try:
        cleaning = load_yaml(CLEANING_CONFIG_PATH)

        if cleaning["deep_validation"][
            "append_to_issue_register"
        ]:
            append_issue_register(
                register_path=issue_register_path,
                report=report,
                report_path=historical_report_path,
            )
    except Exception as register_error:
        print(
            "WARNING: The validation report was saved, but "
            "the issue register could not be updated:"
        )
        print(str(register_error))

    print("=" * 75)
    print(f"Status: {report['status']}")
    print(
        "Downstream readiness: "
        f"{report['downstream_readiness']}"
    )
    print(f"Issues: {len(report['issues'])}")
    print(
        "Historical report: "
        f"{historical_report_path}"
    )
    print(f"Latest report: {latest_report_path}")
    print("=" * 75)

    return 1 if report["status"] == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())