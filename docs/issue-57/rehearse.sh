#!/bin/bash
# Issue #57 temp-copy rehearsal + keel-verify evidence (macOS). Never modifies the live policy
# directory or managed-agents.json: apply/rollback only get --target <workdir>/policies and
# --inventory <workdir>/managed-agents.json (copies). Live reads (read-only): the 9 policies,
# managed-agents.json, buzz-acp whitelisted env (snapshot/verify), 周衡 Desktop logs (sizes).
# The Seatbelt probe writes only uniquely named probe files and deletes them at once (probe.sh).
#
# Usage: rehearse.sh <workdir under $HOME>     evidence lands in <workdir>/evidence
set -euo pipefail
source "$(cd "$(dirname "$0")" && pwd)/common.sh"
W="${1:?workdir}"
case "$W" in "$HOME"/*) ;; *) die "workdir must be under \$HOME" ;; esac
case "$W" in "$HOME/kairo"*|"$HOME/lab/buzz"*|"$HOME/Library"*|"$HOME/.local"*) die "workdir inside live data" ;; esac
[ ! -e "$W" ] || die "$W exists"
mkdir -p "$W"; chmod 700 "$W"; W="$(cd "$W" && pwd -P)"
E="$W/evidence"; C="$W/policies"; MA="$W/managed-agents.json"
mkdir -p "$E"
unset ISSUE57_I_UNDERSTAND_LIVE ISSUE57_THIN_PYTHON ISSUE57_TEST_NEW_POLICY ISSUE57_TEST_OLD_POLICY ISSUE57_TEST_PS_FIXTURE ISSUE57_TEST_BASELINE ISSUE57_TARGET
LIVE="$(cd "$LIVE_POLICIES" && pwd -P)"

live_state() {  # $1 = output file: policy sha, MA sha, buzz-acp pid set
  { echo "# $(date '+%Y-%m-%d %H:%M:%S %Z')"; print_policy_hashes "$LIVE"
    echo "managed-agents.json $(sha256_of "$INVENTORY")"
    echo "buzz-acp pids: $(ps -axww -o pid=,comm= | awk '$2 ~ /buzz-acp$/ {print $1}' | sort -n | tr '\n' ' ')"; } > "$1"
}

echo "== 0. meta"
{ echo "date: $(date '+%Y-%m-%d %H:%M:%S %Z')"; echo "repo_sha: ${ISSUE57_REPO_SHA:-unknown}"; sw_vers | tr '\t' ' '
  echo "workdir: $W"; echo "thin python: $LIVE_THIN_PY ($("$LIVE_THIN_PY" -c 'import sys; print(sys.version.split()[0])'))"
  echo "git blob ids of the rehearsed files:"
  ( cd "$ISSUE57_DIR" && for f in common.sh apply.sh rollback.sh verify.sh snapshot.sh probe.sh rehearse.sh issue57.py zhouheng-seatbelt.json zhouheng-seatbelt.before.json zhouheng-prompt-rule.md; do
      echo "  $(git hash-object "$f")  $f"; done ); } > "$E/00-meta.txt"
live_state "$E/02-live-before.txt"
bash "$ISSUE57_DIR/snapshot.sh" --out "$W/snapshot-before.json" > "$E/03-snapshot-before.txt"

echo "== 1. live pre-state verify (read-only, expect old)"
bash "$ISSUE57_DIR/verify.sh" --relays local --expect old --prompt absent > "$E/04-verify-live-pre-old.txt" 2>&1 || true

echo "== 2. temp copies"
mkdir "$C"; chmod 700 "$C"
cp -p "$LIVE"/*.json "$C/"
cp -p "$INVENTORY" "$MA"; chmod 600 "$MA"
{ echo "## copy policies"; print_policy_hashes "$C"; echo "managed-agents.json copy $(sha256_of "$MA")"; } > "$E/05-copy-before.txt"
bash "$ISSUE57_DIR/verify.sh" --relays local --target "$C" --expect old --static-only --inventory "$MA" --prompt absent > "$E/06-verify-copy-0-old.txt" 2>&1 || true

echo "== 3. apply on copy"
[ "$C" != "$LIVE" ] || die "refusing: target is live"
bash "$ISSUE57_DIR/apply.sh" --target "$C" --inventory "$MA" > "$E/07-apply.txt" 2>&1
bash "$ISSUE57_DIR/verify.sh" --relays local --target "$C" --expect new --static-only --inventory "$MA" --prompt present > "$E/08-verify-copy-1-new.txt" 2>&1 || true

echo "== 4. sandbox probe with the applied copy"
bash "$ISSUE57_DIR/probe.sh" --policy "$C/$POLICY_NAME" --workdir "$W/probe" --out "$E/09-probe" > /dev/null 2>&1 || true

echo "== 5. rollback (backup) on copy"
bash "$ISSUE57_DIR/rollback.sh" --target "$C" --inventory "$MA" > "$E/10-rollback.txt" 2>&1
bash "$ISSUE57_DIR/verify.sh" --relays local --target "$C" --expect old --static-only --inventory "$MA" --prompt absent > "$E/11-verify-copy-2-old.txt" 2>&1 || true
{ echo "## copy after rollback"; print_policy_hashes "$C"; echo "managed-agents.json copy $(sha256_of "$MA")"
  echo "## live"; print_policy_hashes "$LIVE"; echo "managed-agents.json live $(sha256_of "$INVENTORY")"
  cmp "$C/$POLICY_NAME" "$LIVE/$POLICY_NAME" && echo "zhouheng policy: copy byte-identical to live (9e087351)"
  cmp "$MA" "$INVENTORY" && echo "managed-agents.json: copy byte-identical to live"; } > "$E/12-copy-after-rollback.txt" 2>&1 || true

echo "== 6. rollback --from-template"
{ bash "$ISSUE57_DIR/apply.sh" --target "$C" && bash "$ISSUE57_DIR/rollback.sh" --target "$C" --from-template; } > "$E/13-template-rollback.txt" 2>&1 || echo "TEMPLATE ROLLBACK FAILED" >> "$E/13-template-rollback.txt"

echo "== 7. negatives"
{
  echo "### apply with a policy that names a missing directory (must refuse, nothing changed)"
  "$PY3" -c 'import json,sys; p=json.load(open(sys.argv[1])); p["write_paths"].append(sys.argv[3]); open(sys.argv[2],"w").write(json.dumps(p,indent=2))' "$NEW_POLICY" "$W/broken.json" "$HOME/kairo/does-not-exist-scout57"
  ISSUE57_TEST_NEW_POLICY="$W/broken.json" bash "$ISSUE57_DIR/apply.sh" --target "$C" 2>&1 && echo "UNEXPECTED rc=0" || echo "rc=$? (expected non-zero)"
  echo "zhouheng copy sha256 after refused apply: $(sha256_of "$C/$POLICY_NAME")"
  echo "### apply refuses the live managed-agents.json while Desktop runs"
  bash "$ISSUE57_DIR/apply.sh" --target "$C" --inventory "$INVENTORY" 2>&1 && echo "UNEXPECTED rc=0" || echo "rc=$? (expected non-zero)"
  echo "zhouheng copy sha256: $(sha256_of "$C/$POLICY_NAME")"
  echo "### apply on the live directory without ISSUE57_I_UNDERSTAND_LIVE (must refuse)"
  bash "$ISSUE57_DIR/apply.sh" 2>&1 && echo "UNEXPECTED rc=0" || echo "rc=$? (expected non-zero)"
  echo "### verify with 周衡 local process missing BUZZ_TEAM_POLICY_PATH (fixture from the live snapshot)"
  "$PY3" - "$W/snapshot-before.json" "$W/fixture-missing-policy.json" <<'PY'
import json, sys
snap = json.load(open(sys.argv[1]))
procs = snap["processes"]
for p in procs:
    if p["seat"] == "zhouheng" and p["relay"] == "local":
        p["env"].pop("BUZZ_TEAM_POLICY_PATH", None)
        p["env"]["GROK_HOME"] = p["env"].get("GROK_HOME", "")
json.dump(procs, open(sys.argv[2], "w"))
PY
  ISSUE57_TEST_PS_FIXTURE="$W/fixture-missing-policy.json" bash "$ISSUE57_DIR/verify.sh" --relays local --expect old 2>&1 | grep -E "NOTE|FAIL|VERIFY" || true
} > "$E/14-negatives.txt" 2>&1

echo "== 8. live after"
live_state "$E/15-live-after.txt"
bash "$ISSUE57_DIR/snapshot.sh" --out "$W/snapshot-after.json" > "$E/16-snapshot-after.txt"
{ diff <(sed 1d "$E/02-live-before.txt") <(sed 1d "$E/15-live-after.txt") && echo "IDENTICAL: live policies, managed-agents.json, buzz-acp pid set"; } > "$E/17-live-diff.txt" 2>&1 || true
grep -rIl -E 'PRIVATE_KEY|nsec1|BUZZ_PRIVATE|BUZZ_AUTH_TAG=' "$E" > "$E/18-redaction-check.txt" 2>&1 || echo "0 files match PRIVATE_KEY|nsec1|BUZZ_PRIVATE|BUZZ_AUTH_TAG=" > "$E/18-redaction-check.txt"
echo "rehearsal done: $E"
