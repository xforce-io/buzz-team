-- #62 verify（只读）。-v phase=before|after -v backup="$(cat before/backup.json)"
-- 运行：PGOPTIONS='-c default_transaction_read_only=on' psql -X -v ON_ERROR_STOP=1 -v phase=before -v backup=... -f verify.sql
-- before：总数 9/17、逐目标精确匹配（id + owner）、backup.json 与现状全行一致、引用检查全 0。
-- after ：总数 8/8、剩余 8 条可见定义与 8 个 workflow 一一对应、目标全部消失且其余列不变、非目标行逐列不变、引用检查全 0。
\ir targets.sql
\if :{?phase}
\else
  \echo 'verify.sql: missing -v phase=before|after'
  SELECT 1/0 AS missing_phase_variable;
\endif
\if :{?backup}
\else
  \echo 'verify.sql: missing -v backup=<backup.json content>'
  SELECT 1/0 AS missing_backup_variable;
\endif
SELECT set_config('r62.phase', :'phase', false) IS NOT NULL AS r62_phase_loaded \gset
SELECT set_config('r62.backup', :'backup', false) IS NOT NULL AS r62_backup_loaded \gset
\echo '== #62 verify: role / time / read-only =='
SELECT current_setting('r62.phase') AS phase, current_user AS role,
       to_char(clock_timestamp() AT TIME ZONE 'Asia/Shanghai', 'YYYY-MM-DD HH24:MI:SS') || ' CST' AS verify_time_cst,
       current_setting('transaction_read_only') AS read_only;

\echo '== evidence: FKs referencing workflows (information_schema) =='
SELECT tc.table_name, string_agg(kcu.column_name, ',' ORDER BY kcu.ordinal_position) AS fk_columns, tc.constraint_name, rc.delete_rule
  FROM information_schema.referential_constraints rc
  JOIN information_schema.table_constraints tc ON tc.constraint_schema = rc.constraint_schema AND tc.constraint_name = rc.constraint_name
  JOIN information_schema.key_column_usage kcu ON kcu.constraint_schema = tc.constraint_schema AND kcu.constraint_name = tc.constraint_name
  JOIN information_schema.table_constraints pk ON pk.constraint_schema = rc.unique_constraint_schema AND pk.constraint_name = rc.unique_constraint_name
 WHERE pk.table_schema = 'public' AND pk.table_name = 'workflows'
 GROUP BY tc.table_name, tc.constraint_name, rc.delete_rule ORDER BY 1;
\echo '== evidence: columns whose name contains "workflow" (information_schema) =='
SELECT c.table_name, c.column_name, c.data_type
  FROM information_schema.columns c JOIN information_schema.tables t USING (table_schema, table_name)
 WHERE c.table_schema = 'public' AND t.table_type = 'BASE TABLE' AND c.column_name ILIKE '%workflow%' ORDER BY 1, 2;

\echo '== reference check: rows pointing at any target workflow id (must all be 0) =='
DO $refs$
DECLARE
  ids   text[] := ARRAY(SELECT t->>'d_tag' FROM jsonb_array_elements(current_setting('r62.ev')::jsonb) t);
  col   record;
  n     bigint;
  bad   bigint := 0;
  k     int := 0;
