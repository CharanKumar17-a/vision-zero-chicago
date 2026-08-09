# Crash Cleaning Contract

## Contract Status

- Status: approved for implementation
- Effective date: 2026-08-09
- Source: Chicago Traffic Crashes - Crashes
- Dataset ID: `85ca-t3if`
- Configuration: `config/cleaning.yml`
- Historical period: January 1, 2018 through December 31, 2025
- Reference snapshot: `snapshot_20260804T161823Z`
- Reference rows: 877,919

## Purpose

This contract defines how the frozen Chicago crash snapshot must be converted
into a reproducible analytical crash table.

It separates cleaning decisions from implementation code. The Day 5 cleaning
script must follow this contract and must not introduce undocumented deletion,
imputation, recoding or filtering.

The cleaned crash table will support later vehicle and people aggregation,
corridor assignment, corridor-month modeling, forecasting, treatment-benefit
estimation and portfolio optimization.

## Input Contract

### Input location

```text
data/raw/chicago_traffic_crashes/crashes/
```

The cleaning pipeline must use the latest successful crashes acquisition
manifest to identify the frozen input snapshot.

### Input grain

One row represents one recorded crash.

### Primary key

```text
crash_record_id
```

The primary key must be present, nonblank, unique and preserved without case
modification.

### Expected input

The reference snapshot contains:

- 18 compressed CSV parts,
- 877,919 rows,
- 39 selected source fields,
- records from January 1, 2018 through December 31, 2025.

The raw files are immutable and must never be manually edited.

## Output Contract

### Output location

```text
data/interim/crashes_clean.parquet
```

### Output grain

One row represents one recorded crash.

### Required row preservation

The cleaned output must contain the same number of rows as the successful input
manifest. For the reference snapshot, the expected row count is 877,919.

Cleaning must not:

- remove rows with missing coordinates,
- remove rows with blank severity,
- remove rare categories,
- remove apparent outliers without an approved rule,
- create additional rows,
- manually correct source values,
- silently impute missing values.

Quality problems must be retained, measured and flagged.

## Schema Contract

The 39 acquisition fields must be classified exactly once.

### Datetime field

- `crash_date`

`crash_date` is the authoritative event timestamp. It must parse successfully
and fall inside the configured historical period.

### String fields

- `crash_record_id`
- `traffic_control_device`
- `device_condition`
- `weather_condition`
- `lighting_condition`
- `first_crash_type`
- `trafficway_type`
- `alignment`
- `roadway_surface_cond`
- `road_defect`
- `crash_type`
- `intersection_related_i`
- `dooring_i`
- `work_zone_i`
- `hit_and_run_i`
- `damage`
- `prim_contributory_cause`
- `sec_contributory_cause`
- `street_direction`
- `street_name`
- `beat_of_occurrence`
- `most_severe_injury`

`beat_of_occurrence` is treated as a string because it is a geographic code,
not a quantity.

### Nullable integer fields

- `posted_speed_limit`
- `lane_cnt`
- `street_no`
- `num_units`
- `injuries_total`
- `injuries_fatal`
- `injuries_incapacitating`
- `injuries_non_incapacitating`
- `injuries_reported_not_evident`
- `injuries_no_indication`
- `injuries_unknown`
- `crash_hour`
- `crash_day_of_week`
- `crash_month`

Nullable integer types must be used so missing values are not converted into
false numeric values.

### Nullable float fields

- `latitude`
- `longitude`

## Text Standardization Rules

For configured categorical text fields:

1. Remove leading and trailing whitespace.
2. Convert empty strings to null.
3. Convert configured categorical values to uppercase.
4. Preserve `crash_record_id` case.
5. Preserve the original raw files unchanged.
6. Do not merge or rename source categories unless a later approved mapping
   explicitly requires it.

Standardization applies only to the cleaned output.

## Indicator Rules

The source indicator fields are `intersection_related_i`, `dooring_i`,
`work_zone_i` and `hit_and_run_i`.

Expected non-null values are `Y` and `N`. Missing values must remain null. A
missing value must not automatically become `N`, because missing and false are
not equivalent. Unexpected values must be preserved and reported as warnings.

## Severity Contract

### Source and derived fields

- Source field: `most_severe_injury`
- Derived field: `severity_kabco`

### Mapping

| Source value | KABCO code | Meaning | Reference rows |
|---|---|---|---:|
| `FATAL` | K | Fatal injury | 980 |
| `INCAPACITATING INJURY` | A | Incapacitating injury | 15,037 |
| `NONINCAPACITATING INJURY` | B | Non-incapacitating injury | 74,659 |
| `REPORTED, NOT EVIDENT` | C | Possible injury | 41,869 |
| `NO INDICATION OF INJURY` | O | No indicated injury | 743,380 |
| Blank or unmapped | U | Unknown | 1,994 blank rows |

Blank or previously unseen values must map to `U`. The pipeline must report
blank and unmapped values separately. It must not infer severity from other
fields without a separately verified rule. The original
`most_severe_injury` field must remain available in the cleaned output.

## Injury Count Rules

All injury-count fields must be parsed as nullable, nonnegative integers.

The pipeline must check:

