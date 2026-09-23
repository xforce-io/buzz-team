# #29 长工具 turn gate 与超时/进程消失告警

状态：L2（实现事实源；L1 Approved，peng 2026-09-23）。

## 1 范围

方案 A only：未完成长工具（含 shell `[bg]`）不得让 ACP turn 关闭；超时或进程消失必须在 ≤2 分钟内可见告警。

非目标：方案 B（inflight job 账本 + 结束后再醒）；修改 `block/buzz`；kairo 产品改动。

## 2 配置

可选 `instance.local.json` 节，未知键 fail-closed：

```json
"long_tool": {
  "timeout_seconds": 1200,
  "poll_seconds": 60
}
```

| 键 | 默认 | 约束 |
|---|---|---|
| `timeout_seconds` | 1200（20 min，落在 15–30） | 正整数 |
| `poll_seconds` | 60 | 正整数，**≤ 120**（检测延迟上限） |

环境覆盖：`BUZZ_LONG_TOOL_TIMEOUT_SECONDS`、`BUZZ_LONG_TOOL_POLL_SECONDS`。非法值 `ValueError`，不回退默认。

无新 CLI 子命令。

## 3 检查点

`Runtime.launch` 在现有 wake / task / ledger 闸之后：

- `mode == executor`：不再 `execve`。`runTurnGate` 以 stdio 中继拉起原 command（含 Seatbelt 包装），解析 NDJSON ACP。
- `mode == harness`：stdio 继承（Desktop 冷启 `stdin=null`，不伪造 turn），等待子进程。S1 协议门不在这条缝。

首次经 `agent-executor` spawn 的 grok 保持中继进程，后续 `session/prompt` 仍经过 gate。

## 4 Turn 持有

`LongToolWatch` 只活在中继进程内，不落盘（避免方案 B）。

未闭合：`pending` / `in_progress`，或带 `[bg]` / `backgrounded` 的「假 completed」。
闭合：非后台 `completed` / `failed` / `cancelled`，或 PID 退出且可判定，或 timeout / vanished 已告警。

`canCloseTurn` 为假时扣住：

- `session/prompt` JSON-RPC `result.stopReason`（含 `end_turn`）
- 带 `stopReason` 的 `session/update`

`session/cancel` 立即转发已扣住的 `stopReason` 帧（放行，不丢弃），否则 prompt JSON-RPC 可能没有 result。非 JSON / 非 ACP 行原样转发（测试夹具与诊断）。JSON-RPC batch 整包转发，不拆开持有。

无 PID 的 `[bg]`：对 executor PID 做子进程快照；仍没有则保持打开直到超时，禁止猜成功。

## 5 告警

工具存活/超时检测间隔 = `poll_seconds`。stdio 与 `session/cancel` 的中继循环保持短 tick（约 0.25s），不把 cancel 或子进程退出拖到一个 poll 周期。

| 事件 | 动作 |
|---|---|
| 超时 | `timeout` 告警，工具标失败，放行 turn |
| PID 在 agent 非后台终态之前消失（含被杀） | `exited` 告警，同上 |
| agent 后发非后台 completed/failed | 闭合，无告警 |

出口（脱敏，无 command / prompt / 凭据）：

1. stderr JSON：`type=long_tool_alert`
2. 若存在 `BUZZ_WAKE_CHANNEL` + `BUZZ_WAKE_POST_REF`：buzz 回帖 `【长工具】`（不是 `【熔断】`，不 rotate）
3. 向仍打开的 turn 注入一条 `session/update` 文本后再放行 close
4. 已有 task ledger 时追加 `long_tool_alert` 事件；没有账本不发明

回帖失败写 stderr 后仍关闭 turn，避免二次空窗。

## 6 模块

| 模块 | 改动 |
|---|---|
| `turn_gate.py` | policy、watch、ACP 分类、stdio 中继、告警 |
| `runtime.py` | executor `execve` → `runTurnGate`；task fork 子进程同样 |
| `config.py` | `validateLongTool` |
| `context.py` | 可选 `record_long_tool_alert` |

## 7 测试

| Story | 覆盖 |
|---|---|
| S1 | 假 ACP：`[bg]` + 立即 `end_turn` 必须等到 PID 退出；`canCloseTurn`；`session/cancel` 立即转发已扣住的 `stopReason`（不得丢弃） |
| S2 | 短超时 / 杀 PID → 告警；`poll_seconds > 120` 拒绝；缺省 1200/60 |

Mac/Desktop 真 grok `[bg]` 与 Activity 仍须活机验证。
