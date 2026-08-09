"""Tests for independent crash-core validation calculations."""

from pathlib import Path

import pandas as pd
import pytest
import yaml

from src.data.crash_validation import (
    configured_output_columns,
    validate_batch,
)


ROOT = Path(__file__).resolve().parents[1]
CLEANING_CONFIG_PATH = ROOT / "config" / "cleaning.yml"


def load_cleaning_config():
    with CLEANING_CONFIG_PATH.open(encoding="utf-8") as file:
        return yaml.safe_load(file)


def valid_clean_frame() -> pd.DataFrame:
    """Return one internally consistent cleaned crash record."""

    return pd.DataFrame(
        {
            "crash_record_id": ["TEST-001"],
            "crash_date": [pd.Timestamp("2020-01-06 10:00:00")],
            "posted_speed_limit": [30],
            "traffic_control_device": ["NO CONTROLS"],
            "device_condition": ["NO CONTROLS"],
            "weather_condition": ["CLEAR"],
            "lighting_condition": ["DAYLIGHT"],
            "first_crash_type": ["REAR END"],
            "trafficway_type": ["NOT DIVIDED"],
            "lane_cnt": [2],
            "alignment": ["STRAIGHT AND LEVEL"],
            "roadway_surface_cond": ["DRY"],
            "road_defect": ["NO DEFECTS"],
            "crash_type": ["NO INJURY / DRIVE AWAY"],
            "intersection_related_i": ["N"],
            "dooring_i": ["N"],
            "work_zone_i": ["N"],
            "hit_and_run_i": ["N"],
            "damage": ["OVER $1,500"],
            "prim_contributory_cause": [
                "FAILING TO REDUCE SPEED"
            ],
            "sec_contributory_cause": [
                "UNABLE TO DETERMINE"
            ],
            "street_no": [100],
            "street_direction": ["N"],
            "street_name": ["STATE ST"],
            "beat_of_occurrence": [111],
            "num_units": [2],
            "most_severe_injury": [
                "NO INDICATION OF INJURY"
            ],
            "injuries_total": [0],
            "injuries_fatal": [0],
            "injuries_incapacitating": [0],
            "injuries_non_incapacitating": [0],
            "injuries_reported_not_evident": [0],
            "injuries_no_indication": [2],
            "injuries_unknown": [0],
            "crash_hour": [10],
            # January 6, 2020 was Monday.
            # Chicago uses Sunday=1 and Monday=2.
            "crash_day_of_week": [2],
            "crash_month": [1],
            "latitude": [41.881],
            "longitude": [-87.627],
            "crash_year": [2020],
            "crash_month_start": [
                pd.Timestamp("2020-01-01")
            ],
            "severity_kabco": ["O"],
            "coordinate_status": ["valid"],
            "has_valid_coordinates": [True],
        }
    )


def validate(frame: pd.DataFrame):
    cleaning = load_cleaning_config()

    return validate_batch(
        frame=frame,
        cleaning=cleaning,
        history_start="2018-01-01",
        history_end="2025-12-31",
    )


def test_configured_output_contains_44_unique_columns():
    cleaning = load_cleaning_config()
    columns = configured_output_columns(cleaning)

    assert len(columns) == 44
    assert len(set(columns)) == 44

    assert "crash_record_id" in columns
    assert "crash_date" in columns
    assert "crash_year" in columns
    assert "crash_month_start" in columns
    assert "severity_kabco" in columns
    assert "coordinate_status" in columns
    assert "has_valid_coordinates" in columns


def test_valid_record_has_no_validation_mismatches():
    metrics = validate(valid_clean_frame())

    assert metrics["rows"] == 1
    assert metrics["missing_primary_keys"] == 0
    assert metrics["duplicate_primary_keys_within_batch"] == 0
    assert metrics["invalid_crash_dates"] == 0
    assert metrics["dates_outside_historical_window"] == 0

    assert metrics["crash_year_mismatches"] == 0
    assert metrics["crash_month_start_mismatches"] == 0
    assert metrics["severity_kabco_mismatches"] == 0
    assert metrics["coordinate_status_mismatches"] == 0
    assert metrics["coordinate_valid_flag_mismatches"] == 0

    assert metrics["invalid_indicator_values"] == 0
    assert metrics["negative_injury_value_rows"] == 0
    assert metrics["injury_reconciliation_mismatches"] == 0

    assert metrics["crash_hour_mismatches"] == 0
    assert metrics["crash_day_of_week_mismatches"] == 0
    assert metrics["crash_month_mismatches"] == 0

    assert metrics["valid_coordinate_rows"] == 1

    assert metrics["numeric_range_warning_counts"] == {
        "posted_speed_limit": 0,
        "lane_cnt": 0,
        "num_units": 0,
    }


def test_missing_configured_column_is_a_critical_error():
    frame = valid_clean_frame().drop(columns=["crash_year"])

    with pytest.raises(
        ValueError,
        match="Missing configured output columns",
    ):
        validate(frame)


def test_derived_date_mismatches_are_detected():
    frame = valid_clean_frame()

    frame.loc[0, "crash_year"] = 2019
    frame.loc[0, "crash_month_start"] = pd.Timestamp(
        "2020-02-01"
    )
    frame.loc[0, "crash_hour"] = 11
    frame.loc[0, "crash_day_of_week"] = 3
    frame.loc[0, "crash_month"] = 2

    metrics = validate(frame)

    assert metrics["crash_year_mismatches"] == 1
    assert metrics["crash_month_start_mismatches"] == 1
    assert metrics["crash_hour_mismatches"] == 1
    assert metrics["crash_day_of_week_mismatches"] == 1
    assert metrics["crash_month_mismatches"] == 1


def test_severity_mapping_mismatch_is_detected():
    frame = valid_clean_frame()
    frame.loc[0, "severity_kabco"] = "K"

    metrics = validate(frame)

    assert metrics["severity_kabco_mismatches"] == 1
    assert metrics["blank_or_unknown_severity_rows"] == 0


def test_coordinate_mismatches_are_detected():
    frame = valid_clean_frame()

    frame.loc[0, "latitude"] = pd.NA
    frame.loc[0, "longitude"] = pd.NA

    # These intentionally remain incorrect.
    frame.loc[0, "coordinate_status"] = "valid"
    frame.loc[0, "has_valid_coordinates"] = True

    metrics = validate(frame)

    assert metrics["coordinate_status_mismatches"] == 1
    assert metrics["coordinate_valid_flag_mismatches"] == 1


def test_injury_and_indicator_issues_are_detected():
    frame = valid_clean_frame()

    frame.loc[0, "injuries_total"] = 1
    frame.loc[0, "dooring_i"] = "MAYBE"

    metrics = validate(frame)

    assert metrics["injury_reconciliation_mismatches"] == 1
    assert metrics["invalid_indicator_values"] == 1


def test_negative_injury_values_are_detected():
    frame = valid_clean_frame()

    frame.loc[0, "injuries_fatal"] = -1

    metrics = validate(frame)

    assert metrics["negative_injury_value_rows"] == 1


def test_numeric_range_warnings_are_detected():
    frame = valid_clean_frame()

    frame.loc[0, "posted_speed_limit"] = 0
    frame.loc[0, "lane_cnt"] = 99
    frame.loc[0, "num_units"] = 21

    metrics = validate(frame)

    assert metrics["numeric_range_warning_counts"] == {
        "posted_speed_limit": 1,
        "lane_cnt": 1,
        "num_units": 1,
    }