# Desktop ACP 任务映射与账本硬闸（#16）

## 入口

使用仓库外非 editable 安装的 `buzz-team --instance INSTANCE`；Desktop 路径通过 `binding_environment` 注入 `BUZZ_TASK_ID` / `BUZZ_TASK_SCOPE` 与（频道唤醒时）`BUZZ_WAKE_*`，或 `launch --task` / `BUZZ_WAKE_PAYLOAD`。

## 通过条件

1. **S1**：`session bind` 后，Desktop bind 可将 `BUZZ_TASK_ID`（及可选 `BUZZ_TASK_SCOPE`）与 `BUZZ_WAKE_SURFACE|CHANNEL|POST_REF|BODY` 写入 managed agents `env_vars`；`launch harness` 无 task 时 fail-closed；有 task 时映射字段与 CLI `--task` 一致，不从频道标题猜测。未配置的生产频道 UUID 不得出现在仓库里。
2. **S2**：task-scoped launch 在 ledger `status=budget_exceeded`（或 rotate 等价上限 / 金额 `unavailable`）时硬停（错误含 hard stop / budget exceeded），写入 `BUZZ_WAKE_FUSE=<turns|usd|input_tokens|budget_exceeded>` 并留下 `budget_gate` 事件；若已注入 wake 上下文，#15 消费该 fuse 做 【熔断】回帖 + rotate，本夹具不重验回帖文案。`context handoff` 后 `launch` 在未 consume 时拒绝，`context consume --task` 或 `launch --consume-handoff` 后可继续；不再出现永久 `cannot consume context handoff` 死胡同。
3. **S3**：同一夹具分别走 CLI `--task` 与 Desktop env `BUZZ_TASK_ID`：映射关键字段与 ledger 字段集合一致；故意损坏映射时两端均拒绝续跑。频道唤醒可用独立 `BUZZ_WAKE_*` 或 `BUZZ_WAKE_PAYLOAD` JSON，展开结果相同。

## 证据

记录命令、返回码、脱敏 task/session 标识、ledger status / handoff_status、budget_gate 事件；不记录认证、prompt 或会话正文。

## 边界

mention-gate / session rotate 实现归 #15。本夹具只验收 #16 注入 `BUZZ_WAKE_*` 与硬停写出 `BUZZ_WAKE_FUSE`；【熔断】回帖与换窗见 `session-rotate.md`。
