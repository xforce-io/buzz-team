# 上下文成本（#7）

## 入口

使用仓库外非 editable 安装的 `buzz-team --instance INSTANCE context ...`。

## 通过条件

1. 已验证 task_id 可以创建账本并记录 actual、estimated、unavailable 三种指标口径。
2. 报告能给出累计输入/输出、缓存拆分、峰值上下文、耗时、重试和预算状态，且交接状态不会覆盖预算状态。
3. 未闭合工具调用时 handoff 被拒绝；完整 turn 后 handoff 原子写入，可通过 `context restore` 或带 task 的启动路径消费，且不含完整 prompt/认证。
4. handoff 失败或账本损坏时 fail-closed，不覆盖旧文件、不自动截断、不切换其它任务上下文。

## 证据

记录命令、返回码、脱敏 task/turn 标识、指标质量和文件权限；不记录私有 prompt、认证或完整工具结果。

5. （#16）`budget_exceeded` 时 task-scoped launch 硬停；`context consume` 将 handoff 标为 consumed 后允许新 launch，禁止永久 cannot-consume 死胡同。
