# Harness Engineering 总结

生成日期：2026-05-17

本文档只总结 harness engineering 相关问题，包括稳定性、编排可靠性、token 消耗、等待时间、重试、阶段推进、测试/审核/评估流程和可观测性。本文档不评价 Animal Adventure 本身的功能、玩法或代码质量；涉及项目文件时，仅作为 harness 行为证据。

## 运行快照

- 当前状态：`workspace/state.json` 显示 `total_phases=16`、`current_phase=8`。
- 阶段进度：phase 1-7 已完成；phase 8 为 `status="building"`，`review.status="fixing"`。
- 当前 blocker：phase 8 还有 1 个 HIGH issue open，issue `8.1` 已有 2 次 fix attempts。
- 使用量：`workspace/usage.jsonl` 记录 89 次 Claude 调用，累计约 `29,915` input tokens、`638,744` output tokens、`47,608,443` cache read tokens、`4,118,672` cache write tokens。
- 补充会话线索：`C:\Users\OEM\.codex\session_index.jsonl` 中，晚于 harness 首条事件 `2026-05-15T02:18:20` 的同 cwd 会话包括“分析 harness token 消耗”“审查 harness 代码”“确认并规划修复问题”“重启harness并定时报状态”等；本报告仅把这些作为定位线索，结论仍以仓库和 runtime artifacts 为准。
- 关键证据来源：`workspace/state.json`、`workspace/usage.jsonl`、`workspace/events.jsonl`、`workspace/external_dependency_context.json`、`workspace/fix_test_failure.log`、`harness/*.py`、`.claude/**`、`harness/config.json`、`git log -- harness .claude`。

## 已经解决的问题

### 1. setup/exempt 任务无新 diff 时导致 hook/verify 不稳定

- Summary：把 setup/exempt/no-op 任务从“必须产生新 commit”调整为“可验证的幂等完成”，减少 phase 1 scaffold 类任务因无新文件写入而触发 false negative，让 harness 可以稳定处理已满足的基础设施任务。
- Harness engineering 方面：setup phase 稳定性、hook/verify 协作、幂等执行。
- 证据来源：`workspace/harness_resume.err.log` 记录 `[VERIFY] Exempt/setup task completed with no tracked changes; accepting as idempotent.`；`harness/verify.py` 对 `setup_noop`、`exempt_noop` 建立接受路径；`git log -S "Exempt/setup task completed with no tracked changes"` 指向 `8257cf4` 和后续 verify 演进。
- 解决方式：`verify_execution()` 在 setup/exempt/test_first no-op 场景下检查 signal files 是否 tracked and clean；满足条件时返回 `VerificationResult(commit_ok=True, skipped_reason="setup_noop"|"exempt_noop")`，不再强迫 agent 或 hook 生成无意义 commit。
- 最佳实践判断：符合。setup 类型任务天然应支持幂等运行，验证逻辑应以可证明的文件状态为准，而不是把“没有新 diff”一律当失败。
- Trade-off / 备注：需要严格校验 signal files 已存在且 clean，否则会掩盖 agent 漏写文件的问题。

### 2. TDD 三任务 triplet 合并为 `tdd_slice`

- Summary：把 test-first、implementation、unit-test 三个 Claude task 合并为一个 `tdd_slice`，减少重复 system prompt 和上下文注入，把 verification 收回 harness 本地执行，从而降低 token 消耗并提升 agent 对一个完整功能切片的执行效率。
- Harness engineering 方面：任务颗粒度、token 成本控制、verification 归属、agent 效率。
- 证据来源：git commit `f606a4a fix(harness): coarsen tdd task planning` 同时修改 `.claude/agents/builder.md`、`.claude/hooks/stop_validate_json.py`、`.claude/rules/python/python-builder-guide.md`、`.claude/rules/typescript/typescript-builder-guide.md`、`harness/phase_handlers.py`、`harness/verify.py`；`harness/tests/unit/test_tdd_ordering.py` 覆盖 `tdd_slice`；`harness/config.json` 增加 `task_planning_limits.allow_legacy_tdd_triplets=false`。
- 解决方式：TASK_BUILD 默认要求开发阶段生成 `tdd_slice`，stop hook 拒绝 legacy `unit_test` Claude task；harness 在每个完成的 slice 后运行 compile/test verification。
- 最佳实践判断：符合。把确定性验证交给 harness，把创造性实现交给 agent，减少 agent 调用次数和重复提示注入。
- Trade-off / 备注：单个 `tdd_slice` 比旧的单一 micro-task 更大，因此需要 task planning limit、timeout bonus 和 artifact size guardrail 控制切片大小。

### 3. Claude 429 / 外部依赖失败曾直接阻塞或破坏执行上下文

