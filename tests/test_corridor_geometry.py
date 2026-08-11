"""Tests for corridor geometry construction, validation, side-effect isolation, and governance contracts."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import geopandas as gpd
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.build_corridor_geometry import build_corridor_geometries  # noqa: E402
from src.data.corridor_geometry import (  # noqa: E402
    INVALID_OBJECTIDS,
    load_centerline_segments,
    load_spatial_config,
    normalize_street_name,
)
from src.data.validate_corridor_geometry import validate_corridor_geometries  # noqa: E402

SPATIAL_CONFIG_PATH = ROOT / "config" / "spatial.yml"
REGISTER_PATH = ROOT / "data" / "interim" / "high_crash_corridor_register.csv"

PARQUET_OUTPUT_PATH = ROOT / "data" / "interim" / "high_crash_corridors.parquet"
GEOJSON_OUTPUT_PATH = ROOT / "data" / "interim" / "high_crash_corridors_review.geojson"
MANIFEST_PATH = ROOT / "docs" / "data_quality" / "spatial_acquisition_manifest.json"
ISSUE_REGISTER_PATH = ROOT / "docs" / "data_quality" / "data_quality_issue_register.csv"


def test_normalize_street_name():
    config = load_spatial_config(SPATIAL_CONFIG_PATH)
    assert normalize_street_name("  king  ", get_aliases(config)) == "DR MARTIN LUTHER KING JR"
    assert normalize_street_name("Lake Shore Drive", get_aliases(config)) == "LAKE SHORE"
    assert normalize_street_name("LaSalle", get_aliases(config)) == "LA SALLE"
    assert normalize_street_name("Wacker Dr Lower", get_aliases(config)) == "WACKER DR LOWER"
    assert normalize_street_name("79th St", get_aliases(config)) == "79TH ST"


def get_aliases(config: dict) -> dict[str, str]:
    aliases = config.get("corridor_geometry", {}).get("street_name_aliases", {})
    return {str(k).upper(): str(v).upper() for k, v in aliases.items()}


def test_spatial_snapshot_loader():
    with MANIFEST_PATH.open(encoding="utf-8") as f:
        manifest = json.load(f)

    snapshot_dir = ROOT / manifest["snapshot_directory"]
    all_segs, by_name = load_centerline_segments(snapshot_dir)

    assert len(all_segs) == 56336
    obj_ids = {s["objectid"] for s in all_segs}
    assert "69442" not in obj_ids
    assert "69766" not in obj_ids


def test_build_all_43_corridor_geometries():
    gdf_3435, gdf_4326 = build_corridor_geometries()

    assert len(gdf_3435) == 43
    assert len(gdf_4326) == 43

    assert str(gdf_3435.crs) == "EPSG:3435"
    assert str(gdf_4326.crs) == "EPSG:4326"

    required_cols = [
        "corridor_id",
        "corridor_name",
        "street_name",
        "from_street",
        "to_street",
        "source_group",
        "geometry_status",
        "resolution_method",
        "source_street_names",
        "source_objectids",
        "source_segment_count",
        "length_feet",
        "corridor_length_feet",
        "geometry_linework_length_feet",
        "route_component_lengths_feet",
        "boundary_from_distance_feet",
        "boundary_to_distance_feet",
        "is_multipart",
        "geometry",
    ]
    for col in required_cols:
        assert col in gdf_3435.columns

    for geom in gdf_3435["geometry"]:
        assert geom is not None
        assert not geom.is_empty
        assert geom.is_valid


def test_geometry_types_and_multipart_policy():
    gdf_3435, _ = build_corridor_geometries()

    geom_types = list(gdf_3435["geometry"].geom_type)
    assert geom_types.count("LineString") == 42
    assert geom_types.count("MultiLineString") == 1

    multipart_ids = list(gdf_3435[gdf_3435["is_multipart"]]["corridor_id"])
    assert multipart_ids == ["HCC019"]

    hcc019_geom = gdf_3435[gdf_3435["corridor_id"] == "HCC019"].iloc[0]["geometry"]
    assert hcc019_geom.geom_type == "MultiLineString"
    assert len(hcc019_geom.geoms) == 2

    # HCC038 and HCC039 are LineString and not multipart
    hcc038 = gdf_3435[gdf_3435["corridor_id"] == "HCC038"].iloc[0]
    assert hcc038["geometry"].geom_type == "LineString"
    assert bool(hcc038["is_multipart"]) is False

    hcc039 = gdf_3435[gdf_3435["corridor_id"] == "HCC039"].iloc[0]
    assert hcc039["geometry"].geom_type == "LineString"
    assert bool(hcc039["is_multipart"]) is False


def test_hcc019_lake_shore_drive_routing_and_length_semantics():
    gdf_3435, _ = build_corridor_geometries()
    hcc019 = gdf_3435[gdf_3435["corridor_id"] == "HCC019"].iloc[0]

    assert hcc019["resolution_method"] == "verified_two_carriageway_proximity"
    assert bool(hcc019["is_multipart"]) is True
    assert hcc019["boundary_from_distance_feet"] == 162.973
    assert hcc019["boundary_to_distance_feet"] == 0.0

    comp_lengths = json.loads(hcc019["route_component_lengths_feet"])
    assert "NB" in comp_lengths
    assert "SB" in comp_lengths

    nb_len = comp_lengths["NB"]
    sb_len = comp_lengths["SB"]

    assert 13300 < nb_len < 13400
    assert 13150 < sb_len < 13250

    expected_corridor_len = round((nb_len + sb_len) / 2.0, 3)
    expected_linework_len = round(nb_len + sb_len, 3)

    assert abs(float(hcc019["corridor_length_feet"]) - expected_corridor_len) < 0.01
    assert abs(float(hcc019["geometry_linework_length_feet"]) - expected_linework_len) < 0.01
    assert float(hcc019["length_feet"]) == float(hcc019["corridor_length_feet"])


def test_hcc038_fairbanks_routing_metrics():
    gdf_3435, _ = build_corridor_geometries()
    hcc038 = gdf_3435[gdf_3435["corridor_id"] == "HCC038"].iloc[0]

    assert hcc038["resolution_method"] == "verified_source_continuation"
    names = json.loads(hcc038["source_street_names"])
    assert sorted(names) == ["COLUMBUS", "FAIRBANKS"]

    assert 1900 < float(hcc038["corridor_length_feet"]) < 2100
    assert float(hcc038["corridor_length_feet"]) == float(hcc038["geometry_linework_length_feet"])
    assert hcc038["source_segment_count"] == 6


def test_hcc039_wacker_routing_metrics():
    gdf_3435, _ = build_corridor_geometries()
    hcc039 = gdf_3435[gdf_3435["corridor_id"] == "HCC039"].iloc[0]

    assert hcc039["resolution_method"] == "verified_multilevel_source_family"
    names = json.loads(hcc039["source_street_names"])
    assert "WACKER" in names
    assert "WACKER LOWER" in names

    assert 9200 < float(hcc039["corridor_length_feet"]) < 9500
    assert float(hcc039["corridor_length_feet"]) == float(hcc039["geometry_linework_length_feet"])
    assert hcc039["source_segment_count"] == 25


def test_routing_policies_loaded_from_spatial_yml():
    config = load_spatial_config(SPATIAL_CONFIG_PATH)
    geom_cfg = config["corridor_geometry"]

    aliases = geom_cfg["street_name_aliases"]
    assert aliases["KING"] == "DR MARTIN LUTHER KING JR"
    assert aliases["LAKE SHORE DRIVE"] == "LAKE SHORE"
    assert aliases["LASALLE"] == "LA SALLE"

    prox = geom_cfg["boundary_proximity"]
    assert prox["maximum_feet"] == 200
    assert prox["approved_corridors"] == ["HCC019"]
    assert prox["is_crash_assignment_threshold"] is False

    policies = geom_cfg["exception_policies"]
    assert policies["HCC019"]["method"] == "verified_two_carriageway_proximity"
    assert policies["HCC038"]["method"] == "verified_source_continuation"
    assert policies["HCC039"]["method"] == "verified_multilevel_source_family"


def test_governance_assignment_status_and_null_threshold():
    config = load_spatial_config(SPATIAL_CONFIG_PATH)
    gov = config["governance"]
    assert gov["current_geometry_status"] == "validated_with_limitations"
    assert gov["current_assignment_status"] == "ready_for_threshold_sensitivity_analysis"

    assignment = config["crash_assignment"]
    assert assignment["threshold_status"] == "approved_for_modeling"
    assert assignment["selected_distance_threshold_feet"] == 100


def test_clean_clone_output_rebuilding():
    if PARQUET_OUTPUT_PATH.is_file():
        PARQUET_OUTPUT_PATH.unlink()
    if GEOJSON_OUTPUT_PATH.is_file():
        GEOJSON_OUTPUT_PATH.unlink()

    assert not PARQUET_OUTPUT_PATH.is_file()
    assert not GEOJSON_OUTPUT_PATH.is_file()

    cmd = [sys.executable, str(ROOT / "src" / "data" / "build_corridor_geometry.py")]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0

    assert PARQUET_OUTPUT_PATH.is_file()
    assert GEOJSON_OUTPUT_PATH.is_file()

    gdf = gpd.read_parquet(PARQUET_OUTPUT_PATH)
    assert len(gdf) == 43


def test_validator_execution_isolated(tmp_path):
    """Verify validator execution using tmp_path to prevent modifying tracked files."""
    latest_report = tmp_path / "corridor_geometry_validation.json"
    hist_dir = tmp_path / "corridor_geometry_runs"
    issue_reg = tmp_path / "data_quality_issue_register.csv"
    issue_reg.write_text(ISSUE_REGISTER_PATH.read_text(encoding="utf-8"), encoding="utf-8")

    report = validate_corridor_geometries(
        latest_report_path=latest_report,
        historical_report_dir=hist_dir,
        issue_register_path=issue_reg,
    )

    assert report["status"] == "PASS_WITH_WARNINGS"
    assert report["downstream_readiness"] == "READY_WITH_LIMITATIONS"
    assert report["summary"]["total_corridors"] == 43
    assert report["summary"]["critical_failures"] == 0
    assert report["summary"]["warning_count"] == 4

    assert latest_report.is_file()
    assert len(list(hist_dir.glob("*.json"))) == 1
