import csv
import json
from datetime import date
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]

PROJECT_CONFIG_PATH = ROOT / "config" / "project.yml"
SOURCES_CONFIG_PATH = ROOT / "config" / "sources.yml"
ACQUISITION_CONFIG_PATH = ROOT / "config" / "acquisition.yml"


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as file:
        data = yaml.safe_load(file)

    assert isinstance(data, dict), f"Expected YAML mapping in {path}"
    return data


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as file:
        data = json.load(file)

    assert isinstance(data, dict), f"Expected JSON object in {path}"
    return data


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def latest_file(directory: Path, pattern: str) -> Path:
    candidates = sorted(directory.glob(pattern))
    assert candidates, f"No files matched {directory / pattern}"
    return candidates[-1]


def load_config() -> dict[str, Any]:
    return load_yaml(PROJECT_CONFIG_PATH)


def test_required_directories_exist():
    required_directories = [
        "config",
        "data/raw",
        "data/interim",
        "data/processed",
        "data/external",
        "docs/decisions",
        "docs/data_quality",
        "docs/data_quality/acquisition_manifests",
        "docs/data_quality/raw_snapshot_validation",
        "docs/evidence",
        "notebooks",
        "src/data",
        "src/features",
        "src/models",
        "src/treatments",
        "src/optimization",
        "src/validation",
        "src/visualization",
        "tests",
        "outputs/figures",
        "outputs/tables",
        "outputs/forecasts",
        "outputs/recommendations",
        "outputs/logs",
        "dashboard/powerbi",
        "dashboard/streamlit",
        "automation/n8n",
        "reports",
    ]

    missing = [
        directory
        for directory in required_directories
        if not (ROOT / directory).is_dir()
    ]

    assert not missing, f"Missing directories: {missing}"


def test_expected_dataset_sizes_are_correct():
    config = load_config()
    analysis = config["analysis"]

    assert analysis["expected_panel_rows"] == (
        analysis["corridor_count"]
        * analysis["history_months"]
    )

    assert analysis["expected_forecast_rows"] == (
        analysis["corridor_count"]
        * analysis["forecast_months"]
    )


def test_governance_boundary_is_configured():
    config = load_config()
    governance = config["governance"]

    assert (
        governance["final_decision_authority"]
        == "city_and_engineering_team"
    )

    assert governance["automated_project_approval"] is False


def test_decision_contract_exists():
    contract_path = ROOT / "docs" / "decision_contract.md"

    assert contract_path.is_file()
    assert contract_path.stat().st_size > 0

    contract_text = contract_path.read_text(
        encoding="utf-8"
    ).lower()

    assert "final decision remains with the city" in contract_text


def test_historical_window_matches_expected_months():
    config = load_config()
    analysis = config["analysis"]

    history_start = date.fromisoformat(
        analysis["history_start"]
    )

    history_end = date.fromisoformat(
        analysis["history_end"]
    )

    calculated_months = (
        (history_end.year - history_start.year) * 12
        + history_end.month
        - history_start.month
        + 1
    )

    assert history_start == date(2018, 1, 1)
    assert history_end == date(2025, 12, 31)
    assert calculated_months == analysis["history_months"]
    assert calculated_months == 96


def test_acquisition_contract_is_safe_and_reproducible():
    contract = load_yaml(ACQUISITION_CONFIG_PATH)
    settings = contract["acquisition"]

    assert settings["history_start"] == (
        "2018-01-01T00:00:00.000"
    )
    assert settings["history_end_exclusive"] == (
        "2026-01-01T00:00:00.000"
    )
    assert settings["batch_size"] == 50000
    assert settings["output_format"] == "csv.gz"
    assert settings["preserve_raw_files"] is True
    assert settings["overwrite_existing_files"] is False
    assert settings["raw_root"].startswith("data/raw/")
    assert settings["manifest_root"].startswith(
        "docs/data_quality/"
    )


