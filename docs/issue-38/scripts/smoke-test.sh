#!/usr/bin/env bash
# Static (+ optional live) smoke for Issue #38 scripts. Never mutates live.
# Default (CI/Linux): static only. SMOKE_LIVE=1 on Mac enables pin/pid checks.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"

echo "== bash -n =="
for f in common.sh apply.sh rollback.sh verify-after-restart.sh smoke-test.sh; do
  bash -n "$DIR/$f"
  echo "  OK $f"
done

if command -v shellcheck >/dev/null 2>&1; then
  echo "== shellcheck (warnings non-fatal) =="
  set +e
  shellcheck -x "$DIR/common.sh" "$DIR/apply.sh" "$DIR/rollback.sh" \
    "$DIR/verify-after-restart.sh" "$DIR/smoke-test.sh" \
    2>&1 | tee /tmp/issue38-shellcheck.log
  sc_rc=${PIPESTATUS[0]}
  set -e
  echo "shellcheck exit=$sc_rc (non-fatal; log=/tmp/issue38-shellcheck.log)"
else
  echo "shellcheck not installed — skipped"
fi

echo "== F5 order: config_written_at after first mutation + after local writes =="
python3 "$DIR/_check_f5_order.py" "$DIR/apply.sh"

echo "== no safe_kill / kill-wait in call paths =="
if grep -nE '^[[:space:]]*safe_kill_zhou|^[[:space:]]*kill[[:space:]]+-?[0-9]|TIMEOUT waiting for Desktop to respawn' \
    "$DIR/apply.sh" "$DIR/rollback.sh" "$DIR/common.sh" "$DIR/verify-after-restart.sh"; then
  echo "FAIL: kill/respawn call path still present" >&2
  exit 1
fi
if grep -nE '^safe_kill_zhou\(\)' "$DIR/common.sh"; then
  echo "FAIL: safe_kill_zhou still defined" >&2
  exit 1
fi
echo "no kill/respawn call paths OK"

echo "== quit-first: baseline-only + desktop-not-running; escape hatch ABSENT =="
grep -q -- '--baseline-only' "$DIR/apply.sh"
grep -q 'require_desktop_not_running' "$DIR/apply.sh"
grep -q 'require_desktop_not_running' "$DIR/rollback.sh"
# Assert escape hatch gone from product scripts + RUNBOOK (not this smoke file's assertion text).
if grep -n 'SKIP_DESKTOP_CHECK' "$DIR/common.sh" "$DIR/apply.sh" "$DIR/rollback.sh" \
    "$DIR/verify-after-restart.sh" "$DIR/../RUNBOOK.md"; then
  echo "FAIL: SKIP_DESKTOP_CHECK escape hatch must be fully removed" >&2
  exit 1
fi
echo "SKIP_DESKTOP_CHECK absent OK"
grep -q 'snapshot_all_team_pids' "$DIR/apply.sh"
grep -q 'all-pids-before.tsv' "$DIR/apply.sh"
grep -q 'all-pids-before.tsv' "$DIR/verify-after-restart.sh"
# D1: identity scan (pubkey from pid-file names + BUZZ_RELAY_URL); no pid-file kill -0 / pgrep -P
grep -q 'scan_team_seat_identity_matches' "$DIR/common.sh"
grep -q 'team_seat_pubkeys_from_pid_files' "$DIR/common.sh"
grep -q 'require_team_seats_not_running' "$DIR/common.sh"
grep -q '_seat_identity_scan.py' "$DIR/common.sh"
test -f "$DIR/_seat_identity_scan.py"
# Seat-dead check must NOT use pgrep -P or kill -0 on pid-file pids
DIR="$DIR" python3 - <<'PY'
import os, re
from pathlib import Path
text = Path(os.environ["DIR"], "common.sh").read_text()
start = text.find("# ---- TEAM seat identity scan")
end = text.find("# Record baseline capture time")
assert start >= 0 and end > start, "D1 identity-scan region missing"
region = text[start:end]
code = "\n".join(l for l in region.splitlines() if not l.lstrip().startswith("#"))
if re.search(r"\bpgrep\s+-P\b", code):
    raise SystemExit("FAIL: D1 still uses pgrep -P")
