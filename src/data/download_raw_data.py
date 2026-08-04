from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
import yaml
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


ROOT = Path(__file__).resolve().parents[2]

SOURCES_CONFIG_PATH = ROOT / "config" / "sources.yml"
ACQUISITION_CONFIG_PATH = ROOT / "config" / "acquisition.yml"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as file:
        data = yaml.safe_load(file)

    if not isinstance(data, dict):
        raise ValueError(f"Expected YAML mapping in {path}")

    return data


def build_session(
    maximum_retries: int,
    retry_backoff_seconds: float,
) -> requests.Session:
    retry_policy = Retry(
        total=maximum_retries,
        connect=maximum_retries,
        read=maximum_retries,
        status=maximum_retries,
        backoff_factor=retry_backoff_seconds,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=frozenset(["GET"]),
        raise_on_status=False,
    )

    adapter = HTTPAdapter(max_retries=retry_policy)

    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update(
        {
            "User-Agent": (
                "Vision-Zero-Chicago-Capstone/raw-data-acquisition"
            )
        }
    )

    return session


def build_where_clause(
    date_field: str,
    history_start: str,
    history_end_exclusive: str,
) -> str:
    return (
        f"{date_field} >= '{history_start}' "
        f"AND {date_field} < '{history_end_exclusive}'"
    )


def convert_to_csv_url(api_url: str) -> str:
    if api_url.endswith(".json"):
        return f"{api_url[:-5]}.csv"
    if api_url.endswith(".csv"):
        return api_url

    raise ValueError(
        f"Expected a .json or .csv Socrata API URL: {api_url}"
    )


def fetch_source_count(
    session: requests.Session,
    api_url: str,
    where_clause: str,
    timeout_seconds: int,
) -> int:
    response = session.get(
        api_url,
        params={
            "$select": "count(*) AS row_count",
            "$where": where_clause,
        },
        timeout=timeout_seconds,
    )
    response.raise_for_status()

    payload = response.json()
    if not payload or "row_count" not in payload[0]:
        raise ValueError(f"Unexpected count response from {response.url}")

    return int(payload[0]["row_count"])


def read_csv_page(
    content: bytes,
    selected_fields: list[str],
) -> tuple[list[str], int]:
    if not content:
        raise ValueError("The API returned an empty response")

    text_stream = io.TextIOWrapper(
        io.BytesIO(content),
        encoding="utf-8-sig",
        newline="",
    )
    reader = csv.reader(text_stream)

    try:
        header = next(reader)
    except StopIteration as error:
        raise ValueError("The CSV response contained no header") from error

    normalized_header = [field.lstrip("\ufeff") for field in header]
    if normalized_header != selected_fields:
        raise ValueError(
            "Downloaded header does not match the acquisition contract. "
            f"Expected {selected_fields}; received {normalized_header}"
        )

    row_count = sum(1 for row in reader if row)
    return normalized_header, row_count


