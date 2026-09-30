-- #62 目标清单（唯一来源）。apply/rollback/verify/rehearse/backup 都先 \ir 本文件。
-- 来源：2026-10-01 00:10–00:45 CST 只读快照（PGOPTIONS=-c default_transaction_read_only=on，role buzz）。
-- 每个目标同时按 id 和 owner pubkey 精确匹配；事件另按主键 (community_id, created_at, id) 与 d_tag 匹配。
-- lock_key = 上游 c507a4d replaceable.rs::event_replacement_lock_key(community, 30620, pubkey, d_tag)（FNV-1a 64）；
--   与上游 delete_workflow_in_transaction 取同一把 pg_advisory_xact_lock，和 relay 的并发重发互斥。CI 复算校验。
--
--   107226dd  event 2a6c6209  owner 裴昭  裴昭探针 probe-disabled（有 workflows 行）
--   037a83e7  event 9dd10e17  owner 周衡  #38 smoke 临时
--   0ec65559  event e1c40066  owner 方维  方维旧「站会开窗唤醒」
--   33e8caad  event e17964d9  owner 秦牧  秦牧 probe-schema
--   cf9e7de9  event 763c0180  owner 秦牧  秦牧 probe-schema
--   33b7bd61  event 8926aa68  owner 秦牧  秦牧 probe-mention
--   ce80d151  event 8cba8571  owner 周衡  #38 smoke
--   38ad49f3  event 856fc79b  owner 周衡  #38 smoke
--   910066ef  event 1360986d  owner 周衡  #38 smoke
SET TimeZone = 'UTC';
SET bytea_output = 'hex';
SELECT set_config('r62.community', '14a17e2d-40ae-4182-86c1-7dde01da0f03', false) AS r62_community \gset
-- 期望总数（只读快照实测）：workflows 9 → 8；社区内可见 kind:30620 17 → 8（剩下 8 条恰为 8 个保留 workflow 的定义）。
SELECT set_config('r62.expect', '{"wf_before":9,"wf_after":8,"live_before":17,"live_after":8,"n_wf":1,"n_ev":9}', false) AS r62_expect \gset
SELECT set_config('r62.wf', $r62$[
{"id":"107226dd-c569-470a-987a-3b9223b20b77","owner":"265e4fc1258c1a9a596a5ad0562c73d04aeae090401382ea26ba4ddbe6d97529","definition_hash":"913a972bb6e95ad4c6a5678390295b6b38a9b9f7537ecec055bc2a7ae68ac248","updated_at":"2026-09-24T04:26:54.757964+00:00"}
]$r62$, false) IS NOT NULL AS r62_wf_loaded \gset
SELECT set_config('r62.ev', $r62$[
{"d_tag":"107226dd-c569-470a-987a-3b9223b20b77","id":"2a6c62098ea6f61fa1a866e77b8f808cfc462a868d36065631e486593b8c5ed2","pubkey":"265e4fc1258c1a9a596a5ad0562c73d04aeae090401382ea26ba4ddbe6d97529","created_at":"2026-09-24T04:26:54+00:00","lock_key":"-7632354990814537388"},
{"d_tag":"037a83e7-ebfc-4080-be20-b875cd23d4bc","id":"9dd10e17f1f1c324ded98ca480d6bfc0a6c6b33e3d248c83b816d50f46227b6b","pubkey":"51fb6cd8eb6a72674998d5be5b1e8e826e2d60c870337cffc3278225e4297d9e","created_at":"2026-09-24T05:48:38+00:00","lock_key":"-605135785468913841"},
{"d_tag":"0ec65559-05de-4487-9154-72afe030422f","id":"e1c40066b5992077a14a706930c1646a2aa23d9f9803be1cc203812ede327f9f","pubkey":"db5955756e3825e2f208cb4b69a33ee4a2b20313474a213ea9efcbf931ce7861","created_at":"2026-09-17T01:57:51+00:00","lock_key":"4963262606270097149"},
{"d_tag":"33e8caad-530b-4f71-82bf-d4da55b49cce","id":"e17964d952818211ca71c7fb8874f6fb59fabaf49304ce286db0214d0f1091c6","pubkey":"7b7afbdd7c0c3b887b973a6d8ddaccbfb925bedfcc35bdca5d63684aa5ae8c41","created_at":"2026-09-24T04:52:41+00:00","lock_key":"4401139199164537071"},
{"d_tag":"cf9e7de9-70ee-4691-af8e-6b48151938b2","id":"763c01806f798a7771576fb08f15f417f744f96f17755f4e3484736b94c8538d","pubkey":"7b7afbdd7c0c3b887b973a6d8ddaccbfb925bedfcc35bdca5d63684aa5ae8c41","created_at":"2026-09-24T04:52:41+00:00","lock_key":"8292968290255201938"},
{"d_tag":"33b7bd61-0741-4786-b9f3-e85653e7e424","id":"8926aa682d5eeb8b30fb08c4397df3fb89a7322d5638f04485731af8e1d68a56","pubkey":"7b7afbdd7c0c3b887b973a6d8ddaccbfb925bedfcc35bdca5d63684aa5ae8c41","created_at":"2026-09-24T04:52:58+00:00","lock_key":"-9120298248650278736"},
{"d_tag":"ce80d151-114f-447a-a496-5f6fcc667c9f","id":"8cba8571e46618d9283d501c0db0d70018b32363fd7fda9eaf90371faa9ff47e","pubkey":"51fb6cd8eb6a72674998d5be5b1e8e826e2d60c870337cffc3278225e4297d9e","created_at":"2026-09-24T05:47:19+00:00","lock_key":"5177047769962197764"},
{"d_tag":"38ad49f3-b5c5-4f2e-a5ac-e70fda814c03","id":"856fc79b37e7465a5291086f2802afdb19a2139799063c30682f8b0ad5bd1a43","pubkey":"51fb6cd8eb6a72674998d5be5b1e8e826e2d60c870337cffc3278225e4297d9e","created_at":"2026-09-24T05:47:30+00:00","lock_key":"-4733852303929179463"},
{"d_tag":"910066ef-e737-4d7b-84e6-8c99652e1d55","id":"1360986d5fede95c09b892bccc80327e5951099c5848b94a18abf46a73dd3a56","pubkey":"51fb6cd8eb6a72674998d5be5b1e8e826e2d60c870337cffc3278225e4297d9e","created_at":"2026-09-24T05:48:20+00:00","lock_key":"-2802408076134113180"}
]$r62$, false) IS NOT NULL AS r62_ev_loaded \gset