if re.search(r"\bkill\s+-0\b", code):
    raise SystemExit("FAIL: D1 still uses kill -0 on pid-file pids")
assert "team_seat_pubkeys_from_pid_files" in region
assert "__" in region and "TEAM" in region
print("D1 identity scan present; no pgrep -P / kill -0 in seat-dead check OK")
PY
if grep -nE 'pgrep[[:space:]].*buzz-acp' "$DIR/common.sh" "$DIR/apply.sh" "$DIR/rollback.sh"; then
  echo "FAIL: machine-wide buzz-acp pgrep must not be used (yuanbao false-abort)" >&2
  exit 1
fi
echo "D1 no machine-wide buzz-acp OK"

# A14: :3000 preflight in apply mutate + rollback
grep -q 'require_relay_3000_listening' "$DIR/common.sh"
grep -q 'require_relay_3000_listening' "$DIR/apply.sh"
grep -q 'require_relay_3000_listening' "$DIR/rollback.sh"
grep -q 'relay :3000 not listening' "$DIR/common.sh"
# mutate-phase ordering: relay preflight before workflow re-assert / write
DIR="$DIR" python3 - <<'PY'
import os, re
from pathlib import Path
t = Path(os.environ["DIR"], "apply.sh").read_text()
m = re.search(r"mutate phase: require Desktop NOT running", t)
assert m, "mutate phase marker missing"
tail = t[m.start():]
rel = tail.find("require_relay_3000_listening")
ra = tail.find("assert_live_workflow_matches_before")
upd = tail.find("buzz workflows update")
if rel < 0:
    raise SystemExit("FAIL: require_relay_3000_listening missing from mutate phase")
if not (rel < ra < upd):
    raise SystemExit(f"FAIL: mutate order relay < re-assert < update (rel={rel} ra={ra} upd={upd})")
print("A14 :3000 preflight in apply mutate (before re-assert) + rollback OK")
PY

# D1 fixture: yuanbao same-pubkey different relay → not matched; grep line → not matched; real seat → matched
echo "== D1 identity-scan fixture (yuanbao/grep self-exclusion) =="
FIX=$(mktemp)
PUB=51fb6cd8eb6a72674998d5be5b1e8e826e2d60c870337cffc3278225e4297d9e
cat > "$FIX" <<FIXEOF
99901 /opt/homebrew/Cellar/python@3.14/3.14.0_1/Frameworks/Python.framework/Versions/3.14/Resources/Python.app/Contents/MacOS/Python -m buzz_team.cli --instance /Users/xupeng/lab/buzz launch harness -- BUZZ_RELAY_URL=ws://127.0.0.1:3000 BUZZ_RUNTIME_ID=a558771623f29898/${PUB} GROK_ACP_CWD=/Users/xupeng/.local/share/buzz/agent-runtime/identities/a558771623f29898/${PUB}/workspace
99902 /Users/xupeng/.local/share/buzz/binaries/4937-activity-recovery/buzz-acp BUZZ_RELAY_URL=ws://127.0.0.1:3000 BUZZ_RUNTIME_ID=a558771623f29898/${PUB}
99903 /opt/homebrew/Cellar/python@3.14/3.14.0_1/Frameworks/Python.framework/Versions/3.14/Resources/Python.app/Contents/MacOS/Python -m buzz_team.cli --instance /tmp/yuanbao launch harness -- BUZZ_RELAY_URL=ws://127.0.0.1:3001 BUZZ_RUNTIME_ID=a558771623f29898/${PUB} GROK_ACP_CWD=/tmp/yuanbao/identities/a558771623f29898/${PUB}/workspace
99904 grep ${PUB} /tmp/something
99905 bash -c "echo ${PUB} and BUZZ_RELAY_URL=ws://127.0.0.1:3000"
# Self pipeline: scanner pid 88880 with a child whose cmdline contains the pubkey (must be excluded)
88880 bash /tmp/fake-scan-script.sh
88881 grep ${PUB} /proc/fake
PPIDMAP 99901 100
PPIDMAP 99902 99901
PPIDMAP 99903 100
PPIDMAP 99904 100
PPIDMAP 99905 100
PPIDMAP 88880 100
PPIDMAP 88881 88880
FIXEOF
SCAN_OUT=$(python3 "$DIR/_seat_identity_scan.py" --relay "ws://127.0.0.1:3000" --pubkey "$PUB" --self-pid 88880 < "$FIX" || true)
rm -f "$FIX"
echo "$SCAN_OUT"
# Expect only 99901 and 99902 (real team seats). 99903 yuanbao different relay; 99904 grep; 99905 bash — excluded.
echo "$SCAN_OUT" | grep -q '^99901[[:space:]]'
echo "$SCAN_OUT" | grep -q '^99902[[:space:]]'
if echo "$SCAN_OUT" | grep -qE '^99903|^99904|^99905|^88880|^88881'; then
  echo "FAIL: fixture matched yuanbao/grep/bash/self line" >&2
  echo "$SCAN_OUT" >&2
  exit 1
