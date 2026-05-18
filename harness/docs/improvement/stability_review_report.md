# Harness Stability Review Report

Date: 2026-05-13

Scope: static review of the autonomous harness code, with emphasis on run stability, resume behavior, state integrity, subprocess timeout handling, commit safety, and observability.

## Summary

The harness already has useful stability foundations: atomic state writes, run locks, structured events, resume reconciliation, targeted verification, mocked e2e coverage, and explicit handling for external dependency blocks. After revalidation, the strongest confirmed risks are the stop hook trusting broad agent-declared path values before the verifier can intervene, EXECUTE signals not being tied to the active runtime task, and limited observability around task-level external-dependency blocks.

## Findings

### P1 - Stop hook can stage and commit unintended files via broad pathspecs

Files:

- `.claude/hooks/stop_git_commit.py:60`
- `.claude/hooks/stop_git_commit.py:65`
- `.claude/hooks/stop_git_commit.py:77`

The stop hook treats every agent-reported `files_changed` entry as safe if `(root / f).resolve()` remains inside the project root, then passes those raw values directly to `git add`. This blocks obvious `../` escapes, but it still permits broad values such as `.` and directory-like path values. In an EXECUTE or FIX signal, an agent can report `files_changed: ["."]`; the hook runs `git add .` and commits every dirty/untracked file in the temporary worktree. I reproduced this in a throwaway Git repository: with `intended.py` and `unrelated.py` both untracked, a signal containing `files_changed=["."]` caused both files to appear in the hook-created commit.

The fallback verifier in `harness/verify.py` is narrower because it gates through `safe_changed_signal_files()`, so the primary bug is the stop hook's pre-verification staging path.

Impact: a single bad agent signal can contaminate task/fix commits with unrelated user changes or runtime artifacts, which undermines resume reconciliation and makes later review diffs unreliable.

Recommendation:

- Add `--` before path arguments in every `git add`.
- Reject directories, empty paths, `.`, pathspec magic, wildcard-like pathspecs, and non-normal file paths in `stop_git_commit.py`.
- Require each signaled path to resolve to an actual file or deletion path that appears in `git status --porcelain -z -- <path>` before staging.
- Add regression tests where `files_changed` is `.`, a directory, `:(glob)*`, and an unrelated dirty file exists.

### P1 - EXECUTE signals can update tasks outside the active task/phase

Files:

- `.claude/hooks/stop_validate_json.py:49`
- `.claude/hooks/stop_validate_json.py:52`
- `.claude/hooks/stop_validate_json.py:55`
- `harness/phase_handlers.py:141`
- `harness/phase_handlers.py:166`
- `harness/phase_handlers.py:173`
- `harness/phase_handlers.py:176`

The EXECUTE schema validates only that `phase_id` is an integer and task IDs match `N.M`. `handle_executing()` sends one active task to the agent, but then iterates over every returned `signal["tasks"]` entry and updates whatever task ID the signal contains. There is no check that `signal.phase_id == phase_id`, that every returned task ID belongs to the active phase, or that it is the active task being executed.

Impact: a malformed or confused agent response can mark a task from another phase complete, increment the wrong task's errors, or create commit messages that do not match the state transition. If the wrong task ID exists, state can be corrupted; if it does not exist, `update_state()` raises and the harness crashes after the subprocess work. This can make resume skip required work or reconcile the wrong commit.

Recommendation:

- In `handle_executing()`, reject or fail the active task unless the returned signal has exactly one result for the expected active task ID and matching `phase_id`.
- Add the same runtime-context check to `stop_git_commit.py` before it commits: read `workspace/state.json`, confirm `signal.phase_id == current_phase`, and confirm the completed task IDs are currently `building` or otherwise expected for the active subprocess.
- Apply similar phase-ID validation to TASK_BUILD, REVIEW, FIX, and EVALUATE paths where the hook schema cannot know runtime context.
- Add unit tests for wrong phase ID, extra task IDs, missing active task ID, and duplicate task IDs in agent signals.

### P3 - Blocked task status is hidden from `--status` and loses current-blocker visibility on resume

Files:

- `harness/harness.py:93`
- `harness/harness.py:98`
- `harness/harness.py:130`
- `harness/harness.py:137`
- `harness/state.py:310`
- `harness/state.py:314`
- `harness/state.py:315`
- `harness/tests/unit/test_harness.py:491`

