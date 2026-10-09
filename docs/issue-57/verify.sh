#!/bin/bash
# Issue #57 verify (read-only). Static: 周衡 policy sha256 (expect old = 9e087351, new = this
# directory's zhouheng-seatbelt.json), other 8 = baseline-before, thin._load_policy passes.
# Per relay (local ws://127.0.0.1:3000 and yuanbao): exactly one 周衡 buzz-acp whose env has
# BUZZ_ACP_AGENT_COMMAND = f66ef5e thin, BUZZ_TEAM_POLICY_PATH = live 周衡 policy with the expected
# sha256, KAIRO_PROVIDER=grok, six proxy vars on 127.0.0.1:9567, and a grok child launched through
# thin. Missing = wrong = FAIL. Local relay must be ESTABLISHED; yuanbao state is recorded only.
# --compare-state: other seats' pids unchanged; with --restarted 周衡 pids must be new; 周衡 logs
# must show no thin launch failure ("BUZZ_TEAM_POLICY_PATH must be an absolute path", exit 126).
# This script does not query the Sandbox unified log. Write-deny acceptance is the run/session
# log plus probe.sh (see docs/issue-63); a missing unified-log deny is not pass/fail.
#
# Usage: verify.sh [--target POLICY_DIR] --expect old|new [--static-only] [--inventory FILE]
#                  [--prompt present|absent|skip] [--relays local|all] [--save-state FILE] [--compare-state FILE [--restarted]]
set -euo pipefail
source "$(cd "$(dirname "$0")" && pwd)/common.sh"

T=""; ARGS=(); SAVE=""; INV="$INVENTORY"
while [ $# -gt 0 ]; do
  case "$1" in
    --target) T="$2"; shift 2 ;;
    --expect|--prompt|--relays|--compare-state) ARGS+=("$1" "$2"); shift 2 ;;
    --inventory) INV="$2"; shift 2 ;;
    --static-only|--restarted) ARGS+=("$1"); shift ;;
    --save-state) SAVE="$2"; shift 2 ;;
    *) die "unknown argument $1" ;;
  esac
done
TARGET="$(cd "${T:-${ISSUE57_TARGET:-$LIVE_POLICIES}}" && pwd -P)"
THIN_PY="${ISSUE57_THIN_PYTHON:-$LIVE_THIN_PY}"
EXTRA=()
if [ -n "${ISSUE57_TEST_OLD_POLICY:-}" ]; then EXTRA+=(--old-sha "$(sha256_of "$ISSUE57_TEST_OLD_POLICY")"); fi
if [ -n "${ISSUE57_TEST_NEW_POLICY:-}" ]; then EXTRA+=(--new-policy "$ISSUE57_TEST_NEW_POLICY"); fi
if [ -n "${ISSUE57_TEST_BASELINE:-}" ]; then EXTRA+=(--baseline "$ISSUE57_TEST_BASELINE"); fi
if [ -n "$SAVE" ]; then
  "$PY3" "$HELPER" snapshot --policies "$TARGET" --inventory "$INV" --rule "$RULE_FILE" --out "$SAVE" >/dev/null
  echo "issue57: state saved to $SAVE"
fi
set +e
"$PY3" "$HELPER" verify --policies "$TARGET" --inventory "$INV" --rule "$RULE_FILE" --thin-python "$THIN_PY" \
  ${EXTRA[@]+"${EXTRA[@]}"} ${ARGS[@]+"${ARGS[@]}"}
rc=$?
set -e
exit $rc
