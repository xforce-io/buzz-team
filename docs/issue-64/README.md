# #64 席位长任务时限：配置层探明笔记与契约

依据：

- Issue #64 正文（Hogan 00:40 根因；三道时限；#57 RUN3）
- Quill L1：<https://github.com/xforce-io/buzz-team/issues/64#issuecomment-6073472569>
- Knox PASS（`human:required`）：<https://github.com/xforce-io/buzz-team/issues/64#issuecomment-6073498234>
- 设计门：peng 经 Jenny 2026-10-09 批准「配置层探明 + 契约；键存在则以后再批 per-seat 抬参；本仓不实现选项 (2)；不默认选项 (3)」

本 PR **只写文档**。不改 `src/`、不改上游 `block/buzz` / buzz-acp、不改活机 Desktop / `managed-agents.json` / 策略 / pin、不抬任何时限。peng 尚未给出抬参数值。合入须 peng 人工完成；不自批、不自合。

| 文件 | 作用 |
|---|---|
| `README.md` | 探明笔记：三道时限、活动定义未知、孤儿、配置面 0 命中、Mac 只读附录模板、S 表 |
| `CONTRACT.md` | 现行栈下席位任务必须遵守的契约 |
| `PR.md` | PR 正文草稿（含 S1…S7） |

功能地图：skip。本票无用户 UI 路径。

---

## 1. 设计门（已批）

| 项 | 取值 |
|---|---|
| 主路径 | 配置层探明 + 契约文档 |
| 选项 (1) 抬参 | **条件后续**：仅当 Mac 只读证实键已暴露，且 peng 另批数值与活机窗 |
| 选项 (2) 活动感知 teardown | **本仓不实现**（须改上游 buzz-acp；活动定义仍为未知） |
| 选项 (3) 任务脱离 agent | **不默认采用**；除非 peng 另开设计并接受无人管理生命周期 |
| 本 PR 抬参 | **不做**。数值未定 |

孤儿根治不是本仓目标。抬超时只能降低触发概率；残留风险与观测方法见 §4 与 `CONTRACT.md`。

---

## 2. 现象与时间线（#57 RUN3 → 本票）

周衡后台跑三条 ref。RUN1 / RUN2 完成并写 notes。RUN3（`20260930 093139.m4a`，能源梳理，标题「刚总沟通」）写出 transcript / digest / manifest，**没有** `notes.jsonl`、**没有** EXIT3。RUN3 **不计入** #57 通过证据，转本票独立跟踪。

时间线（北京时间，#57 续跑夜；Hogan 只读：mtime、memtrace 心跳、周衡 buzz-acp 日志）：

| 时间 | 事件 |
|---|---|
| 23:52:58 | 拉起 grok ACP **50111、50113** |
| 23:54:31 | 周衡以后台任务启动三条 ref 脚本 |
| 23:58:40 | 按 900s 倒推的 idle 计时起点（00:13:40 − 900） |
| 00:00:14 | 周衡本轮结束 |
| 00:09:17 | grok **56637** 启动（应为 note 调用） |
| 00:13:24 / 00:13:28 | 50111 / 50113 最后心跳 |
| 00:13:40 | buzz-acp：`idle pool sleep bound reached — tearing pool back to lazy state idle_pool_sleep_seconds=900`（**整池** teardown） |
| 00:13:24–00:13:58 | 50111、50113 退出；脚本 shell 同退出 → 无 EXIT3；kairo 随 shell 退出 |
| 00:15:17–00:15:47 | 56637 最后心跳后消失（相对主链多活约 2 分钟）→ **孤儿**，无人接收结果写 note |

证据目录：`$D=~/lab/buzz/evidence/issue57-live-20260930-151341`（`$D/13-*`、`$D/12-*`、50111 / 50113 / 56637 三份 memtrace）。#57 结案评论 5915806699。

先前「两 agent 分别计 idle」已排除：整池一条 teardown。周衡日志自 9/24 起该类 teardown 45 次，9 席均有。

