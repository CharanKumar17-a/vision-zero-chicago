from __future__ import annotations

import csv
import json
import logging
import sys
import traceback
from collections.abc import Mapping
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

from src.data.crash_cleaning import (  # noqa: E402
    classify_coordinates,
    coerce_nullable_float,
    coerce_nullable_integer,
    count_invalid_indicator_values,
    map_severity,
    normalize_string_series,
    parse_crash_dates,
)


CLEANING_CONFIG_PATH = ROOT / "config" / "cleaning.yml"
ACQUISITION_CONFIG_PATH = ROOT / "config" / "acquisition.yml"

ISSUE_COLUMNS = [
    "issue_id",
    "run_id",
    "detected_at_utc",
    "pipeline_stage",
    "dataset",
    "issue_code",
    "severity",
    "status",
    "affected_rows",
    "description",
    "evidence_file",
    "governance_reference",
    "resolution",
    "closed_at_utc",
]


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as file:
        value = yaml.safe_load(file)
    if not isinstance(value, dict):
        raise ValueError(f"Expected a YAML mapping: {path}")
    return value


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as file:
        value = json.load(file)
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def project_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def display_path(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def nested_value(mapping: Mapping[str, Any], key: str) -> Any:
    value: Any = mapping
    for part in key.split("."):
        if not isinstance(value, Mapping) or part not in value:
            raise KeyError(f"Missing configuration key: {key}")
        value = value[part]
    return value


def make_logger(log_path: Path) -> logging.Logger:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("build_crash_core")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s"
    )
    for handler in (
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_path, encoding="utf-8"),
    ):
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    return logger


