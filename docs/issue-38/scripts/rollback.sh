#!/usr/bin/env bash
# Issue #38 rollback from a backup-* directory produced by apply.sh
# Does NOT kill or wait for respawn. Tolerates a stale/dead 周衡 pid file.
set -euo pipefail

BACKUP=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --backup) BACKUP=${2:?}; shift 2 ;;
    --backup=*) BACKUP=${1#*=}; shift ;;
    -*) echo "unknown arg: $1" >&2; exit 2 ;;
    *) BACKUP=$1; shift ;;
  esac
done
if [[ -z "$BACKUP" ]]; then
  echo "usage: rollback.sh --backup <backup-dir>   # Desktop must be fully quit (Cmd+Q)" >&2
  exit 2
fi
# shellcheck source=common.sh
source "$(dirname "$0")/common.sh"

require_live_guard
verify_thin_pin

echo "== rollback: require Desktop NOT running (identity scan + positive-control gate) =="
require_desktop_not_running "$BACKUP" || exit 1

echo "== rollback: require relay :3000 listening (A14) =="
require_relay_3000_listening || exit 1


test -f "$BACKUP/zhouheng-row-before.json"
test -f "$BACKUP/pj.md"
test -f "$BACKUP/AGENTS.md"
test -f "$BACKUP/instructions-1.md"
test -f "$BACKUP/workflow-live-before.yaml"
test -f "$BACKUP/workflow-get.json"

RB_STEP="init"
RB_RESTORED_WF=0
RB_RESTORED_ROW=0
RB_RESTORED_PROMPTS=0
RB_FAIL_REPORTED=0
rollback_fail_report() {
  local ec=${1:-1}
  [[ "${RB_FAIL_REPORTED}" -eq 1 ]] && return 0
  RB_FAIL_REPORTED=1
  echo "ROLLBACK FAILED (exit=$ec) at step: ${RB_STEP:-unknown}" >&2
  echo "BACKUP=$BACKUP" >&2
  echo "Restored so far: workflow=$RB_RESTORED_WF row=$RB_RESTORED_ROW prompts=$RB_RESTORED_PROMPTS" >&2
  echo "Re-run after fixing the failure; script is idempotent where live already matches snapshot." >&2
  if [[ "$RB_RESTORED_WF$RB_RESTORED_ROW$RB_RESTORED_PROMPTS" != "000" ]]; then
    if [[ ! -f "$BACKUP/config_written_at.txt" ]] || [[ "$RB_RESTORED_ROW" -eq 1 || "$RB_RESTORED_PROMPTS" -eq 1 || "$RB_RESTORED_WF" -eq 1 ]]; then
      record_config_written_at "$BACKUP" || true
    fi
  fi
}
trap 'ec=$?; rollback_fail_report "$ec"; exit "$ec"' ERR
trap 'ec=$?; [[ $ec -ne 0 ]] && rollback_fail_report "$ec"' EXIT

echo "== resolve 周衡 pid file (exact; extras abort; dead pid OK) =="
ZH_PID_FILE=$(zhou_pid_file)
echo "周衡 pid file: $ZH_PID_FILE"
ZHOU_PID_NOW=$(python3 -c "import json; print(json.load(open(r'''$ZH_PID_FILE'''))['pid'])")
if kill -0 "$ZHOU_PID_NOW" 2>/dev/null; then
  echo "周衡 pid $ZHOU_PID_NOW currently alive (will NOT kill)"
else
  echo "NOTE: 周衡 pid $ZHOU_PID_NOW is dead/stale — continuing rollback (no kill path)"
fi

# Other-seat pid snapshot skipped: Desktop is quit, ACP pids are gone.
# Pid comparison happens in verify-after-restart.sh --restart-mode app|single.

eval "$(grep -E '^PJ_PRIVATE_KEY=' /Users/xupeng/.local/share/buzz/config/agents.env | sed 's/^PJ_PRIVATE_KEY=/BUZZ_PRIVATE_KEY=/')"
export PATH="/Users/xupeng/lab/buzz/bin:$PATH"
export BUZZ_RELAY_URL="${BUZZ_RELAY_URL:-ws://127.0.0.1:3000}"

RB_STEP="workflow-restore"
echo "== workflow restore: compare live vs workflow-live-before.yaml =="
LIVE_GET=$(mktemp)
buzz workflows get --workflow "$WF_ID" > "$LIVE_GET"
NEED_WF=1
python3 -c "
import json, sys
from pathlib import Path
live=json.loads(Path(sys.argv[1]).read_text())['content']
want=Path(sys.argv[2]).read_text()
def norm(s):
    return s.replace('\r\n','\n').strip()+'\n'
