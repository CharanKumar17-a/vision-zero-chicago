from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pandas as pd


def normalize_string_series(
    series: pd.Series,
    *,
    uppercase: bool = False,
) -> pd.Series:
    """Trim text, convert blanks to null and optionally uppercase it."""
    normalized = series.astype("string").str.strip()
    normalized = normalized.mask(normalized.eq(""), pd.NA)

    if uppercase:
        normalized = normalized.str.upper()

    return normalized


def coerce_nullable_integer(
    series: pd.Series,
) -> tuple[pd.Series, int]:
    """Convert values to nullable integers and count invalid values."""
    text = series.astype("string").str.strip()
    missing = series.isna() | text.eq("").fillna(False)
    cleaned = text.mask(missing, pd.NA)

    numeric = pd.to_numeric(cleaned, errors="coerce")

    non_numeric = (
        ~missing
        & numeric.isna()
    )

    fractional = (
        numeric.notna()
        & numeric.mod(1).ne(0)
    )

    invalid_count = int(
        non_numeric.sum() + fractional.sum()
    )

    numeric = numeric.mask(fractional)

    return numeric.astype("Int64"), invalid_count


def coerce_nullable_float(
    series: pd.Series,
) -> tuple[pd.Series, int]:
    """Convert values to nullable floats and count invalid values."""
    text = series.astype("string").str.strip()
    missing = series.isna() | text.eq("").fillna(False)
    cleaned = text.mask(missing, pd.NA)

    numeric = pd.to_numeric(cleaned, errors="coerce")

    non_numeric = (
        ~missing
        & numeric.isna()
    )

    return numeric.astype("Float64"), int(non_numeric.sum())


def parse_crash_dates(
    series: pd.Series,
) -> tuple[pd.Series, pd.Series, pd.Series, int]:
    """Parse crash timestamps and derive year and month-start fields."""
    text = series.astype("string").str.strip()
    cleaned = text.mask(text.eq("").fillna(False), pd.NA)

    parsed = pd.to_datetime(
        cleaned,
        errors="coerce",
        format="mixed",
    )

    invalid_count = int(parsed.isna().sum())

    crash_year = parsed.dt.year.astype("Int64")

    crash_month_start = (
        parsed.dt.to_period("M")
        .dt.to_timestamp()
    )

    return (
        parsed,
        crash_year,
        crash_month_start,
        invalid_count,
    )


def map_severity(
    series: pd.Series,
    mapping: Mapping[str, str],
    unknown_code: str,
) -> tuple[pd.Series, dict[str, int]]:
    """Map source severity values to KABCO codes."""
    normalized = normalize_string_series(
        series,
        uppercase=True,
    )

    blank_mask = normalized.isna()

    unmapped_mask = (
        normalized.notna()
        & ~normalized.isin(mapping.keys())
    )

    mapped = (
        normalized.map(mapping)
        .astype("string")
        .fillna(unknown_code)
    )

    metrics = {
        "blank_severity_rows": int(blank_mask.sum()),
        "unmapped_severity_rows": int(unmapped_mask.sum()),
    }

    return mapped, metrics


def classify_coordinates(
    latitude: pd.Series,
    longitude: pd.Series,
    config: Mapping[str, Any],
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Parse coordinates and assign a documented quality status."""
    latitude_text = latitude.astype("string").str.strip()
    longitude_text = longitude.astype("string").str.strip()

    latitude_missing = (
        latitude.isna()
        | latitude_text.eq("").fillna(False)
    )

    longitude_missing = (
        longitude.isna()
        | longitude_text.eq("").fillna(False)
    )

    latitude_numeric = pd.to_numeric(
        latitude_text.mask(latitude_missing, pd.NA),
        errors="coerce",
    ).astype("Float64")

    longitude_numeric = pd.to_numeric(
        longitude_text.mask(longitude_missing, pd.NA),
        errors="coerce",
    ).astype("Float64")

    both_missing = (
        latitude_missing
        & longitude_missing
    )

    incomplete_pair = (
        latitude_missing
        ^ longitude_missing
    )

    non_numeric = (
        ~latitude_missing
        & ~longitude_missing
        & (
            latitude_numeric.isna()
            | longitude_numeric.isna()
        )
    )

    numeric_pair = (
        latitude_numeric.notna()
        & longitude_numeric.notna()
    )

    out_of_range = (
        numeric_pair
        & (
            latitude_numeric.lt(
                config["latitude_minimum"]
            )
            | latitude_numeric.gt(
                config["latitude_maximum"]
            )
            | longitude_numeric.lt(
                config["longitude_minimum"]
            )
            | longitude_numeric.gt(
                config["longitude_maximum"]
            )
        )
    )

    status = pd.Series(
        config["valid_status"],
        index=latitude.index,
        dtype="string",
    )

    status = status.mask(
        both_missing,
        config["missing_pair_status"],
    )

    status = status.mask(
        incomplete_pair,
        config["incomplete_pair_status"],
    )

    status = status.mask(
        non_numeric,
        config["non_numeric_status"],
    )

    status = status.mask(
        out_of_range,
        config["out_of_range_status"],
    )

    valid_flag = status.eq(
        config["valid_status"]
    ).astype("boolean")

    output = pd.DataFrame(
        {
            config["latitude_field"]: latitude_numeric,
            config["longitude_field"]: longitude_numeric,
            config["status_field"]: status,
            config["valid_flag_field"]: valid_flag,
        },
        index=latitude.index,
    )

    status_counts = {
        str(key): int(value)
        for key, value in status.value_counts(
            dropna=False
        ).items()
    }

    return output, status_counts


def count_invalid_indicator_values(
    series: pd.Series,
    allowed_values: list[str],
) -> int:
    """Count non-null indicator values outside the allowed set."""
    normalized = normalize_string_series(
        series,
        uppercase=True,
    )

    invalid = (
        normalized.notna()
        & ~normalized.isin(allowed_values)
    )

    return int(invalid.sum())