fi
# Count matches == 2
n=$(echo "$SCAN_OUT" | awk 'NF' | wc -l | tr -d ' ')
if [[ "$n" != "2" ]]; then
  echo "FAIL: expected 2 fixture matches, got $n" >&2
  exit 1
fi
echo "D1 fixture: team seats matched; yuanbao/grep/bash excluded OK"
# D3: baseline_at + age check + mutate re-assert
grep -q 'BASELINE_MAX_AGE_S=1800' "$DIR/common.sh"
grep -q 'record_baseline_at' "$DIR/common.sh"
grep -q 'record_baseline_at' "$DIR/apply.sh"
grep -q 'require_baseline_fresh' "$DIR/common.sh"
grep -q 'require_baseline_fresh' "$DIR/apply.sh"
grep -q 'assert_live_workflow_matches_before' "$DIR/common.sh"
grep -q 'assert_live_workflow_matches_before' "$DIR/apply.sh"
grep -q 'baseline_at' "$DIR/../RUNBOOK.md"
echo "D3 baseline_at + freshness + mutate re-assert OK"
# mutate phase must not require seats alive; freshness+re-assert before write
DIR="$DIR" python3 - <<'PY'
import os, re
from pathlib import Path
t = Path(os.environ["DIR"], "apply.sh").read_text()
m = re.search(r"mutate phase: require Desktop NOT running", t)
assert m, "mutate phase marker missing"
tail = t[m.start():]
if re.search(r"^\s*require_all_team_alive\b", tail, re.M):
    raise SystemExit("FAIL: require_all_team_alive in mutate phase")
if re.search(r"^\s*ZHOU_PID_BEFORE=\$\(require_zhou_alive\)", tail, re.M):
    raise SystemExit("FAIL: require_zhou_alive capture in mutate phase")
if "require_baseline_fresh" not in tail:
    raise SystemExit("FAIL: require_baseline_fresh missing from mutate phase")
if "assert_live_workflow_matches_before" not in tail:
    raise SystemExit("FAIL: assert_live_workflow_matches_before missing from mutate phase")
upd = tail.find("buzz workflows update")
ra = tail.find("assert_live_workflow_matches_before")
if upd < 0 or ra < 0 or not (ra < upd):
    raise SystemExit(f"FAIL: mutate re-assert must precede workflows update (ra={ra} upd={upd})")
print("mutate phase does not require seats alive; freshness+re-assert before write OK")
PY

echo "== N1: Mode A only if ALL THREE effort+idle+max visible =="
grep -q 'got_effort is not None and got_idle is not None and got_max is not None' \
  "$DIR/verify-after-restart.sh"
# Ensure we no longer gate Mode A on effort+idle alone
if grep -nE 'got_effort is not None and got_idle is not None:' \
    "$DIR/verify-after-restart.sh" | grep -v got_max; then
  echo "FAIL: Mode A still gates on effort+idle only" >&2
  exit 1
fi
echo "N1 three-of-three OK"

