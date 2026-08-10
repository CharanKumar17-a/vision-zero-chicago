"""Core spatial geometry construction and helper logic for Vision Zero Chicago.

Provides configuration-driven street normalization, spatial snapshot loading,
deterministic shortest-path routing, line_merge geometry assembly, and length semantics.
"""

from __future__ import annotations

import heapq
import json
import re
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

import yaml
from pyproj import Transformer
from shapely import line_merge
from shapely.geometry import LineString, MultiLineString, shape
from shapely.ops import transform, unary_union

ROOT = Path(__file__).resolve().parents[2]
SPATIAL_CONFIG_PATH = ROOT / "config" / "spatial.yml"

INVALID_OBJECTIDS = {"69442", "69766"}


def load_spatial_config(path: Path = SPATIAL_CONFIG_PATH) -> dict[str, Any]:
    """Load spatial configuration from spatial.yml."""
    with path.open(encoding="utf-8") as f:
        val = yaml.safe_load(f)
    if not isinstance(val, dict):
        raise ValueError(f"Expected YAML dict mapping: {path}")
    return val


def get_street_name_aliases(config: dict[str, Any] | None = None) -> dict[str, str]:
    """Extract street name aliases from spatial configuration."""
    cfg = config or load_spatial_config()
    aliases = cfg.get("corridor_geometry", {}).get("street_name_aliases", {})
    return {str(k).upper(): str(v).upper() for k, v in aliases.items()}


def normalize_street_name(value: str | None, aliases: dict[str, str] | None = None) -> str:
    """Normalize a street name for consistent matching and lookup."""
    val = str(value or "").upper().strip()
    val = re.sub(r"[^A-Z0-9]+", " ", val)
    val = " ".join(val.split())
    alias_dict = aliases if aliases is not None else get_street_name_aliases()
    return alias_dict.get(val, val)


def load_centerline_segments(
    snapshot_dir: Path,
    config: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    """Load all valid street centerline features from GeoJSON snapshot parts.

    Excludes invalid geometry objectids 69442 and 69766.
    Reprojects geometry from EPSG:4326 to EPSG:3435 (US Survey feet).

    Returns:
        tuple of (all_segments_list, segments_by_normalized_street_name_dict)
    """
    aliases = get_street_name_aliases(config)
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:3435", always_xy=True)
    all_segments: list[dict[str, Any]] = []
    by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)

    pages = sorted(snapshot_dir.rglob("part-*.geojson"))
    for page_path in pages:
        with page_path.open(encoding="utf-8") as f:
            data = json.load(f)
        for feature in data.get("features", []):
            props = feature.get("properties") or {}
            geom_data = feature.get("geometry")

            objectid = str(props.get("objectid"))
            if objectid in INVALID_OBJECTIDS:
                continue

            if not isinstance(geom_data, dict) or not geom_data.get("coordinates"):
                continue

            raw_shape = shape(geom_data)
            if raw_shape.is_empty:
                continue

            geom_3435 = transform(transformer.transform, raw_shape)
            street_nam_raw = str(props.get("street_nam") or "")
            norm_name = normalize_street_name(street_nam_raw, aliases)

            segment = {
                "objectid": objectid,
                "trans_id": str(props.get("trans_id") or ""),
                "fnode": str(props.get("fnode_id") or ""),
                "tnode": str(props.get("tnode_id") or ""),
                "street_nam_raw": street_nam_raw,
                "street_nam_norm": norm_name,
                "pre_dir": normalize_street_name(props.get("pre_dir"), aliases),
                "street_typ": normalize_street_name(props.get("street_typ"), aliases),
                "suf_dir": normalize_street_name(props.get("suf_dir"), aliases),
                "f_cross": normalize_street_name(props.get("f_cross"), aliases),
                "t_cross": normalize_street_name(props.get("t_cross"), aliases),
                "geometry_3435": geom_3435,
                "geometry_4326": raw_shape,
                "length_feet": float(geom_3435.length),
            }

            all_segments.append(segment)
            by_name[norm_name].append(segment)

    return all_segments, by_name


