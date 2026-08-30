# Vision Zero Chicago — Model Card: 2026 Corridor Crash Risk Forecasting

## 1. Model Details

- **Model Name**: Vision Zero Chicago Corridor Crash Risk Forecast Suite
- **Model Version**: 2.0 (Post-Audit Calibrated)
- **Release Date**: August 30, 2026
- **Model Types**:
  - **Total Crash Forecast**: 12-Month Rolling Mean Historical Benchmark (Poisson Deviance Selection).
  - **Fatal and Serious Injury (KSI) Forecast**: Negative Binomial Generalized Linear Model (GLM) with Empirical-Bayes (EB) corridor-level shrinkage calibration.
- **Developers**: Vision Zero Chicago Capstone Team.
- **License / Governance**: Internal Decision-Support Framework aligned with City of Chicago Vision Zero standards.

---

## 2. Intended Use & Responsible-Use Boundaries

### Primary Intended Use
- Forecast expected annual baseline crash frequency (total crashes and KSI crashes) for 43 designated High-Crash Corridors (HCC001–HCC043) in Chicago for the 2026 planning year.
- Provide baseline safety risk estimates to parameterize Crash Modification Factor (CMF) treatment benefit calculations in Phase 4B/4C portfolio optimization.

### Out-of-Scope / Prohibited Uses
- **NOT** an automated capital project approval system.
- **NOT** a real-time crash prediction tool.
- **NOT** a replacement for engineering field surveys, geometric assessments, or community engagement.
- **NOT** official City of Chicago policy.

---

## 3. Training & Validation Data

- **Analytical Grain**: `corridor_id` × `year_month` (4,128 monthly observations across 43 corridors over 96 months: 2018–2025).
- **Crash Core**: 877,919 cleaned CPD crash records (2018–2025), with 114,224 primary spatial assignments to the 43 corridors under a governed 100-foot buffer.
- **Temporal Splitting (Chronological, Zero Leakage)**:
  - **Warm-up / Lag Initialization**: 2018 (12 months)
  - **Training Set**: 2019–2023 (60 months)
  - **Validation Set (Model Selection)**: 2024 (12 months)
  - **Test / Backtest Set (Hindsight Evaluation)**: 2025 (12 months)
  - **Production Forecast Horizon**: 2026 (12 months, 516 corridor-month predictions)

---

## 4. Model Selection & Methodology

### Total Crash Forecasting
- **Candidate Models Evaluated**: Poisson GLM, Negative Binomial GLM, Random Forest Regressor, Gradient Boosted Trees, and 12-Month Rolling Mean Benchmark.
- **Selected Model**: **12-Month Rolling Mean Historical Benchmark**.
- **Rationale**: Outperformed parameterized GLM and ML models on validation Poisson deviance and mean absolute error. Reported transparently as an empirical benchmark rather than overstating complex ML.

### KSI Crash Forecasting
- **Candidate Models Evaluated**: Poisson GLM, Zero-Inflated Poisson, Negative Binomial GLM, Negative Binomial + Empirical-Bayes shrinkage.
- **Selected Model**: **Negative Binomial GLM + Empirical-Bayes Shrinkage Calibration**.
- **Rationale**: KSI crashes exhibit severe zero-inflation (61.6% zero-months across corridors) and high overdispersion. Empirical-Bayes shrinkage pools variance across corridors, preventing extreme point-estimate fluctuations on low-volume corridors.

---

## 5. Quantitative Performance & Backtest Results

### Validation Performance (2024 Held-Out Year)
- **Total Crash Calibration Ratio**: 0.984 (Observed / Predicted)
- **KSI Crash Calibration Ratio (EB-Calibrated)**: 1.000

### Hindsight Backtest Performance (2025 Held-Out Year)
- **Total Crash Calibration Ratio**: 1.030
- **2-Year Aggregate Bias (2024–2025)**: +0.68%
- **KSI Crash Calibration Ratio (EB-Calibrated)**: 0.917

---

## 6. Known Limitations & Technical Caveats

1. **Lack of Continuous Traffic Exposure (AADT)**: Segment-level average daily traffic counts are not available continuously across all 43 corridors in open city datasets. Models predict recorded crash burden rather than exposure-normalized crash rates.
2. **High Sparsity in Severe Injuries**: Due to the rarity of fatal crashes at the monthly corridor grain, KSI predictions reflect calibrated expected values rather than exact occurrence times.
3. **Stationarity Assumption**: Forecasts assume baseline roadway network geometry remains invariant to major unmodeled external interventions during the forecast year.
