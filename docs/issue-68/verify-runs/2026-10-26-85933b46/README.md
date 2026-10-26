# keel-verify #68（仓库可证 · 2026-10-26）

候选 SHA：`85933b465b5373582df6ece69dc4351c25facbbf`  
PR：https://github.com/xforce-io/buzz-team/pull/75  
地图：`.agents/skills/verify-buzz-team/features/missed-fires.md`  
安装：仓库外 venv `/tmp/buzz-team-68-verify-venv`，wheel `buzz_team-0.1.0-py3-none-any.whl` sha256 `99aa53f3d8bae0b7589a1428017ce6c4856ad2a13c33959de575a7c75e7af00b`  
工作树在冻结 SHA 时干净。未启动 Desktop，未写 live cursor，未连生产 postgres，未调 live `pmset`。

Python：`/tmp/buzz-team-68-verify-venv/bin/python`（下表简写为 `python`）。夹具目录：`docs/issue-68/fixtures/0930-replay/`。

## L1.8 / 仓库可证

| ID | 结果 | 命令 | 证据 |
|---|---|---|---|
| S1.A1 | **pass** | `python docs/issue-68/check-missed-fires.py --workflows …/workflows.json --fires …/fires.json --pmset …/pmset.txt --since 2026-09-30T08:50:00+08:00 --now 2026-09-30T17:40:00+08:00 --no-advance` | `01-evening-replay.*` + `01-evening-assert.txt`：恰好 4 行，id `97152434` / `cd608a18` / `2d75251c` / `50d27eb7` |
| S1.A2 | **pass** | 同上 | 每行含 definition_id、planned_at_cst、sleep_interval；`display=休眠期间`，`label=未知（休眠）` |
| S1.A3 | **pass** | 同上 | 前三 `16:58:00 Maintenance Sleep → 17:16:32 Wake`；17:30 为 `17:17:44 Clamshell Sleep → 17:35:33 Wake` |
| S1.A4 | **pass** | 同上，`--since 2026-09-30T08:40:00+08:00 --now 2026-09-30T09:35:00+08:00` | `02-morning-replay.*`：`miss_awake=0`，`fired_ok=6`，`misses=[]` |
| S1.A5 | **pass** | 同上（上午 + 晚间） | JSON 自带 `sleep_interval`；操作者不必再读 pmset |
| S2.A1 | **pass** | `--fires fires-morning-awake-miss.json` + 上午窗 | `03-awake-miss.*`：`miss_awake=1`，`7d90ca75`，`异常（醒着漏触发）`，exit 2 |
| S2.A2 | **pass** | 晚间回放 | `01-evening-replay.*`：`miss_awake=0`，4 条均为休眠 |
| S2.A3 | **pass** | 空 fires + `--since 2026-09-29T16:50:00+08:00 --now 2026-09-29T17:40:00+08:00` | `05-pmset-horizon.*`：`miss_pmset_rolled=4`，`miss_awake=0`，标签 `未知（pmset 已滚动）`，exit 0 |
| S2.A4 | **pass** | unittest `FridaySkipTests`；CLI 空 fires + 2026-10-02 09:00 窗 | `04-unittest.txt`；`06-friday-skip-ids.txt`：`f5cc62c0` 不进 misses（周日=1） |
| C.A1 | **pass** | `--cursor 2026-09-30T16:50:00+08:00 --now 2026-09-30T19:50:00+08:00` | `07-forward-jump.*`：4 条休眠漏列出，`cursor_after=now-120s`（`11:48:00Z`） |
| C.A2 | **pass** | `--cursor 2026-09-30T09:38:00+00:00 --now 2026-09-30T09:30:00+00:00` | `08-clock-rewind.*`：`skipped_clock_rewind=true`，游标不变，exit 0 |
| C.A3 | **pass** | `--cursor 2026-09-30T08:50:00+08:00 --now 2026-09-30T17:40:00+08:00` | `09-long-sleep.*`：同一窗 4 条休眠漏，exit 0 |
| C.A4 | **pass** | 醒着缺 1 夹具 + `--now 2026-09-30T09:31:00+08:00` | `10-grace-late.*`：`miss_awake=0`，`skipped_not_due=1`，exit 0 |
| C.A5 | **pass** | 夹具齐全但无 `--since` / `--cursor` | `11-no-cursor-no-since.*`：exit 2，`no cursor and no --since`，不用 exit 1 |
| H.A1 | **pass** | `python -m unittest tests.test_doctor -v` | `04-unittest.txt`（6 绿）；`doctor.py` 无 workflow DB / pmset；blob `6317efec` = `origin/main` |
| H.A2 | **pass** | 晚间 sibling exit 0；`git diff origin/main -- docs/issue-58/bin/buzz-health` 空 | `01-evening-replay.exit`=0；`05-doctor-buzz-health-vs-main.txt` blob `8fa0e037` = `origin/main`；`tests.test_issue58_entries` 42 绿 |
| S3.A0 | **not_run** | stub | 本轮无补跑 / 提醒 / 实例 README 策略句验收。检测 JSON 已含 id / 计划时间 / 标签。 |
| 活机 postgres + live pmset | **not_run** | human:required | ACP Desktop down；本 agent 不重拉、不写 live cursor、不连 `buzz-prod-postgres-1`、不用 live `pmset` 顶替 09-30。 |

夹具缺 `--pmset` / `--fires` / `--workflows` 之一：`99-partial-fixture.*` exit 2，`will not substitute live pmset or SQL`。

## 必重跑五项（本 run 实测，不沿用实现 agent 口头结论）

| # | 期望 | 实测 |
|---|---|---|
| 1 | 晚间 4「休眠期间」，exit 0 | pass · `01-evening-replay.exit`=0 |
| 2 | 上午 `miss_awake=0` | pass · `02-morning-replay.stdout` |
| 3 | 醒着缺 1：`miss_awake=1`，exit 2 | pass · `03-awake-miss.exit`=2 |
| 4 | `unittest tests.test_missed_fires tests.test_doctor` | pass · 31 tests，0.344s，OK |
| 5 | `doctor.py` 与 `bin/buzz-health` 相对 main 退出契约未改 | pass · 两文件 blob 与 `origin/main` 逐字节相同 |

`python -m unittest discover -s tests -v` 另有 1 个失败：`tests.test_issue62_sql.LocalPostgresTest`（本环境无 #62 本地 postgres；非本票、非本地图「仓库可证」）。未标 #68 fail。

下一步：ready for @Knox。不合入。活机仍 human:required。
