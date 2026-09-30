#!/usr/bin/env bash
# #62 执行入口（Hogan 在 peng 的 Mac 上运行）。每步输出 tee 到 $R62_EVIDENCE/<step>.log，带 CST 时间与 psql role。
#   run.sh backup | verify-before | rehearse | apply | verify-after | visible | rollback
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
  echo "# scripts: $(cd "$HERE" && sha targets.sql backup.sql verify.sql rehearse.sql apply.sql rollback.sql visible.sql | awk '{printf "%s=%s ", $2, substr($1,1,12)}')"
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
  visible)
    # 执行后可见性核对：只读 psql（BEGIN READ ONLY + default_transaction_read_only=on），代替原 CLI 列表核对；#62 未授权任何签名身份
    { header; inline "$HERE/visible.sql" | psql_run ro -f - 2>&1; echo "# end $(cst)"; } | tee "$EV/visible.log"
    ;;
  *)
    die "usage: run.sh backup|verify-before|rehearse|apply|verify-after|visible|rollback"
    ;;
esac