- negative injury counts,
- fatal injuries greater than total injuries,
- incapacitating injuries greater than total injuries,
- whether injury components reconcile with `injuries_total`,
- whether severity and injury-count fields appear inconsistent.

These consistency checks are warnings unless an approved rule later makes them
fatal. Source records must not be removed because of an injury inconsistency.

## Date and Time Rules

`crash_date` is authoritative. The source fields `crash_hour`,
`crash_day_of_week` and `crash_month` are retained for validation.

The pipeline must derive date components from `crash_date` and compare them
with the source components. A mismatch must be reported. A source component
must not overwrite the authoritative timestamp.

Derived date fields are `crash_year` and `crash_month_start`.
`crash_month_start` will support the future corridor-month panel.

## Coordinate Rules

Coordinate fields are `latitude` and `longitude`. Derived fields are
`coordinate_status` and `has_valid_coordinates`.

Possible coordinate statuses:

- `valid`
- `missing_pair`
- `incomplete_pair`
- `non_numeric`
- `out_of_range`

A coordinate pair is valid at the cleaning stage when both values are present,
both are numeric, latitude is between -90 and 90, and longitude is between
-180 and 180.

The reference snapshot contains 7,150 rows without coordinate pairs, 99.19%
valid coordinate coverage and zero incomplete coordinate pairs during raw
validation.

Rows without valid coordinates remain in the cleaned crash table, raw and
cleaned quality totals, and non-spatial descriptive analysis. They are excluded
from corridor assignment unless a verified location-recovery method is
approved later.

Chicago-specific geographic plausibility and corridor-distance checks belong
to the spatial layer, not the cleaning layer.

## Join Governance

The crashes table is the parent analytical table. Future vehicle and people
data must be aggregated to one row per `crash_record_id` before joining.

Required join rules:

- Join key: `crash_record_id`
- Join type: left join from crashes
- Authoritative timestamp: `crashes.crash_date`
- Crashes without people records must be retained
- Child-table timestamps must not overwrite `crashes.crash_date`
- The joined analytical table must remain one row per crash

These rules implement decisions `D008` and `D009`.

## Derived Columns

The cleaning pipeline must produce:

- `crash_year`
- `crash_month_start`
- `severity_kabco`
- `coordinate_status`
- `has_valid_coordinates`

The output therefore contains the 39 retained source fields plus these five
required derived fields. Any additional derived field requires a documented
contract update.

## Validation Levels

### Failure conditions

The cleaning process must fail when:

- a required input field is missing,
- the input cannot be linked to a successful acquisition manifest,
- output row count differs from the manifest,
- a primary key is missing,
- a primary key is duplicated,
- `crash_date` cannot be parsed,
- a crash date is outside the historical period,
- rows are unexpectedly deleted,
- rows are unexpectedly added.

### Warning conditions

The process may complete with documented warnings for:

- blank or unmapped severity,
- invalid indicator values,
- negative or inconsistent injury counts,
- invalid source time components,
- source time components inconsistent with `crash_date`,
- missing or invalid coordinate pairs,
- globally invalid coordinates,
- implausible speed limits,
- implausible lane counts,
- implausible unit counts.

Warnings must be counted and included in validation evidence.

## Required Validation Evidence

The Day 5 and Day 6 implementation must produce evidence containing:

- source manifest and snapshot used,
- input and output row counts,
- input and output column counts,
- missing and duplicate primary keys,
- invalid dates and dates outside the historical period,
- minimum and maximum crash dates,
- severity source and KABCO value counts,
- coordinate-status counts and valid-coordinate coverage,
- indicator-value exceptions,
- numeric-range and injury-consistency exceptions,
- overall cleaning status,
- downstream readiness status,
- generated timestamp.

## Known Limitations

1. Missing coordinates prevent corridor assignment for affected records.
2. Historical crash counts measure recorded crash burden, not
   traffic-volume-adjusted risk.
3. Blank severity values remain unknown rather than being inferred.
4. Source categorical values may contain reporting variation.
5. Cleaning cannot prove engineering or treatment applicability.
6. The frozen snapshot does not represent real-time crash reporting.

## Non-Goals

This cleaning stage will not:

- assign crashes to corridors,
- join raw vehicle or people rows,
- build corridor-month features,
- create lag or rolling features,
- train forecasting models,
- select treatments,
- calculate benefits,
- optimize a portfolio,
- build dashboard measures,
- automate pipeline execution.

Those activities belong to later validated layers.

## Acceptance Criteria

The cleaning contract is ready for implementation when:

1. `config/cleaning.yml` loads successfully.
2. All 39 acquisition fields are classified exactly once.
3. The cleaning and acquisition schemas match exactly.
4. Row-preservation and no-imputation rules are explicit.
5. Severity mapping uses observed source values.
6. Coordinate handling implements assumption `A009`.
7. Join governance implements decisions `D008` and `D009`.
8. Failure and warning conditions are separated.
9. Required evidence is defined.
10. No transformation code has been written before contract approval.

## Downstream Dependency

Day 5 may build the crash cleaning pipeline only after this contract and its
automated contract tests pass.

The final portfolio recommendation remains decision support. Final project selection remains with the City and engineering teams.