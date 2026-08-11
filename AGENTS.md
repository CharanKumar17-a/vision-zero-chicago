# Vision Zero Chicago Agent Contract

## Project objective

Build Vision Zero Chicago as a transparent and reproducible decision-support system that:

- forecasts corridor-level crash risk;
- evaluates eligible corridor-treatment combinations;
- calculates safety benefits using documented CMFs and crash costs;
- recommends project portfolios under $15M, $25M and $40M planning budgets;
- evaluates 20%, 30% and 40% equity spending floors;
- explains selected and excluded alternatives;
- preserves final authority with City staff and engineering reviewers.

The system supports decisions. It does not automatically approve projects.

## Source-of-truth precedence

When sources disagree, use this order:

1. Approved decision-log entries.
2. Configuration files.
3. Data-quality, spatial and methodological contracts.
4. Source and assumption registers.
5. Validated reports and acceptance tests.
6. Implementation code.
7. Conversation history.

Never silently change a contract, decision, threshold, assumption, expected value or warning policy merely to make a test pass.

A conflict with a higher-precedence source is a governance blocker, not an implementation bug.

## Required task framing

Before editing, report:

- business decision supported;
- analytical grain;
- authoritative inputs;
- expected outputs;
- acceptance criteria;
- files intended to change;
- files explicitly out of scope;
- leakage risk;
- crash double-counting risk;
- spatial and temporal reconciliation risks;
- governance risks;
- reproducibility risks.

Stop and request direction if the task conflicts with an approved decision, contract or governance boundary.

## Implementation protocol

During implementation:

- write or update acceptance tests when behavior changes;
- preserve raw source files without modification;
- preserve invalid source records when policy requires warning-only treatment;
- keep analytical grain explicit;
- prevent crash double-counting;
- use chronological validation for forecasting;
- prevent future information from entering historical features;
- preserve uncertainty and warning evidence;
- avoid unrelated refactoring;
- avoid abstractions that do not reduce a demonstrated project risk;
- prioritize the minimum credible decision-support product;
- never weaken, remove or bypass a valid test to obtain a pass;
- never edit unrelated user changes;
- never claim that planning scenarios are official City policy;
- never claim real-time data unless the source and refresh process genuinely support it.

## Mandatory completion gates

A task is incomplete until all applicable gates pass:

- every changed Python file compiles;
- targeted tests pass;
- the complete pytest suite passes;
- tests create no Git-visible side effects;
- git diff --check passes;
- git diff --cached --check passes when staged changes exist;
- configured row counts, keys, schemas, CRS values and grain checks pass;
- derived fields reconcile with their source fields;
- validation reports reconcile with published analytical outputs;
- critical validation failures equal zero;
- each warning includes affected rows, explanation and governance reference;
- no prohibited raw, interim, PDF, GeoJSON, Parquet or log artifact is staged;
- Git status contains only intended files;
- the final diff contains no unrelated changes.

File existence alone is not proof of correctness.

Do not declare PASS when any mandatory gate fails.

## Change authority

Do not stage or commit unless the user explicitly approves the exact staged file list after receiving the verification report.

Do not reset, restore, delete or overwrite user changes to resolve a verification failure.

## Required final response

Always report:

- objective completed;
- acceptance criteria with PASS, FAIL or BLOCKED status;
- important row counts, keys and reconciliation metrics;
- targeted and full tests executed;
- test results;
- warnings and limitations;
- files changed;
- unexpected changes;
- governance conflicts;
- Git readiness;
- recommended next phase.

Separate verified facts from planned or inferred behavior.
