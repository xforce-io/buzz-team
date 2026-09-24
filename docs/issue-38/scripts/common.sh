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
zhou_pid_file() {
  local exact extras
  exact="${PID_DIR}/${PUB}__${TEAM}.json"
  if [[ ! -f "$exact" ]]; then
    echo "周衡 pid file missing: $exact" >&2
    exit 1
  fi
  # shopt nullglob
  extras=()
  local f
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

# Kill 周衡 ACP only if: (a) pid from exact file (b) kill -0 alive (c) env/cmdline contains full PUB.
safe_kill_zhou() {
  local zh_file old_pid blob
  zh_file=$(zhou_pid_file)
  old_pid=$(python3 -c "import json; print(json.load(open(r'''$zh_file'''))['pid'])")
  if ! kill -0 "$old_pid" 2>/dev/null; then
    echo "ABORT: pid $old_pid from $zh_file is not alive (kill -0 failed). Restart ONLY 周衡 from Desktop." >&2
    exit 1
  fi
  blob=$(ps eww -p "$old_pid" 2>/dev/null || true)
  if [[ -z "$blob" || "$blob" != *"$PUB"* ]]; then
    echo "ABORT: pid $old_pid is alive but env/cmdline does not contain 周衡 pubkey $PUB." >&2
    echo "Refusing to kill (stale pid reuse risk). Restart ONLY 周衡 from Desktop." >&2
    exit 1
  fi
  echo "safe-kill 周衡 pid=$old_pid file=$(basename "$zh_file") (pubkey confirmed in process)"
  kill "$old_pid"
  # Wait for respawn with new pid in same exact file
  local i new_pid
  for i in $(seq 1 60); do
    sleep 1
    new_pid=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('pid',''))" "$zh_file" 2>/dev/null || true)
    if [[ -n "$new_pid" && "$new_pid" != "$old_pid" ]] && kill -0 "$new_pid" 2>/dev/null; then
      blob=$(ps eww -p "$new_pid" 2>/dev/null || true)
      if [[ "$blob" == *"$PUB"* ]]; then
        echo "周衡 respawned pid=$new_pid after ${i}s"
        return 0
      fi
    fi
  done
  echo "TIMEOUT waiting for Desktop to respawn 周衡. Start ONLY 周衡 from Desktop UI (do not relaunch app)." >&2
  exit 1
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
# Usage: patch_zhou_row <python-snippet that receives `row` dict and mutates it>
# Or restore from a saved row JSON file: restore_zhou_row <row.json>
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
# Replace only this index; do not touch other seats
agents[idx]=saved
ma_path.write_text(json.dumps(agents, ensure_ascii=False, indent=2)+chr(10))
print('restored 周衡 row only from', row_path)
" "$row_file"
}
