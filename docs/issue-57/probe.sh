#!/bin/bash
# Issue #57 Seatbelt write probe (macOS). Renders the profile from a temp copy of a policy with the
# live seats' own launcher code (buzz_team.thin.command/_profile in the f66ef5e-preview venv, via
# issue57.py precheck) and runs /usr/bin/sandbox-exec with exactly that profile:
#   allowed: each write_path of the policy + 周衡 identity tmp/ (positive control) ->
#            create a uniquely named probe file and delete it at once, inside the sandbox;
#   denied:  ~/kairo, ~/kairo/<topic> roots, ~/.config/kairo, /private/tmp -> must be EPERM.
# Nothing else is written. A probe that survives (or an unexpected success) is removed at once
# and reported. Output: <out>/profile.sb, precheck.json, probe.txt.
#
# Usage: probe.sh --policy FILE --workdir DIR_UNDER_HOME --out DIR
set -euo pipefail
source "$(cd "$(dirname "$0")" && pwd)/common.sh"
P=""; W=""; O=""
while [ $# -gt 0 ]; do
  case "$1" in
    --policy) P="$2"; shift 2 ;;
    --workdir) W="$2"; shift 2 ;;
    --out) O="$2"; shift 2 ;;
    *) die "unknown argument $1" ;;
  esac
done
[ -f "$P" ] && [ -n "$W" ] && [ -n "$O" ] || die "usage: probe.sh --policy FILE --workdir DIR --out DIR"
[ -x /usr/bin/sandbox-exec ] || die "macOS sandbox-exec required"
THIN_PY="$LIVE_THIN_PY"
case "$(real_path "$P")" in "$(cd "$LIVE_POLICIES" && pwd -P)"/*) die "probe takes a temp copy, not the live policy" ;; esac
mkdir -p "$W/policy" "$O"; chmod 700 "$W" "$W/policy"
COPY="$W/policy/$POLICY_NAME"
cp "$P" "$COPY"; chmod 600 "$COPY"
precheck "$COPY" --profile-out "$O/profile.sb" --json-out "$O/precheck.json" > /dev/null
PROFILE="$(cat "$O/profile.sb")"
ID="$("$PY3" -c 'import json,sys; print(json.load(open(sys.argv[1]))["roots"][0])' "$O/precheck.json")"
STAMP="$(date +%Y%m%d%H%M%S)-$$"
NAME=".scout57-probe-$STAMP"
FAIL=0
R="$O/probe.txt"
{
  echo "date: $(date '+%Y-%m-%d %H:%M:%S %Z')"
  echo "policy copy: $COPY sha256 $(sha256_of "$COPY")"
  echo "profile: $O/profile.sb sha256 $(sha256_of "$O/profile.sb")"
  echo "rendered by: $("$PY3" -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d["thin_module"], "thin.py sha256", d["thin_py_sha256"], "package", d["package"].get("package_sha"), "|", d["rendered_by"])' "$O/precheck.json")"
  echo "probe name: $NAME"
} > "$R"

attempt() {  # $1 = allow|deny, $2 = directory
  local want="$1" d="$2" f="$2/$NAME" out rc
  out="$(/usr/bin/sandbox-exec -p "$PROFILE" /bin/sh -c ': > "$1" && rm -f "$1" && echo PROBE_CREATED_AND_DELETED' sh "$f" 2>&1 | grep -v 'MacSec error' || true)"
  if printf '%s' "$out" | grep -q PROBE_CREATED_AND_DELETED; then rc=ok; else rc=denied; fi
  if [ -e "$f" ]; then rm -f "$f"; echo "LEAK $f existed after probe; removed" >> "$R"; FAIL=1; fi
  if [ "$want" = allow ] && [ "$rc" = ok ]; then echo "PASS allow $d => created+deleted" >> "$R"
  elif [ "$want" = deny ] && [ "$rc" = denied ] && printf '%s' "$out" | grep -q 'Operation not permitted'; then echo "PASS deny  $d => $(printf '%s' "$out" | tr '\n' ' ' | sed 's/ *$//')" >> "$R"
  else echo "FAIL $want $d => $rc: $(printf '%s' "$out" | tr '\n' ' ')" >> "$R"; FAIL=1; fi
}

echo "## allowed (policy write_paths + identity tmp control)" >> "$R"
"$PY3" -c 'import json,sys; [print(p) for p in json.load(open(sys.argv[1]))["write_paths"]]' "$COPY" > "$W/allow.txt"
echo "$ID/tmp" >> "$W/allow.txt"
while IFS= read -r d; do attempt allow "$d"; done < "$W/allow.txt"
echo "## denied (must stay EPERM)" >> "$R"
for d in "$HOME/kairo" "$HOME/kairo/能源梳理" "$HOME/kairo/ai-native" "$HOME/.config/kairo" /private/tmp; do attempt deny "$d"; done
leftover=0
while IFS= read -r d; do [ ! -e "$d/$NAME" ] || leftover=1; done < "$W/allow.txt"
for d in "$HOME/kairo" "$HOME/kairo/能源梳理" "$HOME/kairo/ai-native" "$HOME/.config/kairo" /private/tmp; do [ ! -e "$d/$NAME" ] || leftover=1; done
echo "leftover probe files: $leftover" >> "$R"
[ "$FAIL" = 0 ] && [ "$leftover" = 0 ] && echo "PROBE PASS" >> "$R" || echo "PROBE FAIL" >> "$R"
cat "$R"
[ "$FAIL" = 0 ] && [ "$leftover" = 0 ]
