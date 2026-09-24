# S1…S3 验收表（pre-merge / post-merge）

| ID | 验收 | Pre-merge（本 PR / Quill） | Post-merge live（Hogan） |
|---|---|---|---|
| S1 | 受控触发开窗 workflow，≤120s 出现周衡开窗帖；文案无五人齐点 | after/workflow.yaml 已去「点名五角色」；与 light-keel 对齐；保留 `@周衡`+owner+cron。**未** live update | `buzz workflows update` 后 trigger 一次；频道见开窗帖；doctor 无关 |
| S2 | doctor ok；运行时 effort=medium；idle 值与理由明确 | after managed 行 idle=180、effort=medium；IDLE-DECISION.md。**未**写 managed-agents.json | apply.sh 只重启周衡；doctor+bind 前后对比仅周衡 pid 变；进程 env 见 medium/180 |
| S3 | DM「完成了吗」三栏；prompt 无重复长任务节、无 `find ~` | system_prompt 去重+三栏+禁 find；pj.md/AGENTS/instructions-1 after 快照在 PR | apply 后受控 DM；回复含 已完成/未完成/不在本范围 |

Closes 语义：PR 合入关闭配置/文案交付；**live 行为验收**在 Hogan apply 之后勾 Issue checklist。
