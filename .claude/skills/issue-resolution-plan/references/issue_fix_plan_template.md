# Issue Fix Plan Template

Use this template when the repository does not provide its own issue fix plan style.

## Plan: <short issue title>

## Context

Summarize the confirmed issue, root cause, affected workflow, and why the planned change is sufficient.

---

## Issue Or Change Area 1 - <name>

**Files:** `<path>` - `<function/class/area>`; include every directly affected file.

**Problem:** Explain the defect or gap with evidence.

**Change:** Describe the smallest concrete implementation change. Include condition analysis for edge cases and compatibility concerns.

**Tests:** List named unit tests and what each verifies. Include negative and edge cases when relevant.

**Regression coverage:** List existing tests or commands that must continue to pass for nearby unchanged behavior.

Repeat this section for each independent issue or change area.

---

## Files To Modify

| File | Change |
|------|--------|
| `<path>` | `<planned change>` |

---

## Test Coverage Matrix

| Planned change | Test case or verification | Coverage type |
|----------------|---------------------------|---------------|
| `<change>` | `<test name or command>` | Unit / integration / manual / regression |

---

## Implementation Order

1. Apply the lowest-risk isolated production change.
2. Add or update the directly related unit tests.
3. Repeat for each change area.
4. Run focused tests.
5. Run broader regression tests.

---

## Verification Criteria

```bash
<focused test command>
<broader regression command>
```

Manual checks:

- `<observable behavior to confirm>`

---

## Plan Audit

- File scope is complete.
- Each modified behavior has test coverage.
- Regression tests cover adjacent unchanged behavior.
- The plan avoids unrelated refactors and speculative features.
- No contradictions remain between root cause, solution, tests, and verification.
