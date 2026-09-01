# Decision-Output Mart Contract (Phase 5A)

## 1. Overview & Business Objective

The Phase 5A Decision-Output Mart serves as the single source of truth for Vision Zero Chicago decision-support user interfaces (Power BI dashboards and Streamlit web applications). It connects portfolio optimization selections, treatment economics, spatial corridor equity, 2026 crash risk forecasts, and master corridor linework into decoupled, high-performance relational tables.

---

## 2. Table Schemas, Grains & Primary Keys

### A. `fact_portfolio_scenario_summary` (`vw_power_bi_portfolio_summary`)
- **Analytical Grain**: `portfolio_id` × 1 row (36 canonical scenarios: 27 Official, 9 Stress; 192 total serving grid scenarios).
- **Primary Key**: `portfolio_id` (VARCHAR)
- **Governed Fields**:
  - `portfolio_id`: Unique scenario run identifier (e.g. `PORT_OFF_BASE_B15M_EQ20`).
  - `run_group`: `OFFICIAL`, `BINDING-BUDGET STRESS TEST`, or `WHAT-IF PLANNER GRID`.
  - `scenario_level`: CMF uncertainty scenario (`CONSERVATIVE`, `BASE`, `OPTIMISTIC`).
  - `budget_usd`: Capital budget constraint ceiling ($2M to $40M).
  - `equity_floor`: Minimum required equity spending share (0.15 to 0.40).
  - `selection_hash`: SHA-256 hash of selected `(corridor_id, treatment_id)` pairs.
  - `portfolio_equivalence_group`: Unique identifier for equivalent selection sets.
  - `equivalent_portfolio_count`: Number of portfolios sharing identical selections.
  - `is_canonical_portfolio`: Boolean flag marking exactly one canonical row per equivalence group.
  - `is_default_dashboard_portfolio`: Boolean flag marking `PORT_OFF_BASE_B15M_EQ20` as the default executive dashboard selection.

### B. `fact_portfolio_project_selections` (`vw_power_bi_project_selections`)
- **Analytical Grain**: `portfolio_id` × `corridor_id` (1,341 canonical detail rows across 36 scenarios; 6,999 detail rows across 192 serving grid scenarios).
- **Primary Key**: `(portfolio_id, corridor_id)`
- **Governed Fields**:
  - `portfolio_id`, `corridor_id`, `corridor_name`, `treatment_id`, `treatment_name`, `uncertainty_scenario`, `capital_project_cost`, `present_value_benefit`, `net_present_benefit`, `benefit_cost_ratio`, `equity_area_flag`, `physical_applicability_status` (`APPLICABLE` / `NOT_APPLICABLE`), `evidence_status`, `selected_rank_by_benefit`, `required_governance_labels`, `run_group`, `scenario_level`, `budget_usd`, `equity_floor`, `selection_hash`, `portfolio_equivalence_group`, `is_canonical_portfolio`, `is_default_dashboard_portfolio`.

### C. `dim_corridor_master` (`vw_power_bi_corridor_master`)
- **Analytical Grain**: `corridor_id` × 1 row (43 high-crash corridor rows).
- **Primary Key**: `corridor_id`
- **Governed Fields**:
  - `corridor_id`, `corridor_name`, `street_name`, `from_street`, `to_street`, `source_group`, `spatial_total_length_feet`, `spatial_total_length_miles`, `corridor_length_weighted_svi`, `high_svi_length_share`, `equity_classification_A_weighted_ge_0_75`, `equity_classification_B_share_ge_0_50`, `attr_lane_count_available`, `attr_adt_available`, `attr_posted_speed_available`, `attr_median_width_available`, `attr_crossings_available`, `annual_forecast_total_crashes_2026`, `annual_forecast_ksi_crashes_2026`, `demand_risk_rank_2026`, `centroid_latitude`, `centroid_longitude`, `geometry_wkt`, `geometry_crs` (`EPSG:3435`).

### D. `fact_corridor_treatment_benefits` (`vw_power_bi_treatment_benefits`)
- **Analytical Grain**: `corridor_id` × `treatment_id` × `scenario_level` (387 candidate rows).
- **Primary Key**: `(corridor_id, treatment_id, scenario_level)`

---

