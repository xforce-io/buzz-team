-- #68 read-only workflows + scheduled_workflow_fires.
-- BEGIN READ ONLY … ROLLBACK. Hogan live only; CI uses fixtures.
--
--   PGOPTIONS='-c default_transaction_read_only=on' \
--     docker exec -i -e PGOPTIONS="$PGOPTIONS" buzz-prod-postgres-1 \
--     psql -U buzz -d buzz -X -v ON_ERROR_STOP=1 -At \
--     -v community_id='14a17e2d-40ae-4182-86c1-7dde01da0f03' \
--     -v window_start='2026-09-30T00:50:00+00:00' \
--     -v window_end='2026-09-30T09:40:00+00:00' \
--     -f docs/issue-68/read.sql
--
-- Does not print passwords or BUZZ_PRIVATE_KEY. Does not write.

BEGIN READ ONLY;

SELECT json_build_object(
  'workflows', COALESCE((
    SELECT json_agg(json_build_object(
      'id', w.id::text,
      'name', w.name,
      'owner_seat', u.display_name,
      'cron', w.definition->'trigger'->>'cron',
      'created_at', to_char((w.created_at AT TIME ZONE 'UTC'), 'YYYY-MM-DD"T"HH24:MI:SS+00:00'),
      'status', w.status::text,
      'enabled', w.enabled,
      'trigger_on', w.definition->'trigger'->>'on'
    ) ORDER BY w.id)
    FROM workflows w
    JOIN users u ON u.community_id = w.community_id AND u.pubkey = w.owner_pubkey
    WHERE w.community_id = (:'community_id')::uuid
      AND w.status = 'active'
      AND w.enabled IS TRUE
      AND w.definition->'trigger'->>'on' = 'schedule'
      AND w.definition->'trigger'->>'cron' IS NOT NULL
  ), '[]'::json),
  'fires', COALESCE((
    SELECT json_agg(json_build_object(
      'workflow_id', f.workflow_id::text,
      'scheduled_for', to_char((f.scheduled_for AT TIME ZONE 'UTC'), 'YYYY-MM-DD"T"HH24:MI:SS+00:00')
    ) ORDER BY f.scheduled_for, f.workflow_id)
    FROM scheduled_workflow_fires f
    WHERE f.community_id = (:'community_id')::uuid
      AND f.scheduled_for > (:'window_start')::timestamptz
      AND f.scheduled_for <= (:'window_end')::timestamptz
  ), '[]'::json)
);

ROLLBACK;
