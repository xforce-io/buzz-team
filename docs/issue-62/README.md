# #62 实例清理：删除残留 workflow（1 行 + 9 条 kind:30620 定义）

对象：本机生产 relay `ws://127.0.0.1:3000`（`buzz-prod-relay-1`，镜像 `ghcr.io/block/buzz:sha-c507a4d`），库在 docker 容器 `buzz-prod-postgres-1`（PostgreSQL 17.11，库 `buzz`，psql role `buzz`：superuser、bypassrls）。

## 授权

- **peng 2026-10-01 00:05 CST（经 Jenny）**：
  > 2026-10-01 00:05 peng 授权（仅限两项实例清理，一次性）：……(2) 残留 workflow 037a83e7…、107226dd…：peng 同意清理——Scout 开票，先只读核对它们确实已失效且无任务引用，把要删的具体记录与回滚方式贴进票，经 Knox 审后由 Hogan 执行删除并留证。限制：不碰其他席位、thin-bin pin、managed-agents.json、channel_wake、代理与 upstream block/buzz；不在 #57 续跑期间做活机改动（等 Jenny 通知 #57 结束）。
- **peng 2026-10-01 00:35 CST（经 Jenny）扩大范围**：#62 列出的另外 7 条孤儿定义（秦牧 3、周衡 #38 smoke 3、方维旧站会唤醒 1）一并清理，同一 PR，全部满足 Knox 的 P2 要求。
- **Knox 00:40 补充**：每个目标同时按 id 和 owner pubkey 精确匹配；总数断言 workflows 9 → 8、可见 30620 17 → 8，剩下 8 条必须恰为 8 个保留 workflow 的定义。
- #57 已结束（verdict B，Knox PASS），不再等待。执行仍需：**Knox 对本 PR PASS → peng 合入 → Hogan 按下文执行**。Scout 不执行 apply/rehearse。

## 目标（唯一来源：`targets.sql`）

community `14a17e2d-40ae-4182-86c1-7dde01da0f03`。9 个 d_tag 都没有 workflow_runs / approvals / fires，cron 均为 2 月 30/31 日（永不触发）或早已被替换（0ec65559）。

| # | d_tag（workflow id） | 当前可见 30620 event id | owner | 说明 | workflows 行 |
|---|---|---|---|---|---|
| 1 | `107226dd-c569-470a-987a-3b9223b20b77` | `2a6c62098ea6f61fa1a866e77b8f808cfc462a868d36065631e486593b8c5ed2` | 裴昭 `265e4fc1…` | probe-disabled 探针 | **有**（status=active, enabled=true, definition_hash `913a972b…`）→ DELETE |
| 2 | `037a83e7-ebfc-4080-be20-b875cd23d4bc` | `9dd10e17f1f1c324ded98ca480d6bfc0a6c6b33e3d248c83b816d50f46227b6b` | 周衡 `51fb6cd8…` | #38 smoke 临时 | 无（09-24 kind:5 已删） |
| 3 | `0ec65559-05de-4487-9154-72afe030422f` | `e1c40066b5992077a14a706930c1646a2aa23d9f9803be1cc203812ede327f9f` | 方维 `db595575…` | 旧「站会开窗唤醒」（现役是周衡的 f5cc62c0，不动） | 无 |
| 4 | `33e8caad-530b-4f71-82bf-d4da55b49cce` | `e17964d952818211ca71c7fb8874f6fb59fabaf49304ce286db0214d0f1091c6` | 秦牧 `7b7afbdd…` | probe-schema（enabled:false） | 无 |
| 5 | `cf9e7de9-70ee-4691-af8e-6b48151938b2` | `763c01806f798a7771576fb08f15f417f744f96f17755f4e3484736b94c8538d` | 秦牧 `7b7afbdd…` | probe-schema（enabled:false） | 无 |
| 6 | `33b7bd61-0741-4786-b9f3-e85653e7e424` | `8926aa682d5eeb8b30fb08c4397df3fb89a7322d5638f04485731af8e1d68a56` | 秦牧 `7b7afbdd…` | probe-mention（enabled:false） | 无 |
| 7 | `ce80d151-114f-447a-a496-5f6fcc667c9f` | `8cba8571e46618d9283d501c0db0d70018b32363fd7fda9eaf90371faa9ff47e` | 周衡 `51fb6cd8…` | #38 smoke | 无 |
| 8 | `38ad49f3-b5c5-4f2e-a5ac-e70fda814c03` | `856fc79b37e7465a5291086f2802afdb19a2139799063c30682f8b0ad5bd1a43` | 周衡 `51fb6cd8…` | #38 smoke（UPDATED 版） | 无 |
| 9 | `910066ef-e737-4d7b-84e6-8c99652e1d55` | `1360986d5fede95c09b892bccc80327e5951099c5848b94a18abf46a73dd3a56` | 周衡 `51fb6cd8…` | #38 smoke | 无 |