def latest_successful_manifest(
    cleaning: Mapping[str, Any],
) -> tuple[Path, dict[str, Any]]:
    input_config = cleaning["dataset"]["input"]
    directory = project_path(input_config["manifest_directory"])
    manifests = sorted(
        directory.glob(input_config["manifest_pattern"]),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for path in manifests:
        manifest = load_json(path)
        if manifest.get("status") == "PASS":
            return path, manifest
    raise FileNotFoundError("No successful crash manifest was found")


def snapshot_parts(
    manifest: Mapping[str, Any],
) -> tuple[Path, list[Path]]:
    directory = project_path(str(manifest["snapshot_directory"]))
    if not directory.is_dir():
        raise FileNotFoundError(f"Snapshot directory missing: {directory}")
    parts = sorted(directory.glob("*.csv.gz"))
    expected = int(manifest["part_count"])
    if len(parts) != expected:
        raise ValueError(
            f"Manifest expects {expected} parts; found {len(parts)}"
        )
    return directory, parts


def date_window(
    cleaning: Mapping[str, Any],
) -> tuple[pd.Timestamp, pd.Timestamp]:
    config = cleaning["date_window"]
    project = load_yaml(project_path(config["source"]))
    start = pd.Timestamp(nested_value(project, config["start_key"]))
    end = pd.Timestamp(nested_value(project, config["end_key"]))
    return start, end + pd.Timedelta(days=1)


def empty_metrics() -> dict[str, Any]:
    return {
        "input_rows": 0,
        "output_rows": 0,
        "input_columns": 0,
        "output_columns": 0,
        "missing_primary_keys": 0,
        "duplicate_primary_keys": 0,
        "invalid_crash_dates": 0,
        "dates_outside_historical_window": 0,
        "minimum_crash_date": None,
        "maximum_crash_date": None,
        "blank_severity_rows": 0,
        "unmapped_severity_rows": 0,
        "severity_kabco_counts": {},
        "coordinate_status_counts": {},
        "valid_coordinate_rows": 0,
        "valid_coordinate_coverage": None,
        "invalid_indicator_values": {},
        "invalid_numeric_values": {},
        "numeric_range_warnings": {},
    }


def add_mapping(
    target: dict[str, int],
    values: Mapping[str, int],
) -> None:
    for key, value in values.items():
        target[str(key)] = target.get(str(key), 0) + int(value)


def update_date_limit(
    current: pd.Timestamp | None,
    candidate: pd.Timestamp | None,
    *,
    choose_minimum: bool,
) -> pd.Timestamp | None:
    if candidate is None or pd.isna(candidate):
        return current
    if current is None:
        return candidate
    if choose_minimum:
        return min(current, candidate)
    return max(current, candidate)


def numeric_range_counts(
    frame: pd.DataFrame,
    rules: Mapping[str, Any],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for column, rule in rules.items():
        series = frame[column]
        outside = series.notna() & (
            series.lt(rule["minimum"]) | series.gt(rule["maximum"])
        )
        counts[f"{column}_outside_range"] = int(outside.sum())
        if not rule["missing_allowed"]:
            counts[f"{column}_missing"] = int(series.isna().sum())
    return counts


def clean_part(
    raw: pd.DataFrame,
    cleaning: Mapping[str, Any],
    start: pd.Timestamp,
    end_exclusive: pd.Timestamp,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    frame = raw.copy()
    schema = cleaning["schema"]
    coordinate_config = cleaning["coordinates"]
    severity_config = cleaning["severity"]
    indicator_config = cleaning["indicator_fields"]
    uppercase = set(cleaning["text_normalization"]["uppercase_columns"])

    metrics: dict[str, Any] = {
        "input_rows": len(frame),
        "input_columns": len(frame.columns),
        "invalid_numeric_values": {},
        "invalid_indicator_values": {},
    }

    raw_latitude = frame[coordinate_config["latitude_field"]].copy()
    raw_longitude = frame[coordinate_config["longitude_field"]].copy()

    for column in schema["string_columns"]:
        frame[column] = normalize_string_series(
            frame[column], uppercase=column in uppercase
        )

    date_field = cleaning["processing"]["authoritative_timestamp"]
    parsed, year, month_start, invalid_dates = parse_crash_dates(
        frame[date_field]
    )
    frame[date_field] = parsed
    frame["crash_year"] = year
    frame["crash_month_start"] = month_start
    metrics["invalid_crash_dates"] = invalid_dates
    metrics["dates_outside_historical_window"] = int(
        (parsed.notna() & (parsed.lt(start) | parsed.ge(end_exclusive))).sum()
    )
    metrics["minimum_crash_date"] = parsed.min()
    metrics["maximum_crash_date"] = parsed.max()

    for column in schema["nullable_integer_columns"]:
        frame[column], invalid = coerce_nullable_integer(frame[column])
        metrics["invalid_numeric_values"][column] = invalid

    coordinate_fields = {
        coordinate_config["latitude_field"],
        coordinate_config["longitude_field"],
    }
    for column in schema["nullable_float_columns"]:
        if column not in coordinate_fields:
            frame[column], invalid = coerce_nullable_float(frame[column])
            metrics["invalid_numeric_values"][column] = invalid

    coordinates, coordinate_counts = classify_coordinates(
        raw_latitude, raw_longitude, coordinate_config
    )
    for column in coordinates:
        frame[column] = coordinates[column]
    metrics["coordinate_status_counts"] = coordinate_counts
    metrics["valid_coordinate_rows"] = coordinate_counts.get(
        coordinate_config["valid_status"], 0
    )

    severity, severity_metrics = map_severity(
        frame[severity_config["source_field"]],
        severity_config["mapping"],
        severity_config["unknown_code"],
    )
    frame[severity_config["output_field"]] = severity
    metrics.update(severity_metrics)
    metrics["severity_kabco_counts"] = {
        str(key): int(value)
        for key, value in severity.value_counts(dropna=False).items()
    }

    for column in indicator_config["columns"]:
        metrics["invalid_indicator_values"][column] = (
            count_invalid_indicator_values(
                frame[column], indicator_config["allowed_non_null_values"]
            )
        )

    metrics["numeric_range_warnings"] = numeric_range_counts(
        frame, cleaning["numeric_quality_ranges"]
    )
    metrics["missing_primary_keys"] = int(
        frame[cleaning["dataset"]["output"]["primary_key"]].isna().sum()
    )

    source_fields = (
        schema["datetime_columns"]
        + schema["string_columns"]
        + schema["nullable_integer_columns"]
        + schema["nullable_float_columns"]
    )
    output_fields = source_fields + list(cleaning["derived_columns"])
    if len(output_fields) != len(set(output_fields)):
        raise ValueError("Output schema contains duplicate columns")
    frame = frame[output_fields]
    metrics["output_rows"] = len(frame)
    metrics["output_columns"] = len(frame.columns)
    return frame, metrics


def merge_metrics(total: dict[str, Any], part: Mapping[str, Any]) -> None:
    for key in (
        "input_rows",
        "output_rows",
        "missing_primary_keys",
        "invalid_crash_dates",
        "dates_outside_historical_window",
        "blank_severity_rows",
        "unmapped_severity_rows",
        "valid_coordinate_rows",
    ):
        total[key] += int(part.get(key, 0))
    total["input_columns"] = max(total["input_columns"], part["input_columns"])
    total["output_columns"] = max(
        total["output_columns"], part["output_columns"]
    )
    total["minimum_crash_date"] = update_date_limit(
        total["minimum_crash_date"],
        part.get("minimum_crash_date"),
        choose_minimum=True,
    )
    total["maximum_crash_date"] = update_date_limit(
        total["maximum_crash_date"],
        part.get("maximum_crash_date"),
        choose_minimum=False,
    )
    for key in (
        "severity_kabco_counts",
        "coordinate_status_counts",
        "invalid_indicator_values",
        "invalid_numeric_values",
        "numeric_range_warnings",
    ):
        add_mapping(total[key], part.get(key, {}))


def issue(
    code: str,
    severity: str,
    rows: int,
    description: str,
    governance: str = "",
) -> dict[str, Any]:
    return {
        "issue_code": code,
        "severity": severity,
        "affected_rows": int(rows),
        "description": description,
        "governance_reference": governance,
    }


def validation_issues(
    metrics: Mapping[str, Any], expected_rows: int
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    critical = {
        "input_row_count_mismatch": (
            abs(metrics["input_rows"] - expected_rows),
            "Input rows do not match the successful manifest.",
        ),
        "output_row_count_mismatch": (
            abs(metrics["output_rows"] - metrics["input_rows"]),
            "Output rows do not match input rows.",
        ),
        "missing_primary_key": (
            metrics["missing_primary_keys"],
            "Primary key is missing after cleaning.",
        ),
        "duplicate_primary_key": (
            metrics["duplicate_primary_keys"],
            "Primary key is duplicated after cleaning.",
        ),
        "invalid_crash_date": (
            metrics["invalid_crash_dates"],
            "Authoritative crash date could not be parsed.",
        ),
        "crash_date_outside_window": (
            metrics["dates_outside_historical_window"],
            "Crash date is outside the approved historical window.",
        ),
    }
    for code, (rows, description) in critical.items():
        if rows:
            issues.append(issue(code, "ERROR", rows, description))

    warning_totals = {
        "blank_severity": (
            metrics["blank_severity_rows"],
            "Blank severity was mapped to U.",
            "severity contract",
        ),
        "unmapped_severity": (
            metrics["unmapped_severity_rows"],
            "Unmapped severity was mapped to U.",
            "severity contract",
        ),
        "invalid_coordinate": (
            metrics["input_rows"] - metrics["valid_coordinate_rows"],
            "Coordinate is unavailable or invalid for corridor assignment.",
            "A009",
        ),
    }
    for code, (rows, description, governance) in warning_totals.items():
        if rows:
            issues.append(
                issue(code, "WARNING", rows, description, governance)
            )

    groups = {
        "invalid_indicator_values": "invalid_indicator_value",
        "invalid_numeric_values": "invalid_numeric_value",
        "numeric_range_warnings": "numeric_range_warning",
    }
    for metric_name, code_prefix in groups.items():
        for field, rows in metrics[metric_name].items():
            if rows:
                issues.append(
                    issue(
                        f"{code_prefix}:{field}",
                        "WARNING",
                        rows,
                        f"Configured quality warning for {field}.",
                    )
                )
    return issues


def json_metrics(metrics: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(metrics)
    for key in ("minimum_crash_date", "maximum_crash_date"):
        value = result[key]
        result[key] = None if value is None else value.isoformat()
    return result


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as file:
        json.dump(value, file, indent=2, ensure_ascii=False)
        file.write("\n")
    temporary.replace(path)


def append_issues(
    path: Path,
    run_id: str,
    detected_at: str,
    issues: list[dict[str, Any]],
    evidence_file: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    has_content = path.is_file() and path.stat().st_size > 0
    with path.open("a", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=ISSUE_COLUMNS)
        if not has_content:
            writer.writeheader()
        for number, item in enumerate(issues, start=1):
            writer.writerow(
                {
                    "issue_id": f"DQ-{run_id}-{number:03d}",
                    "run_id": run_id,
                    "detected_at_utc": detected_at,
                    "pipeline_stage": "crash_cleaning",
                    "dataset": "crashes_clean",
                    "issue_code": item["issue_code"],
                    "severity": item["severity"],
                    "status": "open",
                    "affected_rows": item["affected_rows"],
                    "description": item["description"],
                    "evidence_file": evidence_file,
                    "governance_reference": item["governance_reference"],
                    "resolution": "",
                    "closed_at_utc": "",
                }
            )


def main() -> int:
    started = datetime.now(timezone.utc)
    run_id = started.strftime("%Y%m%dT%H%M%SZ")
    default_log = ROOT / "outputs" / "logs" / "cleaning"
    logger = make_logger(default_log / f"crash_cleaning_{run_id}.log")

    metrics = empty_metrics()
    issues: list[dict[str, Any]] = []
    status = "FAIL"
    published = False
    error: dict[str, Any] | None = None
    manifest_path: Path | None = None
    manifest: dict[str, Any] | None = None
    snapshot: Path | None = None
    output_path = ROOT / "data" / "interim" / "crashes_clean.parquet"
    temporary_output = output_path.with_name(
        f".{output_path.stem}_{run_id}.tmp.parquet"
    )
    report_path = (
        ROOT
        / "docs"
        / "data_quality"
        / "cleaning_runs"
        / f"crash_cleaning_{run_id}.json"
    )
    latest_report = (
        ROOT / "docs" / "data_quality" / "crash_cleaning_validation.json"
    )
    issue_register = (
        ROOT / "docs" / "data_quality" / "data_quality_issue_register.csv"
    )
    writer: pq.ParquetWriter | None = None

    logger.info("Crash cleaning started | run_id=%s", run_id)

    try:
        cleaning = load_yaml(CLEANING_CONFIG_PATH)
        acquisition = load_yaml(ACQUISITION_CONFIG_PATH)
        evidence = cleaning["evidence"]
        output_path = project_path(cleaning["dataset"]["output"]["path"])
        temporary_output = output_path.with_name(
            f".{output_path.stem}_{run_id}.tmp.parquet"
        )
        report_path = project_path(evidence["run_report_directory"]) / (
            f"crash_cleaning_{run_id}.json"
        )
        latest_report = project_path(evidence["latest_report_path"])
        issue_register = project_path(evidence["issue_register_path"])

        manifest_path, manifest = latest_successful_manifest(cleaning)
        snapshot, parts = snapshot_parts(manifest)
        source_key = cleaning["dataset"]["source_config_key"]
        selected_fields = acquisition["sources"][source_key]["select_fields"]
        if list(manifest["selected_fields"]) != list(selected_fields):
            raise ValueError(
                "Manifest fields do not match acquisition configuration"
            )

        start, end_exclusive = date_window(cleaning)
        expected_rows = int(manifest["downloaded_rows"])
        primary_key = cleaning["dataset"]["output"]["primary_key"]
        output_path.parent.mkdir(parents=True, exist_ok=True)
        seen_keys: set[str] = set()

        logger.info(
            "Manifest=%s | parts=%d | expected_rows=%s",
            manifest_path.name,
            len(parts),
            f"{expected_rows:,}",
        )

        for number, part in enumerate(parts, start=1):
            raw = pd.read_csv(
                part,
                usecols=selected_fields,
                dtype="string",
                compression="gzip",
                low_memory=False,
            )
            cleaned, part_metrics = clean_part(
                raw, cleaning, start, end_exclusive
            )

            for key in cleaned[primary_key].dropna().astype(str):
                if key in seen_keys:
                    metrics["duplicate_primary_keys"] += 1
                else:
                    seen_keys.add(key)

            merge_metrics(metrics, part_metrics)
            table = pa.Table.from_pandas(
                cleaned, preserve_index=False
            ).replace_schema_metadata()
            if writer is None:
                writer = pq.ParquetWriter(
                    temporary_output,
                    table.schema,
                    compression="snappy",
                )
            writer.write_table(table)
            logger.info(
                "Part %05d/%05d | rows=%s | total=%s",
                number,
                len(parts),
                f"{len(cleaned):,}",
                f"{metrics['output_rows']:,}",
            )

        if writer is not None:
            writer.close()
            writer = None

        metrics["valid_coordinate_coverage"] = (
            metrics["valid_coordinate_rows"] / metrics["input_rows"]
        )
        issues = validation_issues(metrics, expected_rows)
        errors = sum(item["severity"] == "ERROR" for item in issues)
        warnings = sum(item["severity"] == "WARNING" for item in issues)
        status = (
            "FAIL"
            if errors
            else "PASS_WITH_WARNINGS"
            if warnings
            else "PASS"
        )

        if status == "FAIL":
            temporary_output.unlink(missing_ok=True)
            logger.error("Critical validation failed; output not published")
        else:
            temporary_output.replace(output_path)
            published = True
            logger.info("Published %s", output_path)

    except Exception as exception:
        if writer is not None:
            writer.close()
            writer = None
        temporary_output.unlink(missing_ok=True)
        error = {
            "type": type(exception).__name__,
            "message": str(exception),
            "traceback": traceback.format_exc(),
        }
        issues.append(
            issue(
                "pipeline_exception",
                "ERROR",
                1,
                f"{type(exception).__name__}: {exception}",
            )
        )
        logger.exception("Crash cleaning failed")

    completed = datetime.now(timezone.utc)
    report = {
        "pipeline": "crash_core_cleaning",
        "run_id": run_id,
        "started_at_utc": started.isoformat(timespec="seconds"),
        "completed_at_utc": completed.isoformat(timespec="seconds"),
        "status": status,
        "downstream_readiness": "NOT_READY" if status == "FAIL" else status,
        "published_output": published,
        "manifest": {
            "path": display_path(manifest_path),
            "status": manifest.get("status") if manifest else None,
            "snapshot_directory": display_path(snapshot),
            "expected_rows": (
                int(manifest["downloaded_rows"]) if manifest else None
            ),
            "part_count": int(manifest["part_count"]) if manifest else None,
        },
        "output": {
            "path": display_path(output_path),
            "exists": output_path.is_file(),
            "size_bytes": (
                output_path.stat().st_size if output_path.is_file() else None
            ),
        },
        "metrics": json_metrics(metrics),
        "issues": issues,
        "error": error,
        "governance": {
            "raw_files_modified": False,
            "rows_dropped_by_policy": False,
            "imputation_used": False,
            "final_decision_authority": "city_and_engineering_team",
        },
    }

    write_json(report_path, report)
    write_json(latest_report, report)
    append_issues(
        issue_register,
        run_id,
        completed.isoformat(timespec="seconds"),
        issues,
        display_path(report_path) or "",
    )

    logger.info("Status=%s | report=%s", status, report_path)
    logger.info("Elapsed=%s", completed - started)
    return 1 if status == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())