# Spatial Assignment Contract

## Contract Status

- Status: approved for corridor-geometry implementation
- Crash-assignment status: blocked until corridor geometry passes validation
- Candidate corridor count: 43
- Corridor grain: one row per official high-crash corridor
- Crash assignment grain: at most one primary corridor per crash
- Final authority: City and engineering teams

## Purpose

This contract defines how the Vision Zero Chicago project will:

1. Convert the official high-crash corridor definitions into structured records.
2. Construct corridor line geometries from Chicago Street Center Lines.
3. Validate the 43 candidate corridor geometries.
4. Evaluate crash-to-corridor distance thresholds.
5. Assign eligible crash records to corridors.
6. prevent double counting, silent spatial assumptions and undocumented exclusions.

The contract separates spatial decisions from implementation code.

## Why This Contract Is Required

A spatial join can run successfully while producing incorrect results.

Potential errors include:

- assigning crashes to a nearby parallel road;
- assigning one crash to multiple corridors;
- measuring distance using latitude and longitude degrees;
- extending a corridor beyond its published boundaries;
- silently excluding crashes without coordinates;
- using an arbitrary buffer distance;
- accepting disconnected or incomplete corridor geometry;
- modifying geometry manually without source evidence.

These errors would affect corridor crash counts, forecasts, treatment benefits and the optimized project portfolio.

## Scope

### Included

- The 43 official high-crash corridor definitions.
- Chicago Street Center Lines as the geometry source.
- Corridor register creation.
- Corridor geometry construction.
- Geometry quality validation.
- Distance-threshold sensitivity analysis.
- Crash-to-corridor candidate matching.
- Selection of one primary corridor per eligible crash.
- Spatial evidence and issue reporting.

### Excluded

- Engineering approval of corridor boundaries.
- Official designation of new corridors.
- Modification of City source geometry.
- Automatic approval of ambiguous matches.
- Automatic project funding decisions.
- Treatment selection or portfolio optimization.

## Source Contract

### Corridor-definition source

The official high-crash corridor plan supplies:

- corridor name;
- main street;
- start boundary;
- end boundary;
- source page;
- published corridor scope.

Published source wording must be preserved.

Normalized versions may be added for matching, but they must not replace the original values.

### Street-geometry source

Chicago Street Center Lines supplies the road-segment geometry used to construct each corridor.

The project must retain enough source-segment provenance to explain which centerline records were used for each corridor.

### Prohibited source handling

The pipeline must not:

- manually redraw corridor lines without evidence;
- silently extend corridor boundaries;
- add unverified corridors;
- overwrite raw source files;
- delete source segments to make validation pass;
- modify crash coordinates;
- treat normalized street names as original source values.

## Corridor Register Contract

### Grain

One row represents one official high-crash corridor.

### Primary key

```text
corridor_id
```

### ID format

```text
HCC001 through HCC043
```

Once assigned, a corridor ID must remain stable.

IDs must not be regenerated based on row order after downstream outputs exist.

### Required fields

| Field | Purpose |
|---|---|
| `corridor_id` | Stable project identifier |
| `corridor_name` | Published or review-friendly corridor label |
| `street_name` | Main corridor street |
| `from_street` | Published starting boundary |
| `to_street` | Published ending boundary |
| `source_name` | Corridor-definition source |
| `source_page` | Page supporting the definition |
| `extraction_status` | Whether transcription has been verified |
| `geometry_status` | Current geometry-construction status |

### Extraction rules

- All 43 rows must be supported by the verified corridor source.
- Source page must be recorded.
- Corridor names and boundaries require a second verification pass.
- Original source wording must be retained.
- Normalized matching fields may be created separately.
- Missing boundaries must be flagged.
- Boundaries must not be inferred silently.

## Coordinate Reference System Contract

### Source and publication CRS

```text
EPSG:4326
```

This is used for source coordinates and published web-map geometry.

### Analysis CRS

```text
EPSG:3435
```

This projected coordinate system is used for Chicago-area distance and length calculations in US survey feet.

### Required rule

Distance and buffer calculations must never be performed directly in EPSG:4326.

Latitude and longitude are angular coordinates. Treating degrees as feet or metres would produce invalid spatial distances.

### CRS workflow

