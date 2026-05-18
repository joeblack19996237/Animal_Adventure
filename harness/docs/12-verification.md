# Verification Plan

1. Write a minimal test spec: 2 phases, 2 tasks each (one logic task, one config task), Python (simple CLI app)
2. Run `python harness/harness.py docs/spec.md`
3. Verify state.json updated after each task with `tdd_applied` or `tdd_skipped` and correct `task_type`
4. Verify state.json populated with tasks and task_types after TASK_BUILD completes
4b. Verify logic task has a `tests/` file; config task does not
4c. Verify each task produces a git commit — `git log --oneline` shows one commit per task
4d. Verify usage.jsonl has one entry per subprocess with estimation_error populated
5. Verify review_report.md created after phase 1 completes with `## Summary` + verdict
5b. Verify reviewer only looks at files in `git diff {sha}..HEAD`
5c. Verify review contains at least one `[FUNCTIONALITY]` dimension check
6. Kill harness mid-run, run with `--resume` — confirm it picks up correctly
6b. Introduce two CRITICAL issues; verify both are sent to one subprocess in FIX mode; verify signal["fixes"] has two entries
6c. Simulate one issue with status="open" in the fix signal — verify harness passes failure_history into the next subprocess covering all remaining open issues; fixed issues marked fixed in state.json
6d. Kill harness after state.json write (WRITE 1) but before review_report.md removal (WRITE 2) — verify on resume the state is consistent and issue is not re-attempted
7. Manually set a task `attempts: 2` in state.json, re-run — verify halt fires on 3rd
7b. Simulate subprocess timeout: set SUBPROCESS_TIMEOUT["EXECUTE"] = 1, run a task — verify TimeoutExpired is caught, task records status="error" in state.json, harness exits cleanly
8. Test stop_validate_json.py: run a `claude -p` session that emits prose-wrapped JSON — verify hook catches it, agent self-corrects, and `call_claude()` receives a clean signal
8b. Test Stop hook guard: simulate `stop_hook_active=True` in hook input — verify hook exits 0 and `extract_signal()` handles the residue in harness
8c. Test stop_git_commit.py (EXECUTE): verify hook reads signal["tasks"], collects files_changed from entries where status=="complete", stages only those files, commits with feat(phase-N) message — no unintended files staged
8d. Test stop_git_commit.py (FIX): verify hook reads signal["fixes"], collects files_changed from entries where status=="fixed" only, skips open/deferred entries
8e. Test stop_git_commit.py (TASK_BUILD/REVIEW): verify hook exits 0 without committing
9. Test hook: run a `claude -p` session that tries `rm -rf *` — verify blocked (exit 2)
10. Test hook: Write a file, verify hook confirms existence
11. Inject a syntax error into a generated file — verify harness `verify_execution()` catches it and retries without incrementing attempts
12. Introduce a new task_type via the agent — verify sync_task_types() adds it to state.json
13. Test stop_validate_json.py schema validation: emit a signal missing a required field (e.g. omit tasks[].task_type in EXECUTE mode) — verify hook rejects it with exit 1, agent self-corrects within same subprocess, call_claude() receives a valid signal
14. Introduce two MEDIUM/LOW issues in the review — verify harness defers them (status="deferred") and appends to tech_debt.jsonl; after all phases complete, run CLEANUP pass and verify deferred issues are fixed and tech_debt.jsonl entries updated
14b. After CLEANUP pass completes, verify review.status is "fixed" in state.json for the relevant phase
15. Verify state.py imports cleanly with no harness.py dependency: `python -c "from harness.state import load_state, save_state"` — no import error

---

## Reuse From ECC (codebase: D:\AI\claude_code\everything-claude-code)

| ECC File | How Used |
|----------|----------|
| `agents/code-reviewer.md` | Copy review checklist verbatim into new `.claude/agents/code-reviewer.md` |
| `scripts/gan-harness.sh` | Model loop structure, score/plateau logic → translate to Python |
| `hooks/hooks.json` | Model hook schema for .claude/settings.json |
| `skills/autonomous-loops/SKILL.md` | Reference for sequential pipeline pattern |
| `scripts/hooks/cost-tracker.js` | Reference implementation for calibrate.py — same data source (`usage.input_tokens` from claude CLI JSON); V1 logs to `workspace/usage.jsonl`, V2 adds opt-in append to `~/.claude/metrics/costs.jsonl` |

## Phase 11 Harness Reliability Regression

- Simulate REVIEW timeout and assert `phase.status="building"`, `review.status="error"`, `review.last_error` populated, and `--resume` returns to REVIEWING without rebuilding completed tasks.
- Simulate interrupted `task.status="building"` and assert resume resets it to `pending`, while `complete`, `halted`, and `error` tasks are not reset incorrectly.
- Verify `workspace/events.jsonl` and `workspace/harness.log` are created during mocked E2E and contain startup, state transition, subprocess, verification, halt, or complete events as applicable.
- Verify `workspace/run.lock` and `workspace/harness.pid` reject parallel runs, preserve locks after unexpected crashes, and clear stale locks only when the PID is gone.
- Verify hook and fallback commit gates use pre/post snapshots and signal-listed safe paths; unrelated dirty or untracked files must not be staged.
- Run deterministic harness E2E in `harness/tests/e2e/` with mocked Claude. These tests validate harness behavior, not generated fixture app completeness.
- Keep live Claude smoke E2E opt-in with `HARNESS_LIVE_E2E=1`; it is skipped by default.
