#!/usr/bin/env bash
# Issue #38 live apply — 周衡 only. Do NOT run until merge gate + Hogan.
# Quit-first flow (Knox/Jenny 2026-09-24):
#   1) apply.sh --baseline-only   # Desktop UP; capture 9-seat pid baseline + snapshots
#   2) peng Cmd+Q fully quits Buzz Desktop
#   3) apply.sh --backup <dir>    # Desktop DOWN; write workflow+row+prompts; no seat-alive req
#   4) peng reopens Desktop via the proxy-fix method peng approved; then MA read-back + verify
# Does NOT kill ACP processes. Desktop must be fully quit before mutate (no escape hatch).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=common.sh
source "$(dirname "$0")/common.sh"

MODE=""
BACKUP_ARG=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --baseline-only) MODE=baseline; shift ;;
    --backup) BACKUP_ARG=${2:?}; MODE=mutate; shift 2 ;;
    --backup=*) BACKUP_ARG=${1#*=}; MODE=mutate; shift ;;
    *) echo "unknown arg: $1 (want --baseline-only | --backup <dir>)" >&2; exit 2 ;;
  esac
done
if [[ -z "$MODE" ]]; then
  echo "usage: apply.sh --baseline-only | apply.sh --backup <backup-dir>" >&2
  echo "Quit-first flow: baseline (Desktop up) → Cmd+Q → --backup (Desktop down) → reopen → verify." >&2
  exit 2
fi

require_live_guard
verify_thin_pin

# ---------- baseline-only: Desktop UP, seats alive, write backup, stop ----------
if [[ "$MODE" == "baseline" ]]; then
  echo "== baseline-only: Desktop must be UP with doctor 9/9 =="
  echo "== resolve 周衡 pid file (exact PUB__TEAM; abort on extras) =="
  ZH_PID_FILE=$(zhou_pid_file)
  echo "周衡 pid file: $ZH_PID_FILE"
  echo "== precondition: doctor 9/9 (all TEAM seat pids alive) =="
  require_all_team_alive || exit 1
  echo "== precondition: 周衡 ACP pubkey-confirmed =="
  ZHOU_PID_BEFORE=$(require_zhou_alive) || exit 1

echo "== assert live workflow == staged before =="
eval "$(grep -E '^PJ_PRIVATE_KEY=' /Users/xupeng/.local/share/buzz/config/agents.env | sed 's/^PJ_PRIVATE_KEY=/BUZZ_PRIVATE_KEY=/')"
export PATH="/Users/xupeng/lab/buzz/bin:$PATH"
export BUZZ_RELAY_URL="${BUZZ_RELAY_URL:-ws://127.0.0.1:3000}"
LIVE_GET=$(mktemp)
assert_live_workflow_matches_before "$ROOT" "$LIVE_GET"

echo "== preflight: active 周衡 row (idle=1500, effort=low) =="
python3 -c "
import json
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
  mkdir -p "$BACKUP/agent-pids/before"
  echo "BACKUP=$BACKUP"
  printf '%s\n' "$ZHOU_PID_BEFORE" > "$BACKUP/zhou-pid-before.txt"

  echo "== snapshot before (pids + MA + prompts + workflow) =="
  cp -R "$PID_DIR"/. "$BACKUP/agent-pids/before/" || true
  snapshot_other_pids "$BACKUP/others-before.tsv"
  snapshot_all_team_pids "$BACKUP/all-pids-before.tsv"
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
p.write_text(c if c.endswith(chr(10)) else c+chr(10))
print('saved workflow-live-before.yaml from live get')
"
  rm -f "$LIVE_GET"
  echo "== positive control: identity scan requires 9/9 seats (BUZZ_RUNTIME_ID=\${ID_TEAM}/<pubkey>) =="
  run_seat_scan_positive_control "$BACKUP" || exit 1
  record_baseline_at "$BACKUP"

  cat <<MSG

========== BASELINE CAPTURED — DO NOT MUTATE YET ==========
BACKUP=$BACKUP

