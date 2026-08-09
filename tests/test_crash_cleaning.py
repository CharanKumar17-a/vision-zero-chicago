from pathlib import Path

import pandas as pd
import yaml

from src.data.crash_cleaning import (
    classify_coordinates,
    coerce_nullable_float,
    coerce_nullable_integer,
    count_invalid_indicator_values,
    map_severity,
    normalize_string_series,
    parse_crash_dates,
)


ROOT = Path(__file__).resolve().parents[1]
CLEANING_CONFIG_PATH = ROOT / "config" / "cleaning.yml"


def load_cleaning_config() -> dict:
    with CLEANING_CONFIG_PATH.open(encoding="utf-8") as file:
        return yaml.safe_load(file)


def test_normalize_string_series():
    source = pd.Series(
        [" fatal ", "", None, " no indication of injury "],
        dtype="string",
    )

    result = normalize_string_series(
        source,
        uppercase=True,
    )

    assert result.iloc[0] == "FATAL"
    assert pd.isna(result.iloc[1])
    assert pd.isna(result.iloc[2])
    assert result.iloc[3] == "NO INDICATION OF INJURY"


def test_coerce_nullable_integer():
    source = pd.Series(
        ["1", " 2 ", "", None, "bad", "3.5"],
        dtype="string",
    )

    result, invalid_count = coerce_nullable_integer(source)

    assert str(result.dtype) == "Int64"
    assert result.iloc[0] == 1
    assert result.iloc[1] == 2
    assert result.iloc[2:].isna().all()
    assert invalid_count == 2


def test_coerce_nullable_float():
    source = pd.Series(
        ["41.88", " -87.63 ", "", None, "bad"],
        dtype="string",
    )

    result, invalid_count = coerce_nullable_float(source)

    assert str(result.dtype) == "Float64"
    assert result.iloc[0] == 41.88
    assert result.iloc[1] == -87.63
    assert result.iloc[2:].isna().all()
    assert invalid_count == 1


def test_parse_crash_dates():
    source = pd.Series(
        [
            "2018-01-15T12:30:00.000",
            "2025-12-31T23:52:00.000",
            "not-a-date",
        ],
        dtype="string",
    )

    parsed, years, month_starts, invalid_count = (
        parse_crash_dates(source)
    )

    assert invalid_count == 1
    assert years.iloc[0] == 2018
    assert years.iloc[1] == 2025
    assert pd.isna(years.iloc[2])

    assert month_starts.iloc[0] == pd.Timestamp("2018-01-01")
    assert month_starts.iloc[1] == pd.Timestamp("2025-12-01")
    assert pd.isna(month_starts.iloc[2])

    assert pd.isna(parsed.iloc[2])


def test_map_severity():
    config = load_cleaning_config()["severity"]

    source = pd.Series(
        [
            "FATAL",
            "NO INDICATION OF INJURY",
            "",
            None,
            "UNEXPECTED VALUE",
        ],
        dtype="string",
    )

    result, metrics = map_severity(
        source,
        mapping=config["mapping"],
        unknown_code=config["unknown_code"],
    )

    assert result.tolist() == ["K", "O", "U", "U", "U"]
    assert metrics["blank_severity_rows"] == 2
    assert metrics["unmapped_severity_rows"] == 1


def test_classify_coordinates():
    config = load_cleaning_config()["coordinates"]

    latitude = pd.Series(
        ["41.88", None, "41.90", "bad", "95"],
        dtype="string",
    )

    longitude = pd.Series(
        ["-87.63", None, None, "-87.60", "-87.60"],
        dtype="string",
    )

    result, status_counts = classify_coordinates(
        latitude,
        longitude,
        config,
    )

    assert result["coordinate_status"].tolist() == [
        "valid",
        "missing_pair",
        "incomplete_pair",
        "non_numeric",
        "out_of_range",
    ]

    assert result["has_valid_coordinates"].tolist() == [
        True,
        False,
        False,
        False,
        False,
    ]

    assert status_counts == {
        "valid": 1,
        "missing_pair": 1,
        "incomplete_pair": 1,
        "non_numeric": 1,
        "out_of_range": 1,
    }


def test_count_invalid_indicator_values():
    source = pd.Series(
        ["Y", "N", " y ", "", "X", None],
        dtype="string",
    )

    invalid_count = count_invalid_indicator_values(
        source,
        allowed_values=["Y", "N"],
    )

    assert invalid_count == 1