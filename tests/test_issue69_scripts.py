"""Issue #69 scripts: shape, dry-run, warn-only checker. No live DB or Desktop."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
ISSUE = ROOT / "docs" / "issue-69"


def _run(args, env=None, cwd=None):
    return subprocess.run(
        args, cwd=cwd or ISSUE, env=env, text=True, capture_output=True, check=False
    )


class ScriptShapeTest(unittest.TestCase):
    def test_rehearse_rolls_back_and_never_commits(self):
        body = (ISSUE / "rehearse.sql").read_text()
        order = [body.index(s) for s in ("BEGIN;", "GET DIAGNOSTICS n = ROW_COUNT", "ROLLBACK;", "REHEARSAL PASS")]
        self.assertEqual(order, sorted(order))
        code = "\n".join(line for line in body.splitlines() if not line.lstrip().startswith("--"))
        self.assertNotRegex(code, r"(?im)^\s*COMMIT\s*;")
        self.assertIn("IF n <> 1 THEN", body)

    def test_verify_is_read_only(self):
        body = (ISSUE / "verify.sql").read_text()
        self.assertIn("not read-only", body)
        self.assertIn("n_kept", body)
        self.assertNotRegex(body, r"(?im)^\s*(INSERT|UPDATE|DELETE|COMMIT)\b")

    def test_backup_is_whole_row(self):
        body = (ISSUE / "backup.sql").read_text()
        self.assertIn("row_to_json(w.*)", body)
        self.assertIn("row_to_json(e.*)", body)
        self.assertIn("workflows_all", body)
        self.assertIn("default_transaction_read_only=on", (ISSUE / "backup.sql").read_text() + (ISSUE / "run.sh").read_text())

    def test_run_sh_does_not_sql_apply(self):
        run = (ISSUE / "run.sh").read_text()
        self.assertIn('psql_run ro', run)
        self.assertIn("apply.sh", run)
        self.assertNotIn("apply.sql", run)
        self.assertIn("REHEARSAL PASS", run)

    def test_targets_pin_one_and_seven(self):
        text = (ISSUE / "targets.sql").read_text()
        self.assertIn("f5cc62c0-3756-419e-8a3f-8e694df2e93e", text)
        self.assertIn("0 1 * * MON-FRI", text)
        self.assertIn("0 1 * * 1-5", text)
        self.assertEqual(text.count("7d90ca75-51a1-40a6-8966-8fffc9c523c3"), 1)
        self.assertIn('"n_kept":7', text)


class DryRunTest(unittest.TestCase):
    def test_apply_default_is_dry_run(self):
        src = ISSUE / "examples" / "numeric-dow-sample.yaml"
        proc = _run(["bash", str(ISSUE / "apply.sh"), "--from-yaml", str(src)])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("DRY-RUN", proc.stdout)
        self.assertIn("0 1 * * MON-FRI", proc.stdout)
        self.assertIn("no buzz workflows update sent", proc.stdout)

    def test_apply_live_refuses_without_guard(self):
        src = ISSUE / "examples" / "numeric-dow-sample.yaml"
        proc = _run(["bash", str(ISSUE / "apply.sh"), "--live", "--from-yaml", str(src), "--backup", "/tmp"])
        self.assertEqual(proc.returncode, 2)
        self.assertIn("Refusing live mutation", proc.stderr)

    def test_apply_live_refuses_blackout_window(self):
        env = dict(**{k: v for k, v in __import__("os").environ.items()})
        env["ISSUE69_I_UNDERSTAND_LIVE"] = "yes"
        env["ISSUE69_NOW_CST"] = "0859"
        src = ISSUE / "examples" / "numeric-dow-sample.yaml"
        with tempfile.TemporaryDirectory() as raw:
            evidence = Path(raw)
            (evidence / "before").mkdir()
            (evidence / "before" / "backup.json").write_text("{}")
            proc = _run(
                ["bash", str(ISSUE / "apply.sh"), "--live", "--from-yaml", str(src), "--backup", str(evidence)],
                env=env,
            )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("08:58-09:02", proc.stderr)

    def test_rollback_default_is_dry_run(self):
        src = ISSUE / "after" / "workflow.yaml"
        proc = _run(["bash", str(ISSUE / "rollback.sh"), "--from-yaml", str(src)])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("DRY-RUN", proc.stdout)


class CheckerTest(unittest.TestCase):
    def test_numeric_sample_warns_and_exits_zero(self):
        proc = _run(["python3", str(ISSUE / "check-numeric-dow.py"), str(ISSUE / "examples" / "numeric-dow-sample.yaml")])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("warnings=1", proc.stdout)
        self.assertIn("SUN,MON,TUE,WED,THU", proc.stdout)

    def test_named_sample_is_clean(self):
        proc = _run(["python3", str(ISSUE / "check-numeric-dow.py"), str(ISSUE / "examples" / "named-dow-sample.yaml")])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("warnings=0", proc.stdout)

    def test_strict_fails_on_numeric(self):
        proc = _run([
            "python3", str(ISSUE / "check-numeric-dow.py"), "--strict",
            str(ISSUE / "examples" / "numeric-dow-sample.yaml"),
        ])
        self.assertEqual(proc.returncode, 2)


class LocalPostgresOptionalTest(unittest.TestCase):
    def test_local_sql_rehearsal_if_postgres_exists(self):
        proc = _run(["bash", str(ISSUE / "test" / "local-test.sh")], cwd=ISSUE / "test")
        if proc.returncode == 77:
            self.skipTest(proc.stdout.strip() or "no initdb")
        self.assertEqual(proc.returncode, 0, proc.stdout[-2000:] + proc.stderr[-2000:])
        self.assertIn("ALL #69 SQL CHECKS PASSED", proc.stdout)


if __name__ == "__main__":
    unittest.main()
