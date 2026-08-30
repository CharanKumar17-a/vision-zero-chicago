# Vision Zero Chicago — Mentor Demonstration Script & Walkthrough

## Overview & Demo Objectives

This walkthrough provides a structured, 5–8 minute demonstration script for presenting the Vision Zero Chicago decision-support platform to project mentors, technical reviewers, and municipal stakeholders.

---

## 1. Opening & Problem Statement (1 Minute)

- **The Challenge**: The City of Chicago identified 43 High-Crash Corridors (HCC001–HCC043) that account for a disproportionate share of severe traffic injuries. However, capital funding is constrained, and CDOT cannot implement safety treatments on all corridors simultaneously.
- **The System**: Vision Zero Chicago provides an end-to-end, reproducible decision-support system that:
  1. Forecasts 2026 corridor-level crash risk using chronological models without data leakage;
  2. Evaluates evidence-based countermeasures using FHWA Crash Modification Factors (CMFs) and USDOT crash valuations;
  3. Solves a Mixed-Integer Linear Program (MILP) to recommend optimal portfolios across varying planning budgets ($15M, $25M, $40M) and equity spending floors (20%, 30%, 40%);
  4. Preserves clear governance boundaries: the system advises decision-makers but preserves final project approval with licensed professional engineers.

---

## 2. Executive Recommendation & Baseline Portfolio (2 Minutes)

*Navigate to the Executive Recommendation page (`https://vision-zero-chicago-charan.streamlit.app/`).*

- **Point out the Baseline Policy Scenario** (`PORT_OFF_BASE_B15M_EQ20`):
  - **Planning Budget**: $15.0M
  - **Equity Floor**: 20.0%
  - **Uncertainty Tier**: Base Point Estimates
- **Highlight Key Performance Indicators (Hero Metric Cards)**:
  - **Corridors Funded**: **39 of 43** (4 corridors deferred due to the binding $15M budget).
  - **Allocated Capital Cost**: **$14.99M** ($14,988,510 allocated, $11,490 budget slack).
  - **Safety Impact**: **48.04 fatal and serious injuries (KSI) avoided per year**; **2,170 total crashes avoided per year**.
  - **Achieved Equity Share**: **47.35%** of capital allocated to high-SVI equity-priority corridors (comfortably exceeding the 20% floor).
  - **Economic Return**: **$4.00B present value safety benefit** ($4,003,734,895.70), yielding a comprehensive societal Benefit-Cost Ratio (BCR) of **267.12:1** (and a direct economic-only BCR of **34.2:1**).
- **Point out the Stakeholder Disclaimer Banner**:
  - *"Analyst-defined planning costs and crash-cost assumptions — not an approved City benefit-cost estimate. All projects require engineering field surveys."*

---

## 3. Interactive Scenario Testing & Live Sensitivity Analysis (2 Minutes)

*Demonstrate the real-time sidebar controls to show dynamic optimization in action:*

1. **Test Budget Ceiling Increase ($15M → $25M)**:
   - Drag the Planning Budget slider from **$15M** to **$25M**.
   - *Observation*: The portfolio instantly updates to **43 of 43 corridors funded** (100% network coverage).
   - *Explanation*: The total cost to treat all 43 corridors under base unit costs is **$17.56M**. Under a $25M budget, the budget is non-binding, leaving **$7.44M in budget slack** and achieving **~52 KSI avoided/year**.
2. **Test Equity Spending Floor Sensitivity (20% → 30% → 40%)**:
   - Change the Minimum Equity Spending Floor dropdown from **20%** to **30%**, then to **40%**.
   - *Observation*: The selected portfolio remains identical at 45.2% high-SVI share for the $25M budget (or 47.35% for the $15M budget).
   - *Explanation*: The high-crash corridors naturally concentrate in high-vulnerability neighborhoods. Because the unconstrained optimal portfolio already spends >45% in high-SVI zones, policy floors of 20%, 30%, and 40% are mathematically non-binding.
3. **Reset to Baseline**:
   - Click the **"Reset to Baseline Scenario"** button in the sidebar.
   - *Observation*: The controls and KPIs immediately restore to the canonical 39-corridor, $14.99M baseline.

---

## 4. Corridor Explorer & Governance Auditability (1.5 Minutes)

1. **Corridor Explorer Page**:
   - Navigate to **Corridor Explorer** in the sidebar.
   - Filter to a specific corridor (e.g. `HCC019 Lake Shore Drive` or `HCC001 Pulaski Rd`).
   - Explain how Decision D027 screens out Road Diets on divided carriageways (LSD receives Refuge Islands TRT_001 instead).
   - Point out the **"Download as CSV"** action for exporting scenario project tables directly to Excel/GIS.
2. **Governance & Methodology Page**:
   - Navigate to **Governance & Methodology**.
   - Highlight the Decision Log (D001 through D027), FHWA CMF sources, USDOT economic cost references, and checksum-verified dataset manifests.

---

## 5. Technical Robustness & Deployment Architecture (30 Seconds)

- **Test Suite**: 327 passing automated tests covering spatial joins, data cleaning, ML forecasting, MILP determinism, and Streamlit AppTests.
- **Deployment**: Live on Streamlit Community Cloud with GitHub Actions keepalive ping, supported by Google Cloud Run container specifications configured for zero minimum instances (scale-to-zero).
- **Data Mart**: Star-schema SQL data mart supporting decoupled analytical consumption.
