# #69 站会 cron 改用星期名（仓库产物；活机 BLOCKED）

对象：生产 relay 上周衡的 `站会开窗唤醒` `f5cc62c0-3756-419e-8a3f-8e694df2e93e`。
产品：peng 经 Jenny 2026-10-21 确认选项 A：`0 1 * * MON-FRI` + 数字星期 warn。
设计：[docs/design/69-cron-weekday-names](../design/69-cron-weekday-names/README.md)。

**本目录不执行活机 apply。** ACP 现为 0/9 HOLD。活机 S1（周五/周日 fire）在 Desktop/relay 可用之前标 BLOCKED。不要重拉 Desktop。Hogan 在 ACP≥9 后按下面做。

## 授权与边界

- 真更新：Knox `human:required`（脚本会碰 postgres 只读/预演 + owner update）→ peng 合入 → Hogan 执行。
- owner = 周衡。`buzz workflows update` 需要周衡私钥；脚本不读 `agents.env`，由执行者导出 `BUZZ_PRIVATE_KEY`。
- SQL 只做备份 / 断言 / `BEGIN…ROLLBACK` 预演。禁止 SQL 改 definition 当活机 apply（30620 带签名）。
- 默认 dry-run。`--live` 还要 `ISSUE69_I_UNDERSTAND_LIVE=yes`。
- 避开 CST 08:58–09:02。
- 不改上游、不动其他 7 条定义、不写 Desktop。

## 文件

| 文件 | 作用 |
|---|---|
| `after/workflow.yaml` | #38 after 文案 + `MON-FRI`（模板；活机只改 cron） |
| `examples/` | checker 样例（数字 1 条 / 名称 0 条）；不是模板 |
| `check-numeric-dow.py` | 只读 warn；读 YAML 或 list JSON；默认 exit 0 |
| `targets.sql` | 1 个目标 id + 7 个保持 id + 期望 cron |
| `backup.sql` | 整行备份（只读） |
| `verify.sql` | before/after 断言 |
| `rehearse.sql` | 模拟 UPDATE cron → 断言 1/7 → `ROLLBACK` |
| `apply.sh` / `rollback.sh` | owner update；默认 dry-run |
| `run.sh` | 入口 |
| `test/local-test.sh` | 有 postgres 时跑 backup/verify/rehearse |

## Hogan 顺序（Mac，ACP≥9 之后）

证据目录默认 `~/lab/buzz/evidence/issue-69/`（`R69_EVIDENCE` 可覆盖）。

```bash
cd <buzz-team>/docs/issue-69
./run.sh backup
./run.sh verify-before
./run.sh rehearse
# 把 live YAML 存成 before/workflow-live.yaml（buzz workflows get 的 content）
./apply.sh --from-yaml "$R69_EVIDENCE/before/workflow-live.yaml"   # dry-run，确认只改 cron
ISSUE69_I_UNDERSTAND_LIVE=yes ./run.sh apply --live
./run.sh verify-after
```

apply 只把 live YAML 里的 `0 1 * * 1-5` 换成 `0 1 * * MON-FRI`。文案不同时不得整文件覆盖 `after/workflow.yaml`。

回退：

```bash
ISSUE69_I_UNDERSTAND_LIVE=yes ./run.sh rollback --live
```

## 机器断言

- 恰好 1 条定义的 cron 变化；其余 7 条 `definition_hash` / 整行与 backup 一致。
- before cron = `0 1 * * 1-5`；after = `0 1 * * MON-FRI`。
- 目标 d_tag 可见 30620 仍为 1 条（owner update 替换事件）。
- 预演最后 `ROLLBACK`，库回到 backup。

## 数字星期检查

```bash
./check-numeric-dow.py examples/numeric-dow-sample.yaml   # warn 1，exit 0
./check-numeric-dow.py examples/named-dow-sample.yaml     # warn 0
./check-numeric-dow.py --strict examples/numeric-dow-sample.yaml  # exit 2
# 活机：buzz workflows list > list.json && ./check-numeric-dow.py list.json
```

relay cron 0.16：**数字星期 1=周日 … 7=周六**。写 `MON-FRI` 这类名称。

## 活机 S1（BLOCKED）

处理后用 cron 0.16 + `normalize_cron` 算 14 次，并在第一个周五 / 第一个周日查 `scheduled_workflow_fires`。仓库侧 14 次已由 `tests/test_cron_dow.py` 锁死。fire 行数需 Mac 醒着且 relay 在跑；休眠记「未知（休眠）」。

## 停止条件

- verify-before 不是 PASS（总数不是 8、cron 已不是 `1-5`、backup 过期、7 个保持 id 缺失）。
- rehearse 不是 `REHEARSAL PASS`。彩排不过，不 apply。
- apply 窗口落在 08:58–09:02 CST。
- ACP 不是 9/9：停，回报，不重拉 Desktop。
- verify-after 失败：立刻 owner rollback，再 verify-before，回报 Scout/Knox。