def test_acquisition_source_contracts_are_complete():
    source_catalog = load_yaml(SOURCES_CONFIG_PATH)
    contract = load_yaml(ACQUISITION_CONFIG_PATH)

    assert set(contract["sources"]) == {
        "crashes",
        "vehicles",
        "people",
    }

    for source_name, acquisition_source in contract[
        "sources"
    ].items():
        source_key = acquisition_source["source_config_key"]
        source_config = source_catalog["sources"][source_key]

        selected_fields = acquisition_source["select_fields"]
        primary_key = source_config["primary_key"]
        date_field = acquisition_source["date_field"]

        assert len(selected_fields) == len(set(selected_fields))
        assert primary_key in selected_fields
        assert date_field in selected_fields
        assert set(source_config["required_fields"]).issubset(
            selected_fields
        )
        assert acquisition_source["order_by"] == [
            date_field,
            primary_key,
        ]

        assert source_name == source_key


def test_day3_acquisition_evidence_is_complete():
    contract_report_path = (
        ROOT
        / "docs"
        / "data_quality"
        / "acquisition_contract_validation.json"
    )
    contract_report = load_json(contract_report_path)
    assert contract_report["overall_status"] == "PASS"

    manifest_root = (
        ROOT
        / "docs"
        / "data_quality"
        / "acquisition_manifests"
    )
    validation_root = (
        ROOT
        / "docs"
        / "data_quality"
        / "raw_snapshot_validation"
    )

    for source_name in ("crashes", "vehicles", "people"):
        manifest_path = latest_file(
            manifest_root,
            f"{source_name}_*_manifest.json",
        )
        manifest = load_json(manifest_path)

        assert manifest["status"] == "PASS"
        assert manifest["expected_rows_before_download"] > 0
        assert manifest["expected_rows_before_download"] == (
            manifest["downloaded_rows"]
        )
        assert manifest["downloaded_rows"] == (
            manifest["expected_rows_after_download"]
        )
        assert manifest["part_count"] == len(manifest["parts"])

        validation_path = latest_file(
            validation_root,
            f"{source_name}_*_validation.json",
        )
        validation = load_json(validation_path)

        assert validation["acquisition_integrity_status"] == (
            "PASS"
        )
        assert validation["expected_rows"] == (
            validation["observed_rows"]
        )
        assert validation["missing_primary_keys"] == 0
        assert validation["duplicate_primary_keys"] == 0
        assert validation["invalid_dates"] == 0
        assert validation["dates_outside_window"] == 0


def test_day3_quality_issues_have_governance_rules():
    relationship_report_path = (
        ROOT
        / "docs"
        / "data_quality"
        / "raw_relationship_validation.json"
    )
    relationship_report = load_json(relationship_report_path)
    metrics = relationship_report["metrics"]

    decision_rows = load_csv(
        ROOT / "docs" / "decision_log.csv"
    )
    decision_ids = {
        row["decision_id"] for row in decision_rows
    }

    assumption_rows = load_csv(
        ROOT / "docs" / "assumption_register.csv"
    )
    assumptions = {
        row["assumption_id"]: row
        for row in assumption_rows
    }

    assert metrics["vehicle_orphan_rows"] == 0
    assert metrics["people_orphan_rows"] == 0

    if (
        metrics["vehicle_crash_date_mismatches"] > 0
        or metrics["people_crash_date_mismatches"] > 0
    ):
        assert "D008" in decision_ids

    if metrics["crashes_without_people_records"] > 0:
        assert "D009" in decision_ids

    crash_validation_path = latest_file(
        ROOT
        / "docs"
        / "data_quality"
        / "raw_snapshot_validation",
        "crashes_*_validation.json",
    )
    crash_validation = load_json(crash_validation_path)
    coordinate_profile = crash_validation["coordinate_profile"]

    if (
        coordinate_profile["missing_coordinate_pairs"] > 0
        or coordinate_profile["incomplete_coordinate_pairs"] > 0
    ):
        assert "A009" in assumptions
        assert assumptions["A009"]["status"] == "validated_rule"
        assert (
            assumptions["A009"]["sensitivity_required"]
            == "true"
        )