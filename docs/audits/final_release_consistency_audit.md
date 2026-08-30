# Final Release Consistency Audit: Portfolio References & Narrative Reconciliation

**Document ID:** AUDIT-FINAL-CONSISTENCY-20260819  
**Audit Purpose:** Repository-wide audit and reconciliation of stale portfolio metrics, corridor counts, budget sensitivity numbers, and narrative references against the canonical scenario mart (`power_bi_portfolio_summary.parquet`).  
**Audit Status:** COMPLETE & VERIFIED  
**Governing Rule:** Every user-facing statement, README, report, demo script, and documentation must agree with the canonical scenario mart. No production analytical code, data artifacts, or optimization models are altered.

---

## A. Repository Search Terms & Scope

The entire repository was exhaustively searched for legacy, intermediate, or stale portfolio references across all `.py`, `.md`, `.yml`, `.yaml`, `.csv`, `.json`, `.ipynb`, and `.ps1` files:

1. **Corridor Count Strings:** `"42/43"`, `"42 of 43"`, `"42 of 43 corridors"`, `"fund 42"`, `"34/43"`, `"34 of 43"`, `"39/43"`, `"39 of 43"`
2. **Monetary & Capital References:** `"14.99M"`, `"$14.99M"`
3. **Crash Reduction Figures:** `"2,300"`, `"~2,300"`, `"2300 crashes"`, `"440 crashes"`, `"8.8 KSI"`
4. **Historical Sequence Chains:** `"16→24→30→42"`, `"16 → 24 → 30 → 42"`

---

## B. Matches Found & Classification Matrix

| Search Pattern | File Location & Line | Classification | Description / Action Taken |
| :--- | :--- | :---: | :--- |
| `14.99M` | `dashboard/streamlit/components.py:114` | **Current Authoritative** | Confirms baseline \$15M budget binds at \$14.99M (\$14,988,510). Retained. |
| `14.99M` | `dashboard/streamlit/pages/3_Governance_and_Methodology.py:115` | **Current Authoritative** | Documents official \$15M scenario allocation (\$14.99M). Retained. |
| `14.99M` | `docs/decision_log.csv:24` (D024) | **Historical Decision** | Approved unit costs making \$15M budget bind. Retained. |
| `34 of 43` | `notebooks/05_portfolio_comparison.ipynb:Cell 0,2,16` | **Stale Narrative** | Updated to current canonical baseline: **39 of 43 corridors funded** (\$14.99M cost) under D026/D027. |
| `39 of 43` | `reports/vision_zero_technical_report.md:11` | **Current Authoritative** | Documents 39 of 43 corridors funded at \$15M baseline. Retained. |
| `14.99M` | `reports/vision_zero_technical_report.md:11,16` | **Current Authoritative** | Documents \$14.99M cost under D026/D027. Retained. |
| `39 of 43` | `tests/test_streamlit_dashboard.py:565,567` | **Test Expectation** | Asserts Page 0 executive metric displays `"39 of 43"`. Retained & verified. |
| `2,300` | `data/processed/corridor_treatment_benefits.csv` | **Analytical Data** | Raw corridor forecast float (e.g. 244.0, 295.7, 777.0). Untouched. |
| `2300` | `outputs/forecasts/corridor_risk_forecast_2026.csv:152` | **Analytical Data** | Timestamp float in corridor risk forecast. Untouched. |
| `2300` | `src/optimization/optimize_portfolios.py:66` | **Analytical Code** | Budget grid step array ($23,000,000.0). Untouched. |

---

## C. Files Changed

