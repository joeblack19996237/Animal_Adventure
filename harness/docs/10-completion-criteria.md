# Completion Criteria

Phase 11 harness completion additionally requires the state machine to advance without stale locks, unrelated commits, or unresolved blocking review issues. A blocking FIX does not count as complete until targeted re-review approves the fixed CRITICAL/HIGH issues. Commit gates must stage only files changed after the task started and listed in the agent signal.

## Task Classification (code-builder TASK_BUILD mode)

| Check | Who runs it | Fail action |
|-------|------------|-------------|
| Phase spec read in full before classifying | Agent self-check | Do not emit signal |
| Every task has `id`, `title`, and `task_type` | `stop_validate_json.py` schema validation | Stop hook rejects signal; agent self-corrects within subprocess |
| `task_type` matches a known type or is a valid new domain | Agent self-check | Use closest known type or introduce a descriptive new one |
| Tasks cover all requirements in the phase spec — none omitted | Agent self-check | Add missing tasks before emitting signal |
| No files created or modified — no git commit | Agent self-check | TASK_BUILD emits JSON only; any file writes are an error |

## Task Execution (code-builder EXECUTE mode)

| Check | Who runs it | Fail action |
|-------|------------|-------------|
| All task files exist and non-empty | Agent self-check | Emit `failed` signal → attempts++ |
| `py_compile` clean on all new `.py` files | Agent self-check + harness `verify_execution()` | Retry via `run_batch_retry_loop()` — no attempts increment |
| TDD: failing test written before implementation | Agent self-check | Emit `failed` signal → attempts++ |
| TDD: `pytest` passes after implementation | Agent self-check + harness `verify_execution()` | Retry via `run_batch_retry_loop()` — no attempts increment |
| No `print()`, bare `except:`, or `TODO` in new code | Agent self-check | Emit `failed` signal → attempts++ |
| `files_changed` lists all created/modified files | `stop_validate_json.py` schema validation | Stop hook rejects signal; agent self-corrects within subprocess |
| git commit made with correct files and message | `stop_git_commit.py` Stop hook + `verify_execution()` empty-diff guard | Empty diff (`pre_sha == HEAD`) → `verify_execution()` returns a failed task signal; retry happens in `run_batch_retry_loop()` so external dependency failures remain resumable |
| If TDD not applicable: `tdd_skipped` reason in signal | `stop_validate_json.py` schema validation | Stop hook rejects signal; agent self-corrects within subprocess |

## Code Review (code-reviewer REVIEW mode)

| Check | Who runs it | Fail action |
|-------|------------|-------------|
| Spec files read before reviewing | Agent self-check | Do not proceed to review |
| `git diff {sha}..HEAD` run to scope files | Agent self-check | Do not proceed to review |
| All 4 dimensions checked (functionality, security, performance, design) | Agent self-check | Do not emit signal |
| Every issue has severity, file+line, description, fix, `Status: open` | Agent self-check | Do not emit signal |
| `## Summary` section with verdict in `review_report.md` | Agent self-check | Do not emit signal |
| Verdict is one of APPROVE / WARN / BLOCK | `stop_validate_json.py` schema validation | Stop hook rejects signal; agent self-corrects within subprocess |
| APPROVE/WARN: no open CRITICAL or HIGH issues in report | Agent self-check | Re-evaluate verdict — emit BLOCK if CRITICAL/HIGH found |
| BLOCK: at least one CRITICAL or HIGH issue present | Agent self-check | Re-evaluate verdict — emit APPROVE/WARN if none found |

## Issue Fix (code-builder FIX mode — all CRITICAL/HIGH in one subprocess)

| Check | Who runs it | Fail action |
|-------|------------|-------------|
| All open issues read from `review_report.md` before starting | Agent self-check | Do not proceed |
| Each fix addresses its specific issue (not a workaround) | Agent self-check | Emit per-issue `status: "open"` in signal |
| `pytest` passes after all fixes — no regressions | Agent self-check + harness `verify_fix()` | All issues treated as open, retry |
| Per-issue status reported in `signal["fixes"]` array | `stop_validate_json.py` schema validation | Stop hook rejects signal; agent self-corrects within subprocess |
| Open issues: `reason` present in signal; failure_history passed to next subprocess | Harness builds failure_history | — |
| Each completed fix includes `files_changed` | `stop_validate_json.py` schema validation | Stop hook rejects signal; agent self-corrects within subprocess |
| git commit with correct files for completed fixes | `stop_git_commit.py` Stop hook | Hook logs warning to stderr; harness empty-diff guard catches missing commits |
