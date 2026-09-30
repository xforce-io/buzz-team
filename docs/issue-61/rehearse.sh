#!/bin/bash
# shellcheck disable=SC2015  # ok() always returns 0, so "A && ok || bad" is a safe if/else
# Issue #61 rehearsal on a synthetic instance (never the live file): builds an instance.local.json
# with the live structure (same 9 identity keys; placeholders for every unrelated value; 沈予 has
# the two keys), a fake HOME, and runs apply / verify / rollback plus negative cases.
# The status step uses the real buzz_team source at 595c0cfe (git archive from this repo, or
# ISSUE61_REHEARSE_SRC=<dir containing buzz_team/>). If lsof is missing (Linux) a no-op stub is used.
#
# Usage: rehearse.sh [EMPTY_DIR]      (default: mktemp -d)
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
R="${1:-$(mktemp -d)}"
mkdir -p "$R"; R=$(cd "$R" && pwd -P)
[ -z "$(ls -A "$R")" ] || { echo "rehearse: $R is not empty" >&2; exit 2; }
LOG="$R/rehearsal.log"; : > "$LOG"
PASSN=0; FAILN=0
ok()  { echo "PASS $*" | tee -a "$LOG"; PASSN=$((PASSN + 1)); }
bad() { echo "FAIL $*" | tee -a "$LOG"; FAILN=$((FAILN + 1)); }
expect_rc() { # expect_rc NAME WANT CMD...
  local name="$1" want="$2" got=0; shift 2
  echo "--- $name: $*" >> "$LOG"
  "$@" >> "$LOG" 2>&1 || got=$?
  if [ "$got" = "$want" ]; then ok "$name (exit $got)"; else bad "$name (exit $got, want $want)"; fi
}
same() { if [ "$2" = "$3" ]; then ok "$1"; else bad "$1 ($2 != $3)"; fi; }
sha() { if command -v shasum >/dev/null 2>&1; then shasum -a 256 "$1" | awk '{print $1}'; else sha256sum "$1" | awk '{print $1}'; fi; }

# ---- 595c0cf source + python wrapper
SRC="${ISSUE61_REHEARSE_SRC:-}"
if [ -z "$SRC" ]; then
  mkdir -p "$R/src595"
  git -C "$(git -C "$HERE" rev-parse --show-toplevel)" archive 595c0cfe43253b58087906a8bedc8d31388e3b5b src/buzz_team | tar -x -C "$R/src595"
  SRC="$R/src595/src"
fi
mkdir -p "$R/bin"
printf '#!/bin/sh\nPYTHONPATH="%s" exec python3 "$@"\n' "$SRC" > "$R/bin/python"; chmod +x "$R/bin/python"
if ! command -v lsof >/dev/null 2>&1; then
  printf '#!/bin/sh\nexit 0\n' > "$R/bin/lsof"; chmod +x "$R/bin/lsof"
  echo "NOTE lsof missing: using no-op stub (desktop_pids will be empty)" | tee -a "$LOG"
fi
export PATH="$R/bin:$PATH"

