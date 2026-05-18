# Plan: Fix EXECUTE Correction-Turn Signal Loss + Phase 12 Task Granularity

## Context

Phase 12 的 `tdd_slice` 任务要求 builder 一次性写出大量测试代码（30K–36K tokens）。
这触发了两个连锁问题：

1. **stop hook 触发 correction turn**：builder 输出内容不是纯 JSON → `stop_validate_json.py` 退出 1 → correction turn 开始，`stop_hook_active=True` → 验证被完全绕过
2. **correction turn 丢失信号字段**：builder 在 correction turn 只输出骨架 JSON：
   - `phase_id: null` → 已由 commit `4a11fd0` 修复（注入为已知值）
   - `tasks: []` → **新问题**，导致 `active task 12.2 not found in signal` → HALT

当前状态：
- 12.1 ✅ complete
- 12.2 ❌ error（`tests/test_quest_service.py` 40,900 字节已存在但未提交）
- 12.3–12.7 pending（12.3 描述过长，预计会重现同样问题）

---

## 根因

`phase_handlers.py` 在 `signal_task_ids` 为空时无条件 HALT，而不区分：
- 空 tasks（correction turn 丢弃内容）→ 应容忍，注入 stub 继续
- 非空 tasks 但含错误 ID → 应继续 HALT

---

## 方案

### Part 1 — Harness 容错修复（3 个源文件 + 测试）

**文件变更表**

| 文件 | 变更 |
|------|------|
| `harness/phase_handlers.py` | 区分空 tasks（注入 stub + WARNING）vs 错误 ID（保留 HALT） |
| `harness/agents.py` | EXECUTE prompt 追加 task ID 显式提醒 |
| `.claude/agents/builder-execute-fix.md` | 新增 correction turn 说明 |
| `harness/tests/unit/test_phase_handlers.py` | 新增 2 个测试用例 |

---

### Part 1A：`harness/phase_handlers.py`

**位置**：现有 lines 366–378（`signal_task_ids` 验证块）

**当前逻辑**（简化）：
```
if task_id not in signal_task_ids:
    → error_task + HALT
```

**新逻辑**：
```
if task_id not in signal_task_ids:
    if signal_task_ids is EMPTY:
        → logger.warning("correction turn — injecting stub for task X")
        → inject {"id": task_id, "title": ..., "task_type": ..., "status": "complete", "files_changed": []}
          into signal["tasks"]
        → continue（让 verify_execution 验证实际 git commit）
    else:
        → 保留原有 error_task + HALT（非空但 ID 错误，是真实信号错误）
```

关键安全保证：stub 的 `files_changed: []` 会在 `phase_handlers.py` line 432–433 被
`getattr(verify_failures, "committed_files", [])` 覆盖，verify 仍然验证实际 git commit。

---

### Part 1B：`harness/agents.py`

**位置**：`execute()` 函数 prompt 组装，现有 line 450 之后：

```python
# 现有
+ f' Your JSON signal must include "phase_id": {phase_id} (integer, not null).'
# 新增
+ f' Your JSON signal tasks array must contain an entry with "id": "{task["id"]}".'
+ _JSON_SIGNAL_SUFFIX
```

`task["id"]` 在此作用域内已赋值（line 419：`task = tasks[0]`）。

---

### Part 1C：`.claude/agents/builder-execute-fix.md`

**位置**：`Wrapper: mode(R), phase_id(R), tasks(R)` 行（line 99）之后、`### FIX` 标题之前。

新增说明块：
```markdown
> **Correction turn（stop hook 要求重新输出 JSON）**：若 stop hook 因响应不是纯 JSON
> 而要求修正，correction turn 必须包含所有必需字段：`"mode": "EXECUTE"`、
> `"phase_id": <prompt 中的整数，不能为 null>`、以及含当前任务条目的 `"tasks"` 数组。
> 禁止输出 `"tasks": []`——空数组会丢失活跃任务导致 harness HALT。
```

---

### Part 1D：`harness/tests/unit/test_phase_handlers.py`

**插入位置**：line 1052 之后（`test_handle_executing_rejects_missing_active_task_in_signal` 结束后）

**测试 1：`test_execute_patches_empty_signal_tasks_and_continues`**

覆盖：correction turn 场景，`tasks: []` → 注入 stub → 任务通过 → 结果为 REVIEWING

```python
# Arrange: 活跃任务 status=pending
# signal = {"phase_id": 1, "mode": "EXECUTE", "tasks": []}
# monkeypatch verify_execution → 返回 []（空，无失败）
# Act: handle_executing(...)
# Assert:
#   - 结果为 HarnessState.REVIEWING（未 HALT）
#   - caplog 包含 "correction turn"（WARNING 级别）
#   - sample_state tasks[0]["status"] == "complete"
```

**测试 2：`test_execute_halts_on_nonempty_wrong_task_ids`**

覆盖：非空 tasks 但含错误 ID → 保持 HALT 行为（回归保证）

```python
# Arrange: signal 含 task_id="1.2"，活跃任务为 "1.1"
# 与现有 test_handle_executing_rejects_missing_active_task_in_signal 逻辑相同
# 仅命名更明确，证明 else 分支未被破坏
# Assert: pytest.raises(SystemExit)，task["status"] == "error"
```

