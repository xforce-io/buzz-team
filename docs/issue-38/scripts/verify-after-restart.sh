#!/usr/bin/env bash
# Read-only post-Desktop-restart verification for Issue #38.
# Usage:
#   verify-after-restart.sh <backup-dir> --expect after|before --restart-mode single|app
#     after:  effort=medium idle=180 max_turn=7200
#     before: effort=low    idle=1500 max_turn=7200
#     --restart-mode single: other 8 pids unchanged+alive; 周衡 new+alive
#       (experiments without Cmd+Q ONLY; quit-first always implies app)
#     --restart-mode app:    all 9 pids changed+alive (default live flow after Cmd+Q)
# Detection: Mode A only if ALL THREE of effort, idle, max_turn visible in process env
# (pid-file pid = Python wrapper; buzz-acp is its child). Else Mode B: managed-agents
# row + process start time AFTER backup/config_written_at.txt (never MA mtime).
set -euo pipefail
# Reopen command: X=http://127.0.0.1:9567; open -a Buzz --env HTTP_PROXY=$X --env HTTPS_PROXY=$X --env ALL_PROXY=$X --env http_proxy=$X --env https_proxy=$X --env all_proxy=$X

BACKUP=${1:?usage: verify-after-restart.sh <backup-dir> --expect after|before --restart-mode single|app}
shift || true
EXPECT=""
RESTART_MODE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --expect) EXPECT=${2:?}; shift 2 ;;
    --expect=*) EXPECT=${1#*=}; shift ;;
    --restart-mode) RESTART_MODE=${2:?}; shift 2 ;;
    --restart-mode=*) RESTART_MODE=${1#*=}; shift ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done
if [[ -z "$EXPECT" ]]; then
  echo "FAIL: --expect after|before is required" >&2
  exit 2
fi
if [[ -z "$RESTART_MODE" ]]; then
  echo "FAIL: --restart-mode single|app is required (no auto-guess)" >&2
  exit 2
fi
case "$EXPECT" in
  after|before) ;;
  *) echo "--expect must be after|before, got: $EXPECT" >&2; exit 2 ;;
esac
case "$RESTART_MODE" in
  single|app) ;;
  *) echo "--restart-mode must be single|app, got: $RESTART_MODE" >&2; exit 2 ;;
esac

# shellcheck source=common.sh
source "$(dirname "$0")/common.sh"
reject_live_test_hooks

if [[ "$EXPECT" == "after" ]]; then
  WANT_EFFORT=medium
  WANT_IDLE=180
else
  WANT_EFFORT=low
  WANT_IDLE=1500
fi
WANT_MAX=7200

test -d "$BACKUP"
test -f "$BACKUP/others-before.tsv"
test -f "$BACKUP/all-pids-before.tsv"
test -f "$BACKUP/zhou-pid-before.txt" || test -f "$BACKUP/zhouheng-row-before.json"
test -f "$BACKUP/config_written_at.txt"

echo "== verify-after-restart expect=$EXPECT restart-mode=$RESTART_MODE (effort=$WANT_EFFORT idle=$WANT_IDLE max=$WANT_MAX) =="
echo "BACKUP=$BACKUP"

OLD_PID=""
if [[ -f "$BACKUP/zhou-pid-before.txt" ]]; then
  OLD_PID=$(tr -d '[:space:]' < "$BACKUP/zhou-pid-before.txt")
fi
# Config write time: ONLY apply's config_written_at (never managed-agents.json mtime —
# Desktop rewrites MA on start with last_started_at/updated_at; mtime is not config-write time).
CONFIG_AT=$(tr -d '[:space:]' < "$BACKUP/config_written_at.txt")
echo "config_written_at=$CONFIG_AT old_zhou_pid=${OLD_PID:-unknown}"

ZH_PID_FILE=$(zhou_pid_file)
# Pid in the pid file is the Python wrapper process; real buzz-acp is its child.
NEW_PID=$(python3 -c "import json; print(json.load(open(r'''$ZH_PID_FILE'''))['pid'])")
echo "周衡 pid file (wrapper) -> $NEW_PID"

if ! kill -0 "$NEW_PID" 2>/dev/null; then
  echo "FAIL: 周衡 wrapper pid $NEW_PID is not alive. Reopen with the exact RUNBOOK A13 command:" >&2
  echo "$REOPEN_CMD" >&2
  echo "Then wait for seats." >&2
  exit 1
