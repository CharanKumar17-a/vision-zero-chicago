# Vision Zero Chicago Road-Safety Investment Prioritization

## Project Purpose

Chicago has a limited road-safety budget and cannot fund every high-crash
corridor.

This project will:

1. Estimate where future recorded crash burden may be highest.
2. Estimate which applicable safety treatment could provide the greatest benefit
   for each corridor.
3. Recommend a combination of projects within a selected budget and equity
   requirement.
4. Produce a transparent shortlist for City and engineering review.

The system supports decision-making. Final project selection remains with the
City and qualified transportation-engineering teams.

## Business Decision

Which combination of corridor-level road-safety projects should be shortlisted
for engineering review under a limited budget and an equity requirement?

## Planned Analytical Workflow

1. Verify and freeze source data.
2. Clean crash and supporting datasets.
3. Assign crashes to candidate corridors.
4. Create a balanced corridor-month panel.
5. Validate data quality and spatial assignments.
6. Engineer time-safe predictive features.
7. Train and evaluate count-forecasting models.
8. Produce a 12-month corridor crash forecast.
9. Estimate treatment safety and economic benefits.
10. Optimize the project portfolio under budget and equity constraints.
11. Publish results through Power BI and Streamlit.
12. Preserve the final decision for City and engineering review.

## Expected Dataset Sizes

| Dataset | Expected grain | Expected rows |
|---|---|---:|
| Historical panel | 43 corridors × 96 months | 4,128 |
| Production forecast | 43 corridors × 12 months | 516 |

These counts are validation targets. They must be revised if the verified source
data changes the project boundary.

## Main Tools

- Python
- pandas and NumPy
- GeoPandas and Shapely
- scikit-learn
- statsmodels
- SciPy
- pytest
- Power BI
- Streamlit
- n8n
- Git and GitHub

## Repository Structure

- `config/` — project settings
- `data/raw/` — immutable source extracts
- `data/interim/` — intermediate transformations
- `data/processed/` — validated analytical datasets
- `docs/` — decisions, assumptions, evidence and quality reports
- `notebooks/` — reproducible exploration
- `src/` — production Python code
- `tests/` — automated validation
- `outputs/` — generated tables, forecasts, figures and logs
- `dashboard/` — Power BI and Streamlit work
- `automation/` — n8n workflow definitions
- `reports/` — final technical and stakeholder reports

## Local Setup

Open PowerShell in the project directory:

```powershell
Set-Location "D:\data-analytics\vision-zero-chicago"