import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from buzz_team import thin


class ThinLauncherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.identity = self.root / "state" / "identity"
        self.home = self.identity / "grok"
        self.cwd = self.identity / "workspace"
        self.home.mkdir(parents=True)
        self.cwd.mkdir()
        for child in ("tmp", "cache", "cache/uv", "cache/cargo", "cache/npm"):
            (self.identity / child).mkdir(parents=True, exist_ok=True)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        (self.bin / "grok").write_text("#!/bin/sh\n")
        (self.bin / "grok").chmod(0o700)
        self.policy = self.root / "policy.json"
        self.env = {"BUZZ_TEAM_POLICY_PATH": str(self.policy), "GROK_HOME": str(self.home),
                    "GROK_ACP_CWD": str(self.cwd), "PATH": str(self.bin)}
        self.seatbelt = self.root / "sandbox-exec"
        self.seatbelt.write_text("")

    def save(self, mode="development", paths=None):
        self.policy.write_text(json.dumps({"version": 1, "grok_home": str(self.home),
                                           "grok_executable": str(self.bin / "grok"),
                                           "mode": mode, "write_paths": paths or []}))

    def command(self, args=None):
        with patch.object(thin, "SEATBELT", self.seatbelt):
            return thin.command(self.env, args or ["--", "agent", "--always-approve"])

    def test_development_policy_execs_grok_with_original_args(self):
        self.save()
        argv, env, cwd = self.command()
        self.assertEqual(argv[0], str(self.seatbelt))
        self.assertEqual(argv[-3:], [str((self.bin / "grok").resolve()), "agent", "--always-approve"])
        self.assertIn(str(self.identity), argv[2])
        self.assertEqual(env["GROK_SANDBOX"], "off")
        self.assertEqual(env["TMPDIR"], str(self.identity.resolve() / "tmp") + "/")
        self.assertEqual(cwd, self.cwd.resolve())

    def test_business_policy_limits_writes(self):
        production = self.root / "production"
        production.mkdir()
        self.save("business", [str(production)])
        argv, _, _ = self.command()
        self.assertIn(str(production), argv[2])
        self.assertIn("deny file-write*", argv[2])

    def test_business_without_production_write_does_not_expand_boundary(self):
        self.save("business")
        argv, _, _ = self.command()
        self.assertIn(str(self.identity.resolve()), argv[2])
        self.assertNotIn(str((self.root / "production").resolve()), argv[2])

    def test_rejects_policy_in_writable_root(self):
        self.env["BUZZ_TEAM_POLICY_PATH"] = str(self.identity / "policy.json")
        self.policy = Path(self.env["BUZZ_TEAM_POLICY_PATH"])
        self.save()
        with self.assertRaisesRegex(ValueError, "overlaps writable"):
            self.command()

    def test_rejects_identity_mismatch_and_missing_sandbox(self):
        self.save()
        self.env["GROK_HOME"] = str(self.root)
        with self.assertRaisesRegex(ValueError, "different Grok home"):
            self.command()
        self.env["GROK_HOME"] = str(self.home)
        with patch.object(thin, "SEATBELT", self.root / "missing"):
            with self.assertRaisesRegex(ValueError, "Seatbelt unavailable"):
                thin.command(self.env, ["agent"])

    def test_rejects_production_write_in_development_and_wrong_command(self):
        production = self.root / "production"
        production.mkdir()
        self.save("development", [str(production)])
        with self.assertRaisesRegex(ValueError, "development policy"):
            self.command()
        self.save()
        with self.assertRaisesRegex(ValueError, "invalid Grok argument"):
            self.command(["auth"])


if __name__ == "__main__":
    unittest.main()