# ---- synthetic instance: $R/syn/lab/buzz/instance.local.json (+ managed-agents.json)
gen() { python3 - "$1" <<'PY'
import hashlib, json, os, sys
root = sys.argv[1]; relay = "ws://127.0.0.1:3000"
h = hashlib.sha256(relay.encode()).hexdigest()[:16]
pubs = ["a5cab3959de16db291ff97fe0b5802eeb897104127a973c8d9c8f118099bb0a0", "51fb6cd8eb6a72674998d5be5b1e8e826e2d60c870337cffc3278225e4297d9e",
        "db5955756e3825e2f208cb4b69a33ee4a2b20313474a213ea9efcbf931ce7861", "a2fe5d4920dd476e82a17e2cbcab6be525b211e5e3c9a1402a1792436af62587",
        "7b7afbdd7c0c3b887b973a6d8ddaccbfb925bedfcc35bdca5d63684aa5ae8c41", "27cd85fee67194bee4dd93fc837cc450589ccf6bb52b40b0aade4e1687b2d3c1",
        "265e4fc1258c1a9a596a5ad0562c73d04aeae090401382ea26ba4ddbe6d97529", "9c2f92188fe96b72e80798b9cf4576ed5ba71f4a5cbed7217562a4518b7ece1c",
        "5c37a76835e17b283cfea136088da26abecbe7b51c567eb57bcad967132917ac"]
withenv = {1, 2, 3, 5, 7}; agents = {}
for i, p in enumerate(pubs):
    a = {"label": "沈予" if i == 3 else f"seat-{i}", "pubkey": p, "relay_url": relay,
         "policy": "development" if i % 2 else "business", "instructions": f"{root}/private/instructions-{i}.md"}
    if i in withenv: a["skills_directory"] = f"{root}/skills/{i}"
    a["adapter"] = "grok"
    if i in withenv: a["binding_environment"] = {"BUZZ_ACP_CONFIG": f"{root}/run/placeholder-{i}.acp.toml"}
    if i == 3: a["binding_environment"].update({"BUZZ_ACP_SESSION_POLICY": "thread", "BUZZ_ACP_MAX_TURNS_PER_SESSION": "4"})
    a["mention_aliases"] = [f"alias{i}"]
    agents[f"{h}/{p}"] = a
d = {"state_root": f"{root}/state", "protected_home": root,
     "production": {"data_root": f"{root}/prod", "protected_paths": [f"{root}/prod/p{i}" for i in range(4)], "blocked_ports": [8787]},
     "policies": {"development": {"production_write": True, "data_mode": "test"}, "business": {"production_write": True, "data_mode": "test"}},
     "repositories": {"kairo": {"source": f"{root}/src/kairo", "origin": "https://example.invalid/kairo.git"}},
     "agents": agents, "version": 2, "binaries": {"buzz": f"{root}/bin/buzz", "harness": f"{root}/bin/agent-harness"},
     "adapters": {"grok": {"kind": "grok", "command": f"{root}/bin/grok"}},
     "desktop": {"managed_agents": f"{root}/desktop/managed-agents.json", "app": f"{root}/Buzz.app"},
     "data_environment": {"KAIRO_SERVE_ROOT": {"test": f"{root}/kairo-test", "production": f"{root}/kairo-prod"}},
     "compatibility": {"sha256": {"buzz": "0" * 64, "harness": "0" * 64}, "executor_sha256": {"grok": "0" * 64}},
     "channel_wake": {"default": {"require_mention": True, "allow_short_ack": True,
                                  "rotate": {"max_turns": 40, "max_usd": 5, "max_input_tokens": 2000000}}, "channels": {}}}
os.makedirs(f"{root}/lab/buzz", exist_ok=True); os.makedirs(f"{root}/desktop", exist_ok=True)
p = f"{root}/lab/buzz/instance.local.json"
open(p, "w").write(json.dumps(d, indent=2, ensure_ascii=False) + "\n"); os.chmod(p, 0o600)
rows = [{"name": a["label"], "pubkey": a["pubkey"], "relay_url": relay, "acp_command": "buzz-acp", "env_vars": {}} for a in agents.values()]
rows.append({"name": "shenyu-definition", "pubkey": "", "relay_url": "", "env_vars": {"BUZZ_ACP_MAX_TURNS_PER_SESSION": "4"}})
open(f"{root}/desktop/managed-agents.json", "w").write(json.dumps(rows, indent=2, ensure_ascii=False) + "\n")
PY
}
gen "$R/syn"
T="$R/syn/lab/buzz/instance.local.json"
cp -p "$T" "$R/original.json"
OLD=$(sha "$T"); MA_SHA=$(sha "$R/syn/desktop/managed-agents.json")
jq . "$T" | cmp -s - "$T" && ok "synthetic file is jq-canonical like the live file (jq . reproduces it byte-for-byte)" || bad "synthetic not jq-canonical"
echo "synthetic sha256 $OLD" | tee -a "$LOG"