Task-level external dependency blocks are recorded as `task.status="blocked_external_dependency"`, but `_summarize_status()` only considers phase, review, cleanup, and evaluate errors. It does not surface task-level `last_error`. On resume, `reset_interrupted_tasks()` converts both `building` and `blocked_external_dependency` tasks back to `pending`. That reset is intentional and already covered by `test_task_external_block_resets_to_pending_on_resume`, so the issue is not "resume cannot work"; it is that the current blocker is hard to see before retry and not clearly preserved as blocker history after retry starts.

Impact: when EXECUTE is blocked by Claude CLI auth, rate limits, missing tools, or another external dependency, `--status` may not show the true current blocker. A later `--resume` may retry as designed, but operators lose quick visibility into why the previous run stopped.

Recommendation:

- Include task-level blocked/error status and `last_error` in `_summarize_status()`.
- Preserve the existing auto-retry behavior if desired, but copy the blocker into `last_blocked_error`, `blocked_retry_count`, or a task-level history field before resetting to `pending`.
- Update tests to assert both behaviors: `--status` reports the blocked task, and `--resume` retries while preserving the blocker history.

### P2 - Timeout handling retries without proving the timed-out process tree is gone

Files:

- `harness/subprocess_runner.py:69`
- `harness/subprocess_runner.py:72`
- `harness/subprocess_runner.py:73`
- `harness/agents.py:142`
- `harness/agents.py:145`

`run_claude_process()` delegates timeout handling to `subprocess.run()`. Python terminates and waits for the direct child process on timeout, but this code does not explicitly terminate or wait on the whole descendant process tree before `call_claude()` retries the same prompt once. On Windows the code starts a new process group, but `subprocess.run()` does not use that group to kill descendants. If the Claude CLI or a Bash tool spawned child processes, those children may keep writing files while the retry starts.

Impact: the second attempt may run against a workspace still being mutated by the timed-out attempt. That can cause nondeterministic commits, test failures, or stale locks from child processes.

Recommendation:

- Replace `subprocess.run()` with `Popen` so timeout handling can terminate the process group/tree explicitly.
- On Windows, use `taskkill /T /F /PID <pid>` or an equivalent process-tree termination strategy after timeout.
- On POSIX, use `start_new_session=True` and kill the process group.
- Add an event that records whether termination succeeded before retrying.

### P3 - Stale lock detection can be fooled by PID reuse

Files:

- `harness/run_lock.py:22`
- `harness/run_lock.py:27`
- `harness/run_lock.py:36`
- `harness/run_lock.py:97`
- `harness/run_lock.py:110`

The run lock stores only the PID, cwd, spec metadata, and `started_at`. `_pid_alive()` treats any currently alive process with the same PID as an active harness. If the original harness crashes and the OS later reuses the PID for another process, `clear_stale_lock()` will refuse to clear the lock.

Impact: rare, but on long-lived Windows machines it can leave the harness blocked until the user manually clears the lock or uses a more informed stale-lock tool.

Recommendation:

- Store and verify process creation time or command identity when possible.
- Include a lock owner token in both `run.lock` and `harness.pid`.
- Make `--clear-stale-lock` print richer diagnostics when PID exists but does not look like a harness process.

## Suggested Fix Order

1. Harden `stop_git_commit.py` path validation and `git add --` usage.
2. Add runtime phase/task signal validation in both `phase_handlers.py` and the stop commit hook.
3. Improve task-level blocked status reporting while preserving the intended retry behavior.
4. Rework subprocess timeout cleanup around process groups.
5. Add PID creation-time/owner-token checks to run lock handling.

## Tests To Add

- Hook test: `files_changed=["."]` must not stage unrelated files.
- Hook test: directory path and Git pathspec magic are rejected.
- Execute handler test: wrong `signal.phase_id` fails the active task.
- Execute handler test: signal for `2.1` while executing `1.1` is rejected.
- Status test: blocked EXECUTE task appears in `--status` with `last_error`.
- Resume/status test: blocked EXECUTE task appears in `--status`, and resume preserves blocker history while retrying.
- Timeout test: first Claude process is terminated before retry starts.

## Verification

This review was primarily static. A targeted throwaway-repository repro confirmed the stop-hook `files_changed=["."]` behavior. No full test suite was run as part of the review.
