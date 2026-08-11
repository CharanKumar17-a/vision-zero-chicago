-- 03_data_quality_reconciliation.sql
-- Executable SQL data-quality and reconciliation checks

CREATE OR REPLACE VIEW vw_data_quality_reconciliation AS
SELECT
    (SELECT COUNT(*) FROM vw_corridor_month_features) AS total_rows,
    (SELECT COUNT(DISTINCT corridor_id || '_' || CAST(crash_month_start AS VARCHAR)) FROM vw_corridor_month_features) AS distinct_keys,
    (SELECT COUNT(*) - COUNT(DISTINCT corridor_id || '_' || CAST(crash_month_start AS VARCHAR)) FROM vw_corridor_month_features) AS duplicate_keys,
    (SELECT COUNT(DISTINCT corridor_id) FROM vw_corridor_month_features) AS corridor_count,
    (SELECT MIN(cnt) FROM (SELECT COUNT(*) AS cnt FROM vw_corridor_month_features GROUP BY corridor_id)) AS min_months_per_corridor,
    (SELECT MAX(cnt) FROM (SELECT COUNT(*) AS cnt FROM vw_corridor_month_features GROUP BY corridor_id)) AS max_months_per_corridor,
    (SELECT CAST(MIN(crash_month_start) AS VARCHAR) FROM vw_corridor_month_features) AS min_month,
    (SELECT CAST(MAX(crash_month_start) AS VARCHAR) FROM vw_corridor_month_features) AS max_month,
    (SELECT CAST(SUM(total_crashes) AS BIGINT) FROM vw_corridor_month_features) AS total_crashes_sum,
    (SELECT CAST(SUM(ksi_crashes) AS BIGINT) FROM vw_corridor_month_features) AS ksi_crashes_sum,
    (SELECT COUNT(*) FROM vw_corridor_month_features WHERE total_crashes = 0) AS zero_crash_rows,
    (SELECT COUNT(*) FROM vw_corridor_month_features WHERE model_split = 'warmup') AS warmup_rows,
    (SELECT COUNT(*) FROM vw_corridor_month_features WHERE model_split = 'train') AS train_rows,
    (SELECT COUNT(*) FROM vw_corridor_month_features WHERE model_split = 'validation') AS validation_rows,
    (SELECT COUNT(*) FROM vw_corridor_month_features WHERE model_split = 'test') AS test_rows,
    (SELECT COUNT(*) FROM vw_corridor_month_features WHERE model_ready = true) AS model_ready_rows,
    (SELECT COUNT(*) FROM vw_corridor_month_features WHERE total_crashes < 0 OR ksi_crashes < 0) AS negative_counts,
    (SELECT COUNT(*) FROM vw_corridor_month_features WHERE corridor_id IS NULL OR crash_month_start IS NULL) AS null_keys,
    (SELECT COUNT(*) FROM vw_corridor_month_features WHERE model_split NOT IN ('warmup', 'train', 'validation', 'test')) AS unexpected_splits,
    (SELECT CAST(SUM(ABS(ksi_crashes - (fatal_crashes + serious_injury_crashes))) AS BIGINT) FROM vw_corridor_month_features) AS ksi_reconciliation_diff,
    (SELECT CAST(SUM(ABS(total_crashes - (fatal_crashes + serious_injury_crashes + moderate_injury_crashes + minor_injury_crashes + property_damage_only_crashes + unknown_severity_crashes))) AS BIGINT) FROM vw_corridor_month_features) AS severity_reconciliation_diff;
