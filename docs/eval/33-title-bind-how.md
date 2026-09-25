# #33 keel-how：角色头衔 → p 与自提及 👀

> 历史记录：#53 已退役本文涉及的本地 ACP 代理、任务/会话状态或 Desktop 私有绑定入口。文中的旧模块、CLI 和操作步骤不再是现行契约；当前运行与回退见 [运行手册](../runbook.md)及 [#53 设计](../design/53-remove-acp-middle-layer.md)。

状态：how（只读核树，2026-09-24）。不改产品代码。供粘贴 [Issue #33](https://github.com/xforce-io/buzz-team/issues/33)；L1 见 [docs/design/33-title-bind-zhouheng-eyes.md](../design/33-title-bind-zhouheng-eyes.md)。

约束：不改 workflow owner（[#34](https://github.com/xforce-io/buzz-team/issues/34) 已关）；不改 `block/buzz`；不改 live pin `046ac43`；不把 Online 每帖改线到 `agent-executor`（[#24](https://github.com/xforce-io/buzz-team/issues/24) no-go）。

---

## Overview

「谁被 @、醒没醒」现在是**两套互不消费的机制**：

1. **Online ACP 真路径**（Desktop / 定制 `buzz-acp`）：只认事件上的 Nostr `#p` 标签是否等于**本 agent 公钥**。正文里的 `@项目经理` / `@周衡` 字符串本身不决定谁醒。见上游只读对照 `crates/buzz-acp/src/filter.rs` `match_event`、`crates/buzz-acp/src/relay.rs` `send_subscribe`。本仓库不实现这条缝。已写进 `docs/eval/24-wake-without-desktop.md`。
2. **buzz-team 残余路径**：`decideWake` 只扫本帖正文，把精确 `@token` 对照实例私有 `mention_aliases`，输出 `{allowed, reason}`。结构化 mention **一律拒绝**。这条缝只在 `Runtime.launch` 且带 `BUZZ_WAKE_SURFACE=stream`（或 fuse）时运行。Online 每帖**不**重进 `launch`。

角色头衔（「项目经理」）**没有**单独的 title→p 表。身份主键是 `sha256(relay)[:16] + "/" + pubkey`（`src/buzz_team/config.py` `identity`），不是头衔、不是显示名。

自提及 👀：**本仓库零反应代码**。可观察 👀 若存在，只能是上游 kind:7（`buzz reactions add --event … --emoji`）。buzz-team 今天既不发、也不读。

#34 已把炼丹房「站会开窗唤醒」的 workflow owner 改到周衡 `51fb6cd8…`、正文改成 `@周衡`。本票不重做那条。余下缺口是：头衔 token 仍未绑到周衡 `p`；命中后没有可核对的 👀。

---

## 1. 怎么跑

### 1.1 Online ACP：只认 `#p`，不认头衔正文

活机路径（`docs/eval/24-wake-without-desktop.md` §1.2）：

```text
频道帖（Nostr event）
  → 长跑 buzz-acp 同一 PID
      → send_subscribe：kinds + #h + （require_mention 时）#p=[本 agent 公钥]
      → match_event：tags 里存在 p=<agent_pubkey_hex> 才匹配
      → session/prompt → 已存在的 grok
  不经过 Runtime.launch / decideWake / enforceChannelWake
  进程环境通常没有 BUZZ_WAKE_*
```

上游 `match_event`（只读）：`require_mention=true` 时，在 `event.tags` 里找 `["p", <agent_pubkey_hex>, …]`。没有该标签 → 本规则不匹配，不进 prompt。**不**扫描 `event.content` 里的 `@token`，**不**读 buzz-team `mention_aliases`。

上游 `send_subscribe`（只读）：`filter.require_mention` 为真时才把 `#p=[agent_pubkey_hex]` 写进 REQ。默认 `subscribe=mentions` 就是这条。

因此：

| 帖上实际有什么 | Online 谁醒 |
|---|---|
| `#p` = 周衡公钥 | 周衡 ACP 可见；方维不可见（除非也有方维的 `p`） |
| `#p` = 方维公钥 | 只方维。这是 #33 开票时的主因（当时 workflow-owner 落方维；#34 已改） |
| 正文 `@项目经理` 或 `@周衡`，**没有**对应 `p` | 原生过滤不匹配 → 不 spawn / 不 prompt（与 #24 无 @ 三问同类） |
| 结构化 `p/workflow-owner` | 由 **workflow 配置**写出 `p` 标签；不在 buzz-team。#34 已把 owner 改到周衡 |

ACP「提及结果」若写成 `mentioned` / `not_mentioned`，指的是**这套 `#p` 过滤**，不是 `decideWake` 的 `reason`。两边字符串碰巧都能出现 `not_mentioned`，但不是同一个函数。

### 1.2 buzz-team：`@token` → 身份 key，不是直接 → p

入口：

```text
buzz-team wake decide --identity ID --channel C --post-ref R --body BODY
  → decideWake(config, identity, channel, postRef, body, surface, mentions)
```

或 Desktop 薄入口（仅当进程真的进 wrapper **且** env 已有 wake）：

```text
agent-harness / agent-executor
  → Runtime.launch
      → applyWakePayload(os.environ)
      → enforceChannelWake
          → decideWake(...)
```

`decideWake`（`src/buzz_team/wake.py`）顺序：

1. `surface == "dm"` → `{allowed: True, reason: "dm"}`，不看正文。
2. `surface != "stream"` → `ValueError("unknown wake surface")`。
3. `mentions` 非空（`None` / `[]` / `{}` 以外）→ `ValueError("structured mentions unsupported")`。`--mentions` CLI 与 `BUZZ_WAKE_MENTIONS` JSON 走同一拒绝。
4. `extractAliasTokens(body)`：从 `@` 起切到空白或 ASCII 标点（`_START_BOUNDARY` / `_END_BOUNDARY`）。
5. token 大小写折叠后若是 `freeman` / `human` → 跳过（人类点名不是 agent 命中）。
6. token **精确**落在 `aliasIndex`（各 `agents.*.mention_aliases`）→ 收入 `agentMentions`（值为**身份 key**，不是裸 pubkey）。
7. 本身份在集合中 → `{allowed: True, reason: "mentioned"}`。
8. 集合为空且该频道 `single_owner_identity == identity` → `{allowed: True, reason: "single_owner"}`。
9. 否则 `{allowed: False, reason: "not_mentioned"}`。

返回值**没有** `pubkey` 字段。调用方若要 p，必须自己 `config.agent(identity)["pubkey"]`。

`enforceChannelWake`：无 `BUZZ_WAKE_SURFACE=stream` 且无 `BUZZ_WAKE_FUSE` → 直接放行（#21 冷启）。有 stream 才读 `BUZZ_WAKE_CHANNEL` / `POST_REF` / `BODY`，缺则 `ValueError`。deny 时抛 `ChannelWakeSilent`，`exec_tool_calls=0`。

`applyWakePayload`（`src/buzz_team/desktop.py`）只展开已知键：`surface` / `channel` / `post_ref|postRef` / `body` / `scope`。**没有** title、没有 mentions、没有 pubkey。未知键 fail-closed。

### 1.3 头衔今天能不能当 alias？

`validateMentionAlias`（`src/buzz_team/wake.py`）允许非空、≤64、无 NUL、无前导 `@`、无空白、且不是 `freeman`/`human`。**没有** ASCII-only 限制。

本机探活（不入库）：

| 正文 | `extractAliasTokens` | 与 alias `项目经理` |
|---|---|---|
| `请 @项目经理 开窗` | `["项目经理"]` | 可命中 |
| `请 @「项目经理」 开窗` | `["「项目经理」"]` | 不命中（书名号不在边界集） |
| `@项目经理，开窗` | `["项目经理，开窗"]` | 不命中（全角逗号不是 `_END_BOUNDARY`） |
| alias 写成 `@项目经理` | `validateMentionAlias` 拒绝 | 配不上 |

仓库**没有**把「项目经理」写进任何 `mention_aliases`。真实表只存在于实例 `instance.local.json`，禁止提交。是否已配周衡 / 是否误配方维：本 how 从源码**无法**断言，只能说机制是精确 token → 唯一身份 key。

同一 alias 挂两个身份 → `validateMentionAliases` / `aliasIndex` 抛 `mention alias conflict`，相关身份全部进不了门（#15 fail-closed）。

### 1.4 自提及 / 👀 今天怎么（不）跑

本仓库 `src/` 与 `tests/` **没有** `reaction` / `👀` / kind:7 发送或读取。

现有发帖缝只有熔断回帖：

```text
applyFuse → sendFuseReply
  → 校验 binaries.buzz 的 sha256 pin
  → buzz_cli.rewrite（频道类型）
  → subprocess: buzz messages send --channel --reply-to --content
```

`buzz_cli.rewrite` 只处理 `messages send` 的 `--reply-to`；不认识 `reactions`。

上游只读（不改）：`block/buzz` `crates/buzz-cli/src/commands/reactions.rs` `cmd_add_reaction` → `buzz reactions add --event <hex64> --emoji "…"`，签 kind:7。Desktop `MessageReactions.tsx` 展示。buzz-acp 的 `match_event` **不**因为有反应而匹配，也不自动发 👀。

因此「自提及静默无 👀」的源码解释是：**没有发送者**。不是发了被吃掉。Online 命中时 buzz-team 根本不在 PID 里；launch 命中时也只做 allow/deny，不 ack。

「自提及」在本仓库没有独立符号。没有「作者==被 @ 身份则跳过」的分支。若 ACP 对作者==自己的帖不醒，那是上游过滤，本仓库看不见。

---

## 2. 东西在哪

### 2.1 本仓库

| 职责 | 路径 | 符号 |
|---|---|---|
| 身份 key = relay 哈希 + pubkey | `src/buzz_team/config.py` | `identity`, `Config.agent` |
| 别名校验 / 冲突 | `src/buzz_team/wake.py` | `validateMentionAlias`, `validateMentionAliases`, `aliasIndex` |
| 正文 `@token` 切分 | `src/buzz_team/wake.py` | `extractAliasTokens`, `_startsMention`, `_endsMention` |
| 点名判定 | `src/buzz_team/wake.py` | `decideWake`, `channelPolicy` |
| launch 门控 | `src/buzz_team/wake.py` | `enforceChannelWake`, `ChannelWakeSilent` |
| env 展开 | `src/buzz_team/desktop.py` | `applyWakePayload`, `_WAKE_PAYLOAD_FIELDS` |
| 启动缝 | `src/buzz_team/runtime.py` | `Runtime.launch` |
| 薄入口 | `src/buzz_team/instance.py` | `prepare` → `agent-harness` / `agent-executor` |
| bind（不写 title / alias） | `src/buzz_team/desktop.py` | `binding_diff`, `selected_rows` |
| 只读 CLI | `src/buzz_team/cli.py` | `wake decide`, `wake cursor` |
| 唯一对外发帖 | `src/buzz_team/wake.py` + `src/buzz_team/buzz_cli.py` | `sendFuseReply`, `rewrite` |
| 契约：暂无结构化 mention | `docs/design/15-channel-mention-gate-rotate.md` | §8.1、§12.1 |
| 契约：Online 谁醒不在本仓 | `docs/eval/24-wake-without-desktop.md` | §1.2、§2.5 |
| 夹具 | `tests/test_wake.py` | `MentionGateTests`, `WakeCLITests` |

本仓库 **没有**：title/role 配置键、pubkey 解析输出、`wake resolve`、reaction / 👀、ACP JSON-RPC mention 解析、workflow-owner 写入。

`Runtime.env` 注释写明：`data_environment` 是实例数据，**不是** role-name 逻辑（`src/buzz_team/runtime.py`）。

`desktop.binding_diff` 只改 `acp_command` / `agent_command` / 白名单 `env_vars`。不写 display name、title、handle。

### 2.2 上游只读（禁止本票修改）

| 职责 | 路径 | 符号 |
|---|---|---|
| `#p` 订阅 | `block/buzz` `crates/buzz-acp/src/relay.rs` | `send_subscribe` |
| `#p` 匹配 | `block/buzz` `crates/buzz-acp/src/filter.rs` | `match_event`, `SubscriptionRule.require_mention` |
| kind:7 发送 | `block/buzz` `crates/buzz-cli/src/commands/reactions.rs` | `cmd_add_reaction` |
| UI 反应展示 | `block/buzz` `desktop/src/features/messages/ui/MessageReactions.tsx` | — |

workflow `p/workflow-owner` 的事实源是 instance/workflow 配置，不是 buzz-team。#34 已关。

---

## 3. Gotchas

1. **`mentioned` 一词两义。** ACP / Ops 日志里的 `mentioned` 是 `#p`。`decideWake` 的 `reason=mentioned` 是 alias 表。用错边当验收会假绿。
2. **结构化 mention 在 buzz-team 是错误，不是解析输入。** #15 收口：非空载荷 `structured_mentions_unsupported`。不要为了接 `p/workflow-owner` 在本票打开这个口；那是 #34 的配置面。
3. **Online 不进 `launch`。** 给 `mention_aliases` 配上「项目经理」**不会**让 Desktop ACP 在只有正文、没有 `#p` 时叫醒周衡。#24 已把「每帖改经 executor」标 no-go。
4. **头衔切分对中文标点不友好。** 书名号、全角逗号会并进 token。约定标题必须是无装饰的 `项目经理`，正文也必须是 `@项目经理` 这种可切形式。
5. **别名一对多 fail-closed。** 方维若也挂 `项目经理`，两边都 `deny`，不会「随便挑一个」。
6. **返回值没有 p。** 今天 `wake decide` 只报 allowed/reason。S1「证据 = ACP mention result」若要 buzz-team 侧的 p，必须扩输出；不能从现有 JSON 读到周衡公钥。
7. **没有 👀 发送者。** 缺的是 buzz-team（或 agent）调用已有 `buzz reactions add`。不是 Desktop 把反应吞了。自动 👀 若要挂在 Online 真帖上，本仓单独做不到（同 #24：真帖不经 `launch`）。
8. **`BUZZ_WAKE_POST_REF` 不是 event id 契约。** 熔断回帖当 `--reply-to` 用。`reactions add` 要 64 位 hex event id。未校验就拿 post-ref 去 react 会打空或打错。
9. **pin / workflow / 上游都动不得。** #34 已改 owner；本 how 只描述现状。实现阶段不得借本票改 `046ac43`、workflow 或 `block/buzz`。
10. **实例表不入库。** 周衡/方维的真实 pubkey 与 alias 只在 `instance.local.json`。公开评论只许用已公开前缀（周衡 `51fb6cd8…`，#34 评论）。

---

## 4. 对 L1 的交接（不是设计）

可改、且仍在 buzz-team 边界内的只有：

- 实例私有 `mention_aliases` 把约定头衔精确绑到周衡身份（配置，可另开运维步骤；源码最多做校验/输出）。
- `decideWake` / 新只读 `wake resolve` 把 token → identity → `pubkey` 暴露成可核对 JSON。
- 在**已有 post/event id** 时，经 pin 过的 `buzz reactions add` 发 👀（新发送缝，仿 `sendFuseReply`）。

不能假装已经存在、也不能靠本仓单独补上的：

- Online ACP 把 `@项目经理` 正文解析成周衡 `#p`（上游 / 发送方）。
- 不经 `launch`、又没有 event id 的自动 👀。
- 改 workflow-owner（#34，禁止本票重做）。
