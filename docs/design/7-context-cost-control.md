# #7 按任务测量并控制上下文成本

状态：Approved（用户在会话中明确批准优化后的 L1）。

## 1 背景

仓库目前没有按任务记录输入、输出、缓存、峰值上下文、重试和交接成本。prefix cache 命中率不能证明上下文健康，也不能证明业务结果没有下降。#6 提供稳定 task_id 后，#7 才能把成本与正确任务关联。

## 2 名词解释

- **上下文交接**：见 `docs/glossary.md`，只在完整 turn 后用结构化状态建立可恢复边界。
- **成本账本**：见 `docs/glossary.md`，记录脱敏计数，不保存完整 prompt、工具正文或认证。
- **测量质量**：每个数值标记 `actual`、`estimated` 或 `unavailable`；不同质量不能冒充同一种精度。

## 3 目标与非目标

目标：按 task_id 记录可审计成本；区分 provider 实际值、本地估算和不可用；在预算预警/阶段边界提供安全交接；交接失败保留旧上下文或安全停止；通过基线对比保证工具和业务结果不回归。

非目标：不静默截断；不删除系统/安全/权限约束；不压缩未闭合 turn；不改变模型、工具、权限、消息位置或任务目标；不伪造费用；不以 token 下降掩盖质量下降。

## 4 能力

### 4.1 UI/UX

无新增 GUI。CLI 提供成本账本创建、turn 记录、结构化报告和 handoff 写入。报告显示 actual/estimated/unavailable、峰值、预算状态和交接状态；不可用指标明确显示 `unavailable`。预算超限只产生可诊断状态，不自动截断或改变业务请求。

## 5 思路与折衷

稳定系统/工具契约放在可复用前缀，任务动态状态放在后部；成本记录不修改提示词。预算按 task/provider 能力设置，不采用固定轮数。交接只发生在 turn 完成且没有未闭合 tool_call/tool_result 时。

交接必须保留目标与约束、权限/安全规则、已验证事实、精确工作区/提交标识、工具结果摘要、未决事项、审批状态和下一步；代码与配置仍以工作区和存储为权威源，交接文件不替代源文件。写入和状态切换原子完成，失败不切换到不完整交接。

放弃只保留最近 N 条消息，因为会丢失长期约束和工具因果；放弃把不可得 provider 数据猜成精确 token/费用；放弃在执行中间压缩，以保证业务行为稳定。

## 6 架构

分层：CLI 层负责参数和 JSON 契约；账本层负责测量质量、累计、峰值和预算状态；handoff 层负责字段完整性、未闭合工具调用保护、私有原子写入；运行适配层可读取报告/handoff，不把账本当作 prompt 正文。

主路径：已验证 task_id → 创建账本 → 每个完整 turn 记录 → 预算预警/阶段边界 → 检查未闭合工具调用 → 生成并校验 handoff → 原子切换 → 继续任务。

失败路径：task_id 不合法、指标无法关联、预算配置错误、handoff 字段缺失、未闭合工具调用或写入失败 → 结构化失败；旧账本和旧 handoff 不覆盖，不静默截断或共享其它任务上下文。

## 7 模块

成本账本模块保存每个 task_id 的 JSON 计数和事件；handoff 模块保存私有结构化状态。两者均使用锁、临时文件、fsync 和原子替换。模块不读取或保存认证、完整 prompt、完整工具结果或会话正文。

## 8 API/CLI

- `context start --task TASK [--max-input-tokens N] [--max-context-tokens N]`
- `context record --task TASK --turn TURN --provider P --model M --input-tokens VALUE --output-tokens VALUE ...`
- `context handoff --task TASK --goal TEXT --next-step TEXT --workspace-ref REF --approval-state STATE [--constraint TEXT] [--fact TEXT] [--pending TEXT] [--tool-result TEXT] [--open-tool-calls N]`
- `context report --task TASK`

`VALUE` 可以是非负整数；provider 不提供时必须传 `unavailable`，并保留质量标记。所有输出不含 prompt 和认证。

## 9 边界

每条记录关联 task_id/turn_id；指标字段标记 actual/estimated/unavailable；缓存输入、未缓存输入、上下文峰值和交接成本分开。预算超限不等于允许截断。handoff 不能在 `open_tool_calls > 0` 时提交。私有文件 0600，目录 0700。

## 10 迁移/兼容/回滚

没有账本文件视为未采集，不影响既有任务；没有 token 能力的 provider 使用 unavailable，不改变执行。新增账本/handoff 均为私有状态。写入失败或质量回归时删除本次未生效的临时文件，继续旧上下文或由上层安全停止；不回滚已有认证、会话或工作区。

## 11 测试计划

- E2E：`.agents/skills/verify-buzz-team/features/context-cost.md`；同一 task_id 记录基线与控制组，产生预算预警，完成无未闭合工具调用的 handoff，恢复报告并核对结果/工具/权限/消息行为。
- Integration：实际 CLI 安装、账本原子写入、actual/estimated/unavailable、预算状态、handoff 原子写入和失败回退。
- Unit：计数累计、峰值、质量校验、脱敏、字段完整性和未闭合工具调用保护。

质量门：代表性任务的最终业务结果、工具名/参数/返回处理、权限拒绝、异常恢复、消息位置和重复发送与基线一致；任一关键事实丢失或质量回归均失败，即使 token 下降也不能通过。

## 12 开放问题

不同执行器的真实 token/cache 字段需在适配器验证阶段登记能力矩阵；本仓库不把本地字符估算冒充 provider 计量。

## 13 关联

- [Issue #7](https://github.com/xforce-io/buzz-team/issues/7)
- [Issue #6](https://github.com/xforce-io/buzz-team/issues/6)
- [L1 提案](https://github.com/xforce-io/buzz-team/issues/7#issuecomment-5750493446)
- [上游 bounded history/handoff](https://github.com/block/buzz/blob/main/crates/buzz-agent/README.md)
- [上游 agent vision](https://github.com/block/buzz/blob/main/VISION_AGENT.md)
