# shellcheck shell=bash
# Issue #61 shared definitions. Sourced by apply.sh / rollback.sh / verify.sh; never run directly.
#
# Environment overrides (rehearsal only; the live defaults need none of them):
#   ISSUE61_TARGET          instance.local.json to operate on (default: $HOME/lab/buzz/instance.local.json)
#   ISSUE61_EXPECT_OLD_SHA  pre-change sha256; only allowed when ISSUE61_TARGET is NOT the live file
#   ISSUE61_BACKUP_ROOT     backup root (default: <dir of target>/backups, i.e. ~/lab/buzz/backups live)

LIVE_TARGET="$HOME/lab/buzz/instance.local.json"
LIVE_OLD_SHA="5e372c4da16b6221dc6b959fd170e15bbbbee381d6d8bd9ff443874d26cef3b2"
# 沈予
AGENT_KEY="a558771623f29898/a2fe5d4920dd476e82a17e2cbcab6be525b211e5e3c9a1402a1792436af62587"
# shellcheck disable=SC2016  # jq \$k comes from --arg
# The ONLY change: delete these two keys from 沈予's binding_environment.
DEL_FILTER='del(.agents[$k].binding_environment.BUZZ_ACP_SESSION_POLICY, .agents[$k].binding_environment.BUZZ_ACP_MAX_TURNS_PER_SESSION)'

die() { # die CODE MESSAGE
  local code="$1"; shift
  echo "issue61: ERROR: $*" >&2
  exit "$code"
}
say() { echo "issue61: $*"; }

need() { command -v "$1" >/dev/null 2>&1 || die 2 "required command '$1' not found"; }

sha256_of() {
  if command -v shasum >/dev/null 2>&1; then shasum -a 256 "$1" | awk '{print $1}'
  else sha256sum "$1" | awk '{print $1}'; fi
}

mode_of() {
  if [ "$(uname)" = Darwin ]; then stat -f %Lp "$1"; else stat -c %a "$1"; fi
}

# Absolute, symlink-resolved directory + basename (file itself need not exist).
abspath() {
  local d
  d=$(cd "$(dirname "$1")" 2>/dev/null && pwd -P) || return 1
  printf '%s/%s\n' "$d" "$(basename "$1")"
}

gate() {
  [ "${ISSUE61_I_UNDERSTAND_LIVE:-}" = yes ] \
    || die 2 "refusing: set ISSUE61_I_UNDERSTAND_LIVE=yes (live landing only after Knox PASS + peng merge + Jenny announces #57 ended)"
}

# Sets TARGET, IS_LIVE, EXPECT_OLD_SHA, BACKUP_ROOT.
resolve() {
  TARGET="${ISSUE61_TARGET:-$LIVE_TARGET}"
  local t l
  t=$(abspath "$TARGET") || die 2 "directory of $TARGET does not exist"
  l=$(abspath "$LIVE_TARGET" 2>/dev/null || echo "$LIVE_TARGET")
  if [ "$t" = "$l" ]; then
    IS_LIVE=1
    if [ -n "${ISSUE61_EXPECT_OLD_SHA:-}" ] && [ "$ISSUE61_EXPECT_OLD_SHA" != "$LIVE_OLD_SHA" ]; then
      die 2 "ISSUE61_EXPECT_OLD_SHA may not override the pre-change sha256 of the live file"
    fi
    EXPECT_OLD_SHA="$LIVE_OLD_SHA"
  else
    IS_LIVE=0
    EXPECT_OLD_SHA="${ISSUE61_EXPECT_OLD_SHA:-}"
    [ -n "$EXPECT_OLD_SHA" ] || die 2 "rehearsal target $t needs ISSUE61_EXPECT_OLD_SHA"
  fi
  TARGET="$t"
  BACKUP_ROOT="${ISSUE61_BACKUP_ROOT:-$(dirname "$TARGET")/backups}"
  case "$BACKUP_ROOT" in /*) ;; *) die 2 "backup root must be absolute: $BACKUP_ROOT" ;; esac
  if [ "$IS_LIVE" = 1 ]; then
    case "$BACKUP_ROOT/" in
      /tmp/*|/private/tmp/*|/var/folders/*|/private/var/folders/*)
        die 2 "backup root must be persistent, not $BACKUP_ROOT" ;;
    esac
  fi
}

# Newest <ts>-issue61 backup dir under BACKUP_ROOT, or the one given.
find_backup() {
  local given="$1" b
  if [ -n "$given" ]; then
    [ -d "$given" ] || die 2 "backup dir $given not found"
    (cd "$given" && pwd -P); return
  fi
  b=$(find "$BACKUP_ROOT" -maxdepth 1 -type d -name '*-issue61' 2>/dev/null | LC_ALL=C sort | tail -n 1)
  [ -n "$b" ] || die 2 "no *-issue61 backup under $BACKUP_ROOT (pass --backup DIR)"
  echo "$b"
}

# assert_minus_two ORIGINAL CANDIDATE: jq -S (ORIGINAL minus the two keys) == jq -S CANDIDATE.
assert_minus_two() {
  cmp -s <(jq -S --arg k "$AGENT_KEY" "$DEL_FILTER" "$1") <(jq -S . "$2")
}

manifest_get() { # manifest_get DIR KEY
  sed -n "s/^$2=//p" "$1/manifest.txt" 2>/dev/null | tail -n 1
}
