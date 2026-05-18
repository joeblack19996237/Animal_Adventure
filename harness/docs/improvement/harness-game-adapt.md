# Harness Adaptation: Phaser.js + FastAPI Game Development

## Context

Adds TypeScript/Phaser.js support to the autonomous-dev-harness alongside the existing Python
profile. Enables building a fullstack game: Phaser.js + TypeScript client (browser), Python +
FastAPI + WebSocket server, SQLite WAL database.

Architecture: two separate harness runs — `--language python` for backend, `--language typescript`
for frontend. No harness core state-machine changes required.

All changes are backward-compatible. Existing Python projects are unaffected.

---

## Files to Create (5 new files)

### 1. `.claude/agents/frontend-builder.md`

New agent for TypeScript/Phaser development. Same JSON signal contract as `code-builder.md`.

**Differences from `code-builder.md`:**

| Section | code-builder.md | frontend-builder.md |
|---------|----------------|---------------------|
| Description | "expert Python developer" | "expert TypeScript and Phaser.js developer" |
| Rules ref | `python-standards.md` | `typescript-standards.md` |
| Compile self-check | `python -m py_compile <file>` | `npx tsc --noEmit` |
| Test self-check | `pytest` passes | `npx playwright test` passes |
| TDD exemptions | config, migrations, `__init__.py` | `*.config.ts`, `tsconfig.json`, Phaser scene stubs without logic, `index.html` |

**task_type table:**

| task_type | When to use |
|-----------|-------------|
| `foundation` | Vite config, tsconfig, package.json, project scaffold |
| `scene` | Phaser Scene classes (thin rendering layer only) |
| `entity` | Game entity classes: Player, NPC (pure logic, no Phaser dependency) |
| `network` | WebSocket client, protocol type definitions |
| `state` | Game state machines, client-side store |
| `ui` | HUD, menus, overlay components |
| `testing` | Playwright E2E specs, Vitest fixtures |
| `asset_scaffold` | Stub asset generation (TDD always skipped) |

**EXECUTE mode completion self-checks (add to existing self-check list):**
- `npx tsc --noEmit` passes (no type errors in any changed file)
- All `files_changed` exist and are non-empty
- If TDD applied: `tests/` file exists, `npx vitest run` passes
- No `any` types without explicit `// justified: <reason>` comment
- No `async` function inside `.forEach()` — use `for...of` or `Promise.all`
- No floating promises — every `async` call is `await`ed or has `.catch()`
- `===` throughout, not `==`
- Phaser thin layer rule: `Scene.update()` contains only calls to entity/state methods

---

### 2. `.claude/rules/typescript/typescript-standards.md`

New TypeScript rules file, parallel to `python-standards.md`.

**Content — adapt from ECC sources listed below:**

#### Style (from `typescript-reviewer.md` MEDIUM/Best-Practices)
- 2-space indentation, semicolons required, single quotes
- Max line length: 100 characters
- Two blank lines between top-level definitions; one between methods
- camelCase for variables/functions; PascalCase for classes/interfaces/types/enums
- No `var` — use `const` by default, `let` only when reassignment needed

#### Type Safety (from `typescript-reviewer.md` HIGH)
- `tsconfig.json` must have `"strict": true` — never weaken it
- No `any` — use `unknown` and narrow, or define a precise type
- No non-null assertion `value!` without a preceding guard
- No `as Type` casts to silence errors — fix the type
- All public functions must have explicit return type annotations
- Use `X | Y` union syntax, not `Optional<X>` or `Union[X, Y]`

#### Async Patterns (from `typescript-reviewer.md` HIGH)
- Every `async` function call must be `await`ed or have `.catch()`
- Never `array.forEach(async fn)` — use `for...of` or `Promise.all(array.map(async fn))`
- No floating promises in event handlers or constructors
- `try/catch` around every `JSON.parse()` call

#### Immutability (from ECC `coding-standards/SKILL.md`)
- No mutable module-level variables — use constants or class instances
- Use spread for state updates: `{ ...state, field: newValue }` not `state.field = newValue`
- Prefer `readonly` on class fields that should not change after construction

#### Error Handling
- Never empty `catch` — log or re-throw
- Always `throw new Error("message")`, not `throw "message"`
- Wrap all WebSocket `send()` calls in try/catch — connection may drop

#### File I/O / Browser Patterns
- No `fs` module (browser environment) — use `fetch` for HTTP, `WebSocket` for WS
- `import.meta.env` for environment variables (Vite), not `process.env`
- All asset paths relative to `public/` directory

#### Phaser-Specific (new rules)
- Scene classes are thin rendering layers — no business logic
- `Scene.update(time, delta)` must only call entity/state methods; never contain `if/else` game logic
- `Scene.create()` wires entities to Phaser game objects only
- All game logic (state machines, physics calculations, rule evaluation) lives in `src/entities/`
  or `src/state/` — testable without Phaser via Vitest