def find_shortest_route(
    candidate_segments: list[dict[str, Any]],
    start_nodes: set[str],
    target_nodes: set[str],
) -> dict[str, Any] | None:
    """Find deterministic length-weighted shortest path between start_nodes and target_nodes.

    Tie-breaking uses segment objectid to guarantee deterministic behavior.
    """
    adjacency: dict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    for seg in candidate_segments:
        adjacency[seg["fnode"]].append((seg["tnode"], seg))
        adjacency[seg["tnode"]].append((seg["fnode"], seg))

    distances: dict[str, float] = {}
    parents: dict[str, tuple[str, dict[str, Any]]] = {}
    heap: list[tuple[float, int, str]] = []

    counter = 0
    for node in start_nodes:
        distances[node] = 0.0
        heapq.heappush(heap, (0.0, counter, node))
        counter += 1

    reached_target: str | None = None

    while heap:
        dist, _, node = heapq.heappop(heap)

        if dist > distances.get(node, float("inf")):
            continue

        if node in target_nodes:
            reached_target = node
            break

        neighbors = sorted(adjacency[node], key=lambda item: item[1]["objectid"])
        for neighbor_node, seg in neighbors:
            cand_dist = dist + seg["length_feet"]
            if cand_dist < distances.get(neighbor_node, float("inf")):
                distances[neighbor_node] = cand_dist
                parents[neighbor_node] = (node, seg)
                counter += 1
                heapq.heappush(heap, (cand_dist, counter, neighbor_node))

    if reached_target is None:
        return None

    route_segments: list[dict[str, Any]] = []
    curr = reached_target
    while curr not in start_nodes:
        prev, seg = parents[curr]
        route_segments.append(seg)
        curr = prev

    route_segments.reverse()

    return {
        "length_feet": distances[reached_target],
        "segments": route_segments,
        "start_node": curr,
        "target_node": reached_target,
    }


def merge_route_segments(
    route_segments: list[dict[str, Any]],
    start_node: str | None = None,
) -> LineString:
    """Merge connected route segment geometries into a single LineString.

    Tries line_merge on unary_union first. If line_merge produces a MultiLineString
    due to minor coordinate precision discrepancies along the contiguous path,
    stitches the ordered path coordinates from start_node to target_node to form
    a single LineString.
    """
    lines = []
    for s in route_segments:
        g = s["geometry_3435"]
        if g.geom_type == "LineString":
            lines.append(g)
        elif g.geom_type == "MultiLineString":
            for sub in g.geoms:
                lines.append(sub)

    unioned = unary_union(lines)
    merged = line_merge(unioned)

    if merged.geom_type == "LineString":
        return merged
    elif merged.geom_type == "MultiLineString" and len(merged.geoms) == 1:
        return merged.geoms[0]

    # Stitch ordered route coordinates along Dijkstra path
    path_coords: list[tuple[float, float]] = []
    curr = start_node or route_segments[0]["fnode"]

    for s in route_segments:
        g = s["geometry_3435"]
        g_line = max(g.geoms, key=lambda l: l.length) if g.geom_type == "MultiLineString" else g
        coords = list(g_line.coords)
        if s["fnode"] == curr:
            coords_to_add = coords
            curr = s["tnode"]
        else:
            coords_to_add = coords[::-1]
            curr = s["fnode"]

        if not path_coords:
            path_coords.extend(coords_to_add)
        else:
            path_coords.extend(coords_to_add[1:])

    res_line = LineString(path_coords)
    if res_line.is_empty or not res_line.is_valid:
        raise ValueError("Stitched route geometry is invalid or empty")
    return res_line


