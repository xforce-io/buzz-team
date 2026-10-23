# #68 keel-how：漏触发怎么产生、现在怎么看见

`skip` 实现。事实源，供 L1/L2 引用。不改上游、不改实例。

## Overview

本地 relay（`buzz-prod-relay-1`，镜像 `ghcr.io/block/buzz:sha-c507a4d`）用 cron 循环调度 8 条 schedule workflow。循环是 `sleep(60s)` 再读墙钟 `Utc::now()`，窗口写死 `[now-60s, now]`。窗口外的计划时刻**不写** `scheduled_workflow_fires`，也没有「错过」行。Mac 休眠时调度停；醒来若已超过 60 秒，那几次永远消失。清醒时墙钟跳变或 tick 相位贴整分，也会把某一分钟永远丢掉（2026-10-06 09:30 `7d90ca75`）。

现在要看见漏触发，只能人工拿 fires 缺口对 `pmset -g log`。#68 要在 buzz-team 侧做成可回放的只读对账。

## 东西在哪

| 事实 | 路径 | 仓库跟踪？ |
|---|---|---|
| 8 条本地 schedule 定义 | 生产 postgres `workflows`，community `14a17e2d-40ae-4182-86c1-7dde01da0f03` | live-only；id/cron 快照见 `docs/issue-69/test/fixture.sql` 与下表 |
| 是否触发 | `scheduled_workflow_fires` PK `(community_id, workflow_id, scheduled_for)` | live-only |
| 休眠区间 | Mac `pmset -g log` 的 Sleep / Wake / DarkWake | live-only；滚动约一周 |
| 09-30 四次漏 | Issue #68 L1 Draft 事实表（CST） | **冻结在 Issue**；live pmset 已滚过 09-30，**禁止再抓** |
| 调度逻辑 | block/buzz @ `c507a4d` `crates/buzz-workflow/src/lib.rs` | 上游只读；本仓不拷源码 |
| 应触发算法 | 本仓 `src/buzz_team/cron_dow.py`（cron 0.16，周日=1） | 仓库 |

**不改**：上游 60 秒窗口与补跑；`buzz-team doctor` 的 Desktop/Seatbelt 契约；`bin/buzz-health` 的 #58 五项；元宝 relay；#62 残留；Mac 是否允许休眠。

## 现网 8 条（本地 :3000 only）

cron 为 relay UTC。CST = UTC+8。`f5cc62c0` 在 #69 活机 apply 前仍是 `0 1 * * 1-5`（cron 0.16 = 周日到周四），周五 09:00 **不是**应触发。

| id | 名称 / owner | cron（UTC） | CST 槽 |
|---|---|---|---|
| `7c3362d0-0b64-46fc-8ab8-9ee6ed982296` | 每日待办复制-0845 / 裴昭 | `45 0 * * *` | 08:45 |
| `f5cc62c0-3756-419e-8a3f-8e694df2e93e` | 站会开窗唤醒 / 周衡 | `0 1 * * 1-5` | 09:00（日–四） |
| `97152434-1ec3-4b51-b55d-4159ecec4162` | 能源线收集唤醒 / 韩川 | `0 1,9 * * *` | 09:00、17:00 |
| `619b47c8-4339-46b1-bbfa-2a7fa9b80c19` | 技术线收集-0910 / 秦牧 | `10 1 * * *` | 09:10 |
| `2d75251c-48bc-46b7-9bec-8e06d2989c85` | 中台PBU收集-0915-1715 / 卫平 | `15 1,9 * * *` | 09:15、17:15 |
| `7d90ca75-51a1-40a6-8966-8fffc9c523c3` | 事务秘书处当日简报-0930 / 裴昭 | `30 1 * * *` | 09:30 |
| `cd608a18-6254-41cc-a0d7-c23879b1fe79` | 技术线收集-1710 / 秦牧 | `10 9 * * *` | 17:10 |
| `50d27eb7-e768-4401-af80-8fc95b5f0bae` | 事务秘书处当日简报-1730 / 裴昭 | `30 9 * * *` | 17:30 |

## 09-30 17:00–17:30 冻结事实（CST，禁止再抓 pmset）

出处：Issue #68 L1 Draft（2026-10-01）+ 2026-10-23 PARTIAL 补核。fires 仍缺 4 行；休眠区间沿用 L1，不重抓 live `pmset`。

| 定义 | 计划 | fire | 覆盖休眠区间 | 标签 |
|---|---|---|---|---|
| `97152434-…` 韩川 | 17:00 | 无 | 16:58:00 Maintenance Sleep → 17:16:32 Wake | 休眠期间 |
| `cd608a18-…` 秦牧 | 17:10 | 无 | 同上 | 休眠期间 |
| `2d75251c-…` 卫平 | 17:15 | 无 | 同上（醒来已过 60s 窗） | 休眠期间 |
| `50d27eb7-…` 裴昭 | 17:30 | 无 | 17:17:44 Clamshell Sleep → 17:35:33 Wake | 休眠期间 |

同日醒着对照：08:45–09:30 六条计划均有 fire → 异常 0。09-29 晚间同四槽 4/4 有 fire。09-30 16:50–18:00 对该窗 0 fire。

补充：16:54:50 合盖后基本一直在睡；16:55–16:57 几次秒级 DarkWake **不算醒来**。relay `RestartCount=0`，StartedAt 2026-09-25 07:12 CST。

## 为什么醒来不补（机制，不是产品选项）

`c507a4d` cron 分支：

1. `loop { sleep(60s); now = Utc::now(); cron_fire_instant(expr, now, 60, id) }`
2. `window_start = now - 60s`；`sched.after(window_start).next()` 且 `<= now`
3. 去重只做 `INSERT … ON CONFLICT (community, workflow, scheduled_for) DO NOTHING`
4. cron 分支不读 `latest_scheduled_workflow_fire`，启动与 tick 都没有补触发

所以：休眠超过 60 秒、墙钟向前跳过窗口、或 `sleep(60)+处理耗时` 把缺口扫过整分，该时刻永久丢失。本票只对账，不改这段。

## 对账要和 relay 同一套「应触发」

误报来源（L1 Draft 第 5 节第 6 条，已另开 #69）：若用常见「1=周一」解释 `0 1 * * 1-5`，会把周五无 fire 标成醒着漏触发。应触发必须走本仓 `cron_dow`（周日=1）。#69 未活机 apply 前，周五 `f5cc62c0` 是预期 skip，不是 #68 异常。

## Gotchas

- `pmset -g log` 约一周。2026-10-23 起 live 最早约 10-16，**不能**再证明 09-30。S1 回放用冻结 L1 区间 + fires 夹具。
- DarkWake 仍在休眠。完整 Wake 才结束覆盖区间。
- 醒来后 60 秒内的计划时刻：relay 窗口也可能够不到，按 L1 Draft 与休眠同类，标「未知（休眠）」。
- fires 表目前未见清理调用方；缺行表示当时没 claim，不是被删。
- 只看本地 community。元宝不计。
- `bin/buzz-health` 仍是 #58 口径（doctor / 身份 / 进程 / 签名）。2026-10-23 证实它不对账 fires/pmset。
