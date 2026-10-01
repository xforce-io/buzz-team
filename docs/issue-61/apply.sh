#!/bin/bash
# Issue #61 apply: delete BUZZ_ACP_SESSION_POLICY and BUZZ_ACP_MAX_TURNS_PER_SESSION from
# 沈予's binding_environment in ~/lab/buzz/instance.local.json. Nothing else changes.
#   1. gate ISSUE61_I_UNDERSTAND_LIVE=yes; target must be a regular file (not a symlink) whose
#      sha256 equals the pre-change value (live: 5e372c4d…), else exit 3 without touching anything.
#   2. back up to <backup root>/<ts>-issue61/instance.local.json (cp -p, dir 0700;
#      live root ~/lab/buzz/backups, never /tmp) and check the backup sha256.
#   3. jq del of the two keys into a temp file in the same directory, same mode; assert
#      jq -S (backup minus two keys) == jq -S (temp); then atomic mv over the target.
#   4. re-assert on the target, print old/new sha256, write manifest.txt + diffs to the backup dir.
# Does not restart, signal or read the environment of any process; does not touch managed-agents.json.
#
# Usage: ISSUE61_I_UNDERSTAND_LIVE=yes apply.sh
set -euo pipefail
# shellcheck source=SCRIPTDIR/common.sh
source "$(cd "$(dirname "$0")" && pwd)/common.sh"

[ $# -eq 0 ] || die 2 "apply.sh takes no arguments"
gate
need jq
resolve

# ---- preconditions (nothing is written until all pass)
[ ! -L "$TARGET" ] || die 3 "$TARGET is a symlink; refusing"
[ -f "$TARGET" ] || die 3 "$TARGET missing"
got=$(sha256_of "$TARGET")
[ "$got" = "$EXPECT_OLD_SHA" ] || die 3 "$TARGET sha256 $got != expected pre-change $EXPECT_OLD_SHA (already applied or changed?); nothing touched"
jq -e --arg k "$AGENT_KEY" '.agents[$k].binding_environment
  | (.BUZZ_ACP_SESSION_POLICY == "thread") and (.BUZZ_ACP_MAX_TURNS_PER_SESSION == "4")
    and (.BUZZ_ACP_CONFIG | type == "string" and length > 0)' "$TARGET" >/dev/null \
  || die 3 "沈予 binding_environment is not in the expected pre-change state; nothing touched"
mode=$(mode_of "$TARGET")
say "target $TARGET (mode $mode) sha256 $got matches pre-change value"

# ---- backup
ts=$(date +%Y%m%dT%H%M%S)
B="$BACKUP_ROOT/$ts-issue61"
[ ! -e "$B" ] || die 3 "$B already exists; retry in a second"
mkdir -p "$BACKUP_ROOT"
mkdir -m 700 "$B"
cp -p "$TARGET" "$B/instance.local.json"
[ "$(sha256_of "$B/instance.local.json")" = "$EXPECT_OLD_SHA" ] || die 4 "backup sha256 mismatch; target untouched"
{
  echo "issue=61"
  echo "target=$TARGET"
  echo "created_at=$ts"
  echo "old_sha256=$EXPECT_OLD_SHA"
  echo "mode=$mode"
} > "$B/manifest.txt"
say "backup $B/instance.local.json (sha256 verified)"

# ---- build the new file next to the target, verify, then atomic mv
TMP=$(mktemp "$(dirname "$TARGET")/.instance.local.json.issue61.XXXXXX")
trap 'rm -f "$TMP"' EXIT
jq --arg k "$AGENT_KEY" "$DEL_FILTER" "$B/instance.local.json" > "$TMP"
chmod "$mode" "$TMP"
assert_minus_two "$B/instance.local.json" "$TMP" || die 4 "candidate is not original minus the two keys; target untouched"
jq -e --arg k "$AGENT_KEY" '.agents[$k].binding_environment
  | (has("BUZZ_ACP_SESSION_POLICY") | not) and (has("BUZZ_ACP_MAX_TURNS_PER_SESSION") | not)
    and (.BUZZ_ACP_CONFIG | type == "string" and length > 0)' "$TMP" >/dev/null \
  || die 4 "candidate key check failed; target untouched"
new_sha=$(sha256_of "$TMP")
[ "$(sha256_of "$TARGET")" = "$EXPECT_OLD_SHA" ] || die 3 "target changed during apply; target untouched"
mv -f "$TMP" "$TARGET"
trap - EXIT

# ---- post-checks
[ "$(sha256_of "$TARGET")" = "$new_sha" ] || die 4 "post-mv sha256 mismatch; run rollback.sh"
assert_minus_two "$B/instance.local.json" "$TARGET" || die 4 "post-mv jq -S check failed; run rollback.sh"
[ "$(mode_of "$TARGET")" = "$mode" ] || die 4 "mode changed; run rollback.sh"
echo "new_sha256=$new_sha" >> "$B/manifest.txt"
diff -u "$B/instance.local.json" "$TARGET" > "$B/raw.diff" || true
diff -u <(jq -S . "$B/instance.local.json") <(jq -S . "$TARGET") > "$B/jq-S.diff" || true
say "applied: removed BUZZ_ACP_SESSION_POLICY, BUZZ_ACP_MAX_TURNS_PER_SESSION from 沈予; BUZZ_ACP_CONFIG kept"
say "old sha256 $EXPECT_OLD_SHA"
say "new sha256 $new_sha"
say "backup dir $B (manifest.txt, raw.diff, jq-S.diff); rollback: ISSUE61_I_UNDERSTAND_LIVE=yes rollback.sh --backup $B"
