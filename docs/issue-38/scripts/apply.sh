#!/usr/bin/env bash
# Issue #38 live apply — 周衡 only. Do NOT run until merge gate + Hogan.
# Workflow update FIRST (YAML CONTENT via $(cat)); local patches only if that succeeds.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=common.sh
source "$(dirname "$0")/common.sh"

require_live_guard
verify_thin_pin

echo "== resolve 周衡 pid file (exact PUB__TEAM; abort on extras) =="
ZH_PID_FILE=$(zhou_pid_file)
echo "周衡 pid file: $ZH_PID_FILE"

echo "== assert live workflow == staged before =="
eval "$(grep -E '^PJ_PRIVATE_KEY=' /Users/xupeng/.local/share/buzz/config/agents.env | sed 's/^PJ_PRIVATE_KEY=/BUZZ_PRIVATE_KEY=/')"
export PATH="/Users/xupeng/lab/buzz/bin:$PATH"
export BUZZ_RELAY_URL="${BUZZ_RELAY_URL:-ws://127.0.0.1:3000}"
LIVE_GET=$(mktemp)
buzz workflows get --workflow "$WF_ID" > "$LIVE_GET"
python3 -c "
import json, sys
from pathlib import Path
live=json.loads(Path(sys.argv[1]).read_text())['content']
staged=Path(sys.argv[2]).read_text()
def norm(s):
    return s.replace('\r\n','\n').strip()+'\n'
if norm(live)!=norm(staged):
    print('ABORT: live workflow content != docs/issue-38/before/workflow.yaml', file=sys.stderr)
    print('--- live ---', file=sys.stderr); print(norm(live)[:500], file=sys.stderr)
    print('--- staged ---', file=sys.stderr); print(norm(staged)[:500], file=sys.stderr)
    sys.exit(1)
print('live workflow matches staged before OK')
" "$LIVE_GET" "$ROOT/before/workflow.yaml"

echo "== preflight: active 周衡 row (idle=1500, effort=low) =="
python3 -c "
import json,sys
from pathlib import Path
agents=json.loads(Path(r'''$MA''').read_text())
pub=r'''$PUB'''
target=None
for a in agents:
    env=a.get('env_vars') or {}
    if (a.get('pubkey')==pub) and a.get('idle_timeout_seconds')==1500 and env.get('BUZZ_ACP_EFFORT_LEVEL')=='low':
        target=a; break
if target is None:
    for a in agents:
        env=a.get('env_vars') or {}
        if a.get('name')=='周衡' and a.get('idle_timeout_seconds')==1500 and env.get('BUZZ_ACP_EFFORT_LEVEL')=='low':
            target=a; break
if target is None:
    raise SystemExit('active 周衡 row (idle=1500,effort=low) not found — abort before backup')
if not (target.get('pubkey') or '').startswith('51fb6cd8'):
    raise SystemExit('pubkey mismatch on candidate row')
print('preflight OK: 周衡 active row found')
"

# ---- guards passed: create backup (read-only snapshots; no mutation yet) ----
TS=$(date +%Y%m%d-%H%M%S)
BACKUP=/Users/xupeng/lab/buzz/evidence/issue-38/backup-${TS}
mkdir -p "$BACKUP/agent-pids/before" "$BACKUP/agent-pids/after"
echo "BACKUP=$BACKUP"

echo "== snapshot before =="
cp -R "$PID_DIR"/. "$BACKUP/agent-pids/before/" || true
snapshot_other_pids "$BACKUP/others-before.tsv"
cp "$MA" "$BACKUP/managed-agents.full.json"
python3 -c "
import json
from pathlib import Path
agents=json.loads(Path(r'''$MA''').read_text())
pub=r'''$PUB'''
row=None
for a in agents:
    if a.get('pubkey')==pub or (a.get('name')=='周衡' and (a.get('pubkey') or '').startswith('51fb6cd8')):
        row=a; break
