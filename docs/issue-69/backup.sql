-- #69 backup (read-only). stdout = one JSON object. run.sh stores it as before/backup.json.
-- Run: PGOPTIONS='-c default_transaction_read_only=on' psql -X -At -v ON_ERROR_STOP=1 -f backup.sql
\set QUIET on
\ir targets.sql
SET bytea_output = 'hex';
\pset format unaligned
\pset tuples_only on
WITH
c AS (SELECT current_setting('r69.community')::uuid AS id),
t AS (SELECT current_setting('r69.target')::uuid AS id, decode(current_setting('r69.owner'), 'hex') AS owner),
kept AS (SELECT value::uuid AS id FROM jsonb_array_elements_text(current_setting('r69.kept')::jsonb))
SELECT json_build_object(
  'meta', json_build_object(
     'issue', 69,
     'taken_at_cst', to_char(clock_timestamp() AT TIME ZONE 'Asia/Shanghai', 'YYYY-MM-DD HH24:MI:SS.US') || ' CST',
     'role', current_user, 'session_user', session_user, 'database', current_database(),
     'target', current_setting('r69.target'),
     'cron_before', current_setting('r69.cron_before'),
     'cron_after', current_setting('r69.cron_after'),
     'isolation', current_setting('transaction_isolation'),
     'read_only', current_setting('transaction_read_only')),
  'columns', (SELECT json_object_agg(table_name, cols) FROM (
       SELECT table_name, json_agg(json_build_object('pos', ordinal_position, 'name', column_name, 'type', udt_name,
                'nullable', is_nullable, 'generated', is_generated) ORDER BY ordinal_position) AS cols
         FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name IN ('workflows', 'events') GROUP BY table_name) s),
  'target_workflow', (SELECT row_to_json(w.*)
       FROM workflows w, t, c
      WHERE w.community_id = c.id AND w.id = t.id AND w.owner_pubkey = t.owner),
  'target_events', (SELECT coalesce(json_agg(row_to_json(e.*) ORDER BY e.created_at, e.id), '[]')
       FROM events e, t, c
      WHERE e.community_id = c.id AND e.kind = 30620 AND e.d_tag = t.id::text),
  'kept_hashes', (SELECT coalesce(json_object_agg(w.id::text, encode(w.definition_hash, 'hex')), '{}')
       FROM workflows w, kept, c WHERE w.community_id = c.id AND w.id = kept.id),
  'workflows_all', (SELECT coalesce(json_agg(row_to_json(w.*) ORDER BY w.id), '[]') FROM workflows w),
  'events_30620_all', (SELECT coalesce(json_agg(row_to_json(e.*) ORDER BY e.created_at, e.id), '[]')
       FROM events e, c WHERE e.community_id = c.id AND e.kind = 30620),
  'counts', json_build_object(
     'workflows', (SELECT count(*) FROM workflows),
     'live_30620', (SELECT count(*) FROM events e, c WHERE e.community_id = c.id AND e.kind = 30620 AND e.deleted_at IS NULL),
     'target_live_30620', (SELECT count(*) FROM events e, t, c
        WHERE e.community_id = c.id AND e.kind = 30620 AND e.d_tag = t.id::text AND e.deleted_at IS NULL))
);