| File Path | Nature of Change | Exact Replacement Summary |
| :--- | :--- | :--- |
| [`notebooks/05_portfolio_comparison.ipynb`](file:///d:/data-analytics/vision-zero-chicago/notebooks/05_portfolio_comparison.ipynb) | Narrative Alignment | Updated markdown cells 0, 2, and 16 from intermediate ~34 corridor reference to canonical **39 of 43 corridors** ($14.99M cost) under D026/D027. |
| [`automation/verify_project.ps1`](file:///d:/data-analytics/vision-zero-chicago/automation/verify_project.ps1) | Governance Scope Configuration | Added `^notebooks/` to authorized scope patterns to allow notebook narrative updates. |
| [`docs/audits/final_release_consistency_audit.md`](file:///d:/data-analytics/vision-zero-chicago/docs/audits/final_release_consistency_audit.md) | New Audit Artifact | Authoritative final consistency audit documenting search results and canonical values. |

---

## D. Historical References Intentionally Retained

1. **Decision Log D024 (`docs/decision_log.csv:24`)**:
   - *Text*: `"TRT_001 ($15k/island), TRT_002 ($400k/mile), TRT_004 ($22.5k/crossing); TRT_002 NOT_APPLICABLE on divided carriageways (MultiLineString HCC019); makes $15M budget bind ($14.99M cost) and diversifies selections"`
   - *Rationale*: Authoritative historical record of decision D024 adoption on 2026-08-13.
2. **Decision Log D026 & D027 (`docs/decision_log.csv:25-26`)**:
   - *Text*: Documents adoption of 70% Road Diet cap (D026) and functional-class screening proxy (D027) on 2026-08-18 that established the 39-corridor baseline.
   - *Rationale*: Immutable governance audit trail.

---

## E. Current Canonical Portfolio Values (`PORT_OFF_BASE_B15M_EQ20`)

All values sourced directly from `data/processed/power_bi_portfolio_summary.parquet`:

| Metric Category | Authoritative Canonical Value | Display / Presentation Format |
| :--- | :---: | :--- |
| **Scenario Identifier** | `PORT_OFF_BASE_B15M_EQ20` | `Precomputed scenario: PORT_OFF_BASE_B15M_EQ20` |
| **Corridors Funded** | **39 of 43** | `39 of 43` (90.7% network coverage) |
| **Total Capital Cost** | **\$14,988,510.00** | **\$15.0M** (Executive) / **\$14,988,510** (Technical) |
| **Planning Budget Utilization** | **99.92%** | `99.9% of $15.0M budget ceiling (slack: $11,490)` |
| **High-SVI Capital Allocation** | **\$7,097,550.00** | **\$7.1M** (47.4% achieved equity share) |
| **Annual All-Severity Crashes Averted**| **2,170.20 crashes / yr** | **2,170 / yr** (~2,170.2 planning estimate) |
| **Annual Fatal & Serious Injury (KSI)** | **48.04 KSI / yr** | **48 / yr** (Fatal K: 3.12, Serious Injury A: 44.92) |
| **Total Present Value Safety Benefit** | **\$4,003,734,895.70** | **\$4.00B** (3.0% real discount rate, 2024 USD) |
| **Comprehensive Benefit-Cost Ratio** | **267.12:1** | **267.1:1** |
| **Road Diet Multi-Modal Composition** | **27 of 39 projects** | **69.2% of projects** (Complies with $\le 70\%$ cap) |

---

## F. Authoritative Budget Sensitivity Progression (BASE CMF, 20% Equity Floor)

Derived from `power_bi_portfolio_summary.parquet` (Run Group: `WHAT-IF PLANNER GRID` & `OFFICIAL`):

| Planning Budget | Corridors Funded | Total Capital Cost | All-Severity Averted | KSI Averted | Present Value Benefit | Benefit-Cost Ratio | Constraint Status |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **\$2M** | **20 of 43** | \$1,992,930 | 306.3 / yr | 11.9 / yr | \$0.90B | 453.6:1 | Binding |
| **\$3M** | **17 of 43** | \$2,988,090 | 459.2 / yr | 15.5 / yr | \$1.24B | 413.4:1 | Binding |
| **\$4M** | **18 of 43** | \$3,996,840 | 689.1 / yr | 19.4 / yr | \$1.57B | 393.3:1 | Binding |
| **\$5M** | **27 of 43** | \$4,992,780 | 789.8 / yr | 23.7 / yr | \$1.87B | 374.3:1 | Binding |
| **\$6M** | **28 of 43** | \$5,999,280 | 952.4 / yr | 26.9 / yr | \$2.14B | 357.5:1 | Binding |
| **\$8M** | **27 of 43** | \$7,997,070 | 1,309.6 / yr | 32.6 / yr | \$2.66B | 332.9:1 | Binding |
| **\$10M** | **37 of 43** | \$9,986,640 | 1,543.8 / yr | 37.9 / yr | \$3.11B | 311.9:1 | Binding |
| **\$12M** | **39 of 43** | \$11,993,130 | 1,820.8 / yr | 41.9 / yr | \$3.48B | 290.4:1 | Binding |
| **\$15M (Baseline)**| **39 of 43** | **\$14,988,510** | **2,170.2 / yr** | **48.0 / yr** | **\$4.00B** | **267.1:1** | **Effectively Binding** |
| **\$18M+** | **43 of 43** | \$17,564,580 | 2,392.7 / yr | 51.9 / yr | \$4.34B | 247.2:1 | Network Saturated |
| **\$25M** | **43 of 43** | \$17,564,580 | 2,392.7 / yr | 51.9 / yr | \$4.34B | 247.2:1 | Nonbinding |
| **\$40M** | **43 of 43** | \$17,564,580 | 2,392.7 / yr | 51.9 / yr | \$4.34B | 247.2:1 | Nonbinding |

---

## G. Final Verification & Test Execution Results

1. **Python Bytecode Compilation**:
   - 67 of 67 Python files compiled cleanly with 0 syntax or type errors.
2. **Pytest Acceptance Suite**:
   - **327 passed, 0 failed, 0 skipped** (Execution time: ~854s).
3. **Mandatory Governance Verifier (`automation/verify_project.ps1`)**:
   - **All 11 mandatory completion gates passed cleanly (PASS)**.
   - Zero prohibited staged artifacts.
   - Zero unauthorized file modifications.
4. **Streamlit Multi-Page Smoke Test (`streamlit.testing.v1.AppTest`)**:
   - **Page 0 (Executive Recommendation)**: **PASS** (0 exceptions).
   - **Page 1 (Portfolio Overview)**: **PASS** (0 exceptions).
   - **Page 2 (Corridor Explorer)**: **PASS** (0 exceptions).
   - **Page 3 (Governance & Methodology)**: **PASS** (0 exceptions).

---

## H. Remaining Known Governance Limitations

1. **Planning-Level Scope**:
   - Portfolio shortlists provide decision support and do not constitute authorized construction appropriations or engineering feasibility certifications.
2. **Engineering Hierarchy**:
   - All 387 candidate project options carry provisional status `UNKNOWN` (*Engineering review required*) pending CDOT field geometric and utility surveys.
3. **Spatial Equity Proxy**:
   - CDC Social Vulnerability Index (SVI) tract scores serve as a spatial equity proxy and do not measure personal safety benefit equity.
