#!/usr/bin/env bash
# Local PostgreSQL rehearsal for #69 SQL: backup → verify-before → rehearse.
# Live owner apply is not executed here. Needs initdb; exit 77 if missing.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ISSUE="$(dirname "$HERE")"
SCHEMA="$(cd "$ISSUE/../issue-62/test" && pwd)/schema.sql"
PGBIN="${PGBIN:-}"
if [ -z "$PGBIN" ]; then
  PGBIN=$(pg_config --bindir 2>/dev/null || true)
fi
if [ -z "$PGBIN" ]; then
  PGBIN=$(find /usr/lib/postgresql -maxdepth 2 -name bin 2>/dev/null | sort -V | tail -1 || true)
fi
[ -n "$PGBIN" ] && [ -x "$PGBIN/initdb" ] || { echo "SKIP: no initdb (PGBIN=$PGBIN)"; exit 77; }
[ -f "$SCHEMA" ] || { echo "FAIL: missing $SCHEMA" >&2; exit 1; }

TMP="$(mktemp -d)"
PORT="${R69_TEST_PORT:-$((50000 + RANDOM % 10000))}"
cleanup() {
  "$PGBIN/pg_ctl" -D "$TMP/data" -m immediate stop >/dev/null 2>&1 || true
  rm -rf "$TMP"
}
trap cleanup EXIT

"$PGBIN/initdb" -D "$TMP/data" -U buzz -A trust --no-sync >/dev/null
"$PGBIN/pg_ctl" -D "$TMP/data" -o "-k $TMP -p $PORT -c listen_addresses='' -c fsync=off -c TimeZone=UTC" -l "$TMP/pg.log" -w start >/dev/null
P=("$PGBIN/psql" -h "$TMP" -p "$PORT" -U buzz -X -q -v ON_ERROR_STOP=1)
"${P[@]}" -d postgres -c "CREATE DATABASE buzz" >/dev/null
"${P[@]}" -d buzz -f "$SCHEMA" >/dev/null
"${P[@]}" -d buzz -f "$HERE/fixture.sql" >/dev/null

export R69_PSQL="$PGBIN/psql -h $TMP -p $PORT -U buzz -d buzz"
export R69_EVIDENCE="$TMP/ev"
state() {
  "${P[@]}" -d buzz -At -c "SELECT md5((SELECT string_agg(row_to_json(w.*)::text, ',' ORDER BY id) FROM workflows w))"
}
BEFORE=$(state)
"$ISSUE/run.sh" backup >/dev/null
"$ISSUE/run.sh" verify-before | grep -q 'VERIFY-BEFORE PASS'
"$ISSUE/run.sh" rehearse | grep -q 'REHEARSAL PASS'
AFTER=$(state)
[ "$BEFORE" = "$AFTER" ] || { echo "FAIL: rehearse left the database changed" >&2; exit 1; }
echo "ALL #69 SQL CHECKS PASSED"