def build_single_carriageway_corridor(
    main_name: str,
    from_name: str,
    to_name: str,
    candidate_segments: list[dict[str, Any]],
    by_name: dict[str, list[dict[str, Any]]],
    max_proximity_feet: float = 200.0,
) -> dict[str, Any]:
    """Construct standard single-carriageway corridor geometry."""
    from_segments = by_name.get(from_name, [])
    to_segments = by_name.get(to_name, [])

    if not from_segments:
        raise ValueError(f"No centerline segments found for FROM street: {from_name}")
    if not to_segments:
        raise ValueError(f"No centerline segments found for TO street: {to_name}")
    if not candidate_segments:
        raise ValueError(f"No candidate segments found for main street: {main_name}")

    main_nodes = {node for seg in candidate_segments for node in [seg["fnode"], seg["tnode"]]}
    from_nodes = {node for seg in from_segments for node in [seg["fnode"], seg["tnode"]]}
    to_nodes = {node for seg in to_segments for node in [seg["fnode"], seg["tnode"]]}

    shared_from_nodes = main_nodes & from_nodes
    shared_to_nodes = main_nodes & to_nodes

    boundary_from_dist = 0.0
    boundary_to_dist = 0.0
    from_resolved_by_proximity = False
    to_resolved_by_proximity = False

    start_nodes = shared_from_nodes
    if not start_nodes:
        from_geom = unary_union([s["geometry_3435"] for s in from_segments])
        nearest_segs = sorted(
            candidate_segments,
            key=lambda s: s["geometry_3435"].distance(from_geom),
        )
        min_dist = nearest_segs[0]["geometry_3435"].distance(from_geom)
        if min_dist > max_proximity_feet:
            raise ValueError(
                f"FROM boundary '{from_name}' distance {min_dist:.1f} ft exceeds max {max_proximity_feet} ft"
            )
        boundary_from_dist = min_dist
        from_resolved_by_proximity = True
        start_nodes = {
            node
            for seg in nearest_segs[:5]
            if seg["geometry_3435"].distance(from_geom) <= min_dist + 50.0
            for node in [seg["fnode"], seg["tnode"]]
        }

    target_nodes = shared_to_nodes
    if not target_nodes:
        to_geom = unary_union([s["geometry_3435"] for s in to_segments])
        nearest_segs = sorted(
            candidate_segments,
            key=lambda s: s["geometry_3435"].distance(to_geom),
        )
        min_dist = nearest_segs[0]["geometry_3435"].distance(to_geom)
        if min_dist > max_proximity_feet:
            raise ValueError(
                f"TO boundary '{to_name}' distance {min_dist:.1f} ft exceeds max {max_proximity_feet} ft"
            )
        boundary_to_dist = min_dist
        to_resolved_by_proximity = True
        target_nodes = {
            node
            for seg in nearest_segs[:5]
            if seg["geometry_3435"].distance(to_geom) <= min_dist + 50.0
            for node in [seg["fnode"], seg["tnode"]]
        }

    route_res = find_shortest_route(candidate_segments, start_nodes, target_nodes)
    if route_res is None:
        raise ValueError(
            f"No connected path found on '{main_name}' between '{from_name}' and '{to_name}'"
        )

    route_segs = route_res["segments"]
    merged_geom = merge_route_segments(route_segs, start_node=route_res["start_node"])
    route_len = float(merged_geom.length)

    return {
        "geometry": merged_geom,
        "segments": route_segs,
        "corridor_length_feet": round(route_len, 3),
        "geometry_linework_length_feet": round(route_len, 3),
        "route_component_lengths": {"main": round(route_len, 3)},
        "boundary_from_distance_feet": round(boundary_from_dist, 3),
        "boundary_to_distance_feet": round(boundary_to_dist, 3),
        "from_resolved_by_proximity": from_resolved_by_proximity,
        "to_resolved_by_proximity": to_resolved_by_proximity,
        "is_multipart": False,
    }


