# Harness Engineering 总结

生成日期：2026-05-17

本文档只总结 harness engineering 相关问题，包括稳定性、编排可靠性、token 消耗、等待时间、重试、阶段推进、测试/审核/评估流程和可观测性。本文档不评价 Animal Adventure 本身的功能、玩法或代码质量；涉及项目文件时，仅作为 harness 行为证据。

## 待解决的问题

### P0. phase 8 fix 验证出现误失败

- 问题：`pytest -m integration` 选中 0 个测试并返回 5，导致 HIGH issue `8.1` 保持 open。
- 影响：修复循环被错误阻塞，浪费 FIX 调用和等待时间；phase 8 无法完成，`review.status` 停在 `fixing`。
- 涉及文件：`harness/verify.py`、`harness/harness.py`、`harness/lang.py`、`workspace/fix_test_failure.log`、`workspace/state.json`。
- 证据来源：`workspace/fix_test_failure.log` 显示 `collected 415 items / 415 deselected / 0 selected`，returncode `5`；`workspace/state.json` 中 issue `8.1.status="open"`、`attempts=2`。
- 最佳实践：多 profile 验证应区分“命令失败”和“该 profile 在当前 repo/phase 没有适用测试”；对 `pytest` exit code 5 应在明确允许的场景下视为 skip。
- 改进建议：在 `_select_test_cmds()` 或 `verify_fix()` 中加入 no-tests-selected 处理；当 integration/e2e phase 已由 TypeScript profile 跑过 `npm run test:e2e`，Python `pytest -m integration` 若 0 selected，应记录为 skipped profile，并在 state/events 中写明 skipped reason。

### P0. 429 reset 等待通过进程内 `time.sleep()` 执行

- 问题：当前一次 FIX 等待约 12,946 秒。
- 影响：长时间占用 harness 进程和 lock；如果机器休眠、进程被杀或窗口关闭，恢复路径依赖人工判断。
- 涉及文件：`harness/agents.py`、`workspace/events.jsonl`、`workspace/external_dependency_context.json`、`harness/run_lock.py`。
- 证据来源：`workspace/events.jsonl` 中 `external_dependency_wait_start.seconds=12946.674268`；`workspace/external_dependency_context.json` 记录 `mode="FIX"`、`cleanup_status="clean"`。
- 最佳实践：长等待应持久化为 resumable wait，而不是让主进程长睡眠。
- 改进建议：对超过阈值的 retry delay，例如 10-15 分钟以上，写入 `external_dependency_context.json` 后主动退出，并提示 reset 后运行 `python harness/harness.py --resume`；短等待仍可 sleep。
- comments: 这里的处理只会诊断429等待，请确认不会影响大任务长时间执行的情况

### P1. usage guardrails 被全局放宽

- 问题：`max_single_output_tokens=61000`、`max_phase_claude_calls=20`、`max_phase_combined_tokens=8000000`。
- 影响：token 成本和等待时间风险升高；大输出调用可能继续发生，直到事后 guardrail 才发现。
- 涉及文件：`harness/config.json`、`workspace/usage.jsonl`。
- 证据来源：`git diff -- harness/config.json` 显示 guardrails 从 `15000/10/2500000` 放宽到 `61000/20/8000000`；`workspace/usage.jsonl` 中 phase 7 task `7.3` output `40,583`，总 cache read `47,608,443`。
- 最佳实践：budget 应同时覆盖 actual tokens、cache tokens、调用次数、mode、phase 和 rolling window；最好在调用前做预算预判，调用后做硬停止。
- 改进建议：把放宽阈值改为显式 profile/phase override，而不是全局提高；增加 pre-call 预算估算和 report 输出；对超大输出任务要求拆分或降上下文。
- comments: 加预算估值会明显提升harness的复杂度，并且还需要按task type区分，带来的收益有限，最主要的问题是提高harness文档性和token的使用效率

### P1. `usage.jsonl` 和 `events.jsonl` 缺少稳定 call id

- 问题：token、等待、耗时需要人工按时间拼接。
- 影响：总结报告和运维诊断成本高；难以准确回答“某次调用消耗了多少 token、等了多久、跑了哪个验证命令”。
- 涉及文件：`workspace/usage.jsonl`、`workspace/events.jsonl`、`harness/calibrate.py`、`harness/subprocess_runner.py`、`harness/agents.py`。
- 证据来源：usage entry 有 `phase_id/task_id/mode`，events 有 subprocess/pacing/wait 事件，但没有共同 `call_id`。
- 最佳实践：每次 Claude 调用应有唯一 `call_id`，贯穿 start/end/timeout/usage/pacing/wait/verification 事件。
- 改进建议：在 `call_claude()` 入口生成 `call_id`，写入所有相关 events 和 usage entry；报告生成时可直接 group by `call_id`。

