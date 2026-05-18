# Harness Open Issues Resolution Plan

## Summary

目标是用最小复杂度解决当前 open issues：不引入复杂 token 预算预测器，而是采用 **fail closed + lightweight observability + targeted verification hygiene**。

核心原则：

- 429 长等待只处理 Claude API 429 reset，不影响正常长任务执行。
- harness 文档性/验证配置导致的失败不再消耗 agent retry；直接 halt、记录原因、等待人工介入。
- token 优化重点放在减少无效 retry、减少重复 prompt、提升可观测性，而不是 pre-call token 估算。
- 自动阶段总结不作为本轮实现目标；改为通过 call id 和现有 artifacts 提高按需分析能力。

执行时第一步必须先把本 plan 保存到：

`harness/docs/improvement/harness-open-issues-resolution-plan-2026-05-17.md`

## Key Changes

### 1. 429 Resumable Wait

- 在 `harness/agents.py` 中仅对 `api_error_status == 429` 且 `_external_dependency_retry_delay()` 成功解析 reset delay 的场景应用新逻辑。
- 新增配置，例如 `external_dependency.max_in_process_wait_seconds = 900`。
- 若 `retry_delay <= threshold`，保持当前短等待行为。
- 若 `retry_delay > threshold`：
  - 写入 `external_dependency_context.json`
  - 执行现有 cleanup/preflight 逻辑
  - emit `external_dependency_wait_deferred`
  - 抛出 `ExternalDependencyError`，让 harness 进入 blocked/resumable 状态
- 明确不对普通 subprocess 长运行时间做判断；普通长任务仍由 timeout/process cleanup 机制处理。

### 2. Stable `call_id`

- 在 `agents.call_claude()` 入口生成稳定 `call_id`。
- 将 `call_id` 写入：
  - Claude subprocess start/end/timeout/failure events
  - session pacing events
  - external dependency wait/deferred events
  - `usage.jsonl`
  - verification command events where they are triggered by a specific Claude call
- 更新 `calibrate.log_usage(..., call_id=None)` 为向后兼容 optional 参数。
- 更新调用方把 `result["call_id"]` 传入 `log_usage()` 和 verification helpers。

### 3. Verification Fail Closed

- 扩展 `VerificationResult`，增加：
  - `failure_kind`
  - `harness_blocker`
  - `blocker_reason`
  - `failure_artifact`
- 在 `verify_fix()` 中识别 pytest no-tests-selected：
  - pytest return code `5`
  - 或 stdout/stderr 明确显示 0 selected / no tests ran
- 如果某个 profile no-tests-selected，但已有其他适用 verification command 通过，则记录 skipped，不视为失败。
- 如果所有 verification commands 都 skipped 或不适用，则返回 `harness_blocker=True`，不让 agent retry。
- 以下 non-agent-actionable / harness-documentation failures 统一 fail closed，不增加 task/issue attempts：
  - `agent completed task but created no commit`
  - `claimed fixed but no commit was created`
  - `claimed fixed but no files changed in git`
  - `claimed files ... not found in git diff`
  - no applicable verification command
- 对 execution task：halt task，记录 `last_error`，等待人工介入。
- 对 fix issue：halt affected issue，记录 `last_error`，等待人工介入。
- 扩展 `halt_task()` / `halt_issue()` 支持 reason，并保证 `--status` 能显示 halted reason。

### 4. Fix Failure Artifacts

- 保留现有 `workspace/fix_test_failure.log` 作为 latest。
- 同时写入归档日志：
  - `workspace/fix-test-failures/phase_{phase_id}_issues_{issue_ids}_attempt_{attempt}.log`
- 归档日志包含 command、returncode、stdout/stderr tail、failure_kind、call_id when available。
- 不引入新的 summary state source；只保存排障证据。

### 5. Usage Guardrails And Config

- 提交当前 `harness/config.json` 的 guardrail 调整。
- 不实现 pre-call token estimator。
- 在 harness docs 中说明：
  - usage guardrails 是 post-call operational guardrails
  - 不是精确预算系统
  - token 优化主要依赖 task 粒度、减少重复 prompt、fail-closed 避免无效 retry
- 保留当前 post-call guardrail 检查和 status/report 可见性。

### 6. Open Issues Document Update

- 更新 `harness/docs/harness-summary-reports/harness_engineering_open_issues_2026-05-17.md` 的改进建议：
  - 移除复杂 pre-call 预算估算建议
  - 移除自动阶段总结作为本轮实现目标
  - 统一改为 fail closed、call_id、no-tests-selected skip、failure artifact retention、config documentation 的解决方案

## Files To Modify

| File | Planned change |
|---|---|
| `harness/agents.py` | Add `call_id`; defer long 429 waits instead of sleeping in-process |
| `harness/subprocess_runner.py` | Accept optional `call_id`; include it in subprocess events |
| `harness/calibrate.py` | Add optional `call_id` to `log_usage()` entries |
| `harness/verify.py` | Add verification failure classification, no-tests-selected skip, fail-closed result metadata, archived fix logs |
| `harness/phase_handlers.py` | Halt task on `VerificationResult.harness_blocker` without retry/attempt increment |
| `harness/fix.py` | Halt affected issue on fix verification harness blocker without retry/attempt increment |
| `harness/state.py` | Allow `halt_task()` / `halt_issue()` to record reason |
| `harness/harness.py` | Surface halted task/issue reason in `--status` |
| `harness/config.json` | Keep approved guardrail values; add 429 wait threshold config |
| `harness/docs/*` | Document guardrail semantics and approved solution |
| `harness/docs/harness-summary-reports/harness_engineering_open_issues_2026-05-17.md` | Update solution text to match this plan |

## Tests

Add or update unit tests:

- `harness/tests/unit/test_agents.py`
  - long 429 retry delay emits deferred event and raises `ExternalDependencyError`
  - short 429 retry delay still uses existing sleep/retry behavior
  - non-429 long subprocess behavior is unaffected

- `harness/tests/unit/test_subprocess_runner.py`
  - subprocess start/end/timeout events include `call_id` when provided

- `harness/tests/unit/test_calibrate.py`
  - `log_usage()` writes `call_id` when provided
  - old callers without `call_id` still work

- `harness/tests/unit/test_verify.py`
  - pytest exit code 5 / 0 selected is skipped when another verification command passed
  - all commands skipped returns `harness_blocker=True`
  - no commit / no diff / diff mismatch returns `harness_blocker=True`
  - fix failure writes both latest and archived log

- `harness/tests/unit/test_phase_handlers.py`
  - execution verification harness blocker halts task
  - task attempts are not incremented

- `harness/tests/unit/test_fix.py`
  - fix verification harness blocker halts issue
  - issue attempts are not incremented
  - normal agent-fix failure still increments attempts

- `harness/tests/unit/test_harness.py`
  - `--status` includes halted task/issue reason

Regression checks:

- Existing external dependency wait tests
- Existing timeout/process cleanup tests
- Existing fallback commit tests
- Existing targeted re-review tests
- Existing usage guardrail tests

Verification command:

```powershell
python -m pytest harness/tests/unit
```

## Assumptions

- `900` seconds is the default threshold for in-process 429 wait; longer reset windows become resumable waits.
- Fail-closed means halted task/issue with reason, not auto-resetting `error`.
- No pre-call token estimator will be implemented in this iteration.
- No automatic phase summary generator will be implemented in this iteration.
- The implementation should preserve current successful paths and only change behavior for confirmed harness-caused or non-agent-actionable failures.
