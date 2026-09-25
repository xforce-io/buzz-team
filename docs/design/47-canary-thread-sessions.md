# 沈予线程会话灰度

状态：Approved（L1：Issue #47；2026-09-25 用户回复“go, keel”）。

## 1 背景

[Issue #47](https://github.com/xforce-io/buzz-team/issues/47)。当前 Desktop 的 9 个本机实例身份都未显式设置 `BUZZ_ACP_SESSION_POLICY` 与 `BUZZ_ACP_MAX_TURNS_PER_SESSION`。Desktop 包内 `buzz-acp` 已支持这两个上游参数：默认分别为 `channel`、`0`。历史异常用量的成因尚未确认，灰度需要把线程隔离的行为验证与用量观察分开判定。

## 2 名词解释

会话范围：一个上游 ACP provider 会话复用的消息边界；`channel` 覆盖频道，`thread` 以频道线程根帖为边界，DM 在两种策略下均按对话复用。纳入 [名词表](../glossary.md)；[运行身份](../glossary.md)沿用既有定义。

## 3 目标与非目标

目标：沈予先进入 `thread` 会话范围并按明确的轮数上限轮换；记录灰度前后用量与任务量，验证两个线程互不串上下文，再给 9 个身份逐一记录推广或保留原值的决定。

非目标：把轮数上限当作总 token 上限；把日用量变化直接解释为因果关系；修改上游代码；在灰度证明前改其他身份。

## 4 能力

本机实例的单身份 `binding_environment` 可声明 `BUZZ_ACP_SESSION_POLICY` 与 `BUZZ_ACP_MAX_TURNS_PER_SESSION`。灰度值为 `thread` 和 `4`；回退值为 `channel` 和 `0`。写入 Desktop 身份行后，以实际 `buzz-acp` 启动摘要核对，不以配置文件存在代替运行态生效。

### 4.1 UI/UX

N/A。没有新页面。操作者通过实例记录、doctor 与 Desktop 线程回复判断配置和行为。

## 5 思路与折衷

沿用 Desktop 生命周期及上游 ACP 的会话范围、主动轮换；本仓库只验证、传递两项已有上游环境变量。以单身份灰度降低会话切换风险。四轮上限可在受控消息中验证轮换，但可能增加新会话冷启动成本；在比较 token 时同时记录 turn 与任务量。放弃直接编辑全部 Desktop 身份行以及新建自研轮换器。

## 6 架构

主路径：本机实例配置 → `bind` 校验并写沈予 Desktop 绑定环境，保留原有 ACP 入口（现役为 Desktop 包内 `buzz-acp`）→ Desktop 重启 → 包内 `buzz-acp` 解析上游变量 → 以线程根帖选择会话并在第 4 个完成 turn 后使该范围会话失效 → 下一帖建立新会话。

失败路径：非法策略或轮数在绑定前拒绝；绑定冲突不改库存；启动摘要不匹配、跨线程引用或回复失败时按备份回退沈予的两项值。其余身份继续原配置。

## 7 模块

- 实例配置与 Desktop 绑定：现有 `binding_environment` 的允许键和取值校验仅扩展这两项，保持其他环境及认证不变。
- `buzz-acp`：仅使用 Desktop 包内实现，不改代码或二进制。
- 灰度记录：本机实例的脱敏 evidence 记录每日汇总与运行态，不加入仓库或 issue 正文。

## 8 API/CLI

`agents.<id>.binding_environment` 新增可接受键：

| 键 | 接受值 | 灰度值 | 回退值 |
|---|---|---|---|
| `BUZZ_ACP_SESSION_POLICY` | `channel`、`thread` | `thread` | `channel` |
| `BUZZ_ACP_MAX_TURNS_PER_SESSION` | 十进制整数 `0`–`1000` | `4` | `0` |

`bind` 仍需 Desktop 停止。回退时显式写 `channel`/`0`，因为现有绑定会保留其他未知环境键，不能仅删除实例配置中的键就声称恢复默认。

## 9 边界

DM 仍是 conversation 范围。轮数上限按完成 turn 计数，不会限制单 turn 或总账单。灰度用量采用沈予本机 Grok `usage.json` 中 `turns[].endedAt`（北京时间）、`totalTokens`，以 session ID 去重并记缺失项；任务量、模型/版本变化与异常另列，不把低流量日冒充节省。公开记录只给聚合数字。

## 10 迁移/兼容/回滚

先备份 Desktop 库存与实例配置；仅在停稳后绑定沈予，重启后核对进程摘要。至少运行 1 天、至多 2 天。出现错误时停稳、将两项显式设为 `channel`/`0`、重新绑定并重启核对。是否推广由 S1/S2 的证据决定；S3 给每个身份留下决定与实际值，不把未推广当失败。

## 11 测试计划

- E2E S1：沈予启动摘要为 `thread`/`4`；灰度前后各至少 1 个完整自然日的 token、turn、任务量和缺失量记录。路径见 `.agents/skills/verify-buzz-team/features/session-policy.md`。
- E2E S2：两个线程各一条互斥上下文与回复；同一线程完成 4 个 turn 后下一帖仍可回复且发生轮换。
- E2E S3：9/9 身份各有“推广”或“保留及理由”，运行态与决定一致。
- Integration：隔离 Desktop 库存中绑定仅修改目标身份；错误值拒绝且库存原字节不变；显式回退值生效。
- Unit：两项环境变量取值边界、默认行为与非目标身份保持。

## 12 开放问题

灰度日任务量可能与基线不等；只报告差异及可能的混杂因素。若无足够真实任务量，则延长到 2 天并标注数据不足，不凭受控测试帖推断成本收益。

## 13 关联

[Issue #47](https://github.com/xforce-io/buzz-team/issues/47)、[#6](https://github.com/xforce-io/buzz-team/issues/6)、[#7](https://github.com/xforce-io/buzz-team/issues/7)、[#44](https://github.com/xforce-io/buzz-team/issues/44)。
