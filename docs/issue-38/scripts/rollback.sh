#!/usr/bin/env bash
# Issue #38 rollback from a backup-* directory produced by apply.sh
set -euo pipefail

BACKUP=${1:?usage: rollback.sh /Users/xupeng/lab/buzz/evidence/issue-38/backup-<ts>}
# shellcheck source=common.sh
source "$(dirname "$0")/common.sh"

require_live_guard
verify_thin_pin

test -f "$BACKUP/zhouheng-row-before.json"
test -f "$BACKUP/pj.md"
test -f "$BACKUP/AGENTS.md"
test -f "$BACKUP/instructions-1.md"
test -f "$BACKUP/workflow-live-before.yaml"
test -f "$BACKUP/workflow-get.json"

echo "== resolve 周衡 pid file =="
ZH_PID_FILE=$(zhou_pid_file)
echo "周衡 pid file: $ZH_PID_FILE"

echo "== snapshot other seats before rollback =="
TMP_OTHERS=$(mktemp)
snapshot_other_pids "$TMP_OTHERS"

echo "== restore 周衡 managed-agents row ONLY (no whole-file overwrite) =="
restore_zhou_row_from_file "$BACKUP/zhouheng-row-before.json"

echo "== restore pj.md / AGENTS.md / instructions-1.md =="
cp "$BACKUP/pj.md" "$PJ_MD"
cp "$BACKUP/AGENTS.md" "$ID_ROOT/AGENTS.md"
cp "$BACKUP/instructions-1.md" "$INSTR"

echo "== restore workflow from LIVE snapshot taken at apply (workflow-live-before.yaml) =="
eval "$(grep -E '^PJ_PRIVATE_KEY=' /Users/xupeng/.local/share/buzz/config/agents.env | sed 's/^PJ_PRIVATE_KEY=/BUZZ_PRIVATE_KEY=/')"
export PATH="/Users/xupeng/lab/buzz/bin:$PATH"
export BUZZ_RELAY_URL="${BUZZ_RELAY_URL:-ws://127.0.0.1:3000}"
# Prefer yaml extracted from live get at apply time; never staged before/ which may drift.
buzz workflows update --channel "$CH_ID" --workflow "$WF_ID" --yaml "$BACKUP/workflow-live-before.yaml"

echo "== restart 周衡 ACP only (safe kill) =="
safe_kill_zhou

echo "== verify other seats untouched =="
verify_other_pids_unchanged "$TMP_OTHERS"
rm -f "$TMP_OTHERS"

echo "rollback complete from $BACKUP"
