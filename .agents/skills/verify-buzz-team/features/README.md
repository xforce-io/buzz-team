# 功能地图

| 验收 | 功能 | 入口 |
|---|---|---|
| #53 S1 | [运行库存](runtime-inventory.md) | Desktop 身份配置、进程、现役脚本 |
| #53 S2 | [薄运行链路](thin-runtime.md) | Desktop → buzz-acp → Seatbelt → Grok |
| #53 S3 | [退役运行层](retired-runtime.md) | 普通安装包、CLI、README/runbook |
| #47 S1–S3 | [原生会话](native-session.md) | Desktop Advanced、usage 事件 |
| #48 S1–S3 | [业务权限](business-access.md) | Desktop 作者策略、Seatbelt |
| #54 S1–S4 | [官方升级](official-upgrade.md) | 官方组件、只读诊断、官方 Buzz CLI |
| #58 S1–S5 | [实例入口](instance-entries.md) | `~/lab/buzz/bin/buzz`、`bin/buzz-health`、`docs/issue-58/*.sh` |
| #57 S1–S5 | [周衡 Kairo 写入](zhouheng-kairo-write.md) | 周衡真实会话、Seatbelt 探针、docs/issue-57 脚本 |
| #69 S1–S3 | [星期名 cron](cron-weekday-names.md) | 仓库模板 / `cron_dow` 单测 / `docs/issue-69/check-numeric-dow.py` / dry-run apply；活机 `docs/issue-69/README.md`（ACP≥9） |
| #68 S1–S2 | [漏触发对账](missed-fires.md) | 仓库夹具 / `missed_fires` 单测 / `docs/issue-68/check-missed-fires.py`；活机 Hogan human:required；S3 stub |
