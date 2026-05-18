# Plan: Merge Agents + Integration Testing Support (v3)

## Context

Four agent files duplicate ~70% of content, creating maintenance burden. The harness has no
concept of phase types, so integration/e2e phases receive wrong test commands and incorrect
TDD triplet enforcement. Goal: one builder, one reviewer, proper phase lifecycle, and a
dedicated integration testing guide the agent reads when building integration phases.

**Confirmed scope:** Phase-level language routing retained. Integration testing is spec-phase-
driven. TypeScript unit tests → vitest; Playwright E2E is deferred to next iteration.

---

## Design Principles Applied

1. **Separate harness mechanics from language guidance.** `builder.md` / `reviewer.md` describe
   signal schemas, modes, and orchestration rules only. Language-specific content goes into
   `rules/<lang>/` files referenced by name in the agent preamble.
2. **Task types removed entirely.** They are never validated by the harness (stop hook only
   checks `task_type` is a string) and not injected into agent prompts. The field remains in
   signals for observability, but no predefined vocabulary is enforced or listed.
3. **phase_type assigned to ALL phases** from the spec title, so every harness branch (TDD
   enforcement, test command selection) can cleanly gate on it.
4. **Integration/e2e phases are language-optional.** They often touch both Python and TypeScript
   files. No language tag is required; the harness falls back to `state["language"]` for profile
   selection. `check_spec_completeness()` exempts these phases from the language-tag check.

---

## Requirement 1 — Merge Builder Agents

### New files

**`.claude/agents/builder.md`** — harness mechanics only:
- Modes: TASK_BUILD, EXECUTE, FIX — when each is invoked and what the harness expects
- Signal schemas for all three modes (verbatim, unchanged from current agents)
- TDD triplet rule: test_first → implementation → unit_test (development phases only)
- `## TDD task ordering` section must state: all tasks in setup (phase 1), integration, and
  e2e phases **must** use `tdd_mode: "exempt"` with a `tdd_skipped` reason explaining why the
  TDD triplet does not apply (e.g., `"setup phase — no application logic to test"`,
  `"integration test — no TDD triplet required"`). The hook enforces `tdd_skipped` is present
  on every exempt task.
- Verification gates to run before signaling `complete`
- File references using the CLAUDE.md format, pointing to language-specific guides:
  - `- .claude/rules/python/python-builder-guide.md — python task types, test/compile commands, TDD patterns, integration testing patterns` (injected at runtime when language=python)
  - `- .claude/rules/typescript/typescript-builder-guide.md — typescript task types, test/compile commands, TDD patterns, integration testing patterns` (injected at runtime when language=typescript)
- Reference to integration guide for integration/e2e phases:
  - `- .claude/rules/common/integration-testing-guide.md — integration and e2e phase build rules: task TDD exemption, real-service test structure, test isolation patterns` (read this when phase title indicates integration or E2E)

**`.claude/rules/python/python-builder-guide.md`** — new file:
- Test command (from profile): `pytest --asyncio-mode=auto`
- Integration test command (from profile): `pytest -m integration --asyncio-mode=auto`
- Compile check: `python -m py_compile <file>`
- TDD patterns: pytest fixtures, `pytest.raises()`, AAA structure, 80%+ coverage

**`.claude/rules/typescript/typescript-builder-guide.md`** — new file:
- Test command (from profile): `npx vitest run`
- Integration test command (from profile): `npx vitest run` (Playwright deferred)
- Compile check: `npx tsc --noEmit`
- TDD patterns: vitest `describe`/`it`, `expect()`, TypeScript strict test files
- Phaser thin-layer rules: `Scene.update()` calls entity/state methods only, no game logic

**`.claude/rules/common/integration-testing-guide.md`** — new file (see Req 3 detail below)

### Files to modify

**`.claude/settings.builder.json`** — add TypeScript PostToolUse hooks from
`settings.frontend-builder.json` (the hooks already check file extension and coexist):
```json
{ "matcher": "Write", "hooks": [{ "type": "command", "command": "python .claude/hooks/post_ts_lint_format.py" }] },
{ "matcher": "Edit",  "hooks": [{ "type": "command", "command": "python .claude/hooks/post_ts_lint_format.py" }] }
```

