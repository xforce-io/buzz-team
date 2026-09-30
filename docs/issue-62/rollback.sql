-- #62 rollback：按 backup.json 全行还原（Knox P2-2）。
--   workflow 行：INSERT … SELECT * FROM json_populate_record(NULL::workflows, <备份行>)
--   事件行：UPDATE events SET (<全部非生成列>) = json_populate_record(NULL::events, <备份行>) 的对应列
--          （search_tsv 是 GENERATED ALWAYS，不能赋值，由库重算；随后逐列全行比对，含 search_tsv）
-- 运行：psql -X -v ON_ERROR_STOP=1 -1 -v backup="$(cat before/backup.json)" -f rollback.sql   （生产经 run.sh rollback）
-- 不含 BEGIN/COMMIT；前置/后置断言不符即 RAISE，整个事务回滚。
\ir targets.sql
\if :{?backup}
\else
  \echo 'rollback.sql: missing -v backup=<backup.json content>'
  SELECT 1/0 AS missing_backup_variable;
\endif
SELECT set_config('r62.backup', :'backup', false) IS NOT NULL AS r62_backup_loaded \gset
\echo '== #62 rollback: role / time =='
SELECT current_user AS role, to_char(clock_timestamp() AT TIME ZONE 'Asia/Shanghai', 'YYYY-MM-DD HH24:MI:SS') || ' CST' AS exec_time_cst,
       current_setting('transaction_isolation') AS isolation;

DO $rollback$
DECLARE
  c     uuid  := current_setting('r62.community')::uuid;
  x     jsonb := current_setting('r62.expect')::jsonb;
  b     json  := current_setting('r62.backup')::json;
  mwf   jsonb := current_setting('r62.wf')::jsonb;
  mev   jsonb := current_setting('r62.ev')::jsonb;
  r     json;
  n     bigint;
  total bigint := 0;
  cols  text;
  vals  text;
