# Plan: Per-Phase Language Switching

## Context
The harness currently uses a single `--language` CLI flag for the entire run, stored as one global `self.profile` on the `Harness` object. A full-stack project needs backend phases (python) and frontend phases (typescript) in one run. The fix: detect the language for each phase by searching its heading for any value in `language_types` (case-insensitive substring match), build a per-phase profile map, and route every agent call, verification step, and fix cycle to the correct language profile.

**No changes needed** to `.claude/agents/*.md`, `.claude/settings*.json`, or any hook `.py` files — hooks are already file-extension-based and settings files are already selected per-call via `profile["builder_settings"]` in `agents.py`.

---

## Spec Format — flexible language identifier
```markdown
## Phase 1: Project Foundation [python]
## Phase 2: API Layer [python]
## Phase 3: Frontend UI [typescript]
```
Any heading that contains a known `language_types` value (case-insensitive) is accepted — brackets are conventional but not required. Phases whose heading contains no recognized language name fall back to the `--language` CLI default.

---

## Language gap in Fix and Cleanup (phase-group approach)
Issue IDs already encode the phase (`"2.3"` → phase 2). Each phase in `state.json` has a `"language"` field. No language field is needed on individual issue objects.

- **`run_fix_cycle`**: already receives `phase_id` — call `harness.profile_for(phase_id)` directly.
- **`run_cleanup`**: parse `phase_id` from each issue ID, group issues by `phase_id`, look up `state["phases"][phase_id]["language"]`, call `fix_issues` once per phase group with the correct profile. Issues within the same phase share a language, so this is a clean natural grouping.

---

## Files Changed

| File | Change summary |
|---|---|
| `harness/spec_validation.json` | Add `"language_types": ["python", "typescript"]` |
| `harness/spec.py` | Search `language_types` values in phase titles (case-insensitive substring match); store matched value as `language` per phase; Layer 3 completeness check |
| `harness/state.py` | Add `"language"` to allowed fields on phase objects only |
| `harness/agents.py` | Replace hardcoded `"Run pytest"` with dynamic `" ".join(profile["test_cmd"])` |
| `harness/harness.py` | Replace `self.profile` with `self.profiles: dict[int, dict]` + `profile_for()` method |
| `harness/verify.py` | Derive `phase_id` from batch; replace `harness.profile[x]` with `harness.profile_for(phase_id)[x]` |
| `harness/fix.py` | `run_fix_cycle`/`run_batch_retry_loop`: use `profile_for`; `run_cleanup`: group by language; `_finish`: accept multiple test commands |
| `harness/tests/conftest.py` | Add `"language": "python"` to phase dict in `sample_state` |
| `harness/tests/integration/test_resume.py` | Add `"language": "python"` to phases in `_base_state`; add mixed-language resume test |
| `harness/tests/integration/test_state_machine.py` | Add `"language": "python"` to inline phase dicts |
| `harness/tests/unit/test_spec.py` | Add 4 tests for language tag extraction |
| `harness/tests/unit/test_spec_completeness.py` | Update headings fixtures to include `[python]`; add 4 Layer 3 tests |
| `harness/tests/unit/test_state.py` | Add 2 tests for `language` field on phase and issue |
| `harness/tests/unit/test_harness.py` | Add 2 tests for `profile_for` |
| `harness/tests/unit/test_fix.py` | Update `_make_harness` to use `profile_for`; add 2 new tests |
| `harness/tests/unit/test_per_phase_language.py` | NEW — 5 end-to-end tests for full per-phase language path |

---

## Step-by-Step Implementation

### Step 1 — `harness/spec_validation.json`
Add after `"app_type_requirements"`:
```json
"language_types": ["python", "typescript"]
```

---

### Step 2 — `harness/spec.py`

**2a. No regex constant needed** — language detection is a substring search against `language_types`, not a fixed bracket pattern.

**2b. `_extract_phases` — add `language_types` parameter; search title for any known language:**
```python
def _extract_phases(spec_text: str, language_types: list[str] | None = None) -> list[dict]:
    ...
    language = None
    if language_types:
        title_lower = title.lower()
        for lang in language_types:
            if lang in title_lower:
                language = lang
                break
    phases.append({"id": phase_id, "title": title, "language": language, ...})
```