# fake HOME: the "live" path inside it holds a copy whose sha differs from 5e372c4d…
export HOME="$R/home"; mkdir -p "$HOME/lab/buzz"; cp -p "$T" "$HOME/lab/buzz/instance.local.json"
LIVE_COPY_SHA=$(sha "$HOME/lab/buzz/instance.local.json")
unset ISSUE61_TARGET ISSUE61_EXPECT_OLD_SHA ISSUE61_BACKUP_ROOT ISSUE61_I_UNDERSTAND_LIVE ISSUE61_FORCE_ROLLBACK
E="$R/evidence"
run_env=(env ISSUE61_TARGET="$T" ISSUE61_EXPECT_OLD_SHA="$OLD" ISSUE61_PY="$R/bin/python")
gated=("${run_env[@]}" ISSUE61_I_UNDERSTAND_LIVE=yes)

echo "== negatives before apply" | tee -a "$LOG"
expect_rc "N1 apply without ISSUE61_I_UNDERSTAND_LIVE refused" 2 "${run_env[@]}" "$HERE/apply.sh"
expect_rc "N2 live path: sha != 5e372c4d… -> exit 3, untouched" 3 env ISSUE61_I_UNDERSTAND_LIVE=yes "$HERE/apply.sh"
same "N2 live-path copy unchanged" "$(sha "$HOME/lab/buzz/instance.local.json")" "$LIVE_COPY_SHA"
[ ! -e "$HOME/lab/buzz/backups" ] && ok "N2 no backup dir created" || bad "N2 backup dir created"
expect_rc "N3 live path: ISSUE61_EXPECT_OLD_SHA override refused" 2 env ISSUE61_I_UNDERSTAND_LIVE=yes ISSUE61_EXPECT_OLD_SHA="$LIVE_COPY_SHA" "$HERE/apply.sh"
expect_rc "N4 live path: /tmp backup root refused" 2 env ISSUE61_I_UNDERSTAND_LIVE=yes ISSUE61_BACKUP_ROOT=/tmp/issue61-bk "$HERE/apply.sh"
same "N3/N4 live-path copy unchanged" "$(sha "$HOME/lab/buzz/instance.local.json")" "$LIVE_COPY_SHA"
expect_rc "N5 rehearsal target with wrong expected sha -> exit 3" 3 env ISSUE61_TARGET="$T" ISSUE61_EXPECT_OLD_SHA="$(printf '0%.0s' {1..64})" ISSUE61_I_UNDERSTAND_LIVE=yes "$HERE/apply.sh"
ln -s "$T" "$R/syn/lab/buzz/link.json"
expect_rc "N6 symlink target refused" 3 env ISSUE61_TARGET="$R/syn/lab/buzz/link.json" ISSUE61_EXPECT_OLD_SHA="$OLD" ISSUE61_I_UNDERSTAND_LIVE=yes "$HERE/apply.sh"
rm "$R/syn/lab/buzz/link.json"
same "N5/N6 target unchanged" "$(sha "$T")" "$OLD"
[ ! -e "$R/syn/lab/buzz/backups" ] && ok "N5/N6 no backup dir created" || bad "N5/N6 backup dir created"

