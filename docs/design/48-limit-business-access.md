# 业务身份作者与写入边界

状态：Approved（L1：Issue #48；2026-09-25 用户回复“go, keel”）。

## 1 背景

[Issue #48](https://github.com/xforce-io/buzz-team/issues/48)。七个业务身份目前允许任意作者触发，且未由本仓库套 Seatbelt。权限收紧须保留 owner 和确需参与的成员、workflow 发布者。

## 2 名词解释

作者名单：能触发业务身份回复的公钥集合，owner 仍按上游规则允许；本设计新词。其余术语见 [名词表](../glossary.md)。

## 3 目标与非目标

目标：七个业务身份仅响应名单内作者；启用身份级 Seatbelt，只允许身份运行目录及经核准的生产路径写入。

非目标：改变开发身份的响应范围；修改上游 ACP；以提示词代替文件系统约束；自动推断哪些生产目录有业务必要性。

## 4 能力

每个业务身份的实例配置显式给出 `respond_to_allowlist`；业务策略显式给出 `write_paths`。绑定将作者名单传给 Desktop 上游 ACP；运行入口在进程边界应用 Seatbelt。未配置的旧实例保持旧行为，以便先准备实例配置再切换候选版本；验收要求七个身份全部完成配置，不能以兼容模式宣称通过。

### 4.1 UI/UX

N/A。没有新页面。操作者从 Desktop 启动摘要、频道提及结果和受限写入结果判断。

## 5 思路与折衷

使用上游 `respond_to=allowlist` 与 Seatbelt 的现有宿主能力。名单按身份分别配置，业务写路径按策略配置，避免代码内写死成员或目录。放弃全员默认可用、仅依赖 Grok 内置沙箱、以及直接编辑 Desktop 行而无可回滚实例来源。写路径限制可能使未列入的工具缓存失败；灰度期间按实际业务必要性审查后调整名单，不扩大到整个 home。

## 6 架构

主路径：实例身份名单与业务策略写路径 → 配置校验 → `bind` 在 Desktop 行写 `respond_to=allowlist` 和公钥列表、保持包内 `buzz-acp` 入口 → 上游 ACP 检查消息作者；未受约束的业务 executor 启动时应用本策略 Seatbelt profile。写入身份运行目录或核准生产目录成功，其余路径被拒。

失败路径：名单格式、空名单、写路径越界、控制文件重叠在准备或启动前拒绝；缺 Seatbelt 或父进程已有未知 Seatbelt 时拒绝启动，避免静默继承较宽的约束；绑定冲突不覆盖库存；合法业务写入失败则按 receipt 回退绑定和实例配置。

## 7 模块

- `config` 校验名单和业务写路径。
- `desktop` 绑定作者准入。
- `runtime` 生成业务 Seatbelt profile，并在上游 ACP 调用业务 executor 时套用。
- `health` 将已启用业务 Seatbelt 纳入 doctor。

## 8 API/CLI

实例 `agents.<identity>.respond_to_allowlist` 为非空、去重的 64 位小写十六进制公钥数组。仅业务身份使用。`policies.<business>.write_paths` 为绝对路径数组，限定在 `production.data_root` 或人工列出的 `production.protected_paths` 下，不得覆盖控制文件、整个 home 或实例目录。字段同时存在时启用新边界；单独存在为错误。`bind` 在目标 Desktop 行写 `respond_to=allowlist` 与 `respond_to_allowlist`。回退使用 bind receipt；原库存作者策略一并恢复。

## 9 边界

owner 的隐含允许行为由上游 ACP 决定；是否纳入 workflow 发布者须按实际签名公钥确认。Seatbelt 不是读权限控制；本票只限定文件写入。临时文件使用身份级 `TMPDIR`，不得写全局 `/tmp`。受限父进程中的 executor 继承既有 Seatbelt。

## 10 迁移/兼容/回滚

先盘点作者与写路径、备份实例和 Desktop 库存，准备七个身份的公钥名单及策略路径。在隔离安装验证配置后，停稳 Desktop、逐身份绑定并重启。保留 bind receipt；业务写入或消息收发异常时停稳，恢复原实例配置及库存，重启核对。旧实例字段缺失期间不改变现役行为，但不满足验收。

## 11 测试计划

- E2E S1：七个启动摘要均为 allowlist，名单内和名单外成员各一次实际提及，后者无触发；见 `.agents/skills/verify-buzz-team/features/business-access.md`。
- E2E S2：七个业务身份均被 Seatbelt 约束；一次核准生产写入成功、一次范围外写入拒绝。
- Integration：隔离 Desktop 库存只改七个目标行，回退恢复原行；真实 `sandbox-exec` 执行正反向写入。
- Unit：名单、公钥、路径与控制文件重叠校验；缺 Seatbelt 拒绝启动。

## 12 开放问题

七个身份各自的实际作者名单以及生产写路径要从实例运维记录核对；未核对前不得绑定真实 Desktop。若上游 ACP 对 NIP-OA 消息使用 owner 身份判定，以实际签名与授权链观察结果为准。

## 13 关联

[Issue #48](https://github.com/xforce-io/buzz-team/issues/48)、[#2](https://github.com/xforce-io/buzz-team/issues/2)、[#44](https://github.com/xforce-io/buzz-team/issues/44)。
