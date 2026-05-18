---
name: issue-resolution-plan
description: Analyze software issues, identify root causes and affected files/configuration, propose minimal surgical solutions, and after the solution is accepted produce a comprehensive executable implementation plan with file-level changes, unit test coverage, verification criteria, regression checks, and a final plan audit. Use when you are asked to analyze an issue, close/resolve an issue, draft an issue fix plan, or turn issue investigation into an implementation plan.
---

# Issue Resolution Plan

## Overview

Use this skill to turn an issue into a verified, executable plan. The output must be a complete plan, not code, unless the user separately asks for implementation.

When the user writes in Chinese, write the analysis and plan in Chinese while preserving code symbols, file paths, command names, and test names in their original form.

## Workflow

### 1. Build Context Before Concluding

Read the issue, related code, tests, config, docs, logs, and recent diffs needed to understand the failure. Prefer repository evidence over assumptions.

State assumptions explicitly. If the issue has multiple plausible interpretations, list them and explain what evidence supports each. If a missing fact could change the plan materially, ask a concise question before planning.

Do not hide uncertainty. If the simpler fix seems sufficient, say so. If the requested approach is risky or overcomplicated, push back with the tradeoff.

### 2. Analyze And Propose A Solution

Produce an issue analysis before any implementation plan. Include:

- Issue summary: what is failing, who or what is affected, and the expected behavior.
- Root cause: the most likely underlying defect or design gap, with evidence from files, tests, logs, or configuration.
- Affected scope: exact files, directories, configs, data models, workflows, commands, or external integrations involved.
- Non-affected scope: nearby code that was inspected but should not be modified.
- Proposed solution: the minimum surgical change set that resolves the root cause.
- Alternatives and tradeoffs: include only materially plausible options.
- Risks: behavior that could regress and why.
- Approval gate: ask the user to confirm the proposed solution before generating the implementation plan, unless the user has already explicitly approved or requested the plan.

Keep the proposal goal-driven. Every proposed change must trace directly to the issue.

### 3. Confirm Plan Scope Before Writing The Plan

Before drafting the plan, verify that the file scope is sufficient and correct:

- Identify every production file, test file, fixture, schema/config file, and documentation file that must change.
- Check callers, imports, serialization contracts, feature flags, generated files, and command entry points that could be affected.
- Confirm there is no hidden gap between the proposed root-cause fix and observable user behavior.
- Confirm the plan will not require speculative features, broad refactors, or unrelated cleanup.
- Confirm regression coverage exists or is explicitly added for unchanged behavior.

If the scope is incomplete, expand it before writing the plan. If expanding the scope changes the solution materially, return to the approval gate.

### 4. Draft The Executable Plan

Use the style of `harness/docs/issue_fix_plan.md` when that file exists in the repository. If it is unavailable, use `references/issue_fix_plan_template.md` from this skill as the structural reference.

The plan must include:

- Context: concise explanation of the confirmed issue and root cause.
- Per-issue or per-change sections: exact files/functions/areas to modify, the intended behavior, and important condition analysis.
- Files to modify: table with every file and the planned change.
- Tests: unit test cases for each changed behavior, including negative and edge cases when relevant.
- Coverage mapping: every planned code change must have a named test or verification item.
- Regression checks: tests that must keep passing for code that is not changed.
- Verification criteria: commands and manual checks that prove the issue is resolved.
- Implementation order: safest sequence for applying changes.
- Risks and rollback notes: only when useful for executing safely.

Do not include code patches unless the user explicitly asks for code. Small pseudocode snippets are acceptable when they clarify an exact condition or contract.

### 5. Audit The Plan Before Final Output

Perform a final self-review and either revise the plan or add an audit section. Check:

- No missing file, config, test, fixture, or documentation change.
- No contradiction between root cause, proposed solution, files to modify, tests, and verification.
- No test case points at behavior untouched by the plan unless it is a regression check.
- Every modified behavior has test coverage.
- Regression tests are listed for unchanged but adjacent behavior.
- The implementation order will not leave the repo in a broken intermediate state.
- The plan follows simplicity first and surgical changes.

The final output should be a comprehensive, complete, effective, executable plan.
