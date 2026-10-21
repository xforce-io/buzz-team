# shellcheck shell=bash
# Shared constants for Issue #69. Bash 3.2 compatible.

WF_ID=f5cc62c0-3756-419e-8a3f-8e694df2e93e
CH_ID=9bdc9fa2-48b7-4352-8b1f-7baf70ba6bd3
PUB=51fb6cd8eb6a72674998d5be5b1e8e826e2d60c870337cffc3278225e4297d9e
CRON_BEFORE='0 1 * * 1-5'
CRON_AFTER='0 1 * * MON-FRI'
COMMUNITY=14a17e2d-40ae-4182-86c1-7dde01da0f03

ISSUE69_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$ISSUE69_DIR/../.." && pwd)"

die() { echo "issue-69: $*" >&2; exit 1; }

sha() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$@"
  else shasum -a 256 "$@"; fi
}

cst_hm() {
  if [ -n "${ISSUE69_NOW_CST:-}" ]; then
    printf '%s\n' "$ISSUE69_NOW_CST"
  else
    TZ=Asia/Shanghai date +%H%M
  fi
}

# Refuse live apply/rollback inside CST 08:58–09:02 (exclusive of 09:02).
refuse_apply_window() {
  local hm
  hm=$(cst_hm)
  case "$hm" in
    ''|*[!0-9]*) die "invalid CST clock '$hm'" ;;
  esac
  if [ $((10#$hm)) -ge 858 ] && [ $((10#$hm)) -lt 902 ]; then
    die "refuse CST 08:58-09:02 apply window (now=$hm). New and old cron both fire at 01:00 UTC"
  fi
}

require_live_guard() {
  if [ "${ISSUE69_I_UNDERSTAND_LIVE:-}" != "yes" ]; then
    echo "Refusing live mutation. Default is dry-run." >&2
    echo "Live apply is human:required after ACP>=9. Set ISSUE69_I_UNDERSTAND_LIVE=yes and pass --live." >&2
    exit 2
  fi
}

rewrite_cron() {
  # rewrite_cron <yaml-file> → stdout YAML with CRON_AFTER. Fails unless current is CRON_BEFORE.
  local src="$1"
  PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}" python3 -c "
from pathlib import Path
from buzz_team.cron_dow import replace_schedule_cron
text = Path(r'''$src''').read_text()
print(replace_schedule_cron(text, r'''$CRON_AFTER''', expect=r'''$CRON_BEFORE'''), end='')
"
}
