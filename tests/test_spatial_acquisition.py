"""Tests for immutable spatial-source acquisition and validation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from src.data import download_spatial_sources as spatial


ROOT = Path(__file__).resolve().parents[1]
SPATIAL_CONFIG_PATH = ROOT / "config" / "spatial.yml"
SOURCES_CONFIG_PATH = ROOT / "config" / "sources.yml"


def load_yaml(path: Path) -> dict[str, Any]:
    """Load one project YAML configuration file."""

    with path.open(encoding="utf-8") as file:
        data = yaml.safe_load(file)

    assert isinstance(data, dict)
    return data


def make_feature(
    objectid: int,
    geometry_type: str = "MultiLineString",
    extra_properties: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a valid synthetic street-centerline GeoJSON feature."""

    if geometry_type == "MultiLineString":
        coordinates: Any = [
            [
                [-87.6300, 41.8800],
                [-87.6290, 41.8810],
            ]
        ]
    else:
        coordinates = [
            [-87.6300, 41.8800],
            [-87.6290, 41.8810],
        ]

    properties = {
        "objectid": objectid,
        "trans_id": objectid + 1000,
        "fnode_id": objectid + 2000,
        "tnode_id": objectid + 3000,
        "street_nam": "STATE",
        "street_typ": "ST",
        "f_cross": "MADISON",
        "t_cross": "MONROE",
        "status": "OPEN",
        "length": 100.0,
    }

    if extra_properties:
        properties.update(extra_properties)

    return {
        "type": "Feature",
        "geometry": {
            "type": geometry_type,
            "coordinates": coordinates,
        },
        "properties": properties,
    }


def make_feature_collection(
    objectids: list[int],
) -> dict[str, Any]:
    """Create a synthetic GeoJSON FeatureCollection."""

    return {
        "type": "FeatureCollection",
        "features": [
            make_feature(objectid)
            for objectid in objectids
        ],
    }


class FakeResponse:
    """Small requests.Response substitute for deterministic unit tests."""

    def __init__(
        self,
        payload: Any,
        *,
        content_type: str = "application/vnd.geo+json; charset=UTF-8",
        status_code: int = 200,
        url: str = "https://example.test/resource.geojson",
    ) -> None:
        self.payload = payload
        self.content = json.dumps(payload).encode("utf-8")
        self.headers = {"Content-Type": content_type}
        self.status_code = status_code
        self.url = url

    def raise_for_status(self) -> None:
        """Raise an HTTP-style error for non-success responses."""

        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> Any:
        """Return the configured JSON payload."""

        return self.payload


class FakeSession:
    """Return queued fake responses and record request parameters."""

    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def get(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        timeout: int | None = None,
    ) -> FakeResponse:
        """Return the next queued response."""

        self.calls.append(
            {
                "url": url,
                "params": params,
                "timeout": timeout,
            }
        )

        if not self.responses:
            raise AssertionError("No fake response remains")

        return self.responses.pop(0)


def street_acquisition_config(
    page_size: int = 2,
) -> dict[str, Any]:
    """Return a minimal paginated GeoJSON acquisition definition."""

    return {
        "source_config_key": "street_center_lines",
        "download_mode": "paginated_geojson",
        "url_field": "geojson_url",
        "count_url_field": "count_url",
        "output_directory": "street_pages",
        "page_filename_pattern": "part-{part_number:05d}.geojson",
        "page_size": page_size,
        "order_by": "objectid",
        "expected_content_types": [
            "application/vnd.geo+json",
            "application/geo+json",
            "application/json",
        ],
        "required_geojson_type": "FeatureCollection",
        "expected_geometry_types": [
            "MultiLineString",
            "LineString",
        ],
        "required_property_fields": [
            "objectid",
            "trans_id",
            "fnode_id",
            "tnode_id",
            "street_nam",
            "street_typ",
            "f_cross",
            "t_cross",
            "status",
            "length",
        ],
    }


def street_source_definition() -> dict[str, Any]:
    """Return a minimal backing-dataset source definition."""

    return {
        "geojson_url": (
            "https://data.cityofchicago.org/"
            "resource/pr57-gg9e.geojson"
        ),
        "count_url": (
            "https://data.cityofchicago.org/"
            "resource/pr57-gg9e.json"
        ),
        "primary_key": "objectid",
    }