echo "== verify old" | tee -a "$LOG"
expect_rc "V1 verify --expect old" 0 "${run_env[@]}" "$HERE/verify.sh" --expect old --evidence "$E"
grep -q "unsupported binding environment override" "$E"/*-verify-old/status.out \
  && ok "V1 real 595c0cf status reproduces 'unsupported binding environment override'" || bad "V1 status did not reproduce the error"
expect_rc "V2 verify --expect new before apply fails" 1 "${run_env[@]}" "$HERE/verify.sh" --expect new --evidence "$E/neg"

echo "== apply" | tee -a "$LOG"
expect_rc "A1 apply" 0 "${gated[@]}" "$HERE/apply.sh"
B=$(find "$R/syn/lab/buzz/backups" -maxdepth 1 -type d -name '*-issue61' | head -n 1)
NEW=$(sha "$T")
same "A1 backup sha == original" "$(sha "$B/instance.local.json")" "$OLD"
same "A1 manifest new_sha256 == target sha" "$(sed -n 's/^new_sha256=//p' "$B/manifest.txt")" "$NEW"
same "A1 mode preserved (600)" "$(stat -c %a "$T" 2>/dev/null || stat -f %Lp "$T")" 600
same "A1 backup dir mode 700" "$(stat -c %a "$B" 2>/dev/null || stat -f %Lp "$B")" 700
same "A1 raw diff = exactly 2 lines removed + 1 comma change" \
  "$(grep -c '^-[^-]' "$B/raw.diff")/$(grep -c '^+[^+]' "$B/raw.diff")" "3/1"
grep -E '^[-+][^-+]' "$B/raw.diff" | tee -a "$LOG"
[ -z "$(find "$R/syn/lab/buzz" -maxdepth 1 -name '.instance.local.json.issue61.*')" ] && ok "A1 no temp file left" || bad "A1 temp file left"
same "A1 managed-agents.json untouched" "$(sha "$R/syn/desktop/managed-agents.json")" "$MA_SHA"
expect_rc "A2 second apply refused (sha now new)" 3 "${gated[@]}" "$HERE/apply.sh"
same "A2 target unchanged" "$(sha "$T")" "$NEW"

echo "== verify new" | tee -a "$LOG"
expect_rc "V3 verify --expect new" 0 "${run_env[@]}" "$HERE/verify.sh" --expect new --evidence "$E"
cat "$E"/*-verify-new/status.out | tee -a "$LOG"; echo >> "$LOG"
expect_rc "V4 verify --expect old after apply fails" 1 "${run_env[@]}" "$HERE/verify.sh" --expect old --evidence "$E/neg"

echo "== rollback negatives" | tee -a "$LOG"
expect_rc "R1 rollback without gate refused" 2 "${run_env[@]}" "$HERE/rollback.sh" --backup "$B"
mkdir -p "$R/fakebk"; jq '.version = 3' "$B/instance.local.json" > "$R/fakebk/instance.local.json"
expect_rc "R2 tampered backup refused" 4 "${gated[@]}" "$HERE/rollback.sh" --backup "$R/fakebk"
same "R2 target unchanged" "$(sha "$T")" "$NEW"
cp -p "$T" "$R/new.json"; printf ' ' >> "$T"
expect_rc "R3 target drifted since apply -> refused" 3 "${gated[@]}" "$HERE/rollback.sh" --backup "$B"
cp -p "$R/new.json" "$T"; same "R3 drift test restored" "$(sha "$T")" "$NEW"

echo "== rollback" | tee -a "$LOG"
expect_rc "R4 rollback (newest backup auto-selected)" 0 "${gated[@]}" "$HERE/rollback.sh"
same "R4 sha back to original" "$(sha "$T")" "$OLD"
cmp -s "$T" "$R/original.json" && ok "R4 byte-identical to original" || bad "R4 bytes differ"
same "R4 mode 600" "$(stat -c %a "$T" 2>/dev/null || stat -f %Lp "$T")" 600
ls "$B"/pre-rollback-*.json >/dev/null 2>&1 && ok "R4 pre-rollback copy kept in backup dir" || bad "R4 no pre-rollback copy"
expect_rc "V5 verify --expect old after rollback" 0 "${run_env[@]}" "$HERE/verify.sh" --expect old --evidence "$E"
expect_rc "R5 second rollback is a no-op" 0 "${gated[@]}" "$HERE/rollback.sh"
same "R5 target unchanged" "$(sha "$T")" "$OLD"

echo "== re-apply after rollback" | tee -a "$LOG"
sleep 1
expect_rc "A3 apply again" 0 "${gated[@]}" "$HERE/apply.sh"
same "A3 same new sha as first apply (deterministic)" "$(sha "$T")" "$NEW"
expect_rc "V6 verify --expect new (newest backup)" 0 "${run_env[@]}" "$HERE/verify.sh" --expect new --evidence "$E"
same "managed-agents.json untouched throughout" "$(sha "$R/syn/desktop/managed-agents.json")" "$MA_SHA"

echo "== summary: PASS $PASSN FAIL $FAILN (log $LOG)" | tee -a "$LOG"
[ "$FAILN" = 0 ]
