#!/bin/bash
# Issue #57 apply: install the new 周衡 Seatbelt policy (5 Kairo write paths).
#   1. preconditions: 周衡 policy sha256 = 9e087351 (rollback point), 9 policy files, thin python;
#      the new policy is staged next to the live file (0600) and must pass
#      buzz_team.thin._load_policy before anything changes.
#   2. backup: <target>/zhouheng-seatbelt.json.issue57-<ts>.bak (0600, same directory) and
#      <target>/../backups/issue57-<ts>/ (manifest, optional managed-agents.json copy).
#   3. install (atomic mv, 0600), precheck again; on failure restore the backup automatically.
#   4. optional --inventory FILE: insert the prompt rule into both 周衡 rows. Refused for the
#      live managed-agents.json while Buzz Desktop runs (Desktop rewrites the file from memory on
#      agent start, #38 A6/A11); the live prompt is edited in the Desktop UI (README step 4).
#   5. print the 9 policy sha256; the other 8 must be unchanged.
# Does not restart, signal or read the environment of any process.
#
# Usage: apply.sh [--target POLICY_DIR] [--inventory FILE]   (live needs ISSUE57_I_UNDERSTAND_LIVE=yes)
set -euo pipefail
source "$(cd "$(dirname "$0")" && pwd)/common.sh"

T=""; INV=""
while [ $# -gt 0 ]; do
  case "$1" in
    --target) T="$2"; shift 2 ;;
    --inventory) INV="$2"; shift 2 ;;
    *) die "unknown argument $1" ;;
  esac
done
resolve_target "$T"
LIVEFILE="$TARGET/$POLICY_NAME"

# ---- preconditions (nothing changes until all pass)
[ -f "$LIVEFILE" ] || die "$LIVEFILE missing"
got=$(sha256_of "$LIVEFILE")
[ "$got" = "$EXPECT_OLD_SHA" ] || die "$LIVEFILE sha256 $got is not the rollback point $EXPECT_OLD_SHA (already applied?)"
n=$(ls "$TARGET"/*.json | wc -l | tr -d ' ')
[ "$n" = 9 ] || die "expected 9 policy files in $TARGET, found $n"
[ -f "$SOURCE_POLICY" ] || die "missing $SOURCE_POLICY"
if [ -n "$INV" ]; then
  [ -f "$INV" ] || die "inventory $INV missing"
  if is_live_inventory "$INV" && desktop_running; then
    die "Buzz Desktop is running: do not write the live managed-agents.json; add the rule in the Desktop UI (README step 4)"
  fi
fi
STAGE="$TARGET/.$POLICY_NAME.issue57-new"
rm -f "$STAGE"
trap 'rm -f "$STAGE"' EXIT
cp "$SOURCE_POLICY" "$STAGE"
chmod 600 "$STAGE"
precheck "$STAGE" >/dev/null 2>"$STAGE.err" || { cat "$STAGE.err" >&2; rm -f "$STAGE.err"; die "new policy fails thin._load_policy; nothing changed"; }
rm -f "$STAGE.err"
echo "issue57: staged new policy passes thin._load_policy"
OTHERS_BEFORE="$(other_hashes "$TARGET")"
echo "before:"; print_policy_hashes "$TARGET"

# ---- backup
STAMP=$(date +%Y%m%d-%H%M%S)
BACKUP_FILE="$TARGET/$POLICY_NAME.issue57-$STAMP.bak"
BACKUP_DIR="$(dirname "$TARGET")/backups/issue57-$STAMP"
[ ! -e "$BACKUP_FILE" ] && [ ! -e "$BACKUP_DIR" ] || die "backup $STAMP exists"
cp -p "$LIVEFILE" "$BACKUP_FILE"; chmod 600 "$BACKUP_FILE"
[ "$(sha256_of "$BACKUP_FILE")" = "$EXPECT_OLD_SHA" ] || die "backup copy differs"
mkdir -p "$BACKUP_DIR"; chmod 700 "$BACKUP_DIR"
{ echo "policy_backup=$BACKUP_FILE"; echo "policy_sha256=$EXPECT_OLD_SHA"; } > "$BACKUP_DIR/manifest"
if [ -n "$INV" ]; then
  cp -p "$INV" "$BACKUP_DIR/managed-agents.json"; chmod 600 "$BACKUP_DIR/managed-agents.json"
  { echo "inventory=$(real_path "$INV")"; echo "inventory_sha256=$(sha256_of "$INV")"; } >> "$BACKUP_DIR/manifest"
fi
echo "$BACKUP_DIR" > "$(dirname "$TARGET")/backups/issue57-latest"
echo "issue57: backup $BACKUP_FILE (+ $BACKUP_DIR)"

restore_policy() {
  cp -p "$BACKUP_FILE" "$STAGE" && chmod 600 "$STAGE" && mv -f "$STAGE" "$LIVEFILE"
  [ "$(sha256_of "$LIVEFILE")" = "$EXPECT_OLD_SHA" ] && echo "issue57: restored rollback point $EXPECT_OLD_SHA" >&2
}

# ---- install
mv -f "$STAGE" "$LIVEFILE"
chmod 600 "$LIVEFILE"
if ! precheck "$LIVEFILE" > "$BACKUP_DIR/precheck-after-apply.json" 2>"$BACKUP_DIR/precheck-after-apply.err"; then
  cat "$BACKUP_DIR/precheck-after-apply.err" >&2
  restore_policy
  die "installed policy fails thin._load_policy; automatically rolled back"
fi
echo "issue57: installed policy passes thin._load_policy: $(tail -1 "$BACKUP_DIR/precheck-after-apply.json")"

if [ -n "$INV" ]; then
  if ! "$PY3" "$HELPER" insert-rule --inventory "$INV" --rule "$RULE_FILE"; then
    cp -p "$BACKUP_DIR/managed-agents.json" "$INV"
    restore_policy
    die "prompt rule insertion failed; policy and inventory rolled back"
  fi
fi

echo "after:"; print_policy_hashes "$TARGET"
[ "$(other_hashes "$TARGET")" = "$OTHERS_BEFORE" ] || die "other policy files changed during apply"
echo "issue57: other 8 policies unchanged"
echo "issue57: applied $(sha256_of "$LIVEFILE"). Rollback: $(dirname "$0")/rollback.sh --target $TARGET${INV:+ --inventory $INV}"
