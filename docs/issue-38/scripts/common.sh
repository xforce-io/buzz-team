# shellcheck shell=bash
# Shared constants/helpers for Issue #38 apply/rollback (周衡 only).

PUB=51fb6cd8eb6a72674998d5be5b1e8e826e2d60c870337cffc3278225e4297d9e
# Desktop agent-pids team key (Hogan live-verified 2026-09-24)
TEAM=a558771623f298980db444a8406459dff1cbd20f264a72d00ffaca270c0fa16f
# Identity workspace dir uses the short team id prefix
ID_TEAM=a558771623f29898
PIN_SHORT=046ac43
PIN_FULL=046ac4345647ea6bc9c57bbf91ddb556a91694cd
# Max age of a --baseline-only backup before mutate will refuse it (seconds).
BASELINE_MAX_AGE_S=1800

WF_ID=f5cc62c0-3756-419e-8a3f-8e694df2e93e
CH_ID=9bdc9fa2-48b7-4352-8b1f-7baf70ba6bd3
INSTANCE=/Users/xupeng/lab/buzz
MA="${HOME}/Library/Application Support/xyz.block.buzz.app/agents/managed-agents.json"
PID_DIR="${HOME}/Library/Application Support/xyz.block.buzz.app/agents/agent-pids"
ID_ROOT="${HOME}/.local/share/buzz/agent-runtime/identities/${ID_TEAM}/${PUB}/workspace"
PJ_MD=/Users/xupeng/lab/buzz-team/team/prompts/pj.md
INSTR="${INSTANCE}/private/instructions-1.md"
EXEC_WRAP=/Users/xupeng/lab/buzz/bin/agent-executor
HARNESS_WRAP=/Users/xupeng/lab/buzz/bin/agent-harness

require_live_guard() {
  if [[ "${ISSUE38_I_UNDERSTAND_LIVE:-}" != "yes" ]]; then
    echo "Refusing: set ISSUE38_I_UNDERSTAND_LIVE=yes. See docs/issue-38/RUNBOOK.md" >&2
    exit 2
  fi
}

# Smoke fixtures must never influence a live run, even if a caller sets both
# the live acknowledgement and the fixture override.
reject_live_test_hooks() {
  if [[ "${ISSUE38_I_UNDERSTAND_LIVE:-}" == "yes" && -n "${ISSUE38_PS_FIXTURE:-}" ]]; then
    echo "ABORT: ISSUE38_PS_FIXTURE is smoke-only; refusing on live run" >&2
    return 2
  fi
}

# Fail unless thin wrappers resolve to pin 046ac43 (full SHA).
verify_thin_pin() {
  local f
  for f in "$EXEC_WRAP" "$HARNESS_WRAP"; do
    if [[ ! -f "$f" ]]; then
      echo "pin check FAIL: missing $f" >&2
      exit 1
    fi
    if ! grep -q "$PIN_FULL" "$f"; then
      echo "pin check FAIL: $f does not reference $PIN_FULL ($PIN_SHORT)" >&2
      echo "--- $f ---" >&2
      cat "$f" >&2
      exit 1
    fi
  done
  echo "pin check OK: wrappers reference $PIN_FULL"
}