This matches any format — `[python]`, `(python)`, bare word `python` — as long as the language name from `language_types` appears anywhere in the heading. Title is stored unchanged (no stripping).

**2c. `parse_spec` — load `language_types` from config and pass to `_extract_phases`:**
```python
language_types = config.get("language_types", [])
phases = _extract_phases(spec_text, language_types)
```

Then write `language` to state phases in the `write_phases` block as before:
```python
{"id": p["id"], "title": p["title"], "language": p["language"], "status": "pending", ...}
```

**2d. `check_spec_completeness` — Layer 3 (after existing Layer 2 block):**

Phase 1 is excluded — it is the project setup/bootstrap phase and may scaffold both Python and TypeScript simultaneously. All subsequent phases (Phase 2+) must have a recognized language name in their heading.

```python
language_types = config.get("language_types", [])
if language_types and phases:
    for phase in phases:
        if phase["id"] == 1:
            continue  # Phase 1 (project setup) is exempt from language tag requirement
        if phase["language"] is None:
            missing.append(
                f"Phase {phase['id']} title '{phase['title']}' has no language identifier. "
                f"Include one of {language_types} in the heading (e.g. [python])."
            )
```
Note: `phases` is extracted via `_extract_phases(spec_text, language_types)`. `phase["language"]` is `None` when no known language name is found in the title — the unknown-language case cannot occur because only values present in `language_types` are ever stored.

---

### Step 3 — `harness/state.py`

**`_apply_phase_fields`**: `allowed = {"status", "language"}`

`_apply_issue_fields` is unchanged — no `"language"` needed on issue objects.

---

### Step 4 — `harness/agents.py`

In `fix_issues`, replace:
```python
"Run pytest after all fixes. Respond with JSON only."
```
With:
```python
f"Run `{' '.join(profile['test_cmd'])}` after all fixes. Respond with JSON only."
```

---

### Step 5 — `harness/harness.py`

**5a. `__init__` — replace `self.profile: dict = {}`:**
```python
self.profiles: dict[int, dict] = {}   # phase_id → language profile
self._default_language: str = "python"
```

**5b. New method `profile_for`:**
```python
def profile_for(self, phase_id: int) -> dict:
    return self.profiles.get(phase_id) or get_profile(self._default_language)
```

**5c. First-run branch in `run()` — replace `self.profile = get_profile(args.language)`:**
```python
self._default_language = args.language
for p in self.phases:
    lang = p.get("language") or self._default_language
    self.profiles[p["id"]] = get_profile(lang)
# Backfill None language fields in state with resolved language
for sp in state["phases"]:
    if sp.get("language") is None:
        sp["language"] = self._default_language
save_state(state)
```

**5d. Resume branch — replace `self.profile = get_profile(language)`:**
```python
self._default_language = args.language if args.language != "python" else state.get("language", "python")
for sp in state.get("phases", []):
    lang = sp.get("language") or self._default_language
    self.profiles[sp["id"]] = get_profile(lang)
```

**5e. State machine loop — add `profile` derivation before dispatch:**
```python
profile = self.profile_for(phase_id)
if current_state == HarnessState.TASK_BUILD:
    current_state = self._do_task_build(state, phase_id, profile)
elif current_state == HarnessState.EXECUTING:
    current_state = self._do_executing(state, phase_id, profile)
elif current_state == HarnessState.REVIEWING:
    current_state = self._do_reviewing(state, phase_id, profile)
```

**5f. `_do_task_build(state, phase_id, profile)` — add `profile` parameter:**
- Replace `self.profile` → `profile` in `agents.build_tasks(...)` call
- Replace `self.profile` → `profile` in `sync_task_types(state, new_tasks, ...)` call

**5g. `_do_executing(state, phase_id, profile)` — add `profile` parameter:**
- Replace `profile=self.profile` → `profile=profile` in `agents.execute(...)` call

**5h. `_do_reviewing(state, phase_id, profile)` — add `profile` parameter:**
- Replace `self.profile` → `profile` in `agents.review_phase(...)` call
- No change to the issue dicts — language is not stamped on issues (looked up from phase at cleanup time)

---

### Step 6 — `harness/verify.py`

**New module-level helper:**
```python
def _phase_id_from_batch(batch: list) -> int:
    try:
        return int(batch[0]["id"].split(".")[0])
    except (IndexError, ValueError):
        return 1
```

