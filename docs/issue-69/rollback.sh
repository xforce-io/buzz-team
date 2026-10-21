#!/usr/bin/env bash
# #69 owner rollback: republish the backed-up YAML. Default dry-run.
# Live: ISSUE69_I_UNDERSTAND_LIVE=yes rollback.sh --live --backup <evidence-dir>
# SQL restore of the workflows row is forbidden after owner update (30620 would desync).
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

SRC="$FROM_YAML"
if [ -z "$SRC" ] && [ -n "$BACKUP" ] && [ -f "$BACKUP/before/workflow-live.yaml" ]; then
  SRC="$BACKUP/before/workflow-live.yaml"
fi
if [ -z "$SRC" ] && [ -n "$BACKUP" ] && [ -f "$BACKUP/before/workflow-get.json" ]; then
  SRC=$(mktemp)
  PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}" python3 -c "
import json
from pathlib import Path
print(json.loads(Path(r'''$BACKUP/before/workflow-get.json''').read_text())['content'], end='')
" > "$SRC"
  trap 'rm -f "$SRC"' EXIT
fi
[ -n "$SRC" ] || die "need --from-yaml or --backup with before/workflow-live.yaml or workflow-get.json"

echo "rollback YAML source: $SRC"
echo "----- YAML to republish -----"
cat "$SRC"

if [ "$LIVE" -eq 0 ]; then
  echo "DRY-RUN: no buzz workflows update sent."
  exit 0
fi

require_live_guard
refuse_apply_window
[ -n "${BUZZ_PRIVATE_KEY:-}" ] || die "live rollback needs BUZZ_PRIVATE_KEY in the environment"
command -v buzz >/dev/null || die "buzz CLI not on PATH"
buzz workflows update --channel "$CH_ID" --workflow "$WF_ID" --yaml "$(cat "$SRC")"
echo "#69 rollback OK (owner republish). Next: run.sh verify-before on the same backup (expect cron 1-5)."
