# #24 评估：不依赖 Desktop 注入的频道 wake / mention 控烧

状态：评估完成（2026-09-22）。**结论：no-go**。不改 `block/buzz` / Desktop；禁静态假 `BUZZ_WAKE_*`。#23 保持 park。

本文件是 Scout · Product 书面结论，供 parent 粘贴到 [Issue #24](https://github.com/xforce-io/buzz-team/issues/24)。上游 `block/buzz` 仅作只读对照，未改、未申请 write access。

---

## Overview

#15/#16 接收端已在 buzz-team 落地：`decideWake` / `enforceChannelWake` / `applyWakePayload` / ledger 硬闸。它们的**唯一运行时钩子**是 `Runtime.launch` 读进程环境里的 `BUZZ_WAKE_*`。

活机 Online @（炼丹房 @沈予，2026-09-22）的真路径是：长跑 `buzz-acp` 同一 PID 收帖，再 `session/prompt` 给已存在的 `grok` 子进程。该路径**不** re-spawn Desktop ACP，**不**进 `agent-executor`，**不**带 `BUZZ_WAKE_*`。

提案：「每帖改经 `agent-executor`，并从 ACP 回合载荷（非 env）读频道/帖/正文，再跑现有 `decideWake` / `enforceChannelWake`」。

在「只改 xforce-io/buzz-team、零改上游、禁假 env」约束下，**(a) 与 (b) 均不可行**。现有 bind/wrapper 是一次性 `execve`，不是每帖拦截器；Desktop↔buzz-acp 也不是 ACP stdio（stdin 为 null）；`session/prompt` 只有 `sessionId` + 文本块，没有 channel / post_ref。

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

在 buzz-team 新写一个长跑 ACP stdio 代理，**不是**「Desktop 已认的 wrapper」。那是新产品（完整 JSON-RPC、permission、steer、liveness），等于再做一套 buzz-acp，且违背「不启第二套后台团队」。

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

## 4. 结论：**no-go**

提案的两个合取条件在 buzz-team 内都做不到。#15 真路径 E2E 继续暂缺，有据。#23 保持 park。不要开「实现 ACP 代理 + decideWake」实现票冒充本评估的 go。

### 风险（若无视结论硬做）

| 风险 | 后果 |
|---|---|
| 把 `execve` wrapper 改成长跑 ACP 代理 | 新产品；Desktop Activity / permission / steer 回归面大；等于 fork buzz-acp |
| 从 prompt 文本猜 @ | 误拦或误放；违反 #15 fail-closed |
| 发明 channel/post id | 熔断回帖打到错误线程；明确禁止 |
| 静态 `BUZZ_WAKE_*` | 全员假唤醒或冷启全拒；peng 已禁 |
| 再改 `block/buzz` | 组织边界，#23 已 park |

---

## 5. S3：buzz-team 里还能用的控烧 vs 缺口

### 仍可用（不经过 Online @ 真路径）

| 工具 | 能做什么 | 上不了真路径的原因 |
|---|---|---|
| `wake decide` / `decideWake` | 已知四件套时离线判定 | Online @ 不调用 |
| `enforceChannelWake` | `surface=stream` 或 fuse 时拒 launch | 每帖不进 `launch` |
| `applyWakePayload` | 展开 Desktop JSON env | 无人写 env |
| `ChannelCursorStore` / `applyFuse` / 【熔断】回帖 | 换窗 + 回帖 | 需要 fuse **且** 已有 channel/post/session |
| `ContextLedger` / `fuseReason` / `setWakeFuse` | task-scoped 硬闸 | 普通 ACP 无 `BUZZ_TASK_ID`（禁假 task env） |
| `binding_environment` 白名单 | 可带静态 `BUZZ_TASK_*` / `BUZZ_WAKE_*` | 静态 wake 禁止；且改不了 reserved `BUZZ_ACP_AGENT_COMMAND` |
| `agent-harness` / `agent-executor` | 冷启/显式 spawn 时进 launch | Online @ 不 spawn |
| buzz-acp 自带 `require_mention` / `subscribe=mentions` | Nostr `#p` / `buzz:workflow-mention` | **另一套** mention；不是 #15 别名 `@token`。炼丹房未 @ 仍长跑，说明它挡不住本票场景 |
| Seatbelt / `doctor` / 停机 bind | 身份隔离与库存 | 不管每帖唤醒 |
| 运维（#15 评论） | 缩 Online / 只 @ 一人 / 杀超大 session | 人工，不是运行时门控 |

### 缺口（#15 真路径 E2E 仍缺）

1. 没有任何 buzz-team 进程坐在「每帖 → 执行向 tool_call」之前。
2. 没有结构化的当帖 `channel` / `post_ref` / `body` 进入 buzz-team。
3. 不能在不改上游的前提下，给每帖注入真实 `BUZZ_WAKE_*`。
4. 未 @ 身份执行向 tool_call = 0：**未验、现网不成立**。
5. 熔断后下一 turn 换 `session_id`：Online @ 上 **未接线**（sticky 仍在 buzz-acp/grok）。

---

## 6. 明确不建议的后继

- 不要开「buzz-team ACP 代理实现票」当作本评估的 go。那是新项目，不是复用 `decideWake`。
- 不要为了过门控写假 `BUZZ_WAKE_*` / `BUZZ_TASK_*`。
- 不要申请改 `block/buzz`；#23 已记录组织边界。

若产品目标仍是真频道控烧，选项只剩：**接受缺口（运维减烧）**，或 **将来组织批准改上游时重启 #23**（P0：buzz-acp 每帖注入 wake 并 spawn executor）。那是另一张票，不是本评估的实现草稿。
