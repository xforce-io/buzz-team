# 超限 session 换窗（#15 S2）

## 入口

`ChannelCursorStore` / `applyFuse` 与 Desktop ACP 无 `--task` 的 `launch`。#16 硬停后须设置 `BUZZ_WAKE_FUSE`（`turns` | `usd` | `input_tokens` | `budget_exceeded`）以及频道、帖引用、旧 `BUZZ_ACP_SESSION_ID`。金额 `unavailable` 的熔断由 #16 发信号，本票不计量。

S2 真客户端端到端依赖 #16 在 Desktop 路径发出熔断信号；本仓库先验收换窗契约与回帖形状。

## 通过条件

1. 熔断当时立即分配新 `session_id`；【熔断】回帖含原因枚举、旧/新 `session_ref`（12 位哈希），无 prompt/认证/工具正文。
2. 下一执行 turn 的 session id ≠ 熔断前 session id。
3. 使用已退役 session id 的无 task sticky/`launch` 被拒绝；执行向 tool_call = 0。
4. 回帖走 `buzz` 消息路径，不经过已熔断 session 的执行器循环。

## 证据

脱敏 session_ref、游标状态 `fused`、回帖摘录、返回码；证据留实例 `evidence/<sha>/`，不入库。未实跑 Desktop+#16 不得标 E2E pass。
