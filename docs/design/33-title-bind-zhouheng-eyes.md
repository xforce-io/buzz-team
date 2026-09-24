# #33 角色头衔绑定周衡 p + 自提及可见 👀

状态：**Draft（L1）**。等人 Approve 后才实现。禁止把本文标成 Approved。

Owner：Quill · Runtime。关联：[Issue #33](https://github.com/xforce-io/buzz-team/issues/33)。how：`docs/eval/33-title-bind-how.md`。

## 1 背景

炼丹房「站会开窗唤醒」曾把结构化 `p/workflow-owner` 落到方维，ACP 只醒方维，周衡 `not_mentioned`。Scout [#34](https://github.com/xforce-io/buzz-team/issues/34) 已把 workflow owner 改到周衡 `51fb6cd8…`、正文改成 `@周衡`，并关票。pin `046ac43` 不动。

次要缺口仍在：约定角色头衔（「项目经理」）没有绑到周衡的 `p`；命中后自提及静默，无 👀。排障无法用头衔或自提及确认打中的是周衡而不是运维座。

现有机制见 how，不在此重复故事。一句话：Online ACP 只认 `#p`；buzz-team 只认精确 `@alias` 且不输出 p、不发反应。

## 2 名词解释

沿用 [名词表](../glossary.md) 的运行身份、ACP、Activity。本票新增：

- **角色头衔**：实例私有、精确、无 `@` 的提及 token（约定值 `项目经理`）。它不是身份 key，也不是 workflow-owner。
- **解析命中**：头衔 token 唯一映射到周衡的运行身份，并给出其 64 位 hex `pubkey`。
- **提及确认**：对被提及事件发一条 kind:7 反应，emoji 固定 `👀`。这是可观察反馈，不是回帖，不是熔断。
- **自提及**：被解析到的身份对「点名自己」的那条帖做提及确认。作者是否就是该身份不作为跳过条件。

## 3 目标与非目标

目标：

- **S1**：约定头衔 `@项目经理` 解析到周衡 `p`，不落到方维。证据是 buzz-team 提及解析 JSON（含 `pubkey`），必要时对照 ACP `#p`（仅当发送方已经带了该 p）。
- **S2**：解析命中后，对触发帖发出至少 1 条可观察 `👀`（或人批过的等价信号），从命中到可见 ≤30s。

非目标：

- 不改 workflow 正文 / `p/workflow-owner`（#34，禁止重做）。
- 不改 `block/buzz`；不改 live pin。
- 不把 Online 每帖改线到 `agent-executor`（#24 no-go）。
- 不新开 ACP 代理、不轮询频道、不写假 `BUZZ_WAKE_*`。
- 不新增第二套 title 表（不与 `mention_aliases` 并行）。
- 不打开结构化 mention 解析（#15：非空载荷仍 fail-closed）。
- 不把真实 pubkey / 生产 alias 写进 git。

## 4 能力

### 4.1 UI/UX

无新增 GUI。频道可见变化仅限：命中后目标帖上出现周衡身份的 `👀`。Activity 不因此多开执行向工具循环。

CLI 只读/确认：

- `wake decide` 现有判定，成功时带上解析到的 `pubkey` / `tokens`。
- 新增 `wake resolve --body`：不依赖「询问的是谁」，返回 token→identity→p。
- 新增 `wake ack --identity --post-ref [--body] [--channel]`：校验 pin 后调用已有 `buzz reactions add`。`--body` 在场则必须先判定命中，未命中不得发反应。

公开 JSON 只含身份 key、pubkey、token、reason、emoji、脱敏 event ref。不含 prompt、认证、完整环境。

### 4.2 失败可见性

头衔冲突、结构化 mention、未知 surface、buzz 摘要与 pin 不符、post-ref 不是 64 位 hex、反应发送失败：非零退出，不假装命中，不写 👀。

## 5 思路与折衷

把「头衔是谁」和「Online 谁醒」分开。本票只做前者在 buzz-team 的唯一事实源，以及命中之后的 👀。后者继续由发送方的 `#p`（workflow / Desktop 点选）承担。

复用 `mention_aliases`，不建 `role_titles`。how 已证明 `项目经理` 能通过 `validateMentionAlias`，且 `@项目经理` 能被 `extractAliasTokens` 切出。第二张表只会和别名一对多冲突规则分叉。

`decideWake` 今天只回 `{allowed, reason}`，不够 S1。扩返回值和加 `wake resolve`，让「ACP mention result」在本仓有对等物：`{token, identity, pubkey}`。禁止从正文猜方维/周衡；禁止「最近发言者」。

👀 走上游已有 CLI，不改 `block/buzz`。发送缝仿 `sendFuseReply`：校验 `binaries.buzz` pin，再 `subprocess`。不经执行器工具循环，避免「先醒再自己点 👀」的 30s 不确定性。

放弃「改 buzz-acp 扫正文头衔」：禁止动上游，且 #15 明确不猜显示名。放弃「Online 自动 👀」：真帖不进 `launch`，本仓看不见 event id。放弃「让模型自己 react」：不是运行时，不能定量 ≤30s。

自动 👀 只挂在**已经持有合法 event id** 的路径：`wake ack`，以及 `enforceChannelWake` 判定 `allowed` 且 `BUZZ_WAKE_POST_REF` 是 64 位 hex 时。post-ref 不合格则不发，不发明 id。

## 6 架构

```text
正文 @项目经理
  → extractAliasTokens
  → aliasIndex（实例私有；项目经理 只挂周衡）
  → resolve: {token, identity, pubkey=周衡}
       方维不在 mapping → 其 decideWake = not_mentioned

命中 + 合法 event id
  → sendMentionAck：buzz reactions add --event <id> --emoji 👀
  → UI / reactions get 可见（≤30s）
```

主路径（S1）：实例已把 `项目经理` 只挂在周衡 → `wake resolve --body "@项目经理"` 与 `wake decide --identity <周衡>` 给出周衡 p；同正文对方面维 `not_mentioned`。

主路径（S2）：S1 命中后 `wake ack --identity <周衡> --post-ref <event> --body "@项目经理"`（或 launch 门控自动 ack）→ kind:7 👀。

未命中路径：不 ack。结构化 mention / 别名冲突 / 非 hex post-ref：fail-closed。

Online 对照（非本票实现）：发送方若已带周衡 `#p`，ACP 记周衡 `mentioned`；若只有头衔正文、没有 `#p`，ACP 仍不醒。how 已标为残余。人若要求「纯正文 `@项目经理` 也要 Online 醒周衡」→ 本 L1 **不承诺**，须另开发送方/上游票。

## 7 模块

| 模块 | 改动 |
|---|---|
| 实例配置 | 运维把 `agents.<周衡>.mention_aliases` 纳入精确 token `项目经理`（及可选显示名 `周衡`）。只许周衡。源码不写死姓名。 |
| `wake.py` | `decideWake` 成功命中时带 `pubkey` / `identity` / `tokens`；新增 `resolveMentions`、`sendMentionAck`。 |
| `cli.py` | `wake resolve`、`wake ack`。 |
| `buzz_cli.py` | 不把 `reactions add` 误送进 `messages send` 的 rewrite；未知子命令原样转发。 |
| verify | 新功能文件，见 §11。 |

`desktop.py` / `runtime.py` / `sessions.py` / workflow / pin：**不改职责**。`enforceChannelWake` 仅在已 allow 且 post-ref 合法时调用 `sendMentionAck`；缺 event id 不阻塞 allow（S1 与 S2 解耦：解析成功但无法 ack 时，ack 记失败，不把 mentioned 改成 deny）。

S2 定量「≤30s」约束的是 ack 发送+relay 可见，不是执行器回合。`sendMentionAck` 超时与 `sendFuseReply` 同级（≤20s 子进程 + 余量观察），合计 ≤30s。超时 = fail，不重试静默。

## 8 API/CLI 与配置契约

### 8.1 头衔绑定

唯一配置面：`instance.local.json` 的 `agents.<identity>.mention_aliases: ["项目经理", …]`。

规则：

1. token 走现有 `validateMentionAlias`。禁止 `@` 前缀、空白、`freeman`/`human`。
2. `项目经理` 只能出现在周衡那一条 agent 上。方维或其他身份出现同一 token → 启动期 `mention alias conflict`。
3. 正文必须是可切形式 `@项目经理`。`@「项目经理」`、`@项目经理，`（全角逗号）不算命中。不扩展边界集来「变聪明」。
4. 大小写仍区分（中文无影响）。禁止模糊匹配「项目 经理」、拼音、英文 PM。
5. 仓库不提交真实表。文档只规定字段。

不新增 `role_titles` / `title` / `display_name` 配置键。`binding_diff` 不把头衔写入 Desktop 库存。

### 8.2 解析输出（S1 证据）

`wake resolve --body TEXT [--channel CHANNEL]`：

```json
{
  "resolved": [
    {"token": "项目经理", "identity": "<relay16>/<pubkey64>", "pubkey": "<64 hex>"}
  ]
}
```

无命中：`resolved` 为空数组，exit 0。冲突或非法正文：exit 2。`--mentions` 若有人传入非空：exit 2，`structured mentions unsupported`。

`wake decide` 在 `reason=mentioned` 时额外带：

```json
{
  "allowed": true,
  "reason": "mentioned",
  "identity": "<周衡 identity>",
  "pubkey": "<周衡 64 hex>",
  "tokens": ["项目经理"]
}
```

`not_mentioned` / `single_owner` / `dm` 不发明头衔 p。`single_owner` 不是 S1 命中。

S1 定量：对约定正文，`wake resolve` 的 `resolved` 恰好 1 条，且 `pubkey` 等于实例里周衡的 `agents.*.pubkey`；对方面维 `wake decide` 为 `not_mentioned`。

ACP 对照（可选，不代替上款）：仅当测试帖的 `#p` 已是周衡时，Ops 日志允许出现周衡 `mentioned`。纯正文无 `#p` 的 Online 不醒，**不**标 S1 fail。

### 8.3 提及确认（S2）

`wake ack --identity ID --post-ref EVENT [--body TEXT] [--channel CHANNEL]`：

1. `--post-ref` 必须是 64 位 hex（与上游 `validate_hex64` 同形）。否则 exit 2，不调用 buzz。
2. 若给了 `--body`：先 `decideWake`；`allowed` 为假则 exit 2，不发 👀。
3. 校验 `binaries.buzz` pin，调用 `reactions add --event EVENT --emoji 👀`。超时或非零 → fail。
4. 成功 JSON：`{ "reacted": true, "emoji": "👀", "event_ref": "<12 hex>" }`。`event_ref` 用现有 `sessionRef` 同类脱敏，不回传完整 event id。

等价信号（仅当人在 Approve 时显式点头）：`wake ack` 成功 JSON + `buzz reactions get` 含该身份 pubkey 与 emoji `👀`。UI 上的 👀 仍是首选观察面。未点头则必须 UI 或 get 可见，不能只交 CLI stdout。

`enforceChannelWake` 自动 ack：`decision.allowed` 且 `BUZZ_WAKE_POST_REF` 合法 hex 时发一次。同一进程同一 event 不连发。自动 ack 失败写 stderr JSON，**不**把本次 allow 改成 deny。

禁止：用 `messages send` 发「👀」冒充实反应；用熔断帖；用 Activity tool 名冒充。

### 8.4 与既有契约

| 项 | 本票 | 既有 |
|---|---|---|
| 谁可 Online 醒 | 不改；仍是 `#p` | #24 / 上游 buzz-acp |
| 正文 alias 门 | 复用，扩输出 | #15 `decideWake` |
| 结构化 mention | 仍拒绝 | #15 §12.1 |
| workflow owner | 不改 | #34 |
| 熔断回帖 | 不混用 👀 | #15 `sendFuseReply` |
| pin | 不动 `046ac43` | #29/#32 |

## 9 边界

- 只覆盖 buzz-team 解析与 ack。不宣称改了 Desktop @ 自动完成或 buzz-acp 过滤。
- 一个头衔同一时刻只指向一个已注册身份。
- agent 不得改 `mention_aliases`。
- ack 用的是该 `--identity` 对应 buzz 包装器的身份；不得用方维的 buzz 给周衡「代点」👀。
- 公开输出脱敏。实例文件 0600 惯例不变。

## 10 迁移/兼容/回滚

旧实例无 `项目经理` alias：`wake resolve` 为空，S1 未就绪，不猜测。不在 `prepare`/`bind` 里自动写生产 alias。

回滚：去掉本票新增 CLI/发送缝，或从实例删掉头衔 alias。不回滚 #34 workflow，不回滚已发出的 kind:7。回滚后 Online `#p` 行为与今日相同。

## 11 测试计划

功能文件与验收故事 1:1（实现阶段新增，本 Draft 先点名）：

- S1：`.agents/skills/verify-buzz-team/features/title-bind.md`  
  夹具：周衡身份挂 `项目经理`，方维不挂。`wake resolve --body "@项目经理"` → 恰好周衡 p。`wake decide` 周衡 `mentioned`+pubkey，方维 `not_mentioned`。负向：`@「项目经理」`、全角逗号、双方同挂 alias、`--mentions` 非空。
- S2：`.agents/skills/verify-buzz-team/features/mention-ack.md`  
  单元：mock buzz，`wake ack` 在命中时调用 `reactions add --emoji 👀`，未命中 / 非 hex post-ref / pin 不符不调用。集成或活机：命中后 ≤30s `reactions get` 或 UI 可见 ≥1 条 👀。

`features/README.md` 加两行。CLI 只读成功不能冒充 Desktop UI 上的 👀，除非人批了 §8.3 等价信号。

质量门：按 `verify-buzz-team` 手册；未实跑不得 pass。证据在实例 `evidence/<sha>/`，不入库。公开 Issue 只贴脱敏摘要。

## 12 开放问题（Approve 时收口）

1. **S1 证据面（建议默认 A）。**  
   A：`wake resolve` / `wake decide` 的 p 即为「ACP mention result」在本仓的对等物。Online 纯正文无 `#p` 不醒，不挡 S1。  
   B：必须活机 `@项目经理`（无手工 `#p`）让 ACP 记周衡 `mentioned`。  
   选 B 则本票 **做不到**（要改发送方或 `block/buzz`）。请批 A，或另开票。
2. **S2 自动 vs 只 CLI（建议默认：CLI 必修，launch 自动可选）。**  
   Online 真帖没有 event id 进 buzz-team 时，验收用受控 `wake ack`（Hogan 开窗帖的真实 event id）。不要求 Online 自动 👀。
3. **等价信号（建议默认：不启用）。**  
   除非人显式同意 §8.3 等价，否则必须 UI 或 `reactions get` 看见 👀。

未圈选则按建议默认实现，仍须先有人把本文标 Approved。

## 13 关联

- [Issue #33](https://github.com/xforce-io/buzz-team/issues/33)（本票）
- [Issue #34](https://github.com/xforce-io/buzz-team/issues/34)（workflow owner；已关；勿重做）
- [Issue #15](https://github.com/xforce-io/buzz-team/issues/15) / [L1](15-channel-mention-gate-rotate.md)
- [Issue #24](https://github.com/xforce-io/buzz-team/issues/24) / [how](../eval/24-wake-without-desktop.md)
- [Issue #16](https://github.com/xforce-io/buzz-team/issues/16)（不抢映射/ledger）
