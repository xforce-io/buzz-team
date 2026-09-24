import sys
from pathlib import Path
lines = Path(sys.argv[1]).read_text().splitlines()
wf = mut = rec = patch = None
for i, l in enumerate(lines, 1):
    if 'APPLY_STEP="workflow-update"' in l:
        wf = i
    if l.strip() == "MUTATED=1":
        mut = i
    if mut and rec is None and "record_config_written_at" in l and not l.strip().startswith("#"):
        rec = i
    if 'APPLY_STEP="patch-managed-agents"' in l:
        patch = i
if not (wf and mut and rec and patch):
    raise SystemExit(f"missing markers wf={wf} mut={mut} rec={rec} patch={patch}")
if not (wf < mut < rec < patch):
    raise SystemExit(f"bad order wf={wf} mut={mut} rec={rec} patch={patch}")
print(f"F5 ordering OK ({wf} < {mut} < {rec} < {patch})")
