# L2 技术设计：应触发 vs fires + pmset + 游标

不改上游 block/buzz。不给 `doctor.py` 增加 workflow DB 或 `pmset`。不改 #58 `bin/buzz-health` 的退出与「不写文件」契约。实现待人批 L1/L2 之后另开 PR。

## 1. 模块（批准后才写代码）

```text
src/buzz_team/missed_fires.py     纯函数：应触发枚举 / 分类 / 游标步进
docs/issue-68/check-missed-fires.py   sibling CLI：夹具或只读 SQL + pmset + 游标文件
docs/issue-68/fixtures/0930-replay/   冻结 L1 区间与 fires（禁止用 live pmset 顶替）
tests/test_missed_fires.py        黄金回放 + Knox/Quill 四类时钟
```

复用 `src/buzz_team/cron_dow.py`（已锁 cron 0.16 周日=1、`normalize_cron`、`next_fire_times`）。本票扩展窗内枚举，不复制上游 cron 源码。Python 标识与 JSON 键跟现有 `buzz_team` / doctor 一样用 snake_case，不在本模块另起一套驼峰。

`buzz_team.doctor` 仍只检查 Desktop 库存和 Seatbelt。`bin/buzz-health` 仍只跑 #58 五项。

## 2. 为什么是 sibling，不是 doctor / buzz-health

| 入口 | 若塞进本票 | 冲突 |
|---|---|---|
| `doctor` | 读 postgres / pmset；休眠漏可能变成 fail | #69 L2 已禁 workflow DB；doctor 的 `ok` 会与 Seatbelt 健康缠在一起 |
| `buzz-health` | 游标必须落盘；异常要改 exit 2 | #58：「Writes nothing」；exit 2 会把身份/进程/签名和对账混成一次失败 |
| sibling | 只读 SQL + 读 pmset + **只写**游标文件 | 休眠漏 exit 0；异常 exit 2 只作用于本脚本 |

「不 overload doctor fail」：休眠是未知，不是库存坏了。清醒异常值得脚本非零，但不值得让整机 `buzz-health` 变红——10/06 那种时钟缝隙会把日常健康检查打成持续失败，Hogan 反而看不见 #58 信号。本轮不在 buzz-health 里加「仅展示、不改 exit」的挂钩；要加另批。

## 3. 应触发 vs fire

对账对象：community `14a17e2d-40ae-4182-86c1-7dde01da0f03`，`status=active` 且 `enabled=true`，`definition.trigger.on = schedule`，且带 cron。元宝不计。创建时刻之前的槽位不算应触发。

应触发时刻：

- cron 按 UTC；5 段经 `normalize_cron` 补秒 `0` 与年 `*`。
- 星期编号与 `cron_dow` 相同（1=周日）。
- 枚举半开窗 `(cursor, now - grace]` 内、秒为 0 的计划瞬时。现网 8 条均为 DOM=`*` 且 month=`*`，与 `next_fire_times` 同一限制；其它日历 cron 本票拒绝并 fail fast。
- 匹配：`scheduled_workflow_fires` 存在相同 `(community_id, workflow_id, scheduled_for)` 即为有 fire。只看有没有行，不看 `workflow_runs` 是否 completed（S1 定量是 fire 行）。

`f5cc62c0` 在 #69 apply 前周五 09:00 不是应触发，不得标异常。apply 之后以库里的现 cron 为准（读 definition，不写死 `1-5`）。

## 4. pmset 区间

输入：live `pmset -g log`，或回放夹具里的 Sleep/Wake/DarkWake 行。只认这三类。

覆盖规则（与 L1 Draft / #62 休眠口径一致）：

- 休眠区间 = [进入 Sleep, 下一次**完整 Wake**)；中间 DarkWake 仍在睡。
- 计划时刻落在该区间，或落在完整 Wake 之后 60 秒内 → 休眠标签。
- 计划时刻晚于本机日志最早一条 Sleep/Wake/DarkWake → 可以判醒着或休眠。
- 计划时刻早于该地平线 → 「未知（pmset 已滚动）」，禁止标异常。
- 09-30 回放**必须**用冻结区间，禁止调用 live `pmset` 冒充。

2026-10-23：live 最早约 10-16。历史回放只能靠夹具。

## 5. 游标与 grace

Knox/Quill 三条，本票写成算法，没有「往前推 N 分钟」的滑动窗。

状态文件（实现时默认，可用参数覆盖）：

```text
~/lab/buzz/var/issue68-reconcile-cursor.json
```

字段：`reconciled_to`（UTC ISO）、`updated_at`、`grace_seconds`。不进 git。不写 Desktop 库存，不写 postgres。

| 步骤 | 规则 |
|---|---|
| grace | **120 秒**（约 2 分钟）。计划时刻 `T` 仅当 `T <= now - 120s` 才进入本轮。 |
| 有游标 | 窗 = `(reconciled_to, now - grace]`。对完后只把游标写到 `now - grace`。 |
| `now - grace < reconciled_to` | 时钟回拨：本轮跳过，**不**把游标改小，exit 0，报告 `skipped_clock_rewind`。 |
| 无游标 | **必须** `--since <UTC>`；否则非零退出。`--since` 只作本轮窗左端并在成功后写成新游标。 |
| `--no-advance` | 审计 / 回放：算窗、打印，不写文件。 |
| `--now` / `--cursor` / `--pmset` / `--fires` / `--workflows` | 夹具入口。默认不写 live 游标。 |
| 对账失败（SQL/pmset 读失败） | fail fast，不写游标。 |

晚到 fire：`T` 仍在 `(now-grace, now]` 时本轮不评估；下次 `T` 已入窗且行已在则算正常。这就是 C.A4。