**`harness/lang.py`** — both profiles:
- `builder_agent` → `".claude/agents/builder.md"`
- Add `builder_guide`: Python → `".claude/rules/python/python-builder-guide.md"`, TypeScript →
  `".claude/rules/typescript/typescript-builder-guide.md"`
- Add `integration_test_cmd`: Python → `["pytest", "-m", "integration", "--asyncio-mode=auto"]`,
  TypeScript → `["npx", "vitest", "run"]`
- Remove `task_types` from both profiles
- TypeScript only: `builder_settings` → `".claude/settings.builder.json"`,
  `test_cmd` → `["npx", "vitest", "run"]`

**`harness/agents.py`** — `build_file_lists()`:
- Add `profile["builder_guide"]` to `builder_files` list
- Add `profile["reviewer_guide"]` to `reviewer_files` list (added in Req 2)

**`harness/calibrate.py`**:
- Delete `sync_task_types()` function entirely
- In `log_usage()`: remove lines 35-37 (`known = state.get("task_types", [])` check and
  the associated warning) — log `task_type` as-is without validation

**`CLAUDE.md`**:
- `## Agent Files`: replace four entries with `builder.md` and `reviewer.md`
- `## Docs`: remove "includes task_types registry" from state.json description
- `## Git Rules`: replace `code-builder` and `code-reviewer` with `builder` and `reviewer`
- `## Skills`: update skill references to include new language guide files

### Files to delete
- `.claude/agents/code-builder.md`
- `.claude/agents/frontend-builder.md`
- `.claude/settings.frontend-builder.json`

---

## Requirement 2 — Merge Reviewer Agents

### New files

**`.claude/agents/reviewer.md`** — harness mechanics only:
- Mode: REVIEW
- 4 dimensions in order: Functionality, Security, Performance, Design/Quality
- Severity definitions (CRITICAL / HIGH / MEDIUM / LOW) and verdict rules (APPROVE / WARN / BLOCK)
- Signal schema (verbatim, unchanged)
- File references using CLAUDE.md format:
  - `- .claude/rules/python/python-review-standards.md — python compile check, security checks, performance checks, integration test review criteria` (injected when language=python)
  - `- .claude/rules/typescript/typescript-review-standards.md — typescript compile check, XSS/eval/prototype-pollution checks, Phaser thin-layer, performance, integration test review criteria` (injected when language=typescript)

**`.claude/rules/python/python-review-standards.md`** — new file:
- Compile check: `python -m py_compile <file>`
- Security: hardcoded secrets, pickle/yaml.load, `subprocess(shell=True)`, SQL injection,
  path traversal
- Performance: N+1 queries, O(n²), unbounded DB fetches
- Design: bare `except:`, functions >50 lines, missing tests
- Integration test review:
  - Verify `@pytest.mark.integration` used; marker registered in `pytest.ini`/`conftest.py`
  - Verify no mocks for external deps in integration tests
  - Verify fixture cleanup (each test starts/ends with clean state)
  - Verify cross-component paths are covered (not just happy-path unit coverage)

**`.claude/rules/typescript/typescript-review-standards.md`** — new file:
- Compile: `npx tsc --noEmit`, `npx eslint <file>`
- Security: XSS (`innerHTML`/`outerHTML`), `eval`/`new Function`, prototype pollution, WebSocket
  `JSON.parse` in try/catch, `import.meta.env` (not hardcoded)
- Performance: allocations in `update()`, missing `destroy()` on scene transitions, O(n²)
  in game loop
- Phaser: `Scene.update()` must only call entity/state methods — no inline game logic
- Integration test review:
  - Verify `*.integration.test.ts` files test cross-component interactions
  - Verify no mocks for external service calls
  - Verify test cleanup between runs

### Files to modify

**`.claude/skills/security-review/SKILL.md`** — append `## TypeScript / Browser` section:
- XSS prevention (textContent not innerHTML, DOMPurify for untrusted HTML)
- Code injection (no `eval`, `new Function` with external input)
- Prototype pollution (validate keys before `Object.assign` or spread)
- WebSocket/fetch: `JSON.parse` in try/catch, type guards before use
- Secrets: `import.meta.env` only; no tokens in `console.log`
- Dependencies: `npm audit` clean

**`harness/lang.py`** — both profiles:
- `reviewer_agent` → `".claude/agents/reviewer.md"`
- Add `reviewer_guide`: Python → `".claude/rules/python/python-review-standards.md"`,
  TypeScript → `".claude/rules/typescript/typescript-review-standards.md"`
