#!/usr/bin/env bash
# Read-only post-Desktop-restart verification for Issue #38.
# Usage:
#   verify-after-restart.sh <backup-dir> [--expect after|before]
#     after  (default): effort=medium idle=180 max_turn=7200
#     before:           effort=low    idle=1500 max_turn=7200
# Detection: prefer process cmdline/env; else managed-agents.json row + process
# start time later than backup/config_written_at.txt. Method is printed.
set -euo pipefail

BACKUP=${1:?usage: verify-after-restart.sh <backup-dir> [--expect after|before]}
shift || true
EXPECT=after
while [[ $# -gt 0 ]]; do
  case "$1" in
    --expect) EXPECT=${2:?}; shift 2 ;;
    --expect=*) EXPECT=${1#*=}; shift ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done
case "$EXPECT" in
  after|before) ;;
  *) echo "--expect must be after|before, got: $EXPECT" >&2; exit 2 ;;
esac

# shellcheck source=common.sh
source "$(dirname "$0")/common.sh"

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
test -f "$BACKUP/zhou-pid-before.txt" || test -f "$BACKUP/zhouheng-row-before.json"
test -f "$BACKUP/config_written_at.txt"

echo "== verify-after-restart expect=$EXPECT (effort=$WANT_EFFORT idle=$WANT_IDLE max=$WANT_MAX) =="
echo "BACKUP=$BACKUP"

OLD_PID=""
if [[ -f "$BACKUP/zhou-pid-before.txt" ]]; then
  OLD_PID=$(tr -d '[:space:]' < "$BACKUP/zhou-pid-before.txt")
fi
CONFIG_AT=$(tr -d '[:space:]' < "$BACKUP/config_written_at.txt")
echo "config_written_at=$CONFIG_AT old_zhou_pid=${OLD_PID:-unknown}"

ZH_PID_FILE=$(zhou_pid_file)
NEW_PID=$(python3 -c "import json; print(json.load(open(r'''$ZH_PID_FILE'''))['pid'])")
echo "周衡 pid file -> $NEW_PID"

if ! kill -0 "$NEW_PID" 2>/dev/null; then
  echo "FAIL: 周衡 pid $NEW_PID is not alive. Ask peng to restart ONLY 周衡 from Desktop." >&2
  exit 1
fi
if [[ -n "$OLD_PID" && "$NEW_PID" == "$OLD_PID" ]]; then
  echo "FAIL: 周衡 pid $NEW_PID is NOT new (still equals pre-apply pid). Restart did not happen." >&2
  exit 1
fi
echo "周衡 NEW alive pid OK: $NEW_PID (old=${OLD_PID:-n/a})"

# Pubkey must appear in process
BLOB=$(ps eww -p "$NEW_PID" 2>/dev/null || true)
if [[ "$BLOB" != *"$PUB"* ]]; then
  echo "FAIL: process $NEW_PID env/cmdline missing full pubkey $PUB" >&2
  exit 1
fi
echo "pubkey present in process OK"

# Dual detection for effort/idle/max
python3 - "$NEW_PID" "$PUB" "$WANT_EFFORT" "$WANT_IDLE" "$WANT_MAX" "$MA" "$CONFIG_AT" <<'PY'
import json, os, sys, time
from pathlib import Path
from datetime import datetime, timezone

pid, pub, want_effort, want_idle, want_max, ma_path, config_at = sys.argv[1:8]
want_idle=int(want_idle); want_max=int(want_max)

def read_proc(pid):
    # macOS: ps eww already collected by caller via environ file if needed
    env={}
    # Try /proc-like via ps output file from parent? Use os.environ of target via ctypes? 
    # Prefer parsing `ps eww` output from a subprocess.
    import subprocess
    out=subprocess.check_output(['ps','eww','-p',str(pid)], text=True, stderr=subprocess.DEVNULL)
    # env vars appear as KEY=VAL tokens
    for tok in out.split():
        if '=' in tok:
            k,v=tok.split('=',1)
            env[k]=v
    cmdline=out
    return env, cmdline

env, cmdline = read_proc(pid)
method=None
got_effort=got_idle=got_max=None

# Method A: process env/cmdline
for key in ('BUZZ_ACP_EFFORT_LEVEL',):
    if key in env:
        got_effort=env[key]; break