fi
if [[ -n "$OLD_PID" && "$NEW_PID" == "$OLD_PID" ]]; then
  echo "FAIL: 周衡 pid $NEW_PID is NOT new (still equals pre-quit baseline). Restart did not happen." >&2
  exit 1
fi
echo "周衡 NEW alive wrapper pid OK: $NEW_PID (old=${OLD_PID:-n/a})"

# Pubkey must appear in wrapper process env/cmdline
BLOB=$(ps eww -p "$NEW_PID" 2>/dev/null || true)
if [[ "$BLOB" != *"$PUB"* ]]; then
  echo "FAIL: process $NEW_PID env/cmdline missing full pubkey $PUB" >&2
  exit 1
fi
echo "pubkey present in wrapper process OK"

# Dual detection for effort/idle/max (N1: Mode A only if ALL THREE visible)
python3 - "$NEW_PID" "$PUB" "$WANT_EFFORT" "$WANT_IDLE" "$WANT_MAX" "$MA" "$CONFIG_AT" <<'PY'
import json, os, sys, time, platform, subprocess, re
from pathlib import Path
from datetime import datetime, timezone

pid, pub, want_effort, want_idle, want_max, ma_path, config_at = sys.argv[1:8]
want_idle = int(want_idle)
want_max = int(want_max)

def read_proc(pid):
    """Read env from the pid-file pid (Python wrapper). buzz-acp is its child.
    Optional child-env fallback omitted for simplicity — leave Mode B if wrapper lacks vars.
    """
    env = {}
    out = subprocess.check_output(['ps', 'eww', '-p', str(pid)], text=True, stderr=subprocess.DEVNULL)
    for tok in out.split():
        if '=' in tok:
            k, v = tok.split('=', 1)
            env[k] = v
    return env, out

def process_start_epoch(pid):
    """Parse ps -o lstart= ; never use etimes (macOS: 'etimes: keyword not found').
    Empty/unparseable lstart => FAIL (never treat as 0).
    """
    # ps emits lstart as local wall-clock text; force stable English names without changing TZ.
    locale_env = {**os.environ, 'LC_ALL': 'C', 'LANG': 'C'}
    try:
        lstart = subprocess.check_output(
            ['ps', '-o', 'lstart=', '-p', str(pid)],
            text=True,
            stderr=subprocess.DEVNULL,
            env=locale_env,
        ).strip()
    except Exception as e:
        print('FAIL: cannot read ps -o lstart= for pid', pid, e, file=sys.stderr)
        sys.exit(1)
    if not lstart:
        print('FAIL: empty lstart for pid', pid, '(refusing to treat as epoch 0)', file=sys.stderr)
        sys.exit(1)
    # Sample: "Thu Sep 24 14:54:38 2026"
    try:
        if platform.system() == 'Darwin':
            epoch_s = subprocess.check_output(
                ['date', '-j', '-f', '%a %b %d %T %Y', lstart, '+%s'],
                text=True,
                stderr=subprocess.DEVNULL,
                env=locale_env,
            ).strip()
        else:
            # GNU date (CI/Linux smoke)
            epoch_s = subprocess.check_output(
                ['date', '-d', lstart, '+%s'],
                text=True,
                stderr=subprocess.DEVNULL,
                env=locale_env,
            ).strip()
    except Exception as e:
        print('FAIL: cannot parse lstart', repr(lstart), e, file=sys.stderr)
        sys.exit(1)
    if not epoch_s or not epoch_s.lstrip('-').isdigit():
        print('FAIL: unparseable lstart epoch', repr(epoch_s), 'from', repr(lstart), file=sys.stderr)
        sys.exit(1)
    return int(epoch_s)

env, cmdline = read_proc(pid)
got_effort = got_idle = got_max = None

if 'BUZZ_ACP_EFFORT_LEVEL' in env:
    got_effort = env['BUZZ_ACP_EFFORT_LEVEL']
else:
    m = re.search(r'--reasoning-effort[=\s]+(\w+)', cmdline)
    if m:
        got_effort = m.group(1)

if 'BUZZ_ACP_IDLE_TIMEOUT' in env:
    try:
        got_idle = int(env['BUZZ_ACP_IDLE_TIMEOUT'])
    except ValueError:
        got_idle = env['BUZZ_ACP_IDLE_TIMEOUT']

