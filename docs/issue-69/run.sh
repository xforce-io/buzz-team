#!/usr/bin/env bash
# #69 entrypoint for Hogan on the Mac. Default apply/rollback are dry-run.
#   run.sh backup | verify-before | rehearse | apply | verify-after | rollback | check
# SQL goes to docker buzz-prod-postgres-1 unless R69_PSQL is set.
# apply / rollback never write SQL definitions; they call apply.sh / rollback.sh.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=common.sh
source "$HERE/common.sh"

STEP="${1:-}"
EV="${R69_EVIDENCE:-$HOME/lab/buzz/evidence/issue-69}"
CONTAINER="${R69_CONTAINER:-buzz-prod-postgres-1}"
BACKUP="$EV/before/backup.json"

cst() { TZ=Asia/Shanghai date '+%Y-%m-%d %H:%M:%S CST'; }

inline() {
  local f="$1" d line
  d="$(dirname "$f")"
  while IFS= read -r line || [ -n "$line" ]; do
    if [[ "$line" =~ ^\\ir[[:space:]]+([^[:space:]]+)[[:space:]]*$ ]]; then
      inline "$d/${BASH_REMATCH[1]}"
    else
      printf '%s\n' "$line"
    fi
  done < "$f"
}

psql_run() {
  local mode="$1" opts=""
  shift
  [ "$mode" = ro ] && opts="-c default_transaction_read_only=on"
  if [ -n "${R69_PSQL:-}" ]; then
    local -a cmd
    # shellcheck disable=SC2206
    cmd=($R69_PSQL)
    PGOPTIONS="$opts" "${cmd[@]}" -X -v ON_ERROR_STOP=1 "$@"
  else
    docker exec -i -e PGOPTIONS="$opts" "$CONTAINER" psql -U buzz -d buzz -X -v ON_ERROR_STOP=1 "$@"
  fi
}

header() {
  echo "# #69 $STEP  start $(cst)  host $(hostname -s 2>/dev/null || hostname)  operator ${USER:-?}"
  echo "# scripts: $(cd "$HERE" && sha targets.sql backup.sql verify.sql rehearse.sql | awk '{printf "%s=%s ", $2, substr($1,1,12)}')"
  [ -f "$BACKUP" ] && echo "# backup.json sha256 $(sha "$BACKUP" | awk '{print $1}')"
  return 0
}

need_backup() { [ -s "$BACKUP" ] || die "missing $BACKUP (run: run.sh backup)"; }
backup_sha() { sha "$BACKUP" | awk '{print $1}'; }
log_passed() {
  [ -f "$1" ] && grep -q "$2" "$1" && grep -q "backup.json sha256 $(backup_sha)" "$1"
}

mkdir -p "$EV/before" "$EV/after"
case "$STEP" in
  backup)
    [ -e "$BACKUP" ] && die "$BACKUP exists; move it aside first"
    { header; } > "$EV/backup.log"
    inline "$HERE/backup.sql" | psql_run ro -At -f - > "$BACKUP.tmp"
    mv "$BACKUP.tmp" "$BACKUP"
    sha "$BACKUP" | tee "$BACKUP.sha256" >> "$EV/backup.log"
    echo "# end $(cst)" >> "$EV/backup.log"
    cat "$EV/backup.log"
    ;;
  verify-before|verify-after)
    need_backup
    phase="${STEP#verify-}"
    { header; inline "$HERE/verify.sql" | psql_run ro -v phase="$phase" -v backup="$(cat "$BACKUP")" -f - 2>&1; echo "# end $(cst)"; } \
      | tee "$EV/$STEP.log"
    ;;
  rehearse)
    need_backup
    log_passed "$EV/verify-before.log" 'VERIFY-BEFORE PASS' || die "verify-before has not passed on this backup"
    { header; inline "$HERE/rehearse.sql" | psql_run rw -v backup="$(cat "$BACKUP")" -f - 2>&1; echo "# end $(cst)"; } \
      | tee "$EV/rehearse.log"
    ;;
  apply)
    need_backup
    log_passed "$EV/verify-before.log" 'VERIFY-BEFORE PASS' || die "verify-before has not passed on this backup"
    log_passed "$EV/rehearse.log" 'REHEARSAL PASS' || die "rehearse has not passed on this backup — no live update"
    shift
    "$HERE/apply.sh" --backup "$EV" "$@"
    ;;
  rollback)
    need_backup
    shift
    "$HERE/rollback.sh" --backup "$EV" "$@"
    ;;
  check)
    shift
    python3 "$HERE/check-numeric-dow.py" "$@"
    ;;
  *)
    die "usage: run.sh backup|verify-before|rehearse|apply|verify-after|rollback|check"
    ;;
esac
