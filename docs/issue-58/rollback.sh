#!/bin/bash
# Issue #58 rollback: restore the four 595c0cfe entries and README.md, remove bin/buzz-health.
# Source: the apply backup (default: path in <target>/backups/issue58-latest), or
# --from-template to regenerate the canonical 595c0cfe entries when no backup is usable
# (README.md is then NOT restored and must be restored manually; the script prints this).
# Every restored entry must match the recorded 595c0cfe sha256.
# Does not restart Desktop or touch any process.
#
# Usage: rollback.sh [--target DIR] [--backup DIR | --from-template]
set -euo pipefail
source "$(cd "$(dirname "$0")" && pwd)/common.sh"

T=""; B=""; TEMPLATE=no
while [ $# -gt 0 ]; do
  case "$1" in
    --target) T="$2"; shift 2 ;;
    --backup) B="$2"; shift 2 ;;
    --from-template) TEMPLATE=yes; shift ;;
    *) die "unknown argument $1" ;;
  esac
done
resolve_target "$T"
BIN="$TARGET/bin"
[ -d "$BIN" ] || die "$BIN missing"
echo "before:"; print_entry_hashes "$BIN"

STAGE="$BIN/.issue58-rollback.$$"
mkdir "$STAGE"
trap 'rm -rf "$STAGE"' EXIT
if [ "$TEMPLATE" = yes ]; then
  for e in $ENTRIES; do entry_595_text "$e" > "$STAGE/$e"; done
  echo "issue58: source=template (595c0cfe)"
  echo "issue58: NOTE: --from-template restores the four bin/ entries only; README.md is NOT restored and must be restored manually (e.g. from backups/<ts>-issue58/README.md)"
else
  if [ -z "$B" ]; then
    [ -f "$TARGET/backups/issue58-latest" ] || die "no --backup and no backups/issue58-latest"
    B="$(cat "$TARGET/backups/issue58-latest")"
  fi
  [ -f "$B/manifest.sha256" ] || die "$B/manifest.sha256 missing"
  ( cd "$B" && while read -r sum file; do
      [ "$(sha256_of "$file")" = "$sum" ] || { echo "issue58: ABORT: backup $file changed since apply" >&2; exit 1; }
    done < manifest.sha256 )
  for e in $ENTRIES; do cp "$B/bin/$e" "$STAGE/$e"; done
  echo "issue58: source=backup $B"
fi
for e in $ENTRIES; do
  got=$(sha256_of "$STAGE/$e")
  [ "$got" = "$(expected_595_sha "$e")" ] || die "staged $e is not the 595c0cfe entry ($got); nothing restored"
  chmod 700 "$STAGE/$e"
done

# ---- restore (all checks passed)
for e in $ENTRIES; do mv -f "$STAGE/$e" "$BIN/$e"; done
if [ -e "$BIN/buzz-health" ]; then
  if [ "$TEMPLATE" = no ]; then mkdir -p "$B/rolled-back" && mv "$BIN/buzz-health" "$B/rolled-back/buzz-health"
  else rm -f "$BIN/buzz-health"; fi
fi
if [ "$TEMPLATE" = no ]; then
  cp -p "$B/README.md" "$TARGET/README.md.issue58-restore" && mv -f "$TARGET/README.md.issue58-restore" "$TARGET/README.md"
fi

echo "after:"; print_entry_hashes "$BIN"
for e in $ENTRIES; do
  [ "$(sha256_of "$BIN/$e")" = "$(expected_595_sha "$e")" ] || die "$e mismatch after restore"
done
[ ! -e "$BIN/buzz-health" ] || die "buzz-health still present"
echo "issue58: rolled back; 4/4 entries byte-identical to 595c0cfe"
if [ "$TEMPLATE" = yes ]; then
  echo "issue58: README.md NOT restored (--from-template): restore $TARGET/README.md manually"
fi