变更：DELETE 1 行（#1，按 id + owner + definition_hash），软删 9 条事件（`deleted_at = NOW()`，按主键 (community_id, created_at, id) + pubkey + d_tag）。事件不物理删除，签名原样保留。

保留（不动）：workflows 其余 8 行 f5cc62c0、7d90ca75、50d27eb7、2d75251c、97152434、619b47c8、cd608a18、7c3362d0 及其各 1 条定义；这 9 个 d_tag 早已软删的历史版本（42a59e9c、1f56a781、ed1168ec、9edc191f、a5bc4881）不变。

## 只读核对结果（2026-10-01 00:26–00:50 CST，`PGOPTIONS=-c default_transaction_read_only=on`，role `buzz`）

- **总数**：workflows 9 行（全部在上述 community）；社区内可见 30620 共 17 条 = 9 个 workflow 各 1 条自己的定义（d_tag=id 且 pubkey=owner，逐行核对均为 1）+ 上表 #2–#9 的 8 条孤儿。与 Knox 给出的 9/17 一致。
- **workflows 列**（information_schema.columns）：community_id uuid、id uuid、name varchar(255)、owner_pubkey bytea、channel_id uuid、definition jsonb、definition_hash bytea、status workflow_status(active/disabled/archived)、enabled bool、created_at timestamptz、updated_at timestamptz。无生成列。
- **events 列**：community_id uuid、id bytea、pubkey bytea、created_at timestamptz、kind int4、tags jsonb、content text、sig bytea、received_at timestamptz、channel_id uuid、deleted_at timestamptz、d_tag text、not_before int8、delivered_at int8、**search_tsv tsvector GENERATED ALWAYS STORED**（kind 30620 恒为 NULL）。按 created_at 范围分区（8 个分区，各有 `events_p*_pkey`）；主键 (community_id, created_at, id)。
- **指向 workflows 的外键**（3 个，全部 ON DELETE CASCADE）：workflow_runs、workflow_approvals、scheduled_workflow_fires 的 (community_id, workflow_id)。**名字含 workflow 的列**（4 个）：scheduled_workflow_fires.workflow_id / workflow_run_id、workflow_approvals.workflow_id、workflow_runs.workflow_id。9 个目标 id 在这 4 列中均为 **0 行**；workflows.definition 文本中出现任一目标 id 的行 0；events.tags 中出现目标 id 的只有各自的 30620 与 kind:5。`verify.sql` 每次运行都从 information_schema 重新列出并断言 0。
- **触发器**：workflows 上 `community_write_fence_workflows`；events 上 `community_write_fence_events`、`events_created_at_floor`（仅 created_at/channel_id 更新，GUC `buzz.created_at_floor` 未设置 → 空操作）、`trg_events_purge_soft_deleted_*`（只处理 kind 30003/30078，与 30620 无关），其余只在 INSERT/DELETE 时触发。`community_write_fence` 要求 READ COMMITTED，community `deletion_state=active`、generation 0。
- **#38/#42 引用核对（Knox 00:40）**：在 main 的 `docs/issue-38`、`docs/issue-42` 里 grep 9 个 d_tag 和 9 个 event id。#38 脚本操作的是 `WF_ID=f5cc62c0…`（`scripts/common.sh:16`，保留），smoke 脚本每次新建临时 id。周衡 3 条 smoke 定义（ce80d151、38ad49f3、910066ef）只出现在历史证据快照 `docs/issue-38/smoke/list-{before,after}.json`、`list-diff.txt` 里；037a83e7 只出现在 `docs/issue-38/smoke/` 的历史证据里。脚本与 #42 文档 0 命中，event id 0 命中。**#38/#42 的改写计划都不引用它们。**

## 方法（Knox 已认可方向）

