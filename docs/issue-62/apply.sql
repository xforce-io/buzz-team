-- #62 apply：删除 1 个 workflow 行 + 软删 9 条 kind:30620 定义事件。
-- 语义照搬上游 block/buzz#7735 delete_workflow_in_transaction（删行 + deleted_at=NOW()，同一把 advisory lock）。
-- 运行（必须整文件单事务）：psql -X -v ON_ERROR_STOP=1 -1 -f apply.sql   （生产经 run.sh apply）
-- 本文件不含 BEGIN/COMMIT：由 psql -1 包成一个事务；rehearse.sql 在自己的 BEGIN…ROLLBACK 里 \ir 本文件。
-- 所有检查与变更在同一个 DO 块内：任何计数不符都 RAISE EXCEPTION，整个事务回滚，库不变。
\ir targets.sql
\echo '== #62 apply: role / time / isolation =='
SELECT current_user AS role, session_user,
       to_char(clock_timestamp() AT TIME ZONE 'Asia/Shanghai', 'YYYY-MM-DD HH24:MI:SS') || ' CST' AS exec_time_cst,
       current_setting('transaction_isolation') AS isolation, current_setting('session_replication_role') AS repl_role;

DO $apply$
DECLARE
  c        uuid  := current_setting('r62.community')::uuid;
  x        jsonb := current_setting('r62.expect')::jsonb;
  wf       jsonb := current_setting('r62.wf')::jsonb;
  ev       jsonb := current_setting('r62.ev')::jsonb;
  t        jsonb;
  n        bigint;
  total    bigint := 0;
