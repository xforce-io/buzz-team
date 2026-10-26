# #68 S1–S2 漏触发只读对账

入口：`buzz_team.missed_fires`；`python -m unittest tests.test_missed_fires tests.test_doctor`；`docs/issue-68/check-missed-fires.py` + `fixtures/0930-replay/`。活机按 [`docs/issue-68/README.md`](../../../../docs/issue-68/README.md)：Mac + postgres + live `pmset`，**human:required**。本 agent 不跑活机，不重拉 Desktop，不改 `~/lab/buzz` 现网入口。

设计：[`docs/design/68-missed-fires/product.md`](../../../../docs/design/68-missed-fires/product.md) L1.8；L2.8 映射见 [`technical.md`](../../../../docs/design/68-missed-fires/technical.md) §8–§9。L1/L2 已批（peng via Jenny 2026-10-26）。

S3 补跑 / 提醒 / 实例 README 策略句：**stub**，本轮无验收。

## 仓库可证

1. **S1.A1–A3 09-30 晚间回放**：`--since 2026-09-30T08:50:00+08:00 --now 2026-09-30T17:40:00+08:00` + 冻结夹具。恰好 4 行，id 顺序 `97152434` / `cd608a18` / `2d75251c` / `50d27eb7`，`display=休眠期间`，`label=未知（休眠）`。前三区间 `16:58:00 Maintenance Sleep → 17:16:32 Wake`，17:30 为 `17:17:44 Clamshell Sleep → 17:35:33 Wake`。exit 0。
2. **S1.A4–A5 同日上午**：`--since 2026-09-30T08:40:00+08:00 --now 2026-09-30T09:35:00+08:00` → `miss_awake=0`，`fired_ok=6`。输出自带区间，不必再读 pmset。
3. **S2.A1 醒着缺 1**：`fires-morning-awake-miss.json` 去掉 `7d90ca75` 09:30 → `miss_awake=1`，label `异常（醒着漏触发）`，CLI exit 2。
4. **S2.A2 休眠不标异常**：晚间 4 条 `miss_awake=0`。
5. **S2.A3 pmset 地平线之前**：09-29 17:00–17:30 对 09-30 08:34 地平线 → `未知（pmset 已滚动）`，不是异常。
6. **S2.A4 周五 `1-5`**：`f5cc62c0` cron `0 1 * * 1-5`（#69 apply 前）在 2026-10-02 09:00 不进应触发、不进 misses。复用 `cron_dow`（周日=1）。
7. **C.A1 向前跳**：游标 T0 → T0+3h，中间漏列出，游标=`now-grace`（120s）。
8. **C.A2 向后拨**：`now-grace` 早于游标 → `skipped_clock_rewind`，游标不变，exit 0。
9. **C.A3 长睡一次跑**：08:50→17:40 一窗列出全部 4 条休眠漏。
10. **C.A4 grace 内晚到**：`T` 在 `(now-grace, now]`，即使 fires 无行也不进 misses。
11. **C.A5 无游标无 `--since`**：exit 2，不扫全表。不用 exit 1。
12. **H.A1 doctor**：`tests/test_doctor.py` 仍绿；`doctor.py` 不读 workflow DB / pmset。
13. **H.A2 buzz-health**：#58 入口与退出不变；仅休眠漏时 sibling exit 0。

夹具模式缺 `--pmset` / `--fires` / `--workflows` 之一即 fail fast，**禁止** live `pmset` 顶替。CI：`python -m unittest discover -s tests -v`。

## 活机（human:required）

本 agent 不跑。未执行不得标 pass。

1. Hogan 在 Mac 上对生产 postgres 跑 sibling（`read.sql`：`BEGIN READ ONLY … ROLLBACK` + `PGOPTIONS=-c default_transaction_read_only=on`）+ live `pmset -g log`。
2. 无游标必须 `--since <UTC>`。成功后只写 `~/lab/buzz/var/issue68-reconcile-cursor.json`。
3. 不启动 Desktop，不写 Desktop 库存，不改 `~/lab/buzz` 现网入口，不触发 workflow。
4. Knox 审实现 PR 后方可合入；活机 apply 仍 human:required。
