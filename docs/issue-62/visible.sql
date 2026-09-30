-- #62 执行后可见性核对（只读）。代替原 Knox P3 的 `buzz workflows list`：
-- #62 未授权任何签名身份（Jenny 2026-10-01 00:52 定），不用 peng 的键或 CLI_PRIVATE_KEY，改为直接查 list 的数据源。
-- workflows list 读的是社区内未删除（deleted_at IS NULL）的 kind:30620 定义；这里列出剩余 workflows 行与可见 30620
-- （d_tag / event id / owner / 频道 / 是否为对应 workflow 自己的定义），并断言：
--   workflows = 8，可见 30620 = 8，二者一一对应（d_tag = workflow id 且 pubkey = owner），9 个目标 d_tag 均不可见，目标 workflow 行不存在。
-- 运行：PGOPTIONS='-c default_transaction_read_only=on' psql -X -v ON_ERROR_STOP=1 -f visible.sql（run.sh visible 已如此调用）
\ir targets.sql
BEGIN READ ONLY;
\echo '== #62 visible: role / time / read-only =='
SELECT current_user AS role, session_user,
       to_char(clock_timestamp() AT TIME ZONE 'Asia/Shanghai', 'YYYY-MM-DD HH24:MI:SS') || ' CST' AS check_time_cst,
       current_setting('transaction_read_only') AS read_only;

\echo '== remaining workflows rows =='
SELECT w.id, w.name, encode(w.owner_pubkey, 'hex') AS owner_pubkey, w.channel_id, w.status, w.enabled
  FROM workflows w ORDER BY w.channel_id, w.id;

\echo '== visible kind:30620 definitions (deleted_at IS NULL; the data `workflows list` reads) =='
SELECT e.d_tag, encode(e.id, 'hex') AS event_id, encode(e.pubkey, 'hex') AS owner_pubkey, e.channel_id,
       (w.id IS NOT NULL) AS own_definition_of_workflow_row
  FROM events e
  LEFT JOIN workflows w ON w.community_id = e.community_id AND w.id::text = e.d_tag AND w.owner_pubkey = e.pubkey
 WHERE e.community_id = current_setting('r62.community')::uuid AND e.kind = 30620 AND e.deleted_at IS NULL
 ORDER BY e.channel_id, e.d_tag;

\echo '== visible kind:30620 per channel =='
SELECT e.channel_id, count(*) AS visible, string_agg(left(e.d_tag, 8), ',' ORDER BY e.d_tag) AS d_tags
  FROM events e WHERE e.community_id = current_setting('r62.community')::uuid AND e.kind = 30620 AND e.deleted_at IS NULL
 GROUP BY e.channel_id ORDER BY 1;

DO $visible$
DECLARE
  c  uuid  := current_setting('r62.community')::uuid;
  x  jsonb := current_setting('r62.expect')::jsonb;
  wf jsonb := current_setting('r62.wf')::jsonb;
  ev jsonb := current_setting('r62.ev')::jsonb;
  n  bigint;
BEGIN
  IF current_setting('transaction_read_only') <> 'on' THEN RAISE EXCEPTION '#62 visible: transaction is not read-only'; END IF;
  SELECT count(*) INTO n FROM workflows;
  IF n <> (x->>'wf_after')::int THEN RAISE EXCEPTION '#62 VISIBLE CHECK FAIL: workflows=% (want %)', n, x->>'wf_after'; END IF;
  SELECT count(*) INTO n FROM events WHERE community_id = c AND kind = 30620 AND deleted_at IS NULL;
  IF n <> (x->>'live_after')::int THEN RAISE EXCEPTION '#62 VISIBLE CHECK FAIL: visible 30620=% (want %)', n, x->>'live_after'; END IF;
  SELECT count(*) INTO n FROM workflows w
   WHERE (SELECT count(*) FROM events e WHERE e.community_id = w.community_id AND e.kind = 30620 AND e.deleted_at IS NULL
            AND e.d_tag = w.id::text AND e.pubkey = w.owner_pubkey) <> 1;
  IF n <> 0 THEN RAISE EXCEPTION '#62 VISIBLE CHECK FAIL: % workflows without exactly one own visible definition', n; END IF;
  SELECT count(*) INTO n FROM events e WHERE e.community_id = c AND e.kind = 30620 AND e.deleted_at IS NULL
     AND NOT EXISTS (SELECT 1 FROM workflows w WHERE w.community_id = c AND w.id::text = e.d_tag AND w.owner_pubkey = e.pubkey);
  IF n <> 0 THEN RAISE EXCEPTION '#62 VISIBLE CHECK FAIL: % visible definitions are not a kept workflow''s own definition', n; END IF;
  SELECT count(*) INTO n FROM events e, jsonb_array_elements(ev) m
   WHERE e.community_id = c AND e.kind = 30620 AND e.deleted_at IS NULL AND e.d_tag = m->>'d_tag';
  IF n <> 0 THEN RAISE EXCEPTION '#62 VISIBLE CHECK FAIL: % target d_tags still visible', n; END IF;
  SELECT count(*) INTO n FROM workflows w, jsonb_array_elements(wf) m WHERE w.id = (m->>'id')::uuid;
  IF n <> 0 THEN RAISE EXCEPTION '#62 VISIBLE CHECK FAIL: target workflow row still present'; END IF;
  RAISE NOTICE '#62 VISIBLE CHECK PASS: workflows 8, visible 30620 8 = the 8 kept workflows'' own definitions; 9 target d_tags not visible';
END
$visible$;
ROLLBACK;
