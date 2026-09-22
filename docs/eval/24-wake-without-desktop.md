# #24 评估：不依赖 Desktop 注入的频道 wake / mention 控烧

状态：评估收口（2026-09-22）。Staff/peng 先核无 @；parent 活机三问已贴 [Issue #24](https://github.com/xforce-io/buzz-team/issues/24#issuecomment-5775220603)。

**票级结论：downgrade。** 强制把 Online 每帖改经 `agent-executor`：**no-go**（技术做不到，且产品上不应要求）。不改 `block/buzz`；禁假 `BUZZ_WAKE_*`；#23 保持 park。

本文件供 parent 粘贴到 Issue #24。上游只读对照，未改。

---

## Overview

#15/#16 接收端已在 buzz-team 落地：`decideWake` / `enforceChannelWake` / `applyWakePayload` / ledger 硬闸。它们的**唯一运行时钩子**是 `Runtime.launch` 读进程环境里的 `BUZZ_WAKE_*`。

活机 Online @（炼丹房 @沈予，2026-09-22）的真路径是：长跑 `buzz-acp` 同一 PID 收帖，再 `session/prompt` 给已存在的 `grok` 子进程。该路径**不** re-spawn Desktop ACP，**不**进 `agent-executor`，**不**带 `BUZZ_WAKE_*`。

提案：「每帖改经 `agent-executor`，并从 ACP 回合载荷（非 env）读频道/帖/正文，再跑现有 `decideWake` / `enforceChannelWake`」。

Staff/peng：**不要默认要求把 Online 回合改线到 executor。** 先核无 @ 帖是否已经：(a) 不回帖 (b) Activity 执行向 tool_call = 0 (c) 无明显 token 尖峰。

活机（2026-09-22 18:52:38 Asia/Shanghai，炼丹房，`mention_pubkeys=[]`）三问**成立**：无新 `grok agent` spawn、ACP PID 不变、Hogan Activity ~75s 无执行向 tool、freeman 日志无增长。对照：更早的 @沈予 **会**在同一 ACP PID 下 spawn grok 子进程。原生 buzz-acp mention 过滤已经挡住「未 @ 全员唤醒」这条原痛点。

因此 #15 env 门对 Online ACP「谁醒」**冗余**。在「只改 buzz-team、零改上游、禁假 env」下，改线提案 (a)(b) **技术上也不可行**——但这不再是主因。谁醒由 Desktop/buzz-acp 的 @ / `#p` 承担；buzz-team 不要再铺一条 Online 路径。

---

## 1. 今天怎么跑

### 1.1 设计意图（buzz-team 文档里的路径）

`docs/design/1-runtime-instance-migration.md` 画的是：

```text
Buzz Desktop（生命周期）
  → acp_command = <instance>/bin/agent-harness
      → buzz-team launch harness
          → execve binaries.harness（定制 buzz-acp）
              → 子进程 BUZZ_ACP_AGENT_COMMAND = <instance>/bin/agent-executor
                  → buzz-team launch executor
                      → execve grok
```

`desktop.binding_diff` 已把库存改成这两条薄入口：

```168:169:src/buzz_team/desktop.py
        row["acp_command"] = str(config.instance / "bin/agent-harness")
        row["agent_command"] = str(config.instance / "bin/agent-executor")
```

`instance.prepare` 生成的 wrapper 只做一件事：转进 `launch`，然后 `Runtime.launch` **替换自身**：

```106:111:src/buzz_team/instance.py
    commands = {"agent-harness": "launch harness --", "agent-executor": "launch executor --",
                "buzz": "buzz --", "agent-worktree": "workspace"}
    for name, command in commands.items():
        target = config.instance / "bin" / name
        write_private(target, f'#!/bin/sh\nset -eu\n{prefix}{command} "$@"\n')
```

```118:127:src/buzz_team/runtime.py
    def launch(self, mode: str, args: list[str], task_id: str | None = None,
               task_scope: str | None = None, *, consume_handoff: bool = False):
        from .desktop import applyWakePayload
        from .instance import digest
        from .wake import enforceChannelWake
        applyWakePayload(os.environ)
        if mode == "harness" and not task_id and _harnessRequiresTaskId(consumeHandoff=consume_handoff):
            raise ValueError(
                "desktop ACP harness launch requires task_id; bind session and set BUZZ_TASK_ID or pass --task")
        wakeEnv = enforceChannelWake(self, mode, task_id)
```

门控读的是 **env**，不是 ACP JSON-RPC：

```455:475:src/buzz_team/wake.py
def enforceChannelWake(runtime, mode: str, taskId: str | None) -> dict[str, str]:
    """Gate Desktop/ACP channel launches. Remaining hook: Desktop must set BUZZ_WAKE_*."""
    ...
    # Cold-start ACP has no BUZZ_WAKE_*. channel_wake config alone must not gate those launches.
    needsGate = surface == "stream" or bool(fuseReason)
    if not needsGate:
        return extra
```

#21 已收口：无 `BUZZ_WAKE_SURFACE=stream`、无 fuse 的冷启动**必须**放行。因此「实例配了 `channel_wake` / `mention_aliases`」拦不住长跑 ACP。这是刻意行为，不是漏网。

### 1.2 活机 Online @ 真路径（#23 测量 + 上游只读对照）

Staff/Scout 活机（pin `5daaa3d+`）：

- ACP **同一 PID**，不因 @沈予 re-spawn
- 树里是 `buzz-acp` → `grok agent`，**没有** `agent-executor`
- 进程环境 **没有** `BUZZ_WAKE_*`
- 从未打印 `buzz-team: launching …`，从未进 `enforceChannelWake`

只读对照公开仓 `block/buzz`（评估时 `main`，未改）：

| 步骤 | 上游符号 | 含义 |
|---|---|---|
| 冷启/首启 | `desktop/.../runtime.rs` `spawn_agent_child` | Desktop 起的是 `record.acp_command`。`stdin` **null**，stdout/stderr 进日志。Desktop **不对** harness 讲 ACP。 |
| agent 二进制 | 同函数 `BUZZ_ACP_AGENT_COMMAND` | 来自 **persona harness descriptor**（`resolve_effective_harness_descriptor`），**不是** `record.agent_command`。bind 写入的 `agent_command=agent-executor` 在这条缝上不是事实源。 |
| 保留键 | `reserved_env_keys.rs` | `BUZZ_ACP_AGENT_COMMAND` / `ARGS` 在保留名单里。实例 `binding_environment` / Desktop `env_vars` **不能**覆盖。 |
| 每帖 | `crates/buzz-acp` `run_prompt_task` | 长跑 buzz-acp 组 batch，调 `session_prompt_blocks_with_idle_timeout`。 |
| ACP 载荷 | `build_prompt_params` | 只有 `{sessionId, prompt:[{type:text,text}]}`。**无** channel_id、event_id、`_meta`。 |

因此「ACP 回合载荷」若存在，是 **buzz-acp → grok** 的 stdio，不是 Desktop → buzz-team。buzz-team 在 `execve` 之后已经离开该 PID。

```text
冷启（有时经 agent-harness，有时 Desktop 直接起 bundled buzz-acp）
  Desktop spawn_agent_child(acp_command, stdin=null)
    → [可选] launch harness：无 BUZZ_WAKE_* → #21 放行 → execve buzz-acp
    → buzz-acp 长跑（同一 PID）

Online @ 每帖（真烧钱路径）
  频道帖 → buzz-acp 订阅/queue
    → run_prompt_task
    → session/prompt(sessionId, 拼好的文本块) → 已存在的 grok
    → 工具循环
  不经过 Runtime.launch / enforceChannelWake / applyWakePayload
```

`Runtime.launch(harness)` 会把 `BUZZ_ACP_AGENT_COMMAND` 写成 `agent-executor`。活机子进程仍是 `grok agent`，说明这条 overwrite **没有**作用在被测 ACP 上。最简解释：该 PID 的 `acp_command` 仍是 bundled buzz-acp，或 Desktop 在 bind 之后又按 persona 重写了启动缝。**即使 overwrite 生效**，也只影响 **pool 首次 spawn**；之后每帖仍是对已存在 grok 的 `session/prompt`，不会再进 `launch executor`。

注意：有 @沈予 的测量只证明「被 @ 时绕过 buzz-team launch，且会在同一 ACP 下 spawn grok」。它**不能**单独证明「无 @ 也会醒」。无 @ 对照见 §2.5：不 spawn、不进执行向 tool。

---

## 2. 代码在哪（本仓库）

| 职责 | 路径 | 符号 |
|---|---|---|
| 点名判定 | `src/buzz_team/wake.py` | `decideWake`, `extractAliasTokens`, `channelPolicy`, `aliasIndex` |
| 启动门控 | `src/buzz_team/wake.py` | `enforceChannelWake`, `ChannelWakeSilent` |
| 熔断换窗 | `src/buzz_team/wake.py` | `applyFuse`, `ChannelCursorStore`, `sendFuseReply` |
| env 展开 | `src/buzz_team/desktop.py` | `applyWakePayload`, `WAKE_BINDING_KEYS`, `ALLOWED_BINDING_KEYS` |
| 启动缝 | `src/buzz_team/runtime.py` | `Runtime.launch`, `_harnessRequiresTaskId`, `_signalWakeFuse` |
| 薄入口 | `src/buzz_team/instance.py` | `prepare` → `agent-harness` / `agent-executor` |
| bind | `src/buzz_team/desktop.py` | `binding_diff`, `bind` |
| 只读 CLI | `src/buzz_team/cli.py` | `wake decide`, `wake cursor` |
| 账本硬闸 | `src/buzz_team/context.py` | `fuseReason`, `setWakeFuse`, `record_budget_gate` |
| 契约 | `docs/design/15-channel-mention-gate-rotate.md` | §8.6：剩余钩子 = Desktop 注入 env |
| 契约 | `docs/design/16-desktop-acp-task-ledger.md` | §6.1：`BUZZ_WAKE_*` 由 Desktop 写 |

本仓库 **没有**：ACP JSON-RPC 解析器、stdio 代理、`session/prompt` 夹具、从 prompt 文本反推 channel/post 的逻辑。

---

## 2.5 无 @ 时谁在挡？（Staff/peng 要求先核的活机直觉）

buzz-acp **默认**就是 mention 订阅，不是全频道广播。只读上游（未改）：

| 默认 | 符号 | 效果 |
|---|---|---|
| `--subscribe mentions` | `CliArgs.subscribe` default `"mentions"` | 只订 kind 9 / 工作流 / reminder |
| `require_mention = !no_mention_filter` | `SubscribeMode::Mentions` 组 rule | 事件必须带指向**本 agent 公钥**的 `p` 标签 |
| 无 `p` 标签 | `filter.rs` `match_event` / `ChannelFilter.require_mention` | 匹配失败，不进 queue，不 `session/prompt` |
| README 产品语义 | `crates/buzz-acp/README.md` | 「listens for @mentions」「When someone @mentions the agent」；论坛帖要 `--no-mention-filter` 才会看见 |

Desktop 冷启 `spawn_agent_child` **没有**写入 `BUZZ_ACP_SUBSCRIBE=all` 或 `BUZZ_ACP_NO_MENTION_FILTER`（保留名单里也没有这两键当默认覆盖）。活机 Online ACP 与默认 mentions + `#p` 一致。

**活机无 @ 三问（parent，2026-09-22，已成立）：**

| 项 | 证据 |
|---|---|
| 帖 | 18:52:38 Asia/Shanghai · 炼丹房 · `[verify-no-mention-20260922-1845]` · event `3ec531f2…` · `mention_pubkeys=[]` |
| (a) 不回帖 / 不醒 | Scout ps：无新 `grok agent` spawn；已有子进程 start 均早于该帖；ACP PID 41318–41407 未变 |
| (b) 执行向 tool_call = 0 | Hogan Activity ~75s：无新 spawn；未见 PARAMETERS / function_call / mcp / Shell |
| (c) 无明显 token 尖峰 | freeman 身份日志无增长（对照：更早 @沈予 **会**在同一 ACP PID 下 spawn grok 子进程） |
| 源 | Issue #24 评论；`~/lab/buzz/evidence/5daaa3d…/mention-e2e/no-mention-observe.json`（本环境无该文件，不复跑） |

peng 直觉成立。原生过滤已经覆盖「未 @ 全员唤醒」原痛点。**不要**因此改 buzz-team 路径。

| 频道动作 | 现网（默认 buzz-acp + 本轮对照） | #15 `decideWake` 还要不要坐在 Online 上 |
|---|---|---|
| 普通讨论、无 @、无 `p` 标签 | **已验**：不 spawn、无执行向 tool、日志不涨 | **冗余** |
| UI @某身份（`p` 标签） | **已验对照**：同 ACP 下会 spawn grok | 原生已按公钥点名；别名表是另一套 |
| 只打字 `@沈予`、没有 `p` 标签 | 未另测；原生可能不醒（#15 会按正文 alias 判） | 语义差；不要为对齐去改线 executor |
| 已被 @ 后的 sticky 续烧 / 超限 | 原生会继续跑同一 session | **这才是 buzz-team 可选残余**（fuse/rotate/ledger），不是 Online「谁醒」必修 |

#15 L2（2026-09-21）写「未 @ 也进入执行向长循环、单日 ~$306」。**已被 2026-09-22 无 @ 活机否定为现网事实。** 可能当时 `subscribe=all` / `no_mention_filter`，或把「@ 之后 sticky 续烧」记成「每帖未 @ 也醒」。不得再用那句证明必须改 executor。

---

## 3. 可行性

### (a) 只用 Desktop 已认的 bind / config / wrapper，把 Online 每帖赶到 `agent-executor`？

**不可行。**

Desktop 已认、且 buzz-team 已经在用的只有：

1. `managed-agents.json` 的 `acp_command` / `agent_command`（`binding_diff`）
2. `env_vars` 白名单（`BUZZ_ACP_CONFIG` / `BUZZ_TASK_*` / `BUZZ_WAKE_*` 静态键——**禁止**用假 wake 填）
3. `agent-harness` / `agent-executor` 薄入口（`prepare`）

这些全部是 **进程启动** 契约，不是 **每帖** 契约。

卡死点：

1. **Online @ 不重进 `launch`。** 活机同一 PID。`enforceChannelWake` 只在 `Runtime.launch` 开头跑一次。
2. **wrapper 是 `execve`，不是代理。** `launch` 通过后进程变成 buzz-acp 或 grok。后续 `session/prompt` 不再经过 Python。
3. **`record.agent_command` 不是 Desktop 的 spawn 事实源。** 上游 `spawn_agent_child` 用 persona descriptor 写 `BUZZ_ACP_AGENT_COMMAND`。bind 写 `agent-executor` 不能强迫每帖走 executor。
4. **该键是 reserved。** 实例 `binding_environment` 改不了 `BUZZ_ACP_AGENT_COMMAND`。
5. **假想「harness overwrite 已生效」仍不够。** 最多让 pool **第一次** spawn 经过 `launch executor`；无 `BUZZ_WAKE_SURFACE=stream` 时 #21 仍放行；之后每帖仍是对已存在 grok 的 prompt。

要把每帖赶进 executor，必须让 buzz-acp **每帖重新 spawn** 子进程，或换掉 buzz-acp 的 pool。两者都在 `block/buzz`，本票禁止。

在 buzz-team 新写一个长跑 ACP stdio 代理，**不是**「Desktop 已认的 wrapper」。那是新产品，且 Staff/peng 已明确：**不要默认要求这条改线**。谁醒应先认原生 `@` / `#p`。

### (b) 在 buzz-team 内从 ACP 回合载荷读 channel / post / body？

**不可行（结构化字段不存在；猜正文禁止）。**

1. **Desktop 冷启不对 harness 讲 ACP。** `spawn_agent_child` 的 stdin 是 null。没有「Desktop → agent-harness」的 turn payload 可读。
2. **真 ACP 在 buzz-acp → grok。** `build_prompt_params`（上游 `crates/buzz-acp/src/acp.rs`）只序列化：

   ```json
   {"sessionId":"…","prompt":[{"type":"text","text":"…"}]}
   ```

   无 channel UUID、无 event id、无 `_meta`。`channel_id` / `event.id` 只活在 buzz-acp 内存（batch、observer `triggeringEventIds`），不下发到 agent 的 prompt params。
3. **文本块不是 `BUZZ_WAKE_BODY`。** `format_prompt` 拼的是 Base / system / canvas / 会话上下文 / 资料。用 `extractAliasTokens` 扫整段会误伤历史帖与系统段。#15：不猜、不继承父帖、非空结构化 mention 则 deny。
4. **`decideWake` / `enforceChannelWake` 的契约要四件套。** `identity` + `channel` + `postRef` + `body`。缺 channel/post_ref 且 `surface=stream` → `channel wake context missing; refusing launch`。禁止发明 UUID（`applyWakePayload` 连 `channel_id` 这种未知键都拒）。
5. **熔断回帖同样要真 channel + post_ref。** `sendFuseReply` → `messages send --channel … --reply-to …`。没有 post_ref 就做不了 #15 S2。

**假设（未在活机抓包，标假设）：** 拼好的 prompt 某处可能含当帖原文。即便如此，也不是稳定字段契约；不能当 `BUZZ_WAKE_BODY`，更变不出 post_ref。

---

## 4. 结论：**downgrade**（执行器改线：**no-go**）

| 对象 | 判定 | 一句话 |
|---|---|---|
| 票 #24 / #15 Online「谁醒」E2E | **downgrade** | 无 @ 三问成立；原生 `@`/`#p` 已挡全员唤醒。#15 env 门对 Online「谁醒」冗余。 |
| 「每帖改经 agent-executor + 读 ACP 载荷」 | **no-go** | 产品上不应要求；buzz-team 单独也做不到。 |
| 开 ACP 代理 / 改 `block/buzz` 实现票 | **no-go** | 约束未变；#23 park。 |

不要把「被 @ 时绕过 launch」误读成「必须把每帖赶进 executor」。无 @ 已被原生过滤，改线没有产品收益。

### 风险（若无视结论硬做）

| 风险 | 后果 |
|---|---|
| 默认要求 executor 改线 | 重复实现谁醒；Staff/peng 已否 |
| 把 `execve` wrapper 改成长跑 ACP 代理 | 新产品；Activity / permission / steer 回归面大 |
| 从 prompt 文本猜 @ | 误拦或误放；违反 #15 fail-closed |
| 发明 channel/post id | 熔断回帖打错线程 |
| 静态 `BUZZ_WAKE_*` | 全员假唤醒或冷启全拒 |
| 把 2026-09-21「未 @ 也烧」当成 2026-09-22 事实 | 推错下一刀 |

---

## 5. buzz-team 里什么仍然值钱

谁醒（未 @ 不跑）是 **Desktop/buzz-acp 的现网职责**，已被活机验收。buzz-team **不要**为 Online E2E 再铺路径。留下的是：真正走进 `Runtime.launch` 时的可选门控，以及被 @ 之后的计量 / 硬停 / 换窗 / 离线夹具。这些是 **残余价值，不是 Online 真帖必修**。

### 仍然值钱（可选残余，非 Online「谁醒」必修）

| 能力 | 护的是哪条缝 | 不是什么 |
|---|---|---|
| 原生 buzz-acp `subscribe=mentions` + `#p` | Online 未 @ 不醒（本轮已验） | 不是 buzz-team 代码 |
| `Runtime.launch` → `enforceChannelWake` / `applyWakePayload` | **仅当**进程真的进 wrapper：`agent-harness` / `agent-executor` 冷启或显式 spawn，且已有 `BUZZ_WAKE_SURFACE=stream` 或 `BUZZ_WAKE_FUSE` | 不是每帖 Online ACP；无这些 env 时 #21 放行 |
| `wake decide` / `decideWake` | 离线/CLI 别名策略与验收夹具 | 不是 Online 运行时 |
| #21 冷启放行 | 无假 `BUZZ_WAKE_*` 也能起 ACP | 不是控烧 |
| `ChannelCursorStore` / `applyFuse` / 【熔断】回帖 | **@ 之后**、且已有 channel/post/session 时的换窗 | Online sticky 未接线 |
| `ContextLedger` / `fuseReason` / `setWakeFuse` | 已 `session bind` + `BUZZ_TASK_ID` 的硬闸 | 普通无 task ACP 不触发（禁假 task env） |
| Seatbelt / `doctor` / 停机 bind | 身份隔离与库存 | 不管谁醒 |
| 运维：缩 Online / 少 @ / `!rotate` | 人工减烧；`!rotate` 是上游已有换窗 | 不是运行时门控 |

### 降级 / 不要再投资

| 项 | 处理 |
|---|---|
| #15 Online 真路径「谁醒」E2E | **downgrade / 冗余**：无 @ 三问成立；不改 buzz-team 路径 |
| `enforceChannelWake` + `applyWakePayload` 收 env | **可选残余**：保留接收端，给将来真走 launch 且注入了 wake 的路径；#23 park，不为此改上游 |
| 每帖改经 `agent-executor` | **no-go** |
| ACP stdio 代理 | **no-go** |
| 静态假 `BUZZ_WAKE_*` / `BUZZ_TASK_*` | 禁止 |

### 仍可能缺（与「谁醒」分开，且不是本票必修）

#15 S1（未 @ tool_call=0）由原生过滤覆盖，不必 buzz-team 再验 Desktop Activity。

仍缺、且 **不是** executor 改线能单独补上的（可选后续，不阻塞关 #24）：

1. 被 @ 后 sticky 续烧的换窗（#15 S2）在 Online 上未接线。
2. 无 task 的普通 ACP 没有 ledger 硬闸（禁假 `BUZZ_TASK_*`）。
3. 正文 alias 与 Nostr `p` 标签若不一致（只打字 `@沈予`），两边语义不同——先观察，不要为对齐去改上游。

---

## 6. 明确不建议的后继

- 不要开「每帖改经 executor」或「ACP 代理」实现票。
- 不要为过门控写假 env。
- 不要申请改 `block/buzz`。
- 关 #24 为 **downgrade**；#15 真路径「谁醒」标 **冗余（原生 mentions + `#p`）**。
- launch/env 门控当作可选残余留下，不另开 Online E2E 实现票。