def write_compressed_raw_page(content: bytes, output_path: Path) -> None:
    if output_path.exists():
        raise FileExistsError(
            f"Refusing to overwrite existing raw file: {output_path}"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(output_path, "wb") as gzip_file:
        gzip_file.write(content)


def calculate_sha256(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)

    return digest.hexdigest()


def write_manifest(
    manifest: dict[str, Any],
    manifest_path: Path,
) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    with manifest_path.open(
        "w",
        encoding="utf-8",
        newline="\n",
    ) as file:
        json.dump(manifest, file, indent=2)


def fetch_csv_page(
    session: requests.Session,
    csv_url: str,
    selected_fields: list[str],
    where_clause: str,
    order_by: list[str],
    batch_size: int,
    offset: int,
    timeout_seconds: int,
) -> tuple[bytes, str]:
    response = session.get(
        csv_url,
        params={
            "$select": ",".join(selected_fields),
            "$where": where_clause,
            "$order": ",".join(f"{field} ASC" for field in order_by),
            "$limit": batch_size,
            "$offset": offset,
        },
        timeout=timeout_seconds,
    )
    response.raise_for_status()

    return response.content, response.url


def download_source(
    source_name: str,
    source_catalog: dict[str, Any],
    acquisition_config: dict[str, Any],
    session: requests.Session,
    run_id: str,
) -> Path:
    settings = acquisition_config["acquisition"]
    acquisition_source = acquisition_config["sources"][source_name]
    source_config_key = acquisition_source["source_config_key"]
    source_config = source_catalog["sources"][source_config_key]

    api_url = source_config["api_url"]
    csv_url = convert_to_csv_url(api_url)
    selected_fields = acquisition_source["select_fields"]
    date_field = acquisition_source["date_field"]
    order_by = acquisition_source["order_by"]
    primary_key = source_config["primary_key"]

    history_start = settings["history_start"]
    history_end_exclusive = settings["history_end_exclusive"]
    batch_size = int(settings["batch_size"])
    timeout_seconds = int(settings["request_timeout_seconds"])

    where_clause = build_where_clause(
        date_field=date_field,
        history_start=history_start,
        history_end_exclusive=history_end_exclusive,
    )

    raw_root = ROOT / settings["raw_root"]
    manifest_root = ROOT / settings["manifest_root"]
    snapshot_directory = raw_root / source_name / f"snapshot_{run_id}"
    manifest_path = (
        manifest_root / f"{source_name}_{run_id}_manifest.json"
    )

    if snapshot_directory.exists():
        raise FileExistsError(
            f"Snapshot directory already exists: {snapshot_directory}"
        )

    manifest: dict[str, Any] = {
        "run_id": run_id,
        "source_name": source_name,
        "source_config_key": source_config_key,
        "source_title": source_config["source_name"],
        "dataset_id": source_config["dataset_id"],
        "api_url": api_url,
        "csv_url": csv_url,
        "primary_key": primary_key,
        "date_field": date_field,
        "history_start": history_start,
        "history_end_exclusive": history_end_exclusive,
        "where_clause": where_clause,
        "selected_fields": selected_fields,
        "order_by": order_by,
        "batch_size": batch_size,
        "snapshot_directory": str(snapshot_directory.relative_to(ROOT)),
        "started_at_utc": utc_now_iso(),
        "completed_at_utc": None,
        "expected_rows_before_download": None,
        "expected_rows_after_download": None,
        "downloaded_rows": 0,
        "part_count": 0,
        "parts": [],
        "status": "IN_PROGRESS",
        "error": None,
    }

    try:
        expected_before = fetch_source_count(
            session=session,
            api_url=api_url,
            where_clause=where_clause,
            timeout_seconds=timeout_seconds,
        )
        manifest["expected_rows_before_download"] = expected_before
        expected_parts = math.ceil(expected_before / batch_size)

        print(f"Source: {source_name}")
        print(f"Rows expected: {expected_before:,}")
        print(f"Expected parts: {expected_parts}")
        print(f"Snapshot: {snapshot_directory}")
        print("-" * 75)

        downloaded_rows = 0
        part_number = 1

        while downloaded_rows < expected_before:
            offset = downloaded_rows
            content, request_url = fetch_csv_page(
                session=session,
                csv_url=csv_url,
                selected_fields=selected_fields,
                where_clause=where_clause,
                order_by=order_by,
                batch_size=batch_size,
                offset=offset,
                timeout_seconds=timeout_seconds,
            )

            _, page_rows = read_csv_page(
                content=content,
                selected_fields=selected_fields,
            )
            if page_rows == 0:
                raise RuntimeError(
                    "The API returned zero rows before the expected "
                    "source count was reached"
                )

            output_path = (
                snapshot_directory / f"part-{part_number:05d}.csv.gz"
            )
            write_compressed_raw_page(content, output_path)

            manifest["parts"].append(
                {
                    "part_number": part_number,
                    "offset": offset,
                    "row_count": page_rows,
                    "request_url": request_url,
                    "relative_path": str(output_path.relative_to(ROOT)),
                    "compressed_bytes": output_path.stat().st_size,
                    "uncompressed_bytes": len(content),
                    "sha256": calculate_sha256(output_path),
                }
            )

            downloaded_rows += page_rows
            manifest["downloaded_rows"] = downloaded_rows
            manifest["part_count"] = part_number
            write_manifest(manifest, manifest_path)

            print(
                f"Part {part_number:05d}: {page_rows:,} rows | "
                f"total {downloaded_rows:,}/{expected_before:,}"
            )
            part_number += 1

        expected_after = fetch_source_count(
            session=session,
            api_url=api_url,
            where_clause=where_clause,
            timeout_seconds=timeout_seconds,
        )
        manifest["expected_rows_after_download"] = expected_after
        manifest["completed_at_utc"] = utc_now_iso()

        if downloaded_rows != expected_before or expected_before != expected_after:
            raise RuntimeError(
                "Row-count reconciliation failed: "
                f"before={expected_before}, downloaded={downloaded_rows}, "
                f"after={expected_after}"
            )

        manifest["status"] = "PASS"
        write_manifest(manifest, manifest_path)

        print("-" * 75)
        print("Source acquisition status: PASS")
        print(f"Downloaded rows: {downloaded_rows:,}")
        print(f"Manifest: {manifest_path}")

        return manifest_path

    except Exception as error:
        manifest["completed_at_utc"] = utc_now_iso()
        manifest["status"] = "FAIL"
        manifest["error"] = f"{type(error).__name__}: {error}"
        write_manifest(manifest, manifest_path)
        raise


def count_only(
    source_name: str,
    source_catalog: dict[str, Any],
    acquisition_config: dict[str, Any],
    session: requests.Session,
) -> int:
    settings = acquisition_config["acquisition"]
    acquisition_source = acquisition_config["sources"][source_name]
    source_key = acquisition_source["source_config_key"]
    source_config = source_catalog["sources"][source_key]

    where_clause = build_where_clause(
        date_field=acquisition_source["date_field"],
        history_start=settings["history_start"],
        history_end_exclusive=settings["history_end_exclusive"],
    )

    return fetch_source_count(
        session=session,
        api_url=source_config["api_url"],
        where_clause=where_clause,
        timeout_seconds=int(settings["request_timeout_seconds"]),
    )


def main() -> int:
    source_catalog = load_yaml(SOURCES_CONFIG_PATH)
    acquisition_config = load_yaml(ACQUISITION_CONFIG_PATH)
    settings = acquisition_config["acquisition"]
    available_sources = list(acquisition_config["sources"])

    parser = argparse.ArgumentParser(
        description="Download immutable raw Chicago crash-data snapshots."
    )
    parser.add_argument(
        "--source",
        required=True,
        choices=[*available_sources, "all"],
        help="Source to acquire.",
    )
    parser.add_argument(
        "--count-only",
        action="store_true",
        help="Query historical row counts without downloading data.",
    )
    args = parser.parse_args()

    selected_sources = (
        available_sources if args.source == "all" else [args.source]
    )
    session = build_session(
        maximum_retries=int(settings["maximum_retries"]),
        retry_backoff_seconds=float(settings["retry_backoff_seconds"]),
    )

    print("Chicago raw-data acquisition")
    print("=" * 75)
    print(
        "Historical window:",
        settings["history_start"],
        "to",
        settings["history_end_exclusive"],
    )
    print("=" * 75)

    if args.count_only:
        for source_name in selected_sources:
            row_count = count_only(
                source_name=source_name,
                source_catalog=source_catalog,
                acquisition_config=acquisition_config,
                session=session,
            )
            print(f"{source_name}: {row_count:,} rows")

        print("=" * 75)
        print("Count-only check: PASS")
        return 0

    run_id = create_run_id()

    for source_name in selected_sources:
        try:
            download_source(
                source_name=source_name,
                source_catalog=source_catalog,
                acquisition_config=acquisition_config,
                session=session,
                run_id=run_id,
            )
        except Exception as error:
            print(
                "Source acquisition status: FAIL\n"
                f"{type(error).__name__}: {error}",
                file=sys.stderr,
            )
            return 1

    print("=" * 75)
    print("Requested acquisitions completed successfully")
    return 0


if __name__ == "__main__":
    sys.exit(main())