BEGIN
  IF current_setting('transaction_isolation') <> 'read committed' THEN
    RAISE EXCEPTION '#62 rollback abort: isolation %', current_setting('transaction_isolation');
  END IF;
  IF (b->'meta'->>'issue') IS DISTINCT FROM '62' THEN RAISE EXCEPTION '#62 rollback abort: not a #62 backup'; END IF;
  IF json_array_length(b->'target_workflows') <> 1 OR json_array_length(b->'target_events') <> 9 THEN
    RAISE EXCEPTION '#62 rollback abort: backup has % workflows / % events (want 1/9)',
      json_array_length(b->'target_workflows'), json_array_length(b->'target_events');
  END IF;

  PERFORM pg_advisory_xact_lock((e->>'lock_key')::bigint)
     FROM jsonb_array_elements(mev) e ORDER BY (e->>'lock_key')::bigint;

  -- 前置：必须处于 apply 之后的状态，且期间 owner 没有重新发布同 d_tag（否则会出现两条可见定义，停手人工处理）。
  SELECT count(*) INTO n FROM workflows w, jsonb_array_elements(mwf) t WHERE w.community_id = c AND w.id = (t->>'id')::uuid;
  IF n <> 0 THEN RAISE EXCEPTION '#62 rollback abort: % target workflow rows already present', n; END IF;
  SELECT count(*) INTO n FROM events e, jsonb_array_elements(mev) t
   WHERE e.community_id = c AND e.kind = 30620 AND e.d_tag = t->>'d_tag' AND e.deleted_at IS NULL;
  IF n <> 0 THEN RAISE EXCEPTION '#62 rollback abort: % live definitions exist for target d_tags (republished?)', n; END IF;

  -- A) workflow 行：全行还原。备份行必须与清单的 id + owner 一致。
  FOR r IN SELECT * FROM json_array_elements(b->'target_workflows') LOOP
    SELECT count(*) INTO n FROM jsonb_array_elements(mwf) t
     WHERE t->>'id' = r->>'id' AND '\x' || (t->>'owner') = r->>'owner_pubkey';
    IF n <> 1 THEN RAISE EXCEPTION '#62 rollback abort: backup workflow % not in manifest', r->>'id'; END IF;
    INSERT INTO workflows SELECT * FROM json_populate_record(NULL::workflows, r);
    GET DIAGNOSTICS n = ROW_COUNT;
    IF n <> 1 THEN RAISE EXCEPTION '#62 rollback abort: restore workflow % inserted % rows (want 1)', r->>'id', n; END IF;
    SELECT count(*) INTO n FROM workflows w, json_populate_record(NULL::workflows, r) p
     WHERE w.community_id = p.community_id AND w.id = p.id AND ROW(w.*) IS NOT DISTINCT FROM ROW(p.*);
    IF n <> 1 THEN RAISE EXCEPTION '#62 rollback abort: restored workflow % differs from backup', r->>'id'; END IF;
    RAISE NOTICE '#62 restored workflow % (full row == backup)', r->>'id';
  END LOOP;

  -- B) 事件行：全部非生成列按备份回填（列清单取自 information_schema.columns）。
  SELECT string_agg(quote_ident(column_name), ', ' ORDER BY ordinal_position),
         string_agg('b.' || quote_ident(column_name), ', ' ORDER BY ordinal_position)
    INTO cols, vals
    FROM information_schema.columns
   WHERE table_schema = 'public' AND table_name = 'events' AND is_generated = 'NEVER';
  FOR r IN SELECT * FROM json_array_elements(b->'target_events') LOOP
    SELECT count(*) INTO n FROM jsonb_array_elements(mev) t
     WHERE '\x' || (t->>'id') = r->>'id' AND '\x' || (t->>'pubkey') = r->>'pubkey' AND t->>'d_tag' = r->>'d_tag';
    IF n <> 1 THEN RAISE EXCEPTION '#62 rollback abort: backup event % not in manifest', r->>'id'; END IF;
    EXECUTE format(
      'UPDATE events e SET (%s) = (SELECT %s FROM json_populate_record(NULL::events, $1) b)
        WHERE e.community_id = ($1->>''community_id'')::uuid AND e.created_at = ($1->>''created_at'')::timestamptz
          AND e.id = decode(substr($1->>''id'', 3), ''hex'') AND e.pubkey = decode(substr($1->>''pubkey'', 3), ''hex'')
          AND e.kind = 30620 AND e.deleted_at IS NOT NULL', cols, vals) USING r;
    GET DIAGNOSTICS n = ROW_COUNT;
    IF n <> 1 THEN RAISE EXCEPTION '#62 rollback abort: restore event % updated % rows (want 1)', r->>'id', n; END IF;
    SELECT count(*) INTO n FROM events e, json_populate_record(NULL::events, r) p
     WHERE e.community_id = p.community_id AND e.created_at = p.created_at AND e.id = p.id
       AND ROW(e.*) IS NOT DISTINCT FROM ROW(p.*);
    IF n <> 1 THEN RAISE EXCEPTION '#62 rollback abort: restored event % differs from backup', r->>'id'; END IF;
    total := total + 1;
  END LOOP;
  IF total <> 9 THEN RAISE EXCEPTION '#62 rollback abort: restored % events (want 9)', total; END IF;

  -- 后置总数回到 9 / 17。
  SELECT count(*) INTO n FROM workflows;
  IF n <> (x->>'wf_before')::int THEN RAISE EXCEPTION '#62 rollback abort: workflows=% after rollback (want %)', n, x->>'wf_before'; END IF;
  SELECT count(*) INTO n FROM events WHERE community_id = c AND kind = 30620 AND deleted_at IS NULL;
  IF n <> (x->>'live_before')::int THEN RAISE EXCEPTION '#62 rollback abort: live 30620=% after rollback (want %)', n, x->>'live_before'; END IF;
  RAISE NOTICE '#62 rollback OK: 1 workflow row + 9 events restored full-row; workflows 9, live 30620 17';
END
$rollback$;
