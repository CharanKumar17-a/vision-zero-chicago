"""Build official corridor geometries from Chicago street centerlines.

This CLI script loads the validated 43-row corridor register and the latest
published spatial snapshot, constructs line geometry for each corridor according
to spatial.yml configuration, validates critical requirements, and writes atomic outputs:
- data/interim/high_crash_corridors.parquet (GeoParquet in EPSG:3435)
- data/interim/high_crash_corridors_review.geojson (GeoJSON in EPSG:4326)

If any critical failure occurs, publication is aborted and outputs are not updated.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Any

import geopandas as gpd
import yaml
from pyproj import Transformer
from shapely.ops import transform

ROOT = Path(__file__).resolve().parents[2]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.corridor_geometry import (  # noqa: E402
    INVALID_OBJECTIDS,
    construct_corridor_geometry,
    load_centerline_segments,
    load_spatial_config,
)

SPATIAL_CONFIG_PATH = ROOT / "config" / "spatial.yml"
MANIFEST_PATH = ROOT / "docs" / "data_quality" / "spatial_acquisition_manifest.json"
REGISTER_PATH = ROOT / "data" / "interim" / "high_crash_corridor_register.csv"

PARQUET_OUTPUT_PATH = ROOT / "data" / "interim" / "high_crash_corridors.parquet"
GEOJSON_OUTPUT_PATH = ROOT / "data" / "interim" / "high_crash_corridors_review.geojson"


def load_register(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def build_corridor_geometries() -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """Load spatial snapshot & register, construct all 43 corridor geometries."""
    config = load_spatial_config(SPATIAL_CONFIG_PATH)

    if not MANIFEST_PATH.is_file():
        raise FileNotFoundError(f"Spatial acquisition manifest not found: {MANIFEST_PATH}")
    if not REGISTER_PATH.is_file():
        raise FileNotFoundError(f"Corridor register not found: {REGISTER_PATH}")

    with MANIFEST_PATH.open(encoding="utf-8") as f:
        manifest = json.load(f)

    snapshot_dir = Path(manifest["snapshot_directory"])
    if not snapshot_dir.is_absolute():
        snapshot_dir = ROOT / snapshot_dir

    if not snapshot_dir.is_dir():
        raise FileNotFoundError(f"Snapshot directory not found: {snapshot_dir}")

    register_rows = load_register(REGISTER_PATH)
    if len(register_rows) != 43:
        raise ValueError(f"Expected 43 corridor register rows, found {len(register_rows)}")

    all_segments, by_name = load_centerline_segments(snapshot_dir, config)
    print(f"Loaded {len(all_segments)} valid centerline segments across {len(by_name)} street names.")

    records_3435: list[dict[str, Any]] = []
    records_4326: list[dict[str, Any]] = []

    transformer_to_4326 = Transformer.from_crs("EPSG:3435", "EPSG:4326", always_xy=True)

    for reg_row in register_rows:
        cid = reg_row["corridor_id"]
        res = construct_corridor_geometry(reg_row, by_name, config)

        # Check for forbidden objectids
        obj_ids = json.loads(res["source_objectids"])
        forbidden_used = set(obj_ids) & INVALID_OBJECTIDS
        if forbidden_used:
            raise ValueError(f"Corridor {cid} used forbidden objectids: {forbidden_used}")

        # EPSG:3435 record
        rec_3435 = {
            "corridor_id": res["corridor_id"],
            "corridor_name": res["corridor_name"],
            "street_name": res["street_name"],
            "from_street": res["from_street"],
            "to_street": res["to_street"],
            "source_group": res["source_group"],
            "geometry_status": res["geometry_status"],
            "resolution_method": res["resolution_method"],
            "source_street_names": res["source_street_names"],
            "source_objectids": res["source_objectids"],
            "source_segment_count": res["source_segment_count"],
            "length_feet": res["length_feet"],
            "corridor_length_feet": res["corridor_length_feet"],
            "geometry_linework_length_feet": res["geometry_linework_length_feet"],
            "route_component_lengths_feet": res["route_component_lengths_feet"],
            "boundary_from_distance_feet": res["boundary_from_distance_feet"],
            "boundary_to_distance_feet": res["boundary_to_distance_feet"],
            "is_multipart": res["is_multipart"],
            "geometry": res["geometry_3435"],
        }
        records_3435.append(rec_3435)

        # EPSG:4326 review record
        geom_4326 = transform(transformer_to_4326.transform, res["geometry_3435"])
        rec_4326 = dict(rec_3435)
        rec_4326["geometry"] = geom_4326
        records_4326.append(rec_4326)

    gdf_3435 = gpd.GeoDataFrame(records_3435, crs="EPSG:3435")
    gdf_4326 = gpd.GeoDataFrame(records_4326, crs="EPSG:4326")

    return gdf_3435, gdf_4326


def publish_outputs_atomically(gdf_3435: gpd.GeoDataFrame, gdf_4326: gpd.GeoDataFrame) -> None:
    """Publish GeoParquet and GeoJSON review files atomically."""
    PARQUET_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    GEOJSON_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    tmp_parquet = PARQUET_OUTPUT_PATH.with_suffix(".tmp.parquet")
    tmp_geojson = GEOJSON_OUTPUT_PATH.with_suffix(".tmp.geojson")

    gdf_3435.to_parquet(tmp_parquet)
    gdf_4326.to_file(tmp_geojson, driver="GeoJSON")

    tmp_parquet.replace(PARQUET_OUTPUT_PATH)
    tmp_geojson.replace(GEOJSON_OUTPUT_PATH)


def main() -> int:
    print("=" * 70)
    print("Building High-Crash Corridor Geometries")
    print("=" * 70)

    try:
        gdf_3435, gdf_4326 = build_corridor_geometries()

        if len(gdf_3435) != 43:
            raise ValueError(f"Expected 43 constructed geometries, got {len(gdf_3435)}")

        publish_outputs_atomically(gdf_3435, gdf_4326)

        print(f"Successfully constructed and published {len(gdf_3435)} corridor geometries.")
        print(f"GeoParquet (EPSG:3435): {PARQUET_OUTPUT_PATH}")
        print(f"GeoJSON Review (EPSG:4326): {GEOJSON_OUTPUT_PATH}")
        print("Status: PASS")
        print("=" * 70)
        return 0

    except Exception as exc:
        print(f"CRITICAL FAILURE during geometry construction: {exc}")
        print("Output publication ABORTED.")
        print("=" * 70)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
