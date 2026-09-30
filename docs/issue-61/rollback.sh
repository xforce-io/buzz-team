#!/bin/bash
# Issue #61 rollback: restore instance.local.json from the apply.sh backup.
#   - gate ISSUE61_I_UNDERSTAND_LIVE=yes; backup = --backup DIR or the newest <ts>-issue61 dir.
#   - the backup file's sha256 must equal the pre-change value (live: 5e372c4d…), else exit 4.
#   - target already at the pre-change sha256: nothing to do (exit 0).
#   - target must still be what apply.sh wrote (manifest new_sha256); if it drifted since apply,
#     refuse (exit 3) unless ISSUE61_FORCE_ROLLBACK=yes. The current file is copied into the
#     backup dir (pre-rollback-<ts>.json) before it is replaced.
#   - restore via temp file in the same directory (cp -p, keeps 0600) + atomic mv; verify sha256.
# No restart needed: no running process reads these two keys from instance.local.json.
#
# Usage: ISSUE61_I_UNDERSTAND_LIVE=yes rollback.sh [--backup DIR]
set -euo pipefail
# shellcheck source=SCRIPTDIR/common.sh
source "$(cd "$(dirname "$0")" && pwd)/common.sh"

GIVEN=""
while [ $# -gt 0 ]; do
  case "$1" in
    --backup) [ $# -ge 2 ] || die 2 "--backup needs a value"; GIVEN="$2"; shift 2 ;;
    *) die 2 "unknown argument $1" ;;
  esac
done
gate
resolve
B=$(find_backup "$GIVEN")
BF="$B/instance.local.json"
[ -f "$BF" ] || die 2 "$BF missing"
[ "$(sha256_of "$BF")" = "$EXPECT_OLD_SHA" ] || die 4 "backup $BF sha256 != pre-change $EXPECT_OLD_SHA; refusing to restore"
say "backup $BF verified (sha256 $EXPECT_OLD_SHA)"

[ ! -L "$TARGET" ] || die 3 "$TARGET is a symlink; refusing"
if [ -f "$TARGET" ]; then
  cur=$(sha256_of "$TARGET")
  if [ "$cur" = "$EXPECT_OLD_SHA" ]; then
    say "target already at pre-change sha256; nothing to do"
    exit 0
  fi
  applied=$(manifest_get "$B" new_sha256)
  if [ "$cur" != "$applied" ] && [ "${ISSUE61_FORCE_ROLLBACK:-}" != yes ]; then
    die 3 "target sha256 $cur is neither pre-change nor what apply.sh wrote (${applied:-none}); it changed since apply. Inspect first; ISSUE61_FORCE_ROLLBACK=yes overrides"
  fi
  ts=$(date +%Y%m%dT%H%M%S)
  cp -p "$TARGET" "$B/pre-rollback-$ts.json"
  say "current target saved to $B/pre-rollback-$ts.json"
fi

TMP=$(mktemp "$(dirname "$TARGET")/.instance.local.json.issue61.XXXXXX")
trap 'rm -f "$TMP"' EXIT
cp -p "$BF" "$TMP"
[ "$(sha256_of "$TMP")" = "$EXPECT_OLD_SHA" ] || die 4 "staged copy sha256 mismatch; target untouched"
mv -f "$TMP" "$TARGET"
trap - EXIT
[ "$(sha256_of "$TARGET")" = "$EXPECT_OLD_SHA" ] || die 4 "restored file sha256 mismatch"
echo "rolled_back_at=$(date +%Y%m%dT%H%M%S)" >> "$B/manifest.txt"
say "rolled back: $TARGET sha256 $EXPECT_OLD_SHA (mode $(mode_of "$TARGET"))"