REQUIRED NEXT:
  1) peng: Cmd+Q fully quit Buzz Desktop (all 9 ACP pids will go away)
  2) operator: ISSUE38_I_UNDERSTAND_LIVE=yes docs/issue-38/scripts/apply.sh --backup $BACKUP
  3) after apply: peng reopens Desktop using the proxy-fix method peng approved
     (see RUNBOOK proxy row); then MA read-back + verify --restart-mode app
===========================================================
MSG
  exit 0
fi

# ---------- mutate: Desktop DOWN, use existing backup, no seat-alive requirement ----------
BACKUP=$BACKUP_ARG
test -d "$BACKUP"
test -f "$BACKUP/zhou-pid-before.txt"
test -f "$BACKUP/others-before.tsv"
test -f "$BACKUP/all-pids-before.tsv"
test -f "$BACKUP/zhouheng-row-before.json"
test -f "$BACKUP/workflow-live-before.yaml"
test -f "$BACKUP/pj.md"
test -f "$BACKUP/AGENTS.md"
test -f "$BACKUP/instructions-1.md"

echo "== mutate phase: require Desktop NOT running (identity scan + positive-control gate) =="
require_desktop_not_running "$BACKUP" || exit 1

echo "== mutate phase: require baseline freshness (max age ${BASELINE_MAX_AGE_S}s) =="
require_baseline_fresh "$BACKUP" || exit 1

echo "== resolve 周衡 pid file path (exact; extras abort; dead pid OK while Desktop quit) =="
ZH_PID_FILE=$(zhou_pid_file)
echo "周衡 pid file: $ZH_PID_FILE (pid may be stale/dead — expected after Cmd+Q)"

APPLY_STEP="mutate-init"
MUTATED=0
APPLY_FAIL_REPORTED=0
apply_fail_report() {
  local ec=${1:-1}
  [[ "${APPLY_FAIL_REPORTED}" -eq 1 ]] && return 0
  APPLY_FAIL_REPORTED=1
  echo "APPLY FAILED (exit=$ec) at step: ${APPLY_STEP:-unknown}" >&2
  echo "BACKUP=$BACKUP" >&2
  echo "Rollback command:" >&2
  echo "  ISSUE38_I_UNDERSTAND_LIVE=yes docs/issue-38/scripts/rollback.sh --backup $BACKUP" >&2
  if [[ "${MUTATED}" -eq 1 ]]; then
    if [[ ! -f "$BACKUP/config_written_at.txt" ]]; then
      record_config_written_at "$BACKUP" || true
    fi
    echo "NOTE: mutations may have occurred; config_written_at recorded for Mode B verify." >&2
  fi
}
trap 'ec=$?; apply_fail_report "$ec"; exit "$ec"' ERR
trap 'ec=$?; [[ $ec -ne 0 ]] && apply_fail_report "$ec"' EXIT

eval "$(grep -E '^PJ_PRIVATE_KEY=' /Users/xupeng/.local/share/buzz/config/agents.env | sed 's/^PJ_PRIVATE_KEY=/BUZZ_PRIVATE_KEY=/')"
export PATH="/Users/xupeng/lab/buzz/bin:$PATH"
export BUZZ_RELAY_URL="${BUZZ_RELAY_URL:-ws://127.0.0.1:3000}"

echo "== mutate phase: require relay :3000 listening (A14) =="
require_relay_3000_listening || exit 1

echo "== mutate phase: re-assert live workflow == staged before (before any write) =="
assert_live_workflow_matches_before "$ROOT" || exit 1

echo "== preflight: on-disk 周衡 row still idle=1500 effort=low (pre-patch) =="
python3 -c "
import json
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
    raise SystemExit('active 周衡 row (idle=1500,effort=low) not found on disk — abort before mutate')
print('preflight OK: on-disk 周衡 row still low/1500')
"

APPLY_STEP="workflow-update"
echo "== update workflow body FIRST (YAML content via cat; owner unchanged) =="
AFTER_WF="$ROOT/after/workflow.yaml"
test -f "$AFTER_WF"
buzz workflows update --channel "$CH_ID" --workflow "$WF_ID" --yaml "$(cat "$AFTER_WF")"
MUTATED=1
# F5: record immediately after FIRST successful mutation
record_config_written_at "$BACKUP"
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
    sys.exit(1)
