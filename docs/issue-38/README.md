# Issue #38 artifacts（周衡指令遵循）

> 历史记录：#53 已退役本文涉及的本地 ACP 代理、任务/会话状态或 Desktop 私有绑定入口。文中的旧模块、CLI 和操作步骤不再是现行契约；当前运行与回退见 [运行手册](../runbook.md)及 [#53 设计](../design/53-remove-acp-middle-layer.md)。

本目录冻结 S1/S2/S3 的 before/after、diff、live apply/rollback 脚本与 runbook，供 Knox 在**单一 tip SHA**上审查，无需读 live。

| 文件 | 作用 |
|---|---|
| `HOW.md` | 事实源与机制（keel-how） |
| `IDLE-DECISION.md` | 现行决策：不采用 1500→180；周衡 idle 保持 1500 |
| `S1-S3-ACCEPTANCE.md` | pre-merge / post-merge 分工 |
| `RUNBOOK.md` | 合入后与 Hogan：quit-first baseline→Cmd+Q→apply→reopen(proxy gate)→verify --restart-mode app |
| `scripts/apply.sh` / `rollback.sh` | 默认拒绝执行（需 `ISSUE38_I_UNDERSTAND_LIVE=yes`） |
| `before/` `after/` `diffs/` | 实例侧变更冻结快照 |

**不要在合入前 apply。** thin-bin pin `046ac43` 禁止改动。并行 Scout 实例车道：无冲突未提交周衡改动（本 PR 未写 live）。

## Script smoke (read-only)

```bash
docs/issue-38/scripts/smoke-test.sh
docs/issue-38/scripts/verify-after-restart.sh  # post-Desktop-restart checks (--expect after|before)   # bash -n + guard refuse + pin/pid resolve; never mutates live
docs/issue-38/scripts/smoke-real-workflow.sh  # live relay: temp workflow create/update($(cat))/delete; list before==after
# artifacts: docs/issue-38/smoke/
```
