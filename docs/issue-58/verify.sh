#!/bin/bash
# Issue #58 verify (read-only): entry state, bin/buzz --help, buzz-health, buzz-acp pid set,
# managed-agents.json digest.
#
# Usage: verify.sh [--target DIR] --expect new|old [--save-state FILE] [--compare-state FILE]
#                  [--health-out FILE]
#   --save-state writes "pids:" and "inventory:" lines; --compare-state requires both equal.
# Exit 0 only if every check passes. Needs no live acknowledgement: it writes nothing in target.
set -euo pipefail
source "$(cd "$(dirname "$0")" && pwd)/common.sh"

T=""; EXPECT=""; SAVE=""; COMPARE=""; HEALTH_OUT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --target) T="$2"; shift 2 ;;
    --expect) EXPECT="$2"; shift 2 ;;
    --save-state) SAVE="$2"; shift 2 ;;
    --compare-state) COMPARE="$2"; shift 2 ;;
    --health-out) HEALTH_OUT="$2"; shift 2 ;;
    *) die "unknown argument $1" ;;
  esac
done
case "$EXPECT" in new|old) ;; *) die "--expect new|old required" ;; esac
TARGET="$(cd "${T:-${ISSUE58_TARGET:-$LIVE_INSTANCE}}" && pwd -P)"
BIN="$TARGET/bin"
echo "issue58 verify: target=$TARGET expect=$EXPECT"
FAIL=0
ok() { echo "PASS $*"; }
bad() { echo "FAIL $*"; FAIL=1; }

print_entry_hashes "$BIN"
if [ "$EXPECT" = new ]; then
  cmp -s "$BIN/buzz" "$ISSUE58_DIR/bin/buzz" && ok "bin/buzz is the #58 entry" || bad "bin/buzz is not the #58 entry"
  cmp -s "$BIN/buzz-health" "$ISSUE58_DIR/bin/buzz-health" && ok "bin/buzz-health is the #58 entry" || bad "bin/buzz-health missing/different"
  [ ! -e "$BIN/agent-harness" ] && ok "agent-harness retired" || bad "agent-harness still present"
  for e in agent-executor agent-worktree; do
    [ "$(sha256_of "$BIN/$e")" = "$(expected_595_sha "$e")" ] && ok "$e unchanged (595c0cfe)" || bad "$e changed"
  done
  HEALTH="$BIN/buzz-health"
else
  for e in $ENTRIES; do
    [ -f "$BIN/$e" ] && [ "$(sha256_of "$BIN/$e")" = "$(expected_595_sha "$e")" ] && ok "$e is the 595c0cfe entry" || bad "$e is not the 595c0cfe entry"
  done
  [ ! -e "$BIN/buzz-health" ] && ok "no bin/buzz-health" || bad "bin/buzz-health present"
  HEALTH="$ISSUE58_DIR/bin/buzz-health"
fi

if "$BIN/buzz" --help >/dev/null 2>&1; then ok "bin/buzz --help rc=0"; else bad "bin/buzz --help rc=$?"; fi

HOUT="${HEALTH_OUT:-$(mktemp)}"
PY3=/usr/bin/python3; [ -x "$PY3" ] || PY3=python3
if "$PY3" "$HEALTH" > "$HOUT"; then ok "buzz-health ok (exit 0) -> $HOUT"; else bad "buzz-health failed (exit $?) -> $HOUT"; fi

PIDS="$(acp_pids | tr '\n' ' ' | sed 's/ $//')"
if [ -f "$INVENTORY" ]; then INV="$(sha256_of "$INVENTORY")"; else INV=missing; fi
echo "buzz-acp pids ($(echo $PIDS | wc -w | tr -d ' ')): $PIDS"
echo "managed-agents.json sha256: $INV"
if [ -n "$SAVE" ]; then printf 'pids: %s\ninventory: %s\n' "$PIDS" "$INV" > "$SAVE"; ok "state saved to $SAVE"; fi
if [ -n "$COMPARE" ]; then
  [ "$(sed -n 's/^pids: //p' "$COMPARE")" = "$PIDS" ] && ok "buzz-acp pid set unchanged" || bad "buzz-acp pid set changed"
  [ "$(sed -n 's/^inventory: //p' "$COMPARE")" = "$INV" ] && ok "managed-agents.json unchanged" || bad "managed-agents.json changed"
fi
[ "$FAIL" = 0 ] && echo "VERIFY PASS" || echo "VERIFY FAIL"
exit "$FAIL"
