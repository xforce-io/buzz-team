# S2 idle 决策：不采用 1500 → 180

状态：修订。尚未 apply。这是 #38 的唯一 idle 决策。`docs/issue-45/idle-decision.md` 只指向本文件。

## 证据

- 2026-09-24 ~12:18 CST：`long_tool_alert` elapsed **1222s**（`find ~`）后 `idle timeout (1500s)` respawn（Issue #38 复现栏）。
- 同文件 peer 席：`idle_timeout_seconds=180`。周衡现值为 1500。
- 合法静默上限取周衡当前 idle：1500 秒。180 不是测量值。
- `max_turn_duration_seconds=7200` / `BUZZ_ACP_MAX_TURN_DURATION=7200` 是整轮绝对上限，与 idle 分开，保持不变。

## 决定

**不采用 180 秒。** 不把周衡 `BUZZ_ACP_IDLE_TIMEOUT` 从 1500 改到 180。

原先采用 180 的理由是座位 idle 不负责长工具保活。1222 秒的静默已经证明，收到 180 会在这类工具结束前撕池。#45 要求在任何 1500→180 apply 之前先改决策。本文件就是那次修订。

`docs/issue-38/scripts/apply.sh` 的变异路径把 effort 调到 medium，idle 保持 1500，不写成 180。

## 观测（不算 S3 通过）

2026-09-24 19:31 的 `sleep 1490`（event `5633d54b545fc4bd92b629402a2683c2aa634e88696d14e4cd211f46ac190250`）被 harness 在约 15 秒后送去后台。ACP turn `01a0d32f` 于 19:32:53 结束。进程从 19:32:16 活到 21:41:28 后自己退出。21:42:30 有一条「静默任务完成」。这不满足「turn 内覆盖 1500 秒静默」。更早一次 event `b5ab68e4…` 没有回帖。
