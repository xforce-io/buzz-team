# #6 任务级会话隔离与稳定恢复

> 历史记录：#53 已退役本文涉及的本地 ACP 代理、任务/会话状态或 Desktop 私有绑定入口。文中的旧模块、CLI 和操作步骤不再是现行契约；当前运行与回退见 [运行手册](../runbook.md)及 [#53 设计](53-remove-acp-middle-layer.md)。

状态：Approved（用户在会话中明确批准优化后的 L1）。

## 1 背景

Buzz 的频道和 DM 是消息投递语义，不等于任务边界。现有 buzz-team 只有身份级运行隔离，任务会话映射尚未由本机运行层持久化和校验。多个任务复用会话会把无关历史带入当前请求，并在重启后产生错误恢复或重复会话风险。

## 2 名词解释

- **任务会话映射**：见 `docs/glossary.md`，是本设计新增的持久归属记录。
- **会话范围**：Buzz 投递上下文的稳定范围，至少区分社区、频道/DM 和必要的线程范围；它不是任务标识。

## 3 目标与非目标

目标：在保留频道/DM 原有行为的前提下，为显式任务建立稳定映射；恢复前验证社区、身份、范围、任务、工作区和执行器会话归属；原子写入并支持崩溃恢复；冲突时拒绝而不静默共享历史。

非目标：不重写 Buzz 会话模型；不把线程自动视为任务；不改变 ACP 或执行器能力；不复制认证；不替代 #2 的文件系统强隔离；不猜测无任务标识的旧会话。

## 4 能力

### 4.1 UI/UX

无新增 GUI。CLI 提供显式绑定、解析、列出任务会话映射，以及带 `--task` 的启动入口。成功输出脱敏的 task/session 标识和状态；空状态返回未映射；冲突、损坏或归属不一致返回非零和可诊断错误，且不会发送执行请求。

## 5 思路与折衷

将 Buzz 投递上下文和任务上下文分层：前者由社区、身份、范围和事件确定，后者由稳定 `task_id`、工作区和 ACP `session_id` 确定。只接受显式任务入口或已有完全匹配的持久映射；不按最近活动、频道标题或线程猜测。`launch --task TASK` 会解析映射并把任务工作区、会话元数据传给执行器；不带 task 的既有启动路径保持不变。

放弃“每频道一个任务会话”，避免破坏频道语义；放弃“每条消息新建会话”，避免丢失连续推理。映射采用同目录临时文件写入后原子替换，旧记录不因恢复失败删除。

## 6 架构

分层：CLI 层负责参数和 JSON 错误契约；会话层负责键校验、归属校验和状态机；存储层负责 0600 文件、原子替换和 JSON 解析；运行层只把已验证映射提供给执行入口，不自行猜测会话。

主路径：显式任务入口 → 校验已注册身份和范围 → 创建/确认映射 → 执行器使用绑定 session → 每次恢复重新校验 → 持久化状态。

失败路径：文件损坏、字段不完整、归属变化、同任务并发恢复或原子替换失败 → 返回结构化错误、保留旧记录、不发送错误 session 请求。

## 7 模块

会话存储模块负责映射记录、幂等绑定、解析、状态更新和列出。CLI 仅调用模块，不直接拼接 JSON。工作区创建继续由现有 `Runtime.workspace` 负责；本设计不扩大为文件系统隔离。

## 8 API/CLI

CLI 新增：

- `session bind --task --community --identity --scope --workspace --session`
- `launch --task TASK MODE [-- EXECUTOR_ARGS...]`
- `session resolve --task --community --identity --scope --workspace`
- `session list`

所有命令通过 `--instance` 选择实例；`identity` 必须已注册；绑定同值重复执行幂等，冲突返回 exit 2。任务启动等待执行器退出后释放恢复占用，嵌套 executor 继承同一 owner。输出不含认证、prompt 或会话正文。

## 9 边界

映射键至少包含 community、identity、scope、task_id；session_id 不是归属证明。一个任务同一时刻最多一个恢复操作。旧无 task_id 会话不自动迁移。公开诊断仅记录脱敏标识、状态和计数。

## 10 迁移/兼容/回滚

旧实例没有映射文件时视为空状态，不修改旧身份会话。映射文件是新增私有状态；文件损坏时拒绝恢复并保留原文件供诊断。回滚删除本次新建映射文件或恢复本次变更前的 receipt，不覆盖并发产生的新状态。

## 11 测试计划

- E2E：`.agents/skills/verify-buzz-team/features/task-sessions.md`；同身份同范围创建 A/B，交替解析并模拟重启，验证互不串历史、DM/频道路由不变、冲突不发送。
- Integration：原子写入、损坏恢复、身份/社区/工作区校验、并发冲突和幂等绑定。
- Unit：键校验、状态转换、序列化、冲突检测和脱敏输出。

质量门：代表性任务的工具参数、返回处理、权限拒绝、异常恢复和最终业务结果须与基线一致；任何语义回归都阻断切换。

## 12 开放问题

真实 Buzz/ACP 适配器提供 task_id 的入口需在客户端验证阶段以现有消息事件确认；本仓库先提供显式、可审计的 CLI 契约，不猜测上游未提供的字段。

## 13 关联

- [Issue #6](https://github.com/xforce-io/buzz-team/issues/6)
- [Issue #7](https://github.com/xforce-io/buzz-team/issues/7)
- [L1 提案](https://github.com/xforce-io/buzz-team/issues/6#issuecomment-5750493043)
- [上游 session isolation](https://github.com/block/buzz/blob/main/crates/buzz-agent/README.md)
