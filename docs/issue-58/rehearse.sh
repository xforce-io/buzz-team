#!/bin/bash
# Issue #58 temp-copy rehearsal + keel-verify evidence (macOS). Never modifies the live instance:
# apply/rollback only ever get --target <workdir>/instance, a copy of ~/lab/buzz/{bin,README.md}.
# Reads (read-only): live bin/README hashes, managed-agents.json, policies, custom_harnesses,
# buzz-acp env (3 variables only, via buzz-health), official buzz codesign.
#
# Usage: rehearse.sh <workdir under /tmp>     evidence lands in <workdir>/evidence
set -euo pipefail
source "$(cd "$(dirname "$0")" && pwd)/common.sh"
W="${1:?workdir}"
case "$W" in /tmp/*|/private/tmp/*) ;; *) die "workdir must be under /tmp" ;; esac
mkdir -p "$W"
W="$(cd "$W" && pwd -P)"
LIVE="$(cd "$LIVE_INSTANCE" && pwd -P)"
case "$W" in "$LIVE"*) die "workdir inside live instance" ;; esac
E="$W/evidence"; C="$W/instance"; F="$W/fixtures"; N="$W/neg"
mkdir -p "$E" "$F" "$N"
[ ! -e "$C" ] || die "$C exists"
HEALTH="$ISSUE58_DIR/bin/buzz-health"
PY3=/usr/bin/python3; [ -x "$PY3" ] || PY3=python3
unset ISSUE58_I_UNDERSTAND_LIVE ISSUE58_TEST_SKIP_SIGNATURE BUZZ58_TEST_OFFICIAL_BUZZ BUZZ58_TEST_PS_FIXTURE BUZZ58_TEST_DOCTOR_FIXTURE

live_snapshot() {  # $1 = output file
  {
    echo "# $(date '+%Y-%m-%d %H:%M:%S %Z')"
    echo "## ls -l ~/lab/buzz/bin"; ls -l "$LIVE/bin"
    echo "## sha256 live entries + README"
    for e in $ENTRIES buzz-health; do
      if [ -e "$LIVE/bin/$e" ]; then echo "$(sha256_of "$LIVE/bin/$e")  bin/$e"; else echo "<absent>  bin/$e"; fi
    done
    echo "$(sha256_of "$LIVE/README.md")  README.md"
    echo "## buzz-acp pids ($(acp_pids | wc -l | tr -d ' '))"; acp_pids | tr '\n' ' '; echo
    echo "## managed-agents.json sha256"; sha256_of "$INVENTORY"
  } > "$1"
}

echo "== 0. meta"
{ echo "date: $(date '+%Y-%m-%d %H:%M:%S %Z')"; echo "repo_sha: ${ISSUE58_REPO_SHA:-unknown}"; sw_vers | tr '\t' ' '
  echo "workdir: $W"; echo "git blob ids of the rehearsed files:"
  ( cd "$ISSUE58_DIR" && for f in common.sh apply.sh rollback.sh verify.sh rehearse.sh instance-readme-line.md bin/buzz bin/buzz-health; do
      echo "  $(git hash-object "$f")  $f"; done ); } > "$E/00-meta.txt"
live_snapshot "$E/01-live-before.txt"

echo "== 1. temp copy"
mkdir -p "$C/backups"
cp -Rp "$LIVE/bin" "$C/bin"
cp -p "$LIVE/README.md" "$C/README.md"
( cd "$C/bin" && for e in $ENTRIES; do echo "$(sha256_of "$e")  $e  expected_595=$(expected_595_sha "$e")"; done ) > "$E/02-copy-entries-before.txt"

echo "== 2. verify (old) + save state"
bash "$ISSUE58_DIR/verify.sh" --target "$C" --expect old --save-state "$E/state-before.txt" --health-out "$E/health-0-old.json" > "$E/03-verify-0-old.txt" 2>&1 || true

echo "== 3. apply"
[ "$C" != "$LIVE" ] || die "refusing: target is live"
bash "$ISSUE58_DIR/apply.sh" --target "$C" > "$E/04-apply.txt" 2>&1
cp "$C/README.md" "$E/04-readme-after-apply.md"

echo "== 4. verify (new) + compare state"
bash "$ISSUE58_DIR/verify.sh" --target "$C" --expect new --compare-state "$E/state-before.txt" --health-out "$E/health-1-new.json" > "$E/05-verify-1-new.txt" 2>&1 || true

echo "== 5. signature controls"
{
  echo "## official path facts"
  echo "~/.local/bin/buzz -> $(readlink "$HOME/.local/bin/buzz")"
  echo "CFBundleIdentifier=$(/usr/bin/defaults read /Applications/Buzz.app/Contents/Info CFBundleIdentifier)"
  echo "CFBundleShortVersionString=$(/usr/bin/defaults read /Applications/Buzz.app/Contents/Info CFBundleShortVersionString)"
  echo "CFBundleExecutable=$(/usr/bin/defaults read /Applications/Buzz.app/Contents/Info CFBundleExecutable)"
  echo "sha256=$(sha256_of "$OFFICIAL_BUZZ")"
  echo "updater: $(strings /Applications/Buzz.app/Contents/MacOS/buzz-desktop | grep -o 'tauri-plugin-updater/[0-9.]*' | head -1); endpoint $(strings /Applications/Buzz.app/Contents/MacOS/buzz-desktop | grep -o 'https://github.com/block/buzz/releases/download/[^ ]*latest.json' | head -1)"
  echo "sparkle framework: $( [ -d /Applications/Buzz.app/Contents/Frameworks/Sparkle.framework ] && echo present || echo absent)"
} > "$E/06-official-path.txt"
mkdir -p "$N/official-copy" "$N/adhoc" "$N/modified"
cp "$OFFICIAL_BUZZ" "$N/official-copy/buzz"
cp "$OFFICIAL_BUZZ" "$N/adhoc/buzz"; /usr/bin/codesign --force -s - "$N/adhoc/buzz" 2>/dev/null
cp "$OFFICIAL_BUZZ" "$N/modified/buzz"; printf '\0' >> "$N/modified/buzz"
{
  echo "requirement: $ISSUE58_REQUIREMENT"
  for case_ in live:"$OFFICIAL_BUZZ" official-copy:"$N/official-copy/buzz" adhoc:"$N/adhoc/buzz" modified:"$N/modified/buzz"; do
    name="${case_%%:*}"; bin="${case_#*:}"
    echo "### $name  $bin"
    echo "sha256=$(sha256_of "$bin")"
    /usr/bin/codesign --verify --strict -R "$ISSUE58_REQUIREMENT" "$bin" >/dev/null 2>&1 && echo "codesign --verify --strict -R <requirement> (decides): rc=0" || echo "codesign --verify --strict -R <requirement> (decides): rc=$?"
    /usr/bin/codesign --verify --strict "$bin" >/dev/null 2>&1 && echo "codesign --verify --strict without -R (record only): rc=0" || echo "codesign --verify --strict without -R (record only): rc=$?"
    echo "codesign -dv (self-asserted, record only):"
    /usr/bin/codesign -dv "$bin" 2>&1 | grep -E '^(Identifier|TeamIdentifier|Signature)=' | sed 's/^/  /' || true
    if [ "$name" = live ]; then
      out=$("$C/bin/buzz" --help 2>&1 >/dev/null) && rc=0 || rc=$?
    else
      out=$(BUZZ58_TEST_OFFICIAL_BUZZ="$bin" "$C/bin/buzz" --help 2>&1 >/dev/null) && rc=0 || rc=$?
    fi
    echo "bin/buzz --help: rc=$rc stderr=${out:-<empty>}"
    if [ "$name" = live ]; then hout="$E/health-sig-live.json"; "$PY3" "$HEALTH" > "$hout" && hrc=0 || hrc=$?
    else hout="$E/health-sig-$name.json"; BUZZ58_TEST_OFFICIAL_BUZZ="$bin" "$PY3" "$HEALTH" > "$hout" && hrc=0 || hrc=$?; fi
    python3 - "$hout" "$hrc" <<'PY'
import json, sys
r = json.load(open(sys.argv[1]))
s = r["official_buzz"]
print(f"buzz-health: exit={sys.argv[2]} ok={r['ok']} failures={r['failures']} test_hooks={r['test_hooks']}")
print(f"  official_buzz: verify={s['codesign_verify']} team={s['team_identifier']} id={s['identifier']} version={s['version']} updated={s['updated']} problems={s['problems']}")
PY
  done
} > "$E/07-signature-controls.txt" 2>&1

echo "== 6. buzz-health negatives (temp inventory copy + injected ps/env)"
cp -p "$INVENTORY" "$F/managed-agents.json"
python3 - "$E/health-1-new.json" "$F" <<'PY'
import copy, json, sys
from pathlib import Path
report, out = json.load(open(sys.argv[1])), Path(sys.argv[2])
procs = [{"pid": p["pid"], "env": {"BUZZ_RELAY_URL": p["relay"], "BUZZ_ACP_AGENT_COMMAND": p["agent_command"],
          "BUZZ_TEAM_POLICY_PATH": p["policy"]}} for p in report["processes"]["local"] + report["processes"]["other_relay"]]
(out / "ps-live.json").write_text(json.dumps(procs, indent=1))
def target():
    return next(i for i, p in enumerate(procs) if p["env"]["BUZZ_RELAY_URL"] == "ws://127.0.0.1:3000" and "lushen" in (p["env"]["BUZZ_TEAM_POLICY_PATH"] or ""))
cases = {"env-missing": ("BUZZ_TEAM_POLICY_PATH", None), "env-wrong": ("BUZZ_ACP_AGENT_COMMAND", "/Users/xupeng/lab/buzz/bin/agent-executor"),
         "non-local-relay": ("BUZZ_RELAY_URL", "ws://192.168.1.2:3000")}
for name, (key, value) in cases.items():
    data = copy.deepcopy(procs)
    if value is None:
        del data[target()]["env"][key]
    else:
        data[target()]["env"][key] = value
    (out / f"ps-{name}.json").write_text(json.dumps(data, indent=1))
doctor = copy.deepcopy(report["doctor"]["result"])
for check in doctor["checks"]:
    if check["name"] == "desktop_inventory":
        check["detail"] = "12 launch identities checked"
(out / "doctor-count-12.json").write_text(json.dumps(doctor, indent=1))
rows = json.load(open(out / "managed-agents.json"))
fizz = next(i for i, r in enumerate(rows) if r.get("pubkey") and "yuanbao" in (r.get("relay_url") or ""))
rows[fizz]["relay_url"] = ""
(out / "managed-agents-relay-blank.json").write_text(json.dumps(rows, ensure_ascii=False))
PY
summ() {
  python3 - "$1" "$2" "$3" <<'PY'
import json, sys
r = json.load(open(sys.argv[2]))
rec = r["identities"]["reconciliation"]
p = r["processes"]
print(f"### {sys.argv[1]}: exit={sys.argv[3]} ok={r['ok']} failures={r['failures']} test_hooks={r['test_hooks']}")
print(f"  reconciliation: doctor={rec['doctor_launch_identities']} local={rec['local']} other_relay={rec['other_relay']} unresolved={rec['unresolved']} ok={rec['ok']}")
print(f"  processes: valid_local={p['valid_local']} other_relay_recorded={p['other_relay_recorded']} without_valid={p['identities_without_valid_process']} invalid={[(x['pid'], x['reasons']) for x in p['local'] if not x['valid']]}")
PY
}
{
  run_neg() {  # name, then env assignments, then args
    local name="$1"; shift
    env "$@" > "$E/health-neg-$name.json" && rc=0 || rc=$?
    summ "$name" "$E/health-neg-$name.json" "$rc"
  }
  run_neg control-live-ps-fixture BUZZ58_TEST_PS_FIXTURE="$F/ps-live.json" "$PY3" "$HEALTH" --inventory "$F/managed-agents.json"
  for c in env-missing env-wrong non-local-relay; do
    run_neg "$c" BUZZ58_TEST_PS_FIXTURE="$F/ps-$c.json" "$PY3" "$HEALTH" --inventory "$F/managed-agents.json"
  done
  run_neg recon-doctor-12 BUZZ58_TEST_PS_FIXTURE="$F/ps-live.json" BUZZ58_TEST_DOCTOR_FIXTURE="$F/doctor-count-12.json" "$PY3" "$HEALTH" --inventory "$F/managed-agents.json"
  run_neg recon-inventory-relay-blank BUZZ58_TEST_PS_FIXTURE="$F/ps-live.json" "$PY3" "$HEALTH" --inventory "$F/managed-agents-relay-blank.json"
} > "$E/08-health-negatives.txt" 2>&1
mkdir -p "$E/fixtures" && cp "$F"/ps-*.json "$F/doctor-count-12.json" "$E/fixtures/"

echo "== 7. rollback"
bash "$ISSUE58_DIR/rollback.sh" --target "$C" > "$E/09-rollback.txt" 2>&1

echo "== 8. verify (old) + compare state"
bash "$ISSUE58_DIR/verify.sh" --target "$C" --expect old --compare-state "$E/state-before.txt" --health-out "$E/health-2-old.json" > "$E/10-verify-2-old.txt" 2>&1 || true
( cd "$C/bin" && for e in $ENTRIES; do echo "$(sha256_of "$e")  $e  expected_595=$(expected_595_sha "$e")  live=$(sha256_of "$LIVE/bin/$e")"; done ) > "$E/11-copy-entries-after-rollback.txt"
cmp -s "$C/README.md" "$LIVE/README.md" && echo "README.md after rollback: byte-identical to live" >> "$E/11-copy-entries-after-rollback.txt" || echo "README.md after rollback: DIFFERS" >> "$E/11-copy-entries-after-rollback.txt"

echo "== 9. agent-harness retirement evidence"
{
  python3 - "$E/health-1-new.json" <<'PY'
import collections, json, sys
r = json.load(open(sys.argv[1]))
procs = r["processes"]["local"] + r["processes"]["other_relay"]
print(f"buzz-acp processes: {len(procs)}")
for cmd, n in collections.Counter(p["agent_command"] for p in procs).items():
    print(f"  BUZZ_ACP_AGENT_COMMAND={cmd}: {n}")
print(f"  pointing at agent-harness: {sum('agent-harness' in (p['agent_command'] or '') for p in procs)}")
print(f"  pointing at lab/buzz/bin/*: {sum('lab/buzz/bin/' in (p['agent_command'] or '') for p in procs)}")
PY
  echo "grep -c agent-harness managed-agents.json: $(grep -o agent-harness "$INVENTORY" | wc -l | tr -d ' ')"
  for h in "$HOME/Library/Application Support/xyz.block.buzz.app/custom_harnesses"/*.json; do
    echo "grep -c agent-harness custom_harnesses/$(basename "$h"): $(grep -o agent-harness "$h" | wc -l | tr -d ' ')"
  done
  echo "lab/buzz/bin/* in managed-agents.json: $(grep -o 'lab/buzz/bin/[a-z-]*' "$INVENTORY" | sort | uniq -c | tr -s ' ' | tr '\n' ';')"
  echo "processes whose command line names lab/buzz/bin (excluding this probe): $(ps -axww -o pid=,ppid=,command= | awk -v me=$$ '$2!=me && $1!=me && /lab\/buzz\/bin/ && !/rehearse.sh|awk/' | wc -l | tr -d ' ')"
} > "$E/12-agent-harness-retirement.txt" 2>&1

echo "== 10. old doctor contrast (595c0cfe classify, read-only)"
( cd /tmp && "$RELEASE_595/bin/python" - "$LIVE/instance.local.json" "$INVENTORY" <<'PY'
import json, sys
from pathlib import Path
from buzz_team import desktop, health
data, rows = json.loads(Path(sys.argv[1]).read_text()), json.loads(Path(sys.argv[2]).read_text())
for c in health.classify_desktop_inventory(data.get("agents") or {}, rows):
    print("595c0cfe", c["id"], c["status"], "|", c["summary"])
r = rows[11]
print(f"row 11 {r.get('name')}: slug={r.get('slug')} pubkey_empty={not r.get('pubkey')} agent_command={r.get('agent_command')!r} "
      f"env BUZZ_RUNTIME_ID set={bool((r.get('env_vars') or {}).get('BUZZ_RUNTIME_ID'))} "
      f"(is an instance identity key: {(r.get('env_vars') or {}).get('BUZZ_RUNTIME_ID') in data['agents']}) "
      f"definition_only={health._inventory_definition_only(r)}")
anomaly = any(c["status"] == "fail" and c["id"].startswith("inventory_") for c in health.classify_desktop_inventory(data.get("agents") or {}, rows))
print(f"health._read_desktop_proxy_maps: anomaly={anomaly} -> desktop_inventory "
      f"{'fail: Desktop managed-agents inventory has instance anomalies' if anomaly else 'pass'}")
print(f"desktop.selected_rows: {len(desktop.selected_rows(data, rows))} identities (no raise)")
PY
) > "$E/13-old-doctor-contrast.txt" 2>&1

live_snapshot "$E/14-live-after.txt"
{
  echo "live bin + README + pids + inventory before vs after (ignoring timestamp line):"
  diff <(sed 1d "$E/01-live-before.txt") <(sed 1d "$E/14-live-after.txt") && echo "IDENTICAL"
  echo "pids saved before apply: $(sed -n 's/^pids: //p' "$E/state-before.txt")"
  echo "pids at end of rehearsal: $(acp_pids | tr '\n' ' ' | sed 's/ $//')"
} > "$E/15-live-diff.txt" 2>&1 || true

echo "== 11. redaction check"
{ echo "files scanned: $(find "$E" -type f | wc -l | tr -d ' ')"
  echo "matches for PRIVATE_KEY|nsec1|BUZZ_PRIVATE: $(find "$E" -type f -exec cat {} + | grep -Eo 'PRIVATE_KEY|nsec1|BUZZ_PRIVATE' | wc -l | tr -d ' ')"; } > "$E/16-redaction-check.txt"
echo "rehearsal done: $E"
