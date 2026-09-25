---
name: verify-buzz-team
description: 验证 Buzz Desktop 管理身份的 Seatbelt 薄入口与只读诊断。
---

# 驾驶手册

## Launch

冻结候选 SHA，确保工作树干净；构建普通 wheel 并装到仓库外独立虚拟环境。记录安装包和 SHA。现役身份由 Desktop 管理，预览时每次只调整一个身份；不得启动第二个同身份消费者。按 `docs/runbook.md` 记录该身份原 Agent harness、ACP command、Arguments、环境变量和回退值。先检查无活跃 turn。

## Drive

读取 `features/README.md` 及本次验收对应文件。优先使用 Desktop 原生界面修改配置，使用真实消息和实际 Seatbelt 正反例；CLI 静态输出不能代替客户端回复或 Activity。只发送带验证标记、无业务副作用的消息，不发给外部客户。异常时按身份回退，不杀在途任务、不复制认证。

## Evidence

实例外证据目录记录候选 SHA、时间、安装产物、前后 Desktop 配置的脱敏摘要、身份 home 路径/inode、真实消息标识、进程链、允许/拒绝写入结果、Activity 已知边界和回退结果。每个 S* 标记 pass/fail/skip；未测试不标 pass。公开 Issue 只贴脱敏摘要，不贴凭据或私有对话。`doctor` 的 `ok` 只表示没有 fail；`unverified` 不表示健康。

## Cleanup

关闭仅为测试启动的工具窗口。保留证据和旧状态。预览结束恢复原身份配置；生产切换须走已记录的发布与回退步骤。不要通过写 Desktop 私有库存修复 UI 不能完成的步骤。