向前跳 / 长睡：游标停在睡前，醒来一次跑完 `(cursor, now-grace]`。这就是 C.A1 / C.A3。

## 6. 分类与输出

对窗内每个应触发瞬时：

1. 有 fire → 正常（可进 `fired_ok` 计数，不进 `misses`）。
2. 无 fire + 休眠规则命中 → `label=未知（休眠）`，`display=休眠期间`，附 `sleep_interval`。
3. 无 fire + 醒着 → `label=异常（醒着漏触发）`。
4. 无 fire + pmset 地平线之外 → `label=未知（pmset 已滚动）`。

JSON（字段名实现时锁定；形状如下）：

```json
{
  "ok": true,
  "cursor_before": "2026-09-30T08:50:00+00:00",
  "cursor_after": "2026-09-30T09:38:00+00:00",
  "now": "2026-09-30T09:40:00+00:00",
  "grace_seconds": 120,
  "counts": {
    "fired_ok": 6,
    "miss_sleep": 0,
    "miss_awake": 0,
    "miss_pmset_rolled": 0,
    "skipped_not_due": 0
  },
  "misses": []
}
```

每条 miss：`definition_id`、`name`、`owner_seat`、`cron`、`planned_at_cst`、`planned_at_utc`、`label`、`display`、`sleep_interval`（可空）。

退出码：

- 0：无 `miss_awake`（可以有休眠 / pmset 滚动 / rewind skip）。
- 2：存在 `miss_awake`，或输入不足（无游标且无 `--since`、夹具缺字段、非 DOM=* cron）。
- 不使用 exit 1。

只读 SQL 与 #62/#69 相同：`BEGIN READ ONLY … ROLLBACK`，`PGOPTIONS=-c default_transaction_read_only=on`，`docker exec -i buzz-prod-postgres-1 psql -U buzz -d buzz`。无私钥。默认不连库：夹具模式供 CI。

## 7. 09-30 回放夹具

目录（实现时）：`docs/issue-68/fixtures/0930-replay/`。

冻结内容来自 [HOW.md](HOW.md)，不是 live：

- `workflows.json`：8 条 id + cron + created_at + owner 名。
- `fires.json`：09-30 08:45–09:30 六条在；16:50–18:00 对该四槽 0 行。可用最小集。
- `pmset.txt`：16:58:00 Sleep → 17:16:32 Wake；17:17:44 Clamshell Sleep → 17:35:33 Wake；上午 08:34:14 已 Wake，08:45–09:30 无 Sleep。DarkWake 样例可附但不结束区间。
- 晚间回放：`--since 2026-09-30T08:50:00+08:00`（或 UTC 等价）且 `--now 2026-09-30T17:40:00+08:00`（grace 后仍覆盖 17:30）→ misses=4，display 均为「休眠期间」。
- 上午回放：`--since 2026-09-30T08:40:00+08:00` 且 `--now 2026-09-30T09:35:00+08:00` → `miss_awake=0`。
- S2 醒着夹具：同一上午去掉一条 fire → `miss_awake=1`。

`--now 17:40` 时 grace 把 17:38 之后排除；17:30 仍在窗内。

## 8. 测试（实现 PR 必过）

`tests/test_missed_fires.py` 只打纯函数 + 夹具文件，不连生产库、不调 live `pmset`。

| 用例 | 断言 |
|---|---|
| 09-30 晚间回放 | 4 miss，id 集合与顺序按计划时间，均为休眠期间，区间与 HOW 表一致 |
| 09-30 上午回放 | `miss_awake=0` |
| 醒着缺 1 | `miss_awake=1`，休眠样例不被标异常 |
| pmset 地平线之前 | 未知（pmset 已滚动） |
| 周五 `1-5` | `f5cc62c0` 09:00 不进应触发 |
| 向前跳 | 游标从 T0 到 T0+3h，中间漏列出，游标=`now-grace` |
| 向后拨 | 游标不变，`skipped_clock_rewind` |
| 长睡一次跑 | 数小时窗内全部 miss 一次列出 |
| grace 内晚到 | `T` 在 `(now-grace, now]`，即使 fires 无行也不进 misses |
| 无游标无 `--since` | 非零 |
| doctor 回归 | `tests/test_doctor.py` 仍绿；本票不改 `doctor.py` |

## 9. 功能地图（L2.8）

实现批准后再加 keel-verify 行。预定路径：`.agents/skills/verify-buzz-team/features/missed-fires.md`（本设计 PR **不建**该文件）。

| ID | 入口 | 环境 |
|---|---|---|
| S1.A1–A5、S2.A1–A4、C.A1–A5、H.A1–A2 | 预定 `missed-fires.md`「仓库可证」 | 本仓夹具 / unittest |
| 活机 postgres + live pmset | 预定「活机」+ 将来 `docs/issue-68/README.md` | Hogan；human:required；本 agent 不跑 |

对不上该行不得进实现 review。

## 10. 安全边界

- 脚本不内嵌私钥，不读 `agents.env`，不调用 `workflows trigger`。
- SQL 强制只读。失败不写游标。
- 游标文件不含密钥；路径在实例 `~/lab/buzz/var/`，不进仓库。
- 输出禁止打印连接串密码或 `BUZZ_PRIVATE_KEY`。
- 本设计 PR 不连生产库、不启动 Desktop、不改 `~/lab/buzz` 现网入口。

## 11. 回退

本轮无产品代码。实现之后：删 sibling 入口与游标文件即回到人工对账；doctor / buzz-health 无变更可回退。

## 12. S3 stub

补跑、提醒出口、实例 README 策略句：不在本 L2 展开。检测 JSON 已含 id / 计划时间 / 标签，足够以后接 B 或 C。