def test_spatial_acquisition_configuration_is_complete():
    """The project must use the backing dataset and stable pagination."""

    spatial_config = load_yaml(SPATIAL_CONFIG_PATH)
    sources_config = load_yaml(SOURCES_CONFIG_PATH)

    acquisition = spatial_config["acquisition"]
    street_acquisition = acquisition["sources"][
        "street_center_lines"
    ]
    street_source = sources_config["corridor_sources"][
        "street_center_lines"
    ]

    assert street_source["map_view_id"] == "6imu-meau"
    assert street_source["backing_dataset_id"] == "pr57-gg9e"
    assert street_source["primary_key"] == "objectid"
    assert street_source["geojson_url"].endswith(
        "/resource/pr57-gg9e.geojson"
    )
    assert street_source["count_url"].endswith(
        "/resource/pr57-gg9e.json"
    )

    assert street_acquisition["download_mode"] == "paginated_geojson"
    assert street_acquisition["page_size"] == 5000
    assert street_acquisition["order_by"] == "objectid"
    assert len(street_acquisition["required_property_fields"]) == 10
    geometry_quality = street_acquisition["geometry_quality"]
    assert geometry_quality == {
        "preserve_invalid_geometry_features": True,
        "invalid_geometry_action": "preserve_and_warn",
        "minimum_valid_geometry_coverage": 0.999,
        "exclude_invalid_geometry_from_corridor_construction": True,
    }

    plan_acquisition = acquisition["sources"][
        "high_crash_corridor_plan"
    ]
    assert plan_acquisition["download_mode"] == "single_file"
    assert acquisition["preservation"][
        "preserve_existing_snapshots"
    ] is True
    assert acquisition["preservation"][
        "overwrite_existing_files"
    ] is False
    assert acquisition["preservation"]["compute_sha256"] is True
    assert acquisition["evidence"][
        "persist_failed_manifests"
    ] is True


def test_configured_source_urls_are_raw_https_urls():
    """YAML source URLs must not contain rendered Markdown syntax."""

    sources_config = load_yaml(SOURCES_CONFIG_PATH)
    corridor_sources = sources_config["corridor_sources"]

    urls = [
        corridor_sources["high_crash_corridor_plan"]["document_url"],
        corridor_sources["street_center_lines"]["page_url"],
        corridor_sources["street_center_lines"]["metadata_url"],
        corridor_sources["street_center_lines"][
            "backing_metadata_url"
        ],
        corridor_sources["street_center_lines"]["geojson_url"],
        corridor_sources["street_center_lines"]["count_url"],
    ]

    for url in urls:
        spatial.validate_https_url(url, "configured URL")
        assert url.startswith("https://")
        assert "[" not in url
        assert "]" not in url


def test_media_type_removes_charset_and_normalizes_case():
    """HTTP media-type validation should ignore charset parameters."""

    assert (
        spatial.media_type(
            "Application/Vnd.Geo+Json; charset=UTF-8"
        )
        == "application/vnd.geo+json"
    )
    assert spatial.media_type(None) == ""


def test_sha256_bytes_matches_hashlib():
    """Manifest checksums must be deterministic."""

    content = b"vision-zero-spatial-source"

    assert spatial.sha256_bytes(content) == hashlib.sha256(
        content
    ).hexdigest()


def test_validate_pdf_accepts_realistic_pdf_bytes():
    """A PDF must have the correct signature and a non-trivial size."""

    content = b"%PDF-1.7\n" + (b"x" * 2048)
    validation = spatial.validate_pdf(content, "%PDF")

    assert validation["signature_present"] is True
    assert validation["minimum_size_met"] is True
    assert validation["bytes"] == len(content)


@pytest.mark.parametrize(
    "content",
    [
        b"<html>not a PDF</html>" + (b"x" * 2048),
        b"%PDF-small",
    ],
)
def test_validate_pdf_rejects_invalid_content(content: bytes):
    """HTML error pages and truncated PDFs must fail validation."""

    with pytest.raises(spatial.SpatialAcquisitionError):
        spatial.validate_pdf(content, "%PDF")


def test_validate_geojson_page_accepts_required_schema():
    """Valid line features should produce page-level evidence."""

    payload = {
        "type": "FeatureCollection",
        "features": [
            make_feature(1, "MultiLineString"),
            make_feature(2, "LineString"),
        ],
    }
    acquisition = street_acquisition_config()

    validation = spatial.validate_geojson_page(
        payload=payload,
        required_geojson_type="FeatureCollection",
        expected_geometry_types=acquisition[
            "expected_geometry_types"
        ],
        required_property_fields=acquisition[
            "required_property_fields"
        ],
        primary_key="objectid",
    )

    assert validation["feature_count"] == 2
    assert validation["null_geometry_count"] == 0
    assert validation["first_primary_key"] == "1"
    assert validation["last_primary_key"] == "2"
    assert validation["geometry_type_counts"] == {
        "LineString": 1,
        "MultiLineString": 1,
    }


