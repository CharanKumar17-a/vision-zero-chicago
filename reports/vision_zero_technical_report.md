# Vision Zero Chicago — Road-Safety Investment Prioritization
Version: 2.0 · Date: 2026-08-30
Scope: Independent capstone decision-support system aligned with the City of Chicago's Vision Zero framework. Not an official City product; does not approve or program projects. Final authority remains with City staff and engineering teams.

## 1. Executive Summary

Chicago cannot fund every high-crash corridor at once. This project builds a transparent, reproducible decision-support system that:
1. Forecasts where future recorded crash burden is likely highest across the 43 official high-crash corridors;
2. Estimates the safety benefits of applicable treatments using FHWA Crash Modification Factors (CMFs) and USDOT crash costs;
3. Optimizes project portfolios under budget and equity constraints using Mixed-Integer Linear Programming (MILP); and
4. Presents results in deployed interactive decision-support applications (Streamlit Cloud, Google Cloud Run container specification, and Power BI data mart) with explicit governance and limitation reporting.

### Key Metrics: Baseline Recommendation vs. Aggregate Candidate Pool

#### A. Canonical Baseline Recommendation (`PORT_OFF_BASE_B15M_EQ20`)
*The official recommended project portfolio under the primary planning scenario ($15M budget ceiling, 20% minimum equity spending floor, BASE CMF point estimates):*
- **Corridors Evaluated & Funded**: **39 of 43 high-crash corridors funded** (4 corridors deferred due to the binding $15M ceiling).
- **Allocated Capital Cost**: **$14,988,510** (~$14.99M), leaving **$11,490 in budget slack**.
- **Equity Capital Allocation**: **47.35% of capital ($7,097,550)** allocated to high-SVI equity-priority corridors (exceeding the 20% policy floor).
- **Averted Crash Burden**: **48.04 fatal and severe injury crashes (KSI) avoided per year**; **2,170.20 total crashes avoided per year**.
- **Present Value Safety Benefit**: **$4,003,734,895.70 (~$4.00B)** over a 20-year analysis period at a 3.0% real discount rate.
- **Benefit-Cost Ratios**: **267.12:1 Comprehensive Societal BCR** (including statistical value of life and severe injury harm); **34.2:1 Economic-Only BCR** (direct tangible economic damages).

#### B. Aggregate Candidate-Pool Universe (All 387 Options)
*The unconstrained mathematical sum of all evaluated candidate possibilities across the network prior to mutual exclusivity and portfolio optimization:*
- **Total Candidate Options**: **387 candidate rows** (43 corridors × 3 treatments × 3 CMF uncertainty scenarios).
- **Aggregate Candidate Capital Cost**: **$26.75M** (sum of all available treatments across all corridors).
- **Aggregate Present Value Safety Benefit**: **$6.55B** (theoretical total benefit if every treatment were simultaneously implemented without mutual exclusivity).
- **Aggregate Candidate-Pool BCR**: **~245:1**.
- *Important Distinction*: These candidate-pool figures represent the gross evaluation universe and must **not** be confused with the selected baseline portfolio recommendation ($14.99M cost, $4.00B PV benefit, 267.12:1 BCR).

---

## 2. Business Problem & Governance Boundary

- **Decision Question**: Which combination of corridor-level road-safety projects should be shortlisted for engineering review under limited capital budgets and equity spending requirements?
- **Constraints Modeled**: Budget ceiling ($2M to $40M); minimum equity spending floor (20%, 30%, 40%); at most one treatment per corridor; BCR ≥ 1.0 candidate eligibility (Decision D023); Road Diet portfolio share ≤ 70% (Decision D026); functional-class screening proxy (Decision D027).
- **Responsible-Use Boundary**: The system supports decision-making; it does not replace engineering feasibility, community input, legal review, or final capital-program authority.

---

## 3. Data Foundation & Verification

- **Clean Crash Core**: 877,919 records (2018–2025); 0 missing/duplicate keys; 0 invalid dates; 99.19% valid-coordinate coverage (7,150 invalid preserved with warnings).
- **Spatially Eligible Crashes**: 870,769 crashes within Chicago municipal boundary.
- **Corridor Register**: 43 high-crash corridors (HCC001–HCC043), official Vision Zero framework.
- **Corridor Geometry**: 43 valid geometries (EPSG:3435); 42 LineString + 1 MultiLineString; 3 governed exceptions (Lake Shore Drive, Fairbanks, Wacker).
- **Street Centerlines**: 56,338 features; 99.996% valid coverage.

---

## 4. Spatial Crash-to-Corridor Assignment

- **Threshold**: 100-ft buffer (internal modeling decision, not City policy).
- **Match Results**: 114,224 unique crashes matched (13.1% of municipal total); 8,132 multiple-candidate matches; 1,803 ties at 10-ft (excluded as unresolved ties to prevent double-counting).
- **Rules**: Valid coordinates required; nearest candidate is primary; at most one primary corridor per crash; unmatched/invalid records preserved and reported.

