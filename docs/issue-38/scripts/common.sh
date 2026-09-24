# shellcheck shell=bash
# Shared constants/helpers for Issue #38 apply/rollback (周衡 only).

PUB=51fb6cd8eb6a72674998d5be5b1e8e826e2d60c870337cffc3278225e4297d9e
# Desktop agent-pids team key (Hogan live-verified 2026-09-24)
TEAM=a558771623f298980db444a8406459dff1cbd20f264a72d00ffaca270c0fa16f
# Identity workspace dir uses the short team id prefix
ID_TEAM=a558771623f29898
PIN_SHORT=046ac43
PIN_FULL=046ac4345647ea6bc9c57bbf91ddb556a91694cd

WF_ID=f5cc62c0-3756-419e-8a3f-8e694df2e93e
CH_ID=9bdc9fa2-48b7-4352-8b1f-7baf70ba6bd3
INSTANCE=/Users/xupeng/lab/buzz
MA="${HOME}/Library/Application Support/xyz.block.buzz.app/agents/managed-agents.json"
PID_DIR="${HOME}/Library/Application Support/xyz.block.buzz.app/agents/agent-pids"
ID_ROOT="${HOME}/.local/share/buzz/agent-runtime/identities/${ID_TEAM}/${PUB}/workspace"
PJ_MD=/Users/xupeng/lab/buzz-team/team/prompts/pj.md
INSTR="${INSTANCE}/private/instructions-1.md"
EXEC_WRAP=/Users/xupeng/lab/buzz/bin/agent-executor
HARNESS_WRAP=/Users/xupeng/lab/buzz/bin/agent-harness

require_live_guard() {
  if [[ "${ISSUE38_I_UNDERSTAND_LIVE:-}" != "yes" ]]; then
    echo "Refusing: set ISSUE38_I_UNDERSTAND_LIVE=yes. See docs/issue-38/RUNBOOK.md" >&2
    exit 2
  fi
}

# Fail unless thin wrappers resolve to pin 046ac43 (full SHA).
verify_thin_pin() {
  local f
  for f in "$EXEC_WRAP" "$HARNESS_WRAP"; do
    if [[ ! -f "$f" ]]; then
      echo "pin check FAIL: missing $f" >&2
      exit 1
    fi
    if ! grep -q "$PIN_FULL" "$f"; then
      echo "pin check FAIL: $f does not reference $PIN_FULL ($PIN_SHORT)" >&2
      echo "--- $f ---" >&2
      cat "$f" >&2
      exit 1
    fi
  done
  echo "pin check OK: wrappers reference $PIN_FULL"
}