def test_validate_geojson_page_preserves_invalid_geometry_for_warning():
    """Invalid geometry stays in raw evidence and is counted for exclusion."""

    feature = make_feature(1)
    feature["geometry"] = None
    payload = {
        "type": "FeatureCollection",
        "features": [feature],
    }
    acquisition = street_acquisition_config()

    validation = spatial.validate_geojson_page(
        payload=payload,
        required_geojson_type="FeatureCollection",
        expected_geometry_types=acquisition[
            "expected_geometry_types"
        ],
        required_property_fields=acquisition[
            "required_property_fields"
        ],
        primary_key="objectid",
    )

    assert validation["feature_count"] == 1
    assert validation["valid_geometry_count"] == 0
    assert validation["invalid_geometry_count"] == 1
    assert validation["null_geometry_count"] == 1
    assert validation["empty_geometry_count"] == 0
    assert validation["invalid_geometry_primary_keys"] == ["1"]


def test_validate_geojson_page_rejects_unexpected_geometry_type():
    """Point geometries must not be accepted as street centerlines."""

    feature = make_feature(1)
    feature["geometry"] = {
        "type": "Point",
        "coordinates": [-87.63, 41.88],
    }
    payload = {
        "type": "FeatureCollection",
        "features": [feature],
    }
    acquisition = street_acquisition_config()

    with pytest.raises(
        spatial.SpatialAcquisitionError,
        match="unexpected geometry type",
    ):
        spatial.validate_geojson_page(
            payload=payload,
            required_geojson_type="FeatureCollection",
            expected_geometry_types=acquisition[
                "expected_geometry_types"
            ],
            required_property_fields=acquisition[
                "required_property_fields"
            ],
            primary_key="objectid",
        )


def test_validate_geojson_page_rejects_missing_required_property():
    """Schema drift must fail before an incomplete page is approved."""

    feature = make_feature(1)
    del feature["properties"]["street_nam"]
    payload = {
        "type": "FeatureCollection",
        "features": [feature],
    }
    acquisition = street_acquisition_config()

    with pytest.raises(
        spatial.SpatialAcquisitionError,
        match="Required GeoJSON properties are missing",
    ):
        spatial.validate_geojson_page(
            payload=payload,
            required_geojson_type="FeatureCollection",
            expected_geometry_types=acquisition[
                "expected_geometry_types"
            ],
            required_property_fields=acquisition[
                "required_property_fields"
            ],
            primary_key="objectid",
        )


def test_validate_geojson_page_rejects_duplicate_primary_keys():
    """Duplicate object IDs inside one page must fail validation."""

    payload = {
        "type": "FeatureCollection",
        "features": [
            make_feature(1),
            make_feature(1),
        ],
    }
    acquisition = street_acquisition_config()

    with pytest.raises(
        spatial.SpatialAcquisitionError,
        match="duplicate primary keys",
    ):
        spatial.validate_geojson_page(
            payload=payload,
            required_geojson_type="FeatureCollection",
            expected_geometry_types=acquisition[
                "expected_geometry_types"
            ],
            required_property_fields=acquisition[
                "required_property_fields"
            ],
            primary_key="objectid",
        )