- Summary：把 Claude 429 从普通 subprocess failure 提升为可识别、可等待、可清理、可 resume 的外部依赖状态，降低限流时 workspace 被半成品污染的概率。
- Harness engineering 方面：稳定性、外部依赖恢复、等待策略。
- 证据来源：`workspace/state.json` task `1.8.last_error` 记录 429；`workspace/events.jsonl` 有 `external_dependency_wait_start`；`workspace/external_dependency_context.json` 记录 `cleanup_status="clean"`；git commit `394eb9f fix(harness): clean external dependency waits before retry`。
- 解决方式：`harness/agents.py` 解析 429 reset 时间，等待前调用 `external_dependency.cleanup_before_wait()`，等待后做 preflight，再 retry；新增 `harness/external_dependency.py` 和相关测试。
- 最佳实践判断：基本符合。外部依赖失败被建模为可恢复状态，并在等待前清理进程和工作区。
- Trade-off / 备注：当前实现仍用长时间 `time.sleep()` 持有运行进程，见待解决问题。

### 4. Claude 调用过密和大输出后继续调用导致限流风险

- Summary：引入 session pacing 和 usage window，把“盲目连续调用 Claude”改为可观测、可配置的节流机制，减少大输出后继续触发限流的概率。
- Harness engineering 方面：token 消耗、等待时间控制、session pacing。
- 证据来源：`harness/config.json` 中 `claude_session_pacing.enabled=true`、`min_seconds_between_calls=60`、`large_output_cooldown_seconds=180`；`workspace/events.jsonl` 多次出现 `session_pacing_wait_start`；git commit `52fb1f7 Improve Claude session pacing visibility`。
- 解决方式：增加 session pacing，并把等待事件写入 `events.jsonl`；`harness/harness.py --status` 暴露 `usage_window`、`last_claude_usage`、`session_pacing`。
- 最佳实践判断：符合。pacing 显式配置化、事件化、可观测化。
- Trade-off / 备注：pacing 降低限流概率，但会增加总运行时间；目前主要是节流，不是完整预算优化。

### 5. subprocess timeout 信息不足，定位 Claude 卡死困难

- Summary：把 Claude subprocess 从黑盒调用改造成带 pid、timeout、stdout/stderr tail 和 start/end event 的可诊断执行单元，提升长任务卡死后的定位能力。
- Harness engineering 方面：稳定性、诊断、超时恢复。
- 证据来源：`workspace/events.jsonl` phase 8 记录 `claude_subprocess_timeout`，随后自动 retry 成功；git commit `04e21d6 fix: improve harness claude process diagnostics`；涉及 `harness/subprocess_runner.py`、`harness/agents.py`。
- 解决方式：增加 Claude subprocess start/end/timeout 事件、stderr/stdout tail、pid/returncode 诊断；timeout 后 retry 一次，第二次失败转为 `TimeoutError`。
- 最佳实践判断：基本符合。timeout 有结构化事件和 bounded retry。
- Trade-off / 备注：retry 会额外消耗时间和 token；超大任务仍需要拆分或更细粒度 timeout policy。

### 6. Windows 进程清理和孤儿进程处理不可靠

- Summary：把 Windows 上的不确定进程清理改成 fail closed 策略，减少超时或 429 等待后残留 Claude/子进程继续污染 workspace 的风险。
- Harness engineering 方面：稳定性、Windows 兼容、外部依赖恢复。
- 证据来源：git commit `6c335d5 fix: fail closed on Windows process cleanup enumeration`；涉及 `harness/subprocess_runner.py`、`harness/tests/unit/test_subprocess_runner.py`。
- 解决方式：Windows process cleanup 失败时 fail closed，不把未知状态误判为 clean；外部依赖 wait 前后记录 process cleanup 结果。
- 最佳实践判断：符合。清理状态不确定时保守失败，避免隐藏污染。
- Trade-off / 备注：保守策略可能让一些可继续运行的场景需要人工介入，但比误继续安全。

### 7. 并行运行或 stale lock 可能破坏 state.json

- Summary：引入 PID/token 双校验的 run lock，把 harness 从“可能多进程同时写 state”收敛为单 writer 模型，提高 state.json 的一致性和 resume 安全性。
- Harness engineering 方面：并发控制、resume 安全。
- 证据来源：`harness/run_lock.py` 使用 `workspace/run.lock`、`workspace/harness.pid`、`lock_token`；`harness/harness.py` 支持 `--clear-stale-lock`；`harness/tests/unit/test_run_lock.py` 覆盖 active/stale/race/token mismatch；git commit `117e1e1` 说明 `run_lock.py` 增加 `lock_token` 检测 PID reuse。
- 解决方式：通过原子创建 lock 文件、PID/token 双校验、stale lock 清理命令防止多个 harness 同时写 state。
- 最佳实践判断：符合。单 writer、可观测 lock、保守 stale 判断。
- Trade-off / 备注：crash 后可能需要 `--clear-stale-lock`，这是安全性和自动恢复之间的取舍。

### 8. agent 完成任务但未提交，导致 state 和 git 不一致