---

## 3. 周衡观测到的三道时限

权威实现与默认值在 **上游 buzz-acp / Desktop**，不在 buzz-team 源码。下表是 Issue #64 / L1 在周衡上的观测值，不是本仓 API。

| 观测名 | 周衡观测值 | 范围 | 效果 |
|---|---|---|---|
| `idle_pool_sleep_seconds` | **900s** | 整个 pool | 整池 teardown，杀 agent 树（本次 00:13:40） |
| `idle_timeout` | **1500s** | 单个工具调用 | 约 25 分钟无输出则回收 agent（9/24：1222s `long_tool_alert` → 1500s `idle_timeout`） |
| `max_turn` | **1800s** | 单轮 | 硬上限：杀并重启 agent，消息重新入队（9/25 15:25 启动行 `max_turn=1800s`；9/30 08:18 `hard-cap timeout … requeueing for retry`）→ **可能静默重跑** |

结论：中途有长时间静默、总长十几分钟以上的任务，**前台 / 后台都不安全**。须同时覆盖中断 / 静默重跑与孤儿后代。

与 `#38` 快照的差异（不在本 PR 调和）：

- [`docs/issue-38/IDLE-DECISION.md`](../issue-38/IDLE-DECISION.md) 冻结的是席位 `BUZZ_ACP_IDLE_TIMEOUT=1500`（不改为 180），并记下 `max_turn_duration_seconds` / `BUZZ_ACP_MAX_TURN_DURATION=7200`。那是 #38 决策，**不是** buzz-team 实现面。
- `idle_pool_sleep_seconds=900` 与 #38 的 idle 1500 **不是同一参数**。peng 保留 1500，它不管本次 pool teardown，但长任务仍受 1500 约束。
- #64 正文记周衡启动行 `max_turn=1800s`；#38 库存快照写的是 `max_turn_duration_seconds=7200`。二者未在 Mac 上对过，**不得臆造映射或「现值」**。契约按 #64 观测包络（900 / 1500 / 1800）约束席位任务。

[`docs/design/29-long-tool-turn-gate.md`](../design/29-long-tool-turn-gate.md) 是 #53 后已退役的历史本地 ACP 中继，**不是**现行契约。

---

## 4. 活动定义：未知（Knox P3-1）

**文档级记录为未知。** 现有 INFO 日志不能定义「什么算活动」。本仓不负责查清；根治活动语义属上游。

已确认、且不得写成已解释的事实：

1. **idle 计时可以在本轮结束前开始。** 倒推起点 23:58:40 早于本轮结束 00:00:14。
2. **后台任务可以不重置 idle。** RUN3 当时仍在跑。
3. buzz-acp INFO 只记生命周期：`agent_pool_ready` 到 teardown 之间无活动行。因此**不能排除**「本轮中约 15 分钟无输出即整池 teardown」。
4. teardown 杀 agent 进程树**不完整** → 任务中断 **且** 可能留孤儿。

不得把 Desktop Activity 面板、memtrace 心跳或「有子进程」臆造成 buzz-acp 的活动定义。

---

## 5. 孤儿残留（56637）与观测

实例：grok **56637**（#57 RUN3 note 调用）在整池 teardown 后仍活约 2 分钟，然后消失；当时已无进程接收结果写 note。

本仓无法改上游杀树。后续若抬参，也只能降低触发概率，**不能根治孤儿**。根治属上游议题，或 peng 另批选项 (3) 重设计。

观测（只读；不作为「无孤儿」的反证缺口去编造）：

- 周衡 buzz-acp 日志里的 teardown / `hard-cap timeout` / `requeueing for retry` / `idle_timeout` 行
- 相关 grok 的 memtrace 心跳起止
- teardown 后 `pgrep` 对照（活机窗才做；本 PR 不做）
- 产物 mtime（transcript / digest / manifest / `notes.jsonl` 有无）

