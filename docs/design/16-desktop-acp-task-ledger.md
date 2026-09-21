# #16 Desktop ACP 挂 #6/#7 硬熔断与可消费 handoff

状态：Approved（L1 经 peng via Jenny 于 2026-09-22 Asia/Shanghai 批准；本 L2 为实现唯一事实源）。

## 1 背景

#6 任务会话映射与 #7 上下文成本账本已在 CLI `--task` 路径可用，但 Desktop ACP 长跑走薄 `launch harness|executor`，常无 `task_id`：不写映射、不累计 ledger、超限不停止。handoff 一旦 `ready`，`Runtime.launch` 会永久抛出 `executor adapter cannot consume context handoff`，无法被新 session 消费。配套 #15 负责 mention-gate / session rotate；本票只补 map + ledger + 硬闸 + handoff 消费。

相对 #7 L2「超限≠截断」：本票仅在 Desktop/ACP（及同等 task-scoped）执行向路径加硬闸，不把静默截断 prompt 合法化。

## 2 名词

- **task 映射**：#6 `SessionStore` 字段集（community / identity / scope / task_id / workspace / session_id）；缺字段或冲突 fail-closed。
- **硬闸**：ledger `status == budget_exceeded` 时拒绝同 task 的后续 `Runtime.launch`（新增执行向 tool 调用 = 0）。
- **handoff 消费**：`handoff_status` ∈ `{unavailable, ready, consumed}`；`ready` 须经显式 consume 后才允许再 launch。

## 3 目标与非目标

目标：Desktop ACP 执行向路径与 CLI `--task` 同契约挂映射与 ledger；超限硬停；handoff 可被新 session 消费；损坏映射两端 fail-closed。

非目标：不实现 #15 mention-gate/rotate；不重做 #6/#7 存储格式（仅增补 `consumed` 与闸门事件）；不改 alfred；不静默截断上下文。

## 4 设计选择

1. **Task 入口**：`launch --task` 或环境变量 `BUZZ_TASK_ID`（CLI 已读）。允许 agent `binding_environment` / Desktop `env_vars` 携带 `BUZZ_TASK_ID` 与 `BUZZ_TASK_SCOPE`（与 `BUZZ_ACP_CONFIG` 同类白名单校验）。
2. **Harness 必须 task-scoped**：`mode == harness` 且无 `task_id` → `ValueError`（执行路径必须先 `session bind`，再设 env 或传 `--task`）。`executor` 无 task 仍保持兼容。
3. **硬闸检查点**：`Runtime.launch` 在已解析映射、即将 exec 前：若 ledger 存在且 `status == budget_exceeded` → 拒绝 launch，并追加可审计 `budget_gate` 事件；ledger 缺失则允许，不发明预算。
4. **Handoff 状态机**：
   - `unavailable`：无 handoff，可 launch。
   - `ready`：未带 consume 标志 → 拒绝 launch（明确错误，不再是永久 cannot-consume）。
   - `ready` + `--consume-handoff` / `BUZZ_CONSUME_HANDOFF=1`：`consume_handoff()` 读出并标 `consumed`，然后允许 launch（映射须仍有效；换窗由 #15/operator 负责）。
   - `consumed`：允许 launch（已交接）。
5. **CLI**：`context restore` 仍只读 `ready`；新增 `context consume --task`（成功读出并标 consumed）。`launch --consume-handoff` 传给 Runtime。

## 5 模块改动

| 模块 | 改动 |
|---|---|
| `context.py` | `handoff_status` 增 `consumed`；`consume_handoff()`；`record_budget_gate()`；`report` 暴露 consumed |
| `runtime.py` | harness 缺 task fail-closed；budget 硬闸；handoff ready/consume 状态机 |
| `cli.py` | `context consume`；`launch --consume-handoff` |
| `desktop.py` | binding env 允许 `BUZZ_TASK_ID` / `BUZZ_TASK_SCOPE` |
| verify | 扩展 task-sessions / context-cost，新增 `desktop-acp-task.md` |

## 6 与 #15 边界

本票：映射注入、ledger、硬停、handoff 可消费。  
#15：mention-gate 与超限后 session rotate。硬停后的产品回帖/换窗归 #15。

## 7 测试计划

| Story | verify feature |
|---|---|
| S1 | `.agents/skills/verify-buzz-team/features/task-sessions.md` + `desktop-acp-task.md` |
| S2 | `context-cost.md` + `desktop-acp-task.md` |
| S3 | 同上夹具 CLI `--task` 与 Desktop env 双路径对照 |

Unit：`tests/test_context.py`、`tests/test_runtime.py`（硬闸、consume、harness 缺 task、binding env）。

## 8 关联

- [Issue #16](https://github.com/xforce-io/buzz-team/issues/16)
- [Issue #6](https://github.com/xforce-io/buzz-team/issues/6) / [Issue #7](https://github.com/xforce-io/buzz-team/issues/7)
- 配套 [Issue #15](https://github.com/xforce-io/buzz-team/issues/15)
