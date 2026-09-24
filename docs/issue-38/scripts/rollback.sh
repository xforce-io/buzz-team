#!/usr/bin/env bash
# Issue #38 rollback from a backup-* directory produced by apply.sh
set -euo pipefail
BACKUP=${1:?usage: rollback.sh /Users/xupeng/lab/buzz/evidence/issue-38/backup-<ts>}
PUB=51fb6cd8eb6a72674998d5be5b1e8e826e2d60c870337cffc3278225e4297d9e
WF_ID=f5cc62c0-3756-419e-8a3f-8e694df2e93e
CH_ID=9bdc9fa2-48b7-4352-8b1f-7baf70ba6bd3
INSTANCE=/Users/xupeng/lab/buzz
MA="${HOME}/Library/Application Support/xyz.block.buzz.app/agents/managed-agents.json"
PID_DIR="${HOME}/Library/Application Support/xyz.block.buzz.app/agents/agent-pids"
ID_ROOT="${HOME}/.local/share/buzz/agent-runtime/identities/a558771623f29898/${PUB}/workspace"
PJ_MD=/Users/xupeng/lab/buzz-team/team/prompts/pj.md
INSTR="${INSTANCE}/private/instructions-1.md"

if [[ "${ISSUE38_I_UNDERSTAND_LIVE:-}" != "yes" ]]; then
  echo "Refusing: set ISSUE38_I_UNDERSTAND_LIVE=yes" >&2
  exit 2
fi
test -f "$BACKUP/managed-agents.json"
test -f "$BACKUP/pj.md"
test -f "$BACKUP/AGENTS.md"
test -f "$BACKUP/instructions-1.md"
test -f "$BACKUP/workflow-before.yaml"

cp "$BACKUP/managed-agents.json" "$MA"
cp "$BACKUP/pj.md" "$PJ_MD"
cp "$BACKUP/AGENTS.md" "$ID_ROOT/AGENTS.md"
cp "$BACKUP/instructions-1.md" "$INSTR"

eval "$(grep -E '^PJ_PRIVATE_KEY=' /Users/xupeng/.local/share/buzz/config/agents.env | sed 's/^PJ_PRIVATE_KEY=/BUZZ_PRIVATE_KEY=/')"
export PATH="/Users/xupeng/lab/buzz/bin:$PATH"
export BUZZ_RELAY_URL="${BUZZ_RELAY_URL:-ws://127.0.0.1:3000}"
buzz workflows update --channel "$CH_ID" --workflow "$WF_ID" --yaml "$BACKUP/workflow-before.yaml"

ZH_PID_FILE=$(ls "$PID_DIR"/${PUB}__*.json 2>/dev/null | head -1 || true)
if [[ -z "${ZH_PID_FILE}" ]]; then
  ZH_PID_FILE=$(ls "$PID_DIR"/${PUB}*.json 2>/dev/null | head -1)
fi
OLD_PID=$(python3 -c "import json;print(json.load(open('$ZH_PID_FILE'))['pid'])")
kill "$OLD_PID"
for i in $(seq 1 60); do
  sleep 1
  NEW_PID=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1])).get('pid',''))" "$ZH_PID_FILE" 2>/dev/null || true)
  if [[ -n "$NEW_PID" && "$NEW_PID" != "$OLD_PID" ]] && ps -p "$NEW_PID" >/dev/null 2>&1; then
    echo "周衡 rolled-back respawn pid=$NEW_PID"
    break
  fi
  if [[ "$i" -eq 60 ]]; then
    echo "respawn timeout" >&2
    exit 1
  fi
done
echo "rollback complete from $BACKUP"
