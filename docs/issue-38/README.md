# Issue #38 artifacts（周衡指令遵循）

本目录冻结 S1/S2/S3 的 before/after、diff、live apply/rollback 脚本与 runbook，供 Knox 在**单一 tip SHA**上审查，无需读 live。

| 文件 | 作用 |
|---|---|
| `HOW.md` | 事实源与机制（keel-how） |
| `IDLE-DECISION.md` | idle 1500→180 理由（对照 #29/#32） |
| `S1-S3-ACCEPTANCE.md` | pre-merge / post-merge 分工 |
| `RUNBOOK.md` | 合入后与 Hogan：doctor+bind+只重启周衡 |
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
