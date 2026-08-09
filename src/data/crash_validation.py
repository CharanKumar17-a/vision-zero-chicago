"""Independent validation calculations for the cleaned crash dataset.

This module must not import transformation functions from crash_cleaning.py.
The validator independently recomputes important derived fields so that it
can detect transformation errors instead of repeating them.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pandas as pd


SCHEMA_GROUPS = (
    "datetime_columns",
    "string_columns",
    "nullable_integer_columns",
    "nullable_float_columns",
)

INJURY_COMPONENT_COLUMNS = (
    "injuries_fatal",
    "injuries_incapacitating",
    "injuries_non_incapacitating",
    "injuries_reported_not_evident",
)


def configured_output_columns(
    cleaning: Mapping[str, Any],
) -> list[str]:
    """Return all configured source and derived output columns."""

    columns: list[str] = []

    for group in SCHEMA_GROUPS:
        columns.extend(cleaning["schema"][group])

    columns.extend(cleaning["derived_columns"].keys())

    return columns


def normalize_text(series: pd.Series) -> pd.Series:
    """Normalize text for independent comparison."""

    normalized = series.astype("string").str.strip().str.upper()
    return normalized.mask(normalized.eq(""))


def numeric_series(series: pd.Series) -> pd.Series:
    """Convert a series to nullable numeric values."""

    return pd.to_numeric(series, errors="coerce")


def string_mismatch_count(
    actual: pd.Series,
    expected: pd.Series,
) -> int:
    """Count null-safe string mismatches."""

    actual_normalized = actual.astype("string")
    expected_normalized = expected.astype("string")

    matches = actual_normalized.eq(expected_normalized)
    both_missing = actual_normalized.isna() & expected_normalized.isna()

    return int((~(matches.fillna(False) | both_missing)).sum())


def numeric_mismatch_count(
    actual: pd.Series,
    expected: pd.Series,
) -> int:
    """Count null-safe numeric mismatches."""

    actual_numeric = numeric_series(actual)
    expected_numeric = numeric_series(expected)

    matches = actual_numeric.eq(expected_numeric)
    both_missing = actual_numeric.isna() & expected_numeric.isna()

    return int((~(matches.fillna(False) | both_missing)).sum())


def boolean_series(series: pd.Series) -> pd.Series:
    """Convert common boolean representations to nullable booleans."""

    if pd.api.types.is_bool_dtype(series.dtype):
        return series.astype("boolean")

    normalized = series.astype("string").str.strip().str.lower()

    return normalized.map(
        {
            "true": True,
            "false": False,
            "1": True,
            "0": False,
        }
    ).astype("boolean")


def boolean_mismatch_count(
    actual: pd.Series,
    expected: pd.Series,
) -> int:
    """Count null-safe boolean mismatches."""

    actual_boolean = boolean_series(actual)
    expected_boolean = expected.astype("boolean")

    matches = actual_boolean.eq(expected_boolean)
    both_missing = actual_boolean.isna() & expected_boolean.isna()

    return int((~(matches.fillna(False) | both_missing)).sum())


def expected_severity(
    frame: pd.DataFrame,
    cleaning: Mapping[str, Any],
) -> pd.Series:
    """Independently derive the configured KABCO severity code."""

    severity = cleaning["severity"]
    source_column = severity["source_field"]
    unknown_code = severity["unknown_code"]

    mapping = {
        str(source).strip().upper(): target
        for source, target in severity["mapping"].items()
    }

    normalized_source = normalize_text(frame[source_column])

    return (
        normalized_source.map(mapping)
        .fillna(unknown_code)
        .astype("string")
    )


def expected_coordinate_fields(
    frame: pd.DataFrame,
    cleaning: Mapping[str, Any],
) -> tuple[pd.Series, pd.Series]:
    """Independently derive coordinate status and validity."""

    coordinates = cleaning["coordinates"]

    latitude_column = coordinates["latitude_field"]
    longitude_column = coordinates["longitude_field"]

    latitude_source = frame[latitude_column]
    longitude_source = frame[longitude_column]

    latitude_numeric = numeric_series(latitude_source)
    longitude_numeric = numeric_series(longitude_source)

    latitude_present = latitude_source.notna()
    longitude_present = longitude_source.notna()

    latitude_non_numeric = latitude_present & latitude_numeric.isna()
    longitude_non_numeric = longitude_present & longitude_numeric.isna()

    missing_pair = ~latitude_present & ~longitude_present
    incomplete_pair = latitude_present ^ longitude_present

    non_numeric = (
        ~missing_pair
        & ~incomplete_pair
        & (latitude_non_numeric | longitude_non_numeric)
    )

    globally_valid = (
        latitude_numeric.between(
            coordinates["latitude_minimum"],
            coordinates["latitude_maximum"],
            inclusive="both",
        )
        & longitude_numeric.between(
            coordinates["longitude_minimum"],
            coordinates["longitude_maximum"],
            inclusive="both",
        )
    )

    out_of_range = (
        ~missing_pair
        & ~incomplete_pair
        & ~non_numeric
        & ~globally_valid
    )

    valid = (
        ~missing_pair
        & ~incomplete_pair
        & ~non_numeric
        & ~out_of_range
    )

    status = pd.Series(
        pd.NA,
        index=frame.index,
        dtype="string",
    )

    status.loc[missing_pair] = coordinates["missing_pair_status"]
    status.loc[incomplete_pair] = coordinates["incomplete_pair_status"]
    status.loc[non_numeric] = coordinates["non_numeric_status"]
    status.loc[out_of_range] = coordinates["out_of_range_status"]
    status.loc[valid] = coordinates["valid_status"]

    return status, valid.astype("boolean")


def numeric_range_warning_counts(
    frame: pd.DataFrame,
    cleaning: Mapping[str, Any],
) -> dict[str, int]:
    """Count values outside configured plausibility ranges."""

    results: dict[str, int] = {}

    for column, rules in cleaning["numeric_quality_ranges"].items():
        values = numeric_series(frame[column])

        outside_range = values.notna() & (
            values.lt(rules["minimum"])
            | values.gt(rules["maximum"])
        )

        results[column] = int(outside_range.sum())

    return results


def validate_batch(
    frame: pd.DataFrame,
    cleaning: Mapping[str, Any],
    history_start: str,
    history_end: str,
) -> dict[str, Any]:
    """Validate one cleaned-data batch and return additive metrics."""

    required_columns = configured_output_columns(cleaning)

    missing_columns = sorted(
        set(required_columns) - set(frame.columns)
    )

    if missing_columns:
        raise ValueError(
            f"Missing configured output columns: {missing_columns}"
        )

    primary_key = cleaning["dataset"]["output"]["primary_key"]
    crash_dates = pd.to_datetime(
        frame["crash_date"],
        errors="coerce",
    )

    start_timestamp = pd.Timestamp(history_start)
    end_exclusive = pd.Timestamp(history_end) + pd.Timedelta(days=1)

    valid_dates = crash_dates.notna()

    dates_outside_window = valid_dates & (
        crash_dates.lt(start_timestamp)
        | crash_dates.ge(end_exclusive)
    )

    expected_year = crash_dates.dt.year.astype("Int64")
    expected_month_start = crash_dates.dt.to_period("M").dt.to_timestamp()

    severity_expected = expected_severity(frame, cleaning)

    coordinate_status_expected, coordinate_valid_expected = (
        expected_coordinate_fields(frame, cleaning)
    )

    actual_coordinate_status = frame[
        cleaning["coordinates"]["status_field"]
    ]

    actual_coordinate_valid = frame[
        cleaning["coordinates"]["valid_flag_field"]
    ]

    injury_components = frame[
        list(INJURY_COMPONENT_COLUMNS)
    ].apply(numeric_series)

    injuries_total = numeric_series(frame["injuries_total"])

    reconciliation_eligible = (
        injuries_total.notna()
        & injury_components.notna().all(axis=1)
    )

    calculated_injuries_total = injury_components.sum(axis=1)

    injury_reconciliation_mismatch = (
        reconciliation_eligible
        & calculated_injuries_total.ne(injuries_total)
    )

    negative_injury_values = (
        injury_components.lt(0).any(axis=1)
        | injuries_total.lt(0)
    )

    expected_hour = crash_dates.dt.hour.astype("Int64")
    expected_month = crash_dates.dt.month.astype("Int64")

    # Chicago crash_day_of_week uses Sunday=1 through Saturday=7.
    expected_day_of_week = (
        ((crash_dates.dt.dayofweek + 1) % 7) + 1
    ).astype("Int64")

    indicator_config = cleaning["indicator_fields"]
    allowed_indicator_values = set(
        indicator_config["allowed_non_null_values"]
    )

    invalid_indicator_values = 0

    for column in indicator_config["columns"]:
        normalized = normalize_text(frame[column])

        invalid_indicator_values += int(
            (
                normalized.notna()
                & ~normalized.isin(allowed_indicator_values)
            ).sum()
        )

    coordinate_status_counts = {
        str(status): int(count)
        for status, count in (
            actual_coordinate_status
            .astype("string")
            .value_counts(dropna=False)
            .items()
        )
    }

    valid_coordinate_rows = int(
        boolean_series(actual_coordinate_valid)
        .fillna(False)
        .sum()
    )

    return {
        "rows": int(len(frame)),
        "missing_primary_keys": int(
            frame[primary_key].isna().sum()
        ),
        "duplicate_primary_keys_within_batch": int(
            frame[primary_key].duplicated(keep=False).sum()
        ),
        "invalid_crash_dates": int(crash_dates.isna().sum()),
        "dates_outside_historical_window": int(
            dates_outside_window.sum()
        ),
        "crash_year_mismatches": numeric_mismatch_count(
            frame["crash_year"],
            expected_year,
        ),
        "crash_month_start_mismatches": string_mismatch_count(
            pd.to_datetime(
                frame["crash_month_start"],
                errors="coerce",
            ),
            expected_month_start,
        ),
        "severity_kabco_mismatches": string_mismatch_count(
            frame[cleaning["severity"]["output_field"]],
            severity_expected,
        ),
        "coordinate_status_mismatches": string_mismatch_count(
            actual_coordinate_status,
            coordinate_status_expected,
        ),
        "coordinate_valid_flag_mismatches": boolean_mismatch_count(
            actual_coordinate_valid,
            coordinate_valid_expected,
        ),
        "valid_coordinate_rows": valid_coordinate_rows,
        "coordinate_status_counts": coordinate_status_counts,
        "blank_or_unknown_severity_rows": int(
            severity_expected.eq(
                cleaning["severity"]["unknown_code"]
            ).sum()
        ),
        "invalid_indicator_values": invalid_indicator_values,
        "negative_injury_value_rows": int(
            negative_injury_values.sum()
        ),
        "injury_reconciliation_mismatches": int(
            injury_reconciliation_mismatch.sum()
        ),
        "crash_hour_mismatches": numeric_mismatch_count(
            frame["crash_hour"],
            expected_hour,
        ),
        "crash_day_of_week_mismatches": numeric_mismatch_count(
            frame["crash_day_of_week"],
            expected_day_of_week,
        ),
        "crash_month_mismatches": numeric_mismatch_count(
            frame["crash_month"],
            expected_month,
        ),
        "numeric_range_warning_counts": (
            numeric_range_warning_counts(frame, cleaning)
        ),
    }