- Summary：把 agent 的“已完成”声明改成必须经过 git diff/commit 验证，必要时由 harness 做 fallback commit，减少 state.json 与真实仓库状态分裂。
- Harness engineering 方面：状态一致性、验证可靠性、commit hygiene。
- 证据来源：`workspace/state.json` task `3.2`、`6.2` 曾记录 `agent completed task but created no commit`；`harness/verify.py` 中 fallback commit 逻辑；git commit `937f967 fix(harness): add artifact quality gate, FIX fallback commit, and test failure log`。
- 解决方式：`verify_execution()` 和 `verify_fix()` 在安全信号文件存在时尝试 fallback commit；若仍无 commit，则把任务或 issue 作为失败处理。
- 最佳实践判断：符合。state 不轻信 agent 声明，以 git diff/commit 作为事实来源。
- Trade-off / 备注：fallback commit 依赖 signal-listed files，仍需要防止 agent 漏报文件。

### 9. 已提交文件再次执行时被误判为 no commit

- Summary：为已提交且 tracked-clean 的 `tdd_slice` / implementation 文件增加接受路径，使 reset/resume 后的重复执行不再因为“没有新 diff”浪费 retry 和 token。
- Harness engineering 方面：resume 幂等性、重复执行成本、verify 准确性。
- 证据来源：git commit `d086183 fix(verify): accept tdd_slice tasks when signal files already committed`；commit message 指出 phase reset 后 agent 重写同样文件导致 hook/fallback 都无内容可 stage；`harness/tests/unit/test_verify.py` 增加 `test_verify_execution_accepts_tdd_slice_with_prior_commit`。
- 解决方式：`verify_execution()` 对 non-implementation task 增加 tracked-and-clean 接受路径，允许用 prior commit 证明任务已完成。
- 最佳实践判断：符合。resume 系统需要把“已完成且可验证”与“未产生新变更”区分开。
- Trade-off / 备注：必须严格限定为 signal files 已 tracked and clean，否则会掩盖真正漏提交的问题。

### 10. 修复失败时缺少可复查的失败日志

- Summary：把 fix 验证失败从一句 state error 扩展为可打开的失败 artifact，让后续 retry、人工介入和报告分析都有共同证据。
- Harness engineering 方面：可观测性、修复闭环。
- 证据来源：`workspace/fix_test_failure.log` 当前记录 phase 8 fix test 失败命令、stdout/stderr tail；`harness/verify.py` 中 `_write_fix_test_failure_log()`；git commit `937f967`。
- 解决方式：fix 验证失败时写入 `workspace/fix_test_failure.log`，并在 `state.json.review.issues[].last_error` 中引用该文件。
- 最佳实践判断：符合。失败原因可追溯，不只保存一句摘要。
- Trade-off / 备注：当前只保留最近一次失败日志，历史失败需要从 events/state/git 中拼接。

### 11. 验证过程污染 `.pytest_cache`、临时目录或 coverage 文件

- Summary：把 verification 临时产物隔离到 workspace 下，并清理常见测试输出，减少测试副产物对 git diff、后续 hook 和 resume 的干扰。
- Harness engineering 方面：验证隔离、可重复性。
- 证据来源：git commit `b9e431f fix: isolate harness verification temp paths`；`harness/verify.py` 中 `_prepare_verification_cmd()` 添加 `--ignore=.pytest_cache` 和 `--basetemp=workspace/verification-tmp`，并清理 `coverage/test-results/playwright-report`。
- 解决方式：把 pytest temp path 固定到 workspace，验证后清理常见产物，避免验证产物误入 diff 或影响后续 run。
- 最佳实践判断：符合。验证环境可控、产物隔离。
- Trade-off / 备注：仍需要按测试框架继续扩展清理规则，例如 Playwright trace/video/report 的保留策略。

### 12. phase/task/review/evaluate resume 规则曾不清晰

- Summary：把隐式状态机文档化并暴露到 `--status`，让 operator 能知道当前卡在哪里、为什么卡住、下一步应该 resume 还是人工修复。
- Harness engineering 方面：状态机、resume、运维可见性。
- 证据来源：`harness/docs/05-harness-py.md`、`harness/docs/08-state-schema.md` 明确状态转移；git commits `74a3544`、`1c891f7`、`1b12252`；`harness/harness.py --status` 输出 `active_tasks`、`error_tasks`、`blocked_tasks`、`recent_claude_events`。
- 解决方式：将 task、issue、review、evaluate 状态机文档化，并在 status 输出中暴露当前 blocker/error 和下一步命令。
- 最佳实践判断：符合。状态可恢复、可解释、可操作。
- Trade-off / 备注：状态 schema 已较复杂，后续需要防止状态字段继续发散。

### 13. stop hook 防止 broad pathspec 污染提交

- Summary：收紧 `stop_git_commit.py` 的文件准入，把 agent 声明的 `files_changed` 从可直接 `git add` 改为必须通过 pathspec 安全检查和 git status 验证，减少 unrelated dirty files 被误提交，保护 harness 的提交边界和 review 可信度。
- Harness engineering 方面：commit safety、hook 安全、state/review diff 可信度。
- 证据来源：`harness/docs/Harness_Stability_Review_Report.md` 的 P1 finding 指出 `files_changed=["."]` 可导致 broad staging；git commit `117e1e1 fix: resolve 5 harness stability bugs and correct pre-existing test failures` 修改 `.claude/hooks/stop_git_commit.py` 和 `harness/tests/unit/test_hooks.py`。
- 解决方式：拒绝 `.`、目录、glob/pathspec magic 等 broad path 值；在 `git add` 前加入 `--` 分隔；只允许出现在 `git status` 中且可归因于 signal 的文件进入 hook commit。
- 最佳实践判断：符合。agent 输出只能作为候选信号，不能直接作为版本控制写入权限。
- Trade-off / 备注：更严格的文件准入可能让部分宽泛 signal 失败，但失败是可解释、可修复的，比污染提交更可控。

