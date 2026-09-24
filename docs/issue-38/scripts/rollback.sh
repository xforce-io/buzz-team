#!/usr/bin/env bash
# Issue #38 rollback from a backup-* directory produced by apply.sh
# Does NOT kill or wait for respawn. Tolerates a stale/dead 周衡 pid file.
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

echo "== resolve 周衡 pid file (exact; extras abort; dead pid OK) =="
ZH_PID_FILE=$(zhou_pid_file)
echo "周衡 pid file: $ZH_PID_FILE"
ZHOU_PID_NOW=$(python3 -c "import json; print(json.load(open(r'''$ZH_PID_FILE'''))['pid'])")
if kill -0 "$ZHOU_PID_NOW" 2>/dev/null; then
  echo "周衡 pid $ZHOU_PID_NOW currently alive (will NOT kill)"
else
  echo "NOTE: 周衡 pid $ZHOU_PID_NOW is dead/stale — continuing rollback (no kill path)"
fi

echo "== snapshot other seats before rollback (read-only) =="
TMP_OTHERS=$(mktemp)
snapshot_other_pids "$TMP_OTHERS"

eval "$(grep -E '^PJ_PRIVATE_KEY=' /Users/xupeng/.local/share/buzz/config/agents.env | sed 's/^PJ_PRIVATE_KEY=/BUZZ_PRIVATE_KEY=/')"
export PATH="/Users/xupeng/lab/buzz/bin:$PATH"
export BUZZ_RELAY_URL="${BUZZ_RELAY_URL:-ws://127.0.0.1:3000}"

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

record_config_written_at "$BACKUP"

echo "== verify other seats untouched (read-only; no kill) =="
verify_other_pids_unchanged "$TMP_OTHERS"
rm -f "$TMP_OTHERS"

cat <<MSG

========== ROLLBACK CONFIG DONE — NO KILL / NO RESPAWN WAIT ==========
Restored from: $BACKUP

REQUIRED NEXT STEP (peng must be present):
  If 周衡 was restarted earlier with the NEW (medium/180) config, ask peng to
  restart ONLY 周衡 from Buzz Desktop AGAIN so ACP loads the restored
  low/1500/7200 config. (Desktop does NOT auto-respawn; scripts do not kill.)

After Desktop restart, verify:
  docs/issue-38/scripts/verify-after-restart.sh $BACKUP --expect before

Expected verify: doctor 9/9; 周衡 NEW alive pid; effort=low idle=1500;
other 8 pids unchanged vs snapshot taken at rollback start.
======================================================================
MSG
