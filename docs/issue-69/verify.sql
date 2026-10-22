-- #69 verify (read-only). -v phase=before|after -v backup="$(cat before/backup.json)"
-- before: 8 workflows, target cron is 1-5, backup matches live rows, 7 kept hashes recorded.
-- after : target cron is MON-FRI, exactly 1 definition changed, 7 kept rows byte-identical,
--         target d_tag still has exactly 1 live 30620.
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
SELECT set_config('r69.phase', :'phase', false) IS NOT NULL AS r69_phase_loaded \gset
SELECT set_config('r69.backup', :'backup', false) IS NOT NULL AS r69_backup_loaded \gset
\echo '== #69 verify: role / time / read-only =='
SELECT current_setting('r69.phase') AS phase, current_user AS role,
       to_char(clock_timestamp() AT TIME ZONE 'Asia/Shanghai', 'YYYY-MM-DD HH24:MI:SS') || ' CST' AS verify_time_cst,
       current_setting('transaction_read_only') AS read_only;

DO $state$
DECLARE
  phase text  := current_setting('r69.phase');
  c     uuid  := current_setting('r69.community')::uuid;
  tid   uuid  := current_setting('r69.target')::uuid;
  owner bytea := decode(current_setting('r69.owner'), 'hex');
  x     jsonb := current_setting('r69.expect')::jsonb;
  kept  jsonb := current_setting('r69.kept')::jsonb;
  b     json  := current_setting('r69.backup')::json;
  n     bigint;
  cron  text;
  kid   uuid;
  live  workflows%ROWTYPE;
  snap  workflows%ROWTYPE;
BEGIN
  IF phase NOT IN ('before', 'after') THEN
    RAISE EXCEPTION '#69 verify FAIL: phase=% (want before|after)', phase;
  END IF;
  IF current_setting('transaction_read_only') <> 'on' THEN
    RAISE EXCEPTION '#69 verify FAIL: not read-only';
  END IF;

  SELECT count(*) INTO n FROM workflows;
  IF n <> (x->>'wf_total')::int THEN
    RAISE EXCEPTION '#69 verify FAIL: workflows=% (want %)', n, x->>'wf_total';
  END IF;
  SELECT count(*) INTO n FROM workflows WHERE community_id <> c;
  IF n <> 0 THEN RAISE EXCEPTION '#69 verify FAIL: % workflows outside community', n; END IF;

  SELECT count(*) INTO n FROM workflows
   WHERE community_id = c AND id = tid AND owner_pubkey = owner;
  IF n <> 1 THEN RAISE EXCEPTION '#69 verify FAIL: target matched % rows (want 1)', n; END IF;

  SELECT definition #>> '{trigger,cron}' INTO cron
    FROM workflows WHERE community_id = c AND id = tid AND owner_pubkey = owner;
  IF phase = 'before' AND cron IS DISTINCT FROM current_setting('r69.cron_before') THEN
    RAISE EXCEPTION '#69 verify FAIL: target cron=% (want %)', cron, current_setting('r69.cron_before');
  END IF;
  IF phase = 'after' AND cron IS DISTINCT FROM current_setting('r69.cron_after') THEN
    RAISE EXCEPTION '#69 verify FAIL: target cron=% (want %)', cron, current_setting('r69.cron_after');
  END IF;

  -- Every kept id exists; after phase they must match the backup row byte for byte.
  n := 0;
  FOR kid IN SELECT value::uuid FROM jsonb_array_elements_text(kept) LOOP
    SELECT count(*) INTO n FROM workflows WHERE community_id = c AND id = kid;
    IF n <> 1 THEN RAISE EXCEPTION '#69 verify FAIL: kept % missing', kid; END IF;
    IF phase = 'after' THEN
      SELECT * INTO live FROM workflows WHERE community_id = c AND id = kid;
      SELECT * INTO snap FROM json_populate_record(NULL::workflows,
        (SELECT r FROM json_array_elements(b->'workflows_all') r
          WHERE (r->>'id')::uuid = kid));
      IF ROW(live.*) IS DISTINCT FROM ROW(snap.*) THEN
        RAISE EXCEPTION '#69 verify FAIL: kept % changed', kid;
      END IF;
    END IF;
  END LOOP;
  IF jsonb_array_length(kept) <> (x->>'n_kept')::int THEN
    RAISE EXCEPTION '#69 verify FAIL: kept list size %', jsonb_array_length(kept);
  END IF;

  -- backup freshness: before = every workflows row matches; after = only the target may differ.
  IF phase = 'before' THEN
    SELECT count(*) INTO n FROM json_array_elements(b->'workflows_all') r,
           json_populate_record(NULL::workflows, r) p
     WHERE NOT EXISTS (SELECT 1 FROM workflows w
                        WHERE w.community_id = p.community_id AND w.id = p.id
                          AND ROW(w.*) IS NOT DISTINCT FROM ROW(p.*));
    IF n <> 0 OR json_array_length(b->'workflows_all') <> (SELECT count(*) FROM workflows) THEN
      RAISE EXCEPTION '#69 verify FAIL: backup.workflows_all stale (% rows differ)', n;
    END IF;
  ELSE
    SELECT count(*) INTO n FROM workflows w
     WHERE w.id <> tid AND NOT EXISTS (
       SELECT 1 FROM json_array_elements(b->'workflows_all') r,
                     json_populate_record(NULL::workflows, r) p
        WHERE p.id = w.id AND ROW(w.*) IS NOT DISTINCT FROM ROW(p.*));
    IF n <> 0 THEN RAISE EXCEPTION '#69 verify FAIL: % non-target rows differ from backup', n; END IF;
    SELECT count(*) INTO n FROM workflows w
     WHERE w.id = tid AND EXISTS (
       SELECT 1 FROM json_array_elements(b->'workflows_all') r,
                     json_populate_record(NULL::workflows, r) p
        WHERE p.id = w.id AND ROW(w.*) IS NOT DISTINCT FROM ROW(p.*));
    IF n <> 0 THEN RAISE EXCEPTION '#69 verify FAIL: target row identical to backup (apply did not change it)'; END IF;
  END IF;

  SELECT count(*) INTO n FROM events
   WHERE community_id = c AND kind = 30620 AND d_tag = tid::text AND deleted_at IS NULL;
  IF n <> 1 THEN RAISE EXCEPTION '#69 verify FAIL: target live 30620=% (want 1)', n; END IF;

  RAISE NOTICE '#69 VERIFY-% PASS: workflows=8 target_cron=% kept=7', upper(phase), cron;
END
$state$;
SELECT CASE current_setting('r69.phase')
         WHEN 'before' THEN 'VERIFY-BEFORE PASS'
         ELSE 'VERIFY-AFTER PASS'
       END AS verify_marker;
