#!/bin/bash
# Issue #57 read-only snapshot of all buzz-acp processes per relay (pid, lstart,
# BUZZ_ACP_AGENT_COMMAND, BUZZ_TEAM_POLICY_PATH, KAIRO_PROVIDER, six proxy vars, relay TCP state,
# grok children), the 9 policy sha256 and 周衡's two managed-agents rows (prompt sha, rule count).
# Only whitelisted env keys are kept; private keys are never read into the output.
#
# Usage: snapshot.sh [--out FILE.json]      (prints a table; --out also saves JSON)
set -euo pipefail
source "$(cd "$(dirname "$0")" && pwd)/common.sh"
OUT=()
while [ $# -gt 0 ]; do
  case "$1" in
    --out) OUT=(--out "$2"); shift 2 ;;
    *) die "unknown argument $1" ;;
  esac
done
echo "# issue57 snapshot $(date '+%Y-%m-%d %H:%M:%S %Z')"
"$PY3" "$HELPER" snapshot --policies "${ISSUE57_TARGET:-$LIVE_POLICIES}" --rule "$RULE_FILE" ${OUT[@]+"${OUT[@]}"}
