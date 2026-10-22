-- #69 target manifest. backup / verify / rehearse \ir this file first.
-- Live hashes are captured at backup time; this file pins ids and expected crons only.
-- Community and the 8 post-#62 workflow ids come from the 2026-10-01 read-only snapshot
-- plus Issue #69 L1 section 2 (the other 7 are daily / * and must not change).
SET TimeZone = 'UTC';
SET bytea_output = 'hex';
SELECT set_config('r69.community', '14a17e2d-40ae-4182-86c1-7dde01da0f03', false) AS r69_community \gset
SELECT set_config('r69.target', 'f5cc62c0-3756-419e-8a3f-8e694df2e93e', false) AS r69_target \gset
SELECT set_config('r69.owner', '51fb6cd8eb6a72674998d5be5b1e8e826e2d60c870337cffc3278225e4297d9e', false) AS r69_owner \gset
SELECT set_config('r69.cron_before', '0 1 * * 1-5', false) AS r69_cron_before \gset
SELECT set_config('r69.cron_after', '0 1 * * MON-FRI', false) AS r69_cron_after \gset
SELECT set_config('r69.expect', '{"wf_total":8,"n_changed":1,"n_kept":7,"live_30620":8}', false) AS r69_expect \gset
SELECT set_config('r69.kept', $r69$[
  "7d90ca75-51a1-40a6-8966-8fffc9c523c3",
  "50d27eb7-e768-4401-af80-8fc95b5f0bae",
  "2d75251c-48bc-46b7-9bec-8e06d2989c85",
  "97152434-1ec3-4b51-b55d-4159ecec4162",
  "619b47c8-4339-46b1-bbfa-2a7fa9b80c19",
  "cd608a18-6254-41cc-a0d7-c23879b1fe79",
  "7c3362d0-0b64-46fc-8ab8-9ee6ed982296"
]$r69$, false) IS NOT NULL AS r69_kept_loaded \gset