if got_effort is None:
    # cmdline flags
    import re
    m=re.search(r'--reasoning-effort[=\s]+(\w+)', cmdline)
    if m: got_effort=m.group(1)

for key in ('BUZZ_ACP_IDLE_TIMEOUT',):
    if key in env:
        try: got_idle=int(env[key])
        except ValueError: got_idle=env[key]
        break

for key in ('BUZZ_ACP_MAX_TURN_DURATION',):
    if key in env:
        try: got_max=int(env[key])
        except ValueError: got_max=env[key]
        break

if got_effort is not None and got_idle is not None:
    method='process_env_cmdline'
    # F4 Mode A: max must be visible too — missing => FAIL (no silent skip)
    if got_max is None:
        print('FAIL: Mode A (process_env_cmdline) missing max_turn in process env/cmdline', file=sys.stderr)
        sys.exit(1)
else:
    method='managed_agents_plus_start_time'
    agents=json.loads(Path(ma_path).read_text())
    row=next(a for a in agents if a.get('pubkey')==pub or a.get('name')=='周衡')
    env2=row.get('env_vars') or {}
    got_effort=env2.get('BUZZ_ACP_EFFORT_LEVEL')
    idle_raw=row.get('idle_timeout_seconds')
    if idle_raw is None:
        idle_raw=env2.get('BUZZ_ACP_IDLE_TIMEOUT')
    if idle_raw is None:
        print('FAIL: Mode B missing idle_timeout in managed-agents row', file=sys.stderr)
        sys.exit(1)
    got_idle=int(idle_raw)
    # F4 Mode B: do NOT default missing max to want_max
    max_raw=row.get('max_turn_duration_seconds')
    if max_raw is None:
        max_raw=env2.get('BUZZ_ACP_MAX_TURN_DURATION')
    if max_raw is None or max_raw=='':
        print('FAIL: Mode B missing max_turn_duration (unchecked would be silent pass)', file=sys.stderr)
        sys.exit(1)
    got_max=int(max_raw)
    # start time must be after config_written_at
    # macOS: ps -o lstart= / or etimes
    import subprocess
    try:
        etimes=int(subprocess.check_output(['ps','-o','etimes=','-p',str(pid)], text=True).strip() or '0')
    except Exception:
        etimes=None
    # parse config_at as UTC
    try:
        cfg=datetime.strptime(config_at, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
        cfg_epoch=cfg.timestamp()
    except Exception as e:
        print('FAIL: cannot parse config_written_at', config_at, e, file=sys.stderr)
        sys.exit(1)
    now=time.time()
    if etimes is None:
        print('FAIL: cannot read process elapsed time for start-time check', file=sys.stderr)
        sys.exit(1)
    start_epoch=now-etimes
    if start_epoch < cfg_epoch - 2:  # 2s skew tolerance
        print(f'FAIL: process start {datetime.fromtimestamp(start_epoch, timezone.utc).isoformat()} '
              f'is NOT after config_written_at {config_at} (mixed old process)', file=sys.stderr)
        sys.exit(1)
    print(f'start_time OK: pid started ~{etimes}s ago, after config_written_at')

print(f'detection_method={method}')
print(f'observed effort={got_effort} idle={got_idle} max={got_max}')

ok=True
if str(got_effort) != str(want_effort):
    print(f'FAIL: effort want={want_effort} got={got_effort}', file=sys.stderr); ok=False
if int(got_idle) != int(want_idle):
    print(f'FAIL: idle want={want_idle} got={got_idle}', file=sys.stderr); ok=False
if got_max is None:
    print('FAIL: max_turn missing/unchecked', file=sys.stderr); ok=False
elif int(got_max) != int(want_max):
    print(f'FAIL: max_turn want={want_max} got={got_max}', file=sys.stderr); ok=False
if not ok:
    sys.exit(1)
print(f'effort/idle/max OK via {method}')
PY

echo "== other 8 seats vs backup others-before.tsv =="
verify_other_pids_unchanged "$BACKUP/others-before.tsv"

echo "== doctor 9/9 (live ACP count on TEAM) =="
python3 -c "
import json, os, subprocess
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

echo "verify-after-restart OK (expect=$EXPECT)"
