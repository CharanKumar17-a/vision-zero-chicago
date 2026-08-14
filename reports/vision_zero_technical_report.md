# Vision Zero Chicago — Road-Safety Investment Prioritization
**Version:** 1.1 · **Date:** 2026-08-13
**Scope:** Independent capstone analysis aligned with the City of Chicago's
Vision Zero framework. Not an official City product; does not approve or
program projects. Final authority remains with City staff and engineering teams.

## 1. Executive Summary
Chicago cannot fund every high-crash corridor at once. This project builds a
transparent decision-support system that (1) forecasts where future recorded
crash burden is likely highest across the 43 official high-crash corridors,
(2) estimates safety benefits of applicable treatments using FHWA CMFs,
(3) optimizes a project portfolio under budget and equity constraints, and
(4) presents results in a deployed app with explicit governance reporting.

Headline (BASE): $5.84B total present-value safety benefit on $26.75M
sourced capital cost across 387 corridor-treatment candidates; portfolio
average BCR ≈ 218:1; 47.4% of spend lands in equity-priority corridors automatically.

Critical finding: under sourced planning-level unit costs ($400k/mi Road Diet,
$15k/island Refuge Island, $22.5k RRFB), full network treatment cost rises to
$20.11M ($19.93M–$21.26M across scenarios). Consequently, the official **$15M
planning budget is strictly BINDING** ($14.99M cost, selecting 34 projects in
BASE scenario). Physical applicability screening (disqualifying Road Diets on
divided carriageways like Lake Shore Drive HCC019) causes the solver to select
Refuge Islands (`TRT_001`) for HCC019, introducing multi-treatment diversity.

## 2. Business Problem
Decision question: which combination of corridor-level road-safety projects
should be shortlisted for engineering review under a limited capital budget
and an equity-spending requirement? Constraints modeled: budget ceiling,
equity floor, at most one treatment per corridor, physical applicability screening,
and candidate BCR >= 1.0 eligibility filter (D023). Responsible-use boundary:
decision support only; does not replace engineering feasibility, community
input, legal review, or final capital-program authority.

## 3. Data Foundation (verified)
- Clean crash core: 877,919 rows; 0 missing/dup keys; 0 invalid dates;
  valid-coordinate coverage 99.19% (7,150 invalid, preserved).
- Spatially eligible crashes: 870,769.
- Corridor register: 43 corridors (HCC001–HCC043).
- Corridor geometry: 43 valid geometries, EPSG:3435; 3 governed exceptions
  (Lake Shore Drive, Fairbanks, Wacker); 42 LineString + 1 MultiLineString.
- Street centerlines: 56,338 features; 99.996% valid coverage.

## 4. Crash-to-Corridor Assignment
100-ft threshold (internal modeling decision, not City policy). 114,224 unique
crashes matched (13.1%); 8,132 multiple-candidate; 1,803 ties at 10-ft
(excluded as unresolved_tie). Valid coordinates required; nearest candidate is
primary; at most one primary corridor per crash; unmatched/invalid preserved
and reported; no double-counting. Sensitivity rationale: 50 ft too restrictive
(104,750 matched); 100 ft adds 9,474 with modest ambiguity rise (5.5% to 7.1%);
quality deteriorates beyond 100 ft.

