"""Tests for the high-crash corridor register pipeline.

Covers: configuration structure, builder output, validator checks,
failure behavior, corridor IDs, source groups, aliases, evidence
paths, and governance rules.
"""

from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]

CORRIDORS_CONFIG_PATH = ROOT / "config" / "corridors.yml"
SPATIAL_CONFIG_PATH = ROOT / "config" / "spatial.yml"

REGISTER_PATH = (
    ROOT
    / "data"
    / "interim"
    / "high_crash_corridor_register.csv"
)

SPATIAL_CONTRACT_PATH = (
    ROOT
    / "docs"
    / "data_quality"
    / "spatial_assignment_contract.md"
)

DECISION_LOG_PATH = ROOT / "docs" / "decision_log.csv"


@pytest.fixture(scope="session", autouse=True)
def ensure_corridor_register_output() -> None:
    """Build the ignored register output when absent."""
    if not REGISTER_PATH.is_file():
        builder_path = (
            ROOT
            / "src"
            / "data"
            / "build_corridor_register.py"
        )

        result = subprocess.run(
            [sys.executable, str(builder_path)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, (
            "Corridor-register build failed.\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )

    assert REGISTER_PATH.is_file()


def load_yaml(path: Path):
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_register():
    with REGISTER_PATH.open(
        encoding="utf-8", newline=""
    ) as f:
        return list(csv.DictReader(f))


# ==============================================================
# Configuration tests
# ==============================================================


class TestCorridorConfiguration:
    """Tests for config/corridors.yml structure."""

    def test_config_exists(self):
        assert CORRIDORS_CONFIG_PATH.is_file()

    def test_config_version(self):
        config = load_yaml(CORRIDORS_CONFIG_PATH)
        assert config["version"] == 1

    def test_config_has_43_corridors(self):
        config = load_yaml(CORRIDORS_CONFIG_PATH)
        assert len(config["corridors"]) == 43

    def test_config_source_document(self):
        config = load_yaml(CORRIDORS_CONFIG_PATH)
        source = config["source"]
        assert (
            source["document"]
            == "high_crash_corridor_framework_plan.pdf"
        )
        assert source["canonical_page"] == 9
        assert source["cross_reference_pages"] == [
            27,
            28,
            29,
        ]

    def test_config_canonical_policy_exists(self):
        config = load_yaml(CORRIDORS_CONFIG_PATH)
        policy = config["source"]["canonical_policy"]
        assert "Page 9" in policy
        assert "authoritative" in policy.lower()

    def test_config_id_mapping(self):
        config = load_yaml(CORRIDORS_CONFIG_PATH)
        mapping = config["id_mapping"]
        assert mapping["id_prefix"] == "HCC"
        assert mapping["id_width"] == 3
        assert mapping["neighborhood_id_offset"] == 0
        assert mapping["downtown_id_offset"] == 31
        assert mapping["first_id"] == "HCC001"
        assert mapping["last_id"] == "HCC043"

    def test_config_extraction_statuses(self):
        config = load_yaml(CORRIDORS_CONFIG_PATH)
        statuses = config["extraction_statuses"]
        assert "verified_first_pass" in statuses
        assert "verified_second_pass" in statuses
        assert "unverified" in statuses

    def test_config_geometry_statuses(self):
        config = load_yaml(CORRIDORS_CONFIG_PATH)
        statuses = config["geometry_statuses"]
        assert "pending_construction" in statuses
        assert "constructed" in statuses
        assert "validated" in statuses
        assert "failed" in statuses

    def test_config_cross_reference_summary(self):
        config = load_yaml(CORRIDORS_CONFIG_PATH)
        xref = config["cross_reference_summary"]
        assert xref["total_corridors"] == 43
        assert xref["same_direction_matches"] == 20
        assert xref["reversed_direction_matches"] == 23
        assert xref["endpoint_disagreements"] == 0
        assert xref["multi_segment_chains"] == 16
        assert xref["chain_breaks"] == 0

    def test_config_corridor_required_fields(self):
        config = load_yaml(CORRIDORS_CONFIG_PATH)
        required = [
            "source_group",
            "source_corridor_number",
            "corridor_name",
            "street_name",
            "from_street",
            "to_street",
            "source_page",
            "cross_reference_page",
            "confidence",
            "extraction_status",
            "geometry_status",
        ]
        for corridor in config["corridors"]:
            for field in required:
                assert field in corridor, (
                    f"Missing {field} in "
                    f"{corridor.get('corridor_name', '?')}"
                )
                assert corridor[field] is not None, (
                    f"Null {field} in "
                    f"{corridor.get('corridor_name', '?')}"
                )

    def test_config_31_neighborhood_corridors(self):
        config = load_yaml(CORRIDORS_CONFIG_PATH)
        neighborhood = [
            c
            for c in config["corridors"]
            if c["source_group"] == "neighborhood"
        ]
        assert len(neighborhood) == 31

    def test_config_12_downtown_corridors(self):
        config = load_yaml(CORRIDORS_CONFIG_PATH)
        downtown = [
            c
            for c in config["corridors"]
            if c["source_group"] == "downtown"
        ]
        assert len(downtown) == 12

    def test_config_neighborhood_numbers_1_to_31(self):
        config = load_yaml(CORRIDORS_CONFIG_PATH)
        numbers = sorted(
            c["source_corridor_number"]
            for c in config["corridors"]
            if c["source_group"] == "neighborhood"
        )
        assert numbers == list(range(1, 32))

    def test_config_downtown_numbers_1_to_12(self):
        config = load_yaml(CORRIDORS_CONFIG_PATH)
        numbers = sorted(
            c["source_corridor_number"]
            for c in config["corridors"]
            if c["source_group"] == "downtown"
        )
        assert numbers == list(range(1, 13))

    def test_config_all_source_pages_are_9(self):
        config = load_yaml(CORRIDORS_CONFIG_PATH)
        for c in config["corridors"]:
            assert c["source_page"] == 9, (
                f"{c['corridor_name']} "
                f"source_page={c['source_page']}"
            )

    def test_config_all_geometry_pending(self):
        config = load_yaml(CORRIDORS_CONFIG_PATH)
        for c in config["corridors"]:
            assert (
                c["geometry_status"]
                == "pending_construction"
            )


# ==============================================================
# Alias tests
# ==============================================================


class TestAliases:
    """Tests for documented corridor name aliases."""

    def test_lake_shore_drive_alias_documented(self):
        config = load_yaml(CORRIDORS_CONFIG_PATH)
        aliases = config["aliases"]
        match = [
            a
            for a in aliases
            if a["canonical_name"] == "Lake Shore Drive"
            and a["matching_alias"] == "Lake Shore"
        ]
        assert len(match) == 1

    def test_western_ave_blvd_alias_documented(self):
        config = load_yaml(CORRIDORS_CONFIG_PATH)
        aliases = config["aliases"]
        match = [
            a
            for a in aliases
            if a["canonical_name"] == "Western Ave/Blvd"
            and a["matching_alias"] == "Western"
        ]
        assert len(match) == 1

    def test_alias_canonical_names_in_corridors(self):
        config = load_yaml(CORRIDORS_CONFIG_PATH)
        corridor_names = [
            c["corridor_name"]
            for c in config["corridors"]
        ]
        for alias in config["aliases"]:
            assert alias["canonical_name"] in corridor_names


# ==============================================================
# Register output tests
# ==============================================================


class TestRegisterOutput:
    """Tests for the built corridor register CSV."""

    def test_register_exists(self):
        assert REGISTER_PATH.is_file()

    def test_register_has_43_rows(self):
        rows = load_register()
        assert len(rows) == 43

    def test_register_columns(self):
        rows = load_register()
        expected = [
            "corridor_id",
            "corridor_name",
            "street_name",
            "from_street",
            "to_street",
            "source_group",
            "source_corridor_number",
            "source_name",
            "source_page",
            "cross_reference_page",
            "confidence",
            "extraction_status",
            "geometry_status",
        ]
        assert list(rows[0].keys()) == expected

    def test_register_corridor_id_range(self):
        rows = load_register()
        ids = [r["corridor_id"] for r in rows]
        expected = [f"HCC{i:03d}" for i in range(1, 44)]
        assert ids == expected

    def test_register_corridor_ids_unique(self):
        rows = load_register()
        ids = [r["corridor_id"] for r in rows]
        assert len(set(ids)) == 43

    def test_register_31_neighborhood(self):
        rows = load_register()
        n = [
            r
            for r in rows
            if r["source_group"] == "neighborhood"
        ]
        assert len(n) == 31

    def test_register_12_downtown(self):
        rows = load_register()
        d = [
            r
            for r in rows
            if r["source_group"] == "downtown"
        ]
        assert len(d) == 12

    def test_register_neighborhood_ids_hcc001_to_hcc031(
        self,
    ):
        rows = load_register()
        n_ids = [
            r["corridor_id"]
            for r in rows
            if r["source_group"] == "neighborhood"
        ]
        expected = [f"HCC{i:03d}" for i in range(1, 32)]
        assert n_ids == expected

    def test_register_downtown_ids_hcc032_to_hcc043(self):
        rows = load_register()
        d_ids = [
            r["corridor_id"]
            for r in rows
            if r["source_group"] == "downtown"
        ]
        expected = [f"HCC{i:03d}" for i in range(32, 44)]
        assert d_ids == expected

    def test_register_no_missing_values(self):
        rows = load_register()
        for row in rows:
            for key, value in row.items():
                assert value.strip(), (
                    f"Empty {key} in "
                    f"{row.get('corridor_id', '?')}"
                )

    def test_register_all_source_pages_are_9(self):
        rows = load_register()
        for r in rows:
            assert r["source_page"] == "9"

    def test_register_cross_reference_pages_valid(self):
        rows = load_register()
        for r in rows:
            page = int(r["cross_reference_page"])
            assert page in {27, 28, 29}

    def test_register_all_geometry_pending(self):
        rows = load_register()
        for r in rows:
            assert (
                r["geometry_status"]
                == "pending_construction"
            )

    def test_register_all_extraction_verified(self):
        rows = load_register()
        for r in rows:
            assert r["extraction_status"] in {
                "verified_first_pass",
                "verified_second_pass",
            }

    def test_register_source_number_uniqueness(self):
        rows = load_register()
        for group in ["neighborhood", "downtown"]:
            numbers = [
                int(r["source_corridor_number"])
                for r in rows
                if r["source_group"] == group
            ]
            assert len(set(numbers)) == len(numbers)


# ==============================================================
# ID mapping tests
# ==============================================================


class TestIDMapping:
    """Tests for project ID to source number mapping."""

    def test_hcc001_is_neighborhood_1(self):
        rows = load_register()
        r = [
            r
            for r in rows
            if r["corridor_id"] == "HCC001"
        ][0]
        assert r["source_group"] == "neighborhood"
        assert r["source_corridor_number"] == "1"
        assert r["corridor_name"] == "Devon"

    def test_hcc031_is_neighborhood_31(self):
        rows = load_register()
        r = [
            r
            for r in rows
            if r["corridor_id"] == "HCC031"
        ][0]
        assert r["source_group"] == "neighborhood"
        assert r["source_corridor_number"] == "31"
        assert r["corridor_name"] == "Stony Island"

    def test_hcc032_is_downtown_1(self):
        rows = load_register()
        r = [
            r
            for r in rows
            if r["corridor_id"] == "HCC032"
        ][0]
        assert r["source_group"] == "downtown"
        assert r["source_corridor_number"] == "1"
        assert r["corridor_name"] == "Michigan"

    def test_hcc043_is_downtown_12(self):
        rows = load_register()
        r = [
            r
            for r in rows
            if r["corridor_id"] == "HCC043"
        ][0]
        assert r["source_group"] == "downtown"
        assert r["source_corridor_number"] == "12"
        assert r["corridor_name"] == "Congress"

    def test_state_corridor_is_hcc037(self):
        rows = load_register()
        r = [
            r
            for r in rows
            if r["corridor_id"] == "HCC037"
        ][0]
        assert r["corridor_name"] == "State"
        assert r["from_street"] == "Chicago"
        assert r["to_street"] == "Harrison"
        assert r["source_group"] == "downtown"
        assert r["source_corridor_number"] == "6"


# ==============================================================
# Spatial config consistency tests
# ==============================================================


class TestSpatialConfigConsistency:
    """Tests for spatial.yml register-related settings."""

    def test_spatial_expected_corridor_count(self):
        spatial = load_yaml(SPATIAL_CONFIG_PATH)
        assert (
            spatial["dataset"]["expected_corridor_count"]
            == 43
        )

    def test_spatial_register_path(self):
        spatial = load_yaml(SPATIAL_CONFIG_PATH)
        assert (
            spatial["corridor_register"]["path"]
            == "data/interim/"
            "high_crash_corridor_register.csv"
        )

    def test_spatial_register_expected_count(self):
        spatial = load_yaml(SPATIAL_CONFIG_PATH)
        assert (
            spatial["corridor_register"][
                "expected_corridor_count"
            ]
            == 43
        )

    def test_spatial_id_format(self):
        spatial = load_yaml(SPATIAL_CONFIG_PATH)
        id_cfg = spatial["corridor_register"][
            "corridor_id"
        ]
        assert id_cfg["prefix"] == "HCC"
        assert id_cfg["width"] == 3
        assert id_cfg["first_id"] == "HCC001"
        assert id_cfg["last_id"] == "HCC043"

    def test_spatial_source_groups_defined(self):
        spatial = load_yaml(SPATIAL_CONFIG_PATH)
        groups = spatial["corridor_register"][
            "source_groups"
        ]
        assert groups["neighborhood"]["count"] == 31
        assert (
            groups["neighborhood"]["id_range"]
            == "HCC001-HCC031"
        )
        assert groups["downtown"]["count"] == 12
        assert (
            groups["downtown"]["id_range"]
            == "HCC032-HCC043"
        )


# ==============================================================
# Evidence and governance tests
# ==============================================================


class TestEvidenceAndGovernance:
    """Tests for validation evidence and governance rules."""

    def test_validation_report_exists(self):
        report_path = (
            ROOT
            / "docs"
            / "data_quality"
            / "corridor_register_validation.json"
        )
        assert report_path.is_file()

    def test_validation_report_passed(self):
        report_path = (
            ROOT
            / "docs"
            / "data_quality"
            / "corridor_register_validation.json"
        )
        with report_path.open(encoding="utf-8") as f:
            report = json.load(f)
        assert report["status"] == "PASS"

    def test_validation_report_has_run_id(self):
        report_path = (
            ROOT
            / "docs"
            / "data_quality"
            / "corridor_register_validation.json"
        )
        with report_path.open(encoding="utf-8") as f:
            report = json.load(f)
        assert "run_id" in report
        assert len(report["run_id"]) > 0

    def test_historical_report_directory_exists(self):
        hist_dir = (
            ROOT
            / "docs"
            / "data_quality"
            / "corridor_register_validation_runs"
        )
        assert hist_dir.is_dir()

    def test_historical_report_file_exists(self):
        hist_dir = (
            ROOT
            / "docs"
            / "data_quality"
            / "corridor_register_validation_runs"
        )
        reports = list(hist_dir.glob("*.json"))
        assert len(reports) >= 1

    def test_validation_governance_fields(self):
        report_path = (
            ROOT
            / "docs"
            / "data_quality"
            / "corridor_register_validation.json"
        )
        with report_path.open(encoding="utf-8") as f:
            report = json.load(f)
        gov = report["governance"]
        assert gov["canonical_source_page"] == 9
        assert gov["cross_reference_pages"] == [27, 28, 29]
        assert gov["raw_files_modified"] is False
        assert gov["geometry_constructed"] is False
        assert gov["crashes_assigned"] is False

    def test_decision_d015_exists(self):
        with DECISION_LOG_PATH.open(
            encoding="utf-8", newline=""
        ) as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        d015 = [
            r
            for r in rows
            if r.get("decision_id") == "D015"
        ]
        assert len(d015) == 1

    def test_contract_documents_canonical_authority(self):
        text = SPATIAL_CONTRACT_PATH.read_text(
            encoding="utf-8"
        )
        assert "page 9" in text.lower() or "Page 9" in text
        assert "canonical" in text.lower()