- TypeScript: `reviewer_skill` → `".claude/skills/security-review/SKILL.md"`

### Files to delete
- `.claude/agents/code-reviewer.md`
- `.claude/agents/frontend-reviewer.md`
- `.claude/skills/typescript-security-review/SKILL.md`

---

## Requirement 3 — Integration Testing Support

### Gap analysis: spec phase alone is NOT sufficient

All five gaps below are resolved by this plan.

| Gap | Resolved by |
|-----|-------------|
| No `phase_type` on any phase | `spec.py` detects type from title; writes to state.json |
| `verify.py` always uses `test_cmd` | `_select_test_cmd()` helper routes to `integration_test_cmd` |
| `stop_validate_json` always enforces TDD triplet | TDD triplet gated on `phase_type == "development"` |
| No `integration_test_cmd` in profiles | Added to both Python and TypeScript profiles in `lang.py` |
| No integration guide file | `.claude/rules/common/integration-testing-guide.md` created; injected by `agents.py` for integration/e2e phases |

### phase_type for ALL phases

Phase 1 is always `"setup"`. Other phases classified by title keywords from
`spec_validation.json`:

| phase_type | Condition |
|------------|-----------|
| `"setup"` | Phase 1 (always) |
| `"integration"` | Title contains a keyword in `phase_type_keywords.integration` |
| `"e2e"` | Title contains a keyword in `phase_type_keywords.e2e` |
| `"development"` | All other non-Phase-1 phases |

Keywords stored in `harness/spec_validation.json` under a new key:
```json
"phase_type_keywords": {
  "integration": ["integration"],
  "e2e": ["e2e", "end-to-end", "end to end", "end2end", "verification"]
}
```
Also add `"integration"` and `"e2e"` to `"phase1_domain_disqualifiers"` to prevent Phase 1
from being mis-classified if its title contains those words.

### Language for integration/e2e phases

Integration phases often need to write both Python and TypeScript files (e.g., pytest calling
a Flask API while also testing TypeScript output). Requiring a single language tag is
inappropriate. Decision:
- Language tag is **optional** for integration/e2e phases
- If absent, harness falls back to `state["language"]` (project default) for profile selection
- `check_spec_completeness()` exempts integration/e2e phases from language-tag requirement
- The integration testing guide instructs the agent that it may write files in any project language

### New file: `.claude/rules/common/integration-testing-guide.md`

Content:
- **When to use this guide**: `phase_type` is `"integration"` or `"e2e"`. The builder reads
  this instead of following the standard TDD triplet rules.
- **Task classification**: All tasks in this phase use `tdd_mode: "exempt"`,
  `tdd_skipped: "integration test — no TDD triplet required"`.
- **What integration tests verify**: Cross-component interactions, real service calls, data
  flowing through the full stack. NOT unit-level isolated logic.
- **Python patterns**: `@pytest.mark.integration`; register marker in `pytest.ini`;
  `conftest.py` fixtures for server startup, DB seed/teardown; run with
  `pytest -m integration --asyncio-mode=auto`; no `unittest.mock` for external services.
- **TypeScript patterns**: Name files `*.integration.test.ts`; use vitest with real service
  calls; run with `npx vitest run`; no `vi.mock()` for external services.
- **Test isolation**: Each test starts with clean state. Fixtures set up and tear down
  real services (start/stop server, seed/clear DB). No shared mutable state between tests.
- **File scope**: Integration tests may create or modify both `.py` and `.ts` files depending
  on the stack being tested.

### harness/spec_validation.json
- Add `"phase_type_keywords"` key (see above)
- Add `"integration"`, `"e2e"`, `"end-to-end"` to `"phase1_domain_disqualifiers"`

### harness/spec.py
- **`_extract_phases()`**: load `phase_type_keywords` from spec_validation.json; after language
  detection, compute `phase_type` per the table above; add to each phase dict.
- **`parse_spec()` (line 56-74)**: include `"phase_type": p["phase_type"]` in each phase shell
  written to state.json.
- **`check_spec_completeness()` (line 186-194)**: skip language-tag requirement for phases
  where `phase_type in ("integration", "e2e")`.

### harness/harness.py
- In `_do_task_build()`: remove the call to `sync_task_types(state, new_tasks, profile)`
  and its import from `calibrate` (`sync_task_types` is deleted).
