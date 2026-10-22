-- #69 rehearse: simulate the definition cron change, assert 1/7, then ROLLBACK.
-- This is NOT the live apply path (owner update writes a signed 30620).
-- Run: psql -X -v ON_ERROR_STOP=1 -v backup="$(cat before/backup.json)" -f rehearse.sql
-- Do not pass -1; this file owns BEGIN … ROLLBACK.
\ir targets.sql
\if :{?backup}
\else
  \echo 'rehearse.sql: missing -v backup=<backup.json content>'
  SELECT 1/0 AS missing_backup_variable;
\endif
BEGIN;
\echo '== #69 rehearse: role / time / isolation =='
SELECT current_user AS role,
       to_char(clock_timestamp() AT TIME ZONE 'Asia/Shanghai', 'YYYY-MM-DD HH24:MI:SS') || ' CST' AS rehearse_time_cst,
       current_setting('transaction_isolation') AS isolation,
       current_setting('transaction_read_only') AS read_only,
       current_setting('session_replication_role') AS repl_role;
DO $env$
BEGIN
  IF current_setting('transaction_isolation') <> 'read committed' THEN
    RAISE EXCEPTION '#69 rehearse abort: isolation %', current_setting('transaction_isolation');
  END IF;
  IF current_setting('transaction_read_only') <> 'off' THEN
    RAISE EXCEPTION '#69 rehearse abort: read-only transaction';
  END IF;
  IF current_setting('session_replication_role') <> 'origin' THEN
    RAISE EXCEPTION '#69 rehearse abort: triggers disabled';
  END IF;
END
$env$;

CREATE TEMP TABLE r69_before_wf ON COMMIT DROP AS SELECT * FROM workflows;
SELECT set_config('r69.backup', :'backup', false) IS NOT NULL AS r69_backup_loaded \gset

DO $fresh$
DECLARE
  b json := current_setting('r69.backup')::json;
  n bigint;
BEGIN
  SELECT count(*) INTO n FROM json_array_elements(b->'workflows_all') r,
         json_populate_record(NULL::workflows, r) p
   WHERE NOT EXISTS (SELECT 1 FROM workflows w
                      WHERE w.community_id = p.community_id AND w.id = p.id
                        AND ROW(w.*) IS NOT DISTINCT FROM ROW(p.*));
  IF n <> 0 OR json_array_length(b->'workflows_all') <> (SELECT count(*) FROM workflows) THEN
    RAISE EXCEPTION '#69 rehearse abort: backup.workflows_all stale (% rows differ)', n;
  END IF;
END
$fresh$;

\echo '== rehearse: simulate cron rewrite (1 row) =='
DO $sim$
DECLARE
  c     uuid  := current_setting('r69.community')::uuid;
  tid   uuid  := current_setting('r69.target')::uuid;
  owner bytea := decode(current_setting('r69.owner'), 'hex');
  kept  jsonb := current_setting('r69.kept')::jsonb;
  n     bigint;
  cron  text;
  kid   uuid;
  live  workflows%ROWTYPE;
  snap  workflows%ROWTYPE;
BEGIN
  UPDATE workflows
     SET definition = jsonb_set(definition, '{trigger,cron}', to_jsonb(current_setting('r69.cron_after')))
   WHERE community_id = c AND id = tid AND owner_pubkey = owner
     AND definition #>> '{trigger,cron}' = current_setting('r69.cron_before');
  GET DIAGNOSTICS n = ROW_COUNT;
  IF n <> 1 THEN
    RAISE EXCEPTION '#69 rehearse abort: UPDATE affected % rows (want 1)', n;
  END IF;

  SELECT definition #>> '{trigger,cron}' INTO cron
    FROM workflows WHERE community_id = c AND id = tid;
  IF cron IS DISTINCT FROM current_setting('r69.cron_after') THEN
    RAISE EXCEPTION '#69 rehearse abort: cron became %', cron;
  END IF;

  n := 0;
  FOR kid IN SELECT value::uuid FROM jsonb_array_elements_text(kept) LOOP
    SELECT * INTO live FROM workflows WHERE community_id = c AND id = kid;
    SELECT * INTO snap FROM r69_before_wf WHERE id = kid;
    IF ROW(live.*) IS DISTINCT FROM ROW(snap.*) THEN
      RAISE EXCEPTION '#69 rehearse abort: kept % changed', kid;
    END IF;
    n := n + 1;
  END LOOP;
  IF n <> 7 THEN RAISE EXCEPTION '#69 rehearse abort: kept compared % (want 7)', n; END IF;

  SELECT count(*) INTO n FROM workflows w
   FULL JOIN r69_before_wf b ON w.community_id = b.community_id AND w.id = b.id
   WHERE w.id IS NULL OR b.id IS NULL
      OR (w.id <> tid AND ROW(w.*) IS DISTINCT FROM ROW(b.*));
  IF n <> 0 THEN RAISE EXCEPTION '#69 rehearse abort: % unexpected row diffs', n; END IF;
  RAISE NOTICE '#69 rehearse: 1 definition changed, 7 unchanged';
END
$sim$;

ROLLBACK;
\echo 'REHEARSAL PASS'
