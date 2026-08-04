from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import requests


PROJECT_ROOT = Path(__file__).resolve().parents[2]

API_URL = (
    "https://data.cityofchicago.org/"
    "resource/85ca-t3if.json"
)

OUTPUT_PATH = (
    PROJECT_ROOT
    / "docs"
    / "data_quality"
    / "crash_monthly_coverage.csv"
)


def fetch_monthly_coverage() -> pd.DataFrame:
    params = {
        "$select": (
            "date_extract_y(crash_date) as crash_year, "
            "date_extract_m(crash_date) as crash_month, "
            "count(*) as crash_count"
        ),
        "$where": "crash_date >= '2017-01-01T00:00:00.000'",
        "$group": (
            "date_extract_y(crash_date), "
            "date_extract_m(crash_date)"
        ),
        "$order": (
            "date_extract_y(crash_date), "
            "date_extract_m(crash_date)"
        ),
        "$limit": 500,
    }

    response = requests.get(
        API_URL,
        params=params,
        headers={"User-Agent": "vision-zero-chicago-capstone/0.1"},
        timeout=60,
    )

    response.raise_for_status()

    coverage = pd.DataFrame(response.json())

    if coverage.empty:
        raise ValueError("The API returned no monthly coverage records.")

    integer_columns = [
        "crash_year",
        "crash_month",
        "crash_count",
    ]

    coverage[integer_columns] = coverage[integer_columns].astype(int)

    coverage["period"] = pd.to_datetime(
        {
            "year": coverage["crash_year"],
            "month": coverage["crash_month"],
            "day": 1,
        }
    )

    return coverage.sort_values("period").reset_index(drop=True)


def summarize_annual_coverage(
    monthly_coverage: pd.DataFrame,
) -> pd.DataFrame:
    annual_coverage = (
        monthly_coverage.groupby("crash_year", as_index=False)
        .agg(
            months_present=("crash_month", "nunique"),
            total_crashes=("crash_count", "sum"),
            minimum_monthly_crashes=("crash_count", "min"),
            maximum_monthly_crashes=("crash_count", "max"),
        )
    )

    last_complete_year = date.today().year - 1

    annual_coverage["candidate_history_year"] = (
        (annual_coverage["crash_year"] >= 2018)
        & (annual_coverage["crash_year"] <= last_complete_year)
        & (annual_coverage["months_present"] == 12)
    )

    return annual_coverage


def main() -> None:
    monthly_coverage = fetch_monthly_coverage()
    annual_coverage = summarize_annual_coverage(monthly_coverage)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    monthly_coverage.to_csv(OUTPUT_PATH, index=False)

    candidate_history = monthly_coverage[
        monthly_coverage["crash_year"].between(
            2018,
            date.today().year - 1,
        )
    ]

    candidate_periods = candidate_history["period"].nunique()

    print("Crash coverage by year")
    print("-" * 90)
    print(annual_coverage.to_string(index=False))
    print("-" * 90)
    print(f"Candidate historical periods: {candidate_periods}")
    print(f"Expected historical periods: 96")
    print(f"Coverage file saved to: {OUTPUT_PATH}")

    if candidate_periods == 96:
        print("Historical coverage gate: PASS")
    else:
        print("Historical coverage gate: REVIEW REQUIRED")


if __name__ == "__main__":
    main()