- In the first-run path of `run()`, gate the null-language fill loop to preserve
  `language: null` for integration/e2e phases:
  ```python
  for sp in state["phases"]:
      if sp.get("language") is None and sp.get("phase_type") not in ("integration", "e2e"):
          sp["language"] = self._default_language
  ```
- Add `phase_type_for()` (`find_phase` is already imported at module level — no inner import):
  ```python
  def phase_type_for(self, phase_id: int) -> str:
      return (find_phase(self.state, phase_id) or {}).get("phase_type", "development")
  ```
- In `_do_executing()`: pass `phase_type=self.phase_type_for(phase_id)` to `agents.execute()`.

### harness/verify.py
- Add `_select_test_cmd(profile, phase_type) -> list[str]`:
  ```python
  def _select_test_cmd(profile: dict, phase_type: str) -> list[str]:
      if phase_type in ("integration", "e2e"):
          return profile.get("integration_test_cmd", profile["test_cmd"])
      return profile["test_cmd"]
  ```
- Replace all `profile["test_cmd"]` references with `_select_test_cmd(profile, harness.phase_type_for(phase_id))`.
  Affected: line 54 (SHA-unchanged fallback), line 128-129, lines 170-171.

### harness/agents.py — fix_issues() test command (fix in this iteration)
- `fix_issues()` currently hard-codes `profile.get("test_cmd", ["pytest"])` in the FIX prompt
  (line 269). For integration/e2e phases the run-after-fix command must be `integration_test_cmd`.
- Add `phase_type: str = "development"` parameter to `fix_issues()`.
- Select test command using the same `_select_test_cmd` logic (inline or import from verify.py):
  ```python
  test_cmd = (
      profile.get("integration_test_cmd", profile.get("test_cmd", ["pytest"]))
      if phase_type in ("integration", "e2e")
      else profile.get("test_cmd", ["pytest"])
  )
  ```
- Update all callers in `harness/fix.py` to pass `phase_type=harness.phase_type_for(phase_id)`.

### harness/fix.py
- `run_batch_retry_loop()`: pass `phase_type=harness.phase_type_for(phase_id)` to
  `agents.execute()`.
- `_collect_test_cmds()`: replace `profile.get("test_cmd", ["pytest"])` with
  `_select_test_cmd(profile, harness.phase_type_for(sp["id"]))` — add `_select_test_cmd`
  to the import from `verify`. This ensures the final full-run test invocation uses
  `integration_test_cmd` for integration/e2e phases rather than always running `test_cmd`.

### .claude/hooks/stop_validate_json.py
- In TASK_BUILD TDD ordering block (line 191+):
  - Read `workspace/state.json`; find phase matching `phase_id`; get `phase_type`.
  - Guard with `try/except (FileNotFoundError, KeyError, json.JSONDecodeError)` → default
    `phase_type = "development"` if state unreadable.
  - Replace the existing `if phase_id != 1:` guard with `if phase_type == "development":` to
    unify all non-development exemptions (setup, integration, e2e) under one rule.
  - All existing TDD ordering logic inside the block (tdd_mode state machine, exempt task
    `tdd_skipped` requirement) is **unchanged**.

### harness/agents.py — conditional integration guide injection
- `build_tasks()` receives `phase: dict` directly; use `phase.get("phase_type", "development")`
  to gate guide injection. No signature change needed.
- `execute()`: add `phase_type: str = "development"` parameter. Gate guide injection on
  `phase_type in ("integration", "e2e")`. Callers must pass the value:
  - `harness.py:_do_executing()` → `phase_type=self.phase_type_for(phase_id)`
  - `fix.py:run_batch_retry_loop()` → `phase_type=harness.phase_type_for(phase_id)`
- Both functions append `".claude/rules/common/integration-testing-guide.md"` to
  `builder_files` when the condition is met, before the prompt is built.

---

## Summary: Changes, Removals, New Files

### Created (7 new files)
| File | Purpose |
|------|---------|
| `.claude/agents/builder.md` | Harness mechanics (modes, signals, TDD triplet rule) |
| `.claude/agents/reviewer.md` | Harness mechanics (REVIEW mode, verdicts, signal) |
| `.claude/rules/python/python-builder-guide.md` | Python test/compile commands, TDD patterns |
| `.claude/rules/typescript/typescript-builder-guide.md` | TypeScript test/compile commands, TDD patterns, Phaser rules |
| `.claude/rules/python/python-review-standards.md` | Python review checks, integration test review |
| `.claude/rules/typescript/typescript-review-standards.md` | TypeScript/Phaser review checks |
| `.claude/rules/common/integration-testing-guide.md` | Integration/e2e phase build rules |

