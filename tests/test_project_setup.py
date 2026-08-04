from datetime import date
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "project.yml"


def load_config():
    with CONFIG_PATH.open(encoding="utf-8") as file:
        return yaml.safe_load(file)


def test_required_directories_exist():
    required_directories = [
        "config",
        "data/raw",
        "data/interim",
        "data/processed",
        "data/external",
        "docs/decisions",
        "docs/data_quality",
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