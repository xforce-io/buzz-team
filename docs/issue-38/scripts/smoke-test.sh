#!/usr/bin/env bash
# Static + read-only smoke for Issue #38 scripts. Never mutates live.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
echo "== bash -n =="
bash -n "$DIR/common.sh"
bash -n "$DIR/apply.sh"
bash -n "$DIR/rollback.sh"
bash -n "$DIR/smoke-test.sh"
echo "bash -n OK"

if command -v shellcheck >/dev/null 2>&1; then
  echo "== shellcheck =="
  shellcheck -x "$DIR/common.sh" "$DIR/apply.sh" "$DIR/rollback.sh" "$DIR/smoke-test.sh"
  echo "shellcheck OK"
else
  echo "shellcheck not installed — skipped"
fi

echo "== refuse without ISSUE38_I_UNDERSTAND_LIVE =="
set +e
out=$(bash "$DIR/apply.sh" 2>&1)
rc=$?
set -e
echo "$out" | head -5
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

echo "== read-only: pin + zhou pid file resolve =="
# shellcheck source=common.sh
source "$DIR/common.sh"
verify_thin_pin
f=$(zhou_pid_file)
echo "zhou_pid_file -> $f"
test -f "$f"
# other seats count
n=$(list_other_team_pids | wc -l | tr -d ' ')
echo "other TEAM seats: $n"
if [[ "$n" -ne 8 ]]; then
  echo "WARN: expected 8 other seats, got $n (non-fatal for smoke)" >&2
fi

echo "smoke-test OK"
