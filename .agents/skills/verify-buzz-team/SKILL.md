---
name: verify-buzz-team
description: 验证 buzz-team CLI、实例迁移与真实 Buzz Desktop 行为。
---

# 驾驶手册

## Launch

以 Issue 当前候选 SHA 安装到仓库外独立虚拟环境，不使用 editable 安装。按 `docs/runbook.md` 创建实例，运行 prepare 和 doctor。原环境继续运行期间禁止 bind 或启动第二套同身份 harness。

## Doctor

运行 CLI doctor、status，确认版本指纹、身份数、执行器 home 和 Desktop 配置目标。认证原地复用，不复制、不重新登录。确认目标 SHA 工作树干净，记录安装产物与源 SHA。使用临时配置先验证回退和冲突拒绝。

## Drive

读取 features/README.md 与本次 S1…Sn 对应文件。迁移预览使用同一真实 Desktop，必须先观察没有活跃任务；记录切换前状态，再按 runbook 执行。不能用修改数据库、伪造消息或 CLI 输出冒充客户端结果。

实际客户端使用可用原生应用控制工具；若改用浏览器，先完整读取 ego-browser skill。切换前后分别记录 DM、频道消息、Activity、工具结果、受限操作拒绝、会话恢复和异常反馈。只发明确带验证标记的无业务副作用请求；不向外部客户发消息。若有在途任务，等待其结束，不杀任务。

## Evidence

证据保存在实例 evidence/<候选 SHA>/，不进入 Git。记录时间、候选 SHA、命令与返回码、截图或 UI 摘录、测试消息标识、身份数量和认证文件路径/inode 是否一致；不得输出凭据内容或完整进程环境。每个 S* 对应 pass/fail/skip；未实际测试不得 pass。公开 Issue 只贴脱敏摘要，不贴私有对话。

冻结SHA后写同目录verification.json，字段为candidate_sha、compatibility_sha256（实际安装包内清单摘要）、client_verified、acceptance、client_evidence。只有本SHA客户端验证完成才标true；将精确SHA与结果的脱敏索引更新到Issue。不要把当前SHA写回源码制造新的未验收候选，或把历史验证当当前通过。

## Cleanup

关闭仅为测试启动的额外窗口，不删除测试证据、旧状态或认证。预览结束恢复原 Desktop 绑定；若预览采用保留新绑定，必须有明确用户授权和记录，不能当作发布。遇到回退冲突停止并报告，不强行覆盖新配置。
