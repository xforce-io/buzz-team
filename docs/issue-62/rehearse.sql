-- #62 rehearse（Knox P2-3）：生产上真执行前的彩排，结果一律 ROLLBACK，库不变。
--   BEGIN → 快照（temp 表）→ 校验 backup.json 仍与现状一致 → apply.sql（含全部计数断言）
--   → rollback.sql（按 backup.json 全行还原）→ 与快照逐列比对（workflows 全表、社区内全部 30620）→ ROLLBACK
-- 在真实触发器（含 community_write_fence）、约束、READ COMMITTED 下运行；任何一步失败 psql 立即退出（ON_ERROR_STOP），
-- 服务器回滚未提交事务。彩排不通过，不做真删除。
-- 运行：psql -X -v ON_ERROR_STOP=1 -v backup="$(cat before/backup.json)" -f rehearse.sql   （不要加 -1；生产经 run.sh rehearse）
\ir targets.sql
\if :{?backup}
\else
  \echo 'rehearse.sql: missing -v backup=<backup.json content>'
  SELECT 1/0 AS missing_backup_variable;
\endif
BEGIN;
\echo '== #62 rehearse: role / time / isolation =='
SELECT current_user AS role, to_char(clock_timestamp() AT TIME ZONE 'Asia/Shanghai', 'YYYY-MM-DD HH24:MI:SS') || ' CST' AS rehearse_time_cst,
       current_setting('transaction_isolation') AS isolation, current_setting('transaction_read_only') AS read_only,
       current_setting('session_replication_role') AS repl_role;
DO $env$
DECLARE n int;
BEGIN
  IF current_setting('transaction_isolation') <> 'read committed' THEN RAISE EXCEPTION '#62 rehearse abort: isolation %', current_setting('transaction_isolation'); END IF;
  IF current_setting('transaction_read_only') <> 'off' THEN RAISE EXCEPTION '#62 rehearse abort: read-only transaction'; END IF;
  IF current_setting('session_replication_role') <> 'origin' THEN RAISE EXCEPTION '#62 rehearse abort: triggers disabled (session_replication_role)'; END IF;
  SELECT count(*) INTO n FROM pg_trigger WHERE tgenabled = 'O' AND NOT tgisinternal
     AND tgrelid IN ('public.workflows'::regclass, 'public.events'::regclass);
  RAISE NOTICE '#62 rehearse: % enabled user triggers on workflows/events (incl. community_write_fence_*)', n;
END
$env$;

CREATE TEMP TABLE r62_before_wf ON COMMIT DROP AS SELECT * FROM workflows;
CREATE TEMP TABLE r62_before_ev ON COMMIT DROP AS
  SELECT * FROM events WHERE community_id = current_setting('r62.community')::uuid AND kind = 30620;
CREATE TEMP TABLE r62_before_child ON COMMIT DROP AS
  SELECT (SELECT count(*) FROM workflow_runs) AS runs, (SELECT count(*) FROM workflow_approvals) AS approvals,
         (SELECT count(*) FROM scheduled_workflow_fires) AS fires;
SELECT set_config('r62.backup', :'backup', false) IS NOT NULL AS r62_backup_loaded \gset

-- backup.json 必须与现状全行一致（否则备份已过期，停手重做 backup）。
DO $fresh$
DECLARE
  b json := current_setting('r62.backup')::json;
  n bigint;