## 3. Relationship Cardinalities & Lineage Rules

- **`dim_corridor_master` to `fact_portfolio_project_selections`**: **1-to-Many** (`corridor_id`).
- **`fact_portfolio_scenario_summary` to `fact_portfolio_project_selections`**: **1-to-Many** (`portfolio_id`).
- **`fact_corridor_treatment_benefits` to `fact_portfolio_project_selections`**: **1-to-Many** (`corridor_id, treatment_id, uncertainty_scenario`).
  - *Lineage Rule*: Phase 4B candidate panel contains 387 unique candidate rows. Phase 5A project selections contain 1,341 canonical detail rows (6,999 serving rows). Each selection row joins back 100% to exactly 1 candidate row with 0 unmatched rows and 0 join expansion.

---

## 4. Allowed Aggregations vs. Prohibited Cross-Portfolio Sums

- **ALLOWED**: Costs, benefits, averted crashes, and project counts may be summed **within a single `portfolio_id` only** (`WHERE portfolio_id = '...'`).
- **PROHIBITED**: Summing costs, benefits, or project counts across multiple `portfolio_id` values is **STRICTLY PROHIBITED**. It double-counts identical candidate projects across scenarios.
- **DASHBOARD KPI FILTERING**: Dashboard KPI cards must filter to a single `portfolio_id` (or filter by `is_canonical_portfolio = True` or `is_default_dashboard_portfolio = True`).

---

## 5. Default Filters & Canonical Baseline Metrics

- **Default View**:
  - `run_group`: `OFFICIAL`
  - `scenario_level`: `BASE`
  - `portfolio_id`: `PORT_OFF_BASE_B15M_EQ20` (`is_default_dashboard_portfolio = True`)
- **Executive Hero Metrics (Baseline Portfolio `PORT_OFF_BASE_B15M_EQ20`)**:
  - **Funded Corridors**: 39 of 43 (4 deferred under $15M budget)
  - **Capital Project Cost**: $14,988,510 (~$14.99M)
  - **Budget Slack**: $11,490
  - **High-SVI Capital Share**: 47.35% (Floor: 20.0%)
  - **Annual KSI Avoided**: 48.04
  - **Annual Total Crashes Avoided**: 2,170.20
  - **Present Value Benefit**: $4,003,734,895.70 (~$4.00B)
  - **Comprehensive BCR**: 267.12:1
- **Economic Scenario Section**:
  - Displays PV Benefit and BCR with mandatory disclaimer:
    *"Analyst-defined planning costs and crash-cost assumptions — not an approved City benefit-cost estimate."*

---

## 6. Official vs. Stress Scenario Separation

- **OFFICIAL (27 runs)**: Official planning scenarios under $15M, $25M, and $40M budgets and 20%, 30%, 40% equity floors across CONSERVATIVE, BASE, and OPTIMISTIC uncertainty.
- **BINDING-BUDGET STRESS TEST (9 runs)**: Analyst-defined diagnostic stress scenarios under $2M, $4M, and $6M budgets under BASE uncertainty. Stress budgets bind effectively (`EFFECTIVELY_BINDING_NO_ADDITIONAL_CORRIDOR`).
- **WHAT-IF PLANNER GRID (156 runs)**: Interactive planning grid covering fine-grained budget and equity permutations.

---

## 7. Spatial Map Serving Readiness & Limitations

- **`dim_corridor_master`** provides WGS84 centroids (`centroid_latitude`, `centroid_longitude`), projected WKT linework (`geometry_wkt`), CRS (`EPSG:3435`), and `corridor_id` join keys.
- **Streamlit Spatial Serving**: Streamlit maps use governed GeoJSON/WKT generated directly from committed corridor geometry.

---

## 8. Mandatory Stakeholder Caveats

1. *"All project cost, benefit, and BCR metrics represent analyst-defined planning scenarios for decision support only."*
2. *"Physical applicability status is UNKNOWN due to missing lane counts, median widths, and crossing inventories. Every selected project requires CDOT/IDOT engineering field survey."*
3. *"Under $15M budget, the portfolio ceiling is BINDING (39 corridors funded). At $25M and $40M, the budget exceeds total network cost ($17.56M BASE) and is NONBINDING."*
