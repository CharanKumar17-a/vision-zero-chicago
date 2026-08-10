"""Tests for the spatial-assignment configuration and contract."""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]

SPATIAL_CONFIG_PATH = ROOT / "config" / "spatial.yml"
SOURCES_CONFIG_PATH = ROOT / "config" / "sources.yml"

SPATIAL_CONTRACT_PATH = (
    ROOT
    / "docs"
    / "data_quality"
    / "spatial_assignment_contract.md"
)


def load_yaml(path: Path):
    with path.open(encoding="utf-8") as file:
        return yaml.safe_load(file)


def load_contract_text() -> str:
    return SPATIAL_CONTRACT_PATH.read_text(
        encoding="utf-8"
    )


def test_spatial_dataset_contract_is_configured():
    spatial = load_yaml(SPATIAL_CONFIG_PATH)
    dataset = spatial["dataset"]

    assert spatial["version"] == 1
    assert dataset["expected_corridor_count"] == 43
    assert dataset["primary_key"] == "corridor_id"

    assert (
        dataset["expected_grain"]
        == "one row per official high-crash corridor"
    )

    assert (
        dataset["outputs"]["corridor_register"]["path"]
        == "data/interim/high_crash_corridor_register.csv"
    )

    assert (
        dataset["outputs"]["corridor_geometry"]["path"]
        == "data/interim/high_crash_corridors.parquet"
    )

    assert (
        dataset["outputs"]["geometry_review"]["path"]
        == "data/interim/high_crash_corridors_review.geojson"
    )


def test_spatial_source_keys_exist():
    spatial = load_yaml(SPATIAL_CONFIG_PATH)
    sources = load_yaml(SOURCES_CONFIG_PATH)

    corridor_sources = sources["corridor_sources"]

    corridor_definition_key = spatial[
        "source_contract"
    ]["corridor_definition"]["source_config_key"]

    street_geometry_key = spatial[
        "source_contract"
    ]["street_geometry"]["source_config_key"]

    assert corridor_definition_key in corridor_sources
    assert street_geometry_key in corridor_sources

    assert (
        spatial["source_contract"]["street_geometry"][
            "dataset_id"
        ]
        == "6imu-meau"
    )

    assert (
        spatial["source_contract"]["corridor_definition"][
            "allow_unverified_corridors"
        ]
        is False
    )

    assert (
        spatial["source_contract"]["street_geometry"][
            "allow_manual_geometry_drawing"
        ]
        is False
    )


def test_corridor_register_contract_is_complete():
    spatial = load_yaml(SPATIAL_CONFIG_PATH)
    register = spatial["corridor_register"]

    required_columns = register["required_columns"]

    assert set(required_columns) == {
        "corridor_id",
        "corridor_name",
        "street_name",
        "from_street",
        "to_street",
        "source_name",
        "source_page",
        "extraction_status",
        "geometry_status",
    }

    assert register["corridor_id"] == {
        "prefix": "HCC",
        "width": 3,
        "first_id": "HCC001",
        "last_id": "HCC043",
        "preserve_after_assignment": True,
    }

    extraction = register["extraction"]

    assert extraction[
        "method"
    ] == "structured_transcription_from_verified_plan"

    assert extraction["require_source_page"] is True

    assert (
        extraction["require_second_pass_verification"]
        is True
    )

    assert (
        extraction["allow_silent_boundary_inference"]
        is False
    )


def test_coordinate_reference_system_is_safe():
    spatial = load_yaml(SPATIAL_CONFIG_PATH)
    crs = spatial["coordinate_reference_system"]

    assert crs["source_crs"] == "EPSG:4326"
    assert crs["analysis_crs"] == "EPSG:3435"
    assert crs["publication_crs"] == "EPSG:4326"
    assert crs["analysis_units"] == "US_survey_feet"

    assert (
        "never_measure_distance_in_EPSG_4326"
        in crs["rules"]
    )

    assert (
        "reproject_before_distance_calculation"
        in crs["rules"]
    )


def test_threshold_requires_sensitivity_analysis():
    spatial = load_yaml(SPATIAL_CONFIG_PATH)
    assignment = spatial["crash_assignment"]

    assert assignment[
        "candidate_distance_thresholds_feet"
    ] == [50, 100, 150, 200]

    assert (
        assignment["selected_distance_threshold_feet"]
        is None
    )

    assert (
        assignment["threshold_status"]
        == "pending_sensitivity_analysis"
    )


