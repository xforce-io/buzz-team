# 功能地图

| 验收 | 功能 | 入口 |
|---|---|---|
| S1 | [独立安装](install.md) | 安装与 --help / --version |
| S2 | [CLI 与适配器](cli.md) | doctor / status / prepare / start / stop |
| S3 | [迁移与恢复](migration.md) | init / bind / rollback |
| S4 | [客户端行为](desktop.md) | Buzz Desktop |
| S5 | [改进项追踪](improvements.md) | 项目文档与 GitHub Issues |
| #6 S1 | [任务会话](task-sessions.md) | session bind / resolve / list |
| #7 S1 | [上下文成本](context-cost.md) | context start / record / handoff / report |
| #11 S1–S5 | [健康检查语义](health.md) | doctor / diagnose |
| #15 S1 | [频道点名门控](channel-mention-gate.md) | wake decide / Desktop 频道唤醒 |
| #15 S2 | [超限 session 换窗](session-rotate.md) | wake cursor / fuse 回帖 |
| #16 S1–S3 | [Desktop ACP 任务账本](desktop-acp-task.md) | Desktop env / launch --task + context consume |
| #29 S1–S2 | [长工具 turn gate](long-tool-turn.md) | executor ACP stdio；`long_tool` 超时/轮询 |
| #33 S1 | [角色头衔绑定](title-bind.md) | wake resolve / decide（含 pubkey） |
| #33 S2 | [提及确认 👀](mention-ack.md) | wake ack → `reactions add` |
| #44 S1–S3 | [上游 pin](upstream-pin.md) | `docs/archive/44-local-fork/`；`docs/runbooks/44-upstream-pin.md` |
| #46 S1–S3 | [桌面库存检查](inventory-doctor.md) | `doctor` → `classify_desktop_inventory` |
