#!/usr/bin/env bash
# Static (+ optional live) smoke for Issue #38 scripts. Never mutates live.
# Default (CI/Linux): static only. SMOKE_LIVE=1 on Mac enables pin/pid checks.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"

echo "== bash -n =="
for f in common.sh apply.sh rollback.sh verify-after-restart.sh smoke-test.sh; do
  bash -n "$DIR/$f"
  echo "  OK $f"
done

if command -v shellcheck >/dev/null 2>&1; then
  echo "== shellcheck (warnings non-fatal) =="
  set +e
  shellcheck -x "$DIR/common.sh" "$DIR/apply.sh" "$DIR/rollback.sh" \
    "$DIR/verify-after-restart.sh" "$DIR/smoke-test.sh" \
    2>&1 | tee /tmp/issue38-shellcheck.log
  sc_rc=${PIPESTATUS[0]}
  set -e
  echo "shellcheck exit=$sc_rc (non-fatal; log=/tmp/issue38-shellcheck.log)"
else
  echo "shellcheck not installed — skipped"
fi

echo "== no safe_kill / kill-wait in call paths =="
if grep -nE '^[[:space:]]*safe_kill_zhou|^[[:space:]]*kill[[:space:]]+-?[0-9]|TIMEOUT waiting for Desktop to respawn' \
    "$DIR/apply.sh" "$DIR/rollback.sh" "$DIR/common.sh" "$DIR/verify-after-restart.sh"; then
  echo "FAIL: kill/respawn call path still present" >&2
  exit 1
fi
if grep -nE '^safe_kill_zhou\(\)' "$DIR/common.sh"; then
  echo "FAIL: safe_kill_zhou still defined" >&2
  exit 1
fi
echo "no kill/respawn call paths OK"

echo "== quit-first: baseline-only + desktop-not-running + SKIP_DESKTOP_CHECK =="
grep -q -- '--baseline-only' "$DIR/apply.sh"
grep -q 'require_desktop_not_running' "$DIR/apply.sh"
grep -q 'require_desktop_not_running' "$DIR/rollback.sh"
grep -q 'SKIP_DESKTOP_CHECK' "$DIR/common.sh"
grep -q 'snapshot_all_team_pids' "$DIR/apply.sh"
grep -q 'all-pids-before.tsv' "$DIR/apply.sh"
grep -q 'all-pids-before.tsv' "$DIR/verify-after-restart.sh"
# mutate phase must not require seats alive
DIR="$DIR" python3 - <<'PY'
import os, re
from pathlib import Path
t = Path(os.environ["DIR"], "apply.sh").read_text()
m = re.search(r"mutate phase: require Desktop NOT running", t)
assert m, "mutate phase marker missing"
tail = t[m.start():]
if re.search(r"^\s*require_all_team_alive\b", tail, re.M):
    raise SystemExit("FAIL: require_all_team_alive in mutate phase")
if re.search(r"^\s*ZHOU_PID_BEFORE=\$\(require_zhou_alive\)", tail, re.M):
    raise SystemExit("FAIL: require_zhou_alive capture in mutate phase")
print("mutate phase does not require seats alive OK")
PY

echo "== N1: Mode A only if ALL THREE effort+idle+max visible =="
grep -q 'got_effort is not None and got_idle is not None and got_max is not None' \
  "$DIR/verify-after-restart.sh"
# Ensure we no longer gate Mode A on effort+idle alone
if grep -nE 'got_effort is not None and got_idle is not None:' \
    "$DIR/verify-after-restart.sh" | grep -v got_max; then
  echo "FAIL: Mode A still gates on effort+idle only" >&2
  exit 1
fi
echo "N1 three-of-three OK"

echo "== lstart parsing (no etimes call) =="
grep -q "lstart=" "$DIR/verify-after-restart.sh"
grep -q 'empty lstart' "$DIR/verify-after-restart.sh"
grep -q "date', '-j', '-f'" "$DIR/verify-after-restart.sh"
if grep -nE "\['ps', '-o', 'etimes='\]" "$DIR/verify-after-restart.sh" "$DIR/common.sh"; then
  echo "FAIL: etimes still invoked" >&2
  exit 1
fi
echo "lstart-only OK"

echo "== lstart parsing under LANG=zh_CN.UTF-8 =="
epoch=$(env -u LC_ALL LANG=zh_CN.UTF-8 python3 - <<'PY'
import os
import platform
import subprocess

lstart = 'Thu Sep 24 14:54:38 2026'
env = {**os.environ, 'LC_ALL': 'C', 'LANG': 'C'}
if platform.system() == 'Darwin':
    cmd = ['date', '-j', '-f', '%a %b %d %T %Y', lstart, '+%s']
else:
    cmd = ['date', '-d', lstart, '+%s']
print(subprocess.check_output(cmd, text=True, env=env).strip())
PY
)
if [[ ! "$epoch" =~ ^-?[0-9]+$ ]]; then
  echo "FAIL: zh_CN lstart parser did not return a numeric epoch: $epoch" >&2
  exit 1
fi
echo "zh_CN lstart parser OK (epoch=$epoch)"

echo "== --restart-mode single|app required (no auto-guess) =="
grep -q -- '--restart-mode' "$DIR/verify-after-restart.sh"
grep -q 'no auto-guess' "$DIR/verify-after-restart.sh"
grep -q 'verify_restart_pids' "$DIR/common.sh"
grep -q 'verify_restart_pids' "$DIR/verify-after-restart.sh"
grep -q 'restart_mode=single OK' "$DIR/common.sh"
grep -q 'restart_mode=app OK' "$DIR/common.sh"
echo "restart-mode branches OK"

echo "== config_written_at only (never MA mtime) =="
grep -q 'Never use managed-agents.json mtime' "$DIR/common.sh"
grep -q 'never MA mtime\|not MA mtime\|NOT config-write' "$DIR/verify-after-restart.sh"
echo "config_written_at authority OK"

echo "== refuse without live guard / required flags =="
set +e
bash "$DIR/apply.sh" >/tmp/i38-apply-unguarded.out 2>&1
rc=$?
set -e
if [[ "$rc" -eq 0 ]]; then
  echo "FAIL: apply.sh with no args should fail" >&2
  exit 1
fi
echo "apply no-args refused OK (exit=$rc)"
set +e
bash "$DIR/verify-after-restart.sh" /tmp/not-a-backup >/tmp/i38-verify-noflags.out 2>&1
rc=$?
set -e
if [[ "$rc" -eq 0 ]]; then
  echo "FAIL: verify without flags should fail" >&2
  exit 1
fi
echo "verify missing flags refused OK (exit=$rc)"

if [[ "${SMOKE_LIVE:-}" == "1" ]]; then
  echo "== SMOKE_LIVE=1: pin + zhou pid + desktop helper =="
  # shellcheck source=common.sh
  source "$DIR/common.sh"
  verify_thin_pin
  f=$(zhou_pid_file)
  echo "zhou_pid_file -> $f"
  desktop_main_pids || true
else
  echo "== SMOKE_LIVE!=1 — skip live Mac pin/pid checks (CI/Linux safe) =="
fi

echo "smoke-test OK"
