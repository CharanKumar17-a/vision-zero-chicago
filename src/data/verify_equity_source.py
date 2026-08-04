from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

import pandas as pd
import requests


ROOT = Path(__file__).resolve().parents[2]

REPORT_PATH = (
    ROOT
    / "docs"
    / "data_quality"
    / "equity_source_verification.json"
)

DOWNLOAD_PAGE_URL = (
    "https://www.atsdr.cdc.gov/place-health/php/"
    "svi/svi-data-documentation-download.html"
)

DOCUMENTATION_URL = (
    "https://www.atsdr.cdc.gov/place-health/media/"
    "pdfs/2024/10/SVI2022Documentation.pdf"
)

CSV_URL = (
    "https://svi2.cdc.gov/webapi/Documents/download"
    "?year=2022&type=csv&category=states&name=ILLINOIS"
)

GEODATABASE_URL = (
    "https://svi2.cdc.gov/webapi/Documents/download"
    "?year=2022&type=db&category=states&name=ILLINOIS"
)

REQUEST_TIMEOUT_SECONDS = 120

HEADERS = {
    "User-Agent": (
        "Vision-Zero-Chicago-Capstone/"
        "1.0 equity-source-verification"
    )
}

REQUIRED_FIELDS = [
    "ST",
    "STATE",
    "ST_ABBR",
    "STCNTY",
    "COUNTY",
    "FIPS",
    "LOCATION",
    "E_TOTPOP",
    "RPL_THEME1",
    "RPL_THEME2",
    "RPL_THEME3",
    "RPL_THEME4",
    "RPL_THEMES",
]

SEPARATOR = "-" * 75


def save_report(report: dict) -> None:
    """Save the verification result as JSON."""

    REPORT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with REPORT_PATH.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            report,
            file,
            indent=2,
            ensure_ascii=False,
        )


def verify_geodatabase_download(
    session: requests.Session,
) -> dict:
    """Confirm that the spatial download is a ZIP package."""

    with session.get(
        GEODATABASE_URL,
        timeout=REQUEST_TIMEOUT_SECONDS,
        stream=True,
    ) as response:
        response.raise_for_status()

        first_chunk = next(
            response.iter_content(chunk_size=1024),
            b"",
        )

        zip_signature_present = first_chunk.startswith(b"PK")

        return {
            "status_code": response.status_code,
            "content_type": response.headers.get(
                "Content-Type",
                "",
            ),
            "content_disposition": response.headers.get(
                "Content-Disposition",
                "",
            ),
            "zip_signature_present": zip_signature_present,
            "status": (
                "PASS"
                if (
                    response.status_code == 200
                    and zip_signature_present
                )
                else "FAIL"
            ),
        }


