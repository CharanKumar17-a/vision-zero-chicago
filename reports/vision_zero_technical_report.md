# Vision Zero Chicago — Road-Safety Investment Prioritization
Version: 1.2 · Date: 2026-08-17
Scope: Independent capstone analysis aligned with the City of Chicago's Vision Zero framework. Not an official City product; does not approve or program projects. Final authority remains with City staff and engineering teams.

1. Executive Summary
Chicago cannot fund every high-crash corridor at once. This project builds a transparent decision-support system that (1) forecasts where future recorded crash burden is likely highest across the 43 official high-crash corridors, (2) estimates the safety benefits of applicable treatments using FHWA Crash Modification Factors (CMFs), (3) optimizes a project portfolio under budget and equity constraints, and (4) presents results in a deployed interactive application with explicit governance and limitation reporting.

Headline results (BASE uncertainty scenario):

Total present-value safety benefit $6.55B on $26.75M provisional capital cost across 387 corridor-treatment candidate rows (43 corridors × 3 treatments × 3 scenarios).
Portfolio selection detail: 1,362 rows across 36 scenarios; 39 of 43 corridors funded at the $15M planning budget (cost ≈ $14.99M, budget binds under D026/D027).
Treatment diversity: pedestrian treatments (Refuge Islands TRT_001, RRFB TRT_004) are now valued with pedestrian-specific KSI severity and are selected in portfolios — no longer a 100% Road Diet concentration.
Equity: spending lands 43–58% in high-SVI equity-priority areas across scenarios, satisfying all tested floors without constraint pressure.
Critical findings on scenario design:

Under sourced planning-level costs (D024) and Road Diet diversification caps (D026/D027), the full 43-corridor network costs ≈ $17.56M–$26.75M depending on scenario. The $15M planning budget is BINDING (selects 39 corridors in BASE, deferring 4 corridors); $25M and $40M remain nonbinding.
A methodological audit (2026-08-17) identified and corrected a severity-allocation issue: pedestrian treatments previously used the all-crash KSI share (~2%) instead of the pedestrian-specific KSI share (~17.5%), understating pedestrian fatal/serious-injury benefits ~8×. Corrected in this version; all downstream outputs regenerated.
2. Business Problem
Decision question: which combination of corridor-level road-safety projects should be shortlisted for engineering review under a limited capital budget and an equity-spending requirement?

Constraints modeled: budget ceiling; minimum equity-spending floor; at most one treatment per corridor; BCR ≥ 1.0 candidate eligibility (D023).

Responsible-use boundary: the system supports decision-making; it does not replace engineering feasibility, community input, legal review, or final capital-program authority.

3. Data Foundation (verified)
Clean crash core: 877,919 rows; 0 missing/dup keys; 0 invalid dates; valid-coordinate coverage 99.19% (7,150 invalid, preserved).
Spatially eligible crashes: 870,769.
Corridor register: 43 corridors (HCC001–HCC043), official Vision Zero framework.
Corridor geometry: 43 valid geometries, EPSG:3435; 42 LineString + 1 MultiLineString; 3 governed exceptions (Lake Shore Drive, Fairbanks, Wacker).
Street centerlines: 56,338 features; 99.996% valid coverage.
4. Crash-to-Corridor Assignment
100-ft threshold (internal modeling decision, not City policy). 114,224 unique crashes matched (13.1%); 8,132 multiple-candidate; 1,803 ties at 10-ft (excluded as unresolved_tie). Valid coordinates required; nearest candidate is primary; at most one primary corridor per crash; unmatched/invalid preserved and reported; no double-counting. Sensitivity rationale: 50 ft too restrictive (104,750 matched); 100 ft adds 9,474 with modest ambiguity rise (5.5%→7.1%); quality deteriorates beyond 100 ft.

