#!/bin/bash
# Issue #57 rollback to the rollback point 9e087351 (周衡 policy before #57, write_paths []).
# Source: the apply backup (default <target>/../backups/issue57-latest) or --from-template
# (docs/issue-57/zhouheng-seatbelt.before.json, byte-identical to 9e087351). The staged file must
# hash to 9e087351 before it replaces the live one; afterwards thin._load_policy must pass.
# --inventory FILE restores managed-agents.json from the same backup (refused for the live file
# while Buzz Desktop runs; then remove the rule line in the Desktop UI).
# Does not restart, signal or read the environment of any process.
#
# Usage: rollback.sh [--target POLICY_DIR] [--backup-dir DIR | --from-template] [--inventory FILE]
set -euo pipefail
source "$(cd "$(dirname "$0")" && pwd)/common.sh"

T=""; B=""; TEMPLATE=no; INV=""
while [ $# -gt 0 ]; do
  case "$1" in
    --target) T="$2"; shift 2 ;;
    --backup-dir) B="$2"; shift 2 ;;
    --from-template) TEMPLATE=yes; shift ;;
    --inventory) INV="$2"; shift 2 ;;
    *) die "unknown argument $1" ;;
  esac
done
resolve_target "$T"
LIVEFILE="$TARGET/$POLICY_NAME"
OTHERS_BEFORE="$(other_hashes "$TARGET")"
echo "before:"; print_policy_hashes "$TARGET"

if [ "$TEMPLATE" = yes ]; then
  SRC="$TEMPLATE_POLICY"
  [ -z "$INV" ] || die "--inventory needs a backup; not with --from-template"
else
  if [ -z "$B" ]; then
    PTR="$(dirname "$TARGET")/backups/issue57-latest"
    [ -f "$PTR" ] || die "no --backup-dir and no $PTR (use --from-template)"
    B="$(cat "$PTR")"
  fi
  [ -f "$B/manifest" ] || die "$B/manifest missing"
  SRC="$(sed -n 's/^policy_backup=//p' "$B/manifest")"
fi
[ -f "$SRC" ] || die "rollback source $SRC missing"
[ "$(sha256_of "$SRC")" = "$EXPECT_OLD_SHA" ] || die "rollback source $SRC is not $EXPECT_OLD_SHA; nothing restored"
if [ -n "$INV" ]; then
  [ -f "$B/managed-agents.json" ] || die "backup has no managed-agents.json"
  if is_live_inventory "$INV" && desktop_running; then
    die "Buzz Desktop is running: do not write the live managed-agents.json; remove the rule line in the Desktop UI"
  fi
fi

STAGE="$TARGET/.$POLICY_NAME.issue57-rollback"
trap 'rm -f "$STAGE"' EXIT
cp "$SRC" "$STAGE"; chmod 600 "$STAGE"
[ "$(sha256_of "$STAGE")" = "$EXPECT_OLD_SHA" ] || die "staged copy differs"
mv -f "$STAGE" "$LIVEFILE"
got=$(sha256_of "$LIVEFILE")
[ "$got" = "$EXPECT_OLD_SHA" ] || die "$LIVEFILE sha256 $got after restore"
echo "issue57: $POLICY_NAME restored, sha256 $got (rollback point)"
if [ -n "$INV" ]; then
  cp -p "$B/managed-agents.json" "$INV"
  want="$(sed -n 's/^inventory_sha256=//p' "$B/manifest")"
  [ "$(sha256_of "$INV")" = "$want" ] || die "inventory restore mismatch"
  echo "issue57: inventory restored byte-identical ($want)"
fi
echo "after:"; print_policy_hashes "$TARGET"
[ "$(other_hashes "$TARGET")" = "$OTHERS_BEFORE" ] || die "other policy files changed during rollback"
echo "issue57: other 8 policies unchanged"
precheck "$LIVEFILE" >/dev/null 2>&1 || die "restored policy fails thin._load_policy (file is restored; report to Jenny)"
echo "issue57: restored policy passes thin._load_policy"
echo "issue57: rolled back. Restart 周衡 (README step R) so the seats load it again."