def test_assignment_prevents_double_counting():
    spatial = load_yaml(SPATIAL_CONFIG_PATH)
    assignment = spatial["crash_assignment"]
    rules = assignment["assignment_rules"]

    assert rules["require_valid_coordinates"] is True
    assert rules["retain_all_candidate_matches"] is True
    assert rules["one_primary_corridor_per_crash"] is True
    assert rules["nearest_candidate_is_primary"] is True

    assert (
        rules["allow_double_counting_in_model_panel"]
        is False
    )

    ambiguity = assignment["ambiguity"]

    assert ambiguity["tie_tolerance_feet"] == 10

    assert (
        ambiguity["multiple_candidate_action"]
        == "assign_nearest_and_flag"
    )

    assert (
        ambiguity["unresolved_tie_action"]
        == "exclude_from_primary_model_and_review"
    )

    unmatched = assignment["unmatched_crashes"]

    assert (
        unmatched["preserve_in_citywide_quality_totals"]
        is True
    )

    assert unmatched["include_in_corridor_model"] is False
    assert unmatched["delete_from_clean_crash_core"] is False


def test_geometry_validation_rules_are_configured():
    spatial = load_yaml(SPATIAL_CONFIG_PATH)
    validation = spatial["validation"]

    fail_conditions = set(validation["fail_conditions"])
    warning_conditions = set(
        validation["warning_conditions"]
    )

    assert {
        "corridor_count_not_43",
        "missing_corridor_id",
        "duplicate_corridor_id",
        "missing_geometry",
        "empty_geometry",
        "invalid_geometry",
        "geometry_crs_missing",
        "geometry_crs_incorrect",
        "unresolved_corridor_boundary",
        "unverified_corridor_added",
    }.issubset(fail_conditions)

    assert {
        "multipart_corridor_geometry",
        "disconnected_corridor_geometry",
        "ambiguous_street_name_match",
        "multiple_boundary_candidates",
        "candidate_threshold_not_selected",
        "crash_assignment_ambiguity",
        "unmatched_valid_coordinate_crash",
    }.issubset(warning_conditions)

    length_review = validation[
        "geometry_length_review_feet"
    ]

    assert length_review["minimum"] == 500
    assert length_review["maximum"] == 60000
    assert length_review["action"] == "warn"


def test_spatial_evidence_policy_is_configured():
    spatial = load_yaml(SPATIAL_CONFIG_PATH)
    evidence = spatial["evidence"]

    assert evidence["persist_run_reports"] is True
    assert evidence["persist_failed_runs"] is True
    assert evidence["publish_geometry_on_failure"] is False

    assert (
        evidence["corridor_register_validation"][
            "latest_report_path"
        ]
        == "docs/data_quality/corridor_register_validation.json"
    )

    assert (
        evidence["geometry_validation"][
            "latest_report_path"
        ]
        == "docs/data_quality/corridor_geometry_validation.json"
    )

    assert (
        evidence["assignment_validation"][
            "latest_report_path"
        ]
        == (
            "docs/data_quality/"
            "crash_corridor_assignment_validation.json"
        )
    )

    assert (
        evidence["issue_register_path"]
        == "docs/data_quality/data_quality_issue_register.csv"
    )


def test_spatial_governance_boundary_is_configured():
    spatial = load_yaml(SPATIAL_CONFIG_PATH)
    governance = spatial["governance"]

    assert (
        governance["current_geometry_status"]
        == "pending_construction"
    )

    assert (
        governance["current_assignment_status"]
        == "blocked_until_geometry_passes"
    )

    assert (
        governance[
            "selected_distance_threshold_is_official_city_policy"
        ]
        is False
    )

    assert governance["automated_corridor_approval"] is False

    assert (
        governance["final_review_authority"]
        == "city_and_engineering_team"
    )


def test_spatial_contract_documents_required_rules():
    contract = load_contract_text()

    required_sections = [
        "## Coordinate Reference System Contract",
        "## Geometry Construction Contract",
        "## Crash Eligibility Contract",
        "## Threshold Selection Protocol",
        "## Candidate-Match Contract",
        "## Primary-Assignment Contract",
        "## Unmatched Crash Contract",
        "## Double-Counting Prevention",
        "## Geometry Validation",
        "## Assignment Validation",
        "## Acceptance Criteria: Corridor Register",
        "## Acceptance Criteria: Corridor Geometry",
        "## Acceptance Criteria: Crash Assignment",
        "## Analytical Limitations",
        "## Governance Boundary",
    ]

    for section in required_sections:
        assert section in contract

    assert (
        "Distance and buffer calculations must never "
        "be performed directly in EPSG:4326."
        in contract
    )

    assert (
        "A crash must never have more than one primary "
        "corridor in the modeling table."
        in contract
    )

    assert (
        "Final project selection remains with the City "
        "and engineering teams."
        in contract
    )