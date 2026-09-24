#!/usr/bin/env bash
# Static + read-only smoke for Issue #38 scripts. Never mutates live.
# Does NOT run apply/rollback live; does NOT re-run smoke-real-workflow.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"

echo "== bash -n =="
for f in common.sh apply.sh rollback.sh verify-after-restart.sh smoke-test.sh; do
  bash -n "$DIR/$f"
  echo "  OK $f"
done

if command -v shellcheck >/dev/null 2>&1; then
  echo "== shellcheck =="
  shellcheck -x "$DIR/common.sh" "$DIR/apply.sh" "$DIR/rollback.sh" "$DIR/verify-after-restart.sh" "$DIR/smoke-test.sh"
  echo "shellcheck OK"
else
  echo "shellcheck not installed — skipped"
fi

echo "== no safe_kill / kill-wait in call paths =="
# Flag real call sites only (ignore comments that document "does NOT respawn").
if grep -nE '^[[:space:]]*safe_kill_zhou|^[[:space:]]*kill[[:space:]]+-?[0-9]|TIMEOUT waiting for Desktop to respawn' \
    "$DIR/apply.sh" "$DIR/rollback.sh" "$DIR/common.sh" "$DIR/verify-after-restart.sh"; then
  echo "FAIL: kill/respawn call path still present" >&2
  exit 1
fi
# Function definition of safe_kill must be gone
if grep -nE '^safe_kill_zhou\(\)' "$DIR/common.sh"; then
  echo "FAIL: safe_kill_zhou still defined in common.sh" >&2
  exit 1
fi
echo "no kill/respawn call paths OK"

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

echo "== read-only: pin + zhou pid file resolve =="
# shellcheck source=common.sh
source "$DIR/common.sh"
verify_thin_pin
f=$(zhou_pid_file)
echo "zhou_pid_file -> $f"
test -f "$f"
n=$(list_other_team_pids | wc -l | tr -d ' ')
echo "other TEAM seats: $n"
if [[ "$n" -ne 8 ]]; then
  echo "WARN: expected 8 other seats, got $n (non-fatal for smoke)" >&2
fi

# require_zhou_alive may fail if 周衡 is currently down (post-fail state) — non-fatal note
set +e
require_zhou_alive >/tmp/issue38-zhou-alive.out 2>/tmp/issue38-zhou-alive.err
arc=$?
set -e
if [[ "$arc" -eq 0 ]]; then
  echo "require_zhou_alive OK: $(cat /tmp/issue38-zhou-alive.out | tail -1)"
else
  echo "NOTE: require_zhou_alive exited $arc (周衡 may be down post-fail; apply would abort until Desktop restart)"
  head -3 /tmp/issue38-zhou-alive.err || true
fi

echo "smoke-test OK"