assert row is not None
Path(r'''$BACKUP/zhouheng-row-before.json''').write_text(json.dumps(row, ensure_ascii=False, indent=2)+chr(10))
print('saved 周衡 row before')
"
cp "$PJ_MD" "$BACKUP/pj.md"
cp "$ID_ROOT/AGENTS.md" "$BACKUP/AGENTS.md"
cp "$INSTR" "$BACKUP/instructions-1.md"
cp "$LIVE_GET" "$BACKUP/workflow-get.json"
python3 -c "
import json
from pathlib import Path
c=json.loads(Path(r'''$BACKUP/workflow-get.json''').read_text())['content']
p=Path(r'''$BACKUP/workflow-live-before.yaml''')
p.write_text(c if c.endswith('\n') else c+'\n')
print('saved workflow-live-before.yaml from live get')
"
rm -f "$LIVE_GET"

# ---- FIRST mutation: workflow body (YAML CONTENT, not path) ----
# buzz workflows update --yaml <YAML> expects the definition string, not a file path.
echo "== update workflow body FIRST (YAML content via cat; owner unchanged) =="
AFTER_WF="$ROOT/after/workflow.yaml"
test -f "$AFTER_WF"
buzz workflows update --channel "$CH_ID" --workflow "$WF_ID" --yaml "$(cat "$AFTER_WF")"
buzz workflows get --workflow "$WF_ID" > "$BACKUP/workflow-get-after.json"
python3 -c "
import json, sys
from pathlib import Path
live=json.loads(Path(sys.argv[1]).read_text())['content']
want=Path(sys.argv[2]).read_text()
def norm(s):
    return s.replace('\r\n','\n').strip()+'\n'
if norm(live)!=norm(want):
    print('ABORT: post-update workflow != docs/issue-38/after/workflow.yaml — local files NOT patched', file=sys.stderr)
    print('--- live ---', file=sys.stderr); print(norm(live)[:500], file=sys.stderr)
    print('--- want ---', file=sys.stderr); print(norm(want)[:500], file=sys.stderr)
    sys.exit(1)
print('workflow read-back matches after/workflow.yaml OK')
" "$BACKUP/workflow-get-after.json" "$AFTER_WF"

# ---- only after workflow success: local patches ----
echo "== patch managed-agents (周衡 row only; read-modify-write) =="
python3 -c "
import json
from pathlib import Path
ma_path=Path(r'''$MA''')
agents=json.loads(ma_path.read_text())
after_prompt=Path(r'''$ROOT/after/system_prompt.md''').read_text()
pub=r'''$PUB'''
idx=None
for i,a in enumerate(agents):
    env=a.get('env_vars') or {}
    if a.get('pubkey')==pub and a.get('idle_timeout_seconds')==1500 and env.get('BUZZ_ACP_EFFORT_LEVEL')=='low':
        idx=i; break
if idx is None:
    for i,a in enumerate(agents):
        env=a.get('env_vars') or {}
        if a.get('name')=='周衡' and a.get('idle_timeout_seconds')==1500 and env.get('BUZZ_ACP_EFFORT_LEVEL')=='low':
            idx=i; break
if idx is None:
    raise SystemExit('active 周衡 row disappeared — abort, no write')
row=agents[idx]
row['idle_timeout_seconds']=180
row.setdefault('env_vars',{})
row['env_vars']['BUZZ_ACP_EFFORT_LEVEL']='medium'
row['env_vars']['BUZZ_ACP_IDLE_TIMEOUT']='180'
args=list(row.get('agent_args') or [])
for i,x in enumerate(args):
    if x=='--reasoning-effort' and i+1 < len(args):
        args[i+1]='medium'
row['agent_args']=args
row['system_prompt']=after_prompt
agents[idx]=row
ma_path.write_text(json.dumps(agents, ensure_ascii=False, indent=2)+chr(10))
print('patched 周衡 row only idle=180 effort=medium prompt_len', len(after_prompt))
"

echo "== patch pj.md / AGENTS.md / instructions-1.md =="
cp "$ROOT/after/pj.md" "$PJ_MD"
cp "$ROOT/after/AGENTS.md" "$ID_ROOT/AGENTS.md"
cp "$ROOT/after/instructions-1.md" "$INSTR"

echo "== restart 周衡 ACP only (safe kill) =="
safe_kill_zhou

echo "== verify other seats untouched =="
verify_other_pids_unchanged "$BACKUP/others-before.tsv"
cp -R "$PID_DIR"/. "$BACKUP/agent-pids/after/" || true

echo "BACKUP=$BACKUP"
echo "apply complete — run doctor+bind per RUNBOOK.md"