```text
Source geometry in EPSG:4326
→ Reproject to EPSG:3435
→ Perform distance and length calculations
→ Reproject review output to EPSG:4326
```

## Geometry Construction Contract

Each corridor geometry must be constructed using the following sequence:

1. Normalize street names for matching.
2. Identify candidate centerline segments for the main street.
3. Identify the published from-boundary intersection.
4. Identify the published to-boundary intersection.
5. Select connected centerline segments between the boundaries.
6. Retain source segment identifiers.
7. Dissolve selected segments by `corridor_id`.
8. Validate the resulting geometry.
9. Publish geometry only after critical checks pass.

### Street-name normalization

Permitted normalization includes:

- uppercase conversion;
- whitespace trimming;
- direction-prefix standardization;
- common street-suffix standardization.

Normalization must not destroy the original values.

### Boundary rules

- From and to boundaries are inclusive.
- Corridor geometry must not extend beyond them without evidence.
- Multiple boundary candidates must be flagged.
- A missing boundary match blocks geometry approval.
- Manual resolution must be recorded in the decision log.

### Geometry types

Permitted output types:

- `LineString`
- `MultiLineString`

A multipart geometry may be legitimate, but it must be flagged for review.

### Connectivity

Disconnected geometry does not automatically prove failure because source centerlines may contain small structural gaps.

However, disconnected geometry must be reported and reviewed before crash assignment.

## Crash Eligibility Contract

A crash can enter spatial assignment only when:

- `has_valid_coordinates` is `True`;
- latitude and longitude are present;
- coordinates passed the clean-layer global range checks;
- the crash remains inside the approved historical window.

Rows without valid coordinates remain in citywide data-quality totals.

They must not be deleted from `crashes_clean.parquet`.

This implements assumption A009.

## Candidate Distance Thresholds

The project will evaluate:

| Scenario | Maximum corridor distance |
|---|---:|
| T1 | 50 feet |
| T2 | 100 feet |
| T3 | 150 feet |
| T4 | 200 feet |

No threshold is currently approved.

```text
selected_distance_threshold_feet: null
```

## Threshold Selection Protocol

For every threshold, measure:

- number and percentage of eligible crashes matched;
- number and percentage unmatched;
- number and percentage with multiple candidate corridors;
- distance-to-primary-corridor distribution;
- match rate by year;
- match rate by corridor;
- changes in corridor crash counts;
- changes in serious and fatal crash counts;
- sensitivity of corridor rankings;
- examples of likely cross-street or parallel-road matches.

The selected threshold must be the smallest defensible distance that provides reasonable roadway coverage without creating excessive ambiguous or implausible matches.

The threshold must not be selected because it improves model accuracy or produces a preferred corridor ranking.

That would introduce circular reasoning.

## Candidate-Match Contract

The pipeline must preserve all corridor candidates that fall within the scenario threshold.

Candidate-match output must include at least:

- `crash_record_id`;
- `corridor_id`;
- distance in feet;
- threshold scenario;
- candidate rank;
- candidate count for the crash;
- ambiguity flag.

This candidate table is an audit layer. It is not the final modeling assignment.

## Primary-Assignment Contract

### Cardinality

A crash may have:

- zero primary corridors; or
- one primary corridor.

A crash must never have more than one primary corridor in the modeling table.

### Primary rule

When multiple corridors qualify:

1. Select the nearest corridor.
2. Record the number of candidates.
3. Record the nearest distance.
4. Flag the assignment as ambiguous.
5. Preserve all candidates in the candidate-match table.

### Tie handling

Candidate distances within 10 feet of each other are treated as a potential tie.

An unresolved tie must:

- remain available for review;
- be excluded from the primary model until resolved;
- never be randomly assigned;
- never be counted twice.

## Unmatched Crash Contract

A crash may remain unmatched because:

- it is outside all 43 corridors;
- coordinates are missing or invalid;
- the selected threshold is intentionally narrow;
- corridor geometry is incomplete;
- the crash lies on a nearby non-corridor road.

Unmatched crashes must:

- remain in citywide totals;
- be excluded from the corridor-month model;
- receive an explicit `unmatched` status;
- never be silently deleted.

A high unmatched rate among crashes that should lie on the published corridors may indicate geometry or threshold failure.

## Double-Counting Prevention

