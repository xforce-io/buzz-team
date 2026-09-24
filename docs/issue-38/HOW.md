# Issue #38 — keel-how：将改子系统怎么工作（出处）

`skip L1`：peng 已批准 S1/S2/S3；无契约/跨模块/权限变更；纯实例配置 + 文案。

## Overview

周衡「指令遵循差」主要来自三处冲突，而非模型能力：

1. **站会开窗 workflow** 文案要求「点名五角色」，与 light-keel / 席位提示「禁止默认五人齐点」冲突 → 触发后只 👀。
2. **席位 effort=low + idle=1500s** 相对工程/运维/测试席（medium / 180s）过偏；`find ~` 挂 ~1222s 后撞 idle 撕池。
3. **prompt 栈** managed `system_prompt` 内「长任务执行与恢复」整节重复两次；AGENTS「短答不要开工具」与被 @ 交付冲突；缺状态三栏契约。

## 东西在哪（S1/S2/S3 事实源）

| Story | 事实源 | 路径 | 仓库跟踪？ |
|---|---|---|---|
| **S1** workflow 文案 | Relay DB / `buzz workflows` | id `f5cc62c0-3756-419e-8a3f-8e694df2e93e`；channel `9bdc9fa2-48b7-4352-8b1f-7baf70ba6bd3`（炼丹房）；owner pubkey `51fb6cd8…7d9e`（周衡）；cron `0 1 * * 1-5` | **live-only**（证据见 `evidence/issue-34-standup-owner-zhouheng/`） |
| **S2** effort / idle | Desktop managed-agents | `~/Library/Application Support/xyz.block.buzz.app/agents/managed-agents.json` 中 **活跃** 周衡行（`idle_timeout_seconds=1500` 且 `env_vars.BUZZ_ACP_EFFORT_LEVEL=low`）；pid 旁路 `…/agents/agent-pids/51fb6cd8…json` | **live-only** |
| **S3** prompt 栈 | 三层 | ① managed `system_prompt`（同上 JSON）；② lab 模板 `/Users/xupeng/lab/buzz-team/team/prompts/pj.md`（非 git）；③ 周衡身份 workspace `…/identities/a558771623f29898/51fb6cd8…/workspace/AGENTS.md`；另 `instance.local.json` → `private/instructions-1.md` | lab/身份为 **live-only**；本 PR 把 after 快照 + 模板纳入 `docs/issue-38/` 与 `team/prompts/pj.md` |

**不改**：thin-bin pin `046ac43`；其他 8 席 managed 行/prompt；upstream block/buzz；`incomplete_follow` 观测。

## 怎么跑

- Workflow：scheduler 按 cron 发 `send_message`；`require_mention` 靠正文 `@周衡`；owner 不可用 `workflows update` 改（Scout：只改 body）。
- Seat：Desktop 拉起 `agent-harness`→`agent-executor`（pin 046ac43）；`BUZZ_ACP_EFFORT_LEVEL` + `agent_args --reasoning-effort` 共同决定 effort；`idle_timeout_seconds` 与 `BUZZ_ACP_IDLE_TIMEOUT` 决定空闲撕池。
- Prompt：Desktop 注入 managed `system_prompt`；workspace `AGENTS.md` 由 grok cwd 加载；`instructions-1.md` 经 instance 绑定。

## Gotchas

- managed-agents.json 里有多条「周衡」历史行；只改 **idle=1500 + effort=low** 的活跃行。
- `…/agent-runtime/ws/AGENTS.md` 为多席共享 → **禁止**改共享副本；只改周衡 identity workspace。
- #29/#32 长工具保活在 harness `turn_gate`，**不**依赖座位 idle=1500。
- 合入后 live apply 须与 Hogan 一起做；本 PR 只冻结脚本与 before/after，**不**碰 live。