# Resolve 周衡 pid file: exactly ${PUB}__${TEAM}.json; abort if any other ${PUB}__*.json.
# Does NOT require the pid to be alive (rollback must tolerate a stale/dead pid).
zhou_pid_file() {
  local exact extras f
  exact="${PID_DIR}/${PUB}__${TEAM}.json"
  if [[ ! -f "$exact" ]]; then
    echo "周衡 pid file missing: $exact" >&2
    exit 1
  fi
  extras=()
  for f in "$PID_DIR"/${PUB}__*.json; do
    [[ -e "$f" ]] || continue
    if [[ "$(basename "$f")" != "$(basename "$exact")" ]]; then
      extras+=("$f")
    fi
  done
  if ((${#extras[@]} > 0)); then
    echo "ABORT: unexpected extra ${PUB}__*.json pid file(s) (stale yuanbao/other?):" >&2
    printf '  %s\n' "${extras[@]}" >&2
    echo "Remove extras or restart only 周衡 from Desktop; refusing to proceed." >&2
    exit 1
  fi
  printf '%s\n' "$exact"
}

# Apply precondition: 周衡 ACP must be alive (doctor 9/9). Abort if pid file points at a dead process.
# Live fact: Desktop does NOT auto-respawn after kill — operator must restart 周衡 from Desktop first.
require_zhou_alive() {
  local zh_file old_pid blob
  zh_file=$(zhou_pid_file)
  old_pid=$(python3 -c "import json; print(json.load(open(r'''${zh_file}'''))['pid'])")
  if ! kill -0 "$old_pid" 2>/dev/null; then
    echo "ABORT: 周衡 pid $old_pid from $zh_file is NOT alive." >&2
    echo "Precondition: doctor 9/9 (all seats up). Ask peng to restart ONLY 周衡 from Buzz Desktop, then re-run apply." >&2
    return 1
  fi
  blob=$(ps eww -p "$old_pid" 2>/dev/null || true)
  if [[ -z "$blob" || "$blob" != *"$PUB"* ]]; then
    echo "ABORT: pid $old_pid is alive but env/cmdline does not contain 周衡 pubkey $PUB." >&2
    echo "Ask peng to restart ONLY 周衡 from Desktop, then re-run apply." >&2
    return 1
  fi
  echo "周衡 ACP alive OK: pid=$old_pid (pubkey confirmed)" >&2
  printf '%s\n' "$old_pid"
}

# Enforce doctor 9/9: every *__${TEAM}.json pid must be alive (kill -0). Abort otherwise.
require_all_team_alive() {
  local f base pid n=0
  local -a dead=()
  for f in "$PID_DIR"/*__"${TEAM}".json; do
    [[ -e "$f" ]] || continue
    base=$(basename "$f")
    pid=$(python3 -c "import json; print(json.load(open(r'''${f}'''))['pid'])")
    n=$((n+1))
    if ! kill -0 "$pid" 2>/dev/null; then
      dead+=("$base:$pid")
    fi
  done
  if [[ "$n" -ne 9 ]]; then
    echo "ABORT: expected 9 *__${TEAM}.json seats, found $n. doctor 9/9 required before apply." >&2
    return 1
  fi
  if ((${#dead[@]} > 0)); then
    echo "ABORT: doctor 9/9 failed — dead seat pid(s):" >&2
    printf '  %s\n' "${dead[@]}" >&2
    echo "Ask peng to restart dead seats from Desktop (prefer ONLY those seats), then re-run apply." >&2
    return 1
  fi
  echo "doctor 9/9 OK: all $n TEAM seat pids alive" >&2
}

# Other seats on this TEAM, excluding 周衡's exact file. Prints "name\tpid" lines.
list_other_team_pids() {
  local f base
  for f in "$PID_DIR"/*__"${TEAM}".json; do
    [[ -e "$f" ]] || continue
    base=$(basename "$f")
    if [[ "$base" == "${PUB}__${TEAM}.json" ]]; then
      continue
    fi
    python3 -c "import json,sys; print(sys.argv[1]+'\t'+str(json.load(open(sys.argv[2]))['pid']))" "$base" "$f"
  done
}

snapshot_other_pids() {
  local out=$1
  list_other_team_pids > "$out"
  local n
  n=$(wc -l < "$out" | tr -d ' ')
  echo "other TEAM seats recorded: $n"
  if [[ "$n" -ne 8 ]]; then
    echo "WARN: expected 8 other seats on TEAM, got $n" >&2
  fi
}

verify_other_pids_unchanged() {
  local before=$1
  local after
  after=$(mktemp)
  list_other_team_pids > "$after"
  if ! diff -u "$before" "$after"; then
    echo "ABORT: other seat pids changed" >&2
    rm -f "$after"
    exit 1
  fi
  rm -f "$after"
  echo "other 8 seats pids unchanged OK"
}

# Patch only the 周衡 row (by full pubkey) inside managed-agents.json.
restore_zhou_row_from_file() {
  local row_file=$1
  python3 -c "
import json, sys
from pathlib import Path
ma_path=Path(r'''$MA''')
row_path=Path(sys.argv[1])
agents=json.loads(ma_path.read_text())
saved=json.loads(row_path.read_text())
pub=r'''$PUB'''
idx=None
for i,a in enumerate(agents):
    if a.get('pubkey')==pub or (a.get('name')=='周衡' and (a.get('pubkey') or '').startswith('51fb6cd8')):
        idx=i; break
if idx is None:
    raise SystemExit('周衡 row not found in live managed-agents.json — abort')
agents[idx]=saved
ma_path.write_text(json.dumps(agents, ensure_ascii=False, indent=2)+chr(10))
print('restored 周衡 row only from', row_path)
" "$row_file"
}

# Record when config was written so verify-after-restart can use start-time fallback.
# The file stores UTC ISO-8601 text; verify converts it to epoch before comparing.
# ONLY this stamp is authoritative for Mode B start-time checks.
# Never use managed-agents.json mtime: Desktop rewrites that file on start
# (last_started_at / updated_at), so its mtime is NOT config-write time (A6/A11).
record_config_written_at() {
  local backup=$1
  local stamp
  stamp=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  printf '%s\n' "$stamp" > "$backup/config_written_at.txt"
  echo "config_written_at=$stamp (UTC) -> $backup/config_written_at.txt"
}

# ---- Desktop process helpers (macOS Buzz.app) ----
# Matcher: prefer Buzz.app MacOS binary path; fall back to exact process name "Buzz".
# No prior matcher existed in these scripts; keep narrow to avoid ACP python wrappers.
# No Desktop-check escape hatch — mutate/rollback always require a full quit.

desktop_main_pids() {
  local pids=""
  pids=$(pgrep -f '/Buzz\.app/Contents/MacOS/' 2>/dev/null || true)
  if [[ -z "$pids" ]]; then
    pids=$(pgrep -x 'Buzz' 2>/dev/null || true)
  fi
  printf '%s\n' "$pids" | awk 'NF' | sort -u
}

# ---- TEAM seat identity scan (D1 / A15) ----
# Why identity (exact BUZZ_RUNTIME_ID=<ID_TEAM>/<pubkey>) instead of kill -0 on
# pid-file pids / pgrep -P / pubkey+relay:
#   - After Cmd+Q, orphaned ACP children reparent to pid 1 (launchd); pgrep -P
#     on the old wrapper pid misses them.
#   - Stale pid-file numbers can be reused by unrelated processes → false positives.
#   - Scope is this TEAM only via exact env token BUZZ_RUNTIME_ID=${ID_TEAM}/<pubkey>
#     (pubkey list from *__${TEAM}.json names). Drop BUZZ_RELAY_URL as the primary
#     distinguisher — yuanbao / other instances may share pubkeys+relay but use a
#     different team id prefix (see A15). Do NOT scan machine-wide for `buzz-acp`
#     by name alone.
# Match rule (all required): seat executable (buzz_team.cli wrapper OR buzz-acp
# argv0) AND exact BUZZ_RUNTIME_ID=${ID_TEAM}/<pubkey> AND not self/descendants.
# Fail-closed: scanner crash / non-zero, ps non-zero, or empty ps ⇒ ABORT (never
# treat as "no seats alive"). Scanner exit 0 = ok (prints matches + SCAN_OK);
# exit 2 = error. Positive control (baseline, Desktop UP) must PASS before a
# 0-match result is trusted in mutate/rollback.

# Emit ps pid/command lines for identity scan.
# macOS: ps -axww (cmdline) AND ps -Eaxww (env visible for our own processes).
# Linux/CI: ps -eww e; live Desktop checks are macOS-only.
# ISSUE38_PS_FIXTURE=path → read fixture instead (smoke tests; no live ps).
# Fail-closed: any real ps non-zero exit or empty combined output ⇒ return 1.
_collect_ps_pid_command_lines() {
  local out1 out2 rc1=0 rc2=0
  reject_live_test_hooks || return $?
  if [[ -n "${ISSUE38_PS_FIXTURE:-}" ]]; then
    if [[ ! -f "$ISSUE38_PS_FIXTURE" ]]; then
      echo "ABORT: ISSUE38_PS_FIXTURE not a file: $ISSUE38_PS_FIXTURE" >&2
      return 1
    fi
    cat "$ISSUE38_PS_FIXTURE"
    return 0
  fi
  case "$(uname -s)" in
    Darwin)
      out1=$(ps -axww -o pid=,command= 2>/dev/null) || rc1=$?
      out2=$(ps -Eaxww -o pid=,command= 2>/dev/null) || rc2=$?
      if [[ "$rc1" -ne 0 ]]; then
        echo "ABORT: ps -axww failed (exit=$rc1) — refuse to treat as no seats alive" >&2
        return 1
      fi
      if [[ "$rc2" -ne 0 ]]; then
        echo "ABORT: ps -Eaxww failed (exit=$rc2) — refuse to treat as no seats alive" >&2
        return 1
      fi
      printf '%s\n%s\n' "$out1" "$out2"
      ;;
    *)
      out1=$(ps -eww -o pid=,args= 2>/dev/null) || rc1=$?
      out2=$(ps -eww e -o pid=,args= 2>/dev/null) || rc2=$?
      if [[ "$rc1" -ne 0 ]]; then
        echo "ABORT: ps -eww failed (exit=$rc1) — refuse to treat as no seats alive" >&2
        return 1
      fi
      if [[ "$rc2" -ne 0 ]]; then
        echo "ABORT: ps -eww e failed (exit=$rc2) — refuse to treat as no seats alive" >&2
        return 1
      fi
      printf '%s\n%s\n' "$out1" "$out2"
      ;;
  esac
}


# Emit PPIDMAP lines so the scanner can exclude $$ descendants (ps/python pipeline).
# Fail-closed on live ps failure (fixture mode skips).
_collect_ppid_map_lines() {
  local rc=0 out
  reject_live_test_hooks || return $?
  if [[ -n "${ISSUE38_PS_FIXTURE:-}" ]]; then
    return 0
  fi
  out=$(ps -axww -o pid=,ppid= 2>/dev/null) || rc=$?
  if [[ "$rc" -ne 0 ]]; then
    echo "ABORT: ps pid/ppid map failed (exit=$rc)" >&2
    return 1
  fi
  while read -r pid ppid; do
    [[ -n "${pid:-}" && -n "${ppid:-}" ]] || continue
    printf 'PPIDMAP %s %s\n' "$pid" "$ppid"
  done <<< "$out"
}


# Extract seat pubkeys from the 9 TEAM pid file names ($PID_DIR/<pubkey>__<TEAM>.json).
team_seat_pubkeys_from_pid_files() {
  local f base
  shopt -s nullglob
  for f in "$PID_DIR"/*__"${TEAM}".json; do
    base=$(basename "$f")
    printf '%s\n' "${base%%__*}"
  done
  shopt -u nullglob
}

# Run identity scan. Prints match lines "pid<TAB>pubkey<TAB>via" to stdout
# (SCAN_OK / COUNT lines go to the captured stream but are filtered for callers
# that only want matches — full output including SCAN_OK is also validated).
# $1 = path to pubkeys file (one per line).
# Optional $2 = "counts" to also emit COUNT lines (positive control).
# Excludes $$ and descendants. Fail-closed on scanner/ps failure or missing SCAN_OK.
scan_team_seat_identity_matches() {
  local pubs_file=$1
  local mode=${2:-}
  local self_pid=$$
  local scanner ps_blob scan_out rc=0 scan_ok_line ps_lines matches_n
  local -a scan_args=()
  scanner="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_seat_identity_scan.py"
  if [[ ! -f "$scanner" ]]; then
    echo "ABORT: missing scanner $scanner" >&2
    return 1
  fi
  if [[ ! -s "$pubs_file" ]]; then
    echo "ABORT: empty pubkeys file for identity scan: $pubs_file" >&2
    return 1
  fi
  # Capture without toggling caller's set -e (assignment/if are set -e safe).
  rc=0
  ps_blob=$(
    {
      _collect_ps_pid_command_lines || exit 1
      _collect_ppid_map_lines || exit 1
    }
  ) || rc=$?
  if [[ "$rc" -ne 0 ]]; then
    echo "ABORT: failed to collect ps/ppid for identity scan (exit=$rc)" >&2
    return 1
  fi
  # Empty ps is never OK live (must at least include the scanning process itself).
  # Fixture mode may be empty only if the fixture file itself is empty — still abort.
  if [[ -z "$(printf '%s\n' "$ps_blob" | awk 'NF && $0 !~ /^PPIDMAP / {print; exit}')" ]]; then
    echo "ABORT: empty ps output for identity scan (fail-closed; refuse 'no seats alive')" >&2
    return 1
  fi
  scan_args=(--team-id "$ID_TEAM" --pubkeys-file "$pubs_file" --self-pid "$self_pid" --exclude-pid "$self_pid")
  if [[ "$mode" == "counts" ]]; then
    scan_args+=(--report-counts)
  fi
  rc=0
  scan_out=$(printf '%s\n' "$ps_blob" | python3 "$scanner" "${scan_args[@]}") || rc=$?
  if [[ "$rc" -ne 0 ]]; then
    echo "ABORT: seat identity scanner exited $rc (fail-closed; refuse 'no seats alive')" >&2
    printf '%s\n' "$scan_out" >&2
    return 1
  fi
  scan_ok_line=$(printf '%s\n' "$scan_out" | grep -E '^SCAN_OK matches=[0-9]+ ps_lines=[0-9]+$' | tail -n1 || true)
  if [[ -z "$scan_ok_line" ]]; then
    echo "ABORT: scanner output missing SCAN_OK summary line (fail-closed)" >&2
    printf '%s\n' "$scan_out" >&2
    return 1
  fi
  matches_n=${scan_ok_line#*matches=}
  matches_n=${matches_n%% *}
  ps_lines=${scan_ok_line#*ps_lines=}
  if [[ ! "$ps_lines" =~ ^[0-9]+$ ]] || [[ "$ps_lines" -le 0 ]]; then
    echo "ABORT: scanner SCAN_OK ps_lines=$ps_lines (must be >0; fail-closed)" >&2
    printf '%s\n' "$scan_out" >&2
    return 1
  fi
  # Emit match (+ optional COUNT) lines; drop SCAN_OK from stdout for callers.
  printf '%s\n' "$scan_out" | grep -vE '^SCAN_OK ' || true
  return 0
}


# Positive-control artifact path inside a baseline backup.
seat_scan_positive_control_path() {
  local backup=$1
  printf '%s\n' "$backup/seat-scan-positive-control.txt"
}

# Require the baseline positive-control artifact exists with a PASS marker.
# Mutate/rollback must call this before trusting a 0-match identity scan.
require_seat_scan_positive_control_artifact() {
  local backup=$1
  local f
  f=$(seat_scan_positive_control_path "$backup")
  if [[ ! -f "$f" ]]; then
    echo "ABORT: missing seat-scan positive control $f" >&2
    echo "Re-run apply.sh --baseline-only with Desktop UP (doctor 9/9) so each of the 9" >&2
    echo "seat pubkeys gets >=1 BUZZ_RUNTIME_ID=${ID_TEAM}/<pubkey> match. Without PASS," >&2
    echo "a 0-match scan is not trusted (fail-closed)." >&2
    return 1
  fi
  if ! grep -qE '^PASS([[:space:]]|$)' "$f"; then
    echo "ABORT: positive control $f lacks PASS marker — refuse to trust 0-match scan" >&2
    return 1
  fi
  echo "seat-scan positive control artifact OK: $f"
}

# Baseline (Desktop UP): run identity scan with --report-counts; require EACH of
# the 9 seat pubkeys has >=1 match. Write $BACKUP/seat-scan-positive-control.txt
# with PASS, per-pid matches (token only), and per-seat counts. On failure do NOT
# leave a usable PASS artifact (caller must not write baseline_at either).
run_seat_scan_positive_control() {
  local backup=$1
  local pubs_file out_file scan_out rc=0
  local -a missing=()
  local pub n total pubs_n
  pubs_file=$(mktemp)
  out_file=$(seat_scan_positive_control_path "$backup")
  team_seat_pubkeys_from_pid_files > "$pubs_file"
  pubs_n=$(wc -l < "$pubs_file" | tr -d ' ')
  if [[ "$pubs_n" -ne 9 ]]; then
    rm -f "$pubs_file"
    echo "ABORT: positive control expected 9 TEAM pubkeys, found $pubs_n under $PID_DIR" >&2
    return 1
  fi
  rc=0
  scan_out=$(scan_team_seat_identity_matches "$pubs_file" counts) || rc=$?
  if [[ "$rc" -ne 0 ]]; then
    rm -f "$pubs_file"
    echo "ABORT: positive control identity scan failed (exit=$rc)" >&2
    return 1
  fi
  # Build artifact (no secrets — only pid / pubkey / BUZZ_RUNTIME_ID token / counts).
  {
    echo "# seat-scan positive control (Issue #38 A15)"
    echo "# team_id=${ID_TEAM}"
    echo "# rule: buzz_team.cli|buzz-acp argv0 AND exact BUZZ_RUNTIME_ID=\${ID_TEAM}/<pubkey>"
    echo "# generated=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "# --- matches (pid, pubkey, token) ---"
    printf '%s\n' "$scan_out" | awk -F'\t' 'NF==3 && $1 ~ /^[0-9]+$/ {print}'
    echo "# --- per-seat counts ---"
    printf '%s\n' "$scan_out" | awk -F'\t' '$1=="COUNT" {print}'
  } > "$out_file.tmp"

  missing=()
  total=0
  while IFS= read -r pub; do
    [[ -n "$pub" ]] || continue
    n=$(printf '%s\n' "$scan_out" | awk -F'\t' -v p="$pub" '$1=="COUNT" && $2==p {print $3; found=1} END{if(!found) print 0}')
    total=$((total + n))
    if [[ "$n" -lt 1 ]]; then
      missing+=("$pub")
    fi
  done < "$pubs_file"
  rm -f "$pubs_file"

  if ((${#missing[@]} > 0)); then
    {
      echo "RESULT=FAIL"
      echo "missing_seats=${#missing[@]}"
      printf 'missing_pubkey=%s\n' "${missing[@]}"
    } >> "$out_file.tmp"
    mv "$out_file.tmp" "$out_file"
    echo "ABORT: positive control FAIL — ${#missing[@]} seat pubkey(s) have 0 identity matches:" >&2
    printf '  %s\n' "${missing[@]}" >&2
    echo "Desktop must be UP with doctor 9/9; refusing to write a usable baseline." >&2
    return 1
  fi
  {
    echo "PASS"
    echo "seats_ok=9"
    echo "total_matches=${total}"
    echo "# total may exceed 18 (wrapper + buzz-acp + executor children like python -m buzz_team.cli)"
  } >> "$out_file.tmp"
  mv "$out_file.tmp" "$out_file"
  echo "seat-scan positive control PASS: 9/9 seats matched (total_matches=${total}) -> $out_file"
}

# Abort if any TEAM seat identity is still live (wrapper or buzz-acp).
# $1 = backup dir that must contain seat-scan-positive-control.txt with PASS
#      before a 0-match result is trusted (mutate/rollback).
require_team_seats_not_running() {
  local backup=${1:-}
  local pubs_file matches rc=0
  if [[ -z "$backup" ]]; then
    echo "ABORT: require_team_seats_not_running needs backup dir (positive-control gate)" >&2
    return 1
  fi
  require_seat_scan_positive_control_artifact "$backup" || return 1
  pubs_file=$(mktemp)
  team_seat_pubkeys_from_pid_files > "$pubs_file"
  if [[ ! -s "$pubs_file" ]]; then
    rm -f "$pubs_file"
    echo "ABORT: no TEAM pid files matching *__${TEAM}.json under $PID_DIR" >&2
    return 1
  fi
  rc=0
  matches=$(scan_team_seat_identity_matches "$pubs_file") || rc=$?
  rm -f "$pubs_file"
  if [[ "$rc" -ne 0 ]]; then
    echo "ABORT: identity scan failed during seats-not-running check (exit=$rc)" >&2
    return 1
  fi
  # Drop COUNT lines if any; keep pid\tpubkey\tvia
  matches=$(printf '%s\n' "$matches" | awk -F'\t' 'NF==3 && $1 ~ /^[0-9]+$/')
  if [[ -n "$matches" ]]; then
    echo "ABORT: TEAM seat process(es) still alive (identity match; Desktop quit incomplete):" >&2
    while IFS=$'\t' read -r pid pub via; do
      [[ -n "${pid:-}" ]] || continue
      echo "  pid=${pid} pubkey=${pub} via=${via}" >&2
    done <<< "$matches"
    echo "Cmd+Q fully quit Desktop and wait for ACP teardown, then re-run." >&2
    return 1
  fi
  echo "TEAM seat identity scan: no live seats OK (positive control trusted)"
}

# Abort unless something is listening on TCP :3000 (relay / colima forward — A14).
require_relay_3000_listening() {
  local out
  out=$(lsof -nP -iTCP:3000 -sTCP:LISTEN 2>/dev/null || true)
  if [[ -z "$out" ]]; then
    echo "ABORT: relay :3000 not listening (colima down?) — see RUNBOOK A14" >&2
    return 1
  fi
  echo "relay :3000 listening OK"
  printf '%s\n' "$out"
}

# Abort if Desktop main process is up, OR any TEAM seat still matches the
# identity scan (exact BUZZ_RUNTIME_ID=${ID_TEAM}/<pubkey> + wrapper/buzz-acp).
# $1 = backup dir for positive-control gate (required).
# Does NOT use pid-file kill -0 or pgrep -P. Does NOT scan machine-wide for
# buzz-acp by name alone.
require_desktop_not_running() {
  local backup=${1:-}
  local pids
  pids=$(desktop_main_pids | tr '\n' ' ' | sed 's/[[:space:]]*$//')
  if [[ -n "$pids" ]]; then
    echo "ABORT: Buzz Desktop appears running (pids: $pids)." >&2
    echo "Cmd+Q fully quit Desktop first, then re-run." >&2
    return 1
  fi
  echo "Desktop not running OK"

  require_team_seats_not_running "$backup" || return 1
}

# Record baseline capture time (epoch seconds) for mutate freshness gate.
record_baseline_at() {
  local backup=$1
  local epoch
  epoch=$(date +%s)
  printf '%s\n' "$epoch" > "$backup/baseline_at"
  echo "baseline_at=$epoch (epoch) -> $backup/baseline_at (max age ${BASELINE_MAX_AGE_S}s)"
}

# Reject backup dirs whose baseline_at is missing or older than BASELINE_MAX_AGE_S.
require_baseline_fresh() {
  local backup=$1
  local stamp now age
  if [[ ! -f "$backup/baseline_at" ]]; then
    echo "ABORT: missing $backup/baseline_at (re-run apply.sh --baseline-only; unstamped baselines are rejected)." >&2
    return 1
  fi
  stamp=$(tr -d '[:space:]' < "$backup/baseline_at")
  if [[ ! "$stamp" =~ ^[0-9]+$ ]]; then
    echo "ABORT: invalid baseline_at '$stamp' in $backup/baseline_at" >&2
    return 1
  fi
  now=$(date +%s)
  age=$((now - stamp))
  if (( age < 0 )); then
    echo "ABORT: baseline_at $stamp is in the future (now=$now)" >&2
    return 1
  fi
  if (( age > BASELINE_MAX_AGE_S )); then
    echo "ABORT: baseline is ${age}s old (max ${BASELINE_MAX_AGE_S}s). Re-run --baseline-only." >&2
    return 1
  fi
  echo "baseline freshness OK: age=${age}s (max ${BASELINE_MAX_AGE_S}s)"
}

# Assert live workflow content == docs/issue-38/before/workflow.yaml.
# Requires buzz CLI + BUZZ_PRIVATE_KEY / PATH / BUZZ_RELAY_URL already exported.
# $1 = issue-38 root (parent of before/). Optional $2 = path to save raw get JSON.
assert_live_workflow_matches_before() {
  local root=$1
  local save_as=${2:-}
  local live_get
  live_get=$(mktemp)
  buzz workflows get --workflow "$WF_ID" > "$live_get"
  if ! python3 -c "
import json, sys
from pathlib import Path
live=json.loads(Path(sys.argv[1]).read_text())['content']
staged=Path(sys.argv[2]).read_text()
def norm(s):
    return s.replace('\r\n','\n').strip()+'\n'
if norm(live)!=norm(staged):
    print('ABORT: live workflow content != docs/issue-38/before/workflow.yaml', file=sys.stderr)
    print('--- live ---', file=sys.stderr); print(norm(live)[:500], file=sys.stderr)
    print('--- staged ---', file=sys.stderr); print(norm(staged)[:500], file=sys.stderr)
    sys.exit(1)
print('live workflow matches staged before OK')
" "$live_get" "$root/before/workflow.yaml"; then
    rm -f "$live_get"
    return 1
  fi
  if [[ -n "$save_as" ]]; then
    cp "$live_get" "$save_as"
  fi
  rm -f "$live_get"
  return 0
}

# Snapshot ALL TEAM seat pids (including 周衡) as name<TAB>pid lines.
snapshot_all_team_pids() {
  local out=$1
  local f base
  : > "$out"
  for f in "$PID_DIR"/*__"${TEAM}".json; do
    [[ -e "$f" ]] || continue
    base=$(basename "$f")
    python3 -c "import json,sys; print(sys.argv[1]+chr(9)+str(json.load(open(sys.argv[2]))['pid']))" "$base" "$f" >> "$out"
  done
  local n
  n=$(wc -l < "$out" | tr -d ' ')
  echo "all TEAM seats recorded: $n"
  if [[ "$n" -ne 9 ]]; then
    echo "WARN: expected 9 TEAM seats, got $n" >&2
  fi
}

# Post-restart pid check for verify-after-restart.sh.
# mode=single: other 8 pids unchanged+alive; 周衡 must be new (caller checks).
# mode=app:    all 9 pids changed+alive.
# Mismatch with declared mode => FAIL (no auto-guess).
verify_restart_pids() {
  local mode=$1
  local all_before=$2
  local zhou_old=$3
  local zhou_new=$4
  case "$mode" in
    single|app) ;;
    *) echo "ABORT: --restart-mode must be single|app, got: $mode" >&2; return 1 ;;
  esac
  python3 - "$mode" "$all_before" "${zhou_old:-}" "$zhou_new" "$PID_DIR" "$TEAM" "$PUB" <<'PY'
import json, os, sys
from pathlib import Path

mode, before_path, zhou_old, zhou_new, pid_dir, team, pub = sys.argv[1:8]
zhou_file = f"{pub}__{team}.json"

before = {}
for line in Path(before_path).read_text().splitlines():
    line = line.strip()
    if not line:
        continue
    name, pid = line.split("\t", 1)
    before[name] = int(pid)

if len(before) != 9:
    print(f"FAIL: baseline all-pids-before has {len(before)} seats, want 9", file=sys.stderr)
    sys.exit(1)

live = {}
for f in Path(pid_dir).glob(f"*__{team}.json"):
    name = f.name
    pid = json.loads(f.read_text())["pid"]
    try:
        os.kill(pid, 0)
        alive = True
    except OSError:
        alive = False
    live[name] = (pid, alive)

if len(live) != 9:
    print(f"FAIL: live TEAM seats={len(live)}, want 9", file=sys.stderr)
    sys.exit(1)

dead = [n for n, (_pid, alive) in live.items() if not alive]
if dead:
    print("FAIL: dead seat pid(s): " + ", ".join(f"{n}:{live[n][0]}" for n in dead), file=sys.stderr)
    sys.exit(1)

changed = []
unchanged = []
for name, old_pid in before.items():
    if name not in live:
        print(f"FAIL: missing live pid file for {name}", file=sys.stderr)
        sys.exit(1)
    new_pid = live[name][0]
    if new_pid == old_pid:
        unchanged.append(f"{name}:{old_pid}")
    else:
        changed.append(f"{name}:{old_pid}->{new_pid}")

zhou_key = zhou_file
if zhou_key not in before or zhou_key not in live:
    print(f"FAIL: 周衡 pid file {zhou_key} missing from before/live", file=sys.stderr)
    sys.exit(1)

if zhou_old and str(live[zhou_key][0]) == str(zhou_old):
    print(f"FAIL: 周衡 pid still equals pre-quit baseline {zhou_old}", file=sys.stderr)
    sys.exit(1)
if live[zhou_key][0] == before[zhou_key]:
    print(f"FAIL: 周衡 pid unchanged vs all-pids-before ({before[zhou_key]})", file=sys.stderr)
    sys.exit(1)

others_changed = [c for c in changed if not c.startswith(zhou_key + ":")]
others_unchanged = [u for u in unchanged if not u.startswith(zhou_key + ":")]

if mode == "single":
    if others_changed:
        print("FAIL: --restart-mode single but other seat pid(s) changed:", file=sys.stderr)
        print("  " + "\n  ".join(others_changed), file=sys.stderr)
        print(
            "Hint: quit-first (Cmd+Q) always implies --restart-mode app; "
            "use --restart-mode single only for experiments without Cmd+Q.",
            file=sys.stderr,
        )
        sys.exit(1)
    if len(others_unchanged) != 8:
        print(
            f"FAIL: --restart-mode single expected 8 other seats unchanged, got {len(others_unchanged)}",
            file=sys.stderr,
        )
        sys.exit(1)
    print("restart_mode=single OK: other 8 pids unchanged+alive; 周衡 new+alive")
elif mode == "app":
    if others_unchanged:
        print("FAIL: --restart-mode app but other seat pid(s) UNCHANGED:", file=sys.stderr)
        print("  " + "\n  ".join(others_unchanged), file=sys.stderr)
        sys.exit(1)
    if len(changed) != 9:
        print(
            f"FAIL: --restart-mode app expected all 9 pids changed, got {len(changed)}",
            file=sys.stderr,
        )
        print("  changed: " + ", ".join(changed), file=sys.stderr)
        sys.exit(1)
    print("restart_mode=app OK: all 9 pids changed+alive")
PY
}
