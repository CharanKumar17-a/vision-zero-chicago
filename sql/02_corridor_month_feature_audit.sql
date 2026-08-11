-- 02_corridor_month_feature_audit.sql
-- Independently reproduce corridor-month features using SQL window functions

CREATE OR REPLACE VIEW vw_corridor_month_feature_audit AS
WITH base AS (
    SELECT
        corridor_id,
        crash_month_start,
        total_crashes,
        ksi_crashes,
        ROW_NUMBER() OVER (PARTITION BY corridor_id ORDER BY crash_month_start) AS row_num
    FROM vw_corridor_month_panel
)
SELECT
    corridor_id,
    crash_month_start,
    total_crashes,
    ksi_crashes,

    -- SQL Lags for total_crashes
    LAG(total_crashes, 1) OVER (PARTITION BY corridor_id ORDER BY crash_month_start) AS sql_total_crashes_lag1,
    LAG(total_crashes, 3) OVER (PARTITION BY corridor_id ORDER BY crash_month_start) AS sql_total_crashes_lag3,
    LAG(total_crashes, 6) OVER (PARTITION BY corridor_id ORDER BY crash_month_start) AS sql_total_crashes_lag6,
    LAG(total_crashes, 12) OVER (PARTITION BY corridor_id ORDER BY crash_month_start) AS sql_total_crashes_lag12,

    -- SQL Rolling Means for total_crashes
    CASE WHEN row_num > 3
         THEN AVG(total_crashes) OVER (PARTITION BY corridor_id ORDER BY crash_month_start ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING)
         ELSE NULL END AS sql_total_crashes_roll_mean3,
    CASE WHEN row_num > 6
         THEN AVG(total_crashes) OVER (PARTITION BY corridor_id ORDER BY crash_month_start ROWS BETWEEN 6 PRECEDING AND 1 PRECEDING)
         ELSE NULL END AS sql_total_crashes_roll_mean6,
    CASE WHEN row_num > 12
         THEN AVG(total_crashes) OVER (PARTITION BY corridor_id ORDER BY crash_month_start ROWS BETWEEN 12 PRECEDING AND 1 PRECEDING)
         ELSE NULL END AS sql_total_crashes_roll_mean12,

    -- SQL Rolling Sums for total_crashes
    CASE WHEN row_num > 3
         THEN CAST(SUM(total_crashes) OVER (PARTITION BY corridor_id ORDER BY crash_month_start ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING) AS BIGINT)
         ELSE NULL END AS sql_total_crashes_roll_sum3,
    CASE WHEN row_num > 6
         THEN CAST(SUM(total_crashes) OVER (PARTITION BY corridor_id ORDER BY crash_month_start ROWS BETWEEN 6 PRECEDING AND 1 PRECEDING) AS BIGINT)
         ELSE NULL END AS sql_total_crashes_roll_sum6,
    CASE WHEN row_num > 12
         THEN CAST(SUM(total_crashes) OVER (PARTITION BY corridor_id ORDER BY crash_month_start ROWS BETWEEN 12 PRECEDING AND 1 PRECEDING) AS BIGINT)
         ELSE NULL END AS sql_total_crashes_roll_sum12,

    -- SQL Lags for ksi_crashes
    LAG(ksi_crashes, 1) OVER (PARTITION BY corridor_id ORDER BY crash_month_start) AS sql_ksi_crashes_lag1,
    LAG(ksi_crashes, 3) OVER (PARTITION BY corridor_id ORDER BY crash_month_start) AS sql_ksi_crashes_lag3,
    LAG(ksi_crashes, 6) OVER (PARTITION BY corridor_id ORDER BY crash_month_start) AS sql_ksi_crashes_lag6,
    LAG(ksi_crashes, 12) OVER (PARTITION BY corridor_id ORDER BY crash_month_start) AS sql_ksi_crashes_lag12,

    -- SQL Rolling Means for ksi_crashes
    CASE WHEN row_num > 3
         THEN AVG(ksi_crashes) OVER (PARTITION BY corridor_id ORDER BY crash_month_start ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING)
         ELSE NULL END AS sql_ksi_crashes_roll_mean3,
    CASE WHEN row_num > 6
         THEN AVG(ksi_crashes) OVER (PARTITION BY corridor_id ORDER BY crash_month_start ROWS BETWEEN 6 PRECEDING AND 1 PRECEDING)
         ELSE NULL END AS sql_ksi_crashes_roll_mean6,
    CASE WHEN row_num > 12
         THEN AVG(ksi_crashes) OVER (PARTITION BY corridor_id ORDER BY crash_month_start ROWS BETWEEN 12 PRECEDING AND 1 PRECEDING)
         ELSE NULL END AS sql_ksi_crashes_roll_mean12,

    -- SQL Rolling Sums for ksi_crashes
    CASE WHEN row_num > 3
         THEN CAST(SUM(ksi_crashes) OVER (PARTITION BY corridor_id ORDER BY crash_month_start ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING) AS BIGINT)
         ELSE NULL END AS sql_ksi_crashes_roll_sum3,
    CASE WHEN row_num > 6
         THEN CAST(SUM(ksi_crashes) OVER (PARTITION BY corridor_id ORDER BY crash_month_start ROWS BETWEEN 6 PRECEDING AND 1 PRECEDING) AS BIGINT)
         ELSE NULL END AS sql_ksi_crashes_roll_sum6,
    CASE WHEN row_num > 12
         THEN CAST(SUM(ksi_crashes) OVER (PARTITION BY corridor_id ORDER BY crash_month_start ROWS BETWEEN 12 PRECEDING AND 1 PRECEDING) AS BIGINT)
         ELSE NULL END AS sql_ksi_crashes_roll_sum12

FROM base;
