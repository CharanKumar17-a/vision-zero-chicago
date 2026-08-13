# Chicago Road Safety Investment Prioritizer

### Vision Zero Chicago — Road Safety Investment Decision Support

> A data-driven decision-support tool aligned with the City of Chicago's Vision Zero goals.
> Final project selection authority remains with City staff and qualified transportation-engineering teams.

## Project Purpose

Chicago has a limited road-safety budget and cannot fund every high-crash
corridor.

This project:

1. Forecasts where future crash burden is likely to be highest across the 43 official high-crash corridors.
2. Evaluates which road-safety treatment could deliver the greatest benefit for each corridor.
3. Recommends a combination of projects within a selected planning budget and equity spending requirement.
4. Produces a transparent, reproducible shortlist for City and engineering review.

The system supports decision-making. It does not automatically approve projects.
Final project selection remains with the City and qualified transportation-engineering teams.

## Business Decision

Which combination of corridor-level road-safety projects should be shortlisted
for engineering review under a limited budget and an equity requirement?

## Analytical Workflow

1. Verify and freeze source data.
2. Clean crash and supporting datasets.
3. Assign crashes to candidate corridors.
4. Create a balanced corridor-month panel.
5. Validate data quality and spatial assignments.
6. Engineer time-safe predictive features.
7. Train and evaluate count-forecasting models.
8. Produce a 12-month corridor crash forecast.
9. Estimate treatment safety and economic benefits using documented CMFs and crash costs.
10. Optimize the project portfolio under budget and equity constraints (MILP).
11. Publish results through Power BI and Streamlit.
12. Preserve the final decision record for City and engineering review.

## Expected Dataset Sizes

| Dataset | Expected grain | Expected rows |
|---|---|---:|
| Historical panel | 43 corridors × 96 months | 4,128 |
| Production forecast | 43 corridors × 12 months | 516 |

These counts are validation targets. They must be revised if the verified source
data changes the project boundary.

## Planning Scenarios

| Budget | Equity floor | Uncertainty |
|---|---|---|
| $15M / $25M / $40M | 20% / 30% / 40% equity spend | Conservative / Base / Optimistic CMF |

Scenarios are planning tools. They are not official City of Chicago budget commitments.

## Main Tools

- Python
- pandas and NumPy
- GeoPandas and Shapely
- scikit-learn
- statsmodels
- SciPy (MILP portfolio optimization)
- pytest
- DuckDB
- Power BI
- Streamlit
- GitHub Actions (Automation)
- Git and GitHub

## Repository Structure

- `config/` — project settings and modeling parameters
- `data/raw/` — immutable source extracts (never modified)
- `data/interim/` — intermediate transformations
- `data/processed/` — validated analytical datasets
- `docs/` — decision log, assumptions, evidence and quality reports
- `notebooks/` — reproducible exploratory analysis
- `src/` — production Python code
- `tests/` — automated validation suite
- `outputs/` — generated tables, forecasts, figures and logs
- `dashboard/` — Power BI and Streamlit decision-support interface
- `automation/` — pipeline scheduling and refresh scripts
- `reports/` — final technical and stakeholder reports

## Data Sources

| Source | Provider | Use |
|---|---|---|
| Traffic Crashes — Crashes | City of Chicago Data Portal | Primary crash records |
| Traffic Crashes — Vehicles | City of Chicago Data Portal | Unit-level crash detail |
| Traffic Crashes — People | City of Chicago Data Portal | Person-level injury classification |
| Street Center Lines | City of Chicago Data Portal | Corridor geometry |
| CDC/ATSDR Social Vulnerability Index 2022 | CDC/ATSDR | Equity area designation |
| FHWA Crash Modification Factors | Federal Highway Administration | Treatment effectiveness evidence |
| FHWA Proven Safety Countermeasures | Federal Highway Administration | Treatment eligibility framework |

## Local Setup

Open PowerShell in the project directory:

```powershell
Set-Location "D:\data-analytics\vision-zero-chicago"
```