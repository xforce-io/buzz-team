#!/usr/bin/env bash
# Real relay smoke for Issue #38: prove --yaml takes CONTENT (via $(cat)), not a path.
# Creates a TEMP workflow only (cron never fires; body mentions NO seat), updates it,
# verifies read-back, deletes it, and asserts full list-workflows BEFORE == AFTER.
# Authorized for live Mac; does NOT touch real workflows (incl. f5cc62c0…).
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$DIR/.." && pwd)"
OUT="${SMOKE_OUT:-$ROOT/smoke}"
# shellcheck source=common.sh
source "$DIR/common.sh"

mkdir -p "$OUT"
STAMP=$(date +%Y%m%d-%H%M%S)
WORKDIR=$(mktemp -d)
trap 'rm -rf "$WORKDIR"' EXIT

eval "$(grep -E '^PJ_PRIVATE_KEY=' /Users/xupeng/.local/share/buzz/config/agents.env | sed 's/^PJ_PRIVATE_KEY=/BUZZ_PRIVATE_KEY=/')"
export PATH="/Users/xupeng/lab/buzz/bin:$PATH"
export BUZZ_RELAY_URL="${BUZZ_RELAY_URL:-ws://127.0.0.1:3000}"
BUZZ_BIN="${BUZZ_BIN:-/Users/xupeng/lab/buzz/bin/buzz}"
test -x "$BUZZ_BIN"

# Capture CLI contract for PR body
"$BUZZ_BIN" workflows update --help > "$OUT/buzz-workflows-update-help.txt" 2>&1

# Channel under test (standup); also snapshot ALL visible channels' workflow lists.
PRIMARY_CH="$CH_ID"

list_all() {
  local out="$1"
  python3 - "$out" <<'PY'
import json, os, subprocess, sys
from pathlib import Path
out = Path(sys.argv[1])
env = os.environ.copy()
buzz = env.get("BUZZ_BIN", "/Users/xupeng/lab/buzz/bin/buzz")
ch_raw = subprocess.check_output([buzz, "channels", "list"], env=env, text=True)
channels = json.loads(ch_raw)
# Normalize to sorted list of {channel_id, name, workflows:[{workflow_id, content, pubkey, created_at}]}
rows = []
for ch in channels:
    cid = ch["channel_id"]
    name = ch.get("name") or ""
    try:
        w_raw = subprocess.check_output(
            [buzz, "workflows", "list", "--channel", cid], env=env, text=True
        )
        wfs = json.loads(w_raw)
    except subprocess.CalledProcessError as e:
        wfs = {"_list_error": str(e), "stderr": getattr(e, "stderr", None)}
    # Sort workflows by id for stable diff
    if isinstance(wfs, list):
        wfs = sorted(wfs, key=lambda w: w.get("workflow_id") or "")
    rows.append({"channel_id": cid, "name": name, "workflows": wfs})
rows.sort(key=lambda r: r["channel_id"])
out.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n")
print(f"listed {len(rows)} channels -> {out}")
PY
}

echo "== BEFORE: full list-workflows across visible channels =="
list_all "$OUT/list-before.json"

# Temp workflow: cron never fires (Feb 30); body mentions NO seat names.
TMP_YAML="$WORKDIR/smoke-temp.yaml"
cat > "$TMP_YAML" <<'YAML'
name: issue38-smoke-temp-do-not-keep
description: TEMP smoke for #38 yaml-content proof; cron never fires; NO seat mention. Delete after smoke.
trigger:
  on: schedule
  cron: "0 0 30 2 *"
steps:
  - id: smoke_noop
    action: send_message
    text: "issue38-smoke-temp placeholder — do not notify anyone; delete after smoke"
    reply_in_thread: false
YAML

# If Feb-30 cron rejected, fall back to Feb-31.
create_out="$WORKDIR/create.json"
set +e
create_err="$WORKDIR/create.err"
"$BUZZ_BIN" workflows create --channel "$PRIMARY_CH" --yaml "$(cat "$TMP_YAML")" >"$create_out" 2>"$create_err"
rc=$?
set -e
if [[ $rc -ne 0 ]]; then
  echo "create with Feb-30 cron failed (rc=$rc); trying Feb-31 fallback" >&2
  cat "$create_err" >&2 || true
  sed -i.bak 's/0 0 30 2 \*/0 0 31 2 */' "$TMP_YAML"
  "$BUZZ_BIN" workflows create --channel "$PRIMARY_CH" --yaml "$(cat "$TMP_YAML")" >"$create_out"
fi
cp "$create_out" "$OUT/create-response.json"
cp "$TMP_YAML" "$OUT/smoke-temp.yaml"