### 14. EXECUTE signal 与当前 phase/task 绑定

- Summary：为 EXECUTE signal 增加 `phase_id` 和 active task 校验，把 agent 输出从“可跨 phase/task 更新 state”收敛为当前任务的单点更新，减少 `state.json` 被错误推进或 resume 跳过工作的风险。
- Harness engineering 方面：状态一致性、运行时上下文校验、phase orchestration。
- 证据来源：`harness/docs/Harness_Stability_Review_Report.md` 的 P1 finding 指出 EXECUTE schema 只验证格式、不验证 active runtime context；git commit `117e1e1` 修改 `harness/phase_handlers.py` 和 `harness/tests/unit/test_phase_handlers.py`。
- 解决方式：`handle_executing()` 校验 signal 的 phase 与当前 phase 一致，并要求返回任务匹配当前 active task；错误 phase、额外 task、缺失 task、重复 task 都进入失败路径。
- 最佳实践判断：符合。LLM signal 必须受 harness runtime context 约束，state transition 不能只依赖 schema shape。
- Trade-off / 备注：更严格的 signal 校验会暴露 agent 输出不稳定问题，但能把错误限制在当前 task，而不是污染整个 run。

### 15. 文本 artifact 质量门禁

- Summary：在 verification 阶段拒绝 UTF-16、BOM、NUL 等不可用文本产物，并把 UTF-8 no BOM 要求写入 builder/reviewer 指南，减少编码污染导致的安装、测试和后续 agent 读取失败。
- Harness engineering 方面：artifact quality gate、跨平台稳定性、verification hygiene。
- 证据来源：git commit `937f967 fix(harness): add artifact quality gate, FIX fallback commit, and test failure log` 修改 `harness/verify.py`、`.claude/agents/builder.md`、`.claude/agents/reviewer.md` 和 `harness/tests/unit/test_verify.py`。
- 解决方式：`verify_execution()` 和 `verify_fix()` 在接受 agent 产物前执行文本质量检查；对 `requirements.txt` 等关键文件增加最小解析校验；agent 指南明确 UTF-8 no BOM。
- 最佳实践判断：符合。harness 应在本地验证产物可用性，而不是把编码问题推迟到下一轮安装或测试才暴露。
- Trade-off / 备注：质量门禁会增加少量验证成本，但比后续跨工具链失败和重复 Claude 调用成本更低。

### 16. 已满足的 implementation 文件不再强迫制造新 diff

- Summary：允许 implementation task 在现有 tracked-clean 文件已经满足需求时通过验证，减少重复实现和空转 retry，让 harness 能复用既有工作，而不是要求 agent 为了完成状态制造无意义 diff。
- Harness engineering 方面：幂等验证、resume 稳定性、token 节省。
- 证据来源：git commit `770447d fix(harness): accept verified existing implementation files` 修改 `harness/verify.py`、`harness/agents.py`、`.claude/agents/builder.md`、`harness/docs/03-agent-code-builder.md` 和 `harness/tests/unit/test_verify.py`。
- 解决方式：当 implementation signal 指向的文件已经 tracked 且 clean，并且验证命令通过时，harness 可接受该任务完成，不再把缺少新 commit 等同为失败。
- 最佳实践判断：符合。autonomous harness 的完成标准应是“目标状态已被验证”，而不只是“本轮产生了新 diff”。
- Trade-off / 备注：需要依赖更强的 verification signal；如果验证命令覆盖不足，可能接受已有但不充分的实现。

### 17. cleanup/evaluate resume 指向修正

- Summary：把 cleanup/evaluate 的 blocked、timeout、error 状态直接路由回对应阶段，避免已完成 task phase 在 resume 时错误回退到 TASK_BUILD，减少重复执行和状态错位。
- Harness engineering 方面：resume targeting、late-stage orchestration、重复执行控制。
- 证据来源：git commit `1c891f7 fix harness cleanup and evaluate resume targeting` 修改 `harness/evaluate.py`、`harness/subprocess_runner.py`、`harness/tests/unit/test_evaluate.py` 和 `harness/tests/unit/test_subprocess_runner.py`。
- 解决方式：resume 根据 cleanup/evaluate 的实际状态选择目标处理器；timeout 相关测试覆盖 cleanup/evaluate 子流程的恢复路径。
- 最佳实践判断：符合。resume 应恢复到最近失败的 harness mode，而不是粗粒度地回到前一个大阶段。
- Trade-off / 备注：状态路由更精细后，测试矩阵变大；需要继续确保每个 mode 都有明确的 blocked/error/complete 语义。

### 18. `--status` 暴露 task-level blocked/error

