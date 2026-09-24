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

eval "$(grep -E '^PJ_PRIVATE_KEY=' /Users/xupeng/.local/share/buzz/config/agents.env | sed 's/^PJ_PRIVATE_KEY=/BUZZ_PRIVATE_KEY=/')"
export PATH="/Users/xupeng/lab/buzz/bin:$PATH"
export BUZZ_RELAY_URL="${BUZZ_RELAY_URL:-ws://127.0.0.1:3000}"

# Workflow: compare live vs apply-time snapshot; equal -> skip; else update with YAML CONTENT.
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
fi
rm -f "$LIVE_GET"

echo "== restore 周衡 managed-agents row ONLY (no whole-file overwrite) =="
restore_zhou_row_from_file "$BACKUP/zhouheng-row-before.json"

echo "== restore pj.md / AGENTS.md / instructions-1.md =="
cp "$BACKUP/pj.md" "$PJ_MD"
cp "$BACKUP/AGENTS.md" "$ID_ROOT/AGENTS.md"
cp "$BACKUP/instructions-1.md" "$INSTR"

echo "== restart 周衡 ACP only (safe kill) =="
safe_kill_zhou

echo "== verify other seats untouched =="
verify_other_pids_unchanged "$TMP_OTHERS"
rm -f "$TMP_OTHERS"

echo "rollback complete from $BACKUP"
