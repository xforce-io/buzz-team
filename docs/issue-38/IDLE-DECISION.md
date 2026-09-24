# S2 idle 决策：1500 → 180

## 证据

- 2026-09-24 ~12:18 CST：`long_tool_alert` elapsed **1222s**（`find ~`）后 `idle timeout (1500s)` respawn（Issue #38 复现栏）。
- 同文件 peer 席（陆深/沈予/方维）：`idle_timeout_seconds=180`，`BUZZ_ACP_EFFORT_LEVEL=medium`（见 `before/peer-idle-effort.json`）。
- #29 / #32（tip `046ac43`）：未完成长工具不得 `turn_ended`；live grok `_x.ai/session_notification` turn_completed 被 gate 扣住。保活在 **harness**，不是座位 idle。

## 决定

**采用 180s**（与其他业务席一致），同时 effort `low`→`medium`。

保留 1500 的唯一合理理由是「长工具需要座位级保活」，但 #29/#32 已在 harness 解决；1500 反而让 `find ~` 空转接近一整段 idle 才撕池，放大无下文窗口。

`max_turn_duration_seconds=7200` / `BUZZ_ACP_MAX_TURN_DURATION=7200` **保持不变**（Issue 未要求改）。
