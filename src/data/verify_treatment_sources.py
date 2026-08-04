from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


ROOT = Path(__file__).resolve().parents[2]

REPORT_PATH = (
    ROOT
    / "docs"
    / "data_quality"
    / "treatment_source_verification.json"
)

COUNTERMEASURE_BOOKLET_URL = (
    "https://highways.dot.gov/sites/fhwa.dot.gov/files/"
    "Proven%20Safety%20Countermeasures%20Booklet.pdf"
)

STEP_STUDIO_URL = (
    "https://highways.dot.gov/sites/fhwa.dot.gov/files/"
    "2022-06/step_studio.pdf"
)

CMF_FACT_SHEET_URL = (
    "https://highways.dot.gov/media/14286"
)

CMF_INFORMATION_PAGE_URL = (
    "https://highways.dot.gov/safety/data-analysis-tools/"
    "rsdp/rsdp-tools/cmf-clearinghouse"
)

COUNTERMEASURE_PAGE_URL = (
    "https://highways.dot.gov/safety/"
    "proven-safety-countermeasures"
)

DIRECT_CMF_URL = (
    "https://cmfclearinghouse.fhwa.dot.gov/"
)

REQUEST_TIMEOUT_SECONDS = 120

HEADERS = {
    "User-Agent": (
        "Vision-Zero-Chicago-Capstone/"
        "1.0 treatment-source-verification"
    )
}

SEPARATOR = "-" * 75


def save_report(
    report: dict[str, Any],
) -> None:
    """Save treatment-source verification evidence."""

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


