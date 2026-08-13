# Vision Zero Chicago — Road-Safety Investment Prioritization
**Version:** 1.0 · **Date:** 2026-08-13
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

Headline (BASE): .84B total present-value safety benefit on .38M
provisional capital cost across 129 corridor-treatment candidates; portfolio
average BCR ≈ 336:1 (individual up to 1,365 — planning-level, not expected
returns); 41.9% of spend lands in equity-priority corridors automatically.

Critical finding: all 43 corridors can be treated for ≈ .7–9.3M (BASE–
CONSERVATIVE), below every official budget (//). Official budgets
are NONBINDING; all 27 official runs select all 43 corridors. Real trade-offs
appear in the analyst-defined binding stress scenarios (//).

## 2. Business Problem
Decision question: which combination of corridor-level road-safety projects
should be shortlisted for engineering review under a limited capital budget
and an equity-spending requirement? Constraints modeled: budget ceiling,
equity floor, at most one treatment per corridor. Responsible-use boundary:
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
Treatments: TRT_001 Refuge Islands, TRT_002 Road Diet, TRT_004 RRFB. CMFs
from FHWA CMF Clearinghouse; USDOT/FHWA comprehensive crash costs; 3.0% real
discount; 20-year useful life; severity-specific K/A/B/C/O/U shares.
BASE totals (committed): PV benefit .84B; capital cost .38M; avg BCR
335.9; max individual BCR 1,365.4. 53 rows exceed BCR 1,000 (BASE/OPTIMISTIC)
- planning-level artifacts, not expected returns. Physical applicability
UNKNOWN (no lane counts/median widths/crossing inventories); field review
required. 100% of selected projects are Road Diet (TRT_002); TRT_001/004 never
selected - flagged for treatment-diversity diagnostic.

## 7. Portfolio Optimization
MILP (scipy.optimize.milp); objective = maximize total present-value benefit;
constraints = budget ceiling, equity floor, at most 1 treatment/corridor,
at least 1 project; repeat-solve determinism verified (3x identical). 36 runs
= 27 official (// x 20/30/40% x 3 uncertainty) + 9 binding stress
(//). Outputs: 36 summary rows; 1,410 selection rows; exact
summary-to-detail reconciliation; exact lineage; all OPTIMAL.
Verified tier structure (BASE stress): 14 core corridors at  (BCR >= 850;
equity share 56.1%), 29 at  (57.8%), 40 at  (43.0%); 3 high-budget-only
corridors (Broadway, Western, Clark; BCRs 379-442) above  to the .31M
all-43 ceiling. Equity floors never bind (achieved 43-58% > all floors)
because high-BCR corridors naturally overlap high-SVI areas.
Honest limitations: official budgets nonbinding (all-43, 1 hash); equity
floors nonbinding; 100% Road-Diet concentration; BCR >= 1.0 eligibility filter
not applied (documented); stress budgets are analyst-defined, not City budgets.

## 8. Validation and Governance
297 tests passed (full pytest -q), 0 Git side effects; 11-gate verifier PASS.
Committed validation reports (PASS/PASS_WITH_WARNINGS, run IDs): crash core
20260809T162130Z; register 20260810T103635Z; geometry 20260810T120855Z;
treatment benefits 20260812T082144Z; optimization 20260812T104902Z;
decision mart 20260812T111723Z. Deployment served from checksum-verified
snapshots; three data modes. Decision log and assumption register maintained.
Final authority: City staff and engineering teams.

## 9. Known Limitations
1. Official budgets nonbinding - official scenarios all identical; binding
   behavior only in stress runs.
2. Physical applicability UNKNOWN (no lane counts/median widths/crossing
   inventories); engineering field survey required.
3. 100% Road Diet selections; TRT_001/004 not selected (diagnostic pending).
4. Extreme BCRs are planning-level artifacts; not expected returns.
5. Equity uses CDC/ATSDR SVI as project-defined planning proxy, not Chicago's
   official equity rule.
6. Forecasts are of recorded crash burden; no exposure (traffic volume) data.
7. BCR < 1.0 eligibility exclusion not applied in the optimizer.
8. 2026 outputs are a retrospective planning simulation; not observed 2026.

## 10. Sources of Every Number
All figures trace to committed files under docs/data_quality/ (run IDs above),
data/processed/*.parquet, notebooks/01,02,03,05, and python -m pytest -q
(297 passed, 2026-08-13).
