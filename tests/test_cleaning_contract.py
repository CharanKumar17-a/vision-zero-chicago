from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
ACQUISITION_CONFIG_PATH = ROOT / "config" / "acquisition.yml"
CLEANING_CONFIG_PATH = ROOT / "config" / "cleaning.yml"
CLEANING_CONTRACT_PATH = (
    ROOT / "docs" / "data_quality" / "cleaning_contract.md"
)


def load_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as file:
        return yaml.safe_load(file)


def load_contract_text() -> str:
    return CLEANING_CONTRACT_PATH.read_text(
        encoding="utf-8"
    )


def test_cleaning_files_exist_and_are_not_empty():
    assert CLEANING_CONFIG_PATH.is_file()
    assert CLEANING_CONTRACT_PATH.is_file()

    assert CLEANING_CONFIG_PATH.stat().st_size > 0
    assert CLEANING_CONTRACT_PATH.stat().st_size > 8_000


def test_cleaning_schema_matches_acquisition_schema():
    acquisition = load_yaml(ACQUISITION_CONFIG_PATH)
    cleaning = load_yaml(CLEANING_CONFIG_PATH)

    acquisition_fields = acquisition["sources"]["crashes"][
        "select_fields"
    ]

    schema = cleaning["schema"]

    cleaning_fields = (
        schema["datetime_columns"]
        + schema["string_columns"]
        + schema["nullable_integer_columns"]
        + schema["nullable_float_columns"]
    )

    assert len(acquisition_fields) == 39
    assert len(cleaning_fields) == 39
    assert len(cleaning_fields) == len(set(cleaning_fields))
    assert set(cleaning_fields) == set(acquisition_fields)


def test_cleaning_output_is_an_interim_parquet_file():
    cleaning = load_yaml(CLEANING_CONFIG_PATH)

    output_path = cleaning["dataset"]["output"]["path"]

    assert output_path == "data/interim/crashes_clean.parquet"
    assert Path(output_path).suffix == ".parquet"


def test_severity_mapping_is_exact():
    cleaning = load_yaml(CLEANING_CONFIG_PATH)

    expected_mapping = {
        "FATAL": "K",
        "INCAPACITATING INJURY": "A",
        "NONINCAPACITATING INJURY": "B",
        "REPORTED, NOT EVIDENT": "C",
        "NO INDICATION OF INJURY": "O",
    }

    assert cleaning["severity"]["mapping"] == expected_mapping


def test_cleaning_contract_has_required_sections():
    contract_text = load_contract_text()

    required_sections = [
        "## Input Contract",
        "## Output Contract",
        "## Schema Contract",
        "## Severity Contract",
        "## Injury Count Rules",
        "## Date and Time Rules",
        "## Coordinate Rules",
        "## Join Governance",
        "## Validation Levels",
        "## Required Validation Evidence",
        "## Known Limitations",
        "## Acceptance Criteria",
    ]

    missing_sections = [
        section
        for section in required_sections
        if section not in contract_text
    ]

    assert not missing_sections, (
        f"Missing cleaning-contract sections: {missing_sections}"
    )


def test_cleaning_contract_preserves_governance_rules():
    contract_text = load_contract_text()

    assert "decisions `D008` and `D009`" in contract_text
    assert "assumption `A009`" in contract_text
    assert "left join from crashes" in contract_text
    assert "crashes.crash_date" in contract_text

    assert (
        "Final project selection remains with the City "
        "and engineering teams."
        in contract_text
    )


def test_cleaning_contract_prohibits_silent_data_loss():
    contract_text = load_contract_text().lower()

    assert "same number of rows" in contract_text
    assert "remove rows with missing coordinates" in contract_text
    assert "silently impute missing values" in contract_text
    assert "raw files are immutable" in contract_text