def verify_required_pdf(
    session: requests.Session,
    *,
    source_name: str,
    url: str,
) -> dict[str, Any]:
    """Verify a required official PDF source."""

    try:
        response = session.get(
            url,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

        response.raise_for_status()

        pdf_signature_present = (
            response.content.startswith(b"%PDF")
        )

        status = (
            "PASS"
            if (
                response.status_code == 200
                and pdf_signature_present
                and len(response.content) > 0
            )
            else "FAIL"
        )

        return {
            "source_name": source_name,
            "url": url,
            "status_code": response.status_code,
            "content_type": response.headers.get(
                "Content-Type",
                "",
            ),
            "content_length_bytes": len(response.content),
            "pdf_signature_present": (
                pdf_signature_present
            ),
            "status": status,
        }

    except requests.RequestException as error:
        return {
            "source_name": source_name,
            "url": url,
            "status": "FAIL",
            "error_type": type(error).__name__,
            "error": str(error),
        }


def check_optional_source(
    session: requests.Session,
    *,
    source_name: str,
    url: str,
) -> dict[str, Any]:
    """
    Check an optional source without allowing access restrictions
    to control the overall verification result.
    """

    try:
        response = session.get(
            url,
            timeout=30,
        )

        if response.status_code == 200:
            status = "AVAILABLE"
        elif response.status_code in {401, 403}:
            status = "AUTOMATED_ACCESS_BLOCKED"
        else:
            status = "UNAVAILABLE_OPTIONAL"

        return {
            "source_name": source_name,
            "url": url,
            "status_code": response.status_code,
            "content_type": response.headers.get(
                "Content-Type",
                "",
            ),
            "status": status,
        }

    except requests.exceptions.SSLError as error:
        return {
            "source_name": source_name,
            "url": url,
            "status": "SSL_VALIDATION_FAILED_OPTIONAL",
            "error_type": type(error).__name__,
            "error": str(error),
        }

    except requests.RequestException as error:
        return {
            "source_name": source_name,
            "url": url,
            "status": "UNAVAILABLE_OPTIONAL",
            "error_type": type(error).__name__,
            "error": str(error),
        }


def main() -> int:
    print("Road-safety treatment-source verification")
    print(SEPARATOR)

    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        # --------------------------------------------------------
        # Required evidence sources
        # --------------------------------------------------------

        countermeasure_booklet = (
            verify_required_pdf(
                session,
                source_name=(
                    "FHWA Proven Safety Countermeasures booklet"
                ),
                url=COUNTERMEASURE_BOOKLET_URL,
            )
        )

        step_studio = verify_required_pdf(
            session,
            source_name=(
                "FHWA STEP Studio treatment and cost guide"
            ),
            url=STEP_STUDIO_URL,
        )

        # --------------------------------------------------------
        # Optional access checks
        # --------------------------------------------------------

        cmf_fact_sheet = check_optional_source(
            session,
            source_name=(
                "FHWA Crash Modification Factors fact sheet"
            ),
            url=CMF_FACT_SHEET_URL,
        )

        cmf_information_page = (
            check_optional_source(
                session,
                source_name=(
                    "FHWA CMF Clearinghouse information page"
                ),
                url=CMF_INFORMATION_PAGE_URL,
            )
        )

        countermeasure_page = (
            check_optional_source(
                session,
                source_name=(
                    "FHWA Proven Safety Countermeasures page"
                ),
                url=COUNTERMEASURE_PAGE_URL,
            )
        )

        direct_cmf_site = check_optional_source(
            session,
            source_name="Direct CMF Clearinghouse",
            url=DIRECT_CMF_URL,
        )

        required_sources = {
            "proven_countermeasure_booklet": (
                countermeasure_booklet
            ),
            "step_studio": step_studio,
        }

        overall_status = (
            "PASS"
            if all(
                result["status"] == "PASS"
                for result
                in required_sources.values()
            )
            else "FAIL"
        )

        # --------------------------------------------------------
        # Save the audit report
        # --------------------------------------------------------

        report = {
            "verification_name": (
                "Road-safety treatment-source verification"
            ),
            "checked_at_utc": (
                datetime.now(timezone.utc)
                .replace(microsecond=0)
                .isoformat()
            ),
            "required_sources": required_sources,
            "optional_access_checks": {
                "cmf_fact_sheet": cmf_fact_sheet,
                "cmf_information_page": (
                    cmf_information_page
                ),
                "countermeasure_page": (
                    countermeasure_page
                ),
                "direct_cmf_clearinghouse": (
                    direct_cmf_site
                ),
            },
            "verified_scope": {
                "treatment_effect_framework": (
                    "Official FHWA countermeasure evidence "
                    "with cited CMF IDs"
                ),
                "planning_cost_framework": (
                    "Official FHWA STEP Studio planning "
                    "cost references"
                ),
            },
            "limitations": [
                (
                    "Individual production CMFs have not yet "
                    "been selected or validated."
                ),
                (
                    "Blocked or certificate-failing websites "
                    "were not treated as successful checks."
                ),
                (
                    "National planning costs require scenario "
                    "ranges and are not Chicago engineering "
                    "estimates."
                ),
                (
                    "Treatment applicability requires "
                    "engineering review."
                ),
            ],
            "overall_status": overall_status,
        }

        save_report(report)

        # --------------------------------------------------------
        # Display results
        # --------------------------------------------------------

        print(
            "FHWA countermeasure booklet PDF: "
            f"{countermeasure_booklet['status']}"
        )

        print(
            "FHWA STEP Studio PDF: "
            f"{step_studio['status']}"
        )

        print(
            "FHWA CMF fact sheet: "
            f"{cmf_fact_sheet['status']}"
        )

        print(
            "FHWA CMF HTML page: "
            f"{cmf_information_page['status']}"
        )

        print(
            "FHWA countermeasure HTML page: "
            f"{countermeasure_page['status']}"
        )

        print(
            "Direct CMF Clearinghouse: "
            f"{direct_cmf_site['status']}"
        )

        print(SEPARATOR)

        print(
            "Overall treatment-source status: "
            f"{overall_status}"
        )

        print(f"Report saved to: {REPORT_PATH}")

        return 0 if overall_status == "PASS" else 1

    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())