## 5. Panel, Features, Forecasting
4,128-row corridor-month panel (43 x 96 months, 2018-2025); zero-filled;
no partial 2026 in modeling. Time-safe split: 2018 warm-up / 2019-23 train /
2024 val / 2025 test; chronological only; leakage audit clean.
Production forecast: 516 corridor-month 2026 predictions (43 x 12) with
Beta-Binomial shrinkage and Empirical-Bayes KSI calibration.
Selected production models: total_crashes = 12-month rolling-mean benchmark
(selected on 2024 validation deviance over Poisson/NegBin GLMs - reported
honestly, not overstated as ML forecast); ksi_crashes = Negative Binomial GLM
+ EB calibration. Feature importance (KSI): total-crash lags/roll means
dominate over sparse KSI lags (KSI 61.6% zero-month); month_cos most
significant (p=0.0046).
EDA (notebook 01): 112,421 total / 2,297 KSI crashes; July peak; top-3
corridors Lake Shore Drive 7,702 / Michigan 6,449 / Fullerton 6,014 (~18%);
top-15 = 57.1%; severity mix O 82.8 / B 9.7 / C 5.5 / A 1.9 / K 0.12%.
Trends (notebook 02): 32 decreasing, 9 stable, 2 increasing (Chicago +10.9%,
Western +10.6%) vs CBD drops (LaSalle -55.9%, State -46.3%, Wacker -33.6%);
14 3-sigma anomaly months across 13 corridors.

## 6. Treatment Benefits and Economics
387 candidate rows (43 corridors x 3 treatments x 3 uncertainty scenarios).
Sourced unit costs (docs/evidence/treatment_unit_costs_2024.csv):
TRT_001 Refuge Islands ($15k/island, 2/mi density), TRT_002 Road Diet ($400k/mi),
TRT_004 RRFB ($22.5k/crossing). CMFs from FHWA CMF Clearinghouse; USDOT/FHWA
comprehensive crash costs; 3.0% real discount; 20-year useful life; severity-specific K/A/B/C/O/U shares.
BASE totals (committed): PV benefit $5.84B; capital cost $26.75M; avg BCR
218:1. Candidate BCR >= 1.0 eligibility filter applied (D023). Physical applicability
screening marks TRT_002 NOT_APPLICABLE on divided carriageway MultiLineString
corridor HCC019 (Lake Shore Drive) (D024).

## 7. Portfolio Optimization
MILP (scipy.optimize.milp); objective = maximize total present-value benefit;
constraints = budget ceiling, equity floor, candidate BCR >= 1.0 eligibility, physical applicability,
at most 1 treatment/corridor, at least 1 project; repeat-solve determinism verified (3x identical).
36 runs = 27 official ($15M/$25M/$40M x 20/30/40% x 3 uncertainty) + 9 binding stress
($2M/$4M/$6M). Outputs: 36 summary rows; 1,212 selection rows; exact
summary-to-detail reconciliation; exact lineage; all OPTIMAL.
Binding $15M official planning budget selects 34 projects in BASE scenario ($14.99M cost,
$11.1k slack), leaving 9 corridors unselected. $25M and $40M budget ceilings allow network coverage.
Equity floors never bind (achieved 43-58% > all floors) because high-BCR corridors
naturally overlap high-SVI areas. Selection diversity introduced via TRT_001 selection on HCC019.

## 8. Validation and Governance
300 tests passed (full pytest -q), 0 Git side effects; 14-gate verifier PASS.
Committed validation reports (PASS/PASS_WITH_WARNINGS): crash core, corridor register,
corridor geometry, treatment benefits, portfolio optimization, decision mart, Streamlit dashboard.
Deployment served from checksum-verified snapshots; three data modes. Decision log (D001–D024)
and assumption register maintained. Final authority: City staff and engineering teams.

## 9. Known Limitations
1. Sourced unit costs are planning-level estimates; actual construction costs
   depend on site-specific ROW, drainage, and utility work.
2. Physical applicability screening is active for divided carriageways (`HCC019`);
   detailed field engineering survey required prior to project programming.
3. Extreme BCRs are planning-level artifacts; not expected returns.
4. Equity uses CDC/ATSDR SVI as project-defined planning proxy, not Chicago's
   official equity rule.
5. Forecasts are of recorded crash burden; no exposure (traffic volume) data.
6. 2026 outputs are a retrospective planning simulation; not observed 2026.

## 10. Sources of Every Number
All figures trace to committed files under docs/data_quality/ (run IDs above),
data/processed/*.parquet, notebooks/01,02,03,05,08, and python -m pytest -q
(300 passed, 2026-08-14).