The corridor-month model must count each assigned crash once.

The following check is mandatory:

```text
number of primary assignment rows
=
number of distinct assigned crash_record_id values
```

Candidate matches may contain multiple rows per crash, but primary assignments may not.

## Geometry Validation

### Critical failures

Geometry publication must fail when any of the following occurs:

- corridor count is not 43;
- corridor ID is missing;
- corridor ID is duplicated;
- a required register field is missing;
- geometry is missing or empty;
- geometry is invalid;
- CRS is missing or incorrect;
- a corridor boundary remains unresolved;
- an unverified corridor is added;
- a source segment is duplicated within one corridor.

### Warnings

The following are reviewable warnings:

- multipart corridor geometry;
- disconnected geometry;
- ambiguous street-name match;
- multiple boundary candidates;
- unusually short geometry;
- unusually long geometry;
- overlapping candidate corridors;
- threshold not yet selected.

Warnings must be recorded rather than hidden.

## Length Review

Corridor lengths outside the following range require review:

| Measure | Threshold |
|---|---:|
| Minimum review length | 500 feet |
| Maximum review length | 60,000 feet |

These are plausibility checks, not automatic deletion rules.

## Assignment Validation

Critical checks include:

- unique crash keys in the primary assignment table;
- no more than one primary corridor per crash;
- every assigned corridor ID exists in the corridor register;
- every assigned crash ID exists in the clean crash core;
- distances are non-negative;
- assigned distances do not exceed the selected threshold;
- invalid-coordinate crashes are not assigned;
- unresolved ties are not included in the primary model.

Warnings include:

- high ambiguity rate;
- unusual corridor match rate;
- abrupt yearly changes in match coverage;
- large sensitivity to threshold selection;
- high unmatched rate among valid-coordinate crashes.

## Required Outputs

### Corridor register

```text
data/interim/high_crash_corridor_register.csv
```

### Validated corridor geometry

```text
data/interim/high_crash_corridors.parquet
```

### Human-review geometry

```text
data/interim/high_crash_corridors_review.geojson
```

### Candidate crash matches

```text
data/interim/crash_corridor_candidates.parquet
```

### Primary crash assignments

```text
data/processed/crash_corridor_assignments.parquet
```

## Required Evidence

The pipeline must produce:

- corridor-register validation report;
- historical corridor-register run report;
- corridor-geometry validation report;
- historical geometry run report;
- threshold sensitivity table;
- assignment validation report;
- historical assignment run report;
- data-quality issue-register entries;
- decision-log entry for the selected threshold.

Reports must be preserved for failed runs.

Failed geometry must not replace previously validated geometry.

## Acceptance Criteria: Corridor Register

The corridor register passes only when:

- it contains exactly 43 rows;
- it contains exactly 43 distinct corridor IDs;
- every required field is populated;
- every row has source-page evidence;
- every extraction has been verified twice;
- no unverified corridor has been added.

## Acceptance Criteria: Corridor Geometry

Geometry passes only when:

- all 43 corridors have non-empty geometry;
- every geometry uses the approved analysis CRS during QA;
- all critical geometry checks equal zero;
- source segment provenance is available;
- warnings are recorded for review;
- geometry publication is atomic.

## Acceptance Criteria: Crash Assignment

Assignment passes only when:

- a threshold has been selected through sensitivity analysis;
- every primary crash key is unique;
- no crash is double counted;
- all assigned corridor IDs are valid;
- every assigned distance is within the selected threshold;
- all unresolved ties are excluded from the primary model;
- coverage and ambiguity rates are reported;
- known limitations are documented.

## Analytical Limitations

The spatial assignment represents proximity to constructed corridor centerlines.

It does not prove:

- the crash occurred because of corridor design;
- the crash occurred within an official roadway right-of-way;
- the nearest corridor caused the crash;
- the selected threshold is official City policy;
- the corridor geometry is engineering-approved.

Crash coordinates may contain recording or geocoding error.

Corridor geometry is decision-support infrastructure, not an engineering survey.

## Governance Boundary

This project may construct, validate and compare candidate corridor assignments.

It may not:

- establish official City corridor boundaries;
- approve engineering geometry;
- create official safety policy;
- automatically approve projects;
- replace professional spatial or engineering review.

Final project selection remains with the City and engineering teams.