#### Testing
- Unit/integration tests use Vitest (`*.test.ts` files in `tests/`)
- E2E tests use Playwright (`*.spec.ts` files in `tests/e2e/`)
- Test names: `it("returns empty list when no players", ...)` — behavior description, not method name
- Playwright tests must register `page.on("pageerror")` and `page.on("console")` error listeners
- No test-specific logic in production code

---

### 3. `.claude/hooks/post_ts_lint_format.py`

Parallel to `post_py_lint_format.py`, runs after every Write/Edit on `.ts`/`.tsx` files.

```python
import json
import subprocess
import sys

data = json.loads(sys.stdin.read())
file_path = data.get("tool_input", {}).get("file_path", "")

if not file_path.endswith((".ts", ".tsx")):
    sys.exit(0)

# Auto-fix formatting silently
subprocess.run(["npx", "prettier", "--write", file_path], capture_output=True)
# Auto-fix safe lint issues silently
subprocess.run(["npx", "eslint", "--fix", file_path], capture_output=True)

# Report remaining violations the agent must fix manually
result = subprocess.run(
    ["npx", "eslint", file_path],
    capture_output=True,
    text=True,
)
if result.returncode != 0 and result.stdout.strip():
    print(
        f"[ESLINT] Lint violations in {file_path!r} — fix before completing the task:\n"
        f"{result.stdout.strip()}"
    )

sys.exit(0)
```

---

### 4. `.claude/settings.frontend-builder.json`

Settings file for frontend-builder agent (TASK_BUILD, EXECUTE, FIX modes).
Parallel to `settings.builder.json`, with TypeScript lint/format hooks replacing Python hooks.

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [{"type": "command", "command": "python .claude/hooks/stop_validate_json.py",
                   "timeout_ms": 10000}],
        "description": "Validate agent output is valid JSON before subprocess exits",
        "id": "stop:validate-json"
      },
      {
        "hooks": [{"type": "command", "command": "python .claude/hooks/stop_git_commit.py",
                   "timeout_ms": 30000}],
        "description": "Stage files_changed from signal and commit",
        "id": "stop:git-commit"
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Write",
        "hooks": [{"type": "command",
                   "command": "python .claude/hooks/post_ts_lint_format.py",
                   "timeout_ms": 15000}],
        "description": "Run prettier + eslint on TypeScript files after Write",
        "id": "post:write:ts-lint-format"
      },
      {
        "matcher": "Edit",
        "hooks": [{"type": "command",
                   "command": "python .claude/hooks/post_ts_lint_format.py",
                   "timeout_ms": 15000}],
        "description": "Run prettier + eslint on TypeScript files after Edit",
        "id": "post:edit:ts-lint-format"
      },
      {
        "matcher": "Write",
        "hooks": [{"type": "command",
                   "command": "python .claude/hooks/post_write_verify.py",
                   "timeout_ms": 5000}],
        "description": "Verify file exists after Write",
        "id": "post:write:verify-exists"
      },
      {
        "matcher": "Edit",
        "hooks": [{"type": "command",
                   "command": "python .claude/hooks/post_edit_verify.py",
                   "timeout_ms": 5000}],
        "description": "Verify edit applied after Edit",
        "id": "post:edit:verify-changed"
      }
    ]
  }
}
```

---

### 5. `docs/harness-game-adapt.md`

This document (already written as part of implementation).

---

## Files to Modify (5 files)

### 1. `harness/lang.py`

**Change 1:** Add `builder_settings` and `reviewer_settings` keys to Python profile:
```python
"builder_settings": ".claude/settings.builder.json",
"reviewer_settings": ".claude/settings.reviewer.json",
```

**Change 2:** Update Python profile `test_cmd`:
```python
"test_cmd": ["pytest", "--asyncio-mode=auto"],  # was ["pytest"]
```

**Change 3:** Add TypeScript profile:
```python
"typescript": {
    "name": "typescript",
    "compile_cmd": ["npx", "tsc", "--noEmit"],
    "compile_extensions": ["*.ts", "*.tsx"],
    "test_cmd": ["npx", "playwright", "test"],
    "build_model": "claude-haiku-4-5-20251001",
    "execute_model": "claude-sonnet-4-6",
    "builder_agent": ".claude/agents/frontend-builder.md",
    "reviewer_agent": ".claude/agents/code-reviewer.md",
    "builder_skill": ".claude/skills/tdd-workflow/SKILL.md",
    "reviewer_skill": ".claude/skills/security-review/SKILL.md",
    "common_rules": ".claude/rules/common/coding-standards.md",
    "rules_file": ".claude/rules/typescript/typescript-standards.md",
    "builder_settings": ".claude/settings.frontend-builder.json",
    "reviewer_settings": ".claude/settings.reviewer.json",
    "task_types": [
        "foundation", "scene", "entity", "network",
        "state", "ui", "testing", "asset_scaffold",
    ],
    "review_exclude_paths": [
        ".claude", "harness", "harness/docs",
        "CLAUDE.md", "README.md", "dist/", "playwright-report/",
    ],
},
```

---

### 2. `harness/agents.py`

Four locations where settings path is hardcoded — replace with profile lookup.

The `profile` dict is already a parameter at all 4 call sites (check function signatures).

```python
# TASK_BUILD (~line 151)  was: ".claude/settings.builder.json"
settings_file=profile.get("builder_settings", ".claude/settings.builder.json"),