5. Panel, Features, Forecasting
4,128-row corridor-month panel (43 × 96 months, 2018–2025); zero-filled; no partial 2026 in modeling.
Time-safe split: 2018 warm-up / 2019–23 train / 2024 validation / 2025 test; chronological only; leakage audit clean.
Production forecast: 516 corridor-month 2026 predictions (43 × 12) with Beta-Binomial shrinkage and Empirical-Bayes KSI calibration.
Selected production models: total_crashes = 12-month rolling-mean benchmark (selected on 2024 validation Poisson deviance over GLMs — reported honestly, not overstated as ML forecast); ksi_crashes = Negative Binomial GLM + EB calibration. KSI is 61.6% zero-month; historical total-crash lags and annual seasonality dominate feature importance.
Hindsight backtest (notebook 09): total-crash calibration 0.984 (2024) / 1.030 (2025), 2-year aggregate bias +0.68%; KSI EB-calibrated 1.000 / 0.917. The forecast generalizes to held-out years.
6. Treatment Benefits and Economics
387 candidate rows (43 corridors × 3 treatments × 3 uncertainty scenarios). Treatments: TRT_001 Refuge Islands, TRT_002 Road Diet, TRT_004 RRFB.
CMFs from FHWA CMF Clearinghouse; USDOT/FHWA comprehensive crash costs; 3.0% real discount rate (approved decision D021; config aligned); 20-yr useful life (TRT_001/002), 10-yr (TRT_004); severity-specific K/A/B/C/O/U shares.
Severity allocation (corrected 2026-08-17): pedestrian treatments use pedestrian-specific KSI shares (~17.5%); total-crash treatments use all-crash shares (~2%). This corrects an ~8× understatement of pedestrian K/A benefits.
BASE totals (verified run 20260817T145547Z): PV benefit $6.55B; capital cost $26.75M; net PV benefit $6.52B. Portfolio-average BCR ≈ 245:1 comprehensive / ≈ 34:1 economic-only (planning-level, not expected City returns).
Physical applicability: default UNKNOWN (governance-consistent); TRT_002 explicitly NOT_APPLICABLE on divided carriageways (HCC019 Lake Shore Drive) → TRT_001 selected there. Engineering field review required before programming.
7. Portfolio Optimization
MILP (scipy.optimize.milp); objective = maximize total present-value benefit; constraints = budget ceiling, equity floor, ≤1 treatment/corridor, ≥1 project, BCR ≥ 1.0 eligibility (D023), 70% Road Diet concentration cap (D026), functional-class Road Diet screening (D027); repeat-solve determinism verified (3× identical).
36 runs = 27 official ($15M/$25M/$40M × 20/30/40% equity × 3 uncertainty) + 9 binding stress ($2M/$4M/$6M).
Outputs (run 20260817T145559Z): 36 summary rows; 1,362 selection rows; exact summary↔detail reconciliation; exact lineage; all OPTIMAL.
Verified selection tiers (BASE): $2M → 20 corridors, $4M → 18, $6M → 28, $15M → 39 (binding), $25M/$40M → all eligible. Equity floors never bind (achieved 43–58% > all floors).
Honest limitations: $15M binds but $25M/$40M are nonbinding; equity floors slack; planning-level costs; stress budgets are analyst-defined, not City budgets.
8. Validation and Governance
306 tests passed (full pytest -q, 2026-08-18), 0 Git side effects; 11-gate verifier PASS.
Committed validation reports (PASS_WITH_WARNINGS), run IDs: treatment benefits 20260817T145547Z; optimization 20260817T145559Z; decision mart 20260817T145601Z / 150635Z; dashboard 20260817T145605Z.
Decision log through D027 (D026 Road Diet 70% cap, D027 functional-class screening proxy); assumption register maintained; deployment served from checksum-verified snapshots (1,362 selections).
Final authority: City staff and engineering teams.
9. Known Limitations
$15M binds; $25M/$40M nonbinding (all eligible corridors fit) — real trade-offs shown in stress tiers.
Physical applicability UNKNOWN (no lane counts/median widths/crossing inventories); engineering field survey required.
BCRs are planning-level (provisional costs + comprehensive crash costs); not expected City returns; economic-only view provided for a conservative estimate.
Equity uses CDC/ATSDR SVI as a project-defined planning proxy, not Chicago's official equity rule.
Forecasts are of recorded crash burden; no exposure (traffic volume) data; not exposure-adjusted risk.
2026 outputs are a retrospective planning simulation (source records can be amended); not observed 2026 outcomes.
Road Diet remains the dominant selected treatment on applicable corridors (all-crash target scope); pedestrian treatments now competitive and selected where applicable.
10. Sources of Every Number
All figures trace to committed files: docs/data_quality/*_validation.json (run IDs above), data/processed/*.parquet (benefits, summary, selections), dashboard/streamlit/deployment_data/ snapshots, notebooks 01–09 (incl. hindsight backtest), and python -m pytest -q (301 passed, 2026-08-17). Decision log D001–D025; evidence tables under docs/evidence/ (CMF matrix, unit costs 2024).