BEGIN
  -- 1) 每个指向 workflows 的外键（按外键列 workflow_id 一类；community_id 列跳过）
  -- 2) 所有名字含 workflow 的列（含非外键列，如 scheduled_workflow_fires.workflow_run_id）
  FOR col IN
    SELECT DISTINCT c.table_name, c.column_name
      FROM information_schema.columns c JOIN information_schema.tables t USING (table_schema, table_name)
     WHERE c.table_schema = 'public' AND t.table_type = 'BASE TABLE'
       AND (c.column_name ILIKE '%workflow%'
            OR (c.table_name, c.column_name) IN (
                 SELECT kcu.table_name, kcu.column_name
                   FROM information_schema.referential_constraints rc
                   JOIN information_schema.key_column_usage kcu ON kcu.constraint_schema = rc.constraint_schema AND kcu.constraint_name = rc.constraint_name
                   JOIN information_schema.table_constraints pk ON pk.constraint_schema = rc.unique_constraint_schema AND pk.constraint_name = rc.unique_constraint_name
                  WHERE pk.table_name = 'workflows' AND kcu.column_name <> 'community_id'))
     ORDER BY 1, 2
  LOOP
    EXECUTE format('SELECT count(*) FROM %I WHERE %I::text = ANY($1)', col.table_name, col.column_name) INTO n USING ids;
    RAISE NOTICE '#62 refs %.% -> % rows', col.table_name, col.column_name, n;
    bad := bad + n; k := k + 1;
  END LOOP;
  IF k < 4 THEN RAISE EXCEPTION '#62 verify FAIL: only % reference columns found (expected >= 4)', k; END IF;
  IF bad <> 0 THEN RAISE EXCEPTION '#62 verify FAIL: % referencing rows for target ids', bad; END IF;
  RAISE NOTICE '#62 refs OK: % columns checked, 0 rows for all 9 target ids', k;
END
$refs$;

DO $state$
DECLARE
  phase text  := current_setting('r62.phase');
  c     uuid  := current_setting('r62.community')::uuid;
  x     jsonb := current_setting('r62.expect')::jsonb;
  wf    jsonb := current_setting('r62.wf')::jsonb;
  ev    jsonb := current_setting('r62.ev')::jsonb;
  b     json  := current_setting('r62.backup')::json;
  n     bigint;
  t     jsonb;