### Modified (12 files)
| File | Key changes |
|------|-------------|
| `.claude/settings.builder.json` | Add TypeScript PostToolUse hooks |
| `.claude/skills/security-review/SKILL.md` | Append TypeScript/browser security section |
| `harness/lang.py` | Both profiles: merged agent paths, builder/reviewer guides, integration_test_cmd; TS: fix test_cmd to vitest; remove task_types |
| `harness/agents.py` | `build_file_lists()`: add builder_guide/reviewer_guide; `build_tasks()`: inject integration guide via `phase.get("phase_type")`; `execute()`: add `phase_type` param + guide injection; `fix_issues()`: add `phase_type` param to select correct test command |
| `harness/calibrate.py` | Delete `sync_task_types()`; remove task_type validation from `log_usage()` |
| `harness/fix.py` | `run_batch_retry_loop()` + all `fix_issues()` callers: pass `phase_type`; `_collect_test_cmds()`: use `_select_test_cmd()` per phase |
| `harness/spec_validation.json` | Add phase_type_keywords; add integration/e2e to phase1_domain_disqualifiers |
| `harness/spec.py` | phase_type detection, write to state, language-tag exemption for integration/e2e |
| `harness/harness.py` | Remove `sync_task_types` call; fix null-language fill loop for integration/e2e; `phase_type_for()` with null guard; pass `phase_type` to `agents.execute()` |
| `harness/verify.py` | `_select_test_cmd()` helper; replace `test_cmd` references |
| `.claude/hooks/stop_validate_json.py` | TDD triplet gated on `phase_type == "development"`; non-development phases verify all tasks have `tdd_skipped` set |
| `CLAUDE.md` | Update agent references, remove task_types mention, update skill list |

### Deleted (6 files)
| File | Reason |
|------|--------|
| `.claude/agents/code-builder.md` | Superseded by `builder.md` |
| `.claude/agents/frontend-builder.md` | Superseded by `builder.md` |
| `.claude/agents/code-reviewer.md` | Superseded by `reviewer.md` |
| `.claude/agents/frontend-reviewer.md` | Superseded by `reviewer.md` |
| `.claude/settings.frontend-builder.json` | Merged into `settings.builder.json` |
| `.claude/skills/typescript-security-review/SKILL.md` | Merged into `security-review/SKILL.md` |

### No longer applicable (remove in place)
| Item | Where | Reason |
|------|-------|--------|
| `task_types` key | `harness/lang.py` profiles | Never validated by harness; agent uses language guide |
| `state["task_types"]` | `harness/state.py` create_state() | Unused in harness logic after prompt injection removed |
| Language-tag requirement for integration/e2e | `harness/spec.py` completeness check | These phases are inherently cross-language |

---

## Remaining Gaps After All Changes

1. **TypeScript integration vs. unit test distinction**: `integration_test_cmd = ["npx", "vitest",
   "run"]` is identical to `test_cmd`. The distinction only matters when Playwright E2E is added
   in the next iteration. No functional regression — verify.py will call the same command either
   way for TypeScript phases currently.

2. **--resume compatibility**: `phase_type` is written by `parse_spec()` on first run. A resumed
   run reads `phase_type` from the existing state.json, which is already correct. No migration
   needed as long as the resumed run was started with the updated harness. Resuming a run
   started with the old harness (which has no `phase_type` in state.json) falls back to
   `"development"` — safe, but may call unit `test_cmd` for an integration phase. Document in
   README: resume requires state.json written by the same harness version.

---

## Test Plan

### Gate 1 — Full regression suite
```bash
pytest harness/tests/ -v
```
High-risk suites:
- `test_lang.py` — task_types removed; builder/reviewer guide keys added; TS test_cmd changes
- `test_agents.py` / `test_agents_settings.py` — agent/settings file paths change
- `test_tdd_ordering.py` — TDD enforcement logic changes in stop hook
- `test_spec.py` / `test_spec_completeness.py` — phase_type field added; exemption logic
- `test_verify.py` — test command selection changes

