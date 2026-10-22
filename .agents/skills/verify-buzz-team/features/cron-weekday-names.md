# #69 S1–S3 星期名 cron

入口：仓库模板与 `buzz_team.cron_dow`；`python -m unittest tests.test_cron_dow tests.test_issue69_scripts`；`docs/issue-69/check-numeric-dow.py`；`docs/issue-69/apply.sh` dry-run。活机按 [`docs/issue-69/README.md`](../../../../docs/issue-69/README.md)：ACP≥9 后 `backup` → `verify-before` → `rehearse` → `apply --live` → `verify-after`，再核第一个周五/周日 fire。ACP 0/9 时活机项标 **blocked**，不得写成 skip，也不得假装已跑。

设计：[`docs/design/69-cron-weekday-names/product.md`](../../../../docs/design/69-cron-weekday-names/product.md) L1.8；L2.8 映射见 [`technical.md`](../../../../docs/design/69-cron-weekday-names/technical.md) §8。

## 仓库可证

1. **S1.A1 14 次下一触发**：`tests/test_cron_dow.py` 从 2026-10-01 10:30 CST 起算。`0 1 * * MON-FRI` 14 次全是周一到周五 09:00 CST；`0 1 * * 1-5` 对照为周日到周四（0 次周五、3 次周日）。
2. **S1.A4 模板 cron**：`docs/issue-38/before/workflow.yaml`、`docs/issue-38/after/workflow.yaml`、`docs/issue-69/after/workflow.yaml` 均为 `0 1 * * MON-FRI`。描述仍是工作日 09:00 CST。`lint_template_paths` 扫这些文件，残留数字 DOW 则失败。
3. **S2.A1 数字样例 warn 1**：`docs/issue-69/check-numeric-dow.py docs/issue-69/examples/numeric-dow-sample.yaml` 列出 1 条，并打印 cron 0.16 周日=1 的 CST 解释（`1-5` → CST 周日到周四 09:00）。默认 exit 0。
4. **S2.A2 名称/`*` warn 0**：同脚本读 `examples/named-dow-sample.yaml`（`MON-FRI`）以及测试里的 `*` 样例，warnings=0。
5. **S2.A3 模板 lint 进 CI**：`TemplateLintTests` 失败当数字 DOW 回到应使用名称的 YAML。CI 命令与仓库惯用一致：`python -m unittest discover -s tests -v`（也可只跑 `tests.test_cron_dow tests.test_issue69_scripts`）。
6. **S2.A4 warn only**：checker 默认 exit 0；`--strict` 才因数字 DOW 退出 2。`doctor.py` 不读 workflow DB，不因数字星期 fail。
7. **S3.A3 dry-run apply**：`docs/issue-69/apply.sh --from-yaml docs/issue-69/examples/numeric-dow-sample.yaml` 打印改写后的 `MON-FRI` 并写 `DRY-RUN`，不调用 `buzz workflows update`。无 `ISSUE69_I_UNDERSTAND_LIVE=yes` 的 `--live` 退出 2；CST 08:58–09:02（`ISSUE69_NOW_CST=0859`）拒绝。
8. **S3.A5 本地 SQL 彩排**：有 `initdb` 时 `docs/issue-69/test/local-test.sh` 跑 `backup` → `verify-before` → `rehearse`（`BEGIN`…断言 1/7…`ROLLBACK`），库 hash 回到 backup。无 `initdb` 时该条 **not_run**（不是 skip 活机）。

## 活机（当前 Desktop/ACP 0/9 → blocked）

不得重拉 Desktop。ACP 恢复到 9/9 后由 Hogan 按 runbook 执行；未执行不得标 pass。

1. **S1.A2 第一个周五 fire**：`f5cc62c0` 在处理后第一个周五 09:00 CST 的 `scheduled_workflow_fires` 有 1 条。当天 Mac 休眠记「未知（休眠）」，仍是 blocked/未知，不是 skip。
2. **S1.A3 第一个周日 fire**：同一 workflow 当天 0 条（休眠同样记未知）。
3. **S2 活机 list**：`buzz workflows list` 交给 `check-numeric-dow.py`；`f5cc62c0` 在 apply 后应为 0 条数字 DOW warn。
4. **S3.A1 backup**：`run.sh backup` 整行备份目标 workflows 行 + 该 d_tag 的 30620 + 全表 8 行。
5. **S3.A2 生产预演**：`run.sh rehearse` 断言只改 1 条、其余 7 条不变，然后 `ROLLBACK`。
6. **S3.A3 live apply**：避开 CST 08:58–09:02，`ISSUE69_I_UNDERSTAND_LIVE=yes ./run.sh apply --live`（owner update，只改 cron）。
7. **S3.A4 rollback 可重放**：owner 重发 backup YAML 后 definition 与备份逐字节一致。本步只在 apply 后需要回退时跑；未 apply 前标 blocked（差 ACP≥9），不是 skip。