使用已有 helper：`_make_execute_result(phase_id=1, task_id="1.2")`

---

## Part 2 — state.json 任务粒度

### Part 2A：提交并标记 12.2 为 complete

`tests/test_quest_service.py`（40,900 字节）已由上次 36K token EXECUTE 写出，但未被提交。

**步骤**：
1. `git add tests/test_quest_service.py && git commit -m "feat(phase-12): Write quest service tests"` → 记录 SHA 为 `<sha_12_2>`
2. 编辑 `workspace/state.json` 任务 12.2：
   - `"status"` → `"complete"`
   - `"tdd_applied"` → `true`
   - `"files_changed"` → `["tests/test_quest_service.py"]`
   - `"last_error"` → `[]`
   - 新增 `"commit_sha": "<sha_12_2>"`

### Part 2B：拆分任务 12.3 → 12.3 + 12.8

**拆分标准**：单个任务描述列出 >5 个独立测试场景 **且** 需要实现新基础组件，视为过重。
12.3 当前：实现 QuestExpiryWorker + 9 个场景 → 预计 30K+ tokens → 超时/correction turn。

**任务 12.3（缩减后）**：
- title：不变（`Write quest expiry scanner tests in tests/test_quest_expiry_scanner.py`）
- description 替换为：
  `"Implement QuestExpiryWorker scheduler and write core expiry tests: 30-second scan interval failing expired active quests, writing failure cooldown, expiring item instances, releasing locks, and preserving existing terminal states."`
- status/tdd_mode：不变（pending / tdd_slice）

**新增任务 12.8**（追加到 phase 12 tasks 数组末尾）：
```json
{
  "id": "12.8",
  "title": "Write quest expiry edge case tests in tests/test_quest_expiry_edge_cases.py",
  "task_type": "testing",
  "description": "Write quest expiry edge case tests: send notification only after commit, backend startup scan failing pre-restart-expired quests, orphan lock cleanup, and concurrent expiry scan plus turn-in/pickup through the serialized write path.",
  "refs": ["docs/requirements.md", "docs/data-model.md", "docs/workflows.md"],
  "status": "pending",
  "attempts": 0,
  "verify_fails": 0,
  "tdd_mode": "tdd_slice",
  "tdd_applied": null,
  "tdd_skipped": null,
  "files_changed": [],
  "last_error": []
}
```

Task ID `"12.8"` 符合 `^\d+\.\d+$` 正则，且与 phase_id=12 的前缀一致。
Phase 12 将有 8 个任务，低于 `config.json` 的 `max_tasks_per_development_phase: 10`。

**12.4–12.7 保持不变**（每个 ≤4 个场景，预计输出 <15K tokens）。

---

## 实现顺序

| 步 | 操作 | 文件 | 风险 |
|----|------|------|------|
| 1 | 修改 `phase_handlers.py`：空 tasks → stub 注入 | `harness/phase_handlers.py` | 低 |
| 2 | 添加 2 个单元测试 | `harness/tests/unit/test_phase_handlers.py` | 无 |
| 3 | 运行 `pytest tests/unit/test_phase_handlers.py -v` 全部通过 | — | — |
| 4 | 修改 `agents.py`：追加 task ID 提醒 | `harness/agents.py` | 低 |
| 5 | 修改 `builder-execute-fix.md`：correction turn 说明 | `.claude/agents/builder-execute-fix.md` | 无 |
| 6 | commit 步骤 1–5：`fix(harness): tolerate empty-tasks correction turn` | — | — |
| 7 | `git add tests/test_quest_service.py && git commit` | — | 无 |
| 8 | 编辑 `workspace/state.json`：12.2 → complete | `workspace/state.json` | 低 |
| 9 | 编辑 `workspace/state.json`：缩减 12.3，新增 12.8 | `workspace/state.json` | 低 |
| 10 | 验证 state.json JSON 合法性 | — | — |
| 11 | Resume harness | — | — |

---

## 回归检查

| 测试 | 预期 |
|------|------|
| `test_handle_executing_rejects_missing_active_task_in_signal` | 仍 `SystemExit`（非空 ID 错误仍 HALT） |
| `test_handle_executing_rejects_wrong_phase_id` | 仍 `SystemExit` |
| `test_handle_executing_ignores_extra_task_ids_in_signal` | 仍通过 |
| `pytest tests/unit/test_phase_handlers.py -v` | 45 原有 + 2 新增 = 47 通过 |
| `pytest tests/unit/ -q` | 全量通过（864+） |

---

## 验证标准

```bash
# Part 1 单元验证
pytest harness/tests/unit/test_phase_handlers.py -v

# Part 1 全量回归
pytest harness/tests/unit/ -q

# Part 2 state.json 验证（PowerShell）
(Get-Content 'workspace\state.json' -Raw | ConvertFrom-Json).phases |
  Where-Object { $_.id -eq 12 } |
  Select-Object -ExpandProperty tasks |
  Select-Object id, status, tdd_mode

# 预期：12.1 complete, 12.2 complete, 12.3-12.8 pending

# 最终：resume harness，观察 12.3 是否在正常 token 范围内（<15K）完成
python harness/harness.py --resume
```