---

## 5. Panel, Features & Crash Risk Forecasting

- **Corridor-Month Panel**: 4,128 rows (43 corridors × 96 months, 2018–2025); zero-filled; no partial 2026 data in modeling.
- **Time-Safe Validation**: Chronological split (2018 warm-up / 2019–2023 train / 2024 validation / 2025 test); strict anti-leakage protocol.
- **Production Forecast Models**:
  - *Total Crashes*: 12-month rolling-mean benchmark (selected on 2024 validation Poisson deviance over GLMs).
  - *KSI Crashes*: Negative Binomial GLM + Empirical-Bayes (EB) shrinkage calibration.
- **Backtest Performance (2024/2025)**: Total-crash calibration ratio of 0.984 (2024) and 1.030 (2025), aggregate bias +0.68%; KSI EB-calibrated ratio 1.000 (2024) and 0.917 (2025).

---

## 6. Treatment Benefits & Economics

- **Candidate Evaluation**: 387 candidate rows (43 corridors × 3 treatments × 3 uncertainty scenarios).
  - Treatments: TRT_001 (Pedestrian Refuge Islands), TRT_002 (Road Diet / 4-to-3 Conversion), TRT_004 (Rectangular Rapid Flashing Beacons / RRFB).
- **Economic Parameters**: FHWA CMF Clearinghouse factors; USDOT comprehensive crash costs; 3.0% real discount rate (Decision D021); 20-year useful life (TRT_001/002) and 10-year useful life (TRT_004).
- **Severity Allocation**: Pedestrian treatments apply pedestrian-specific KSI shares (~17.5%); total-crash treatments apply all-crash shares (~2%).

---

## 7. Portfolio Optimization (MILP)

- **Formulation**: Solved via `scipy.optimize.milp` (HiGHS solver).
- **Objective**: Maximize total present-value safety benefit.
- **Scenarios**:
  - *27 Official Scenarios*: Budgets ($15M, $25M, $40M) × Equity Floors (20%, 30%, 40%) × Uncertainty (BASE, CONSERVATIVE, OPTIMISTIC).
  - *9 Stress Scenarios*: Budgets ($2M, $4M, $6M) × Equity Floors (20%, 30%, 40%) under BASE uncertainty.
  - *156 Planner Grid Scenarios*: What-if budget increments ($2M–$40M) × Equity Floors (15%–40%).
- **Determinism**: 3-repeat solves verified for 100% identical selection hashes and objective values.
- **Lineage Reconciliation**: 100% reconciliation between summary grain (192 rows) and detail selection grain (6,999 rows).

---

## 8. Validation & Governance

- **Test Suite**: 327 passing automated tests (`pytest -q` on 2026-08-30: 327 passed, 0 failed, 0 skipped in 854.08s), 0 Git side-effects.
- **Decision Log**: Governed entries D001 through D027 covering corridor definitions, analytical boundaries, discount rates, unit costs, diversification caps, and screening rules.
- **Snapshots**: Checksum-verified deployment snapshots (`deployment_manifest.json` with SHA-256 validation).

---

## 9. Known Limitations & Claim Boundaries

1. **Societal Benefit, Not City Revenue**: Present value benefits represent comprehensive societal economic harms averted based on USDOT guidance. They do not represent cash revenues, municipal savings, or direct budgetary returns to the City of Chicago.
2. **Planning-Level Estimates**: All project costs, benefits, and BCRs are preliminary planning-level screening estimates based on average unit costs and point-estimate CMFs.
3. **Not Causal Treatment-Effect Evidence**: CMF values reflect empirical associative factors from the FHWA CMF Clearinghouse, not local randomized causal experiments.
4. **Not Individual Crash-Risk Prediction**: Models predict aggregate recorded crash frequency at the monthly corridor level, not the crash probability of individual motorists or pedestrians.
5. **Physical Applicability Requires Field Review**: Roadway geometric feasibility (lane widths, median geometry, crossing spacing, utility conflicts) carries provisional status `UNKNOWN` and requires on-site survey by qualified CDOT/IDOT transportation engineers.
6. **Optimizer Recommends; Humans Decide**: The optimization algorithm provides transparent candidate project shortlists; final project approval, design modification, and programming authority rest exclusively with City staff and engineering teams.
7. **Funding Authorization Outside Model**: Planning budget scenarios ($2M–$40M) are exploratory analytical tools and do not constitute authorized City appropriations or capital program commitments.
8. **Budget Ceiling Sensitivity**: Under base costs, full network treatment costs $17.56M. The $15M budget is **BINDING** (39 corridors funded); higher budgets ($25M, $40M) are **NONBINDING** (all 43 corridors fit).
