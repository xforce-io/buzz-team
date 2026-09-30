#!/bin/bash
# shellcheck disable=SC2016  # jq programs use $k from --arg; single quotes are intended
# Issue #61 verify (read-only except the evidence dir).
#   --expect old : sha256 == pre-change value; 沈予 has BUZZ_ACP_SESSION_POLICY="thread",
#                  BUZZ_ACP_MAX_TURNS_PER_SESSION="4" and a non-empty BUZZ_ACP_CONFIG.
#   --expect new : both keys absent, BUZZ_ACP_CONFIG present, and jq -S (target) ==
#                  jq -S (backup minus the two keys), backup sha256 == pre-change value;
#                  the 595c0cf status output must NOT contain "unsupported binding environment override".
# Always runs (read-only) the 595c0cf status command and records its output:
#   PYTHONDONTWRITEBYTECODE=1 ~/.local/share/buzz-team/releases/595c0cfe*/bin/python \
#     -m buzz_team.cli --instance ~/lab/buzz status
# (bin/buzz now forwards to the official CLI, which has no status command.)
# Also records the managed-agents.json sha256 (path from .desktop.managed_agents) and, with
# --shenyu-pid PID, only the two BUZZ_ACP_* variables from that process's environment (ps eww).
#
# Usage: verify.sh --expect old|new --evidence DIR [--backup DIR] [--shenyu-pid PID]
# Rehearsal overrides: ISSUE61_PY (python with buzz_team 595c0cf), ISSUE61_INSTANCE_DIR.
# Exit 0 = all checks PASS, 1 = some FAIL, 2 = usage.
set -euo pipefail
# shellcheck source=SCRIPTDIR/common.sh
source "$(cd "$(dirname "$0")" && pwd)/common.sh"

EXPECT=""; EVID=""; GIVEN=""; PID=""
while [ $# -gt 0 ]; do
  case "$1" in
    --expect) [ $# -ge 2 ] || die 2 "--expect needs a value"; EXPECT="$2"; shift 2 ;;
    --evidence) [ $# -ge 2 ] || die 2 "--evidence needs a value"; EVID="$2"; shift 2 ;;
    --backup) [ $# -ge 2 ] || die 2 "--backup needs a value"; GIVEN="$2"; shift 2 ;;
    --shenyu-pid) [ $# -ge 2 ] || die 2 "--shenyu-pid needs a value"; PID="$2"; shift 2 ;;
    *) die 2 "unknown argument $1" ;;
  esac
done
case "$EXPECT" in old|new) ;; *) die 2 "--expect old|new required" ;; esac
[ -n "$EVID" ] || die 2 "--evidence DIR required"
need jq
resolve
[ -f "$TARGET" ] || die 2 "$TARGET missing"

ts=$(date +%Y%m%dT%H%M%S)
E="$EVID/$ts-verify-$EXPECT"
mkdir -p "$E"
E=$(cd "$E" && pwd -P)
FAILS=0
check() { # check NAME CONDITION-EXIT-CODE
  local line="PASS $1"
  if [ "$2" != 0 ]; then line="FAIL $1"; FAILS=$((FAILS + 1)); fi
  echo "$line" | tee -a "$E/summary.txt"
}
note() { echo "NOTE $*" | tee -a "$E/summary.txt"; }

sha=$(sha256_of "$TARGET")
{
  echo "target=$TARGET"; echo "sha256=$sha"; echo "mode=$(mode_of "$TARGET")"
  echo "expect=$EXPECT"; echo "pre_change_sha256=$EXPECT_OLD_SHA"; echo "at=$ts"
  ls -l "$TARGET"
} > "$E/target.txt"
jq -S --arg k "$AGENT_KEY" '.agents[$k] | {label, binding_environment}' "$TARGET" > "$E/shenyu-binding-environment.json"

rc() { if "$@" >/dev/null 2>&1; then echo 0; else echo 1; fi; }
if [ "$EXPECT" = old ]; then
  check "S0 sha256 == pre-change $EXPECT_OLD_SHA (got $sha)" "$([ "$sha" = "$EXPECT_OLD_SHA" ] && echo 0 || echo 1)"
  check "S0 沈予 BUZZ_ACP_SESSION_POLICY == \"thread\"" \
    "$(rc jq -e --arg k "$AGENT_KEY" '.agents[$k].binding_environment.BUZZ_ACP_SESSION_POLICY == "thread"' "$TARGET")"
  check "S0 沈予 BUZZ_ACP_MAX_TURNS_PER_SESSION == \"4\"" \
    "$(rc jq -e --arg k "$AGENT_KEY" '.agents[$k].binding_environment.BUZZ_ACP_MAX_TURNS_PER_SESSION == "4"' "$TARGET")"
