from __future__ import annotations

import requests


USER_AGENT = "vision-zero-chicago-capstone/0.1"

CORRIDOR_PLAN_URL = (
    "https://www.chicago.gov/content/dam/city/"
    "sites/complete-streets/pdfs/"
    "06-28-18%20VZ_HCC_FrameworkPlan_reduced%20size.pdf"
)

STREET_METADATA_URL = (
    "https://data.cityofchicago.org/"
    "api/views/6imu-meau"
)

STREET_GEOJSON_URL = (
    "https://data.cityofchicago.org/"
    "api/geospatial/6imu-meau"
    "?method=export&format=GeoJSON"
)


def verify_corridor_plan() -> bool:
    response = requests.get(
        CORRIDOR_PLAN_URL,
        headers={"User-Agent": USER_AGENT},
        stream=True,
        timeout=60,
    )

    print("High Crash Corridors Framework Plan")
    print(f"Status code: {response.status_code}")
    print(
        "Content type: "
        f"{response.headers.get('Content-Type')}"
    )

    if response.status_code != 200:
        print("Plan verification: FAIL")
        return False

    first_bytes = next(
        response.iter_content(chunk_size=8),
        b"",
    )

    is_pdf = first_bytes.startswith(b"%PDF")

    print(f"PDF signature present: {is_pdf}")
    print(
        "Plan verification: "
        f"{'PASS' if is_pdf else 'FAIL'}"
    )

    response.close()

    return is_pdf


def verify_street_metadata() -> bool:
    response = requests.get(
        STREET_METADATA_URL,
        headers={"User-Agent": USER_AGENT},
        timeout=60,
    )

    print("Street Center Lines metadata")
    print(f"Status code: {response.status_code}")

    if response.status_code != 200:
        print("Metadata verification: FAIL")
        return False

    metadata = response.json()

    print(f"Dataset name: {metadata.get('name')}")
    print(f"Dataset ID: {metadata.get('id')}")
    print(f"Attribution: {metadata.get('attribution')}")

    passed = (
        metadata.get("id") == "6imu-meau"
        and metadata.get("name") == "Street Center Lines"
    )

    print(
        "Metadata verification: "
        f"{'PASS' if passed else 'FAIL'}"
    )

    return passed


def verify_street_export() -> bool:
    response = requests.get(
        STREET_GEOJSON_URL,
        headers={"User-Agent": USER_AGENT},
        stream=True,
        timeout=120,
    )

    print("Street Center Lines GeoJSON export")
    print(f"Status code: {response.status_code}")
    print(
        "Content type: "
        f"{response.headers.get('Content-Type')}"
    )

    if response.status_code != 200:
        print("GeoJSON export verification: FAIL")
        return False

    first_bytes = next(
        response.iter_content(chunk_size=20),
        b"",
    )

    looks_like_json = first_bytes.lstrip().startswith(
        (b"{", b"[")
    )

    print(f"JSON signature present: {looks_like_json}")
    print(
        "GeoJSON export verification: "
        f"{'PASS' if looks_like_json else 'FAIL'}"
    )

    response.close()

    return looks_like_json


def main() -> None:
    print("Corridor source verification")
    print("=" * 70)

    plan_passed = verify_corridor_plan()

    print("-" * 70)

    metadata_passed = verify_street_metadata()

    print("-" * 70)

    export_passed = verify_street_export()

    print("=" * 70)

    all_passed = (
        plan_passed
        and metadata_passed
        and export_passed
    )

    print(
        "Overall corridor-source status: "
        f"{'PASS' if all_passed else 'REVIEW REQUIRED'}"
    )

    if not all_passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()