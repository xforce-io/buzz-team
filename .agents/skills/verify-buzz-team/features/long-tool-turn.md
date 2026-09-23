# 长工具 turn gate（#29）

## 入口

仓库外非 editable 安装的 `buzz-team --instance INSTANCE`。协议门在 `launch executor`（`agent-executor` ACP stdio）。配置：`instance.local.json` 的 `long_tool` 或 `BUZZ_LONG_TOOL_TIMEOUT_SECONDS` / `BUZZ_LONG_TOOL_POLL_SECONDS`。

## 通过条件

1. **S1**：后台 / `[bg]` 长工具仍在跑时，不得出现 `session/prompt` 的 `stopReason: end_turn`（或等价 turn close，含 `_x.ai/session/prompt_complete` 与 `turn_completed`）。假 ACP 夹具：先发 `[bg]` 再立即 `end_turn`，gate 必须等到 PID 退出才放行。
   - 真 grok 自然 `[bg]` 常无 `pid=N`（`Background task started` + 随后一行纯数字 PID）。无可靠 PID 时保持打开直到超时或后续绑定该数字；不得把 `newestChild` 短命 wrapper 的退出当成工具结束。
2. **S2**：杀死该 **已绑定的可靠 PID** 或超过 `timeout_seconds`（默认 1200）后，在 `poll_seconds`（默认 60，≤120）内 stderr 出现 `type=long_tool_alert`（`timeout|exited`）；有 wake 频道上下文时回帖 `【长工具】`。不得再出现无人说话的多小时空窗。不得对猜到的 ephemeral 子进程发 `exited`。

## 证据

记录命令、返回码、脱敏 tool_ref / elapsed、告警 reason；不记录 command 正文、prompt 或凭据。

## 边界

不做 inflight job 账本（方案 B）。不改 block/buzz / kairo。Mac Desktop 真 grok `[bg]` 与 Activity 是否仍显示 turn 打开须活机验证；本夹具的 unit/integration 不能冒充客户端。
