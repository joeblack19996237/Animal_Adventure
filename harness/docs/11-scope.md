# Scope

## V1 Scope (Must Have)

| Item | Status |
|------|--------|
| harness.py state machine + state.py state I/O | V1 |
| code-builder.md agent | V1 |
| code-reviewer.md agent | V1 (adapted from ECC) |
| state.json management (includes task_types registry) | V1 |
| review_report.md | V1 |
| Python coding rules | V1 |
| 5 hooks + hook_utils.py (verify + security + stop JSON schema validation + stop git commit + shared transcript parser) | V1 |
| .gitignore — excludes workspace/ from git; makes git add -A safe on first init | V1 |
| extract_signal() fallback in call_claude() | V1 |
| config.json — user-tunable params (timeouts, batch limits, retry thresholds, token budget default) | V1 |
| Per-mode subprocess timeouts (loaded from config.json) + TimeoutExpired → SubprocessError | V1 |
| stop_git_commit.py — stages files_changed from signal, no git add -A | V1 |
| Halt logic (3 attempts) | V1 |
| --resume flag (reads state.json) | V1 |
| TDD workflow in code-builder | V1 |
| TDD applicability self-assessment | V1 |
| harness verify_execution() + verify_fix() | V1 |
| verify_fix() write order: state.json first, review_report.md second | V1 |
| validate_spec() — validates phase count, titles, sequential IDs before TASK_BUILD | V1 |
| fix_issues() — all CRITICAL/HIGH fixed in one subprocess with failure_history | V1 |
| tech_debt.jsonl — accumulated MEDIUM/LOW deferred issues across all phases | V1 |
| run_cleanup() + CLEANUP state — fixes all deferred MEDIUM/LOW after all phases complete | V1 |
| Reviewer reads spec before reviewing | V1 |
| 4-dimension review (incl. Functionality) | V1 |
| Verdict-driven flow (APPROVE/WARN/BLOCK) | V1 |
| Agent files passed by path — agent reads via Read tool | V1 |
| task_type assignment in TASK_BUILD | V1 |
| sync_task_types() — dynamic task_type registry | V1 |
| calibrate.py — estimate_call() + plan_batches() | V1 |
| usage.jsonl — per-call cost accounting | V1 |
| max_batch_tokens = 160K ceiling (config.json) | V1 |
| calibration.json — seed + calibrated overhead/output per (mode, task_type) | V1 |
| Calibrated overhead/output (p90 per mode/task_type) written back to calibration.json | V1 |
| Multi-EXECUTE batching via plan_batches() + execute() | V1 |
| MIN_ENTRIES_BEFORE_BATCHING = 5 guard — single-task mode until calibration data is mature | V1 |
| execute() timeout scales with batch size (len(tasks) × SUBPROCESS_TIMEOUT["EXECUTE"]) | V1 |
| Proportional usage split (execute_weight / output_weight) for batch log_usage() | V1 |
| Token budget guard — `--token-budget N` (default 400,000); stops before next subprocess if 5-hour window total would exceed budget; `get_session_token_total()` sums last-5-hour window from usage.jsonl | V1 |

## Deferred to V1.1

| Item | Reason |
|------|--------|
| CALIBRATE agent call post-run | Needs usage history to analyse |
| Prompt caching via stable content injection | Defer until usage.jsonl shows token cost justifies complexity over file-path approach |

## Deferred to V2

| Item | Reason |
|------|--------|
| Java support | Add `"java"` entry to `LANGUAGE_PROFILES` in `lang.py` + `.claude/rules/java/java-standards.md` + `.claude/agents/java-code-builder.md` + `.claude/agents/java-code-reviewer.md`. No changes to harness.py, state.py, agents.py, calibrate.py, or state machine. |
| `project_compile_cmd` in `LanguageProfile` | Java requires classpath-aware compilation (`mvn compile` / `gradle compileJava`) — incompatible with the per-file `{file}` substitution in `verify_execution()`. Add optional `project_compile_cmd: list \| None` to `LanguageProfile`; when present, `verify_execution()` runs it once instead of the per-file loop. Python profile sets it to `null`. |
| Agent self-improvement | Complex |
| ECC cost log integration | --log-ecc-costs flag, append to ~/.claude/metrics/costs.jsonl |
