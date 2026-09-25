# buzz-team

面向 Buzz 的多 coding-agent 本机运行与管理层。

## 项目状态

当前为 0.1.0 迁移候选，未正式发布。包内兼容清单不预先认证当前代码；每个冻结候选的验证状态只认实例外部证据记录，仍须通过独立审查与人工发布门禁。

## 与 Buzz 的关系

Buzz 提供消息、团队协作与 agent 接入；buzz-team 提供可版本管理的本机运行机制、统一 CLI 和 coding-agent 适配层；具体 coding agent 提供推理与工具执行。buzz-team 不替代 Buzz，不自建聊天系统或模型服务。

通用代码、本机实例配置、运行状态和凭据分别管理。仓库不得包含真实身份配置、私有会话、日志、memory 内容或凭据。

## 架构

Buzz Desktop 管理生命周期，经实例薄入口调用 buzz-acp 与具体 coding agent。buzz-team 的通用运行层负责身份、目录、权限和检查；适配器处理执行器差异。它不启动与 Desktop 竞争的第二套后台团队。

| 存放位置 | 内容 |
|---|---|
| 本仓库及仓库外安装位置 | 通用源码、CLI、适配器、文档、测试 |
| 私有实例目录 | instance.local.json、私有说明、薄入口、迁移备份 |
| 既有身份状态目录 | 会话、工作区、执行器 home；迁移原地复用 |
| 执行器原认证文件 | 现有登录状态；不复制、不重写、不恢复旧令牌 |

## 能力范围

- 独立 CLI，以及不绑定 Grok 的适配器契约；首先迁移已有 Grok 运行能力。
- README 与机器可读清单中的版本兼容信息；未经验证的适配器不得宣称支持。
- 本机实例与源码分离，保留旧环境并提供验证和回退路径。
- 在 Buzz 客户端实际验证迁移前后的行为。

## 依赖与兼容

运行依赖 Python >=3.11，以及用于停机检查的 ps、lsof；受限身份依赖 macOS Seatbelt，缺失时拒绝不受限启动。安装不是认证配置过程，不会自动安装或登录执行器。

版本基线见[机器可读兼容清单](src/buzz_team/compatibility.json)：Buzz Desktop **0.5.25**、Grok **1.0.34 (3736acbc8658)**；定制 buzz-acp 没有版本输出，使用清单中的 SHA-256 标识。其源码 commit 对应关系尚未证实，不以当前检出 SHA 替代。当前候选客户端验证以 `<instance>/evidence/<candidate_sha>/verification.json` 为事实源，同时绑定完整候选 SHA、包内清单摘要和真实客户端证据；脱敏索引见 [Issue #1](https://github.com/xforce-io/buzz-team/issues/1)。缺少匹配记录即未认证，历史候选通过不自动认证当前版本。

Grok 为首个迁移适配器；acp-command 仅声明通用契约，Claude Code/Codex 尚未产品认证。实例固定本机二进制摘要，`doctor`/`diagnose` 检查变更、桥接必需参数及代理对照；摘要相同不等于端到端通过。健康输出区分 pass/fail/unverified/na；`ok` 仅表示无 fail。凭据文件存在性与代理可达性分开归因；CLI 频道读取成功不能冒充 UI/Activity 通过。见 [健康检查](.agents/skills/verify-buzz-team/features/health.md)。

## 使用

按 [运行手册](docs/runbook.md) 将包非 editable 安装在实例之外，再调用 `buzz-team --help`。通过 `--instance` 显式选择实例，不默认推断身份。`init --legacy` 转换已有本机配置，`prepare` 生成薄入口，`doctor` 静态预检，`diagnose` 加深代理探测，`bind` 仅在 Desktop 停止后切换。真实配置与证据不得提交。

开发检查：`PYTHONPATH=src python3 -m unittest discover -s tests -v`。Linux 跳过 macOS 内核测试，本机迁移验收必须运行这些测试。

## 文档

- [名词表](docs/glossary.md)
- [详细架构与契约](docs/design/1-runtime-instance-migration.md)
- [适配器](docs/adapters.md)
- [安装、预览与回退](docs/runbook.md)
- [客户端验证手册](.agents/skills/verify-buzz-team/SKILL.md)