# EXECUTE (~line 196)     was: ".claude/settings.builder.json"
settings_file=profile.get("builder_settings", ".claude/settings.builder.json"),

# REVIEW (~line 228)      was: ".claude/settings.reviewer.json"
settings_file=profile.get("reviewer_settings", ".claude/settings.reviewer.json"),

# FIX (~line 274)         was: ".claude/settings.builder.json"
settings_file=profile.get("builder_settings", ".claude/settings.builder.json"),
```

---

### 3. `harness/requirements.txt`

Add two lines:
```
pytest-asyncio~=0.24
httpx~=0.27
```

---

### 4. `.claude/agents/code-reviewer.md`

Add "TypeScript Addendum" section at end of file. Content from ECC `typescript-reviewer.md`:

```markdown
## TypeScript Addendum

When `git diff` contains `.ts` or `.tsx` files, run these checks first:

```bash
npx tsc --noEmit
npx eslint . --ext .ts,.tsx
```

If either fails, stop and report — do not continue review until they pass.

### CRITICAL — TypeScript Security
- `eval` or `new Function` with user-controlled input — arbitrary code execution
- User input assigned to `innerHTML` or `document.write` — XSS
- Merging untrusted objects without `Object.create(null)` — prototype pollution
- `child_process` with unvalidated user input

### HIGH — Type Safety
- `any` without justification — disables type checking; use `unknown` and narrow
- Non-null assertion `value!` without a preceding guard
- `as Type` cast to silence errors — fix the type instead
- `tsconfig.json` changes that weaken `strict: true`

### HIGH — Async Correctness
- `async` function called without `await` or `.catch()` — unhandled rejection
- `array.forEach(async fn)` — does not await iterations; use `for...of`
- Floating promises in constructors or event handlers

### HIGH — Error Handling
- Empty `catch` blocks with no action
- `JSON.parse` without try/catch — throws on invalid input
- `throw "string"` — always `throw new Error("message")`

### HIGH — Idiomatic Patterns
- `var` usage — use `const` or `let`
- Missing explicit return types on public functions
- `==` instead of `===`
```

---

## Verification

Run these after all changes to confirm nothing is broken:

```bash
cd D:/AI/claude_code/autonomous-dev-harness

# 1. Python profile unchanged
python -c "from harness.lang import get_profile; p = get_profile('python'); print(p['test_cmd'])"
# Expected: ['pytest', '--asyncio-mode=auto']

# 2. TypeScript profile loads
python -c "from harness.lang import get_profile; p = get_profile('typescript'); print(p['builder_agent'])"
# Expected: .claude/agents/frontend-builder.md

# 3. Settings JSON valid
python -c "import json; json.load(open('.claude/settings.frontend-builder.json')); print('OK')"

# 4. Hook syntax valid
python -m py_compile .claude/hooks/post_ts_lint_format.py && echo OK

# 5. agents.py has profile-based settings (not hardcoded)
grep -n "builder_settings" harness/agents.py
# Expected: 3 matches (TASK_BUILD, EXECUTE, FIX)
grep -n "reviewer_settings" harness/agents.py
# Expected: 1 match (REVIEW)

# 6. Both profiles listed
python -c "from harness.lang import LANGUAGE_PROFILES; print(list(LANGUAGE_PROFILES))"
# Expected: ['python', 'typescript']
```

---

## Summary

| File | Action | Effort |
|------|--------|--------|
| `.claude/agents/frontend-builder.md` | CREATE — TypeScript/Phaser agent | 30 min |
| `.claude/rules/typescript/typescript-standards.md` | CREATE — TypeScript rules | 20 min |
| `.claude/hooks/post_ts_lint_format.py` | CREATE — prettier+eslint hook | 5 min |
| `.claude/settings.frontend-builder.json` | CREATE — settings with TS hooks | 5 min |
| `docs/harness-game-adapt.md` | CREATE — this document | done |
| `harness/lang.py` | MODIFY — add TypeScript profile + settings keys | 10 min |
| `harness/agents.py` | MODIFY — profile-based settings routing (4 lines) | 5 min |
| `harness/requirements.txt` | MODIFY — add pytest-asyncio + httpx | 1 min |
| `.claude/agents/code-reviewer.md` | MODIFY — add TypeScript addendum | 10 min |
| `.claude/agents/code-builder.md` | No change needed | — |
