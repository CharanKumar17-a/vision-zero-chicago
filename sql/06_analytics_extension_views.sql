-- 06_analytics_extension_views.sql
-- Create analytics extension views for corridor trends, model performance, equity, and excluded projects

-- 1. View: Corridor Multi-Year Crash Trend (2018-2025) & YoY Delta
CREATE OR REPLACE VIEW vw_corridor_trend AS
WITH annual AS (
    SELECT
        corridor_id,
        corridor_name,
        calendar_year,
        SUM(total_crashes) AS total_crashes,
        SUM(ksi_crashes) AS ksi_crashes
    FROM read_parquet('data/processed/corridor_month_panel.parquet')
    GROUP BY corridor_id, corridor_name, calendar_year
)
SELECT
    corridor_id,
    corridor_name,
    calendar_year,
    total_crashes,
    ksi_crashes,
    total_crashes - LAG(total_crashes, 1) OVER (PARTITION BY corridor_id ORDER BY calendar_year) AS yoy_delta_total_crashes
FROM annual;

-- 2. View: Crash Risk Model Performance & Benchmark Comparison
CREATE OR REPLACE VIEW vw_model_performance AS
SELECT
    target,
    model_name,
    is_selected_winner,
    val_row_count,
    val_actual_total,
    val_predicted_total,
    val_mae,
    val_rmse,
    val_poisson_deviance,
    val_mean_bias,
    val_calibration_ratio,
    val_spearman_rank_corr,
    test_row_count,
    test_actual_total,
    test_predicted_total,
    test_mae,
    test_rmse,
    test_poisson_deviance,
    test_mean_bias,
    test_calibration_ratio,
    test_spearman_rank_corr
FROM read_csv_auto('outputs/tables/model_comparison.csv');

-- 3. View: Portfolio Equity Spending Summary across Scenarios
CREATE OR REPLACE VIEW vw_equity_summary AS
SELECT
    portfolio_id,
    run_group,
    uncertainty_scenario,
    budget,
    equity_floor,
    selected_project_count,
    selected_capital_cost,
    equity_spending,
    achieved_equity_share,
    equity_constraint_status,
    limiting_constraint
FROM read_parquet('data/processed/portfolio_scenario_summary.parquet');

-- 4. View: Excluded Candidate Projects for Canonical Portfolio (PORT_OFF_BASE_B15M_EQ20)
CREATE OR REPLACE VIEW vw_excluded_projects AS
WITH candidate AS (
    SELECT
        corridor_id,
        corridor_name,
        treatment_id,
        treatment_name,
        scenario_level,
        capital_project_cost,
        benefit_cost_ratio,
        equity_area_flag
    FROM read_parquet('data/processed/corridor_treatment_benefits.parquet')
    WHERE scenario_level = 'BASE'
),
selected AS (
    SELECT
        corridor_id,
        treatment_id
    FROM read_parquet('data/processed/portfolio_project_selections.parquet')
    WHERE portfolio_id = 'PORT_OFF_BASE_B15M_EQ20'
)
SELECT
    c.corridor_id,
    c.corridor_name,
    c.treatment_id,
    c.treatment_name,
    c.scenario_level,
    c.capital_project_cost,
    c.benefit_cost_ratio,
    c.equity_area_flag,
    'NOT_SELECTED_IN_PORTFOLIO' AS exclusion_reason_code
FROM candidate c
LEFT JOIN selected s
    ON c.corridor_id = s.corridor_id
   AND c.treatment_id = s.treatment_id
WHERE s.corridor_id IS NULL;