if 'BUZZ_ACP_MAX_TURN_DURATION' in env:
    try:
        got_max = int(env['BUZZ_ACP_MAX_TURN_DURATION'])
    except ValueError:
        got_max = env['BUZZ_ACP_MAX_TURN_DURATION']

# N1: Mode A only if ALL THREE visible; otherwise Mode B (no partial Mode A)
if got_effort is not None and got_idle is not None and got_max is not None:
    method = 'process_env_cmdline'
else:
    method = 'managed_agents_plus_start_time'
    agents = json.loads(Path(ma_path).read_text())
    row = next(a for a in agents if a.get('pubkey') == pub or a.get('name') == '周衡')
    env2 = row.get('env_vars') or {}
    got_effort = env2.get('BUZZ_ACP_EFFORT_LEVEL')
    idle_raw = row.get('idle_timeout_seconds')
    if idle_raw is None:
        idle_raw = env2.get('BUZZ_ACP_IDLE_TIMEOUT')
    if idle_raw is None:
        print('FAIL: Mode B missing idle_timeout in managed-agents row', file=sys.stderr)
        sys.exit(1)
    got_idle = int(idle_raw)
    max_raw = row.get('max_turn_duration_seconds')
    if max_raw is None:
        max_raw = env2.get('BUZZ_ACP_MAX_TURN_DURATION')
    if max_raw is None or max_raw == '':
        print('FAIL: Mode B missing max_turn_duration (unchecked would be silent pass)', file=sys.stderr)
        sys.exit(1)
    got_max = int(max_raw)
    # config_written_at is stored as a UTC ISO-8601 string; compare its epoch to lstart's epoch.
    # lstart is local wall-clock text, parsed by date in the same TZ that ps used; do not set TZ.
    try:
        cfg = datetime.strptime(config_at, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
        cfg_epoch = cfg.timestamp()
    except Exception as e:
        print('FAIL: cannot parse config_written_at', config_at, e, file=sys.stderr)
        sys.exit(1)
    start_epoch = process_start_epoch(pid)
    if start_epoch < cfg_epoch - 2:  # 2s skew tolerance
        print(
            f'FAIL: process start {datetime.fromtimestamp(start_epoch, timezone.utc).isoformat()} '
            f'is NOT after config_written_at {config_at} (mixed old process)',
            file=sys.stderr,
        )
        sys.exit(1)
    age = int(time.time() - start_epoch)
    print(f'start_time OK: lstart epoch={start_epoch} (~{age}s ago), after config_written_at')

print(f'detection_method={method}')
print(f'observed effort={got_effort} idle={got_idle} max={got_max}')

ok = True
if str(got_effort) != str(want_effort):
    print(f'FAIL: effort want={want_effort} got={got_effort}', file=sys.stderr)
    ok = False
if int(got_idle) != int(want_idle):
    print(f'FAIL: idle want={want_idle} got={got_idle}', file=sys.stderr)
    ok = False
if got_max is None:
    print('FAIL: max_turn missing/unchecked', file=sys.stderr)
    ok = False
elif int(got_max) != int(want_max):
    print(f'FAIL: max_turn want={want_max} got={got_max}', file=sys.stderr)
    ok = False
if not ok:
    sys.exit(1)
print(f'effort/idle/max OK via {method}')
PY

echo "== restart-mode=$RESTART_MODE pid check vs backup all-pids-before.tsv =="
verify_restart_pids "$RESTART_MODE" "$BACKUP/all-pids-before.tsv" "${OLD_PID:-}" "$NEW_PID"

echo "== doctor 9/9 (live ACP count on TEAM) =="
python3 -c "
import json, os
from pathlib import Path
pid_dir=Path(os.path.expanduser(r'''$PID_DIR'''))
team=r'''$TEAM'''
alive=0
total=0
for f in pid_dir.glob(f'*__{team}.json'):
    total+=1
    pid=json.loads(f.read_text())['pid']
    try:
        os.kill(pid, 0)
        alive+=1
    except OSError:
        pass
print(f'TEAM seats total={total} alive={alive}')
if total!=9 or alive!=9:
    raise SystemExit(f'FAIL: doctor 9/9 not met (total={total} alive={alive})')
print('doctor 9/9 OK')
"

echo "verify-after-restart OK (expect=$EXPECT restart-mode=$RESTART_MODE)"
