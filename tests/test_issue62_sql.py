"""Issue #62: leftover workflow cleanup SQL (docs/issue-62).

Static checks on the target manifest and scripts, shellcheck, and the full local
PostgreSQL run (backup -> verify -> rehearse -> apply -> verify -> visible -> rollback + negatives).
"""
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
ISSUE = ROOT / "docs" / "issue-62"
COMMUNITY = "14a17e2d-40ae-4182-86c1-7dde01da0f03"


def manifest(name):
    text = (ISSUE / "targets.sql").read_text()
    m = re.search(r"set_config\('r62\.%s', \$r62\$(.*?)\$r62\$" % name, text, re.S)
    return json.loads(m.group(1))


def fnv1a_lock_key(community, kind, pubkey_hex, d_tag):
    """Port of block/buzz c507a4d replaceable.rs::event_replacement_lock_key."""
    h = 0xCBF29CE484222325
    for b in uuid.UUID(community).bytes + struct.pack("<i", kind) + bytes.fromhex(pubkey_hex) + d_tag.encode():
        h = ((h ^ b) * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return h - (1 << 64) if h >= 1 << 63 else h


class ManifestTest(unittest.TestCase):
    def test_targets_exact(self):
        ev, wf = manifest("ev"), manifest("wf")
        self.assertEqual(len(ev), 9)
        self.assertEqual(len(wf), 1)
        self.assertEqual(len({e["d_tag"] for e in ev}), 9)
        self.assertEqual(len({e["id"] for e in ev}), 9)
        self.assertEqual(wf[0]["id"], "107226dd-c569-470a-987a-3b9223b20b77")
        by_tag = {e["d_tag"]: e for e in ev}
        self.assertEqual(by_tag[wf[0]["id"]]["pubkey"], wf[0]["owner"])  # row owner == definition signer
        for e in ev:
            self.assertRegex(e["id"], r"^[0-9a-f]{64}$")
            self.assertRegex(e["pubkey"], r"^[0-9a-f]{64}$")
            self.assertEqual(int(e["lock_key"]), fnv1a_lock_key(COMMUNITY, 30620, e["pubkey"], e["d_tag"]))

    def test_expected_totals(self):
        text = (ISSUE / "targets.sql").read_text()
        exp = json.loads(re.search(r"set_config\('r62\.expect', '(\{.*?\})'", text).group(1))
        self.assertEqual(exp, {"wf_before": 9, "wf_after": 8, "live_before": 17, "live_after": 8, "n_wf": 1, "n_ev": 9})

    def test_readme_lists_every_target(self):
        readme = (ISSUE / "README.md").read_text()
        for e in manifest("ev"):
            self.assertIn(e["d_tag"], readme)
            self.assertIn(e["id"][:8], readme)


class ScriptShapeTest(unittest.TestCase):
    def test_apply_and_rollback_rely_on_single_transaction(self):
        for name in ("apply.sql", "rollback.sql"):
            body = (ISSUE / name).read_text()
            code = "\n".join(l for l in body.splitlines() if not l.lstrip().startswith("--"))
            self.assertNotRegex(code, r"(?im)^\s*(BEGIN|COMMIT|ROLLBACK)\s*;", name)
            self.assertIn("GET DIAGNOSTICS n = ROW_COUNT", code, name)
        apply = (ISSUE / "apply.sql").read_text()
        self.assertIn("IF n <> 1 THEN RAISE EXCEPTION '#62 abort: DELETE workflow", apply)
        self.assertIn("IF total <> 9 THEN RAISE EXCEPTION", apply)
        self.assertIn("pg_advisory_xact_lock", apply)
        rollback = (ISSUE / "rollback.sql").read_text()
        self.assertIn("json_populate_record(NULL::workflows", rollback)
        self.assertIn("json_populate_record(NULL::events", rollback)

    def test_rehearse_includes_real_apply_and_rollback_then_rolls_back(self):
        body = (ISSUE / "rehearse.sql").read_text()
        order = [body.index(s) for s in ("BEGIN;", "\\ir apply.sql", "\\ir rollback.sql", "IS DISTINCT FROM", "ROLLBACK;")]
        self.assertEqual(order, sorted(order))
        self.assertNotRegex(body, r"(?im)^\s*COMMIT\s*;")

    def test_run_sh_flags(self):
        run = (ISSUE / "run.sh").read_text()
        self.assertIn('psql_run rw -1 -f -', run)          # apply: -1 + ON_ERROR_STOP (in psql_run)
        self.assertIn("-v ON_ERROR_STOP=1", run)
        self.assertIn("default_transaction_read_only=on", run)
        self.assertIn("REHEARSAL PASS", run)

    def test_no_signing_identity(self):
        # Jenny 2026-10-01 00:52: #62 has no authorized signing identity; the post-apply list check is read-only psql.
        for path in sorted(ISSUE.rglob("*")):
            if path.is_file():
                text = path.read_text()
                self.assertNotIn("BUZZ_PRIVATE_KEY", text, path)
                self.assertNotIn("run.sh list", text, path)
                self.assertNotRegex(text, r"(?m)^[^#\n]*\$\{?BUZZ_BIN", path)
        run = (ISSUE / "run.sh").read_text()
        self.assertNotIn("workflows list", run)
        self.assertNotRegex(run, r"(?m)^\s*list\)")
        self.assertIn('inline "$HERE/visible.sql" | psql_run ro -f -', run)
        visible = (ISSUE / "visible.sql").read_text()
        code = "\n".join(l for l in visible.splitlines() if not l.lstrip().startswith("--"))
        self.assertIn("BEGIN READ ONLY;", code)
        self.assertRegex(code, r"ROLLBACK;\s*$")
        self.assertNotRegex(code, r"(?i)\b(INSERT|UPDATE|DELETE|COMMIT)\b")
        self.assertIn("VISIBLE CHECK PASS", code)

    @unittest.skipUnless(shutil.which("shellcheck"), "shellcheck not installed")
    def test_shellcheck(self):
        subprocess.run(["shellcheck", str(ISSUE / "run.sh"), str(ISSUE / "test" / "local-test.sh")], check=True)


class LocalPostgresTest(unittest.TestCase):
    def test_full_flow_against_local_postgres(self):
        proc = subprocess.run([str(ISSUE / "test" / "local-test.sh")], capture_output=True, text=True)
        if proc.returncode == 77:
            if os.environ.get("GITHUB_ACTIONS"):
                self.fail("CI must run the #62 PostgreSQL test: " + proc.stdout)
            self.skipTest(proc.stdout.strip())
        self.assertEqual(proc.returncode, 0, proc.stdout[-4000:] + proc.stderr[-4000:])
        self.assertIn("ALL 26 CHECKS PASSED", proc.stdout)


if __name__ == "__main__":
    unittest.main()