**`verify_execution`:**
```python
phase_id = _phase_id_from_batch(batch)
profile = harness.profile_for(phase_id)
# Replace all harness.profile[x] → profile[x]
# Replace profile=harness.profile in agents.execute call → profile=profile
```

**`verify_fix`** (already has `phase_id` parameter):
```python
profile = harness.profile_for(phase_id)
# Replace harness.profile["test_cmd"] → profile["test_cmd"]
```

---

### Step 7 — `harness/fix.py`

**`run_batch_retry_loop`:**
```python
profile = harness.profile_for(phase_id)
# Replace profile=harness.profile → profile=profile in agents.execute call
```

**`run_fix_cycle`:**
```python
profile = harness.profile_for(phase_id)
# Replace harness.profile.get("review_exclude_paths", []) → profile.get(...)
# Replace profile=harness.profile in agents.fix_issues call → profile=profile
```

**`run_cleanup` — major change:**

Issue IDs encode the phase (`"2.3"` → phase 2). The phase has `"language"` in state. Group by phase_id, look up language, call `fix_issues` per group.

1. Build union `exclude_paths` across all phase profiles:
```python
all_exclude: set[str] = set()
for sp in state.get("phases", []):
    all_exclude.update(harness.profile_for(sp["id"]).get("review_exclude_paths", []))
exclude_paths = list(all_exclude)
```

2. Inside the `while True` loop, replace the single `agents.fix_issues` call with a per-phase group loop:
```python
by_phase: dict[int, list] = {}
for issue in still_open:
    pid = _parse_phase_id(issue["id"])   # existing helper in fix.py
    by_phase.setdefault(pid, []).append(issue)

for pid, phase_issues in by_phase.items():
    phase_obj = find_phase(state, pid) or {}
    lang = phase_obj.get("language") or harness._default_language
    profile = get_profile(lang)
    phase_debt_path = Path(f"workspace/tech_debt_phase{pid}.jsonl")
    phase_debt_path.write_text(
        "".join(json.dumps(i) + "\n" for i in phase_issues), encoding="utf-8"
    )
    try:
        result = agents.fix_issues(
            source_file=str(phase_debt_path),
            profile=profile,
            config=harness.config,
            failure_history=failure_history or None,
        )
    finally:
        phase_debt_path.unlink(missing_ok=True)
    # process result["signal"]["fixes"] — same logic as current single-language loop
```

3. Update `_finish()` to accept and run multiple test commands:
```python
def _finish(test_cmds: list[list] | None = None) -> None:
    for cmd in (test_cmds or [["pytest"]]):
        result = subprocess.run(cmd, capture_output=True, text=True)
        print(result.stdout[-1000:] if result.stdout else "(no output)")
        if result.returncode != 0:
            print(f"[WARN] {cmd[0]} reported failures — review manually.")
    print("[HARNESS] COMPLETE.")
```

4. Collect unique test commands from all phase profiles and pass to `_finish`:
```python
seen_cmds: list[list] = []
for sp in state.get("phases", []):
    cmd = harness.profile_for(sp["id"]).get("test_cmd", ["pytest"])
    if cmd not in seen_cmds:
        seen_cmds.append(cmd)
_finish(seen_cmds)
```

Also: add `from lang import get_profile` import to `fix.py` (needed for language-keyed profile lookup in `run_cleanup`).

---

## Test Cases

### Updates to existing test files

**`harness/tests/conftest.py`**
- `sample_state`: add `"language": "python"` to phase dict

**`harness/tests/integration/test_resume.py`**
- `_base_state`: add `"language": "python"` to both phase dicts
- New: `test_resume_mixed_language_state` — phases with `"language": "python"` and `"language": "typescript"` → assert `harness.profile_for(1)["name"] == "python"` and `harness.profile_for(2)["name"] == "typescript"`

**`harness/tests/integration/test_state_machine.py`**
- Add `"language": "python"` to inline phase dicts in `test_executing_task_status_transitions`

