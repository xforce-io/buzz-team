# shellcheck shell=bash
# Shared helpers for issue #57 apply / rollback / verify / snapshot / probe. Bash 3.2 compatible.

ISSUE57_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIVE_POLICIES="${HOME}/lab/buzz/policies"
POLICY_NAME=zhouheng-seatbelt.json
# Rollback point (peng safeguard): live 周衡 policy before #57, write_paths [].
OLD_SHA=9e08735172c519e25a44c2ee92479a1fcedd9b031adfbd98c10336b005a13c23
NEW_POLICY="$ISSUE57_DIR/zhouheng-seatbelt.json"
BEFORE_POLICY="$ISSUE57_DIR/zhouheng-seatbelt.before.json"
RULE_FILE="$ISSUE57_DIR/zhouheng-prompt-rule.md"
HELPER="$ISSUE57_DIR/issue57.py"
# Python of the venv that serves the live seats' buzz-team-thin (cb63521 wheel).
LIVE_THIN_PY="${HOME}/lab/buzz/evidence/f66ef5e-preview/venv/bin/python"
INVENTORY="${HOME}/Library/Application Support/xyz.block.buzz.app/agents/managed-agents.json"
PY3=/usr/bin/python3; [ -x "$PY3" ] || PY3=python3

sha256_of() {
  if command -v shasum >/dev/null 2>&1; then shasum -a 256 "$1" | awk '{print $1}'
  else sha256sum "$1" | awk '{print $1}'; fi
}

die() { echo "issue57: ABORT: $*" >&2; exit 1; }

real_path() { (cd "$(dirname "$1")" 2>/dev/null && echo "$(pwd -P)/$(basename "$1")"); }

# Sets TARGET (policies directory), IS_LIVE, THIN_PY, EXPECT_OLD_SHA, SOURCE_POLICY.
resolve_target() {
  local t="${1:-${ISSUE57_TARGET:-$LIVE_POLICIES}}"
  [ -d "$t" ] || die "target $t is not a directory"
  TARGET="$(cd "$t" && pwd -P)"
  IS_LIVE=no
  if [ -d "$LIVE_POLICIES" ] && [ "$TARGET" = "$(cd "$LIVE_POLICIES" && pwd -P)" ]; then IS_LIVE=yes; fi
  THIN_PY="${ISSUE57_THIN_PYTHON:-$LIVE_THIN_PY}"
  EXPECT_OLD_SHA="$OLD_SHA"; SOURCE_POLICY="$NEW_POLICY"; TEMPLATE_POLICY="$BEFORE_POLICY"
  if [ "$IS_LIVE" = yes ]; then
    [ "${ISSUE57_I_UNDERSTAND_LIVE:-}" = yes ] || die "target is the live policy directory; set ISSUE57_I_UNDERSTAND_LIVE=yes (see docs/issue-57/README.md)"
    local v
    for v in ISSUE57_THIN_PYTHON ISSUE57_TEST_NEW_POLICY ISSUE57_TEST_OLD_POLICY ISSUE57_TEST_PS_FIXTURE; do
      [ -z "$(eval echo "\${$v:-}")" ] || die "$v is test-only; refused on the live policy directory"
    done
  else
    if [ -n "${ISSUE57_TEST_NEW_POLICY:-}" ]; then SOURCE_POLICY="$ISSUE57_TEST_NEW_POLICY"; echo "issue57: TEST HOOK new policy $SOURCE_POLICY"; fi
    if [ -n "${ISSUE57_TEST_OLD_POLICY:-}" ]; then
      TEMPLATE_POLICY="$ISSUE57_TEST_OLD_POLICY"; EXPECT_OLD_SHA="$(sha256_of "$ISSUE57_TEST_OLD_POLICY")"
      echo "issue57: TEST HOOK rollback point $EXPECT_OLD_SHA"
    fi
  fi
  [ -x "$THIN_PY" ] || die "thin python $THIN_PY not executable"
  echo "issue57: target=$TARGET live=$IS_LIVE thin_python=$THIN_PY"
}

# Runs buzz_team.thin._load_policy (+ profile render) on $1 with 周衡's GROK_HOME.
precheck() {
  local policy="$1"; shift
  "$THIN_PY" "$HELPER" precheck --policy "$policy" "$@"
}

print_policy_hashes() {
  local d="$1" f
  for f in "$d"/*.json; do echo "  $(sha256_of "$f")  $(basename "$f")"; done
}

other_hashes() {  # sha256 of every policy except 周衡's, one line each
  local d="$1" f
  for f in "$d"/*.json; do [ "$(basename "$f")" = "$POLICY_NAME" ] || echo "$(sha256_of "$f")  $(basename "$f")"; done
}

desktop_running() { pgrep -f '/Applications/Buzz.app/Contents/MacOS/buzz-desktop' >/dev/null 2>&1; }

is_live_inventory() {
  [ -f "$INVENTORY" ] && [ "$(real_path "$1")" = "$(real_path "$INVENTORY")" ]
}
