# #15 Desktop 频道 mention-gate 与超限 session rotate

状态：Draft（待人工批准）。未 Approved，禁止按本文实现产品代码。

## 1 背景

2026-09-21 本机 Desktop/ACP 频道 sticky session 对每条帖子反复唤醒全员，未 @ 也进入执行向长循环，单日约 100.5M tokens / ~$306。秘书处「点名收集」只是发帖正文规则（`team/secretariat-briefing.md`），不是运行时门控。炼丹房未采用同等门控。

现有机制（已核树）：

- `src/buzz_team/desktop.py`：Desktop 拥有进程生命周期；`bind` 只改写 `acp_command` / `agent_command` 与 `BUZZ_RUNTIME_ID` / `BUZZ_TEAM_INSTANCE`，不注入 mention 判定或 session 换窗。
- `src/buzz_team/sessions.py`：只存任务→会话映射元数据，无唤醒门控。
- `src/buzz_team/context.py`：账本状态为 `collecting` / `budget_warning` / `budget_exceeded`；#7 批准文规定超限只诊断，不自动截断。
- `src/buzz_team/runtime.py` `launch`：有 `task_id` 才 claim/restore；无 task 路径可 sticky 续跑完整历史。
- 配套 [#16](https://github.com/xforce-io/buzz-team/issues/16)（Quill · Runtime）负责 Desktop ACP 挂上 #6 映射与 #7 ledger **硬停**。本票不抢该实现。

## 2 名词解释

沿用 [名词表](../glossary.md) 的运行身份、会话范围、任务会话映射、成本账本、上下文交接。本票新增：

- **点名门控（mention-gate）**：频道帖到达后、执行器进入执行向工具循环前的唤醒判定；未命中则不得长跑。
- **执行向长跑**：会启动或续跑 coding-agent 工具循环、改工作区、发副作用消息或多轮 tool_call 的路径。
- **短读 / 静默**：不进入执行向工具循环；默认不回帖，策略显式允许时最多一次短确认。
- **频道会话游标**：某身份在某频道范围上当前可续跑的 ACP `session_id`。它不是 task_id，也不是 #6 映射本身。
- **熔断信号**：#16 在 Desktop 路径上因上限硬停后发出的可观察事件（账本 `budget_exceeded` 或等价 fuse 记录）。
- **换窗（rotate）**：熔断后退役旧游标，后续执行绑定新 `session_id`，禁止在旧 sticky 上续烧完整历史。
- **单 owner**：实例私有策略为某频道配置的唯一默认可执行身份；仅当帖内**没有任何**可解析 agent 点名时生效。

## 3 目标与非目标

目标：在 Desktop/ACP **频道**路径上，未点名身份不得启动执行向长跑（同帖执行向 tool_call = 0）；被 @ 的身份或已配置单 owner 可以执行；频道绑定 session 触及配置上限后必须熔断回帖并换到新 session；门控与换窗的产品契约可被正负向验证。

非目标：不重写 CLI `--task`；不做完整任务编排 UI；不改真实业务 memory；不替代 #6/#7 已合能力；不实现 #16 的映射注入、ledger 写入、工具硬停与 handoff 消费；不把秘书处简报正文规则当成运行时实现；不把密钥、prompt 或别名表写进 git。

## 4 能力

### 4.1 UI/UX

无新增 GUI。频道可见变化仅限：

- 未点名身份：静默或（若策略允许）一条短确认；Activity 不出现该身份的执行向工具循环。
- 被点名 / 单 owner：沿用现有 Desktop 执行与回帖位置。
- 熔断：该身份在触发帖线程回一条熔断声明；不含 prompt、工具正文、认证或完整环境。

CLI 只提供只读判定与游标/熔断状态检查，便于验收。不提供「强行唤醒未点名身份」的覆盖命令。

## 5 思路与折衷

把「谁被允许醒」和「醒了之后如何计量/硬停」分成两层。本票只做前者，以及硬停**之后**的换窗与回帖。计量、硬停、handoff 归 #16，避免双头熔断。

点名判定 fail-closed：优先用 Buzz/ACP 结构化 mention；没有可靠结构时，只用实例私有别名表做精确 `@token` 匹配。禁止模糊匹配显示名、禁止用最近发言者或频道标题猜测。结构化结果与文本解析冲突、别名一对多、载荷缺失或频道类型不明时，一律不准进入执行向长跑。

放弃「频道在线即全员可跑」，因为这就是 2026-09-21 雪崩路径。放弃「用秘书处 markdown 约定代替门控」，因为它不是运行时。放弃「每条消息新建 session」，以免被点名后的连续推理丢失；只在熔断后换窗。

换窗不静默改写 #6 的不可变 bind。旧映射保留供诊断；新 `session_id` 必须显式 rotate 或新 bind。无 task 的 sticky 游标同样退役，禁止 `launch` 无 task 路径续跑已熔断 session。

## 6 架构

分层：频道事件进入 Desktop ACP 薄入口之后、执行向 tool_call 之前，先过本票门控；通过后才进入 #16 的映射/账本/硬停路径。熔断信号只由 #16 写出；本票消费该信号做回帖与换窗。

主路径：频道帖 → 判定表面为 stream → 解析 mention → 本身份命中或单 owner → 允许执行 →（#16）映射与 ledger → 正常回帖。

未点名路径：解析为未命中 → 不启动执行器或立即退出且执行向 tool_call = 0 → 默认静默。

熔断路径：#16 硬停并写 fuse → 本票发熔断回帖 → 原子退役旧游标并准备新 `session_id` → 下一次被允许的唤醒使用新 session，可消费 #16 handoff（消费实现归 #16）。

失败路径：mention 载荷不明、别名冲突、策略缺失但表面是频道、游标与 #6 映射指向已熔断 session → fail-closed，不发执行请求，不续跑旧 sticky。

```text
频道帖
  → #15 mention-gate（谁可醒）
      拒绝：静默 / 短读；tool_call(exec)=0
      允许：#16 映射 + ledger + 硬停
              未超限：执行
              已熔断：#15 回帖 + rotate 新 session_id
```

## 7 模块

- **点名门控**：输入为身份、频道范围、帖引用、mention 载荷与实例私有策略；输出为 `allow` / `deny` 及原因码。不读认证，不启动执行器。
- **别名与策略**：从 `instance.local.json` 的实例私有节读取；仓库不携带真实 handle。
- **频道会话游标**：实例 `private/` 下记录 `(community, identity, scope) → {session_id, generation, state}`。状态至少含 `active` / `fused` / `retired`。写入用锁、临时文件、fsync、原子替换，权限 0600/0700。
- **熔断回帖**：消费 #16 fuse，经现有 `buzz` 消息入口回帖；不把已熔断 session 再交给执行器去「自己宣布熔断」。
- **换窗**：退役旧游标，登记新 `session_id`；若存在 #6 映射，调用约定的 rotate/rebind，禁止直接改 JSON。

`desktop.py` 仍只做生命周期与 bind；`sessions.py` 仍只做任务映射存储。本票不把门控逻辑塞进这两个模块的现有职责里。

## 8 API/CLI 与配置契约

### 8.1 点名检测

判定对象是**这一条频道帖**（含线程回复，各自独立判定，不继承父帖 @）。DM 不走本门控，沿用既有投递语义。

命中规则，按顺序，任一失败则本身份 `deny`：

1. 频道类型必须可判定为 stream。`buzz_cli.py` 已对未知 `channel_type` fail-closed；门控同样不得猜测。
2. 提取 mention 集合：
   - 若事件含结构化 mention（稳定用户/agent id 或公钥）：只使用该集合。
   - 否则扫描正文，只认 `@` + 已登记别名的完整 token（前后为空白、行首或标点）。大小写按策略声明，默认区分。
   - 结构与文本同时存在且集合不一致：`deny`（ambiguous）。
3. 将 mention 解析到已注册运行身份。一个别名对应多个身份、或同一 token 无法唯一解析：相关身份全部 `deny`。
4. `@freeman` / `@human` 等人类点名**不是** agent 命中；它们不能让全体身份开跑。
5. 本身份公钥或已登记别名出现在可解析 agent mention 中 → `allow`。
6. agent mention 集合为空，且该频道配置了恰好一个 `single_owner_identity` 且等于本身份 → `allow`。
7. 其它 → `deny`。

缺策略、缺别名表、缺结构化字段且无法做唯一别名匹配：视为未点名，`deny`。不存在「默认全员可跑」。

### 8.2 执行向长跑 vs 短读

| 类别 | 允许（非目标身份） | 禁止（非目标身份） |
|---|---|---|
| 启动/续跑执行器 | 否 | `launch` harness/executor、resume 旧 session |
| tool_call | 执行向次数必须为 0 | shell / 写文件 / 网络副作用 / 浏览器 / 多轮工具 / 发业务消息 |
| 读本帖 | 可选：只读本帖与线程元数据以完成判定 | 借「看一眼」扫工作区或历史 session |
| 回帖 | 默认静默；仅当 `allow_short_ack=true` 时一条固定短确认 | 借短确认展开任务 |

被点名或单 owner 进入执行后，仍受 #16 硬停与本票换窗约束。未知工具名视为执行向。

### 8.3 配置面（实例私有，不入库）

真实值只存在于实例 `instance.local.json`（及可选 `private/` 引用）。仓库只规定字段，不写真实频道 UUID、handle 或身份。建议挂在既有 `policies.<name>`，频道覆盖用独立私有节：

```json
{
  "channel_wake": {
    "default": {
      "require_mention": true,
      "single_owner_identity": null,
      "allow_short_ack": false,
      "rotate": {
        "max_turns": 20,
        "max_usd": 10,
        "max_input_tokens": 200000
      }
    },
    "channels": {
      "<channel-id>": {
        "require_mention": true,
        "single_owner_identity": "<identity-key-or-null>"
      }
    }
  }
}
```

身份别名挂在对应 agent 上，例如 `agents.<id>.mention_aliases: ["example-handle"]`。别名不是秘密，但也不得把生产表提交进 git。

上限 `max_turns` / `max_usd` / `max_input_tokens` 是产品闸。#16 必须把同一组闸纳入 Desktop 硬停（映射到 ledger budget 或新增 fuse 事件）。本票**不**实现第二套计量器，只认 #16 写出的熔断信号。若当前 ledger 尚无金额或轮次字段，由 #16 L2 补事件，不在本票另建账本。

`require_mention` 缺省为 true。`single_owner_identity` 缺省为 null。禁止用代码写死「炼丹房 owner」或秘书处人名。

### 8.4 换窗与熔断回帖

当且仅当收到 #16 熔断信号：

1. 停止把旧 `session_id` 交给下一次执行（#16 已保证同 session 新增执行向 tool_call = 0）。
2. 在触发帖线程回帖，字段仅限：固定标题「【熔断】」、原因枚举 `turns` | `usd` | `input_tokens` | `budget_exceeded`、旧 `session_ref`（12 位哈希，与现有 CLI 脱敏一致）、可选新 `session_ref`。禁止 prompt、工具正文、认证、完整环境、原始 token 转储。
3. 原子把频道游标标为 `fused`/`retired`，登记新 `session_id`（熔断时分配或下次允许唤醒时分配均可，但**第一次后续执行**必须使用新 id）。
4. 若该范围已有 #6 映射：不得 `bind` 覆盖旧 `session_id`；必须走显式 rotate/rebind（#16 与 session 存储共同提供）。旧记录保留。
5. 定量：熔断后下一执行 turn 的 `session_id` ≠ 熔断前 `session_id`。

回帖由 ACP 外环发出，不经过已熔断 session 的执行器工具循环。

### 8.5 只读 CLI（验收用）

- `wake decide --identity ID --channel CHANNEL --post-ref REF [--mentions JSON]`
  返回 `{allowed, reason}`；不发送消息、不启动执行器。
- `wake cursor --identity ID --scope SCOPE`
  返回脱敏 `session_ref` 与 `active|fused|retired`。

输出不含认证、prompt、会话正文。配置错误或判定不明时 exit 2。

### 8.6 与 #16 的接口（禁止双所有权）

| 职责 | #15（本票） | #16（Quill） |
|---|---|---|
| 谁可在频道帖上进入执行向长跑 | 是 | 否 |
| 注入/校验 #6 task→session 映射 | 否 | 是 |
| 写读 #7 ledger、硬停工具循环 | 否 | 是 |
| 产出可消费 handoff | 否 | 是 |
| 新 session 消费 handoff | 否（只要求换到新 session） | 是 |
| 熔断频道回帖文案与发送 | 是 | 否 |
| 退役旧 sticky / 绑定新 session_id | 是（产品契约） | 提供映射 rotate 与 fuse 信号 |
| CLI `--task` 路径 | 不改 | 契约对齐，不改叙事 |

合成顺序：门控通过 → #16 映射与账本 → 超限由 #16 硬停并写 fuse → #15 回帖并换窗 → 下次允许的唤醒带新 `session_id` → #16 消费 handoff 或安全拒绝。任一步缺字段 fail-closed，不猜测。

## 9 边界

- 只覆盖 Desktop/ACP 频道路径。CLI `--task`、DM、秘书处检查器原文不在本票改写。
- 门控在执行向 tool_call 之前；通过门控不等于无限预算。
- session_id 不能单独证明归属；换窗后仍要满足 #6 的 community/identity/scope/task 校验（若该执行已有映射）。
- 公开输出只含脱敏 ref、原因枚举和状态。私有游标文件 0600。
- 一个身份在同一频道范围同一时刻最多一个 `active` 游标。
- agent 不得改写 `channel_wake` 或别名表。

## 10 迁移/兼容/回滚

旧实例无 `channel_wake`、无游标文件：频道路径视为 `require_mention=true` 且无单 owner，未点名一律 deny。不自动给现网频道写 owner。无 fuse 信号时不换窗、不发熔断帖。

新增节与游标文件均为实例私有状态。回滚删除本次未生效的游标/配置增量，或恢复绑定 receipt；不回滚认证、业务 memory、已发出的频道帖。回滚后若仍绑定含门控的二进制，缺配置继续 fail-closed，不会退回「全员 sticky」。

## 11 测试计划

功能文件与验收故事 1:1，实现阶段写入，本 Draft 只命名：

- E2E S1：`.agents/skills/verify-buzz-team/features/channel-mention-gate.md`
  多身份 Online 的真实 Desktop 频道：普通讨论帖（无本身份 @）不得出现该身份执行向 tool_call；明确 @ 某一身份时仅该身份（或已配置单 owner）进入执行；非目标静默或短读。定量：同帖未 @ 身份执行向 tool 调用次数 = 0。负向：别名冲突、结构/文本不一致、未知频道类型均不启动。
- E2E S2：`.agents/skills/verify-buzz-team/features/session-rotate.md`
  频道绑定 session 跑到配置上限（由 #16 硬停出 fuse）：频道回帖含【熔断】与原因枚举、无秘密；下一执行 turn 的 session id ≠ 熔断前 session id；旧 sticky 不再被无 task 路径续跑。
- Integration：`wake decide` 对结构化 mention、别名、单 owner、ambiguous 的矩阵；游标原子写入与损坏 fail-closed；fuse 后禁止旧 session_id。
- Unit：token 切分、人类 @ 不计 agent 命中、未知工具视为执行向、脱敏 `session_ref`。

质量门：按 `verify-buzz-team` 手册在仓库外非 editable 安装上跑；CLI 只读成功不能冒充 Desktop Activity。未实跑不得标 pass。证据在实例 `evidence/<sha>/`，不入库。

S2 端到端依赖 #16 能在 Desktop 路径发出熔断信号；门控 S1 可独立验收。

## 12 开放问题

留给 peng / 实现前确认：

1. Desktop/ACP 事件是否已提供结构化 mention（稳定 id/公钥）？若无，是否接受「仅私有别名表 + 精确 @token」直到上游字段核实？
2. 哪些频道配置 `single_owner_identity`？不得把秘书处点名惯例写成全实例默认。
3. 熔断后新 `session_id` 是立即分配并写入回帖，还是等到下一次被 @ 再分配？（定量只约束下一次执行。）
4. `max_usd` 在 #7 账本尚无金额字段：#16 是扩展 ledger，还是金额仅作 `estimated` 事件？`unavailable` 时是否 fail-closed 熔断？
5. 线程回复是否应提供「继承父帖点名」的显式策略？本文默认每帖独立、不继承；若产品要继承，必须另批，禁止默默继承。

## 13 关联

- [Issue #15](https://github.com/xforce-io/buzz-team/issues/15)（本票；Scout · Product）
- [Issue #16](https://github.com/xforce-io/buzz-team/issues/16)（Quill · Runtime：Desktop 挂 #6/#7 硬停与 ledger；不负责 mention 产品语义）
- [Issue #6](https://github.com/xforce-io/buzz-team/issues/6) / [L1](6-task-session-isolation.md)
- [Issue #7](https://github.com/xforce-io/buzz-team/issues/7) / [L1](7-context-cost-control.md)
- [秘书处简报契约](../../team/secretariat-briefing.md)（发帖规则，非本门控实现）
