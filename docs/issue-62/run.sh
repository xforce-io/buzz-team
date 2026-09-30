#!/usr/bin/env bash
# #62 执行入口（Hogan 在 peng 的 Mac 上运行）。每步输出 tee 到 $R62_EVIDENCE/<step>.log，带 CST 时间与 psql role。
#   run.sh backup | verify-before | rehearse | apply | verify-after | list | rollback
# 默认连 docker 容器 buzz-prod-postgres-1（psql -U buzz -d buzz）；SQL 经 stdin 送入，\ir 由本脚本先行内联。
# 测试时用 R62_PSQL 覆盖为本地 psql 命令（如 "psql -h /tmp/pg -p 55432 -d buzz"）。
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
STEP="${1:-}"
EV="${R62_EVIDENCE:-$HOME/lab/buzz/evidence/issue-62}"
CONTAINER="${R62_CONTAINER:-buzz-prod-postgres-1}"
BACKUP="$EV/before/backup.json"

die() { echo "run.sh: $*" >&2; exit 1; }
cst() { TZ=Asia/Shanghai date '+%Y-%m-%d %H:%M:%S CST'; }
sha() { if command -v sha256sum >/dev/null; then sha256sum "$@"; else shasum -a 256 "$@"; fi; }

# 递归内联 "\ir <file>"（psql 从 stdin 读时 \ir 找不到宿主机文件）。
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

# psql_run ro|rw <psql args...>；ro 时强制 default_transaction_read_only=on。
psql_run() {
  local mode="$1" opts=""
  shift
  [ "$mode" = ro ] && opts="-c default_transaction_read_only=on"
  if [ -n "${R62_PSQL:-}" ]; then
    local -a cmd
    read -r -a cmd <<< "$R62_PSQL"
    PGOPTIONS="$opts" "${cmd[@]}" -X -v ON_ERROR_STOP=1 "$@"
  else
    docker exec -i -e PGOPTIONS="$opts" "$CONTAINER" psql -U buzz -d buzz -X -v ON_ERROR_STOP=1 "$@"
  fi
}

header() {
  echo "# #62 $STEP  start $(cst)  host $(hostname -s 2>/dev/null || hostname)  operator ${USER:-?}"
  echo "# scripts: $(cd "$HERE" && sha targets.sql backup.sql verify.sql rehearse.sql apply.sql rollback.sql | awk '{printf "%s=%s ", $2, substr($1,1,12)}')"
  [ -f "$BACKUP" ] && echo "# backup.json sha256 $(sha "$BACKUP" | awk '{print $1}')"
  return 0
}

need_backup() { [ -s "$BACKUP" ] || die "missing $BACKUP (run: run.sh backup)"; }
backup_sha() { sha "$BACKUP" | awk '{print $1}'; }
log_passed() { # log_passed <log> <marker>：日志存在、含标记、且基于当前 backup.json
  [ -f "$1" ] && grep -q "$2" "$1" && grep -q "backup.json sha256 $(backup_sha)" "$1"
}

mkdir -p "$EV/before" "$EV/after"
case "$STEP" in
  backup)
    [ -e "$BACKUP" ] && die "$BACKUP exists; move it aside first (never overwrite a backup)"
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
    log_passed "$EV/rehearse.log" 'REHEARSAL PASS' || die "rehearse has not passed on this backup — no real deletion"
    [ -e "$EV/apply.log" ] && die "$EV/apply.log exists; apply already attempted — inspect before retrying"
    { header; inline "$HERE/apply.sql" | psql_run rw -1 -f - 2>&1; echo "# end $(cst)"; } | tee "$EV/apply.log"
    ;;
  rollback)
    need_backup
    { header; inline "$HERE/rollback.sql" | psql_run rw -1 -v backup="$(cat "$BACKUP")" -f - 2>&1; echo "# end $(cst)"; } \
      | tee "$EV/rollback.log"
    ;;
  list)
    # 官方只读检查：buzz workflows list（两个频道）。仍列出时不重启 relay，如实回报。
    BUZZ_BIN="${BUZZ_BIN:-$HOME/lab/buzz/bin/buzz}"
    export BUZZ_RELAY_URL="${BUZZ_RELAY_URL:-ws://127.0.0.1:3000}"
    [ -x "$BUZZ_BIN" ] || die "BUZZ_BIN not executable: $BUZZ_BIN"
    { header
      for ch in 9bdc9fa2-48b7-4352-8b1f-7baf70ba6bd3 dba84516-ed4d-4ae2-bd54-5a9a65527324; do
        "$BUZZ_BIN" workflows list --channel "$ch" > "$EV/after/list-$ch.json"
        echo "# list $ch saved"
      done
      python3 - "$HERE/targets.sql" "$EV/after" <<'PY'
import json, re, sys
targets = set(re.findall(r'"d_tag":"([0-9a-f-]{36})"', open(sys.argv[1]).read()))
want = {"9bdc9fa2-48b7-4352-8b1f-7baf70ba6bd3": 1, "dba84516-ed4d-4ae2-bd54-5a9a65527324": 7}
ok = True
for ch, n in want.items():
    ids = [w.get("workflow_id") for w in json.load(open(f"{sys.argv[2]}/list-{ch}.json"))]
    leaked = sorted(set(ids) & targets)
    print(f"list {ch}: {len(ids)} workflows (want {n}); targets still listed: {leaked or 'none'}")
    ok &= len(ids) == n and not leaked
print("LIST CHECK PASS" if ok else "LIST CHECK MISMATCH (do not restart relay; report as-is)")
PY
      echo "# end $(cst)"; } 2>&1 | tee "$EV/list.log"
    ;;
  *)
    die "usage: run.sh backup|verify-before|rehearse|apply|verify-after|list|rollback"
    ;;
esac
