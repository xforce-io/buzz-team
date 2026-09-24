#!/usr/bin/env bash
# Issue #38 live apply — 周衡 only. Do NOT run until merge gate + Hogan.
set -euo pipefail

WF_ID=f5cc62c0-3756-419e-8a3f-8e694df2e93e
CH_ID=9bdc9fa2-48b7-4352-8b1f-7baf70ba6bd3
PUB=51fb6cd8eb6a72674998d5be5b1e8e826e2d60c870337cffc3278225e4297d9e
INSTANCE=/Users/xupeng/lab/buzz
MA="${HOME}/Library/Application Support/xyz.block.buzz.app/agents/managed-agents.json"
PID_DIR="${HOME}/Library/Application Support/xyz.block.buzz.app/agents/agent-pids"
ID_ROOT="${HOME}/.local/share/buzz/agent-runtime/identities/a558771623f29898/${PUB}/workspace"
PJ_MD=/Users/xupeng/lab/buzz-team/team/prompts/pj.md
INSTR="${INSTANCE}/private/instructions-1.md"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TS=$(date +%Y%m%d-%H%M%S)
BACKUP=/Users/xupeng/lab/buzz/evidence/issue-38/backup-${TS}
mkdir -p "$BACKUP/agent-pids/before" "$BACKUP/agent-pids/after"

if [[ "${ISSUE38_I_UNDERSTAND_LIVE:-}" != "yes" ]]; then
  echo "Refusing: set ISSUE38_I_UNDERSTAND_LIVE=yes to apply. See docs/issue-38/RUNBOOK.md" >&2
  exit 2
fi

echo "== pin check (must remain 046ac43; bins not modified) =="
ls /Users/xupeng/lab/buzz/bin/agent-executor /Users/xupeng/lab/buzz/bin/agent-harness >/dev/null

echo "== snapshot pids before =="
cp -R "$PID_DIR"/. "$BACKUP/agent-pids/before/" || true
python3 -c "
import json
from pathlib import Path
pid_dir=Path(r'$PID_DIR')
out={}
for f in sorted(pid_dir.glob('*.json')):
    j=json.loads(f.read_text()); out[f.name[:16]]={'pid':j.get('pid'),'file':f.name}
Path(r'$BACKUP/pids-before.json').write_text(json.dumps(out,indent=2)+chr(10))
print(json.dumps(out,indent=2))
"

echo "== backup files =="
cp "$MA" "$BACKUP/managed-agents.json"
cp "$PJ_MD" "$BACKUP/pj.md"
cp "$ID_ROOT/AGENTS.md" "$BACKUP/AGENTS.md"
cp "$INSTR" "$BACKUP/instructions-1.md"
cp "$ROOT/before/workflow.yaml" "$BACKUP/workflow-before.yaml"

eval "$(grep -E '^PJ_PRIVATE_KEY=' /Users/xupeng/.local/share/buzz/config/agents.env | sed 's/^PJ_PRIVATE_KEY=/BUZZ_PRIVATE_KEY=/')"
export PATH="/Users/xupeng/lab/buzz/bin:$PATH"
export BUZZ_RELAY_URL="${BUZZ_RELAY_URL:-ws://127.0.0.1:3000}"
buzz workflows get --workflow "$WF_ID" > "$BACKUP/workflow-get.json"

echo "== patch managed-agents (周衡 active row only) =="
python3 -c "
import json
from pathlib import Path
ma_path=Path(r'$MA')
agents=json.loads(ma_path.read_text())
after_prompt=Path(r'$ROOT/after/system_prompt.md').read_text()
target=None
for a in agents:
    env=a.get('env_vars') or {}
    if a.get('name')=='周衡' and a.get('idle_timeout_seconds')==1500 and env.get('BUZZ_ACP_EFFORT_LEVEL')=='low':
        target=a; break
if target is None:
    raise SystemExit('active 周衡 row (idle=1500,effort=low) not found — abort, no write')
