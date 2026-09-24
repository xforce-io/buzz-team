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
# The file stores UTC ISO-8601 text; verify converts it to epoch before comparing.
# ONLY this stamp is authoritative for Mode B start-time checks.
# Never use managed-agents.json mtime: Desktop rewrites that file on start
# (last_started_at / updated_at), so its mtime is NOT config-write time (A6/A11).
record_config_written_at() {
  local backup=$1
  local stamp
  stamp=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  printf '%s\n' "$stamp" > "$backup/config_written_at.txt"
  echo "config_written_at=$stamp (UTC) -> $backup/config_written_at.txt"
}

# ---- Desktop process helpers (macOS Buzz.app) ----
# Matcher: prefer Buzz.app MacOS binary path; fall back to exact process name "Buzz".
# No prior matcher existed in these scripts; keep narrow to avoid ACP python wrappers.
# Escape hatch: SKIP_DESKTOP_CHECK=1 (documented in RUNBOOK).

desktop_main_pids() {
  local pids=""
  pids=$(pgrep -f '/Buzz\.app/Contents/MacOS/' 2>/dev/null || true)
  if [[ -z "$pids" ]]; then
    pids=$(pgrep -x 'Buzz' 2>/dev/null || true)
  fi
  printf '%s\n' "$pids" | awk 'NF' | sort -u
}

require_desktop_not_running() {
  if [[ "${SKIP_DESKTOP_CHECK:-}" == "1" ]]; then
    echo "WARN: SKIP_DESKTOP_CHECK=1 — skipping Desktop-not-running check" >&2
    return 0
  fi
  local pids
  pids=$(desktop_main_pids | tr '\n' ' ' | sed 's/[[:space:]]*$//')
  if [[ -n "$pids" ]]; then
    echo "ABORT: Buzz Desktop appears running (pids: $pids)." >&2
    echo "Cmd+Q fully quit Desktop first, then re-run. Override: SKIP_DESKTOP_CHECK=1 (see RUNBOOK)." >&2
    return 1
  fi
  echo "Desktop not running OK"
}

# Snapshot ALL TEAM seat pids (including 周衡) as name<TAB>pid lines.
snapshot_all_team_pids() {
  local out=$1
  local f base
  : > "$out"
  for f in "$PID_DIR"/*__"${TEAM}".json; do
    [[ -e "$f" ]] || continue
    base=$(basename "$f")
    python3 -c "import json,sys; print(sys.argv[1]+chr(9)+str(json.load(open(sys.argv[2]))['pid']))" "$base" "$f" >> "$out"
  done
  local n
  n=$(wc -l < "$out" | tr -d ' ')
  echo "all TEAM seats recorded: $n"
  if [[ "$n" -ne 9 ]]; then
    echo "WARN: expected 9 TEAM seats, got $n" >&2
  fi
}

# Post-restart pid check for verify-after-restart.sh.
# mode=single: other 8 pids unchanged+alive; 周衡 must be new (caller checks).
# mode=app:    all 9 pids changed+alive.
# Mismatch with declared mode => FAIL (no auto-guess).
verify_restart_pids() {
  local mode=$1
  local all_before=$2
  local zhou_old=$3
  local zhou_new=$4
  case "$mode" in
    single|app) ;;
    *) echo "ABORT: --restart-mode must be single|app, got: $mode" >&2; return 1 ;;
  esac
  python3 - "$mode" "$all_before" "${zhou_old:-}" "$zhou_new" "$PID_DIR" "$TEAM" "$PUB" <<'PY'
import json, os, sys
from pathlib import Path

mode, before_path, zhou_old, zhou_new, pid_dir, team, pub = sys.argv[1:8]
zhou_file = f"{pub}__{team}.json"

before = {}
for line in Path(before_path).read_text().splitlines():
    line = line.strip()
    if not line:
        continue
    name, pid = line.split("\t", 1)
    before[name] = int(pid)

if len(before) != 9:
    print(f"FAIL: baseline all-pids-before has {len(before)} seats, want 9", file=sys.stderr)
    sys.exit(1)

live = {}
for f in Path(pid_dir).glob(f"*__{team}.json"):
    name = f.name
    pid = json.loads(f.read_text())["pid"]
    try:
        os.kill(pid, 0)
        alive = True
    except OSError:
        alive = False
    live[name] = (pid, alive)

if len(live) != 9:
    print(f"FAIL: live TEAM seats={len(live)}, want 9", file=sys.stderr)
    sys.exit(1)

dead = [n for n, (_pid, alive) in live.items() if not alive]
if dead:
    print("FAIL: dead seat pid(s): " + ", ".join(f"{n}:{live[n][0]}" for n in dead), file=sys.stderr)
    sys.exit(1)

changed = []
unchanged = []
for name, old_pid in before.items():
    if name not in live:
        print(f"FAIL: missing live pid file for {name}", file=sys.stderr)
        sys.exit(1)
    new_pid = live[name][0]
    if new_pid == old_pid:
        unchanged.append(f"{name}:{old_pid}")
    else:
        changed.append(f"{name}:{old_pid}->{new_pid}")

zhou_key = zhou_file
if zhou_key not in before or zhou_key not in live:
    print(f"FAIL: 周衡 pid file {zhou_key} missing from before/live", file=sys.stderr)
    sys.exit(1)

if zhou_old and str(live[zhou_key][0]) == str(zhou_old):
    print(f"FAIL: 周衡 pid still equals pre-quit baseline {zhou_old}", file=sys.stderr)
    sys.exit(1)
if live[zhou_key][0] == before[zhou_key]:
    print(f"FAIL: 周衡 pid unchanged vs all-pids-before ({before[zhou_key]})", file=sys.stderr)
    sys.exit(1)

others_changed = [c for c in changed if not c.startswith(zhou_key + ":")]
others_unchanged = [u for u in unchanged if not u.startswith(zhou_key + ":")]

if mode == "single":
    if others_changed:
        print("FAIL: --restart-mode single but other seat pid(s) changed:", file=sys.stderr)
        print("  " + "\n  ".join(others_changed), file=sys.stderr)
        sys.exit(1)
    if len(others_unchanged) != 8:
        print(
            f"FAIL: --restart-mode single expected 8 other seats unchanged, got {len(others_unchanged)}",
            file=sys.stderr,
        )
        sys.exit(1)
    print("restart_mode=single OK: other 8 pids unchanged+alive; 周衡 new+alive")
elif mode == "app":
    if others_unchanged:
        print("FAIL: --restart-mode app but other seat pid(s) UNCHANGED:", file=sys.stderr)
        print("  " + "\n  ".join(others_unchanged), file=sys.stderr)
        sys.exit(1)
    if len(changed) != 9:
        print(
            f"FAIL: --restart-mode app expected all 9 pids changed, got {len(changed)}",
            file=sys.stderr,
        )
        print("  changed: " + ", ".join(changed), file=sys.stderr)
        sys.exit(1)
    print("restart_mode=app OK: all 9 pids changed+alive")
PY
}
