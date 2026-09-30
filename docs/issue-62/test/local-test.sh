#!/usr/bin/env bash
# #62 本地全流程测试：临时 PostgreSQL 集群 + 生产结构（schema.sql）+ 生产快照数据（fixture.sql），
# 经 run.sh 跑 backup → verify-before → rehearse → apply → verify-after → rollback，并做反例。
# 用法：docs/issue-62/test/local-test.sh      （需要 initdb/pg_ctl/psql；PGBIN 可覆盖）
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ISSUE="$(dirname "$HERE")"
PGBIN="${PGBIN:-$(pg_config --bindir 2>/dev/null || find /usr/lib/postgresql -maxdepth 2 -name bin 2>/dev/null | sort -V | tail -1)}"
[ -x "$PGBIN/initdb" ] || { echo "SKIP: no initdb (PGBIN=$PGBIN)"; exit 77; }
TMP="$(mktemp -d)"
PORT="${R62_TEST_PORT:-$((50000 + RANDOM % 10000))}"
cleanup() {
  "$PGBIN/pg_ctl" -D "$TMP/data" -m immediate stop >/dev/null 2>&1 || true
  if [ -n "${R62_TEST_KEEP:-}" ]; then
    mkdir -p "$R62_TEST_KEEP"
    cp -r "$TMP"/*.log "$TMP/ev" "$R62_TEST_KEEP"/ 2>/dev/null || true
  fi
  rm -rf "$TMP"
}
trap cleanup EXIT

"$PGBIN/initdb" -D "$TMP/data" -U buzz -A trust --no-sync >/dev/null
"$PGBIN/pg_ctl" -D "$TMP/data" -o "-k $TMP -p $PORT -c listen_addresses='' -c fsync=off -c TimeZone=UTC" -l "$TMP/pg.log" -w start >/dev/null
P=("$PGBIN/psql" -h "$TMP" -p "$PORT" -U buzz -X -q -v ON_ERROR_STOP=1)
"${P[@]}" -d postgres -c "CREATE DATABASE buzz" >/dev/null
"${P[@]}" -d buzz -f "$HERE/schema.sql" >/dev/null
"${P[@]}" -d buzz -f "$HERE/fixture.sql" >/dev/null
echo "server: $("${P[@]}" -d buzz -At -c 'SHOW server_version')"

export R62_PSQL="$PGBIN/psql -h $TMP -p $PORT -U buzz -d buzz"
export R62_EVIDENCE="$TMP/ev"
RUN="$ISSUE/run.sh"
q() { "${P[@]}" -d buzz -At -c "$1"; }
state() { q "SELECT md5(concat_ws('|',
  (SELECT string_agg(row_to_json(w.*)::text, ',' ORDER BY id) FROM workflows w),
  (SELECT string_agg(row_to_json(e.*)::text, ',' ORDER BY created_at, id) FROM events e),
  (SELECT string_agg(row_to_json(r.*)::text, ',' ORDER BY id) FROM workflow_runs r),
  (SELECT string_agg(row_to_json(f.*)::text, ',' ORDER BY scheduled_for) FROM scheduled_workflow_fires f)))"; }
counts() { q "SELECT (SELECT count(*) FROM workflows) || '/' || (SELECT count(*) FROM events WHERE kind=30620 AND deleted_at IS NULL)"; }
pass=0
ok() { pass=$((pass + 1)); echo "PASS $pass: $*"; }
fail() { echo "FAIL: $*" >&2; exit 1; }
expect_fail() { # expect_fail <label> <grep-pattern> <cmd...>
  local label="$1" pat="$2" out; shift 2
  if out="$("$@" 2>&1)"; then fail "$label: expected failure"; fi
  grep -q -- "$pat" <<< "$out" || { echo "$out" >&2; fail "$label: missing '$pat'"; }
  ok "$label -> $(grep -o -m1 -- "$pat.*" <<< "$out" | cut -c1-110)"
}
apply_direct() { "${P[@]}" -d buzz -1 -f "$ISSUE/apply.sql" "$@"; }

S0="$(state)"; [ "$(counts)" = "9/17" ] || fail "fixture counts $(counts)"
ok "fixture loaded: workflows/live30620 = $(counts)"

"$RUN" backup >/dev/null; ok "backup.json written ($(wc -c < "$R62_EVIDENCE/before/backup.json") bytes)"
expect_fail "backup refuses to overwrite" "exists; move it aside" "$RUN" backup
"$RUN" verify-before > "$TMP/vb.log" 2>&1 || { cat "$TMP/vb.log"; fail verify-before; }
if ! grep -q 'VERIFY-BEFORE PASS' "$TMP/vb.log" || ! grep -q 'refs OK: 4 columns checked' "$TMP/vb.log"; then fail "verify-before markers"; fi
ok "verify-before PASS (refs: $(grep -c '#62 refs [a-z_]*\.' "$TMP/vb.log") columns, all 0)"
expect_fail "apply gated on rehearse" "rehearse has not passed" "$RUN" apply
[ "$(state)" = "$S0" ] || fail "state changed before rehearse"

"$RUN" rehearse > "$TMP/rh.log" 2>&1 || { cat "$TMP/rh.log"; fail rehearse; }
grep -q 'REHEARSAL PASS' "$TMP/rh.log" || fail "rehearse marker"
[ "$(state)" = "$S0" ] || fail "rehearse changed the database"
ok "rehearse PASS and database byte-identical afterwards ($(grep -o 'workflows [0-9]* columns x [0-9]* rows' "$TMP/rh.log"); $(grep -o 'events(kind 30620) [0-9]* columns x [0-9]* rows' "$TMP/rh.log"))"

"$RUN" apply > "$TMP/ap.log" 2>&1 || { cat "$TMP/ap.log"; fail apply; }
grep -q 'apply OK' "$TMP/ap.log" || fail "apply marker"
[ "$(counts)" = "8/8" ] || fail "after apply counts $(counts)"
ok "apply: workflows/live30620 = $(counts); $(grep -c 'deleted workflow' "$TMP/ap.log") row deleted, $(grep -c 'soft-deleted 30620' "$TMP/ap.log") events soft-deleted"
S1="$(state)"
"$RUN" verify-after > "$TMP/va.log" 2>&1 || { cat "$TMP/va.log"; fail verify-after; }
grep -q 'VERIFY-AFTER PASS' "$TMP/va.log" || fail "verify-after marker"
ok "verify-after PASS"
expect_fail "run.sh apply refuses second attempt" "apply already attempted" "$RUN" apply
expect_fail "apply.sql re-run aborts" "#62 abort: workflows=8 before" apply_direct
[ "$(state)" = "$S1" ] || fail "failed re-run changed state"; ok "failed re-run left state unchanged"

# 上游 relay 重发同一签名事件的插入路径（ON CONFLICT DO NOTHING）不会把 deleted_at 置回 NULL
n="$(q "WITH r AS (INSERT INTO events (community_id,id,pubkey,created_at,kind,tags,content,sig,received_at,channel_id,d_tag,not_before)
  SELECT community_id,id,pubkey,created_at,kind,tags,content,sig,now(),channel_id,d_tag,not_before FROM events
   WHERE kind=30620 AND deleted_at IS NOT NULL AND d_tag='107226dd-c569-470a-987a-3b9223b20b77' AND created_at='2026-09-24 04:26:54+00'
  ON CONFLICT DO NOTHING RETURNING 1) SELECT count(*) FROM r")"
if [ "$n" != 0 ] || [ "$(state)" != "$S1" ]; then fail "re-insert changed state (n=$n)"; fi
ok "re-insert of same signed event: ON CONFLICT DO NOTHING inserted 0, deleted_at stays set"

"${P[@]}" -d buzz -c "INSERT INTO events (community_id,id,pubkey,created_at,kind,tags,content,sig,channel_id,d_tag)
  VALUES ('14a17e2d-40ae-4182-86c1-7dde01da0f03', decode(md5('republish'),'hex'), decode('51fb6cd8eb6a72674998d5be5b1e8e826e2d60c870337cffc3278225e4297d9e','hex'),
  '2026-10-01 00:00:00+00', 30620, '[]', 'republished', '\x00', '9bdc9fa2-48b7-4352-8b1f-7baf70ba6bd3', '910066ef-e737-4d7b-84e6-8c99652e1d55')"
expect_fail "rollback refuses if a target d_tag was republished" "live definitions exist for target d_tags" "$RUN" rollback
q "DELETE FROM events WHERE id = decode(md5('republish'),'hex')" >/dev/null
[ "$(state)" = "$S1" ] || fail "cleanup"

"$RUN" rollback > "$TMP/rb.log" 2>&1 || { cat "$TMP/rb.log"; fail rollback; }
grep -q 'rollback OK' "$TMP/rb.log" || fail "rollback marker"
[ "$(state)" = "$S0" ] || fail "rollback not byte-identical"
ok "rollback: full-row restore, database byte-identical to before (md5 of all rows), counts $(counts)"
mv "$R62_EVIDENCE/verify-before.log" "$TMP/vb1.log"
"$RUN" verify-before > /dev/null 2>&1 || fail "verify-before after rollback"; ok "verify-before PASS again after rollback"

# ---- 反例：每个都必须中止且库不变 ----
inject() { q "$1" >/dev/null; }
neg() { # neg <label> <pattern> <inject-sql> <undo-sql> [psql-env]
  inject "$3"; local s; s="$(state)"
  expect_fail "$1" "$2" apply_direct
  [ "$(state)" = "$s" ] || fail "$1 changed state"
  inject "$4"; [ "$(state)" = "$S0" ] || fail "$1 undo"
}
neg "extra live orphan 30620 -> abort" "live 30620=18 before" \
  "INSERT INTO events (community_id,id,pubkey,created_at,kind,tags,content,sig,channel_id,d_tag) VALUES ('14a17e2d-40ae-4182-86c1-7dde01da0f03', decode(md5('x'),'hex'), decode('7b7afbdd7c0c3b887b973a6d8ddaccbfb925bedfcc35bdca5d63684aa5ae8c41','hex'), '2026-09-30 00:00:00+00', 30620, '[]', 'x', '\x00', 'dba84516-ed4d-4ae2-bd54-5a9a65527324', 'aaaaaaaa-0000-0000-0000-000000000000')" \
  "DELETE FROM events WHERE id = decode(md5('x'),'hex')"
neg "target already soft-deleted -> abort" "live 30620=16 before" \
  "UPDATE events SET deleted_at='2026-09-30' WHERE d_tag='910066ef-e737-4d7b-84e6-8c99652e1d55' AND deleted_at IS NULL" \
  "UPDATE events SET deleted_at=NULL WHERE d_tag='910066ef-e737-4d7b-84e6-8c99652e1d55'"
neg "run exists for 107226dd -> abort (no cascade)" "has 1 runs/approvals/fires" \
  "INSERT INTO workflow_runs (community_id, id, workflow_id, created_at) VALUES ('14a17e2d-40ae-4182-86c1-7dde01da0f03', '00000000-0000-0000-0000-00000000abcd', '107226dd-c569-470a-987a-3b9223b20b77', '2026-09-30')" \
  "DELETE FROM workflow_runs WHERE id='00000000-0000-0000-0000-00000000abcd'"
neg "107226dd row changed (updated_at) -> abort" "matched 0 rows before" \
  "UPDATE workflows SET updated_at = updated_at + interval '1 us' WHERE id='107226dd-c569-470a-987a-3b9223b20b77'" \
  "UPDATE workflows SET updated_at = '2026-09-24 04:26:54.757964+00' WHERE id='107226dd-c569-470a-987a-3b9223b20b77'"
neg "community fenced (quiescing) -> community_write_fence aborts" "community write fenced" \
  "UPDATE communities SET deletion_state='quiescing'" "UPDATE communities SET deletion_state='active'"
expect_fail "REPEATABLE READ -> abort" "isolation is repeatable read" env PGOPTIONS='-c default_transaction_isolation=repeatable\ read' "${P[@]}" -d buzz -1 -f "$ISSUE/apply.sql"
expect_fail "community_write_fence itself rejects non-RC writes" "require READ COMMITTED" env PGOPTIONS='-c default_transaction_isolation=repeatable\ read' "${P[@]}" -d buzz -c "DELETE FROM workflows WHERE id='107226dd-c569-470a-987a-3b9223b20b77'"
expect_fail "verify-before refs check catches a run for 107226dd" "referencing rows for target ids" bash -c \
  "$(printf '%q ' "${P[@]}") -d buzz -c \"INSERT INTO workflow_runs (community_id,id,workflow_id) VALUES ('14a17e2d-40ae-4182-86c1-7dde01da0f03','00000000-0000-0000-0000-00000000abce','107226dd-c569-470a-987a-3b9223b20b77')\" >/dev/null && $(printf '%q' "$RUN") verify-before; rc=\$?; $(printf '%q ' "${P[@]}") -d buzz -c \"DELETE FROM workflow_runs WHERE id='00000000-0000-0000-0000-00000000abce'\" >/dev/null; exit \$rc"
[ "$(state)" = "$S0" ] || fail "refs negative cleanup"
inject "UPDATE workflows SET enabled=false WHERE id='7c3362d0-0b64-46fc-8ab8-9ee6ed982296'"
expect_fail "rehearse detects stale backup" "backup.workflows_all stale" bash -c "$(printf '%q ' "${P[@]}") -d buzz -v backup=\"\$(cat $(printf '%q' "$R62_EVIDENCE/before/backup.json"))\" -f $(printf '%q' "$ISSUE/rehearse.sql")"
inject "UPDATE workflows SET enabled=true WHERE id='7c3362d0-0b64-46fc-8ab8-9ee6ed982296'"
[ "$(state)" = "$S0" ] || fail "final state"
echo "ALL $pass CHECKS PASSED (database back to fixture state $S0)"
