#!/usr/bin/env bash
# Static + optional live smoke for Issue #38 scripts. Never mutates live.
# Default (CI/Linux): static checks only. Set SMOKE_LIVE=1 on Mac for pin/pid checks.
# Does NOT run apply/rollback live; does NOT re-run smoke-real-workflow.
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
  shellcheck -x "$DIR/common.sh" "$DIR/apply.sh" "$DIR/rollback.sh" "$DIR/verify-after-restart.sh" "$DIR/smoke-test.sh" \
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
  echo "FAIL: safe_kill_zhou still defined in common.sh" >&2
  exit 1
fi
echo "no kill/respawn call paths OK"

echo "== F1: require_zhou_alive status on stderr only (static) =="
# Contract stub: status on stderr, bare pid on stdout (always runs; no live ACP needed)
_f1_good() { echo "周衡 ACP alive OK: pid=81513 (pubkey confirmed)" >&2; printf '%s
' "81513"; }
_f1_bad()  { echo "周衡 ACP alive OK: pid=81513 (pubkey confirmed)"; printf '%s
' "81513"; }
good=$(_f1_good 2>/dev/null)
bad=$(_f1_bad 2>/dev/null)
if ! [[ "$good" =~ ^[0-9]+$ ]]; then
  echo "FAIL: good stub stdout not purely numeric: '$good'" >&2
  exit 1
fi
if [[ "$bad" =~ ^[0-9]+$ ]]; then
  echo "FAIL: polluted stub unexpectedly numeric-only" >&2
  exit 1
fi
echo "F1 numeric-capture stub OK (good='$good'; bad polluted as expected)"
grep -E '周衡 ACP alive OK:.*>&2' "$DIR/common.sh" >/dev/null
if grep -nE 'echo "周衡 ACP alive OK' "$DIR/common.sh" | grep -v '>&2'; then
  echo "FAIL: alive-OK echo still writes to stdout" >&2
  exit 1
fi
echo "F1 stderr-status static OK"

echo "== F2: ERR/EXIT fail-report traps present =="
grep -q 'apply_fail_report' "$DIR/apply.sh"
grep -q 'rollback_fail_report' "$DIR/rollback.sh"
grep -q "trap .*ERR" "$DIR/apply.sh"
grep -q "trap .*ERR" "$DIR/rollback.sh"
echo "F2 traps OK"

echo "== F3: require_all_team_alive used by apply =="
grep -q 'require_all_team_alive' "$DIR/common.sh"
grep -q 'require_all_team_alive' "$DIR/apply.sh"
echo "F3 doctor-9/9 enforce OK"

echo "== F4: Mode A/B missing max => FAIL (static) =="
grep -q 'Mode A (process_env_cmdline) missing max_turn' "$DIR/verify-after-restart.sh"
grep -q 'Mode B missing max_turn_duration' "$DIR/verify-after-restart.sh"
if grep -nE 'or want_max' "$DIR/verify-after-restart.sh"; then
  echo "FAIL: still defaults missing max to want_max" >&2
  exit 1
fi
echo "F4 max-required OK"

echo "== F5: config_written_at after first mutation =="
python3 "$DIR/_check_f5_order.py" "$DIR/apply.sh"

echo "== refuse without ISSUE38_I_UNDERSTAND_LIVE =="
set +e
out=$(bash "$DIR/apply.sh" 2>&1)
rc=$?
set -e
echo "$out" | head -3
if [[ "$rc" -ne 2 ]]; then
  echo "FAIL: apply.sh expected exit 2 without guard, got $rc" >&2
  exit 1
fi
set +e
out=$(bash "$DIR/rollback.sh" /tmp/does-not-matter 2>&1)
rc=$?
set -e
if [[ "$rc" -ne 2 ]]; then
  echo "FAIL: rollback.sh expected exit 2 without guard, got $rc" >&2
  exit 1
fi
echo "guard refuse OK (exit 2)"

echo "== apply/rollback print manual-restart instructions (static grep) =="
grep -q 'Ask peng to restart ONLY 周衡' "$DIR/apply.sh"
grep -q 'verify-after-restart.sh' "$DIR/apply.sh"
grep -q 'REQUIRED NEXT STEP' "$DIR/rollback.sh"
grep -q -- '--expect before' "$DIR/rollback.sh"
grep -q -- '--expect after' "$DIR/apply.sh"
echo "manual-restart messaging OK"

echo "== verify-after-restart supports --expect after|before (static) =="
grep -q 'after|before' "$DIR/verify-after-restart.sh"
grep -q 'detection_method=' "$DIR/verify-after-restart.sh"
grep -q 'managed_agents_plus_start_time\|process_env_cmdline' "$DIR/verify-after-restart.sh"
echo "verify dual-mode OK"

if [[ "${SMOKE_LIVE:-}" == "1" ]]; then
  echo "== SMOKE_LIVE=1: pin + zhou pid + numeric capture =="
  # shellcheck source=common.sh
  source "$DIR/common.sh"
  verify_thin_pin
  f=$(zhou_pid_file)
  echo "zhou_pid_file -> $f"
  test -f "$f"
  n=$(list_other_team_pids | wc -l | tr -d ' ')
  echo "other TEAM seats: $n"
  set +e
  # stdout must be bare pid only; status on stderr
  capt=$(require_zhou_alive 2>/tmp/issue38-zhou-alive.err)
  arc=$?
  set -e
  if [[ "$arc" -eq 0 ]]; then
    echo "require_zhou_alive stdout='$capt'"
    if ! [[ "$capt" =~ ^[0-9]+$ ]]; then
      echo "FAIL: captured pid not purely numeric: '$capt'" >&2
      exit 1
    fi
    echo "F1 numeric pid capture OK: $capt"
  else
    echo "NOTE: require_zhou_alive exited $arc (周衡 may be down; apply would abort)"
    head -3 /tmp/issue38-zhou-alive.err || true
  fi
  # Still assert that if we had success path text, stderr has status
  if [[ "$arc" -eq 0 ]]; then
    grep -q '周衡 ACP alive OK' /tmp/issue38-zhou-alive.err
  fi
  set +e
  require_all_team_alive 2>/tmp/issue38-all-alive.err
  aarc=$?
  set -e
  echo "require_all_team_alive exit=$aarc"
  cat /tmp/issue38-all-alive.err | head -5 || true
else
  echo "== SMOKE_LIVE!=1 — skip live Mac pin/pid checks (CI/Linux safe) =="
fi

echo "smoke-test OK"
