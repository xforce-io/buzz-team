# L1 产品设计：定时任务星期段改用名称

状态：**Approved**（peng 经 Jenny 2026-10-21 ~23:46 Asia/Shanghai，Issue #69 确认评论）。本文件映射 Issue S1–S3，不改上游。

## 1. 确认来源

| 项 | 值 |
|---|---|
| 来源 | peng 经 Jenny：「buzz-team按照你的建议推进」 |
| 采纳 | Scout L1 Draft **选项 A** + 数字星期 **warn** |
| 记录 | [Issue #69 确认评论](https://github.com/xforce-io/buzz-team/issues/69#issuecomment)（2026-10-21） |
| 根因旁证 | Hogan 2026-10-02 周五：`f5cc62c0` 无 fire，同分钟每日 cron `97152434` 有 fire |

开放问题裁定：

| # | 问题 | 裁定 |
|---|---|---|
| 1 | A / B / C | **A**：`0 1 * * MON-FRI` |
| 2 | 「工作日」 | **周一到周五**；中国法定节假日/调休不在 cron 能力内，接受 |
| 3 | 现网执行身份 | 沿用 **#38 运维脚本 + owner `buzz workflows update`**（human:required） |
| 4 | #62 组合 | **owner 发 update；SQL 只做备份 / 断言 / 预演** |
| 5 | 防护力度 | **只提示（warn）**；仓库模板 lint 进测试/CI。不把数字星期写成 doctor fail |
| 6 | #38 YAML | **本票**改 `docs/issue-38/{before,after}/workflow.yaml` |

## 2. 问题

本地 relay（`ghcr.io/block/buzz:sha-c507a4d`）用 cron 0.16.0。星期段数字是 **1=周日 … 7=周六**，不是常见的 0/7=周日、1=周一。`0 1 * * 1-5` 实际是周日到周四 09:00 CST。描述写「工作日」，周五不触发、周日会触发。

Hogan 2026-10-02（周五）只读：对照每日 09:00 的 `97152434` 有 fire，`f5cc62c0` 无记录；Mac 09:00 醒着。与 sun=1 推断一致。

## 3. 目标与非目标

目标：

- 站会开窗唤醒按周一到周五 CST 09:00 触发。
- 仓库模板不再写出数字星期段。
- 再写出数字星期时，只读检查能列出并解释 CST 星期几（warn，不判健康失败）。
- 现网改定义可备份、预演、按行数断言、可回退。本 PR 只交付脚本与文档；Hogan 在 ACP 恢复后执行。

非目标：

- 修改上游 block/buzz（cron 库、`normalize_cron`、Desktop 每周选择器）。
- 中国法定节假日 / 调休。
- 元宝 relay、#68 休眠漏触发、#54/#47/#38 活机 apply。
- 重拉 Desktop / ACP；向生产库写入。
- 把 workflow DB 读进 `buzz_team.doctor`（doctor 只检查 Desktop 库存 + Seatbelt）。

## 4. Stories

### S1. 站会开窗唤醒按工作日触发

对象：workflow `f5cc62c0-3756-419e-8a3f-8e694df2e93e`（周衡，炼丹房）。cron 改为 `0 1 * * MON-FRI`。描述仍表示工作日 09:00 CST。

仓库侧：改 #38 before/after 模板，避免 #38 脚本把 `1-5` 写回。

活机侧：owner update。14 次下一触发与周五/周日 fire 核对需要 Mac + relay，**ACP 0/9 HOLD 期间 BLOCKED**。不要为此重拉 Desktop。

### S2. 数字星期 cron 会被提示

仓库：纯函数检测 5/7 段 cron 的 DOW 数字 token；测试扫描 #38/#69 模板，残留数字即失败。

活机：`docs/issue-69/check-numeric-dow.py` 读 YAML 或 `workflows list` JSON，warn 并打印 cron 0.16 的 CST 解释。默认 exit 0；`--strict` 才非零。不接入 doctor，不读生产库。

### S3. 改现网定义可预演、可回退

#62 契约：整行备份、机器断言只改 1 条定义、其余 7 条不变、生产/本地 `BEGIN…ROLLBACK` 预演、回退可重放。真写入走 owner update，不 SQL 改 definition（30620 带签名）。避开 CST 08:58–09:02。脚本默认 dry-run；活机 apply 仍 human:required。

## 5. L1.8 验收

| ID | Story | 验收 | 本 PR | 活机 |
|---|---|---|---|---|
| S1.A1 | S1 | 用本仓算法从 2026-10-01 10:30 CST 起算 14 次：`MON-FRI` 全是周一到周五 09:00 CST；`1-5` 对照为周日到周四（0 次周五、3 次周日） | 测试锁死 | 算法通过即视为仓库侧 pass |
| S1.A2 | S1 | 处理后第一个周五 `scheduled_workflow_fires` 有 1 条 | 脚本就位 | **BLOCKED**（需 Mac+relay，ACP≥9） |
| S1.A3 | S1 | 处理后第一个周日 0 条（当天 Mac 休眠记「未知（休眠）」） | 脚本就位 | **BLOCKED** |
| S1.A4 | S1 | `docs/issue-38/{before,after}/workflow.yaml` 与 `docs/issue-69/after/workflow.yaml` 为 `0 1 * * MON-FRI` | 本 PR | — |
| S2.A1 | S2 | 数字星期样例提示 1 条，并给出 CST 星期解释 | 测试 + checker | 活机 list 输入在 ACP 恢复后跑 |
| S2.A2 | S2 | `MON-FRI` 或 `*` 提示 0 条 | 测试 + checker | 同上 |
| S2.A3 | S2 | 应使用名称的模板若残留数字 DOW，CI 失败 | 测试 | — |
| S2.A4 | S2 | 防护只 warn；doctor 不因数字星期 fail；checker 默认 exit 0 | 实现约束 | 不把 warn 升级为 health fail |
| S3.A1 | S3 | 整行备份 workflows 目标行 + 该 d_tag 的 30620 + 全表 8 行 | 脚本 | Hogan 执行 backup |
| S3.A2 | S3 | 预演断言只改 1 条、其余 7 条 hash 不变，然后 `ROLLBACK` | SQL rehearse | 生产库预演 human:required |
| S3.A3 | S3 | apply 默认 dry-run；真更新需 `ISSUE69_I_UNDERSTAND_LIVE=yes` 且不在 08:58–09:02 CST | 脚本 | Hogan；本 agent 不执行 |
| S3.A4 | S3 | 回退 = owner 原样重发备份 YAML；回退后 definition 与备份逐字节一致 | 脚本 | Hogan |
| S3.A5 | S3 | 本地可用同一套 SQL 在 `BEGIN…ROLLBACK` 下彩排 | 脚本形状测试 | 有 postgres 时跑 local-test |

活机 S1.A2 / S1.A3 在 Desktop/ACP 不可用时不得标 pass。下一步：ACP 恢复后由 Hogan 按 `docs/issue-69/README.md` 执行，不在本 PR 重拉 Desktop。

## 6. 对席位的影响

周五恢复 09:00 开窗唤醒；周日不再唤醒周衡。其余 7 条定义为每天/`*`，不受数字星期影响。

## 7. 关联

#69、#38、#62、#68。上游 Desktop 选择器仍按 0=周日写数字，可能再次引入数字星期 —— 这是 S2 存在的原因，不在本票修上游。
