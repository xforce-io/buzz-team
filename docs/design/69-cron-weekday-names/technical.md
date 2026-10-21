# L2 技术设计：模板、lint、apply/rollback

不改上游 block/buzz。不给 `doctor.py` 增加 workflow DB 访问。

## 1. 模块

```text
src/buzz_team/cron_dow.py          纯函数：DOW 解析 / CST 解释 / 14 次火 / 模板 lint
docs/issue-38/{before,after}/      仓库模板 cron → MON-FRI
docs/issue-69/                     runbook、SQL 备份断言预演、owner apply/rollback、checker
tests/test_cron_dow.py             黄金用例 + 模板 lint
tests/test_issue69_scripts.py      脚本形状、dry-run、禁写窗
```

`buzz_team.doctor` 仍只检查 Desktop 库存和 Seatbelt 策略。

## 2. cron 0.16 算法（文档化，非源码拷贝）

对照 Issue #69 L1 第 3 节实算。映射：

| 数字 | 名称 |
|---|---|
| 1 | SUN |
| 2 | MON |
| 3 | TUE |
| 4 | WED |
| 5 | THU |
| 6 | FRI |
| 7 | SAT |

- `0` / `0-4` / `8`：非法（库拒绝建定义）。
- 名称不区分大小写：`MON-FRI` / `mon-fri` / `Mon-Fri` 相同。
- 上游 `normalize_cron` 只补秒 `0` 和年 `*`，星期段原样。
- CST = UTC+8。UTC 时刻 +8 小时跨日时，CST 星期 = UTC 星期 +1。现网 8 条都在 CST 08:45–17:30，无跨日；checker 对 CST 00:00–07:59 额外标明「UTC 日期与 CST 不同」。

`next_fire_times` 只覆盖 DOM=`*` 且 month=`*` 的日程（现网与本票模板均如此）。黄金起点：2026-10-01 10:30 CST。

数字检测：DOW 字段里出现任何数字 token 即 warn。`*` 与星期名不是数字。

## 3. 模板

`docs/issue-38/before/workflow.yaml` 与 `after/workflow.yaml` 的 cron 从 `0 1 * * 1-5` 改为 `0 1 * * MON-FRI`。描述仍是工作日 09:00 CST。`docs/issue-38/smoke/*.json` 是历史快照，不改。

#38 `apply.sh` 用 after YAML 做 `workflows update`，`common.sh` 断言 live == before。两份模板都改名后：

- 若 #69 尚未活机 apply，#38 的 live==before 会失败（live 仍是 `1-5`），不会把数字写回。
- 若 #69 先 apply（只改 cron），#38 再 apply 会保留 `MON-FRI` 并改文案。

`docs/issue-69/after/workflow.yaml` 是「#38 after 文案 + MON-FRI」。活机 apply **不得**在 live 文案不同时整文件覆盖；只替换唯一的 `cron:` 值，且当前值必须是 `0 1 * * 1-5`。

## 4. lint 与 checker

- CI：`lint_template_paths` 扫描 `docs/issue-38/{before,after}` 与 `docs/issue-69` 下的 YAML（排除 `examples/` / `smoke/` / `evidence/`）。残留数字 DOW 则失败。
- `docs/issue-69/check-numeric-dow.py`：读 YAML 或 list JSON。默认 warn、exit 0；`--strict` 时有 warn 则 exit 2。无密钥。

README 写明：relay cron 0.16 数字星期 周日=1，优先写星期名。

## 5. 现网路径（Hogan，human:required）

对象只有 `f5cc62c0-3756-419e-8a3f-8e694df2e93e`。其余 7 个 id：`7d90ca75`、`50d27eb7`、`2d75251c`、`97152434`、`619b47c8`、`cd608a18`、`7c3362d0`。社区 `14a17e2d-40ae-4182-86c1-7dde01da0f03`。

| 步骤 | 谁写 | 默认 |
|---|---|---|
| `run.sh backup` | 只读 SQL，`row_to_json` 整行 | 可跑（需 postgres） |
| `run.sh verify-before` | 只读 SQL | 可跑 |
| `run.sh rehearse` | `BEGIN` → 模拟 UPDATE cron → 断言 1/7 → `ROLLBACK` | 可跑；库不变 |
| `run.sh apply` | **owner** `buzz workflows update` | **dry-run**；`--live` + `ISSUE69_I_UNDERSTAND_LIVE=yes` 才真发 |
| `run.sh verify-after` | 只读 SQL | apply 之后 |
| `run.sh rollback` | owner 重发备份 YAML | 同上守卫 |

SQL **不**写签名 30620，也 **不**作为活机 apply/rollback。rehearse 的 UPDATE 只在事务里模拟行数，最后 ROLLBACK。

机器断言：

- before：目标 1 行，cron=`0 1 * * 1-5`，workflows=8，其余 7 个 id 的 `definition_hash` 记入 backup。
- rehearse / after：只有目标行的 definition/hash/updated_at 变；cron 变为 `MON-FRI`；7 行与 backup 逐列相同。
- after 额外：该 d_tag 可见 30620 仍为 1 条（owner update 会替换事件）；其余 7 条事件 id 不变。

避开 CST 08:58–09:02（新旧表达式都在 01:00 UTC；落在未 claim 的那一分钟会多触发一次）。

## 6. 回退

活机回退：owner 把 backup 里的 before YAML 原样 `workflows update`。SQL 还原 workflow 行会与 30620 脱节，禁止当作活机回退。

## 7. 测试

- `tests/test_cron_dow.py`：黄金 14 次、数字 warn 1 / 名称 0、模板 lint、非法 0/8。
- `tests/test_issue69_scripts.py`：rehearse 含 BEGIN/ROLLBACK 且无 COMMIT；apply 默认拒绝；禁写窗；checker 默认 exit 0。
- 既有 `tests/test_doctor.py` 保持绿色。
- `docs/issue-69/test/local-test.sh`：有 `initdb` 时跑 SQL backup/verify/rehearse；CI 无 postgres 时不作为本票必过项（与 #62 全量库测分离）。

## 8. 安全边界

脚本不内嵌私钥。live apply 要求调用方已导出 `BUZZ_PRIVATE_KEY`（周衡 owner）。本 PR 不读 `agents.env`、不连生产库、不启动 Desktop。SQL 走 docker `buzz-prod-postgres-1` 的路径仅供 Hogan 在 Mac 上使用，且 backup/verify 强制 `default_transaction_read_only=on`。
