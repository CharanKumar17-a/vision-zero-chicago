---
name: verify-phase
description: Executable verification workflow for Vision Zero Chicago mandatory completion gates.
---

# verify-phase Workflow

Execute this workflow to verify any task before reporting completion.

## Verification Steps

1. Read `AGENTS.md` at the repository root.
2. Read the current task definition and its declared acceptance criteria.
3. Identify all applicable configuration files, decision log entries, quality contracts, validation reports, and tests.
4. Execute `automation/verify_project.ps1` from PowerShell at the repository root.
5. Inspect validation-report status and metrics in detail (do not rely on file existence alone).
6. Reconcile analytical outputs against project configuration and contracts.
7. Classify each applicable completion gate as PASS, FAIL, or BLOCKED.
8. Refuse to declare task completion while any mandatory gate is not PASS.
9. Format the final response using the required `AGENTS.md` summary structure.
10. Never stage or commit changes without explicit user approval.

## Safe Automatic Correction Protocol

Safe automatic correction is permitted ONLY when all of the following conditions are satisfied:
- The problem is purely mechanical and unambiguous.
- The fix is strictly inside the current task's declared file allowlist.
- It does not alter analytical methodology, configuration values, contracts, thresholds, assumptions, or expected results.
- It does not overwrite user work.
- The workflow explicitly reports the correction.
- Verification is rerun immediately after applying the correction.

### Examples of Safe Corrections
- Syntax errors introduced during the current task.
- Formatting or trailing-whitespace errors.
- Missing imports in newly created implementation files.
- Deterministic path-handling errors.

### Mandatory Stop Conditions (No Automatic Fix)
Stop immediately and request direction when:
- Governance sources conflict.
- Methodology is uncertain.
- A configured value would need to change.
- An existing test would need to be weakened or modified.
- Analytical outputs disagree with validation evidence.
- The required fix falls outside the declared file scope.

Limit automatic correction attempts to at most two verification reruns. If failures persist after two reruns, return BLOCKED with complete empirical evidence.