def build_lake_shore_drive_corridor(
    by_name: dict[str, list[dict[str, Any]]],
    exception_cfg: dict[str, Any],
) -> dict[str, Any]:
    """Construct Policy B exception geometry for HCC019 (Lake Shore Drive).

    Builds a two-carriageway MultiLineString with exactly 2 merged LineString parts.
    """
    source_name = exception_cfg.get("source_names", ["LAKE SHORE"])[0]
    lsd_segments = by_name.get(source_name, [])
    div_segments = by_name.get("DIVISION", [])
    roo_segments = by_name.get("ROOSEVELT", [])

    div_geom = unary_union([s["geometry_3435"] for s in div_segments])
    roo_geom = unary_union([s["geometry_3435"] for s in roo_segments])

    # NB Carriageway
    nb_segs = [s for s in lsd_segments if s["suf_dir"] == "NB"]
    nb_res = build_carriageway_route(nb_segs, div_geom, roo_geom)

    # SB Carriageway
    sb_segs = [s for s in lsd_segments if s["suf_dir"] == "SB"]
    sb_res = build_carriageway_route(sb_segs, div_geom, roo_geom)

    nb_line = merge_route_segments(nb_res["segments"], start_node=nb_res["start_node"])
    sb_line = merge_route_segments(sb_res["segments"], start_node=sb_res["start_node"])

    if nb_line.geom_type != "LineString":
        raise ValueError(f"HCC019 NB carriageway line_merge failed to produce a single LineString (got {nb_line.geom_type})")
    if sb_line.geom_type != "LineString":
        raise ValueError(f"HCC019 SB carriageway line_merge failed to produce a single LineString (got {sb_line.geom_type})")

    multi_geom = MultiLineString([nb_line, sb_line])
    expected_parts = exception_cfg.get("expected_parts", 2)
    if len(multi_geom.geoms) != expected_parts:
        raise ValueError(
            f"HCC019 MultiLineString expected exactly {expected_parts} parts, got {len(multi_geom.geoms)}"
        )

    combined_segs = nb_res["segments"] + sb_res["segments"]
    nb_len = float(nb_line.length)
    sb_len = float(sb_line.length)

    corridor_len = (nb_len + sb_len) / 2.0
    linework_len = nb_len + sb_len

    return {
        "geometry": multi_geom,
        "segments": combined_segs,
        "corridor_length_feet": round(corridor_len, 3),
        "geometry_linework_length_feet": round(linework_len, 3),
        "route_component_lengths": {
            "NB": round(nb_len, 3),
            "SB": round(sb_len, 3),
        },
        "boundary_from_distance_feet": round(nb_res["div_distance"], 3),
        "boundary_to_distance_feet": 0.0,
        "from_resolved_by_proximity": True,
        "to_resolved_by_proximity": False,
        "is_multipart": True,
    }


def build_carriageway_route(
    carriageway_segments: list[dict[str, Any]],
    div_geom: Any,
    roo_geom: Any,
) -> dict[str, Any]:
    """Helper to route one Lake Shore Drive carriageway (NB or SB)."""
    adjacency: dict[str, set[str]] = defaultdict(set)
    for seg in carriageway_segments:
        adjacency[seg["fnode"]].add(seg["tnode"])
        adjacency[seg["tnode"]].add(seg["fnode"])

    visited: set[str] = set()
    components: list[list[dict[str, Any]]] = []

    for start in adjacency:
        if start in visited:
            continue
        queue = deque([start])
        nodes: set[str] = set()
        while queue:
            node = queue.popleft()
            if node in visited:
                continue
            visited.add(node)
            nodes.add(node)
            queue.extend(adjacency[node] - visited)

        comp_segs = [s for s in carriageway_segments if s["fnode"] in nodes and s["tnode"] in nodes]
        components.append(comp_segs)

    components.sort(
        key=lambda comp: (
            unary_union([s["geometry_3435"] for s in comp]).distance(div_geom)
            + unary_union([s["geometry_3435"] for s in comp]).distance(roo_geom)
        )
    )
    best_component = components[0]

    div_candidates = sorted(
        best_component,
        key=lambda s: s["geometry_3435"].distance(div_geom),
    )[:5]

    roo_candidates = sorted(
        best_component,
        key=lambda s: s["geometry_3435"].distance(roo_geom),
    )[:5]

    div_dist = div_candidates[0]["geometry_3435"].distance(div_geom)

    start_nodes = {node for seg in div_candidates for node in [seg["fnode"], seg["tnode"]]}
    target_nodes = {node for seg in roo_candidates for node in [seg["fnode"], seg["tnode"]]}

    route_res = find_shortest_route(best_component, start_nodes, target_nodes)
    if route_res is None:
        raise ValueError("Failed to find carriageway route for Lake Shore Drive")

    return {
        "segments": route_res["segments"],
        "length_feet": route_res["length_feet"],
        "div_distance": div_dist,
        "start_node": route_res["start_node"],
    }


