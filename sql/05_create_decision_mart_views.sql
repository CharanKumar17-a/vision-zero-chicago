-- 05_create_decision_mart_views.sql
-- Create integrated decision-output mart views for Power BI & Streamlit serving layer (Phase 5A)

-- 1. View: Portfolio Scenario Summary Mart
CREATE OR REPLACE VIEW vw_power_bi_portfolio_summary AS
WITH summary_base AS (
    SELECT
        portfolio_id,
        run_group,
        uncertainty_scenario AS scenario_level,
        budget AS budget_usd,
        equity_floor,
        portfolio_hash AS selection_hash,
        (run_group || '_' || uncertainty_scenario || '_' || portfolio_hash) AS portfolio_equivalence_group,
        uncertainty_scenario,
        budget,
        solver_status,
        solver_message,
        objective_name,
        selected_project_count,
        selected_corridor_count,
        selected_capital_cost,
        budget_slack,
        budget_utilization_pct,
        equity_spending,
        achieved_equity_share,
        total_present_value_benefit,
        total_net_present_benefit,
        portfolio_bcr,
        maximum_individual_bcr,
        road_diet_project_count,
        road_diet_project_share,
        road_diet_spending_share,
        physical_applicability_unknown_count,
        portfolio_hash,
        budget_constraint_status,
        equity_constraint_status,
        limiting_constraint,
        required_governance_labels
    FROM read_parquet('data/processed/portfolio_scenario_summary.parquet')
)
SELECT
    portfolio_id,
    run_group,
    scenario_level,
    budget_usd,
    equity_floor,
    selection_hash,
    portfolio_equivalence_group,
    CAST(COUNT(*) OVER (PARTITION BY portfolio_equivalence_group) AS BIGINT) AS equivalent_portfolio_count,
    CASE
        WHEN portfolio_id IN (
            'PORT_OFF_CONSERVATIVE_B15M_EQ20',
            'PORT_OFF_BASE_B15M_EQ20',
            'PORT_OFF_OPTIMISTIC_B15M_EQ20',
            'PORT_STR_BASE_B2M_EQ20',
            'PORT_STR_BASE_B4M_EQ20',
            'PORT_STR_BASE_B6M_EQ20'
        ) THEN TRUE
        ELSE FALSE
    END AS is_canonical_portfolio,
    CASE
        WHEN portfolio_id = 'PORT_OFF_BASE_B15M_EQ20' THEN TRUE
        ELSE FALSE
    END AS is_default_dashboard_portfolio,
    uncertainty_scenario,
    budget,
    solver_status,
    solver_message,
    objective_name,
    selected_project_count,
    selected_corridor_count,
    selected_capital_cost,
    budget_slack,
    budget_utilization_pct,
    equity_spending,
    achieved_equity_share,
    total_present_value_benefit,
    total_net_present_benefit,
    portfolio_bcr,
    maximum_individual_bcr,
    road_diet_project_count,
    road_diet_project_share,
    road_diet_spending_share,
    physical_applicability_unknown_count,
    portfolio_hash,
    budget_constraint_status,
    equity_constraint_status,
    limiting_constraint,
    required_governance_labels
FROM summary_base;

-- 2. View: Portfolio Project Selections Detail Mart
CREATE OR REPLACE VIEW vw_power_bi_project_selections AS
SELECT
    s.portfolio_id,
    p.run_group,
    p.scenario_level,
    p.budget_usd,
    p.equity_floor,
    p.selection_hash,
    p.portfolio_equivalence_group,
    p.is_canonical_portfolio,
    p.is_default_dashboard_portfolio,
    s.corridor_id,
    s.corridor_name,
    s.treatment_id,
    s.treatment_name,
    s.uncertainty_scenario,
    s.capital_project_cost,
    s.present_value_benefit,
    s.net_present_benefit,
    s.benefit_cost_ratio,
    s.equity_area_flag,
    s.physical_applicability_status,
    s.evidence_status,
    s.selected_rank_by_benefit,
    s.required_governance_labels
FROM read_parquet('data/processed/portfolio_project_selections.parquet') s
LEFT JOIN vw_power_bi_portfolio_summary p
    ON s.portfolio_id = p.portfolio_id;

-- 3. View: Master Corridor Dimension & Attribute Register
CREATE OR REPLACE VIEW vw_power_bi_corridor_master AS
SELECT
    r.corridor_id,
    r.corridor_name,
    g.street_name,
    g.from_street,
    g.to_street,
    g.source_group,
    r.spatial_total_length_feet,
    (r.spatial_total_length_feet / 5280.0) AS spatial_total_length_miles,
    r.corridor_length_weighted_svi,
    r.high_svi_length_share,
    r.equity_classification_A_weighted_ge_0_75,
    r.equity_classification_B_share_ge_0_50,
    r.attr_lane_count_available,
    r.attr_adt_available,
    r.attr_posted_speed_available,
    r.attr_median_width_available,
    r.attr_crossings_available,
    f.annual_total_crashes_forecast AS annual_forecast_total_crashes_2026,
    f.annual_ksi_forecast_calibrated AS annual_forecast_ksi_crashes_2026,
    f.rank_calibrated_model_forecast AS demand_risk_rank_2026,
    s.centroid_latitude,
    s.centroid_longitude,
    s.geometry_wkt,
    s.geometry_crs
FROM read_parquet('data/processed/corridor_treatment_readiness.parquet') r
LEFT JOIN read_parquet('data/interim/high_crash_corridors.parquet') g
    ON r.corridor_id = g.corridor_id
LEFT JOIN read_csv_auto('outputs/forecasts/corridor_risk_forecast_2026_annual.csv') f
    ON r.corridor_id = f.corridor_id
LEFT JOIN temp_corridor_spatial s
    ON r.corridor_id = s.corridor_id;

-- 4. View: Treatment Benefits Candidate Panel Mart
CREATE OR REPLACE VIEW vw_power_bi_treatment_benefits AS
SELECT
    corridor_id,
    corridor_name,
    treatment_id,
    treatment_name,
    scenario_level AS uncertainty_scenario,
    demand_risk_rank,
    demand_risk_percentile,
    physical_applicability_status,
    relevant_forecast_crashes,
    cmf_id,
    cmf,
    cmf_standard_error,
    crashes_averted_total,
    crashes_averted_k,
    crashes_averted_a,
    crashes_averted_b,
    crashes_averted_c,
    crashes_averted_o,
    annual_monetary_benefit,
    useful_life_years,
    real_discount_rate,
    present_value_factor,
    present_value_benefit,
    capital_project_cost,
    net_present_benefit,
    benefit_cost_ratio,
    equity_area_flag,
    required_governance_labels
FROM read_parquet('data/processed/corridor_treatment_benefits.parquet');
