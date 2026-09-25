# #16 Desktop ACP 挂 #6/#7 硬熔断与可消费 handoff

> 历史记录：#53 已退役本文涉及的本地 ACP 代理、任务/会话状态或 Desktop 私有绑定入口。文中的旧模块、CLI 和操作步骤不再是现行契约；当前运行与回退见 [运行手册](../runbook.md)及 [#53 设计](53-remove-acp-middle-layer.md)。

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

1. **Task 入口**：`launch --task` 或环境变量 `BUZZ_TASK_ID`（CLI 已读）。允许 agent `binding_environment` / Desktop `env_vars` 携带 `BUZZ_TASK_ID`、`BUZZ_TASK_SCOPE` 与 `BUZZ_WAKE_SURFACE|CHANNEL|POST_REF|BODY|SCOPE`（与 `BUZZ_ACP_CONFIG` 同类白名单校验）。`BUZZ_WAKE_FUSE` 不得作为 bind 静态值。
2. **Harness 仅在 stream-wake / 显式 ledger 路径必须 task-scoped**（#19）：`mode == harness` 且无 `task_id`，仅当 `BUZZ_WAKE_SURFACE=stream` 或显式 consume（`--consume-handoff` / `BUZZ_CONSUME_HANDOFF=1`）时 → `ValueError`（该路径必须先 `session bind`，再设 env 或传 `--task`）。普通 Desktop ACP 冷启动无 wake/task 时允许无 `task_id`，禁止用假 `BUZZ_TASK_*` 填 managed-agents。`executor` 无 task 仍保持兼容。
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
| `runtime.py` | harness 缺 task fail-closed；budget 硬闸并写 `BUZZ_WAKE_FUSE`；handoff ready/consume 状态机 |
| `cli.py` | `context consume`；`launch --consume-handoff` |
| `desktop.py` | binding env 允许 `BUZZ_TASK_*` 与 `BUZZ_WAKE_*`；`applyWakePayload` |
| verify | 扩展 task-sessions / context-cost，新增 `desktop-acp-task.md` |

## 6 与 #15 接口（wake env + fuse）

分层顺序：**mention-gate 先**（无 `task_id` 的 harness/executor 路径），**再**本票映射 / ledger / 硬闸（`task_id` 在场时）。禁止双头计量或双头回帖。

### 6.1 Desktop 注入 `BUZZ_WAKE_*`

#15 在实例已配置 `channel_wake` 或任一 `mention_aliases` 时，频道路径缺少下列环境变量则拒绝启动。本票不重做门控，只提供 Desktop bind / launch 可携带的最薄钩子：

| 变量 | 谁写 | 谁读 |
|---|---|---|
| `BUZZ_WAKE_SURFACE`（频道路径为 `stream`） | Desktop ACP 唤醒 | #15 `enforceChannelWake` |
| `BUZZ_WAKE_CHANNEL` | 同上 | 同上 |
| `BUZZ_WAKE_POST_REF` | 同上 | 同上 |
| `BUZZ_WAKE_BODY` | 同上 | 同上 |
| `BUZZ_WAKE_SCOPE` | 可选 | #15 游标 scope |
| `BUZZ_WAKE_PAYLOAD` | Desktop 可传 JSON 一次注入上述字段 | 本票 `applyWakePayload` 展开后交给 #15 |
| `BUZZ_WAKE_FUSE=<reason>` | **本票硬停时写入** | #15 消费后 【熔断】回帖 + rotate |

`binding_environment` / Desktop `env_vars` 白名单在 `BUZZ_ACP_CONFIG` / `BUZZ_TASK_*` 之外增加 `BUZZ_WAKE_SURFACE|CHANNEL|POST_REF|BODY|SCOPE`。仓库不写入生产频道 UUID；真实值只在实例私有配置或 Desktop 唤醒载荷里。

`Runtime.launch` 在门控之前调用 `applyWakePayload(os.environ)`：若存在 `BUZZ_WAKE_PAYLOAD` JSON，按字段展开为 `BUZZ_WAKE_*`，不发明缺失的 channel / post id。

### 6.2 硬停 fuse 信号

硬闸检查点在映射解析之后、exec 之前。`fuseReason(report, rotate=…)` 在 ledger 已存在时计算原因（ledger 缺失不发明预算）：

- `turns`：频道 `rotate.max_turns` 已达
- `usd`：频道 `rotate.max_usd` 已配置且金额为 `unavailable`（无 actual/estimated）
- `input_tokens`：ledger / rotate 的 input 上限已破，或 rotate 上限下 input 为 `unavailable`
- `budget_exceeded`：ledger `status == budget_exceeded` 且无法归到更细原因

硬停时 `setWakeFuse(reason)` 写入 `BUZZ_WAKE_FUSE`，并记 `budget_gate`。若当前进程已有 `BUZZ_WAKE_CHANNEL` + `BUZZ_WAKE_POST_REF`，再调用一次 #15 `enforceChannelWake(..., task_id=None)`，让其消费 fuse 做回帖/换窗；本票不重写 【熔断】文案或 cursor rotate。无 wake 上下文的 CLI `--task` 路径只设 fuse 环境变量并 `ValueError` 硬停。

## 7 测试计划

| Story | verify feature |
|---|---|
| S1 | `.agents/skills/verify-buzz-team/features/task-sessions.md` + `desktop-acp-task.md` |
| S2 | `context-cost.md` + `desktop-acp-task.md` |
| S3 | 同上夹具 CLI `--task` 与 Desktop env 双路径对照 |

Unit：`tests/test_context.py`、`tests/test_runtime.py`、`tests/test_wake.py`（硬闸 fuse env、wake payload 展开、binding wake 白名单、launch 硬停后 #15 消费 fuse）。

## 8 关联

- [Issue #16](https://github.com/xforce-io/buzz-team/issues/16)
- [Issue #6](https://github.com/xforce-io/buzz-team/issues/6) / [Issue #7](https://github.com/xforce-io/buzz-team/issues/7)
- 配套 [Issue #15](https://github.com/xforce-io/buzz-team/issues/15)
