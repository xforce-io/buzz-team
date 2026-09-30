-- #62 backup（只读）。输出单行 JSON 到 stdout，run.sh 存为 <evidence>/before/backup.json 并记 sha256。
-- 运行：PGOPTIONS='-c default_transaction_read_only=on' psql -X -At -v ON_ERROR_STOP=1 -f backup.sql > backup.json
-- 全行备份一律用 row_to_json(<alias>.*)（Knox P2-2）；bytea 固定 hex 输出，json_populate_record 可原样还原。
\set QUIET on
\ir targets.sql
SET bytea_output = 'hex';
\pset format unaligned
\pset tuples_only on
WITH
wf AS (SELECT (t->>'id')::uuid AS id, decode(t->>'owner', 'hex') AS owner
         FROM jsonb_array_elements(current_setting('r62.wf')::jsonb) t),
ev AS (SELECT t->>'d_tag' AS d_tag, decode(t->>'id', 'hex') AS id, decode(t->>'pubkey', 'hex') AS pubkey,
              (t->>'created_at')::timestamptz AS created_at
         FROM jsonb_array_elements(current_setting('r62.ev')::jsonb) t),
c AS (SELECT current_setting('r62.community')::uuid AS id)
SELECT json_build_object(
  'meta', json_build_object(
     'issue', 62,
     'taken_at_cst', to_char(clock_timestamp() AT TIME ZONE 'Asia/Shanghai', 'YYYY-MM-DD HH24:MI:SS.US') || ' CST',
     'role', current_user, 'session_user', session_user, 'database', current_database(),
     'server_version', current_setting('server_version'),
     'isolation', current_setting('transaction_isolation'), 'read_only', current_setting('transaction_read_only')),
  -- 列清单证据（information_schema.columns）：还原时 json_populate_record 按这些列逐列回填。
  'columns', (SELECT json_object_agg(table_name, cols) FROM (
       SELECT table_name, json_agg(json_build_object('pos', ordinal_position, 'name', column_name, 'type', udt_name,
                'nullable', is_nullable, 'default', column_default, 'generated', is_generated) ORDER BY ordinal_position) AS cols
         FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name IN ('workflows', 'events') GROUP BY table_name) s),
  -- 目标 workflow 行（全行）
  'target_workflows', (SELECT coalesce(json_agg(row_to_json(w.*) ORDER BY w.id), '[]')
       FROM workflows w JOIN wf ON w.id = wf.id AND w.owner_pubkey = wf.owner, c WHERE w.community_id = c.id),
  -- 目标 30620 事件（全行，9 条）
  'target_events', (SELECT coalesce(json_agg(row_to_json(e.*) ORDER BY e.d_tag), '[]')
       FROM events e JOIN ev ON e.id = ev.id AND e.pubkey = ev.pubkey AND e.created_at = ev.created_at AND e.d_tag = ev.d_tag, c
      WHERE e.community_id = c.id AND e.kind = 30620),
  -- 这 9 个 d_tag 的全部 30620 版本（含早已软删的历史版本），全行
  'history_events', (SELECT coalesce(json_agg(row_to_json(e.*) ORDER BY e.d_tag, e.created_at, e.id), '[]')
       FROM events e, c WHERE e.community_id = c.id AND e.kind = 30620 AND e.d_tag IN (SELECT d_tag FROM ev)),
  -- 完整 workflows 表（全行）
  'workflows_all', (SELECT coalesce(json_agg(row_to_json(w.*) ORDER BY w.id), '[]') FROM workflows w),
  -- 社区内全部 30620（全行，含已软删）：改后逐列比对非目标行不变
  'events_30620_all', (SELECT coalesce(json_agg(row_to_json(e.*) ORDER BY e.created_at, e.id), '[]')
       FROM events e, c WHERE e.community_id = c.id AND e.kind = 30620),
  'counts', json_build_object(
     'workflows', (SELECT count(*) FROM workflows),
     'live_30620', (SELECT count(*) FROM events e, c WHERE e.community_id = c.id AND e.kind = 30620 AND e.deleted_at IS NULL),
     'all_30620', (SELECT count(*) FROM events e, c WHERE e.community_id = c.id AND e.kind = 30620))
);