- Summary：把 task-level blocked/error 纳入 `--status` 输出，让 operator 能直接看到当前 blocker，而不是手动翻 `state.json`，降低恢复、排障和交接成本。
- Harness engineering 方面：observability、operator workflow、外部依赖恢复。
- 证据来源：`harness/docs/Harness_Stability_Review_Report.md` 的 P3 finding 指出 blocked task status 曾隐藏；git commits `117e1e1` 和 `1b12252 fix(harness): surface task-level errors in --status output` 修改 `harness/harness.py`、`harness/state.py` 和 `harness/tests/unit/test_harness.py`。
- 解决方式：`_summarize_status()` 输出 `blocked_tasks`、`error_tasks`、task-level `last_error` 和 recent events；resume 前后的 blocker 信息更容易被 operator 识别。
- 最佳实践判断：符合。长跑 harness 必须把当前 blocker 放在 status 层，而不是要求人工阅读完整 state。
- Trade-off / 备注：status 输出更长，但换来更低的恢复认知成本。

### 19. agent prompt 注入 TDD / security skill

- Summary：把 builder/reviewer 的关键 skill 文件纳入 prompt preamble，使 TDD workflow 和 security review checklist 成为每次 agent 调用的显式上下文，减少 agent 只读基础角色说明而漏执行质量流程的风险。
- Harness engineering 方面：prompt assembly、质量流程一致性、agent guardrail。
- 证据来源：`harness/docs/review_report.md` 的 F-1 指出 skill 文件未注入会破坏 harness 设计的质量闭环；当前 `harness/agents.py` 的 `build_file_lists()` 将 `profile["builder_skill"]`、`profile["reviewer_skill"]` 加入读取列表；`harness/tests/unit/test_agents.py`、`harness/tests/unit/test_lang.py`、`harness/tests/unit/test_agents_settings.py` 覆盖 skill 引用。
- 解决方式：按语言 profile 注入 `.claude/skills/tdd-workflow*/SKILL.md` 和 `.claude/skills/security-review/SKILL.md`，让 agent 在 task build、execute、review 前读取对应流程。
- 最佳实践判断：符合。harness 依赖的 workflow 不能只存在于仓库文件中，必须进入 agent 实际上下文。
- Trade-off / 备注：每次注入 skill 会增加少量 prompt/context 成本，但换来更稳定的 TDD 和 review 行为。

### 20. building task 在 resume 时可恢复

- Summary：把中断时停留在 `building` 的 task 重置为 `pending` 并重新进入 EXECUTE，减少 kill/crash 后 task 被跳过、phase 直接进入 review 的风险。
- Harness engineering 方面：crash recovery、resume、task state reconciliation。
- 证据来源：`harness/docs/review_report.md` 的 F-2 指出 `building` task 曾可能在 resume 时不可见；当前 `harness/harness.py` 的 `_derive_state()` / `reset_interrupted_tasks()` 路径覆盖该状态；`harness/tests/unit/test_harness.py` 包含 `test_derive_state_resets_building_task_to_pending`。
- 解决方式：resume 时识别 interrupted task，并把未完成的 `building` 状态恢复到可执行队列，而不是视为完成或跳过。
- 最佳实践判断：符合。长跑 autonomous harness 必须把 interrupted in-flight task 当成未完成工作处理。
- Trade-off / 备注：可能重复执行一部分已经写入但未验证的文件，因此必须和 git/verify 幂等逻辑配合。

### 21. REVIEW subprocess error 进入 state，而不是静默重试

- Summary：把 review timeout/subprocess error 写入 `review.status="error"` 和 `review.last_error`，让 resume 能回到 REVIEWING，并让 operator 能看到 review 失败原因。
- Harness engineering 方面：review recovery、错误归因、状态可观测性。
- 证据来源：`harness/docs/review_report.md` 的 F-3 指出 review pseudo-task error 曾无法记录；当前 `harness/state.py` 的 `error_review()`、`harness/phase_handlers.py` 的 review error handling 和 `harness/tests/unit/test_state.py`、`harness/tests/unit/test_phase_handlers.py` 覆盖该行为。
- 解决方式：REVIEW 失败不再通过不存在的 pseudo task ID 写入 task error，而是写入 review 专属状态字段。
- 最佳实践判断：符合。每个 harness mode 都应有自己的 error slot，避免把 phase/review/fix/evaluate 错误塞进 task schema。
- Trade-off / 备注：review 状态字段更多，但故障定位更直接。

### 22. phase 完成状态显式写回

- Summary：在进入下一 phase 前显式设置当前 phase `status="complete"`，让 state.json、status 输出和外部工具都能准确判断 phase 终态，减少只能靠 `current_phase` 推断进度的歧义。
- Harness engineering 方面：state schema 准确性、progress observability、resume 判断。
- 证据来源：`harness/docs/review_report.md` 的 F-4 指出 phase status 曾不写 complete；当前 `harness/phase_handlers.py` 的 `handle_next_phase()` 在推进前调用 `update_state(..., status="complete")`；`harness/tests/unit/test_phase_handlers.py` 和 `harness/tests/e2e/test_harness_e2e_mocked.py` 覆盖 phase complete。
- 解决方式：NEXT_PHASE 先完成当前 phase 状态写入，再递增 `current_phase` 或进入 cleanup。
- 最佳实践判断：符合。state 应显式表达终态，不能要求下游工具从派生条件猜测。
- Trade-off / 备注：phase status 与 review status 需要保持一致，后续 schema 变更要继续维护该不变量。