else
  check "S1 沈予 BUZZ_ACP_SESSION_POLICY absent" \
    "$(rc jq -e --arg k "$AGENT_KEY" '.agents[$k].binding_environment | has("BUZZ_ACP_SESSION_POLICY") | not' "$TARGET")"
  check "S1 沈予 BUZZ_ACP_MAX_TURNS_PER_SESSION absent" \
    "$(rc jq -e --arg k "$AGENT_KEY" '.agents[$k].binding_environment | has("BUZZ_ACP_MAX_TURNS_PER_SESSION") | not' "$TARGET")"
  if B=$(find_backup "$GIVEN" 2>>"$E/errors.txt") && [ -f "$B/instance.local.json" ]; then
    echo "backup=$B" >> "$E/target.txt"
    check "S1 backup $B/instance.local.json sha256 == pre-change" \
      "$([ "$(sha256_of "$B/instance.local.json")" = "$EXPECT_OLD_SHA" ] && echo 0 || echo 1)"
    check "S1 jq -S target == jq -S (backup minus the two keys); everything else identical" \
      "$(rc assert_minus_two "$B/instance.local.json" "$TARGET")"
    diff -u <(jq -S . "$B/instance.local.json") <(jq -S . "$TARGET") > "$E/jq-S.diff" || true
    applied=$(manifest_get "$B" new_sha256)
    if [ -n "$applied" ]; then
      check "S1 sha256 == manifest new_sha256 $applied (got $sha)" "$([ "$sha" = "$applied" ] && echo 0 || echo 1)"
    fi
  else
    check "S1 apply.sh backup found under $BACKUP_ROOT (or --backup)" 1
  fi
fi
check "S1 沈予 BUZZ_ACP_CONFIG present" \
  "$(rc jq -e --arg k "$AGENT_KEY" '.agents[$k].binding_environment.BUZZ_ACP_CONFIG | type == "string" and length > 0' "$TARGET")"

# ---- S2: 595c0cf status (read-only)
INST="${ISSUE61_INSTANCE_DIR:-$(dirname "$TARGET")}"
PY="${ISSUE61_PY:-}"
if [ -z "$PY" ]; then
  for p in "$HOME"/.local/share/buzz-team/releases/595c0cfe*/bin/python; do
    [ -x "$p" ] && PY="$p" && break
  done
fi
if [ -n "$PY" ] && [ -x "$PY" ]; then
  echo "PYTHONDONTWRITEBYTECODE=1 $PY -m buzz_team.cli --instance $INST status" > "$E/status.cmd"
  set +e
  PYTHONDONTWRITEBYTECODE=1 "$PY" -m buzz_team.cli --instance "$INST" status > "$E/status.out" 2>&1
  echo $? > "$E/status.exit"
  set -e
  if grep -q "unsupported binding environment override" "$E/status.out"; then unsupported=1; else unsupported=0; fi
  note "status exit=$(cat "$E/status.exit") output: $(head -c 400 "$E/status.out" | tr '\n' ' ')"
  if [ "$EXPECT" = new ]; then
    check "S2 status output has no 'unsupported binding environment override'" "$unsupported"
    ids=$(jq -r '.identities // empty' "$E/status.out" 2>/dev/null || true)
    note "status identities=${ids:-?} bound=$(jq -r 'if has("bound") then .bound else "?" end' "$E/status.out" 2>/dev/null || echo '?') (bound is recorded, not a failure condition)"
  else
    note "status reports unsupported binding environment override: $([ "$unsupported" = 1 ] && echo yes || echo no) (expected yes before apply)"
  fi
else
  echo "595c0cfe python not found" > "$E/status.out"
  if [ "$EXPECT" = new ]; then check "S2 595c0cfe python available for status" 1; else note "595c0cfe python not found; status skipped"; fi
fi

# ---- S3 evidence (record only)
MA=$(jq -r '.desktop.managed_agents // empty' "$TARGET")
if [ -n "$MA" ] && [ -f "$MA" ]; then
  echo "$(sha256_of "$MA")  $MA" > "$E/managed-agents.sha256"
  note "managed-agents.json sha256 $(cut -d' ' -f1 "$E/managed-agents.sha256") (S3: must equal the pre-landing value)"
fi
if [ -n "$PID" ]; then
  ps eww -p "$PID" -o command= 2>/dev/null | tr ' ' '\n' \
    | grep -E '^BUZZ_ACP_(SESSION_POLICY|MAX_TURNS_PER_SESSION)=' > "$E/shenyu-process-env.txt" || true
  note "pid $PID env: $(tr '\n' ' ' < "$E/shenyu-process-env.txt") (S3: expect thread / 4)"
fi

echo "evidence: $E"
if [ "$FAILS" = 0 ]; then echo "RESULT PASS ($EXPECT)" | tee -a "$E/summary.txt"; exit 0; fi
echo "RESULT FAIL ($EXPECT): $FAILS check(s) failed" | tee -a "$E/summary.txt"; exit 1