### Gate 2 — New unit tests required

**`harness/tests/unit/test_spec.py`**
- `test_phase_type_is_setup_for_phase_1`
- `test_phase_type_integration_for_title_with_integration_keyword`
- `test_phase_type_e2e_for_title_with_e2e_keyword`
- `test_phase_type_development_for_regular_non_setup_phase`
- `test_parse_spec_writes_phase_type_to_state_json_shell`
- `test_check_completeness_no_language_tag_required_for_integration_phase`
- `test_check_completeness_no_language_tag_required_for_e2e_phase`

**`harness/tests/unit/test_lang.py`**
- `test_python_profile_has_integration_test_cmd`
- `test_typescript_profile_has_integration_test_cmd`
- `test_typescript_profile_test_cmd_is_vitest_not_playwright`
- `test_both_profiles_use_builder_md`
- `test_both_profiles_use_reviewer_md`
- `test_both_profiles_have_builder_guide_key`
- `test_both_profiles_have_reviewer_guide_key`
- `test_task_types_not_in_profiles`
- `test_typescript_uses_unified_settings_builder_json`

**`harness/tests/unit/test_verify.py`**
- `test_select_test_cmd_returns_integration_cmd_for_integration_phase`
- `test_select_test_cmd_returns_integration_cmd_for_e2e_phase`
- `test_select_test_cmd_returns_test_cmd_for_development_phase`
- `test_select_test_cmd_returns_test_cmd_for_setup_phase`
- `test_verify_execution_uses_integration_test_cmd` (mock subprocess; phase_type=integration)
- `test_verify_fix_uses_integration_test_cmd` (mock subprocess; phase_type=integration)

**`harness/tests/unit/test_tdd_ordering.py`**
- `test_integration_phase_skips_tdd_triplet` — state.json has `phase_type="integration"`,
  signal has all `tdd_mode="exempt"` with `tdd_skipped` set → hook exits 0
- `test_e2e_phase_skips_tdd_triplet` — same with `phase_type="e2e"`
- `test_development_phase_still_enforces_tdd_triplet` — must not regress
- `test_integration_phase_still_requires_tdd_skipped_reason` — exempt task in integration
  phase without `tdd_skipped` text → hook exits 1 (existing exempt check unchanged)
- `test_hook_degrades_gracefully_when_state_json_missing` — no state.json →
  falls back to development rules, exits 0 for valid triplet

**`harness/tests/unit/test_agents.py`**
- `test_build_file_lists_includes_builder_guide`
- `test_build_file_lists_includes_reviewer_guide`
- `test_build_tasks_integration_guide_appended_for_integration_phase` — phase dict with `phase_type="integration"` passed to `build_tasks()`; confirm integration guide in builder_files
- `test_execute_integration_guide_appended_for_integration_phase` — `phase_type="integration"` passed as parameter to `execute()`; confirm integration guide in builder_files
- `test_integration_guide_not_appended_for_development_phase`
- `test_fix_issues_uses_integration_test_cmd_for_integration_phase` — confirm prompt
  contains integration_test_cmd when `phase_type="integration"`
- `test_fix_issues_uses_test_cmd_for_development_phase`

### Gate 3 — Integration test (harness state machine)

Add to `harness/tests/integration/test_state_machine.py`:
- Scenario: spec with Phase 1 (setup), Phase 2 (backend [python]), Phase 3 (Integration Testing):
  - Phase 3 `state.json` has `"phase_type": "integration"`, `"language": null`
  - Phase 3 TASK_BUILD signal with all `tdd_mode: "exempt"` → stop hook accepts
  - Phase 3 EXECUTE verify calls `integration_test_cmd` not `test_cmd`
  - REVIEW on Phase 3 passes; cycle reaches COMPLETE

### Gate 4 — Manual smoke test
1. Add `## Phase 3: Integration Testing` (no language tag) to `docs/spec.md`
2. Run: `python harness/harness.py docs/spec.md --language python --app-type web --max-phase 3`
3. Assert: `workspace/state.json` Phase 3 has `"phase_type": "integration"`, `"language": null`
4. Assert: Phase 3 tasks in state.json are all `"tdd_mode": "exempt"`
5. Assert: harness logs show `integration_test_cmd` invoked during Phase 3 verify
6. Assert: `pytest harness/tests/` still passes after run