---

## 6. 配置面（本仓 0 命中）

`src/buzz_team/` 只有 `thin.py` / `doctor.py` / `cli.py`，**没有** idle / pool / turn 调参 API。权威在上游 buzz-acp / Desktop。符合 `AGENTS.md`：开源组件不 fork；本地只允许在配置层规避。

本盒在 `main` `603b0aa` 复核（实现本文件之前）：

| 检索 | 范围 | 结果 |
|---|---|---|
| `idle_pool_sleep` / `idle_pool_sleep_seconds` | 全仓 | **0 命中** |
| `idle_timeout` / `max_turn` / `idle_pool_sleep` / `idle_pool_sleep_seconds` | `src/buzz_team/` | **0 命中** |
| `idle_timeout` / `max_turn` | 全仓（本 PR 之前） | 仅 `docs/issue-38/` 历史库存快照与脚本（`idle_timeout_seconds`、`max_turn_duration_seconds`、`peer-idle-effort.json` 的 `max_turn`）。**不是**本仓实现面，也不是本次 Mac 核实 |

L1 / Knox 把这四个词记为「code search 0 命中」，含义与上表一致：旋钮不在 buzz-team 源码面。不得把 #38 快照里的 Desktop 字段名当成已核实的活机键。

**S3 本 PR：`blocked-on-Mac-readonly`。** 实际 Desktop / env / `*.acp.toml` 键名未知。附录 A 留给 Quill / Hogan 在 Mac 上只读填写。不可配则改为 `blocked-on-upstream`，不得假装本仓可修。

历史候选名（#38 快照，**未**在本票核实）：

- `idle_timeout_seconds` / `BUZZ_ACP_IDLE_TIMEOUT`
- `max_turn_duration_seconds` / `BUZZ_ACP_MAX_TURN_DURATION`
- `idle_pool_sleep_seconds`：本仓无候选键

---

## 7. Knox P3 在文档中的落点

| P3 | 文档处理 |
|---|---|
| 活动定义 | §4 写 **未知**；不要求本仓查清 |
| `max_turn` 验收口径 | **开放门**：peng 必须在「观测窗口内零重跑」与「重跑必须可观测（日志告警）」中择一。本 PR 不发明选择。有限硬顶仍在时，禁止只写「无静默重跑」 |
| 抬 `idle_timeout` | 必须先由 peng **修订** [`docs/issue-38/IDLE-DECISION.md`](../issue-38/IDLE-DECISION.md)。本 PR **不改** 该文件，也 **不改** 1500 |

---

## 8. 验收证据（禁止 #63 路径）

#63：seatbelt 写拒绝不进 macOS 统一日志。本票验收 **不得** 使用「Sandbox 日志 / 统一日志里查不到 deny」。

本票证据只认：

- 周衡（或目标席）buzz-acp 日志
- grok memtrace
- 产物 mtime（以及有无 `notes.jsonl` / EXIT 行）

---

## 9. 明确不在范围

- 实现选项 (2)（活动感知 teardown / 推迟回收）
- 把 MacSec 行加入 `write_paths`（认证边界；#64 已排除为根因）
- 把 RUN3 重新计入 #57
- 改 `TMPDIR` / 临时目录策略
- 改上游 `block/buzz` / buzz-acp 源码
- 本 PR 改活机 Desktop / `managed-agents.json` / 策略 / pin / 代理
- 本 PR 抬高 900 / 1500 / 1800（peng 未给数值）
- 复活 #29 本地 turn gate
- 把 #63 统一日志问题绑进本 PR
- 自动化 RUN3 补跑

---

## 10. 仍开放、本 PR 不代填