**`harness/tests/unit/test_spec.py`** (add 4 tests)
- `test_extract_phases_python_tag`: `"## Phase 1: Foundation [python]\n"`, `language_types=["python"]` → `language="python"`, `title="Foundation [python]"` (title unchanged)
- `test_extract_phases_typescript_tag`: `"## Phase 2: UI [typescript]\n"`, `language_types=["python","typescript"]` → `language="typescript"`
- `test_extract_phases_no_matching_language_is_none`: heading with no known language name → `language=None`
- `test_parse_spec_writes_language_to_state`: `write_phases=True` on spec with `[python]` headings, `language_types=["python"]` → `state["phases"][0]["language"] == "python"`

**`harness/tests/unit/test_spec_completeness.py`**
- Update `_COMMON_HEADINGS`: `"## Phase 1: Project Foundation"` → `"## Phase 1: Project Foundation [python]\n"`
- Update any other headings fixtures that include phase headers
- Add 4 new Layer 3 tests:
  - `test_phase_missing_language_fails`: Phase 2 heading with no known language name → error in result
  - `test_all_phases_have_language_passes_layer3`: Phase 2 `[python]` and Phase 3 `[typescript]` → no Layer 3 error
  - `test_language_identifier_case_insensitive`: `[Python]` on Phase 2 matches `"python"` in `language_types`
  - `test_phase1_exempt_from_language_check`: Phase 1 heading with no language name → no Layer 3 error (Phase 1 is always exempt)

**`harness/tests/unit/test_state.py`** (add 1 test)
- `test_apply_phase_fields_allows_language`: `update_state(state, entity_type="phase", phase_id=1, language="typescript")` → phase language updated

**`harness/tests/unit/test_harness.py`** (add 2 tests)
- `test_profile_for_returns_correct_profile`: `harness.profiles = {1: get_profile("python"), 2: get_profile("typescript")}` → `profile_for(2)["name"] == "typescript"`
- `test_profile_for_falls_back_to_default`: `harness.profiles = {}`, `harness._default_language = "python"` → `profile_for(99)["name"] == "python"`

**`harness/tests/unit/test_fix.py`**
- Update `_make_harness` (or equivalent): replace `h.profile = {...}` with `h.profile_for = MagicMock(return_value={...profile_dict...})`
- New: `test_run_cleanup_groups_issues_by_phase` — state with deferred issues from phase 2 (python) and phase 3 (typescript); mock `agents.fix_issues`; assert called twice, each with the correct profile and only that phase's issues
- New: `test_run_fix_cycle_uses_phase_language_profile` — mock `harness.profile_for` to return typescript profile for `phase_id=2`; assert `agents.fix_issues` receives `profile["name"] == "typescript"`

### New file: `harness/tests/unit/test_per_phase_language.py`
- `test_profiles_populated_from_spec`: spec with 3 phases (headings containing `python`, `python`, `typescript`) → `harness.profiles[3]["name"] == "typescript"`
- `test_untagged_phase_falls_back_to_default`: phase without tag + `--language python` → `profile_for(1)["name"] == "python"`
- `test_cleanup_groups_issues_by_phase`: deferred issues from phase 2 (python) and phase 3 (typescript) in state; mock `agents.fix_issues`; assert 2 calls, each with issues only from that phase and the correct profile
- `test_finish_runs_both_test_commands`: mock `subprocess.run`, call `_finish([["pytest"], ["npx", "vitest", "run"]])`, assert both commands invoked

---

## Ordering Constraints

```
1. spec_validation.json    (no deps)
2. spec.py                 (needs spec_validation.json for config contract)
3. state.py                (no deps — allowlist only)
4. agents.py               (no deps — string fix only)
5. harness.py              (needs spec.py + state.py)
6. verify.py               (needs harness.py for profile_for)
7. fix.py                  (needs harness.py + verify.py)
8. conftest.py             (update first, before other tests)
9. test files              (after all source changes)
```

---

## Verification

Run full harness test suite after implementation:
```
python -m pytest harness/ -v
```
Expected: 191 existing tests pass + new tests pass (0 regressions).

Manual smoke test with a two-phase mixed-language spec:
```markdown
## Phase 1: Backend Foundation [python]
Set up FastAPI project.

## Phase 2: Frontend UI [typescript]
Set up Phaser.js scene.
```
```
python harness/harness.py docs/spec.md --app-type web
```
Verify: phase 1 uses `code-builder.md` + `pytest`; phase 2 uses `frontend-builder.md` + `npx playwright test`.
