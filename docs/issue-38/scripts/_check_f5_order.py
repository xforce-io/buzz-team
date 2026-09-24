import sys
from pathlib import Path

# F5: config_written_at must be recorded immediately after the first successful
# mutation (workflow update / MUTATED=1) and refreshed after local writes.
lines = Path(sys.argv[1]).read_text().splitlines()
wf = mut = rec1 = patch = rec2 = None
for i, l in enumerate(lines, 1):
    if 'APPLY_STEP="workflow-update"' in l:
        wf = i
    if l.strip() == "MUTATED=1":
        mut = i
    if mut and rec1 is None and "record_config_written_at" in l and not l.strip().startswith("#"):
        rec1 = i
    if 'APPLY_STEP="patch-managed-agents"' in l:
        patch = i
    if patch and rec2 is None and "record_config_written_at" in l and not l.strip().startswith("#"):
        rec2 = i
if not (wf and mut and rec1 and patch and rec2):
    raise SystemExit(
        f"missing markers wf={wf} mut={mut} rec1={rec1} patch={patch} rec2={rec2}"
    )
if not (wf < mut < rec1 < patch < rec2):
    raise SystemExit(
        f"bad order wf={wf} mut={mut} rec1={rec1} patch={patch} rec2={rec2}"
    )
print(f"F5 ordering OK ({wf} < {mut} < {rec1} < {patch} < {rec2})")
