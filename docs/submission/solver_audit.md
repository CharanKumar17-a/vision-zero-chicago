# Vision Zero Chicago — Solver Audit: MILP Portfolio Optimization

## 1. Solver Architecture & Formulation

- **Optimization Paradigm**: Mixed-Integer Linear Programming (MILP).
- **Solver Engine**: `scipy.optimize.milp` (interfacing with the HiGHS C++ branch-and-cut solver).
- **Decision Variables**: Binary selection indicators $x_{i,j} \in \{0, 1\}$, where $i \in \{1 \dots 43\}$ indexes corridors and $j \in \{\text{TRT\_001}, \text{TRT\_002}, \text{TRT\_004}\}$ indexes safety treatments.
- **Objective Function**: Maximize total 20-year present value safety benefit:
  $$\max \sum_{i=1}^{43} \sum_{j} \text{PV\_Benefit}_{i,j} \cdot x_{i,j}$$
  *(Implemented in standard form as $\min \mathbf{c}^T \mathbf{x}$ where $c_{i,j} = -\text{PV\_Benefit}_{i,j}$).*

---

## 2. Governed Mathematical Constraints

1. **Mutual Exclusivity (Corridor Uniqueness)**:
   $$\sum_{j} x_{i,j} \le 1 \quad \forall i \in \{1 \dots 43\}$$
   *At most one safety capital treatment is selected per high-crash corridor.*

2. **Planning Budget Ceiling**:
   $$\sum_{i=1}^{43} \sum_{j} \text{Cost}_{i,j} \cdot x_{i,j} \le \text{Budget}$$
   *Total capital expenditure must not exceed the specified planning budget.*

3. **Equity Spending Floor**:
   $$\sum_{i \in \text{HighSVI}} \sum_{j} \text{Cost}_{i,j} \cdot x_{i,j} \ge \text{EquityFloor} \times \sum_{i=1}^{43} \sum_{j} \text{Cost}_{i,j} \cdot x_{i,j}$$
   *Rearranged as a linear constraint:*
   $$\sum_{i=1}^{43} \sum_{j} \left( \mathbf{1}_{i \in \text{HighSVI}} - \text{EquityFloor} \right) \cdot \text{Cost}_{i,j} \cdot x_{i,j} \ge 0$$

4. **Non-Trivial Portfolio**:
   $$\sum_{i=1}^{43} \sum_{j} x_{i,j} \ge 1$$

5. **Road Diet Diversification Cap (Decision D026)**:
   $$\sum_{i=1}^{43} x_{i,\text{RoadDiet}} \le 0.70 \times \sum_{i=1}^{43} \sum_{j} x_{i,j}$$
   *Prevents single-treatment mono-culture and promotes multi-modal safety intervention.*

6. **Functional-Class Applicability Screening (Decision D027)**:
   $$x_{i,\text{RoadDiet}} = 0 \quad \forall i \in \text{Expressway/Divided Carriageway (e.g. HCC019 Lake Shore Drive)}$$

7. **Candidate Economic Viability (Decision D023)**:
   $$\text{Candidate Eligible if } \text{BCR}_{i,j} \ge 1.0$$

---

## 3. Solver Determinism & Verification

- **Determinism Check**: Each scenario is solved across 3 independent executions.
- **Result**: 100% identical SHA-256 selection hashes and objective values across all repeat solves.
- **Optimality Status**: All 192 scenario runs achieve verified `OPTIMAL` status with zero solver divergence or infeasibility.

---

## 4. Scenario Spectrum & Lineage

| Scenario Group | Count | Budgets | Equity Floors | Uncertainty Tiers | Output Rows |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **OFFICIAL** | 27 | $15M, $25M, $40M | 20%, 30%, 40% | BASE, CONSERVATIVE, OPTIMISTIC | 27 summary / 1,065 detail |
| **STRESS TEST** | 9 | $2M, $4M, $6M | 20%, 30%, 40% | BASE | 9 summary / 297 detail |
| **WHAT-IF GRID**| 156 | $2M to $40M (26 steps)| 15% to 40% (6 steps)| BASE | 156 summary / 5,637 detail |
| **Total** | **192** | | | | **192 summary / 6,999 detail** |

*Note*: 36 canonical scenarios represent the core 27 official and 9 stress test runs (1,362 canonical detail rows).

---

## 5. Canonical Baseline Portfolio Verification (`PORT_OFF_BASE_B15M_EQ20`)

- **Funded Corridors**: 39 of 43 high-crash corridors (4 deferred due to the $15M ceiling).
- **Allocated Capital Cost**: $14,988,510 (~$14.99M).
- **Budget Slack**: $11,490 (effectively binding).
- **High-SVI Capital Share**: 47.35% (Floor: 20.0%).
- **Annual KSI Avoided**: 48.04 fatal and severe injuries / year.
- **Annual Total Crashes Avoided**: 2,170.20 crashes / year.
- **Present Value Safety Benefit**: $4,003,734,895.70 (~$4.00B).
- **Comprehensive Societal BCR**: 267.12:1 (Direct Economic-Only BCR: 34.2:1).
- **Candidate-Pool Aggregate Comparison**: 387 total candidate options aggregate to $26.75M capital cost and $6.55B PV benefit (~245:1 aggregate candidate BCR) prior to mutual exclusivity and budget optimization.

---

## 6. Budget Sensitivity & Binding Analysis

- **$2M Stress Budget**: Funds 20 corridors ($1.99M allocated, $8.8k slack).
- **$4M Stress Budget**: Funds 18 corridors ($3.99M allocated, $9.7k slack).
- **$6M Stress Budget**: Funds 28 corridors ($5.99M allocated, $12.1k slack).
- **$15M Planning Budget**: Funds 39 corridors ($14.99M allocated, $11.5k slack) — **BINDING**.
- **$25M & $40M Planning Budgets**: Fund all 43 corridors ($17.56M allocated, $7.44M slack at $25M) — **NONBINDING**.