BEGIN
  IF phase NOT IN ('before', 'after') THEN RAISE EXCEPTION '#62 verify: phase must be before|after, got %', phase; END IF;
  IF (b->'meta'->>'issue') IS DISTINCT FROM '62' THEN RAISE EXCEPTION '#62 verify: not a #62 backup'; END IF;

  IF phase = 'before' THEN
    SELECT count(*) INTO n FROM workflows;
    IF n <> (x->>'wf_before')::int THEN RAISE EXCEPTION '#62 verify-before FAIL: workflows=% (want %)', n, x->>'wf_before'; END IF;
    SELECT count(*) INTO n FROM events WHERE community_id = c AND kind = 30620 AND deleted_at IS NULL;
    IF n <> (x->>'live_before')::int THEN RAISE EXCEPTION '#62 verify-before FAIL: live 30620=% (want %)', n, x->>'live_before'; END IF;
    FOR t IN SELECT * FROM jsonb_array_elements(wf) LOOP
      SELECT count(*) INTO n FROM workflows WHERE community_id = c AND id = (t->>'id')::uuid AND owner_pubkey = decode(t->>'owner', 'hex')
         AND definition_hash = decode(t->>'definition_hash', 'hex') AND updated_at = (t->>'updated_at')::timestamptz;
      IF n <> 1 THEN RAISE EXCEPTION '#62 verify-before FAIL: workflow % matched %', t->>'id', n; END IF;
    END LOOP;
    FOR t IN SELECT * FROM jsonb_array_elements(ev) LOOP
      SELECT count(*) INTO n FROM events WHERE community_id = c AND kind = 30620 AND created_at = (t->>'created_at')::timestamptz
         AND id = decode(t->>'id', 'hex') AND pubkey = decode(t->>'pubkey', 'hex') AND d_tag = t->>'d_tag' AND deleted_at IS NULL;
      IF n <> 1 THEN RAISE EXCEPTION '#62 verify-before FAIL: event % matched %', t->>'id', n; END IF;
      SELECT count(*) INTO n FROM events WHERE community_id = c AND kind = 30620 AND d_tag = t->>'d_tag' AND deleted_at IS NULL;
      IF n <> 1 THEN RAISE EXCEPTION '#62 verify-before FAIL: d_tag % has % live definitions', t->>'d_tag', n; END IF;
      SELECT count(*) INTO n FROM workflows WHERE community_id = c AND id::text = t->>'d_tag';
      IF n <> (CASE WHEN wf @> jsonb_build_array(jsonb_build_object('id', t->>'d_tag')) THEN 1 ELSE 0 END) THEN
        RAISE EXCEPTION '#62 verify-before FAIL: d_tag % workflow-row presence unexpected (%)', t->>'d_tag', n;
      END IF;
    END LOOP;
    -- 17 = 9 个 workflow 各 1 条自己的定义（d_tag=id、pubkey=owner）+ 8 条孤儿目标
    SELECT count(*) INTO n FROM workflows w
     WHERE (SELECT count(*) FROM events e WHERE e.community_id = w.community_id AND e.kind = 30620 AND e.deleted_at IS NULL
              AND e.d_tag = w.id::text AND e.pubkey = w.owner_pubkey) <> 1;
    IF n <> 0 THEN RAISE EXCEPTION '#62 verify-before FAIL: % workflows without exactly one own live definition', n; END IF;
    SELECT count(*) INTO n FROM events e WHERE e.community_id = c AND e.kind = 30620 AND e.deleted_at IS NULL
       AND NOT EXISTS (SELECT 1 FROM workflows w WHERE w.community_id = c AND w.id::text = e.d_tag AND w.owner_pubkey = e.pubkey)
       AND NOT EXISTS (SELECT 1 FROM jsonb_array_elements(ev) m WHERE m->>'d_tag' = e.d_tag);
    IF n <> 0 THEN RAISE EXCEPTION '#62 verify-before FAIL: % live orphan definitions outside the manifest', n; END IF;
    -- backup.json 全行 == 现状
    SELECT count(*) INTO n FROM json_array_elements(b->'workflows_all') r, json_populate_record(NULL::workflows, r) p
     WHERE NOT EXISTS (SELECT 1 FROM workflows w WHERE w.community_id = p.community_id AND w.id = p.id AND ROW(w.*) IS NOT DISTINCT FROM ROW(p.*));
    IF n <> 0 OR json_array_length(b->'workflows_all') <> (x->>'wf_before')::int THEN RAISE EXCEPTION '#62 verify-before FAIL: backup.workflows_all stale (%)', n; END IF;
    SELECT count(*) INTO n FROM json_array_elements(b->'events_30620_all') r, json_populate_record(NULL::events, r) p
     WHERE NOT EXISTS (SELECT 1 FROM events e WHERE e.community_id = p.community_id AND e.created_at = p.created_at AND e.id = p.id AND ROW(e.*) IS NOT DISTINCT FROM ROW(p.*));
    IF n <> 0 OR json_array_length(b->'events_30620_all') <> (SELECT count(*) FROM events WHERE community_id = c AND kind = 30620) THEN
      RAISE EXCEPTION '#62 verify-before FAIL: backup.events_30620_all stale (%)', n;
    END IF;
    IF json_array_length(b->'target_workflows') <> 1 OR json_array_length(b->'target_events') <> 9 THEN
      RAISE EXCEPTION '#62 verify-before FAIL: backup targets % / % (want 1/9)', json_array_length(b->'target_workflows'), json_array_length(b->'target_events');
    END IF;
    RAISE NOTICE '#62 VERIFY-BEFORE PASS: workflows 9, live 30620 17 (9 own + 8 orphan targets), 1+9 targets exact, backup fresh';
  ELSE
    SELECT count(*) INTO n FROM workflows;
    IF n <> (x->>'wf_after')::int THEN RAISE EXCEPTION '#62 verify-after FAIL: workflows=% (want %)', n, x->>'wf_after'; END IF;
    SELECT count(*) INTO n FROM events WHERE community_id = c AND kind = 30620 AND deleted_at IS NULL;
    IF n <> (x->>'live_after')::int THEN RAISE EXCEPTION '#62 verify-after FAIL: live 30620=% (want %)', n, x->>'live_after'; END IF;
    SELECT count(*) INTO n FROM workflows w
     WHERE (SELECT count(*) FROM events e WHERE e.community_id = w.community_id AND e.kind = 30620 AND e.deleted_at IS NULL
              AND e.d_tag = w.id::text AND e.pubkey = w.owner_pubkey) <> 1;
    IF n <> 0 THEN RAISE EXCEPTION '#62 verify-after FAIL: % workflows without exactly one live definition', n; END IF;
    SELECT count(*) INTO n FROM events e WHERE e.community_id = c AND e.kind = 30620 AND e.deleted_at IS NULL
       AND NOT EXISTS (SELECT 1 FROM workflows w WHERE w.community_id = c AND w.id::text = e.d_tag AND w.owner_pubkey = e.pubkey);
    IF n <> 0 THEN RAISE EXCEPTION '#62 verify-after FAIL: % live definitions without workflow row', n; END IF;
    SELECT count(*) INTO n FROM workflows w, jsonb_array_elements(wf) m WHERE w.id = (m->>'id')::uuid;
    IF n <> 0 THEN RAISE EXCEPTION '#62 verify-after FAIL: target workflow row still present'; END IF;
    -- 目标事件：deleted_at 已有值，其余列 == 备份
    SELECT count(*) INTO n FROM json_array_elements(b->'target_events') r, json_populate_record(NULL::events, r) p
     WHERE NOT EXISTS (SELECT 1 FROM events e WHERE e.community_id = p.community_id AND e.created_at = p.created_at AND e.id = p.id
             AND e.deleted_at IS NOT NULL
             AND ROW(e.pubkey, e.kind, e.tags, e.content, e.sig, e.received_at, e.channel_id, e.d_tag, e.not_before, e.delivered_at)
                 IS NOT DISTINCT FROM ROW(p.pubkey, p.kind, p.tags, p.content, p.sig, p.received_at, p.channel_id, p.d_tag, p.not_before, p.delivered_at));
    IF n <> 0 THEN RAISE EXCEPTION '#62 verify-after FAIL: % target events not soft-deleted or otherwise changed', n; END IF;
    -- 非目标：workflows 其余 8 行、社区内其余 30620 行逐列不变
    SELECT count(*) INTO n FROM json_array_elements(b->'workflows_all') r, json_populate_record(NULL::workflows, r) p
     WHERE NOT (wf @> jsonb_build_array(jsonb_build_object('id', p.id::text)))
       AND NOT EXISTS (SELECT 1 FROM workflows w WHERE w.community_id = p.community_id AND w.id = p.id AND ROW(w.*) IS NOT DISTINCT FROM ROW(p.*));
    IF n <> 0 THEN RAISE EXCEPTION '#62 verify-after FAIL: % non-target workflow rows changed', n; END IF;
    SELECT count(*) INTO n FROM json_array_elements(b->'events_30620_all') r, json_populate_record(NULL::events, r) p
     WHERE NOT EXISTS (SELECT 1 FROM jsonb_array_elements(ev) m WHERE decode(m->>'id', 'hex') = p.id)
       AND NOT EXISTS (SELECT 1 FROM events e WHERE e.community_id = p.community_id AND e.created_at = p.created_at AND e.id = p.id AND ROW(e.*) IS NOT DISTINCT FROM ROW(p.*));
    IF n <> 0 THEN RAISE EXCEPTION '#62 verify-after FAIL: % non-target 30620 rows changed', n; END IF;
    SELECT count(*) INTO n FROM events WHERE community_id = c AND kind = 30620;
    IF n <> json_array_length(b->'events_30620_all') THEN RAISE EXCEPTION '#62 verify-after FAIL: 30620 row count % (backup %)', n, json_array_length(b->'events_30620_all'); END IF;
    RAISE NOTICE '#62 VERIFY-AFTER PASS: workflows 8, live 30620 8 (1:1 with workflows), targets gone, non-targets unchanged';
  END IF;
END
$state$;
\echo '== live kind:30620 per channel (what `buzz workflows list --channel` should show) =='
SELECT e.channel_id, count(*) AS live, string_agg(left(e.d_tag, 8), ',' ORDER BY e.d_tag) AS d_tags
  FROM events e WHERE e.community_id = current_setting('r62.community')::uuid AND e.kind = 30620 AND e.deleted_at IS NULL
 GROUP BY e.channel_id ORDER BY 1;