if norm(live)==norm(want):
    print('live workflow already equals workflow-live-before.yaml — skip update')
    sys.exit(0)
print('live workflow differs from snapshot — will update')
sys.exit(1)
" "$LIVE_GET" "$BACKUP/workflow-live-before.yaml" && NEED_WF=0 || NEED_WF=1

if [[ "$NEED_WF" -eq 1 ]]; then
  echo "== restore workflow from LIVE snapshot (YAML content via cat) =="
  buzz workflows update --channel "$CH_ID" --workflow "$WF_ID" --yaml "$(cat "$BACKUP/workflow-live-before.yaml")"
  buzz workflows get --workflow "$WF_ID" > "$BACKUP/workflow-get-rollback-verify.json"
  python3 -c "
import json, sys
from pathlib import Path
live=json.loads(Path(sys.argv[1]).read_text())['content']
want=Path(sys.argv[2]).read_text()
def norm(s):
    return s.replace('\r\n','\n').strip()+'\n'
if norm(live)!=norm(want):
    print('ABORT: post-rollback workflow != workflow-live-before.yaml', file=sys.stderr)
    sys.exit(1)
print('rollback workflow read-back OK')
" "$BACKUP/workflow-get-rollback-verify.json" "$BACKUP/workflow-live-before.yaml"
  RB_RESTORED_WF=1
fi
rm -f "$LIVE_GET"

RB_STEP="restore-managed-agents-row"
echo "== restore 周衡 managed-agents row ONLY (no whole-file overwrite) =="
restore_zhou_row_from_file "$BACKUP/zhouheng-row-before.json"
RB_RESTORED_ROW=1

RB_STEP="restore-prompt-files"
echo "== restore pj.md / AGENTS.md / instructions-1.md =="
cp "$BACKUP/pj.md" "$PJ_MD"
cp "$BACKUP/AGENTS.md" "$ID_ROOT/AGENTS.md"
cp "$BACKUP/instructions-1.md" "$INSTR"
RB_RESTORED_PROMPTS=1

echo "== read-back verify restored 周衡 row (low/1500) + prompt files =="
python3 -c "
import json
from pathlib import Path
agents=json.loads(Path(r'''$MA''').read_text())
pub=r'''$PUB'''
row=next(a for a in agents if a.get('pubkey')==pub or a.get('name')=='周衡')
env=row.get('env_vars') or {}
assert row.get('idle_timeout_seconds')==1500, row.get('idle_timeout_seconds')
assert env.get('BUZZ_ACP_EFFORT_LEVEL')=='low', env.get('BUZZ_ACP_EFFORT_LEVEL')
print('managed-agents 周衡 read-back OK: idle=1500 effort=low')
for label, path, src in [
    ('pj.md', r'''$PJ_MD''', r'''$BACKUP/pj.md'''),
    ('AGENTS.md', r'''$ID_ROOT'''+'/AGENTS.md', r'''$BACKUP/AGENTS.md'''),
    ('instructions-1.md', r'''$INSTR''', r'''$BACKUP/instructions-1.md'''),
]:
    if Path(path).read_text()!=Path(src).read_text():
        raise SystemExit(f'{label} read-back mismatch')
    print(f'{label} read-back OK')
"

RB_STEP="record-config-written-at"
record_config_written_at "$BACKUP"

# No live other-seat pid check while Desktop is quit.

RB_STEP="done"
trap - ERR
cat <<MSG

========== ROLLBACK CONFIG DONE — DESKTOP STILL QUIT ==========
Restored from: $BACKUP

REQUIRED NEXT (peng + operator):
  1) peng reopens Buzz Desktop using the method peng approved for the 2026-09-24
     proxy fix (see RUNBOOK proxy assumption row). Do NOT assume Dock/Launchpad
     is safe — Dock may still inject dead HTTP(S)_PROXY=127.0.0.1:6478.
  2) GATE: confirm Desktop main process env HTTP(S)_PROXY points at the listening
     system proxy (127.0.0.1:9567), and
     python -m buzz_team --instance /Users/xupeng/lab/buzz doctor
     is ok with NO proxy_contrast.
  3) GATE: read back managed-agents.json 周衡 row — must still be effort=low
     idle=1500 max_turn=7200 (not overwritten; see A11). If overwritten: STOP, report.
  4) verify:
       docs/issue-38/scripts/verify-after-restart.sh $BACKUP --expect before --restart-mode app
==============================================================
MSG