### 23. signal file paths 进入 verification 前统一净化

- Summary：把 agent 提供的 file paths 先经过 `safe_changed_signal_files()` 和 git snapshot 过滤，再用于 fallback commit、diff 归因和验证，减少路径穿越、unrelated file、compile command 注入造成的安全与稳定性问题。
- Harness engineering 方面：file path trust boundary、verification safety、commit attribution。
- 证据来源：`harness/docs/review_report.md` 的 S-1/S-2 指出 agent-supplied paths 曾可能直接进入 commit 或 compile command；当前 `harness/git_changes.py` 提供 `safe_changed_signal_files()`；`harness/verify.py` 在 fallback commit 和 fix verification 中调用；`harness/tests/unit/test_git_changes.py`、`harness/tests/e2e/test_harness_e2e_mocked.py` 覆盖 unrelated/path traversal 过滤。
- 解决方式：以 pre/post git snapshot 和 normalized relative paths 限定 agent signal 的实际作用范围。
- 最佳实践判断：符合。LLM 输出的 path 只能作为候选输入，必须经过 harness 本地可信边界过滤。
- Trade-off / 备注：如果 agent 漏报文件，harness 会更容易拒绝任务；这会增加一次修正成本，但保护提交边界。

### 24. JSON signal extraction 从 greedy regex 改为括号深度解析

- Summary：把 JSON signal fallback 提取从可能跨多个对象误匹配的贪婪正则改为括号深度扫描，减少 agent 输出被 prose 包裹或含多个 JSON 片段时解析错误的概率。
- Harness engineering 方面：agent protocol robustness、hook fallback、signal parsing。
- 证据来源：`harness/docs/review_report.md` 的 S-5 指出 `extract_signal` greedy regex 风险；当前 `harness/agents.py` 的 `extract_signal()` 先尝试完整 JSON，再按括号深度提取第一个完整对象；`harness/tests/unit/test_agents.py` 覆盖 clean/fenced/prose/no-json 场景。
- 解决方式：移除跨对象贪婪匹配假设，通过 depth counter 找到第一个完整 JSON object。
- 最佳实践判断：符合。agent protocol 应优先要求纯 JSON，同时 fallback 解析必须有边界。
- Trade-off / 备注：如果 agent 输出多个对象，harness 只取第一个完整对象；仍需要 stop hook 继续强制最终输出唯一 signal。

### 25. FIX 后增加 blocking issue 的 targeted re-review

- Summary：在 CRITICAL/HIGH issue 被 fix verification 接受后，增加 scoped targeted re-review，减少 harness 只靠测试通过就推进 phase 的风险，让安全和质量阻塞项真正闭环。
- Harness engineering 方面：review/fix closed loop、quality gate、phase advancement safety。
- 证据来源：`harness/docs/04-agent-code-reviewer.md` 说明 targeted re-review；当前 `harness/fix.py` 的 `_targeted_rereview_blocking_fixes()` 调用 `agents.review_fix()`；`harness/tests/unit/test_fix.py` 和 `harness/tests/e2e/test_harness_e2e_mocked.py` 覆盖 approve/block/error 路径。
- 解决方式：FIX 通过测试后，对本次修复的 blocking issue 使用 `base_sha..head_sha` 范围重新审查；若 targeted review 仍阻塞，则保持 issue open。
- 最佳实践判断：符合。测试验证和 review 验证职责不同，blocking review issue 需要 review 层确认关闭。
- Trade-off / 备注：会增加额外 Claude REVIEW 调用和 token，但只针对 blocking fixes，范围较小。

### 26. FIX/CLEANUP subprocess error 标记所有相关 issue

- Summary：把批量 FIX/CLEANUP subprocess error 从“只标记第一个 issue”改为标记所有本轮 open issue，减少 state 半更新导致 resume 误判的风险。
- Harness engineering 方面：批量错误处理、state consistency、resume correctness。
- 证据来源：`harness/docs/stability_review_plan.md` 的 Bug 2 指出单个 `error_issue()` 会提前 `sys.exit`；当前 `harness/state.py` 提供 `error_issues()`；`harness/fix.py` 在 `agents.SubprocessError` 时对 `open_issues` 批量记录；`harness/tests/unit/test_state.py` 覆盖 `test_error_issues_records_all_issue_errors`。
- 解决方式：将同一失败 subprocess 影响的 issue 一次性写入 error/last_error，再返回控制流。
- 最佳实践判断：符合。一个批处理调用失败时，所有受影响实体都应获得一致的失败状态。
- Trade-off / 备注：某些 issue 可能并非导致失败的直接原因，但它们确实共享同一个失败 subprocess，需要在下一轮一起恢复。