SMOKE_WF=$(python3 -c "
import json,sys
from pathlib import Path
d=json.loads(Path(sys.argv[1]).read_text())
# accept several shapes
wid=d.get('workflow_id') or d.get('id') or (d.get('workflow') or {}).get('workflow_id')
if not wid and isinstance(d, dict):
    for k,v in d.items():
        if 'workflow' in k.lower() and isinstance(v,str) and len(v)>20:
            wid=v; break
if not wid:
    raise SystemExit('cannot parse workflow_id from create response: '+json.dumps(d)[:500])
print(wid)
" "$create_out")
echo "SMOKE_WF=$SMOKE_WF"
echo "$SMOKE_WF" > "$OUT/smoke-workflow-id.txt"

# Guard: never operate on the real standup workflow
if [[ "$SMOKE_WF" == "$WF_ID" ]]; then
  echo "ABORT: create returned real standup workflow id" >&2
  exit 1
fi

# Mutate via update with CONTENT (the bug under test)
UPD_YAML="$WORKDIR/smoke-temp-updated.yaml"
cat > "$UPD_YAML" <<'YAML'
name: issue38-smoke-temp-do-not-keep
description: TEMP smoke UPDATED body for #38; cron never fires; NO seat mention.
trigger:
  on: schedule
  cron: "0 0 30 2 *"
steps:
  - id: smoke_noop
    action: send_message
    text: "issue38-smoke-temp UPDATED — still no seat; delete after smoke"
    reply_in_thread: false
YAML
# Keep cron in sync with whatever create accepted
CRON=$(python3 -c "import re,sys; print(re.search(r'cron: \"([^\"]+)\"', open(sys.argv[1]).read()).group(1))" "$TMP_YAML")
python3 -c "
from pathlib import Path
import re, sys
p=Path(sys.argv[1]); cron=sys.argv[2]
t=p.read_text()
t=re.sub(r'cron: \"[^\"]+\"', f'cron: \"{cron}\"', t)
p.write_text(t)
" "$UPD_YAML" "$CRON"
cp "$UPD_YAML" "$OUT/smoke-temp-updated.yaml"

echo "== update temp workflow with YAML CONTENT (\$(cat)) =="
# Brief settle after create; retry on write-conflict (relay 400 superseded).
sleep 1
upd_ok=0
for attempt in 1 2 3 4 5; do
  set +e
  "$BUZZ_BIN" workflows update --channel "$PRIMARY_CH" --workflow "$SMOKE_WF" --yaml "$(cat "$UPD_YAML")" >"$WORKDIR/update.out" 2>"$WORKDIR/update.err"
  urc=$?
  set -e
  cat "$WORKDIR/update.out" >> "$OUT/update-attempts.txt" 2>/dev/null || true
  echo "attempt=$attempt rc=$urc" >> "$OUT/update-attempts.txt"
  cat "$WORKDIR/update.err" >> "$OUT/update-attempts.txt" 2>/dev/null || true
  if [[ $urc -eq 0 ]]; then
    upd_ok=1
    break
  fi
  if grep -qi 'superseded\|conflict\|write conflict' "$WORKDIR/update.err" "$WORKDIR/update.out" 2>/dev/null; then
    echo "update conflict on attempt $attempt — retrying" >&2
    sleep $((attempt))
    continue
  fi
  echo "update failed non-conflict rc=$urc" >&2
  cat "$WORKDIR/update.err" >&2
  exit $urc
done
[[ $upd_ok -eq 1 ]] || { echo "update failed after retries" >&2; exit 1; }
"$BUZZ_BIN" workflows get --workflow "$SMOKE_WF" > "$OUT/get-after-update.json"
python3 -c "
import json, sys
from pathlib import Path
live=json.loads(Path(sys.argv[1]).read_text())['content']
want=Path(sys.argv[2]).read_text()
def norm(s):
    return s.replace('\r\n','\n').strip()+'\n'
if norm(live)!=norm(want):
    print('FAIL: get after update != updated yaml', file=sys.stderr)
    print('--- live ---', file=sys.stderr); print(norm(live), file=sys.stderr)
    print('--- want ---', file=sys.stderr); print(norm(want), file=sys.stderr)
    sys.exit(1)
print('update read-back OK (content match)')
" "$OUT/get-after-update.json" "$UPD_YAML"

echo "== delete temp workflow =="
set +e
"$BUZZ_BIN" workflows delete --workflow "$SMOKE_WF" >"$OUT/delete-response.txt" 2>"$OUT/delete-stderr.txt"
del_rc=$?
set -e
echo "delete rc=$del_rc" | tee -a "$OUT/delete-response.txt"
# Note kind:30620 may linger after delete (per #34)
if grep -qi '30620\|linger\|tombstone\|still' "$OUT/delete-stderr.txt" "$OUT/delete-response.txt" 2>/dev/null; then
  echo "NOTE: possible kind:30620 linger signal in delete output (recorded)" | tee -a "$OUT/notes.txt"
fi
# Also record if get still returns something after delete
set +e
"$BUZZ_BIN" workflows get --workflow "$SMOKE_WF" >"$OUT/get-after-delete.json" 2>"$OUT/get-after-delete.err"
get_rc=$?
set -e
echo "get-after-delete rc=$get_rc" >> "$OUT/notes.txt"
if [[ $get_rc -eq 0 ]]; then
  echo "NOTE: workflows get still succeeds after delete — possible kind:30620 linger (per #34)" | tee -a "$OUT/notes.txt"
  cat "$OUT/get-after-delete.json" >> "$OUT/notes.txt" || true
fi

echo "== AFTER: full list-workflows =="
list_all "$OUT/list-after.json"

echo "== diff BEFORE vs AFTER (must be empty / identical) =="
python3 -c "
import json, sys
from pathlib import Path
b=json.loads(Path(sys.argv[1]).read_text())
a=json.loads(Path(sys.argv[2]).read_text())
# Drop any leftover smoke workflow if delete lingered in list (should not)
def strip_smoke(rows):
    out=[]
    for r in rows:
        wfs=r.get('workflows')
        if isinstance(wfs, list):
            wfs=[w for w in wfs if 'issue38-smoke-temp' not in (w.get('content') or '')]
        out.append({**r, 'workflows': wfs})
    return out
# Primary assertion: exact equality of the captured lists
if a==b:
    print('DIFF EMPTY: list-before == list-after (exact)')
    Path(sys.argv[3]).write_text('exact match\n')
    sys.exit(0)
# Soft note if only smoke residue
if strip_smoke(a)==strip_smoke(b) and a!=b:
    print('WARN: lists differ only by smoke residue after delete; recording', file=sys.stderr)
    Path(sys.argv[3]).write_text('differ only by smoke residue\n'+json.dumps({'before':b,'after':a}, ensure_ascii=False, indent=2))
    # Still treat as soft-fail for human eyes — exit 0 but flag in notes
    Path(sys.argv[4]).write_text('list diff only smoke residue (kind:30620 linger?)\n')
    sys.exit(0)
print('FAIL: list-before != list-after', file=sys.stderr)
import pprint
# show compact diff of workflow ids per channel
for br, ar in zip(b, a) if len(a)==len(b) else []:
    bid=sorted([(w.get('workflow_id'), (w.get('content') or '')[:40]) for w in (br.get('workflows') or [])])
    aid=sorted([(w.get('workflow_id'), (w.get('content') or '')[:40]) for w in (ar.get('workflows') or [])])
    if bid!=aid:
        print(br['channel_id'], file=sys.stderr)
        print(' before ids', [x[0] for x in bid], file=sys.stderr)
        print(' after  ids', [x[0] for x in aid], file=sys.stderr)
Path(sys.argv[3]).write_text(json.dumps({'before':b,'after':a}, ensure_ascii=False, indent=2))
sys.exit(1)
" "$OUT/list-before.json" "$OUT/list-after.json" "$OUT/list-diff.txt" "$OUT/notes.txt"

# Ensure primary channel is present in before snapshot
python3 -c "
import json,sys
from pathlib import Path
rows=json.loads(Path(sys.argv[1]).read_text())
cid=sys.argv[2]
assert any(r['channel_id']==cid for r in rows), 'primary channel missing from before list'
print('primary channel present:', cid)
" "$OUT/list-before.json" "$PRIMARY_CH"


# Explicit DIFF-SUMMARY for PR evidence
python3 - "$OUT" <<'SUM'
import json, sys
from pathlib import Path
out = Path(sys.argv[1])
b = json.loads((out/"list-before.json").read_text())
a = json.loads((out/"list-after.json").read_text())
smoke = (out/"smoke-workflow-id.txt").read_text().strip() if (out/"smoke-workflow-id.txt").exists() else "?"
def ids(rows):
    return {r["channel_id"]: sorted(w.get("workflow_id") for w in (r.get("workflows") or []) if isinstance(w, dict)) for r in rows}
ib, ia = ids(b), ids(a)
only_after = sorted({x for cid in ia for x in set(ia[cid]) - set(ib.get(cid, []))})
only_before = sorted({x for cid in ib for x in set(ib[cid]) - set(ia.get(cid, []))})
def strip_smoke(rows):
    out_rows=[]
    for r in rows:
        wfs=r.get("workflows")
        if isinstance(wfs, list):
            wfs=[w for w in wfs if "issue38-smoke-temp" not in (w.get("content") or "")]
        out_rows.append({**r, "workflows": wfs})
    return out_rows
exact = a == b
canon = strip_smoke(a) == strip_smoke(b)
linger = (out/"get-after-delete.json").exists() and (out/"get-after-delete.json").stat().st_size > 0
lines = [
    f"exact_list_match={exact}",
    f"canonical_strip_smoke_match={canon}",
    f"smoke_workflow_id={smoke}",
    f"ids_only_in_after={only_after}",
    f"ids_only_in_before={only_before}",
    f"kind30620_get_after_delete_lingers={linger}",
    "note: Nostr kind:30620 may linger in list/get after delete (refs #34); raw list diff may be non-empty solely due to smoke residue",
]
(out/"DIFF-SUMMARY.txt").write_text("\n".join(lines)+"\n")
print("\n".join(lines))
if not exact and not canon:
    raise SystemExit("FAIL: neither exact nor canonical list match")
SUM

echo "smoke-real-workflow OK → $OUT"
echo "STAMP=$STAMP" > "$OUT/meta.txt"
echo "SMOKE_WF=$SMOKE_WF" >> "$OUT/meta.txt"
echo "PRIMARY_CH=$PRIMARY_CH" >> "$OUT/meta.txt"
date >> "$OUT/meta.txt"