print('workflow read-back matches after/workflow.yaml OK')
" "$BACKUP/workflow-get-after.json" "$AFTER_WF"

# ---- only after workflow success: local patches ----
APPLY_STEP="patch-managed-agents"
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
    if x in ('--reasoning-effort','--reasoning_effort') and i+1 < len(args):
        args[i+1]='medium'
row['agent_args']=args
row['system_prompt']=after_prompt
agents[idx]=row
ma_path.write_text(json.dumps(agents, ensure_ascii=False, indent=2)+chr(10))
print('patched 周衡 row only idle=180 effort=medium prompt_len', len(after_prompt))
"

APPLY_STEP="patch-prompt-files"
echo "== patch pj.md / AGENTS.md / instructions-1.md =="
cp "$ROOT/after/pj.md" "$PJ_MD"
cp "$ROOT/after/AGENTS.md" "$ID_ROOT/AGENTS.md"
cp "$ROOT/after/instructions-1.md" "$INSTR"

APPLY_STEP="read-back-verify"
echo "== read-back verify 周衡 row (medium/180) + prompt files =="
python3 -c "
import json
from pathlib import Path
agents=json.loads(Path(r'''$MA''').read_text())
pub=r'''$PUB'''
row=next(a for a in agents if a.get('pubkey')==pub or a.get('name')=='周衡')
env=row.get('env_vars') or {}
assert row.get('idle_timeout_seconds')==180, row.get('idle_timeout_seconds')
assert env.get('BUZZ_ACP_EFFORT_LEVEL')=='medium', env.get('BUZZ_ACP_EFFORT_LEVEL')
assert env.get('BUZZ_ACP_IDLE_TIMEOUT') in ('180', 180), env.get('BUZZ_ACP_IDLE_TIMEOUT')
print('managed-agents 周衡 read-back OK: idle=180 effort=medium')
for label, path, src in [
    ('pj.md', r'''$PJ_MD''', r'''$ROOT/after/pj.md'''),
    ('AGENTS.md', r'''$ID_ROOT'''+'/AGENTS.md', r'''$ROOT/after/AGENTS.md'''),
    ('instructions-1.md', r'''$INSTR''', r'''$ROOT/after/instructions-1.md'''),
]:
    if Path(path).read_text()!=Path(src).read_text():
        raise SystemExit(f'{label} read-back mismatch')
    print(f'{label} read-back OK')
"

APPLY_STEP="record-config-after-local"
# F5: refresh timestamp after local writes complete
record_config_written_at "$BACKUP"

APPLY_STEP="done"
trap - ERR

cat <<MSG

========== APPLY CONFIG DONE — DESKTOP STILL QUIT ==========
BACKUP=$BACKUP

Rollback if needed (Desktop must stay quit):
  ISSUE38_I_UNDERSTAND_LIVE=yes docs/issue-38/scripts/rollback.sh --backup $BACKUP

REQUIRED NEXT (peng + operator):
  1) peng reopens Buzz Desktop using the method peng approved for the 2026-09-24
     proxy fix (see RUNBOOK proxy assumption row). Do NOT assume Dock/Launchpad
     is safe — Dock may still inject dead HTTP(S)_PROXY=127.0.0.1:6478.
  2) GATE: confirm Desktop main process env HTTP(S)_PROXY points at the listening
     system proxy (127.0.0.1:9567), and
     python -m buzz_team --instance /Users/xupeng/lab/buzz doctor
     is ok with NO proxy_contrast.
  3) GATE: read back managed-agents.json 周衡 row — must still be effort=medium
     idle=180 max_turn=7200 (not overwritten by stale in-memory values; see A11).
     If overwritten: STOP, report, do not re-apply; run rollback flow.
  4) verify:
       docs/issue-38/scripts/verify-after-restart.sh $BACKUP --expect after --restart-mode app
===========================================================
MSG