BEGIN
  -- 0) 运行环境：READ COMMITTED（community_write_fence 要求）、可写、触发器正常触发。
  IF current_setting('transaction_isolation') <> 'read committed' THEN
    RAISE EXCEPTION '#62 abort: isolation is %, need read committed', current_setting('transaction_isolation');
  END IF;
  IF current_setting('session_replication_role') <> 'origin' THEN
    RAISE EXCEPTION '#62 abort: session_replication_role=% (triggers would be skipped)', current_setting('session_replication_role');
  END IF;
  SELECT count(*) INTO n FROM pg_trigger
   WHERE tgname IN ('community_write_fence_workflows', 'community_write_fence_events') AND tgenabled = 'O'
     AND tgrelid IN ('public.workflows'::regclass, 'public.events'::regclass);
  IF n <> 2 THEN RAISE EXCEPTION '#62 abort: community_write_fence triggers enabled=% (want 2)', n; END IF;
  IF jsonb_array_length(wf) <> (x->>'n_wf')::int OR jsonb_array_length(ev) <> (x->>'n_ev')::int
     OR (x->>'n_wf')::int <> 1 OR (x->>'n_ev')::int <> 9 THEN
    RAISE EXCEPTION '#62 abort: manifest size wf=% ev=% (want 1/9)', jsonb_array_length(wf), jsonb_array_length(ev);
  END IF;

  -- 1) 与 relay 并发重发互斥：逐坐标取上游同一把事务级 advisory lock（按 key 排序，避免自身死锁）。
  PERFORM pg_advisory_xact_lock((e->>'lock_key')::bigint)
     FROM jsonb_array_elements(ev) e ORDER BY (e->>'lock_key')::bigint;

  -- 2) 改前总数（只读快照：9 / 17）。
  SELECT count(*) INTO n FROM workflows;
  IF n <> (x->>'wf_before')::int THEN RAISE EXCEPTION '#62 abort: workflows=% before (want %)', n, x->>'wf_before'; END IF;
  SELECT count(*) INTO n FROM workflows WHERE community_id <> c;
  IF n <> 0 THEN RAISE EXCEPTION '#62 abort: % workflows outside community %', n, c; END IF;
  SELECT count(*) INTO n FROM events WHERE community_id = c AND kind = 30620 AND deleted_at IS NULL;
  IF n <> (x->>'live_before')::int THEN RAISE EXCEPTION '#62 abort: live 30620=% before (want %)', n, x->>'live_before'; END IF;

  -- 3) 逐对象前置断言。
  FOR t IN SELECT * FROM jsonb_array_elements(wf) LOOP
    SELECT count(*) INTO n FROM workflows
     WHERE community_id = c AND id = (t->>'id')::uuid AND owner_pubkey = decode(t->>'owner', 'hex')
       AND definition_hash = decode(t->>'definition_hash', 'hex') AND updated_at = (t->>'updated_at')::timestamptz;
    IF n <> 1 THEN RAISE EXCEPTION '#62 abort: workflow % (owner %) matched % rows before (want 1)', t->>'id', t->>'owner', n; END IF;
    -- ON DELETE CASCADE 子表必须为 0，保证 DELETE 不连带删任何东西。
    SELECT (SELECT count(*) FROM workflow_runs            WHERE community_id = c AND workflow_id = (t->>'id')::uuid)
         + (SELECT count(*) FROM workflow_approvals       WHERE community_id = c AND workflow_id = (t->>'id')::uuid)
         + (SELECT count(*) FROM scheduled_workflow_fires WHERE community_id = c AND workflow_id = (t->>'id')::uuid) INTO n;
    IF n <> 0 THEN RAISE EXCEPTION '#62 abort: workflow % has % runs/approvals/fires (want 0)', t->>'id', n; END IF;
  END LOOP;
  FOR t IN SELECT * FROM jsonb_array_elements(ev) LOOP
    SELECT count(*) INTO n FROM events
     WHERE community_id = c AND kind = 30620 AND created_at = (t->>'created_at')::timestamptz
       AND id = decode(t->>'id', 'hex') AND pubkey = decode(t->>'pubkey', 'hex') AND d_tag = t->>'d_tag' AND deleted_at IS NULL;
    IF n <> 1 THEN RAISE EXCEPTION '#62 abort: event % (d_tag %, owner %) live matched % (want 1)', t->>'id', t->>'d_tag', t->>'pubkey', n; END IF;
    SELECT count(*) INTO n FROM events WHERE community_id = c AND kind = 30620 AND d_tag = t->>'d_tag' AND deleted_at IS NULL;
    IF n <> 1 THEN RAISE EXCEPTION '#62 abort: d_tag % has % live definitions (want exactly the target)', t->>'d_tag', n; END IF;
  END LOOP;

  -- 4) 变更 A：逐个 DELETE workflow 行（id + owner + definition_hash），每个必须恰好 1 行。
  FOR t IN SELECT * FROM jsonb_array_elements(wf) LOOP
    DELETE FROM workflows
     WHERE community_id = c AND id = (t->>'id')::uuid AND owner_pubkey = decode(t->>'owner', 'hex')
       AND definition_hash = decode(t->>'definition_hash', 'hex');
    GET DIAGNOSTICS n = ROW_COUNT;
    IF n <> 1 THEN RAISE EXCEPTION '#62 abort: DELETE workflow % affected % rows (want 1)', t->>'id', n; END IF;
    RAISE NOTICE '#62 deleted workflow % (1 row)', t->>'id';
  END LOOP;

  -- 5) 变更 B：逐条软删定义事件（主键 + pubkey + d_tag），每条必须恰好 1 行，合计 9。
  FOR t IN SELECT * FROM jsonb_array_elements(ev) LOOP
    UPDATE events SET deleted_at = NOW()
     WHERE community_id = c AND kind = 30620 AND created_at = (t->>'created_at')::timestamptz
       AND id = decode(t->>'id', 'hex') AND pubkey = decode(t->>'pubkey', 'hex') AND d_tag = t->>'d_tag' AND deleted_at IS NULL;
    GET DIAGNOSTICS n = ROW_COUNT;
    IF n <> 1 THEN RAISE EXCEPTION '#62 abort: soft-delete event % (d_tag %) affected % rows (want 1)', t->>'id', t->>'d_tag', n; END IF;
    total := total + n;
    RAISE NOTICE '#62 soft-deleted 30620 % d_tag % (1 row)', left(t->>'id', 8), t->>'d_tag';
  END LOOP;
  IF total <> 9 THEN RAISE EXCEPTION '#62 abort: soft-deleted % events in total (want 9)', total; END IF;

  -- 6) 改后总数：workflows 8；可见 30620 8，且恰为 8 个保留 workflow 的定义（d_tag=id 且 pubkey=owner，一一对应）。
  SELECT count(*) INTO n FROM workflows;
  IF n <> (x->>'wf_after')::int THEN RAISE EXCEPTION '#62 abort: workflows=% after (want %)', n, x->>'wf_after'; END IF;
  SELECT count(*) INTO n FROM events WHERE community_id = c AND kind = 30620 AND deleted_at IS NULL;
  IF n <> (x->>'live_after')::int THEN RAISE EXCEPTION '#62 abort: live 30620=% after (want %)', n, x->>'live_after'; END IF;
  SELECT count(*) INTO n FROM events e
   WHERE e.community_id = c AND e.kind = 30620 AND e.deleted_at IS NULL
     AND NOT EXISTS (SELECT 1 FROM workflows w WHERE w.community_id = e.community_id AND w.id::text = e.d_tag AND w.owner_pubkey = e.pubkey);
  IF n <> 0 THEN RAISE EXCEPTION '#62 abort: % live 30620 without matching workflow row after', n; END IF;
  SELECT count(*) INTO n FROM workflows w
   WHERE (SELECT count(*) FROM events e WHERE e.community_id = w.community_id AND e.kind = 30620 AND e.deleted_at IS NULL
            AND e.d_tag = w.id::text AND e.pubkey = w.owner_pubkey) <> 1;
  IF n <> 0 THEN RAISE EXCEPTION '#62 abort: % workflows without exactly one live definition after', n; END IF;
  SELECT count(*) INTO n FROM events e, jsonb_array_elements(ev) m
   WHERE e.community_id = c AND e.kind = 30620 AND e.d_tag = m->>'d_tag' AND e.deleted_at IS NULL;
  IF n <> 0 THEN RAISE EXCEPTION '#62 abort: % live definitions remain for target d_tags', n; END IF;

  RAISE NOTICE '#62 apply OK: workflows 9->8, live 30620 17->8 (1 row deleted, 9 events soft-deleted)';
END
$apply$;
