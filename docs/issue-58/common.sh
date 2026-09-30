# shellcheck shell=bash
# Shared helpers for issue #58 apply / rollback / verify. Bash 3.2 compatible (macOS /bin/bash).

ISSUE58_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIVE_INSTANCE="${HOME}/lab/buzz"
# Path baked into the 595c0cfe entries (they always name the live instance, also in a copy).
ENTRY_INSTANCE=/Users/xupeng/lab/buzz
RELEASE_595=/Users/xupeng/.local/share/buzz-team/releases/595c0cfe43253b58087906a8bedc8d31388e3b5b
OFFICIAL_BUZZ=/Applications/Buzz.app/Contents/MacOS/buzz
INVENTORY="${HOME}/Library/Application Support/xyz.block.buzz.app/agents/managed-agents.json"
ENTRIES="buzz agent-executor agent-harness agent-worktree"

# sha256 of the four 595c0cfe entries as installed 2026-09-30 08:59 (Hogan retarget).
expected_595_sha() {
  case "$1" in
    buzz) echo 819c2e12c7d0da77b02540b78ab8727ba7bf16258bcfe210d01329f9acb17c31 ;;
    agent-executor) echo 60a780997cd5bdbd7afb5ff8781314e6da1a1371c3d6da3a98e45684de1a3b2f ;;
    agent-harness) echo fe5681bae6c58323dcc03ed74d76dae066960120fdea3569178ce53ab8a4287c ;;
    agent-worktree) echo 73ec3806dd4da0fecb6ccbcaf3b32fd8337f3791a0370ca5326136dd9ac5bb23 ;;
    *) return 1 ;;
  esac
}

# Canonical 595c0cfe entry text (reproduces the sha256 above byte for byte).
entry_595_text() {
  local args
  case "$1" in
    buzz) args='buzz -- "$@"' ;;
    agent-executor) args='launch executor -- "$@"' ;;
    agent-harness) args='launch harness -- "$@"' ;;
    agent-worktree) args='workspace "$@"' ;;
    *) return 1 ;;
  esac
  printf '#!/bin/sh\nset -eu\nexec %s/bin/python -m buzz_team.cli --instance %s %s\n' "$RELEASE_595" "$ENTRY_INSTANCE" "$args"
}

sha256_of() {
  if command -v shasum >/dev/null 2>&1; then shasum -a 256 "$1" | awk '{print $1}'
  else sha256sum "$1" | awk '{print $1}'; fi
}

die() { echo "issue58: ABORT: $*" >&2; exit 1; }

resolve_target() {
  # $1 = value of --target (may be empty)
  local t="${1:-${ISSUE58_TARGET:-$LIVE_INSTANCE}}"
  [ -d "$t" ] || die "target $t is not a directory"
  TARGET="$(cd "$t" && pwd -P)"
  IS_LIVE=no
  if [ -d "$LIVE_INSTANCE" ] && [ "$TARGET" = "$(cd "$LIVE_INSTANCE" && pwd -P)" ]; then IS_LIVE=yes; fi
  if [ "$IS_LIVE" = yes ]; then
    [ "${ISSUE58_I_UNDERSTAND_LIVE:-}" = yes ] || die "target is the live instance; set ISSUE58_I_UNDERSTAND_LIVE=yes (see docs/issue-58/README.md)"
    [ -z "${ISSUE58_TEST_SKIP_SIGNATURE:-}" ] || die "ISSUE58_TEST_SKIP_SIGNATURE is test-only; refused on the live instance"
    [ -z "${BUZZ58_TEST_OFFICIAL_BUZZ:-}" ] || die "BUZZ58_TEST_OFFICIAL_BUZZ is test-only; refused on the live instance"
  fi
  echo "issue58: target=$TARGET live=$IS_LIVE"
}

# 0 when the official CLI passes the same gate as bin/buzz.
official_signature_ok() {
  local bin="${BUZZ58_TEST_OFFICIAL_BUZZ:-$OFFICIAL_BUZZ}" info
  [ -x /usr/bin/codesign ] && [ -f "$bin" ] || return 1
  /usr/bin/codesign --verify --strict "$bin" 2>/dev/null || return 1
  info=$(/usr/bin/codesign -dv "$bin" 2>&1) || return 1
  printf '%s\n' "$info" | grep -qx 'TeamIdentifier=EYF346PHUG' || return 1
  printf '%s\n' "$info" | grep -qx 'Identifier=buzz'
}

acp_pids() {
  ps -axww -o pid= -o comm= | awk '{p=$1; $1=""; sub(/^ /,""); n=split($0,a,"/"); if (a[n]=="buzz-acp") print p}' | sort -n
}

print_entry_hashes() {
  local d="$1" e
  for e in $ENTRIES buzz-health; do
    if [ -e "$d/$e" ]; then echo "  $e $(sha256_of "$d/$e")"; else echo "  $e <absent>"; fi
  done
}