def main() -> int:
    print("CDC/ATSDR SVI 2022 equity-source verification")
    print(SEPARATOR)

    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        # --------------------------------------------------------
        # 1. Verify the official download page
        # --------------------------------------------------------

        page_response = session.get(
            DOWNLOAD_PAGE_URL,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

        page_response.raise_for_status()

        page_status = (
            "PASS"
            if (
                page_response.status_code == 200
                and "Social Vulnerability Index"
                in page_response.text
            )
            else "FAIL"
        )

        # --------------------------------------------------------
        # 2. Verify the official documentation PDF
        # --------------------------------------------------------

        documentation_response = session.get(
            DOCUMENTATION_URL,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

        documentation_response.raise_for_status()

        pdf_signature_present = (
            documentation_response.content.startswith(b"%PDF")
        )

        documentation_status = (
            "PASS"
            if (
                documentation_response.status_code == 200
                and pdf_signature_present
            )
            else "FAIL"
        )

        # --------------------------------------------------------
        # 3. Download and inspect the Illinois SVI CSV
        # --------------------------------------------------------

        csv_response = session.get(
            CSV_URL,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

        csv_response.raise_for_status()

        svi_df = pd.read_csv(
            BytesIO(csv_response.content),
            encoding="utf-8-sig",
            dtype={
                "FIPS": "string",
                "STCNTY": "string",
            },
            low_memory=False,
        )

        available_fields = list(svi_df.columns)

        missing_fields = sorted(
            set(REQUIRED_FIELDS) - set(available_fields)
        )

        required_fields_status = (
            "PASS"
            if not missing_fields
            else "FAIL"
        )

        if missing_fields:
            raise ValueError(
                f"Required SVI fields are missing: {missing_fields}"
            )

        # --------------------------------------------------------
        # 4. Validate state, tract identifiers, and Cook County
        # --------------------------------------------------------

        state_values = sorted(
            svi_df["ST_ABBR"]
            .dropna()
            .astype(str)
            .unique()
            .tolist()
        )

        state_status = (
            "PASS"
            if state_values == ["IL"]
            else "FAIL"
        )

        fips_values = (
            svi_df["FIPS"]
            .astype("string")
            .str.strip()
        )

        missing_fips_count = int(
            (
                fips_values.isna()
                | fips_values.eq("")
            ).sum()
        )

        duplicate_fips_count = int(
            fips_values.duplicated().sum()
        )

        cook_df = svi_df.loc[
            svi_df["COUNTY"].eq("Cook County")
        ].copy()

        cook_county_tract_rows = len(cook_df)

        cook_rpl_themes = pd.to_numeric(
            cook_df["RPL_THEMES"],
            errors="coerce",
        )

        cook_population = pd.to_numeric(
            cook_df["E_TOTPOP"],
            errors="coerce",
        )

        valid_rank_mask = cook_rpl_themes.between(
            0,
            1,
            inclusive="both",
        )

        # CDC uses -999 for unavailable or unranked values.
        # These three Cook County cases have zero population.
        documented_no_data_mask = (
            cook_rpl_themes.eq(-999)
            & cook_population.eq(0)
        )

        unexpected_invalid_mask = ~(
            valid_rank_mask
            | documented_no_data_mask
        )

        documented_zero_population_count = int(
            documented_no_data_mask.sum()
        )

        unexpected_invalid_rank_count = int(
            unexpected_invalid_mask.sum()
        )

        populated_tract_mask = cook_population.gt(0)

        populated_cook_tract_rows = int(
            populated_tract_mask.sum()
        )

        valid_populated_rank_count = int(
            (
                populated_tract_mask
                & valid_rank_mask
            ).sum()
        )

        populated_rank_coverage_percent = (
            valid_populated_rank_count
            / populated_cook_tract_rows
            * 100
            if populated_cook_tract_rows > 0
            else 0
        )

        data_quality_status = (
            "PASS"
            if (
                len(svi_df) > 0
                and state_status == "PASS"
                and missing_fips_count == 0
                and duplicate_fips_count == 0
                and cook_county_tract_rows > 0
                and unexpected_invalid_rank_count == 0
                and valid_populated_rank_count
                == populated_cook_tract_rows
            )
            else "FAIL"
        )

        # --------------------------------------------------------
        # 5. Verify availability of the spatial package
        # --------------------------------------------------------

        geodatabase_result = (
            verify_geodatabase_download(session)
        )

        overall_status = (
            "PASS"
            if (
                page_status == "PASS"
                and documentation_status == "PASS"
                and required_fields_status == "PASS"
                and data_quality_status == "PASS"
                and geodatabase_result["status"] == "PASS"
            )
            else "FAIL"
        )

        # --------------------------------------------------------
        # 6. Save the audit report
        # --------------------------------------------------------

        report = {
            "verification_name": (
                "CDC/ATSDR SVI 2022 equity-source verification"
            ),
            "checked_at_utc": (
                datetime.now(timezone.utc)
                .replace(microsecond=0)
                .isoformat()
            ),
            "source_year": 2022,
            "geography": "Illinois census tracts",
            "intended_project_use": (
                "Project-defined corridor equity constraint"
            ),
            "download_page": {
                "url": DOWNLOAD_PAGE_URL,
                "status_code": page_response.status_code,
                "status": page_status,
            },
            "documentation": {
                "url": DOCUMENTATION_URL,
                "status_code": (
                    documentation_response.status_code
                ),
                "pdf_signature_present": (
                    pdf_signature_present
                ),
                "status": documentation_status,
            },
            "csv_source": {
                "url": CSV_URL,
                "status_code": csv_response.status_code,
                "content_type": csv_response.headers.get(
                    "Content-Type",
                    "",
                ),
                "row_count": len(svi_df),
                "column_count": len(svi_df.columns),
                "state_values": state_values,
                "cook_county_tract_rows": (
                    cook_county_tract_rows
                ),
                "populated_cook_tract_rows": (
                    populated_cook_tract_rows
                ),
                "missing_fips_count": missing_fips_count,
                "duplicate_fips_count": (
                    duplicate_fips_count
                ),
                "documented_zero_population_unranked_count": (
                    documented_zero_population_count
                ),
                "unexpected_invalid_cook_rpl_themes_count": (
                    unexpected_invalid_rank_count
                ),
                "valid_populated_rank_coverage_percent": round(
                    populated_rank_coverage_percent,
                    4,
                ),
                "required_fields": REQUIRED_FIELDS,
                "missing_fields": missing_fields,
                "required_fields_status": (
                    required_fields_status
                ),
                "data_quality_status": (
                    data_quality_status
                ),
            },
            "geodatabase_source": {
                "url": GEODATABASE_URL,
                **geodatabase_result,
            },
            "overall_status": overall_status,
        }

        save_report(report)

        # --------------------------------------------------------
        # 7. Display results
        # --------------------------------------------------------

        print(f"Download page status: {page_status}")

        print(
            "Documentation PDF status: "
            f"{documentation_status}"
        )

        print(
            "Required fields status: "
            f"{required_fields_status}"
        )

        print(f"Missing fields: {missing_fields}")
        print(f"Illinois tract rows: {len(svi_df)}")
        print(f"Available fields: {len(svi_df.columns)}")

        print(
            "Cook County tract rows: "
            f"{cook_county_tract_rows}"
        )

        print(
            "Populated Cook County tract rows: "
            f"{populated_cook_tract_rows}"
        )

        print(
            "Missing FIPS values: "
            f"{missing_fips_count}"
        )

        print(
            "Duplicate FIPS values: "
            f"{duplicate_fips_count}"
        )

        print(
            "Documented zero-population unranked tracts: "
            f"{documented_zero_population_count}"
        )

        print(
            "Unexpected invalid Cook County ranks: "
            f"{unexpected_invalid_rank_count}"
        )

        print(
            "Populated-tract SVI rank coverage: "
            f"{populated_rank_coverage_percent:.2f}%"
        )

        print(
            "Geodatabase package status: "
            f"{geodatabase_result['status']}"
        )

        print(SEPARATOR)

        print(
            "Overall equity-source status: "
            f"{overall_status}"
        )

        print(f"Report saved to: {REPORT_PATH}")

        return 0 if overall_status == "PASS" else 1

    except (
        requests.RequestException,
        pd.errors.ParserError,
        ValueError,
        KeyError,
    ) as error:
        failure_report = {
            "verification_name": (
                "CDC/ATSDR SVI 2022 equity-source verification"
            ),
            "checked_at_utc": (
                datetime.now(timezone.utc)
                .replace(microsecond=0)
                .isoformat()
            ),
            "overall_status": "FAIL",
            "error_type": type(error).__name__,
            "error": str(error),
        }

        save_report(failure_report)

        print("Overall equity-source status: FAIL")
        print(f"Error type: {type(error).__name__}")
        print(f"Error: {error}")
        print(f"Failure report saved to: {REPORT_PATH}")

        return 1

    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())