BEGIN
  SELECT count(*) INTO n FROM json_array_elements(b->'workflows_all') r, json_populate_record(NULL::workflows, r) p
   WHERE NOT EXISTS (SELECT 1 FROM workflows w WHERE w.community_id = p.community_id AND w.id = p.id AND ROW(w.*) IS NOT DISTINCT FROM ROW(p.*));
  IF n <> 0 OR json_array_length(b->'workflows_all') <> (SELECT count(*) FROM workflows) THEN
    RAISE EXCEPTION '#62 rehearse abort: backup.workflows_all stale (% rows differ)', n;
  END IF;
  SELECT count(*) INTO n FROM json_array_elements(b->'events_30620_all') r, json_populate_record(NULL::events, r) p
   WHERE NOT EXISTS (SELECT 1 FROM events e WHERE e.community_id = p.community_id AND e.created_at = p.created_at AND e.id = p.id
                       AND ROW(e.*) IS NOT DISTINCT FROM ROW(p.*));
  IF n <> 0 OR json_array_length(b->'events_30620_all') <> (SELECT count(*) FROM r62_before_ev) THEN
    RAISE EXCEPTION '#62 rehearse abort: backup.events_30620_all stale (% rows differ)', n;
  END IF;
  RAISE NOTICE '#62 rehearse: backup.json matches live state (workflows %, 30620 rows %)',
    json_array_length(b->'workflows_all'), json_array_length(b->'events_30620_all');
END
$fresh$;

\echo '== rehearse step 1/2: apply.sql =='
\ir apply.sql
\echo '== rehearse step 2/2: rollback.sql =='
\ir rollback.sql

-- 逐列比对：列清单来自 information_schema.columns；按主键全外连接，任一列 IS DISTINCT FROM 即失败。
DO $cmp$
DECLARE
  col record;
  n   bigint;
  checked int := 0;
BEGIN
  IF (SELECT count(*) FROM workflows) <> (SELECT count(*) FROM r62_before_wf) THEN RAISE EXCEPTION '#62 rehearse FAIL: workflows row count changed'; END IF;
  FOR col IN SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'workflows' ORDER BY ordinal_position LOOP
    EXECUTE format('SELECT count(*) FROM workflows w FULL JOIN r62_before_wf b ON w.community_id = b.community_id AND w.id = b.id
                     WHERE w.id IS NULL OR b.id IS NULL OR w.%1$I IS DISTINCT FROM b.%1$I', col.column_name) INTO n;
    IF n <> 0 THEN RAISE EXCEPTION '#62 rehearse FAIL: workflows.% differs in % rows after rollback', col.column_name, n; END IF;
    checked := checked + 1;
  END LOOP;
  RAISE NOTICE '#62 rehearse: workflows % columns x % rows identical to snapshot', checked, (SELECT count(*) FROM r62_before_wf);
  checked := 0;
  FOR col IN SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'events' ORDER BY ordinal_position LOOP
    EXECUTE format('SELECT count(*) FROM (SELECT * FROM events WHERE community_id = current_setting(''r62.community'')::uuid AND kind = 30620) e
                     FULL JOIN r62_before_ev b ON e.community_id = b.community_id AND e.created_at = b.created_at AND e.id = b.id
                     WHERE e.id IS NULL OR b.id IS NULL OR e.%1$I IS DISTINCT FROM b.%1$I', col.column_name) INTO n;
    IF n <> 0 THEN RAISE EXCEPTION '#62 rehearse FAIL: events.% differs in % rows after rollback', col.column_name, n; END IF;
    checked := checked + 1;
  END LOOP;
  RAISE NOTICE '#62 rehearse: events(kind 30620) % columns x % rows identical to snapshot', checked, (SELECT count(*) FROM r62_before_ev);
  IF (SELECT ROW(runs, approvals, fires) FROM r62_before_child) IS DISTINCT FROM
     ROW((SELECT count(*) FROM workflow_runs), (SELECT count(*) FROM workflow_approvals), (SELECT count(*) FROM scheduled_workflow_fires)) THEN
    RAISE EXCEPTION '#62 rehearse FAIL: runs/approvals/fires counts changed';
  END IF;
  RAISE NOTICE '#62 REHEARSAL PASS (apply asserts + full-row rollback + column-by-column equality); rolling back';
END
$cmp$;
ROLLBACK;
\echo '#62 rehearse finished: transaction rolled back, database unchanged'