def construct_corridor_geometry(
    corridor_record: dict[str, Any],
    by_name: dict[str, list[dict[str, Any]]],
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Construct geometry for one corridor record according to spatial.yml configuration."""
    cfg = config or load_spatial_config()
    geom_cfg = cfg.get("corridor_geometry", {})
    aliases = get_street_name_aliases(cfg)

    max_proximity_feet = float(geom_cfg.get("boundary_proximity", {}).get("maximum_feet", 200.0))
    exception_policies = geom_cfg.get("exception_policies", {})

    cid = corridor_record["corridor_id"]
    cname = corridor_record["corridor_name"]
    sname = corridor_record["street_name"]
    fname = corridor_record["from_street"]
    tname = corridor_record["to_street"]

    norm_sname = normalize_street_name(sname or cname, aliases)
    norm_fname = normalize_street_name(fname, aliases)
    norm_tname = normalize_street_name(tname, aliases)

    if cid in exception_policies:
        pol_cfg = exception_policies[cid]
        method = pol_cfg["method"]

        if method == "verified_two_carriageway_proximity":
            res = build_lake_shore_drive_corridor(by_name, pol_cfg)
            resolution_method = method
            source_street_names = pol_cfg.get("source_names", [norm_sname])

        elif method == "verified_source_continuation":
            allowed_names = [
                normalize_street_name(name, aliases)
                for name in pol_cfg.get("allowed_source_names", [])
            ]
            candidate_segs = [s for name in allowed_names for s in by_name.get(name, [])]
            res = build_single_carriageway_corridor(
                main_name=norm_sname,
                from_name=norm_fname,
                to_name=norm_tname,
                candidate_segments=candidate_segs,
                by_name=by_name,
                max_proximity_feet=max_proximity_feet,
            )
            resolution_method = method
            source_street_names = sorted(list({s["street_nam_norm"] for s in res["segments"]}))

        elif method == "verified_multilevel_source_family":
            allowed_names = [
                normalize_street_name(name, aliases)
                for name in pol_cfg.get("allowed_source_names", [])
            ]
            candidate_segs = [s for name in allowed_names for s in by_name.get(name, [])]
            res = build_single_carriageway_corridor(
                main_name=norm_sname,
                from_name=norm_fname,
                to_name=norm_tname,
                candidate_segments=candidate_segs,
                by_name=by_name,
                max_proximity_feet=max_proximity_feet,
            )
            resolution_method = method
            source_street_names = sorted(list({s["street_nam_norm"] for s in res["segments"]}))
        else:
            raise ValueError(f"Unknown exception policy method: {method}")

    else:
        candidate_segs = by_name.get(norm_sname, [])
        res = build_single_carriageway_corridor(
            main_name=norm_sname,
            from_name=norm_fname,
            to_name=norm_tname,
            candidate_segments=candidate_segs,
            by_name=by_name,
            max_proximity_feet=max_proximity_feet,
        )
        resolution_method = "standard_shortest_path"
        source_street_names = [norm_sname]

    source_objectids = sorted([s["objectid"] for s in res["segments"]], key=lambda x: int(x))

    output_record = {
        "corridor_id": cid,
        "corridor_name": cname,
        "street_name": sname,
        "from_street": fname,
        "to_street": tname,
        "source_group": corridor_record["source_group"],
        "geometry_status": "validated",
        "resolution_method": resolution_method,
        "source_street_names": json.dumps(source_street_names),
        "source_objectids": json.dumps(source_objectids),
        "source_segment_count": len(res["segments"]),
        "length_feet": res["corridor_length_feet"],
        "corridor_length_feet": res["corridor_length_feet"],
        "geometry_linework_length_feet": res["geometry_linework_length_feet"],
        "route_component_lengths_feet": json.dumps(res["route_component_lengths"]),
        "boundary_from_distance_feet": res["boundary_from_distance_feet"],
        "boundary_to_distance_feet": res["boundary_to_distance_feet"],
        "is_multipart": res["is_multipart"],
        "from_resolved_by_proximity": res.get("from_resolved_by_proximity", False),
        "to_resolved_by_proximity": res.get("to_resolved_by_proximity", False),
        "geometry_3435": res["geometry"],
    }

    return output_record