### 27. targeted re-review 被外部依赖阻塞时重新打开 fixed issue

- Summary：当 targeted re-review 因 429/外部依赖失败而无法完成时，先把相关 blocking issue 从 `fixed` 重新打开，再进入 blocked_external_dependency，避免 resume 后跳过必要复审。
- Harness engineering 方面：review/fix correctness、external dependency recovery、状态保守性。
- 证据来源：`harness/docs/stability_review_plan.md` 的 Bug 3 指出 fixed issue 可能在 targeted re-review blocked 后被错误跳过；当前 `harness/fix.py` 在 `ExternalDependencyError` 中重新设置 issue `status="open"` 并记录 last_error；`harness/tests/unit/test_fix.py` 覆盖 `test_targeted_rereview_external_dependency_reopens_fixed_blocking_issue` 和 blocked mode。
- 解决方式：把“代码已修但复审未完成”视为未闭环状态，等待外部依赖恢复后继续复审。
- 最佳实践判断：符合。review gate 未完成时不能把 blocking issue 当作已解决。
- Trade-off / 备注：可能导致同一 fix 被再次检查甚至重跑，但避免了错误放行。

### 28. evaluator 写权限从 `Write(**)` 收窄到评估产物

- Summary：把 evaluator 从全仓库写权限收窄为只能写 rubric report、screenshots 和 eval scripts，减少评估阶段修改源码、state 或 harness 文件的风险。
- Harness engineering 方面：权限最小化、evaluation isolation、安全边界。
- 证据来源：`harness/docs/stability_review_plan.md` 的 Bug 5 指出 evaluator broad write permission 风险；当前 `.claude/settings.evaluator.json` 只允许 `Write(workspace/rubric-report.md)`、`Write(workspace/screenshots/**)`、`Write(workspace/eval_*.py)` 等评估产物；`harness/tests/unit/test_config_shape.py` 明确断言 evaluator 不包含 `Write(**)`。
- 解决方式：按 evaluator 实际职责收窄 allowlist，并保留评估脚本和截图所需写入。
- 最佳实践判断：符合。评估 agent 应只观察和产出评估证据，不应拥有修改产品或 harness 的默认权限。
- Trade-off / 备注：如果未来 evaluator 需要新的 artifact 类型，需要显式扩展 allowlist。

### 29. evaluate fix 需要真实 commit 和 fixed signal

- Summary：为 evaluate fix 增加 `pre_sha` 对比和 fixed-status 检查，减少 fix agent 没有实际提交或只返回 open/deferred 却被记录为修复成功的 false positive。
- Harness engineering 方面：evaluation fix verification、false-positive 防护、git/state 一致性。
- 证据来源：`harness/docs/issue_fix_plan.md` 的 Bug 2 指出 `verify_evaluate_fix()` 曾忽略 `pre_sha` 和 fix statuses；当前 `harness/evaluate.py` 在 `_run_evaluate_fix()` 检查至少一个 `status="fixed"`，并在 `verify_evaluate_fix()` 中比较 `current_sha` 与 `pre_sha`；`harness/tests/unit/test_evaluate.py` 覆盖相关路径。
- 解决方式：没有 fixed signal 或 HEAD 未变化时不写 `fix_sha`，并保留 evaluate iteration 的修复失败上下文。
- 最佳实践判断：符合。evaluation fix 与普通 fix 一样，必须由 signal、git commit 和测试共同证明。
- Trade-off / 备注：如果 agent 做了非代码型修复但无 commit，仍会被拒绝；这符合当前 harness 以 git 为事实源的设计。

### 30. review `sha_at_review` 以本地 HEAD 为准

- Summary：review 完成时用 harness 本地 `git rev-parse HEAD` 覆盖 agent 返回的 `sha_at_review`，减少 agent 误报 SHA 导致后续 fix diff 范围错误的风险。
- Harness engineering 方面：review provenance、diff correctness、agent trust boundary。
- 证据来源：`harness/docs/issue_fix_plan.md` 的 Bug 3 指出不应信任 agent-provided SHA；当前 `harness/phase_handlers.py` 比较 `agent_sha` 和 `actual_sha` 并优先保存 `actual_sha`；`harness/tests/unit/test_phase_handlers.py` 覆盖 `test_handle_reviewing_stores_actual_head_as_sha_at_review`。
- 解决方式：agent SHA 只作为 fallback；当本地 HEAD 可读时，以 harness 读取的真实 SHA 作为 review anchor。
- 最佳实践判断：符合。涉及 git provenance 的事实必须由 harness 本地读取，不能由 agent 声明。
- Trade-off / 备注：如果本地 git 命令失败，会退回 agent SHA；这种情况应继续记录 warning。

### 31. `verify_fix()` 拒绝无 diff 或 diff 不相交的 false-positive fix