echo "== lstart parsing (no etimes call) =="
grep -q "lstart=" "$DIR/verify-after-restart.sh"
grep -q 'empty lstart' "$DIR/verify-after-restart.sh"
grep -q "date', '-j', '-f'" "$DIR/verify-after-restart.sh"
if grep -nE "\['ps', '-o', 'etimes='\]" "$DIR/verify-after-restart.sh" "$DIR/common.sh"; then
  echo "FAIL: etimes still invoked" >&2
  exit 1
fi
echo "lstart-only OK"

echo "== lstart parsing under LANG=zh_CN.UTF-8 =="
epoch=$(env -u LC_ALL LANG=zh_CN.UTF-8 python3 - <<'PY'
import os
import platform
import subprocess

lstart = 'Thu Sep 24 14:54:38 2026'
env = {**os.environ, 'LC_ALL': 'C', 'LANG': 'C'}
if platform.system() == 'Darwin':
    cmd = ['date', '-j', '-f', '%a %b %d %T %Y', lstart, '+%s']
else:
    cmd = ['date', '-d', lstart, '+%s']
print(subprocess.check_output(cmd, text=True, env=env).strip())
PY
)
if [[ ! "$epoch" =~ ^-?[0-9]+$ ]]; then
  echo "FAIL: zh_CN lstart parser did not return a numeric epoch: $epoch" >&2
  exit 1
fi
echo "zh_CN lstart parser OK (epoch=$epoch)"

echo "== D4: verify error must not prescribe Dock/Launchpad reopen =="
if grep -nE 'Reopen Desktop from Dock/Launchpad|from Dock/Launchpad, wait'     "$DIR/verify-after-restart.sh"; then
  echo "FAIL: verify still prescribes Dock/Launchpad reopen" >&2
  exit 1
fi
grep -q 'peng-approved proxy-fix method (RUNBOOK A13)' "$DIR/verify-after-restart.sh"
echo "D4 proxy-fix reopen wording OK"

echo "== D5: quit-first implies app (single is experiment-only) =="
grep -q 'quit-first (Cmd+Q) always implies --restart-mode app' "$DIR/common.sh"
grep -q 'only for experiments without Cmd+Q' "$DIR/../RUNBOOK.md"
echo "D5 single-vs-app messaging OK"

echo "== --restart-mode single|app required (no auto-guess) =="
grep -q -- '--restart-mode' "$DIR/verify-after-restart.sh"
grep -q 'no auto-guess' "$DIR/verify-after-restart.sh"
grep -q 'verify_restart_pids' "$DIR/common.sh"
grep -q 'verify_restart_pids' "$DIR/verify-after-restart.sh"
grep -q 'restart_mode=single OK' "$DIR/common.sh"
grep -q 'restart_mode=app OK' "$DIR/common.sh"
echo "restart-mode branches OK"

echo "== config_written_at only (never MA mtime) =="
grep -q 'Never use managed-agents.json mtime' "$DIR/common.sh"
grep -q 'never MA mtime\|not MA mtime\|NOT config-write' "$DIR/verify-after-restart.sh"
echo "config_written_at authority OK"

echo "== refuse without live guard / required flags =="
set +e
bash "$DIR/apply.sh" >/tmp/i38-apply-unguarded.out 2>&1
rc=$?
set -e
if [[ "$rc" -eq 0 ]]; then
  echo "FAIL: apply.sh with no args should fail" >&2
  exit 1
fi
echo "apply no-args refused OK (exit=$rc)"
set +e
bash "$DIR/verify-after-restart.sh" /tmp/not-a-backup >/tmp/i38-verify-noflags.out 2>&1
rc=$?
set -e
if [[ "$rc" -eq 0 ]]; then
  echo "FAIL: verify without flags should fail" >&2
  exit 1
fi
echo "verify missing flags refused OK (exit=$rc)"

if [[ "${SMOKE_LIVE:-}" == "1" ]]; then
  echo "== SMOKE_LIVE=1: pin + zhou pid + desktop helper =="
  # shellcheck source=common.sh
  source "$DIR/common.sh"
  verify_thin_pin
  f=$(zhou_pid_file)
  echo "zhou_pid_file -> $f"
  desktop_main_pids || true
else
  echo "== SMOKE_LIVE!=1 — skip live Mac pin/pid checks (CI/Linux safe) =="
fi

echo "smoke-test OK"
