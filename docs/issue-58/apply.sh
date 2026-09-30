#!/bin/bash
# Issue #58 apply: install new-style ~/lab/buzz entries.
#   bin/buzz        -> signature-gated exec of the official Buzz CLI (docs/issue-58/bin/buzz)
#   bin/buzz-health -> read-only health check (docs/issue-58/bin/buzz-health)
#   bin/agent-harness -> retired (moved into the backup dir)
#   bin/agent-executor, bin/agent-worktree -> unchanged (595c0cfe, deprecated)
#   README.md line "**当前 buzz-team release pin…" -> replaced by instance-readme-line.md
# Touches only <target>/bin/{buzz,buzz-health,agent-harness}, <target>/README.md and
# <target>/backups/<ts>-issue58/. Does not restart Desktop, does not read or write
# managed-agents.json, workflows, channel_wake, proxy, colima, :3000/:4500 or any process.
#
# Usage: apply.sh [--target DIR]      (default ~/lab/buzz; live needs ISSUE58_I_UNDERSTAND_LIVE=yes)
set -euo pipefail
source "$(cd "$(dirname "$0")" && pwd)/common.sh"

T=""
while [ $# -gt 0 ]; do
  case "$1" in
    --target) T="$2"; shift 2 ;;
    *) die "unknown argument $1" ;;
  esac
done
resolve_target "$T"
BIN="$TARGET/bin"

# ---- preconditions (nothing is changed until all pass)
[ -d "$BIN" ] || die "$BIN missing"
for e in $ENTRIES; do
  [ -f "$BIN/$e" ] || die "$BIN/$e missing"
  got=$(sha256_of "$BIN/$e")
  [ "$got" = "$(expected_595_sha "$e")" ] || die "$BIN/$e is not the 595c0cfe entry (sha256 $got); refusing so rollback stays exact"
done
[ ! -e "$BIN/buzz-health" ] || die "$BIN/buzz-health already exists (already applied?)"
[ -f "$TARGET/README.md" ] || die "$TARGET/README.md missing"
grep -q '^\*\*当前 buzz-team release pin' "$TARGET/README.md" || die "README entry line not found"
for f in bin/buzz bin/buzz-health instance-readme-line.md; do
  [ -f "$ISSUE58_DIR/$f" ] || die "missing $ISSUE58_DIR/$f"
done
if [ -n "${ISSUE58_TEST_SKIP_SIGNATURE:-}" ]; then
  echo "issue58: TEST HOOK: signature precheck skipped (temp targets only)"
else
  official_signature_ok || die "official buzz CLI fails the signature gate; new bin/buzz would refuse to send"
  echo "issue58: official buzz CLI signature OK (codesign --strict, TeamIdentifier EYF346PHUG)"
fi

# ---- backup
STAMP=$(date +%Y%m%d-%H%M%S)
BACKUP="$TARGET/backups/${STAMP}-issue58"
[ ! -e "$BACKUP" ] || die "$BACKUP exists"
mkdir -p "$BACKUP/bin"
for e in $ENTRIES; do cp -p "$BIN/$e" "$BACKUP/bin/$e"; done
cp -p "$TARGET/README.md" "$BACKUP/README.md"
( cd "$BACKUP" && for f in bin/buzz bin/agent-executor bin/agent-harness bin/agent-worktree README.md; do
    echo "$(sha256_of "$f")  $f"; done ) > "$BACKUP/manifest.sha256"
for e in $ENTRIES; do
  cmp -s "$BIN/$e" "$BACKUP/bin/$e" || die "backup of $e differs"
done
echo "issue58: backup $BACKUP"
echo "before:"; print_entry_hashes "$BIN"

# ---- install (write next to the target, then rename)
install_entry() {
  local src="$1" dst="$2"
  cp "$src" "$dst.issue58-new"
  chmod 700 "$dst.issue58-new"
  mv -f "$dst.issue58-new" "$dst"
}
install_entry "$ISSUE58_DIR/bin/buzz" "$BIN/buzz"
install_entry "$ISSUE58_DIR/bin/buzz-health" "$BIN/buzz-health"
mkdir -p "$BACKUP/retired"
mv "$BIN/agent-harness" "$BACKUP/retired/agent-harness"

python3 - "$TARGET/README.md" "$ISSUE58_DIR/instance-readme-line.md" "$(basename "$BACKUP")" "$(date +%Y-%m-%d)" <<'PY'
import sys
from pathlib import Path
readme, template, backup, date = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], sys.argv[4]
line = template.read_text().strip().replace("{BACKUP}", backup).replace("{DATE}", date)
lines = readme.read_text().split("\n")
hits = [i for i, text in enumerate(lines) if text.startswith("**当前 buzz-team release pin")]
if len(hits) != 1:
    sys.exit("README entry line not unique")
lines[hits[0]] = line
tmp = readme.with_name(readme.name + ".issue58-new")
tmp.write_text("\n".join(lines))
tmp.replace(readme)
PY

echo "after:"; print_entry_hashes "$BIN"
echo "$BACKUP" > "$TARGET/backups/issue58-latest"
echo "issue58: applied. Rollback: $(dirname "$0")/rollback.sh --target $TARGET --backup $BACKUP"
