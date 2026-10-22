#!/usr/bin/env bash
# #69 owner update for f5cc62c0. Default is dry-run: rewrite cron in memory and print.
# Live: ISSUE69_I_UNDERSTAND_LIVE=yes apply.sh --live --backup <evidence-dir>
# Does not write SQL definitions. Avoid CST 08:58–09:02. Does not launch Desktop.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=common.sh
source "$HERE/common.sh"

LIVE=0
BACKUP=""
FROM_YAML=""
while [ $# -gt 0 ]; do
  case "$1" in
    --live) LIVE=1; shift ;;
    --backup) BACKUP=${2:?}; shift 2 ;;
    --backup=*) BACKUP=${1#*=}; shift ;;
    --from-yaml) FROM_YAML=${2:?}; shift 2 ;;
    --from-yaml=*) FROM_YAML=${1#*=}; shift ;;
    *) die "unknown arg: $1" ;;
  esac
done

if [ "$LIVE" -eq 1 ]; then
  require_live_guard
  refuse_apply_window
  [ -n "$BACKUP" ] || die "--live requires --backup <evidence-dir>"
  [ -s "$BACKUP/before/backup.json" ] || die "missing $BACKUP/before/backup.json"
  [ -n "${BUZZ_PRIVATE_KEY:-}" ] || die "live apply needs BUZZ_PRIVATE_KEY in the environment (Zhouheng owner). Script does not read agents.env"
  command -v buzz >/dev/null || die "buzz CLI not on PATH"
fi

SRC="$FROM_YAML"
CLEANUP=""
if [ -z "$SRC" ]; then
  if [ "$LIVE" -eq 1 ]; then
    SRC=$(mktemp)
    CLEANUP="$SRC"
    buzz workflows get --workflow "$WF_ID" > "$BACKUP/before/workflow-get.json"
    PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}" python3 -c "
import json
from pathlib import Path
print(json.loads(Path(r'''$BACKUP/before/workflow-get.json''').read_text())['content'], end='')
" > "$SRC"
    cp "$SRC" "$BACKUP/before/workflow-live.yaml"
  else
    SRC="$HERE/after/workflow.yaml"
    # Dry-run without live YAML uses the #38-after body only as a rewrite demo
    # when --from-yaml is omitted. Hogan must pass live get content for the real change.
    if [ -z "$FROM_YAML" ]; then
      echo "dry-run: no --from-yaml; demonstrating rewrite requires a 1-5 source." >&2
      SRC=$(mktemp)
      CLEANUP="$SRC"
      PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}" python3 -c "
from pathlib import Path
from buzz_team.cron_dow import replace_schedule_cron
text = Path(r'''$HERE/after/workflow.yaml''').read_text()
# after template is already MON-FRI; invert for the dry-run demo input
print(replace_schedule_cron(text, r'''$CRON_BEFORE''', expect=r'''$CRON_AFTER'''), end='')
" > "$SRC"
    fi
  fi
fi

OUT=$(mktemp)
trap 'rm -f "$CLEANUP" "$OUT"' EXIT
rewrite_cron "$SRC" > "$OUT"
echo "rewritten cron: $CRON_BEFORE -> $CRON_AFTER"
echo "----- YAML after rewrite -----"
cat "$OUT"

if [ "$LIVE" -eq 0 ]; then
  echo "DRY-RUN: no buzz workflows update sent. Pass --live after ACP>=9 (human:required)."
  exit 0
fi

mkdir -p "$BACKUP/after"
cp "$OUT" "$BACKUP/after/workflow.yaml"
echo "== owner update $WF_ID =="
buzz workflows update --channel "$CH_ID" --workflow "$WF_ID" --yaml "$(cat "$OUT")"
buzz workflows get --workflow "$WF_ID" > "$BACKUP/after/workflow-get.json"
PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}" python3 -c "
import json
from pathlib import Path
from buzz_team.cron_dow import extract_crons, replace_schedule_cron
live = json.loads(Path(r'''$BACKUP/after/workflow-get.json''').read_text())['content']
before = Path(r'''$SRC''').read_text()
crons = extract_crons(live)
if crons != [r'''$CRON_AFTER''']:
    raise SystemExit('post-update cron is %s' % crons)
expect = replace_schedule_cron(before, r'''$CRON_AFTER''', expect=r'''$CRON_BEFORE''')
def norm(s):
    return s.replace('\r\n', '\n').strip() + '\n'
if norm(live) != norm(expect):
    raise SystemExit('post-update YAML differs by more than cron')
print('owner update read-back OK: only cron changed')
"
echo "#69 apply OK (owner update). Next: run.sh verify-after"