照搬上游 block/buzz#7735（5079c77）`delete_workflow_in_transaction`：同一事务内删 workflow 行并把该坐标的 30620 设 `deleted_at = NOW()`，事先取与上游相同的 `pg_advisory_xact_lock(event_replacement_lock_key(community, 30620, pubkey, d_tag))`（FNV-1a，key 写在 `targets.sql`，CI 复算），与 relay 的并发发布互斥。不走 CLI 的原因见 #62 正文（c507a4d 的删除不软删定义；kind:5 需要席位私钥）。

- `apply.sql`：一个 DO 块完成全部前置断言 → 变更 → 后置断言；每个 DELETE / UPDATE 之后 `GET DIAGNOSTICS n = ROW_COUNT`，`n <> 1` 即 `RAISE EXCEPTION`，事件合计 `<> 9` 也中止；后置断言 workflows = 8、可见 30620 = 8、且 8 条与 8 行一一对应（d_tag=id、pubkey=owner）。以 `psql -X -v ON_ERROR_STOP=1 -1` 运行，任一失败整个事务回滚。
- `backup.sql`：只读，`row_to_json(w.*)` / `row_to_json(e.*)` 全行备份：目标 workflow 行、9 条目标事件、这 9 个 d_tag 的全部历史版本、完整 workflows 表、社区内全部 30620 行，外加 information_schema 列清单与总数。
- `rollback.sql`：`INSERT … SELECT * FROM json_populate_record(NULL::workflows, <备份行>)`；事件行 `UPDATE events SET (<全部非生成列>) = (SELECT … FROM json_populate_record(NULL::events, <备份行>))`（列清单取自 information_schema；search_tsv 为生成列由库重算）。每行还原后与备份逐列比较（`ROW(x.*) IS NOT DISTINCT FROM ROW(p.*)`），数量不符即中止。
- `rehearse.sql`：`BEGIN` → temp 表快照 → 校验 backup.json 与现状全行一致 → `\ir apply.sql` → `\ir rollback.sql` → 按 information_schema 列清单对 workflows 全表、社区内全部 30620 行逐列 `IS DISTINCT FROM` 比较 → `ROLLBACK`。真实触发器、约束、READ COMMITTED 下运行（开头断言 isolation、`session_replication_role=origin`、非只读）。
- `verify.sql`：只读；`phase=before` / `after` 两套断言（见文件头）+ 外键 / workflow 列引用检查（证据表 + 0 行断言）。
- `run.sh`：执行入口。内联 `\ir`，经 `docker exec -i buzz-prod-postgres-1 psql -U buzz -d buzz -X -v ON_ERROR_STOP=1` 送入；只读步骤加 `PGOPTIONS=-c default_transaction_read_only=on`；每步日志带 CST 时间、脚本 sha256、backup.json sha256，SQL 输出里有 `current_user`。`apply` 只有在同一份 backup.json 上 verify-before 与 rehearse 都通过后才会运行，且不允许重复运行。

## Hogan 执行顺序（在已合入 main 的 buzz-team 检出目录，Mac 上）

证据目录默认 `~/lab/buzz/evidence/issue-62/`（可用 `R62_EVIDENCE` 覆盖）。

```bash
cd <buzz-team 检出>/docs/issue-62
./run.sh backup          # 只读 → before/backup.json + backup.json.sha256
./run.sh verify-before   # 只读：9/17、逐目标精确匹配、backup 新鲜、引用检查全 0 → VERIFY-BEFORE PASS
./run.sh rehearse        # 彩排：apply → rollback → 逐列比对 → ROLLBACK → REHEARSAL PASS
./run.sh apply           # 真执行：psql -1，全部计数断言 → "#62 apply OK"
./run.sh verify-after    # 只读：8/8、一一对应、目标消失、非目标逐列不变 → VERIFY-AFTER PASS
./run.sh list            # 官方只读检查：buzz workflows list（炼丹房应 1 条，秘书处应 7 条，目标 0）
```

rehearse 与 apply 之间不要做别的事，也不要间隔太久；中途任何步骤失败都不要继续。`list` 需要能读这两个频道的身份：与 #38 smoke 相同的方式设置 `BUZZ_PRIVATE_KEY`（`BUZZ_RELAY_URL` 默认 `ws://127.0.0.1:3000`），只运行 `list`，不写。

等价的裸命令（不用 run.sh 时；SQL 文件需先把 `\ir` 内联，run.sh 已做）：`docker exec -i buzz-prod-postgres-1 psql -U buzz -d buzz -X -v ON_ERROR_STOP=1 -1 -f - < apply（已内联）`。