# Resolve 周衡 pid file: exactly ${PUB}__${TEAM}.json; abort if any other ${PUB}__*.json.
# Does NOT require the pid to be alive (rollback must tolerate a stale/dead pid).
zhou_pid_file() {
  local exact extras f
  exact="${PID_DIR}/${PUB}__${TEAM}.json"
  if [[ ! -f "$exact" ]]; then
    echo "周衡 pid file missing: $exact" >&2
    exit 1
  fi
  extras=()
  for f in "$PID_DIR"/${PUB}__*.json; do
    [[ -e "$f" ]] || continue
    if [[ "$(basename "$f")" != "$(basename "$exact")" ]]; then
      extras+=("$f")
    fi
  done
  if ((${#extras[@]} > 0)); then
    echo "ABORT: unexpected extra ${PUB}__*.json pid file(s) (stale yuanbao/other?):" >&2
    printf '  %s\n' "${extras[@]}" >&2
    echo "Remove extras or restart only 周衡 from Desktop; refusing to proceed." >&2
    exit 1
  fi
  printf '%s\n' "$exact"
}

# Apply precondition: 周衡 ACP must be alive (doctor 9/9). Abort if pid file points at a dead process.
# Live fact: Desktop does NOT auto-respawn after kill — operator must restart 周衡 from Desktop first.
require_zhou_alive() {
  local zh_file old_pid blob
  zh_file=$(zhou_pid_file)
  old_pid=$(python3 -c "import json; print(json.load(open(r'''${zh_file}'''))['pid'])")
  if ! kill -0 "$old_pid" 2>/dev/null; then
    echo "ABORT: 周衡 pid $old_pid from $zh_file is NOT alive." >&2
    echo "Precondition: doctor 9/9 (all seats up). Ask peng to restart ONLY 周衡 from Buzz Desktop, then re-run apply." >&2
    return 1
  fi
  blob=$(ps eww -p "$old_pid" 2>/dev/null || true)
  if [[ -z "$blob" || "$blob" != *"$PUB"* ]]; then
    echo "ABORT: pid $old_pid is alive but env/cmdline does not contain 周衡 pubkey $PUB." >&2
    echo "Ask peng to restart ONLY 周衡 from Desktop, then re-run apply." >&2
    return 1
  fi
  echo "周衡 ACP alive OK: pid=$old_pid (pubkey confirmed)" >&2
  printf '%s\n' "$old_pid"
}

# Enforce doctor 9/9: every *__${TEAM}.json pid must be alive (kill -0). Abort otherwise.
require_all_team_alive() {
  local f base pid n=0
  local -a dead=()
  for f in "$PID_DIR"/*__"${TEAM}".json; do
    [[ -e "$f" ]] || continue
    base=$(basename "$f")
    pid=$(python3 -c "import json; print(json.load(open(r'''${f}'''))['pid'])")
    n=$((n+1))
    if ! kill -0 "$pid" 2>/dev/null; then
      dead+=("$base:$pid")
    fi
  done
  if [[ "$n" -ne 9 ]]; then
    echo "ABORT: expected 9 *__${TEAM}.json seats, found $n. doctor 9/9 required before apply." >&2
    return 1
  fi
  if ((${#dead[@]} > 0)); then
    echo "ABORT: doctor 9/9 failed — dead seat pid(s):" >&2
    printf '  %s\n' "${dead[@]}" >&2
    echo "Ask peng to restart dead seats from Desktop (prefer ONLY those seats), then re-run apply." >&2
    return 1
  fi
  echo "doctor 9/9 OK: all $n TEAM seat pids alive" >&2
}

# Other seats on this TEAM, excluding 周衡's exact file. Prints "name\tpid" lines.
list_other_team_pids() {
  local f base
  for f in "$PID_DIR"/*__"${TEAM}".json; do
    [[ -e "$f" ]] || continue
    base=$(basename "$f")
    if [[ "$base" == "${PUB}__${TEAM}.json" ]]; then
      continue
    fi
    python3 -c "import json,sys; print(sys.argv[1]+'\t'+str(json.load(open(sys.argv[2]))['pid']))" "$base" "$f"
  done
}

snapshot_other_pids() {
  local out=$1
  list_other_team_pids > "$out"
  local n
  n=$(wc -l < "$out" | tr -d ' ')
  echo "other TEAM seats recorded: $n"
  if [[ "$n" -ne 8 ]]; then
    echo "WARN: expected 8 other seats on TEAM, got $n" >&2
  fi
}

verify_other_pids_unchanged() {
  local before=$1
  local after
  after=$(mktemp)
  list_other_team_pids > "$after"
  if ! diff -u "$before" "$after"; then
    echo "ABORT: other seat pids changed" >&2
    rm -f "$after"
    exit 1
  fi
  rm -f "$after"
  echo "other 8 seats pids unchanged OK"
}

# Patch only the 周衡 row (by full pubkey) inside managed-agents.json.
restore_zhou_row_from_file() {
  local row_file=$1
  python3 -c "
import json, sys
from pathlib import Path
ma_path=Path(r'''$MA''')
row_path=Path(sys.argv[1])
agents=json.loads(ma_path.read_text())
saved=json.loads(row_path.read_text())
pub=r'''$PUB'''
idx=None
for i,a in enumerate(agents):
    if a.get('pubkey')==pub or (a.get('name')=='周衡' and (a.get('pubkey') or '').startswith('51fb6cd8')):
        idx=i; break
if idx is None:
    raise SystemExit('周衡 row not found in live managed-agents.json — abort')
agents[idx]=saved
ma_path.write_text(json.dumps(agents, ensure_ascii=False, indent=2)+chr(10))
print('restored 周衡 row only from', row_path)
" "$row_file"
}

# Record when config was written so verify-after-restart can use start-time fallback.
record_config_written_at() {
  local backup=$1
  local stamp
  stamp=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  printf '%s\n' "$stamp" > "$backup/config_written_at.txt"
  echo "config_written_at=$stamp (UTC) -> $backup/config_written_at.txt"
}
