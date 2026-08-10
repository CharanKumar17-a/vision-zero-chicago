"""Download immutable spatial-source snapshots with validation evidence.

The script downloads two official spatial inputs:

1. The Chicago High Crash Corridors Framework Plan PDF as one file.
2. Chicago Street Center Lines from the backing Socrata dataset as
   ordered, paginated GeoJSON files.

Every response is validated before the source receives PASS status. Both
successful and failed runs produce manifests so data-quality failures remain
auditable. Existing snapshots are never overwritten.
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
import yaml
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


ROOT = Path(__file__).resolve().parents[2]
SPATIAL_CONFIG_PATH = ROOT / "config" / "spatial.yml"
SOURCES_CONFIG_PATH = ROOT / "config" / "sources.yml"
SEPARATOR = "=" * 75
SUBSEPARATOR = "-" * 75


class SpatialAcquisitionError(RuntimeError):
    """Raised when a spatial source cannot pass acquisition validation."""


def load_yaml(path: Path) -> dict[str, Any]:
    """Load a YAML document and require a mapping at its root."""

    with path.open(encoding="utf-8") as file:
        data = yaml.safe_load(file)

    if not isinstance(data, dict):
        raise SpatialAcquisitionError(
            f"Expected a YAML mapping in {path}"
        )

    return data


def utc_now() -> datetime:
    """Return the current timezone-aware UTC timestamp."""

    return datetime.now(timezone.utc)


def timestamp_id(value: datetime | None = None) -> str:
    """Return a compact UTC run identifier."""

    current = value or utc_now()
    return current.strftime("%Y%m%dT%H%M%SZ")


def iso_utc(value: datetime | None = None) -> str:
    """Return an ISO-8601 UTC timestamp."""

    current = value or utc_now()
    return current.isoformat(timespec="seconds")


def sha256_bytes(content: bytes) -> str:
    """Calculate a SHA-256 digest for response bytes."""

    return hashlib.sha256(content).hexdigest()


def atomic_write_bytes(path: Path, content: bytes) -> None:
    """Write bytes through a temporary file and atomically publish them."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f"{path.name}.tmp")
    temporary_path.write_bytes(content)
    temporary_path.replace(path)


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write formatted JSON atomically."""

    content = json.dumps(
        payload,
        indent=2,
        ensure_ascii=False,
    ).encode("utf-8")
    atomic_write_bytes(path, content)


def media_type(value: str | None) -> str:
    """Return a normalized media type without charset parameters."""

    if not value:
        return ""

    return value.split(";", maxsplit=1)[0].strip().lower()


def require_content_type(
    response: requests.Response,
    expected_content_types: list[str],
) -> str:
    """Require the response media type to match the configured allowlist."""

    observed = media_type(response.headers.get("Content-Type"))
    expected = {
        media_type(content_type)
        for content_type in expected_content_types
    }

    if observed not in expected:
        raise SpatialAcquisitionError(
            "Unexpected content type: "
            f"observed={observed!r}, expected={sorted(expected)!r}"
        )

    return observed


def validate_https_url(url: str, field_name: str) -> None:
    """Reject malformed, Markdown-formatted, or non-HTTPS source URLs."""

    if not isinstance(url, str) or not url.startswith("https://"):
        raise SpatialAcquisitionError(
            f"{field_name} must be a raw HTTPS URL"
        )

    forbidden_tokens = ("[", "]", "](", "<", ">")
    if any(token in url for token in forbidden_tokens):
        raise SpatialAcquisitionError(
            f"{field_name} contains Markdown or invalid URL characters"
        )


def build_session(acquisition_config: dict[str, Any]) -> requests.Session:
    """Create a retry-enabled HTTP session."""

    retries = int(acquisition_config.get("maximum_retries", 5))
    backoff = float(acquisition_config.get("retry_backoff_seconds", 2))

    retry_policy = Retry(
        total=retries,
        connect=retries,
        read=retries,
        status=retries,
        backoff_factor=backoff,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
        raise_on_status=False,
    )

    adapter = HTTPAdapter(
        max_retries=retry_policy,
        pool_connections=4,
        pool_maxsize=4,
    )

    session = requests.Session()
    session.mount("https://", adapter)
    session.headers.update(
        {
            "User-Agent": (
                "Vision-Zero-Chicago-Capstone/1.0 "
                "spatial-source-acquisition"
            ),
            "Accept": "application/json, application/geo+json, */*",
        }
    )
    return session


def request_bytes(
    session: requests.Session,
    url: str,
    timeout_seconds: int,
    params: dict[str, Any] | None = None,
) -> requests.Response:
    """Perform one validated HTTP GET request."""

    validate_https_url(url, "request URL")
    response = session.get(
        url,
        params=params,
        timeout=timeout_seconds,
    )
    response.raise_for_status()

    if not response.content:
        raise SpatialAcquisitionError(
            f"Source returned an empty response: {response.url}"
        )

    return response


def validate_pdf(content: bytes, required_signature: str) -> dict[str, Any]:
    """Validate the PDF signature and basic file size."""

    signature = required_signature.encode("ascii")
    signature_present = content.startswith(signature)
    minimum_size_met = len(content) >= 1024

    if not signature_present:
        raise SpatialAcquisitionError(
            "PDF response does not start with the required PDF signature"
        )

    if not minimum_size_met:
        raise SpatialAcquisitionError(
            f"PDF response is unexpectedly small: {len(content)} bytes"
        )

    return {
        "signature_present": signature_present,
        "minimum_size_met": minimum_size_met,
        "bytes": len(content),
    }


def acquire_single_file(
    session: requests.Session,
    source_name: str,
    source_definition: dict[str, Any],
    source_acquisition: dict[str, Any],
    snapshot_directory: Path,
    timeout_seconds: int,
) -> dict[str, Any]:
    """Download and validate a configured single-file source."""

    url_field = source_acquisition["url_field"]
    url = source_definition[url_field]
    validate_https_url(url, url_field)

    response = request_bytes(
        session=session,
        url=url,
        timeout_seconds=timeout_seconds,
    )

    observed_content_type = require_content_type(
        response,
        source_acquisition["expected_content_types"],
    )

    content = response.content
    validation = validate_pdf(
        content,
        source_acquisition["required_file_signature"],
    )

    output_path = (
        snapshot_directory
        / source_acquisition["output_filename"]
    )
    atomic_write_bytes(output_path, content)

    return {
        "source_name": source_name,
        "source_config_key": source_acquisition["source_config_key"],
        "download_mode": "single_file",
        "status": "PASS",
        "url": url,
        "resolved_url": response.url,
        "status_code": response.status_code,
        "content_type": observed_content_type,
        "raw_path": str(output_path.relative_to(ROOT)),
        "bytes_written": len(content),
        "sha256": sha256_bytes(content),
        "validation": validation,
        "error_type": None,
        "error": None,
    }


def parse_json_response(response: requests.Response) -> Any:
    """Decode JSON and raise a domain-specific validation error."""

    try:
        return response.json()
    except (json.JSONDecodeError, requests.exceptions.JSONDecodeError) as error:
        raise SpatialAcquisitionError(
            "Response is not complete valid JSON: "
            f"{error}"
        ) from error


def fetch_expected_row_count(
    session: requests.Session,
    count_url: str,
    timeout_seconds: int,
) -> tuple[int, dict[str, Any]]:
    """Query Socrata for the current backing-dataset row count."""

    response = request_bytes(
        session=session,
        url=count_url,
        timeout_seconds=timeout_seconds,
        params={"$select": "count(*) as row_count"},
    )

    payload = parse_json_response(response)

    if not isinstance(payload, list) or len(payload) != 1:
        raise SpatialAcquisitionError(
            "Count endpoint did not return exactly one result row"
        )

    row_count_value = payload[0].get("row_count")

    try:
        row_count = int(row_count_value)
    except (TypeError, ValueError) as error:
        raise SpatialAcquisitionError(
            f"Invalid row count returned by source: {row_count_value!r}"
        ) from error

    if row_count <= 0:
        raise SpatialAcquisitionError(
            f"Backing dataset row count must be positive: {row_count}"
        )

    return row_count, {
        "url": count_url,
        "resolved_url": response.url,
        "status_code": response.status_code,
        "row_count": row_count,
    }


def validate_geojson_page(
    payload: Any,
    required_geojson_type: str,
    expected_geometry_types: list[str],
    required_property_fields: list[str],
    primary_key: str,
) -> dict[str, Any]:
    """Validate one paginated GeoJSON FeatureCollection."""

    if not isinstance(payload, dict):
        raise SpatialAcquisitionError(
            "GeoJSON page root must be a JSON object"
        )

    observed_type = payload.get("type")
    if observed_type != required_geojson_type:
        raise SpatialAcquisitionError(
            "Unexpected GeoJSON root type: "
            f"observed={observed_type!r}, "
            f"expected={required_geojson_type!r}"
        )

    features = payload.get("features")
    if not isinstance(features, list):
        raise SpatialAcquisitionError(
            "GeoJSON FeatureCollection is missing its features list"
        )

    expected_types = set(expected_geometry_types)
    geometry_type_counts: Counter[str] = Counter()
    primary_keys: list[str] = []
    null_geometry_count = 0
    empty_geometry_count = 0
    invalid_geometry_primary_keys: list[str] = []
    observed_property_fields: set[str] = set()

    for feature_number, feature in enumerate(features, start=1):
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            raise SpatialAcquisitionError(
                f"Feature {feature_number} is not a valid GeoJSON Feature"
            )

        properties = feature.get("properties")
        if not isinstance(properties, dict):
            raise SpatialAcquisitionError(
                f"Feature {feature_number} has no properties object"
            )

        observed_property_fields.update(properties)

        primary_key_value = properties.get(primary_key)
        if primary_key_value in (None, ""):
            raise SpatialAcquisitionError(
                f"Feature {feature_number} is missing primary key {primary_key!r}"
            )

        normalized_primary_key = str(primary_key_value)
        primary_keys.append(normalized_primary_key)

        geometry = feature.get("geometry")
        if not isinstance(geometry, dict):
            null_geometry_count += 1
            invalid_geometry_primary_keys.append(normalized_primary_key)
            continue

        geometry_type = geometry.get("type")
        geometry_type_counts[str(geometry_type)] += 1

        if geometry_type not in expected_types:
            raise SpatialAcquisitionError(
                f"Feature {feature_number} has unexpected geometry type: "
                f"{geometry_type!r}"
            )

        coordinates = geometry.get("coordinates")
        if coordinates in (None, []):
            empty_geometry_count += 1
            invalid_geometry_primary_keys.append(normalized_primary_key)
            continue

    missing_property_fields = sorted(
        set(required_property_fields) - observed_property_fields
    )
    if missing_property_fields:
        raise SpatialAcquisitionError(
            "Required GeoJSON properties are missing: "
            f"{missing_property_fields}"
        )

    duplicate_keys = len(primary_keys) - len(set(primary_keys))
    if duplicate_keys:
        raise SpatialAcquisitionError(
            f"GeoJSON page contains {duplicate_keys} duplicate primary keys"
        )

    invalid_geometry_count = (
        null_geometry_count + empty_geometry_count
    )
    valid_geometry_count = len(features) - invalid_geometry_count

    return {
        "feature_count": len(features),
        "valid_geometry_count": valid_geometry_count,
        "invalid_geometry_count": invalid_geometry_count,
        "null_geometry_count": null_geometry_count,
        "empty_geometry_count": empty_geometry_count,
        "valid_geometry_coverage": (
            valid_geometry_count / len(features)
            if features
            else 0.0
        ),
        "invalid_geometry_primary_keys": invalid_geometry_primary_keys,
        "geometry_type_counts": dict(sorted(geometry_type_counts.items())),
        "observed_property_fields": sorted(observed_property_fields),
        "primary_keys": primary_keys,
        "first_primary_key": primary_keys[0] if primary_keys else None,
        "last_primary_key": primary_keys[-1] if primary_keys else None,
    }


def acquire_paginated_geojson(
    session: requests.Session,
    source_name: str,
    source_definition: dict[str, Any],
    source_acquisition: dict[str, Any],
    snapshot_directory: Path,
    timeout_seconds: int,
) -> dict[str, Any]:
    """Download, validate, and inventory ordered Socrata GeoJSON pages."""

    url = source_definition[source_acquisition["url_field"]]
    count_url = source_definition[source_acquisition["count_url_field"]]
    validate_https_url(url, source_acquisition["url_field"])
    validate_https_url(count_url, source_acquisition["count_url_field"])

    page_size = int(source_acquisition["page_size"])
    if page_size <= 0:
        raise SpatialAcquisitionError("GeoJSON page size must be positive")

    order_by = source_acquisition["order_by"]
    primary_key = source_definition["primary_key"]

    if order_by != primary_key:
        raise SpatialAcquisitionError(
            "Stable pagination requires order_by to match the primary key: "
            f"order_by={order_by!r}, primary_key={primary_key!r}"
        )

    expected_rows, count_evidence = fetch_expected_row_count(
        session=session,
        count_url=count_url,
        timeout_seconds=timeout_seconds,
    )

    expected_page_count = math.ceil(expected_rows / page_size)
    output_directory = (
        snapshot_directory
        / source_acquisition["output_directory"]
    )
    output_directory.mkdir(parents=True, exist_ok=False)

    pages: list[dict[str, Any]] = []
    all_primary_keys: set[str] = set()
    duplicate_primary_key_count = 0
    observed_rows = 0
    total_bytes = 0
    aggregate_geometry_counts: Counter[str] = Counter()
    valid_geometry_features = 0
    invalid_geometry_features = 0
    invalid_geometry_primary_keys: list[str] = []

    geometry_quality = source_acquisition.get("geometry_quality", {})
    invalid_geometry_action = geometry_quality.get(
        "invalid_geometry_action",
        "fail",
    )
    minimum_valid_geometry_coverage = float(
        geometry_quality.get(
            "minimum_valid_geometry_coverage",
            1.0,
        )
    )
    preserve_invalid_geometry_features = bool(
        geometry_quality.get(
            "preserve_invalid_geometry_features",
            False,
        )
    )

    for page_number in range(1, expected_page_count + 1):
        offset = (page_number - 1) * page_size
        params = {
            "$limit": page_size,
            "$offset": offset,
            "$order": order_by,
        }

        response = request_bytes(
            session=session,
            url=url,
            timeout_seconds=timeout_seconds,
            params=params,
        )

        observed_content_type = require_content_type(
            response,
            source_acquisition["expected_content_types"],
        )

        page_filename = source_acquisition[
            "page_filename_pattern"
        ].format(part_number=page_number)
        page_path = output_directory / page_filename

        # Keep the exact HTTP response for lineage. If JSON validation fails,
        # the failed snapshot still contains the problematic source response.
        atomic_write_bytes(page_path, response.content)

        payload = parse_json_response(response)
        validation = validate_geojson_page(
            payload=payload,
            required_geojson_type=source_acquisition[
                "required_geojson_type"
            ],
            expected_geometry_types=source_acquisition[
                "expected_geometry_types"
            ],
            required_property_fields=source_acquisition[
                "required_property_fields"
            ],
            primary_key=primary_key,
        )

        page_feature_count = validation["feature_count"]
        expected_features_this_page = min(
            page_size,
            expected_rows - offset,
        )

        if page_feature_count != expected_features_this_page:
            raise SpatialAcquisitionError(
                "Unexpected page feature count: "
                f"page={page_number}, "
                f"observed={page_feature_count}, "
                f"expected={expected_features_this_page}"
            )

        page_primary_keys = validation.pop("primary_keys")
        page_invalid_geometry_primary_keys = validation.pop(
            "invalid_geometry_primary_keys"
        )
        page_duplicates = sum(
            primary_key_value in all_primary_keys
            for primary_key_value in page_primary_keys
        )
        duplicate_primary_key_count += page_duplicates
        all_primary_keys.update(page_primary_keys)

        if page_duplicates:
            raise SpatialAcquisitionError(
                "Duplicate primary keys detected across GeoJSON pages: "
                f"page={page_number}, duplicates={page_duplicates}"
            )

        aggregate_geometry_counts.update(
            validation["geometry_type_counts"]
        )
        valid_geometry_features += validation["valid_geometry_count"]
        invalid_geometry_features += validation[
            "invalid_geometry_count"
        ]
        invalid_geometry_primary_keys.extend(
            page_invalid_geometry_primary_keys
        )
        observed_rows += page_feature_count
        total_bytes += len(response.content)

        page_evidence = {
            "page_number": page_number,
            "offset": offset,
            "limit": page_size,
            "status_code": response.status_code,
            "content_type": observed_content_type,
            "resolved_url": response.url,
            "raw_path": str(page_path.relative_to(ROOT)),
            "bytes_written": len(response.content),
            "sha256": sha256_bytes(response.content),
            **validation,
            "invalid_geometry_primary_keys": (
                page_invalid_geometry_primary_keys
            ),
            "status": (
                "PASS_WITH_WARNINGS"
                if validation["invalid_geometry_count"]
                else "PASS"
            ),
        }
        pages.append(page_evidence)

        print(
            f"Page {page_number:05d}/{expected_page_count:05d}: "
            f"{page_feature_count:,} features | "
            f"total {observed_rows:,}/{expected_rows:,}"
        )

        # Be a responsible public-API client without materially slowing work.
        if page_number < expected_page_count:
            time.sleep(0.05)

    if observed_rows != expected_rows:
        raise SpatialAcquisitionError(
            "Downloaded row count does not match the live count endpoint: "
            f"observed={observed_rows}, expected={expected_rows}"
        )

    if len(all_primary_keys) != expected_rows:
        raise SpatialAcquisitionError(
            "Unique primary-key count does not match expected rows: "
            f"unique={len(all_primary_keys)}, expected={expected_rows}"
        )

    valid_geometry_coverage = (
        valid_geometry_features / observed_rows
        if observed_rows
        else 0.0
    )

    if invalid_geometry_features:
        if not preserve_invalid_geometry_features:
            raise SpatialAcquisitionError(
                "Invalid geometries were found but preservation is disabled: "
                f"count={invalid_geometry_features}"
            )

        if invalid_geometry_action != "preserve_and_warn":
            raise SpatialAcquisitionError(
                "Invalid geometry action does not permit warning-only "
                f"acceptance: {invalid_geometry_action!r}"
            )

    if valid_geometry_coverage < minimum_valid_geometry_coverage:
        raise SpatialAcquisitionError(
            "Valid geometry coverage is below the configured minimum: "
            f"observed={valid_geometry_coverage:.6f}, "
            f"minimum={minimum_valid_geometry_coverage:.6f}"
        )

    source_status = (
        "PASS_WITH_WARNINGS"
        if invalid_geometry_features
        else "PASS"
    )
    issues = []

    if invalid_geometry_features:
        issues.append(
            {
                "issue_code": "invalid_street_centerline_geometry",
                "severity": "WARNING",
                "affected_rows": invalid_geometry_features,
                "affected_rate": (
                    invalid_geometry_features / observed_rows
                ),
                "primary_keys": invalid_geometry_primary_keys,
                "action": (
                    "preserve_in_raw_snapshot_and_exclude_from_"
                    "corridor_construction"
                ),
                "status": "open",
            }
        )

    return {
        "source_name": source_name,
        "source_config_key": source_acquisition["source_config_key"],
        "download_mode": "paginated_geojson",
        "status": source_status,
        "url": url,
        "count_url": count_url,
        "primary_key": primary_key,
        "order_by": order_by,
        "page_size": page_size,
        "expected_rows": expected_rows,
        "downloaded_rows": observed_rows,
        "unique_primary_keys": len(all_primary_keys),
        "duplicate_primary_keys": duplicate_primary_key_count,
        "valid_geometry_features": valid_geometry_features,
        "invalid_geometry_features": invalid_geometry_features,
        "valid_geometry_coverage": valid_geometry_coverage,
        "minimum_valid_geometry_coverage": (
            minimum_valid_geometry_coverage
        ),
        "invalid_geometry_primary_keys": invalid_geometry_primary_keys,
        "exclude_invalid_geometry_from_corridor_construction": bool(
            geometry_quality.get(
                "exclude_invalid_geometry_from_corridor_construction",
                True,
            )
        ),
        "expected_page_count": expected_page_count,
        "downloaded_page_count": len(pages),
        "bytes_written": total_bytes,
        "geometry_type_counts": dict(
            sorted(aggregate_geometry_counts.items())
        ),
        "count_evidence": count_evidence,
        "output_directory": str(output_directory.relative_to(ROOT)),
        "pages": pages,
        "issues": issues,
        "error_type": None,
        "error": None,
    }


def failed_source_result(
    source_name: str,
    source_acquisition: dict[str, Any],
    error: Exception,
) -> dict[str, Any]:
    """Create a consistent failed-source manifest entry."""

    return {
        "source_name": source_name,
        "source_config_key": source_acquisition.get(
            "source_config_key"
        ),
        "download_mode": source_acquisition.get("download_mode"),
        "status": "FAIL",
        "raw_path": None,
        "sha256": None,
        "download": None,
        "validation": None,
        "error_type": type(error).__name__,
        "error": str(error),
    }


def acquire_source(
    session: requests.Session,
    source_name: str,
    source_definition: dict[str, Any],
    source_acquisition: dict[str, Any],
    snapshot_directory: Path,
    timeout_seconds: int,
) -> dict[str, Any]:
    """Route a source to its configured acquisition strategy."""

    mode = source_acquisition.get("download_mode")

    if mode == "single_file":
        return acquire_single_file(
            session=session,
            source_name=source_name,
            source_definition=source_definition,
            source_acquisition=source_acquisition,
            snapshot_directory=snapshot_directory,
            timeout_seconds=timeout_seconds,
        )

    if mode == "paginated_geojson":
        return acquire_paginated_geojson(
            session=session,
            source_name=source_name,
            source_definition=source_definition,
            source_acquisition=source_acquisition,
            snapshot_directory=snapshot_directory,
            timeout_seconds=timeout_seconds,
        )

    raise SpatialAcquisitionError(
        f"Unsupported acquisition mode for {source_name}: {mode!r}"
    )


def validate_configuration(
    spatial_config: dict[str, Any],
    sources_config: dict[str, Any],
) -> None:
    """Validate required acquisition configuration before any download."""

    acquisition = spatial_config.get("acquisition")
    corridor_sources = sources_config.get("corridor_sources")

    if not isinstance(acquisition, dict):
        raise SpatialAcquisitionError(
            "config/spatial.yml is missing acquisition configuration"
        )

    if not isinstance(corridor_sources, dict):
        raise SpatialAcquisitionError(
            "config/sources.yml is missing corridor_sources"
        )

    configured_sources = acquisition.get("sources")
    if not isinstance(configured_sources, dict) or not configured_sources:
        raise SpatialAcquisitionError(
            "No spatial acquisition sources are configured"
        )

    for source_name, source_acquisition in configured_sources.items():
        source_config_key = source_acquisition.get("source_config_key")
        if source_config_key not in corridor_sources:
            raise SpatialAcquisitionError(
                f"Missing corridor source definition: {source_config_key!r}"
            )

        source_definition = corridor_sources[source_config_key]
        url_field = source_acquisition.get("url_field")
        if url_field not in source_definition:
            raise SpatialAcquisitionError(
                f"{source_name} is missing URL field {url_field!r}"
            )
        validate_https_url(source_definition[url_field], url_field)

        count_url_field = source_acquisition.get("count_url_field")
        if count_url_field:
            if count_url_field not in source_definition:
                raise SpatialAcquisitionError(
                    f"{source_name} is missing count URL field "
                    f"{count_url_field!r}"
                )
            validate_https_url(
                source_definition[count_url_field],
                count_url_field,
            )


def main() -> int:
    """Run spatial acquisition and persist latest and historical manifests."""

    started_at = utc_now()
    run_id = timestamp_id(started_at)

    try:
        spatial_config = load_yaml(SPATIAL_CONFIG_PATH)
        sources_config = load_yaml(SOURCES_CONFIG_PATH)
        validate_configuration(spatial_config, sources_config)
    except Exception as error:
        print(f"Spatial acquisition configuration error: {error}")
        return 1

    acquisition = spatial_config["acquisition"]
    configured_sources = acquisition["sources"]
    corridor_sources = sources_config["corridor_sources"]

    raw_root = ROOT / acquisition["raw_root"]
    snapshot_directory = raw_root / f"snapshot_{run_id}"

    if snapshot_directory.exists():
        print(
            "Refusing to overwrite existing spatial snapshot: "
            f"{snapshot_directory}"
        )
        return 1

    snapshot_directory.mkdir(parents=True, exist_ok=False)

    manifest_directory = ROOT / acquisition["manifest_directory"]
    manifest_directory.mkdir(parents=True, exist_ok=True)
    historical_manifest_path = (
        manifest_directory
        / f"spatial_acquisition_{run_id}_manifest.json"
    )
    latest_manifest_path = ROOT / acquisition["latest_manifest_path"]

    timeout_seconds = int(
        acquisition.get("request_timeout_seconds", 180)
    )
    session = build_session(acquisition)
    source_results: list[dict[str, Any]] = []

    print("Spatial-source acquisition")
    print(SEPARATOR)
    print(f"Run ID: {run_id}")
    print(f"Snapshot: {snapshot_directory}")
    print(SEPARATOR)

    try:
        for source_name, source_acquisition in configured_sources.items():
            source_config_key = source_acquisition["source_config_key"]
            source_definition = corridor_sources[source_config_key]

            print(f"Source: {source_name}")
            print(
                f"Mode: {source_acquisition['download_mode']}"
            )
            print(SUBSEPARATOR)

            try:
                result = acquire_source(
                    session=session,
                    source_name=source_name,
                    source_definition=source_definition,
                    source_acquisition=source_acquisition,
                    snapshot_directory=snapshot_directory,
                    timeout_seconds=timeout_seconds,
                )
            except Exception as error:
                result = failed_source_result(
                    source_name=source_name,
                    source_acquisition=source_acquisition,
                    error=error,
                )

            source_results.append(result)
            print(f"Source status: {result['status']}")

            if result["status"] == "FAIL":
                print(
                    f"Failure: {result['error_type']}: "
                    f"{result['error']}"
                )

            print(SEPARATOR)
    finally:
        session.close()

    passed_source_count = sum(
        result["status"] in {"PASS", "PASS_WITH_WARNINGS"}
        for result in source_results
    )
    warning_source_count = sum(
        result["status"] == "PASS_WITH_WARNINGS"
        for result in source_results
    )
    failed_source_count = sum(
        result["status"] == "FAIL"
        for result in source_results
    )

    if failed_source_count:
        overall_status = "FAIL"
    elif warning_source_count:
        overall_status = "PASS_WITH_WARNINGS"
    else:
        overall_status = "PASS"
    completed_at = utc_now()

    manifest = {
        "run_id": run_id,
        "acquisition_name": "Vision Zero Chicago spatial-source acquisition",
        "started_at_utc": iso_utc(started_at),
        "completed_at_utc": iso_utc(completed_at),
        "status": overall_status,
        "published_snapshot": failed_source_count == 0,
        "snapshot_directory": str(snapshot_directory.relative_to(ROOT)),
        "source_count": len(source_results),
        "passed_source_count": passed_source_count,
        "warning_source_count": warning_source_count,
        "failed_source_count": failed_source_count,
        "preservation": acquisition["preservation"],
        "sources": source_results,
    }

    atomic_write_json(historical_manifest_path, manifest)
    atomic_write_json(latest_manifest_path, manifest)

    print(f"Overall spatial-acquisition status: {overall_status}")
    print(f"Passed sources: {passed_source_count}")
    print(f"Sources with warnings: {warning_source_count}")
    print(f"Failed sources: {failed_source_count}")
    print(f"Historical manifest: {historical_manifest_path}")
    print(f"Latest manifest: {latest_manifest_path}")
    print(SEPARATOR)

    return 0 if overall_status == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())