## 停止条件（出现任何一条就停，不执行或不继续，回报 Scout/Knox）

- `verify-before` 不 PASS：总数不是 9/17、任一目标不匹配（id/owner/hash/updated_at/事件主键）、backup 与现状不一致、任一引用列非 0、出现清单外的可见孤儿定义。
- `rehearse` 不是 `REHEARSAL PASS`（包括 community_write_fence 拒绝、isolation 不是 READ COMMITTED、任一列比对不同）。**彩排不通过，不做真删除。**
- `apply` 报 `#62 abort`：事务已整体回滚，库不变；不要重试，先回报。
- `verify-after` 不 PASS：立即 `./run.sh rollback`，再 `./run.sh verify-before`（用同一份 backup.json，`run.sh` 会把旧日志覆盖，请先另存）确认恢复，回报。
- `list` 仍列出目标：**不重启 relay/colima**，如实回报（relay 查询直接读库，仍列出说明有未预期的缓存或数据，需要另查）。

## 回滚

```bash
./run.sh rollback        # psql -1；按 before/backup.json 全行还原 1 行 + 9 条事件，逐列校验，总数回到 9/17
```

前置：目标 workflow 行不存在、9 个 d_tag 没有可见定义（若 owner 在此期间重新发布过同 d_tag，rollback 会中止，需人工判断）。rehearse 已在生产上把这条回滚完整跑过一次。

## 留证（存 `~/lab/buzz/evidence/issue-62/`，在 #62 回帖摘要）

- `before/backup.json` 与 `backup.json.sha256`；`backup.log`、`verify-before.log`、`rehearse.log`、`apply.log`、`verify-after.log`、`list.log`、`after/list-<channel>.json`。
- 每个日志头有开始时间（CST）、主机、操作者、脚本 sha256、backup.json sha256；SQL 输出里有 psql role（`current_user` / `session_user`）、事务 isolation 和执行时间（CST）。回帖时写明 role 和 apply 的 CST 时间。
- S3：执行后下一次到期的定时任务（如 `7c3362d0…` 每日 08:45 CST）在 `workflow_runs` 有新记录。

## 已知行为（Knox P3）

- **软删不发 kind:5**：直接改库不产生删除事件。owner 若以后用同一 d_tag 发布更新的 30620，relay 会按正常路径重建定义和 workflow 行。这些都是停用探针和 smoke 残留，owner 不会再发布，可接受。
- **重发同一签名事件不会把 `deleted_at` 置回 NULL**（只读查上游 c507a4d 源码）：30620 走 `command_executor::handle_workflow_def` → `persist_command_event` → `replace_parameterized_event_in_transaction`（`crates/buzz-db/src/store/replaceable.rs`）。可见版本查询带 `deleted_at IS NULL`，软删后为空；带 `expected-revision` 标签的事件（2a6c6209、9dd10e17、856fc79b）直接返回 `RevisionMissing` 被拒；其余走 `INSERT … ON CONFLICT DO NOTHING`，与主键 (community_id, created_at, id) 冲突，影响 0 行，返回 `Duplicate`，handler 在 `upsert_workflow` 之前返回 "duplicate: already processed"，workflow 行也不会重建。c507a4d 全库没有 `SET deleted_at = NULL`，库里也没有会清空 deleted_at 的触发器。本地测试第 12 项实测了这条插入路径。
- **relay 进程内缓存**：上游删除后会调用 `invalidate_channel_workflows`，直接改库不会。107226dd 的 cron 永不到期，孤儿定义没有 workflow 行，不影响执行；不重启 relay。

## 测试

`test/local-test.sh`：临时 PostgreSQL 集群，`test/schema.sql`（生产 workflows/events/引用表的列、约束、触发器与真实 fence 函数）+ `test/fixture.sql`（10 条目标行为生产只读快照原样；总数同生产 9/17），经 `run.sh` 跑完整流程与反例（改动中途拒绝、计数不符、fence、isolation、过期备份、重复执行等），共 24 项检查，最后库回到初始状态（全部行 md5 一致）。`tests/test_issue62_sql.py` 在 CI（`.github/workflows/test.yml` 的 unittest）中运行：清单与 lock key 复算、脚本形状、shellcheck、以及上述本地 PostgreSQL 全流程（CI 上找不到 initdb 时判失败，不跳过）。
