# docs(#64): 席位长任务时限探明笔记与契约

Refs #64。

- Quill L1：<https://github.com/xforce-io/buzz-team/issues/64#issuecomment-6073472569>
- Knox PASS（`human:required`）：<https://github.com/xforce-io/buzz-team/issues/64#issuecomment-6073498234>
- 设计门：peng 经 Jenny 2026-10-09 批准配置层探明 + 契约；键存在则以后再批 per-seat 抬参；本仓不实现选项 (2)；不默认选项 (3)

**只文档。** 不改 `src/`、上游 `block/buzz` / buzz-acp、活机 Desktop / `managed-agents.json` / 策略 / pin。本 PR 不抬 900 / 1500 / 1800（peng 未给数值）。不自合。

## 改动

- `docs/issue-64/README.md`：周衡三道时限（`idle_pool_sleep_seconds=900` 整池 teardown；`idle_timeout=1500`；`max_turn=1800` 静默重入队）；idle 可在 turn 结束前启动、后台可不重置 idle；孤儿 56637；活动定义 **未知**；本仓源码面 0 命中（权威在上游）；Mac 只读附录模板；S3 = `blocked-on-Mac-readonly`。
- `docs/issue-64/CONTRACT.md`：中途长静默的长任务在现行栈下不安全；席位须守包络或等另批抬参；RUN3 仅 peng 在 Buzz 外补跑（不自动化）。
- Knox P3：活动 = 未知；`max_turn` 零重跑 vs 可观测重跑留作开放门；抬 `idle_timeout` 须先修订 `docs/issue-38/IDLE-DECISION.md`（本 PR 不改 1500）。
- 明确不在范围：选项 (2)、MacSec `write_paths`、RUN3 计入 #57、`TMPDIR`。
- 功能地图：skip（无用户 UI 路径）。

## 验收表（文档级；跳过活机抬参）

```
S1: pass   docs/issue-64/README.md §2–§5
           idle 可在 turn 内启动；整池 teardown；孤儿 56637；活动定义 = 未知（不臆造）
S2: pass   README §1
           peng 经 Jenny 2026-10-09：探明+契约；条件后续抬参；不实现 (2)；不默认 (3)
S3: blocked-on-Mac-readonly
           src/buzz_team 对 idle_pool_sleep / idle_timeout / max_turn / idle_pool_sleep_seconds = 0
           活机 Desktop / env / *.acp.toml 键未填；附录 A 待 Quill/Hogan
S4: skip   本 PR 不抬参、不修复、不活机
S5: pass   docs/issue-64/CONTRACT.md
           不得超过 900/1500/1800；禁止席位内长静默任务；RUN3 仅 peng、Buzz 外
S6: skip   无活机时限改动
S7: pass   Knox PASS human:required；peng 经 Jenny 批本路径；无活机窗；#57 已关
```

证据口径：acp 日志 / memtrace / 产物 mtime。**不用**「统一日志无 Sandbox deny」（#63）。
