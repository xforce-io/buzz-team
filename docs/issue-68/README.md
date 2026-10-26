# #68 漏触发只读对账（S1 / S2；S3 stub）

Sibling 脚本。**不是** `doctor`，**不改** #58 `bin/buzz-health` 退出契约。不改上游 block/buzz，不重拉 Desktop，不碰元宝。

设计：[docs/design/68-missed-fires](../design/68-missed-fires/README.md)（L1/L2 已批：peng via Jenny 2026-10-26）。

## 仓库可证（CI）

夹具目录 `fixtures/0930-replay/` 冻结 L1 区间与 fires。**禁止**用 live `pmset` 顶替 09-30。

```bash
# S1 晚间：4 行「休眠期间」
python3 docs/issue-68/check-missed-fires.py \
  --workflows docs/issue-68/fixtures/0930-replay/workflows.json \
  --fires docs/issue-68/fixtures/0930-replay/fires.json \
  --pmset docs/issue-68/fixtures/0930-replay/pmset.txt \
  --since 2026-09-30T08:50:00+08:00 \
  --now 2026-09-30T17:40:00+08:00 \
  --no-advance

# S1 上午：miss_awake=0
python3 docs/issue-68/check-missed-fires.py \
  --workflows docs/issue-68/fixtures/0930-replay/workflows.json \
  --fires docs/issue-68/fixtures/0930-replay/fires.json \
  --pmset docs/issue-68/fixtures/0930-replay/pmset.txt \
  --since 2026-09-30T08:40:00+08:00 \
  --now 2026-09-30T09:35:00+08:00 \
  --no-advance

# S2 醒着缺 1：exit 2
python3 docs/issue-68/check-missed-fires.py \
  --workflows docs/issue-68/fixtures/0930-replay/workflows.json \
  --fires docs/issue-68/fixtures/0930-replay/fires-morning-awake-miss.json \
  --pmset docs/issue-68/fixtures/0930-replay/pmset.txt \
  --since 2026-09-30T08:40:00+08:00 \
  --now 2026-09-30T09:35:00+08:00 \
  --no-advance

python -m unittest tests.test_missed_fires tests.test_doctor -v
```

退出码：无 `miss_awake` → 0；有 `miss_awake` 或输入不足 → 2；**不用** 1。

keel-verify（仓库可证，SHA `85933b465b5373582df6ece69dc4351c25facbbf`）：[verify-runs/2026-10-26-85933b46](verify-runs/2026-10-26-85933b46/README.md)。

## 活机（Hogan · human:required）

本 agent 不跑。需要 Mac + `buzz-prod-postgres-1` + live `pmset`。无游标必须 `--since`。成功后只写：

```text
~/lab/buzz/var/issue68-reconcile-cursor.json
```

只读 SQL：`read.sql`（`BEGIN READ ONLY … ROLLBACK`，`PGOPTIONS=-c default_transaction_read_only=on`）。脚本不读 `agents.env`、不调 `workflows trigger`、不打印连接串或 `BUZZ_PRIVATE_KEY`。

## S3 stub

补跑 / 提醒出口 / 实例 README 策略句：本轮不做。检测 JSON 已含 id / 计划时间 / 标签，以后接 B 或 C 不必重做 S1/S2。