1. **抬参数值**：三道各改到多少；是否只改周衡。peng 未定 → 本 PR 不写数。
2. **`max_turn` 验收口径**：零重跑 vs 可观测重跑。见 §7。
3. **Mac 键名与可否 per-seat**：附录 A 空白。S3 = `blocked-on-Mac-readonly`。
4. **孤儿关票条件**：接受「降概率 + 文档风险」，还是必须上游修复。本仓 L1 已标非目标。
5. **RUN3 是否由 peng 在 Buzz 外补跑**：不阻塞本 PR；办法见 `CONTRACT.md`，不自动化。

---

## 11. 本 PR 的 S1…S7（文档级；跳过活机抬参）

| ID | 内容 | 本 PR | 证据 |
|---|---|---|---|
| S1 | 根因与活动定义（文档级） | **pass** | §2–§5：idle 可在 turn 内启动；整池 teardown；56637；活动 = **未知** |
| S2 | 方案选定 | **pass** | §1：peng 经 Jenny 2026-10-09 批探明+契约；条件后续抬参；(2) 不实现；(3) 不默认 |
| S3 | 配置面证据 | **blocked-on-Mac-readonly** | §6：本仓源码面 0 命中；活机键未知；附录 A 待填 |
| S4 | 行为验收（抬参或修复后） | **skip** | 本 PR 不抬参、不修复、不活机 |
| S5 | 仅契约路径 | **pass** | `CONTRACT.md`：不得超过的时限；禁止席位内跑的任务类；RUN3 仅 peng、Buzz 外 |
| S6 | 回滚 | **skip** | 无活机时限改动。将来活机窗须有备份、一键回滚、改前改后启动摘要行对照 |
| S7 | 流程 | **pass** | Knox PASS `human:required`；peng 经 Jenny 批本路径；无活机窗；#57 已关，不冲突 |

将来若做 per-seat 抬参：另开 PR + 另批活机窗 + `human:required`；S4/S6 那时才适用；抬 `idle_timeout` 须先修订 IDLE-DECISION；`max_turn` 仍为有限值时须先关掉 §7 那扇门。

---

## 附录 A — Mac 只读探明模板（Quill / Hogan 稍后填）

**只读。** 不写 Desktop、`managed-agents.json`、`*.acp.toml`、策略、pin、代理。不重启席位。

目标：三道观测名各自对应的**实际键**、落点、可否 per-seat。键无法在配置层改 → 该行标 `blocked-on-upstream`。

| 观测名 | 实际键 / env / toml 路径 | 落点（Desktop Advanced / 库存 `env_vars` / `*.acp.toml` / 启动摘要行） | 周衡现值 | 可否 per-seat | 证据文件 |
|---|---|---|---|---|---|
| `idle_pool_sleep_seconds` | _TBD_ | _TBD_ | 日志观测 900；键未知 | _TBD_ | _TBD_ |
| `idle_timeout` | _TBD_ | _TBD_ | 日志观测 1500；键未知 | _TBD_ | _TBD_ |
| `max_turn` | _TBD_ | _TBD_ | 启动行观测 1800；#38 快照曾写 7200；键未知 | _TBD_ | _TBD_ |

建议只读入口（填结果，不 apply）：

1. Desktop Advanced / 席位启动摘要行（`idle_pool_sleep_seconds=` / `idle_timeout` / `max_turn=`）。
2. 库存只读副本：`~/Library/Application Support/xyz.block.buzz.app/agents/managed-agents.json` 周衡活跃行的字段与 `env_vars`（#38 历史候选：`idle_timeout_seconds`、`max_turn_duration_seconds`、`BUZZ_ACP_IDLE_TIMEOUT`、`BUZZ_ACP_MAX_TURN_DURATION`）。
3. 席位 `*.acp.toml`（#38 快照曾见 `BUZZ_ACP_CONFIG=…/pj.acp.toml`；以活机为准）。
4. 对应 buzz-acp 进程启动摘要行（只摘时限相关字段，不保存私钥或完整环境）。

填写后：三键都可配 → 去掉本 PR 的 `blocked-on-Mac-readonly`，仍须 peng 批数值才允许抬参。任一键不可配 → 该键 `blocked-on-upstream`。