- Summary：把 fix agent 的 `status="fixed"` 与真实 git diff 交叉校验，减少测试通过但修复文件未变、或声明文件与实际 diff 不相交时错误关闭 issue 的风险。
- Harness engineering 方面：fix verification、issue lifecycle correctness、commit attribution。
- 证据来源：`harness/docs/issue_fix_plan.md` 的 Bug 1 指出 `verify_fix()` false-positive 风险；当前 `harness/verify.py` 检查 `current_sha != pre_sha`、`git diff pre_sha..HEAD` 非空、`fix.files_changed` 与实际 diff 相交；`harness/tests/unit/test_verify.py` 覆盖 no-pre-sha、empty files、diff mismatch 等路径。
- 解决方式：只有测试通过、artifact 合格、HEAD 变化且 fix 声明能与真实 diff 对上时，才把 issue 标记为 fixed。
- 最佳实践判断：符合。fix 关闭必须由测试、git diff 和 issue-scoped evidence 共同支撑。
- Trade-off / 备注：对跨文件间接修复可能较严格，需要 agent 准确报告 `files_changed`。

### 32. evaluator FIX subprocess failure 不再变成 orchestrator crash

- Summary：把 evaluator FIX 中的 timeout 和 subprocess parse/error 归类为 evaluate state error，而不是让异常冒泡成 harness crash，提升最终评估阶段的可恢复性。
- Harness engineering 方面：evaluate recovery、error classification、late-stage stability。
- 证据来源：`harness/docs/stability_review_plan.md` 的 Bug 1 指出 `_run_evaluate_fix()` 曾只捕获外部依赖错误；当前 `harness/evaluate.py` 捕获 `agents.TimeoutError` 和 `agents.SubprocessError` 并调用 `error_evaluate()`；`harness/tests/unit/test_evaluate.py` 覆盖 `test_run_evaluate_fix_timeout_records_timeout`、`test_run_evaluate_fix_subprocess_error_records_error`。
- 解决方式：evaluator fix 的超时、不可解析输出和 subprocess failure 都写入 `state["evaluate"]`，resume 可按 evaluate 状态继续，而不是依赖崩溃后的人工判断。
- 最佳实践判断：符合。每个 harness mode 都应把预期失败归类到 state，而不是让主循环异常退出。
- Trade-off / 备注：evaluate state 更复杂，但换来明确的 resume 入口。

### 33. unexpected crash 保留 run lock 作为诊断信号

- Summary：区分受控退出和未预期异常，只在 controlled `SystemExit` 路径释放 run lock，让真正的 harness crash 保留 lock/pid 证据，减少 crash 后被误认为正常结束。
- Harness engineering 方面：run lock 生命周期、crash diagnostics、operator recovery。
- 证据来源：`harness/docs/stability_review_plan.md` 的 Bug 4 指出 unexpected crash 曾可能释放 run lock；当前 `harness/harness.py` 使用 `release_on_exit` 区分受控退出与异常；`harness/tests/unit/test_harness.py` 覆盖 `test_run_preserves_lock_on_unexpected_exception` 和 `test_run_releases_lock_on_controlled_system_exit`。
- 解决方式：受控 halt/block/error 释放 lock 以便 resume；未预期异常保留 lock，供 `--status` / `--clear-stale-lock` 显示和处理。
- 最佳实践判断：符合。lock 不只是互斥工具，也是 crash 后的诊断 artifact。
- Trade-off / 备注：用户可能需要手动清理 stale lock，但能保留更真实的异常上下文。

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

### P1. usage guardrails 被全局放宽

- 问题：`max_single_output_tokens=61000`、`max_phase_claude_calls=20`、`max_phase_combined_tokens=8000000`。
- 影响：token 成本和等待时间风险升高；大输出调用可能继续发生，直到事后 guardrail 才发现。
- 涉及文件：`harness/config.json`、`workspace/usage.jsonl`。
- 证据来源：`git diff -- harness/config.json` 显示 guardrails 从 `15000/10/2500000` 放宽到 `61000/20/8000000`；`workspace/usage.jsonl` 中 phase 7 task `7.3` output `40,583`，总 cache read `47,608,443`。
- 最佳实践：budget 应同时覆盖 actual tokens、cache tokens、调用次数、mode、phase 和 rolling window；最好在调用前做预算预判，调用后做硬停止。
- 改进建议：把放宽阈值改为显式 profile/phase override，而不是全局提高；增加 pre-call 预算估算和 report 输出；对超大输出任务要求拆分或降上下文。

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

### P2. runtime artifacts 没有自动生成阶段总结

- 问题：当前需要人工综合 state、usage、events、git history 和 Codex 会话线索。
- 影响：每次复盘都要重复分析；容易漏掉 token、等待和稳定性问题。
- 涉及文件：`workspace/state.json`、`workspace/usage.jsonl`、`workspace/events.jsonl`、`harness/docs/harness-summary-reports/`。
- 证据来源：本报告就是通过人工读取多个 artifact、git history 和 `C:\Users\OEM\.codex\session_index.jsonl` 生成。
- 最佳实践：harness 应在 phase 结束、BLOCK/FIXING、外部依赖等待前自动生成或更新 run summary。
- 改进建议：增加 `harness/reporting.py` 或 CLI `python harness/harness.py --summary`，自动输出 phase summary、top token calls、wait events、open/deferred/fixed issues。

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