### P1. fix 验证没有按 changed files / issue scope 精准选择

- 问题：fix 验证会按 profiles 顺序跑完整测试命令，失败即中断。
- 影响：对 integration/e2e phase 过重且易误判；phase 8 中 `npm run test:e2e` 成功后，Python marker 命令失败使整体失败。
- 涉及文件：`harness/verify.py`、`harness/harness.py`、`harness/lang.py`。
- 证据来源：`harness/harness.py verification_profiles_for()` 对 game integration/e2e 返回 TypeScript + Python；`harness/lang.py` 的 Python `integration_test_cmd` 是 `pytest -m integration`。
- 最佳实践：验证矩阵应按 phase type、changed files、issue file、profile applicability 选择最小充分命令，并把 skipped/required 明确记录。
- 改进建议：为 `verification_profiles_for()` 增加 applicability predicate，例如 changed files 全是 `.ts/.spec.ts` 时 Python integration command 默认 skip；跨栈 issue 才跑 Python + TypeScript。

### P1. phase 8 open issue 的 attempts 被 harness 验证误失败消耗

- 问题：issue `8.1` 已有 2 次 fix attempts，但失败原因主要来自 harness 验证配置。
- 影响：再继续 retry 可能达到 max attempts 并 halt，造成错误的人工阻塞。
- 涉及文件：`workspace/state.json`、`workspace/fix_test_failure.log`、`harness/verify.py`。
- 证据来源：`workspace/state.json` phase 8 issue `8.1.status="open"`、`attempts=2`、`last_error=["fix tests failed; see workspace\\fix_test_failure.log"]`；failure log 显示 0 selected。
- 最佳实践：retry 计数应区分 agent 修复失败、验证环境失败、验证命令不适用、外部依赖失败。
- 改进建议：将 `verify_fix()` 的 failure 分类写入 issue，例如 `verification_failure_type=no_tests_selected`；对 harness-caused validation failure 不增加 issue attempts，或转为 phase-level harness error。
- comments: 不光是这个问题，任何犹豫harness文档性而造成的agent retry都应该避免。比如：“agent completed task but created no commit”。遇到这类型的问题harness应该立刻停止，清理进程，记录问题，等待人工介入，而不是让agent retry

### P2. runtime artifacts 没有自动生成阶段总结

- 问题：当前需要人工综合 state、usage、events、git history 和 Codex 会话线索。
- 影响：每次复盘都要重复分析；容易漏掉 token、等待和稳定性问题。
- 涉及文件：`workspace/state.json`、`workspace/usage.jsonl`、`workspace/events.jsonl`、`harness/docs/harness-summary-reports/`。
- 证据来源：本报告就是通过人工读取多个 artifact、git history 和 `C:\Users\OEM\.codex\session_index.jsonl` 生成。
- 最佳实践：harness 应在 phase 结束、BLOCK/FIXING、外部依赖等待前自动生成或更新 run summary。
- 改进建议：增加 `harness/reporting.py` 或 CLI `python harness/harness.py --summary`，自动输出 phase summary、top token calls、wait events、open/deferred/fixed issues。
- comments: 这些信息都可以从workspace目录下的相关文件中获得，阶段总结的意义何在？

### P2. `fix_test_failure.log` 只保存最近一次失败

- 问题：早期失败上下文会被覆盖。
- 影响：多次 retry 时需要从 state/events 中手工还原。
- 涉及文件：`harness/verify.py`、`workspace/fix_test_failure.log`、`workspace/state.json`。
- 证据来源：当前只有一个 `workspace/fix_test_failure.log`，issue attempts 记录在 state 中但没有独立日志文件。
- 最佳实践：每次验证失败应保留带时间戳或 attempt id 的 artifact，同时维护 latest 摘要。
- 改进建议：将失败日志写到 `workspace/fix-test-failures/phase_8_issue_8.1_attempt_2.log`，同时保留 `workspace/fix_test_failure.log` 作为最近失败摘要。

### P2. `harness/config.json` 当前有未提交修改

- 问题：该修改直接改变全局 guardrail 行为。
- 影响：后续报告和运行结果难以判断是代码默认行为还是本地临时调参；也可能让别的 phase 继承过宽预算。
- 涉及文件：`harness/config.json`。
- 证据来源：`git diff -- harness/config.json` 显示 guardrails 从 `15000/10/2500000` 放宽到 `61000/20/8000000`。
- 最佳实践：harness 配置变更应有明确提交、注释或 per-run override 记录，并进入 summary。
- 改进建议：把临时阈值迁移到 `profile_overrides` 或 run-local config，并在 summary/status 中显示 “default vs override”。
- comments: 同意提交这个文件，但是改进意见需要考虑我前面的comments给出一个完整，合理，有效的解决方案，而不适当harness过于复杂，却提升效果不大