def test_paginated_geojson_reconciles_count_and_writes_pages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Ordered pages must reconcile exactly to the live count response."""

    monkeypatch.setattr(spatial, "ROOT", tmp_path)
    monkeypatch.setattr(spatial.time, "sleep", lambda _: None)

    count_response = FakeResponse(
        [{"row_count": "3"}],
        content_type="application/json; charset=UTF-8",
        url="https://example.test/count",
    )
    page_one_response = FakeResponse(
        make_feature_collection([1, 2]),
        url="https://example.test/page-1",
    )
    page_two_response = FakeResponse(
        make_feature_collection([3]),
        url="https://example.test/page-2",
    )
    session = FakeSession(
        [
            count_response,
            page_one_response,
            page_two_response,
        ]
    )
    snapshot_directory = tmp_path / "data" / "raw" / "snapshot_test"
    snapshot_directory.mkdir(parents=True)

    result = spatial.acquire_paginated_geojson(
        session=session,
        source_name="street_center_lines",
        source_definition=street_source_definition(),
        source_acquisition=street_acquisition_config(page_size=2),
        snapshot_directory=snapshot_directory,
        timeout_seconds=30,
    )

    assert result["status"] == "PASS"
    assert result["expected_rows"] == 3
    assert result["downloaded_rows"] == 3
    assert result["unique_primary_keys"] == 3
    assert result["duplicate_primary_keys"] == 0
    assert result["expected_page_count"] == 2
    assert result["downloaded_page_count"] == 2

    page_directory = snapshot_directory / "street_pages"
    assert sorted(path.name for path in page_directory.iterdir()) == [
        "part-00001.geojson",
        "part-00002.geojson",
    ]

    assert session.calls[1]["params"] == {
        "$limit": 2,
        "$offset": 0,
        "$order": "objectid",
    }
    assert session.calls[2]["params"] == {
        "$limit": 2,
        "$offset": 2,
        "$order": "objectid",
    }


def test_paginated_geojson_accepts_documented_invalid_geometry_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """A high-coverage source may pass with preserved invalid geometry."""

    monkeypatch.setattr(spatial, "ROOT", tmp_path)
    monkeypatch.setattr(spatial.time, "sleep", lambda _: None)

    invalid_feature = make_feature(3)
    invalid_feature["geometry"] = {
        "type": "MultiLineString",
        "coordinates": [],
    }

    page_two = {
        "type": "FeatureCollection",
        "features": [invalid_feature],
    }

    session = FakeSession(
        [
            FakeResponse(
                [{"row_count": "3"}],
                content_type="application/json",
            ),
            FakeResponse(make_feature_collection([1, 2])),
            FakeResponse(page_two),
        ]
    )
    snapshot_directory = tmp_path / "snapshot_warning"
    snapshot_directory.mkdir()

    acquisition = street_acquisition_config(page_size=2)
    acquisition["geometry_quality"] = {
        "preserve_invalid_geometry_features": True,
        "invalid_geometry_action": "preserve_and_warn",
        "minimum_valid_geometry_coverage": 0.5,
        "exclude_invalid_geometry_from_corridor_construction": True,
    }

    result = spatial.acquire_paginated_geojson(
        session=session,
        source_name="street_center_lines",
        source_definition=street_source_definition(),
        source_acquisition=acquisition,
        snapshot_directory=snapshot_directory,
        timeout_seconds=30,
    )

    assert result["status"] == "PASS_WITH_WARNINGS"
    assert result["downloaded_rows"] == 3
    assert result["valid_geometry_features"] == 2
    assert result["invalid_geometry_features"] == 1
    assert result["invalid_geometry_primary_keys"] == ["3"]
    assert result["valid_geometry_coverage"] == pytest.approx(2 / 3)
    assert result["issues"][0]["issue_code"] == (
        "invalid_street_centerline_geometry"
    )


def test_paginated_geojson_rejects_duplicates_across_pages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Stable pagination must detect repeated IDs across page boundaries."""

    monkeypatch.setattr(spatial, "ROOT", tmp_path)
    monkeypatch.setattr(spatial.time, "sleep", lambda _: None)

    session = FakeSession(
        [
            FakeResponse(
                [{"row_count": "3"}],
                content_type="application/json",
            ),
            FakeResponse(make_feature_collection([1, 2])),
            FakeResponse(make_feature_collection([2])),
        ]
    )
    snapshot_directory = tmp_path / "snapshot_test"
    snapshot_directory.mkdir()

    with pytest.raises(
        spatial.SpatialAcquisitionError,
        match="across GeoJSON pages",
    ):
        spatial.acquire_paginated_geojson(
            session=session,
            source_name="street_center_lines",
            source_definition=street_source_definition(),
            source_acquisition=street_acquisition_config(page_size=2),
            snapshot_directory=snapshot_directory,
            timeout_seconds=30,
        )


def test_paginated_geojson_requires_primary_key_ordering(
    tmp_path: Path,
):
    """Offset pagination is unsafe without deterministic primary-key order."""

    acquisition = street_acquisition_config()
    acquisition["order_by"] = "street_nam"
    snapshot_directory = tmp_path / "snapshot_test"
    snapshot_directory.mkdir()

    with pytest.raises(
        spatial.SpatialAcquisitionError,
        match="order_by to match the primary key",
    ):
        spatial.acquire_paginated_geojson(
            session=FakeSession([]),
            source_name="street_center_lines",
            source_definition=street_source_definition(),
            source_acquisition=acquisition,
            snapshot_directory=snapshot_directory,
            timeout_seconds=30,
        )


def test_atomic_write_json_replaces_complete_document(tmp_path: Path):
    """Latest manifests must always remain valid complete JSON documents."""

    output_path = tmp_path / "manifest.json"
    spatial.atomic_write_json(output_path, {"status": "FAIL"})
    spatial.atomic_write_json(
        output_path,
        {
            "status": "PASS",
            "rows": 3,
        },
    )

    with output_path.open(encoding="utf-8") as file:
        payload = json.load(file)

    assert payload == {
        "status": "PASS",
        "rows": 3,
    }
    assert not output_path.with_name("manifest.json.tmp").exists()