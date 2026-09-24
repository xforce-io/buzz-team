# Issue #38 live apply runbook（合入后与 Hogan 一起执行）

**现在不要执行。** 合入门禁 + Knox human:required 通过后，再跑。

## 0. 前置

- PR tip SHA 已合入 main（或明确按该 tip 的 `docs/issue-38/after/` 执行）。
- thin-bin 仍为 `046ac43`（`lab/buzz/bin/agent-executor` / `agent-harness` 包装器指向
  `…/releases/046ac4345647ea6bc9c57bbf91ddb556a91694cd/…`；`apply.sh`/`rollback.sh` 会校验）。
- Scout：无并行未提交周衡实例脏改。

## 1. doctor + bind（before）

```bash
cd /Users/xupeng/dev/github/buzz-team
python -m buzz_team --instance /Users/xupeng/lab/buzz doctor | tee /Users/xupeng/lab/buzz/evidence/issue-38/doctor-before.json
python -m buzz_team --instance /Users/xupeng/lab/buzz bind | tee /Users/xupeng/lab/buzz/evidence/issue-38/bind-before.txt
```

记录 9 席 `agent-pids`：`~/Library/Application Support/xyz.block.buzz.app/agents/agent-pids/*.json`。
周衡精确文件：`51fb6cd8…__a558771623f298980db444a8406459dff1cbd20f264a72d00ffaca270c0fa16f.json`。

## 2. apply（只动周衡 + workflow body）

```bash
cd /Users/xupeng/dev/github/buzz-team
ISSUE38_I_UNDERSTAND_LIVE=yes docs/issue-38/scripts/apply.sh
```

脚本行为摘要：

1. 校验 `ISSUE38_I_UNDERSTAND_LIVE=yes`、thin-pin `046ac43`、周衡 pid 文件唯一（`${PUB}__${TEAM}.json`）
2. 断言 live workflow content == `docs/issue-38/before/workflow.yaml`（不一致则 abort）
3. **然后**才创建 `evidence/issue-38/backup-<ts>/`（含 live `workflow-get.json` → `workflow-live-before.yaml`、`zhouheng-row-before.json`）— 仅快照，尚未改 live
4. **先** `workflows update --yaml "$(cat after/workflow.yaml)"`（**YAML CONTENT**，不是路径；见 `buzz workflows update --help`），再 `get` 读回校验 == `after/workflow.yaml`。此步失败则 **不** patch 本地文件
5. 仅 workflow 成功后：只 patch managed-agents 的周衡行；更新 pj/AGENTS/instructions-1
6. safe-kill：pid 来自精确文件 + `kill -0` 存活 + 进程 env/cmdline 含周衡全量 pubkey，否则 abort
7. 校验其他 8 席（`*__${TEAM}.json` 减去周衡）pid 不变

实网 workflow 路径烟测：`docs/issue-38/scripts/smoke-real-workflow.sh`（只建/改/删临时 cron，不碰真实 workflow）；产物在 `docs/issue-38/smoke/`。

## 3. doctor + bind（after）

同 before，tee 到 `doctor-after.json` / `bind-after.txt`。对比 pid 表：仅周衡变。

## 4. 行为抽检（Hogan）

- S1：`buzz workflows trigger --workflow f5cc62c0-3756-419e-8a3f-8e694df2e93e`（周衡密钥）；≤120s 开窗帖
- S2：周衡进程 env `BUZZ_ACP_EFFORT_LEVEL=medium`、`BUZZ_ACP_IDLE_TIMEOUT=180`
- S3：DM「完成了吗」→ 三栏

## 5. 回滚

```bash
cd /Users/xupeng/dev/github/buzz-team
ISSUE38_I_UNDERSTAND_LIVE=yes docs/issue-38/scripts/rollback.sh /Users/xupeng/lab/buzz/evidence/issue-38/backup-<timestamp>
```

回滚：先 `workflows get` 与 `workflow-live-before.yaml` 比较——相同则跳过 update；不同则 `--yaml "$(cat workflow-live-before.yaml)"`（CONTENT）并读回校验。然后只写回周衡 managed-agents 行 + pj/AGENTS/instructions-1；同样 safe-kill + 校验其他 8 席 pid。不用 staged `before/workflow.yaml`。

再次 doctor+bind；确认仅周衡 pid 再变一次。
