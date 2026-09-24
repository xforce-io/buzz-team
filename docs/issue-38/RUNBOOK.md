# Issue #38 live apply runbook（合入后与 Hogan 一起执行）

**现在不要执行。** 合入门禁 + Knox human:required 通过后，再跑。

## 0. 前置

- PR tip SHA 已合入 main（或明确按该 tip 的 `docs/issue-38/after/` 执行）。
- thin-bin 仍为 `046ac43`（`instance.local.json` / `lab/buzz/bin/*` 未改）。
- Scout：无并行未提交周衡实例脏改。

## 1. 备份（apply.sh 自动做）

备份根：`/Users/xupeng/lab/buzz/evidence/issue-38/backup-<timestamp>/`

## 2. doctor + bind（before）

```bash
cd /Users/xupeng/dev/github/buzz-team
python -m buzz_team --instance /Users/xupeng/lab/buzz doctor | tee /Users/xupeng/lab/buzz/evidence/issue-38/doctor-before.json
python -m buzz_team --instance /Users/xupeng/lab/buzz bind | tee /Users/xupeng/lab/buzz/evidence/issue-38/bind-before.txt
```

记录 9 席 `agent-pids`：`…/agents/agent-pids/*.json`。

## 3. apply（只动周衡 + workflow body）

```bash
docs/issue-38/scripts/apply.sh
```

预期：

- workflow body 已更新，owner/cron/`@周衡` 不变
- managed-agents 仅周衡活跃行 effort/idle/system_prompt 变
- pj.md、周衡 workspace AGENTS.md、instructions-1.md 已替换
- **仅** pubkey `51fb6cd8…` 对应 ACP pid 变化；其他 8 席 pid 不变

## 4. doctor + bind（after）

同 before，tee 到 `doctor-after.json` / `bind-after.txt`。对比 pid 表。

## 5. 行为抽检（Hogan）

- S1：`buzz workflows trigger --workflow f5cc62c0-3756-419e-8a3f-8e694df2e93e`（周衡密钥）；≤120s 开窗帖
- S2：周衡进程 env `BUZZ_ACP_EFFORT_LEVEL=medium`、`BUZZ_ACP_IDLE_TIMEOUT=180`
- S3：DM「完成了吗」→ 三栏

## 6. 回滚

```bash
docs/issue-38/scripts/rollback.sh /Users/xupeng/lab/buzz/evidence/issue-38/backup-<timestamp>
```

再次 doctor+bind；确认仅周衡 pid 再变一次。
