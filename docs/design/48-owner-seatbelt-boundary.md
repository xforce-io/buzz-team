# #48 上游作者准入与业务身份沙箱

## 1 背景

七个业务身份当前允许任意作者触发，且原业务策略直接跳过 Seatbelt。目标与验收见 [Issue #48](https://github.com/xforce-io/buzz-team/issues/48)。此前以七份固定 allowlist 和 buzz-team Desktop 绑定扩展为前提的设计已撤销。

## 2 名词解释

沿用[名词表](../glossary.md)中的运行身份和权限策略。`owner-only`、`allowlist` 是上游 `buzz-acp` 的作者准入值。

## 3 目标与非目标

目标：七个业务身份不再接受 `anyone`，并仅写入每个身份所需的运行目录、临时目录和批准的生产路径。非目标：自研作者门、默认复制同 owner 身份公钥、按任务创建额外沙箱、扩大频道权限。

## 4 能力

Desktop 对当前七个业务身份配置 `owner-only`。实机提及已验证 owner 和带 NIP-OA 授权的同 owner 身份可触发，边界外作者不触发；当前没有 owner 边界外作者的业务需求。将来有明确需求时再评估上游 allowlist。业务写路径在本机私有策略中逐项声明；Seatbelt 拒绝其余写入。

### 4.1 UI/UX

使用 Desktop 既有编辑 agent 的 Advanced 页面。允许作者看到原线程回复；不允许作者的提及不触发 turn。路径配置缺失时该身份保持旧绑定并标明待处理；配置或合法业务行为失败时回退该身份。无新界面。

## 5 思路与折衷

上游 `owner-only` 已包含 owner 与认证同 owner 身份，可避免七份重复名单。它也会允许未来新增的同 owner 身份；若业务需要固定成员集合，上游此策略并不满足，应在验证后明确范围，而不是误称 allowlist 能排除同 owner 身份。Seatbelt 只保护本机写入边界；读取权限仍按系统与上游现状处理。选择薄入口使运行安全有操作系统保障，代价是每个身份都要确认实际需要的路径。

## 6 架构

```mermaid
flowchart LR
  D[Desktop 作者与身份配置] --> A[上游 buzz-acp 作者门]
  A --> L[本机 Seatbelt 薄入口]
  L --> G[Grok]
```

主路径：Desktop 按上游策略接收已授权作者，`buzz-acp` 启动薄入口，薄入口在身份级沙箱内执行 Grok。失败路径：未经授权作者被上游忽略；沙箱配置缺失或越界写入被拒；合法消息或写入失败时只回退受影响身份。

## 7 模块

作者准入与身份由 Desktop 和 `buzz-acp` 持有；本机策略只存 home、策略类型与写路径。薄入口的运行契约由 [#53](53-remove-acp-middle-layer.md) 负责。无新的 buzz-team 作者策略或私有库存写入模块。

## 8 API/CLI

无新的对外 API。Desktop 使用原生作者策略；本机入口读取 #53 定义的策略文件并执行 Grok。策略文件不含凭据、公钥或 relay 身份。

## 9 边界

同 owner 已认证身份的隐含准入须列在最终运行策略记录里；边界外作者负例不能用另一个同 owner 身份代替。允许写路径不得包含策略文件、执行入口、Desktop 数据或其他身份 home。缺 Seatbelt 或身份 home 不匹配时拒绝启动。

## 10 迁移/兼容/回滚

先选一个业务身份完成作者和沙箱预览，再逐身份推广。每次只调整目标身份，保留当前 Desktop 配置与本机策略备份；不复制认证。回复或必要生产写入失败时恢复该身份旧值，核对身份进程和原线程结果。

## 11 测试计划

- E2E：S1–S3 对应 `.agents/skills/verify-buzz-team/features/business-access.md`。对允许、拒绝作者与允许、拒绝写入分别留真实证据。
- Integration：薄入口和 Seatbelt 继承、身份级回退。
- Unit：策略文件、home、允许写路径和缺 Seatbelt 的拒启。

## 12 开放问题

N/A：当前作者边界已按 S1 真实消息和业务记录确定；未来出现边界外作者需求时另行评估。

## 13 关联

[#44](https://github.com/xforce-io/buzz-team/issues/44)、[#53](https://github.com/xforce-io/buzz-team/issues/53)、[#54](https://github.com/xforce-io/buzz-team/issues/54)。