pub=(target.get('pubkey') or '')
if not pub.startswith('51fb6cd8'):
    raise SystemExit('pubkey mismatch: '+pub[:16])
target['idle_timeout_seconds']=180
target['env_vars']['BUZZ_ACP_EFFORT_LEVEL']='medium'
target['env_vars']['BUZZ_ACP_IDLE_TIMEOUT']='180'
args=list(target.get('agent_args') or [])
for i,x in enumerate(args):
    if x=='--reasoning-effort' and i+1 < len(args):
        args[i+1]='medium'
target['agent_args']=args
target['system_prompt']=after_prompt
ma_path.write_text(json.dumps(agents,ensure_ascii=False,indent=2)+chr(10))
print('patched 周衡 idle=180 effort=medium prompt_len', len(after_prompt))
"

echo "== patch pj.md / AGENTS.md / instructions-1.md =="
cp "$ROOT/after/pj.md" "$PJ_MD"
cp "$ROOT/after/AGENTS.md" "$ID_ROOT/AGENTS.md"
cp "$ROOT/after/instructions-1.md" "$INSTR"

echo "== update workflow body (owner unchanged) =="
buzz workflows update --channel "$CH_ID" --workflow "$WF_ID" --yaml "$ROOT/after/workflow.yaml"
buzz workflows get --workflow "$WF_ID" > "$BACKUP/workflow-get-after.json"

echo "== restart 周衡 ACP only =="
ZH_PID_FILE=$(ls "$PID_DIR"/${PUB}__*.json 2>/dev/null | head -1 || true)
if [[ -z "${ZH_PID_FILE}" ]]; then
  ZH_PID_FILE=$(ls "$PID_DIR"/${PUB}*.json 2>/dev/null | head -1 || true)
fi
if [[ -z "${ZH_PID_FILE}" ]]; then
  echo "no pid file for 周衡" >&2; exit 1
fi
OLD_PID=$(python3 -c "import json;print(json.load(open(r'$ZH_PID_FILE'))['pid'])")
echo "周衡 old pid=$OLD_PID file=$ZH_PID_FILE"
python3 -c "
import json
from pathlib import Path
pid_dir=Path(r'$PID_DIR')
others={}
for f in pid_dir.glob('*.json'):
    if f.name.startswith('$PUB'): continue
    others[f.name[:16]]=json.loads(f.read_text()).get('pid')
Path(r'$BACKUP/others-before.json').write_text(json.dumps(others,indent=2)+chr(10))
print('other seats', len(others))
"
kill "$OLD_PID"
for i in $(seq 1 60); do
  sleep 1
  NEW_PID=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1])).get('pid',''))" "$ZH_PID_FILE" 2>/dev/null || true)
  if [[ -n "$NEW_PID" && "$NEW_PID" != "$OLD_PID" ]] && ps -p "$NEW_PID" >/dev/null 2>&1; then
    echo "周衡 respawned pid=$NEW_PID after ${i}s"
    break
  fi
  if [[ "$i" -eq 60 ]]; then
    echo "TIMEOUT waiting for Desktop to respawn 周衡. Start ONLY 周衡 from Desktop UI (do not relaunch app)." >&2
    exit 1
  fi
done

echo "== verify other seats untouched =="
python3 -c "
import json,sys
from pathlib import Path
before=json.loads(Path(r'$BACKUP/others-before.json').read_text())
pid_dir=Path(r'$PID_DIR')
bad=[]
for f in pid_dir.glob('*.json'):
    if f.name.startswith('$PUB'): continue
    pid=json.loads(f.read_text()).get('pid')
    key=f.name[:16]
    if before.get(key)!=pid:
        bad.append((key, before.get(key), pid))
if bad:
    print('OTHER SEATS CHANGED', bad); sys.exit(1)
print('other 8 seats pids unchanged OK')
"

cp -R "$PID_DIR"/. "$BACKUP/agent-pids/after/" || true
echo "BACKUP=$BACKUP"
echo "apply complete — run doctor+bind per RUNBOOK.md"
