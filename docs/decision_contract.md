# Vision Zero Chicago — Decision Contract

## 1. Business Problem

Chicago has a limited road-safety budget and cannot fund every high-crash corridor.

The project will help decision-makers identify where future recorded crash risk may
be highest, estimate which safety treatment may provide the greatest benefit for
each corridor, and recommend a combination of projects that fits the available
budget and equity requirement.

## 2. Business Decision

Which combination of corridor-level road-safety projects should be shortlisted
for engineering review under a limited budget and an equity requirement?

## 3. Candidate Set

The initial candidate set contains 43 historical high-crash corridors.

The corridor list is a project analysis boundary. It must not be presented as a
new official City designation unless verified by an official City source.

## 4. Unit of Analysis

The modelling dataset will contain one row for each corridor and month.

Expected historical panel:

- 43 corridors
- 96 historical months
- 4,128 corridor-month rows

## 5. Prediction Objective

Estimate the expected number of recorded crashes for each corridor during the
next 12-month planning period.

Expected production forecast:

- 43 corridors
- 12 forecast months
- 516 corridor-month predictions

This is a planning estimate, not a claim that a specific crash will occur.

## 6. Treatment Analysis

For each applicable corridor-treatment combination, estimate:

- Expected crashes without treatment
- Evidence-supported Crash Modification Factor
- Expected crashes prevented
- Expected safety benefit
- Estimated treatment cost
- Benefit-cost ratio
- Treatment applicability status
- Evidence source and limitations

A treatment must not be recommended when its applicability cannot be supported by
the available corridor characteristics and evidence.

## 7. Portfolio Optimization

The optimization stage will recommend a project portfolio subject to:

- Total project cost must not exceed the selected budget
- No more than one treatment may be selected for a corridor
- Only applicable corridor-treatment combinations may be selected
- The selected portfolio must satisfy the project-defined equity requirement

Budget and equity values will be tested as transparent planning scenarios. They
must not be described as official City policy unless confirmed by an official
source.

## 8. Final Outputs

The project will produce:

1. Cleaned and validated corridor-month analytical dataset
2. Twelve-month corridor crash-risk forecast
3. Corridor-treatment benefit and cost table
4. Budget and equity-constrained project recommendation
5. Scenario and sensitivity analysis
6. Power BI decision-support dashboard
7. Streamlit scenario application
8. Reproducible Python pipeline
9. Technical report and implementation documentation

## 9. Decision Authority

The system is a decision-support tool.

The final decision remains with the City and qualified transportation-engineering
teams. They must review treatment feasibility, site conditions, community input,
legal requirements, implementation constraints and available funding before
approving any project.

## 10. Responsible-Use Boundary

The model must not:

- Automatically approve road-safety projects
- Replace engineering or community review
- Claim causal effects that are not supported by evidence
- Treat project-defined budget or equity scenarios as official policy
- Hide missing data, ambiguous spatial assignments or model uncertainty