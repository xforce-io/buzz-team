import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from buzz_team.config import Config, identity
from buzz_team.adapters import adapter
from buzz_team.runtime import Runtime
from buzz_team.instance import init_legacy, prepare, digest, write_json
from buzz_team import desktop, buzz_cli


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.instance = self.root / "instance with spaces"
        self.key = identity("ws://localhost:3000", "a" * 64)
        self.base = self.root / "states" / self.key
        for name in ("grok", "workspace", "tmp", "cache", "test-data", "repos", "worktrees"):
            (self.base / name).mkdir(parents=True)
        (self.base / "grok/auth.json").write_text('{"test-only":"never-copy-me"}')
        (self.base / "grok/config.toml").write_text("# retain original configuration\n")
        self.auth_digest = digest(self.base / "grok/auth.json")
        self.auth_inode = (self.base / "grok/auth.json").stat().st_ino
        self.prod = self.root / "production"
        self.prod.mkdir()
        self.fake = self.root / "fake-executor"
        self.fake.write_text(f"#!{sys.executable}\nimport json,os,sys\nprint(json.dumps({{'args':sys.argv[1:],'cwd':os.getcwd(),'home':os.getenv('GROK_HOME')}}))\n")
        self.fake.chmod(0o700)
        self.instructions = self.root / "instructions.md"
        self.instructions.write_text("Private instructions\n")
        self.legacy = self.root / "legacy.json"
        self.desktop_file = self.root / "managed-agents.json"
        self.app = self.root / "Buzz.app"
        self.rows = [{"pubkey": "a" * 64, "relay_url": "ws://localhost:3000", "system_prompt": "private prompt",
                      "private_key": "test-only-secret", "acp_command": "/old/harness", "agent_command": "/old/executor",
                      "env_vars": {"GROK_HOME": str(self.base / "grok"), "BUZZ_ACP_SESSION_POLICY": "channel"}}]
        write_json(self.desktop_file, self.rows)
        self.old = {"version": 1, "state_root": str(self.root / "states"), "protected_home": str(self.root),
                    "production": {"data_root": str(self.prod), "protected_paths": [str(self.prod)], "blocked_ports": []},
                    "binaries": {"buzz": str(self.fake), "harness": str(self.fake), "grok": str(self.fake)},
                    "agents": {self.key: {"pubkey": "a" * 64, "relay_url": "ws://localhost:3000", "policy": "development",
                                            "instructions": str(self.instructions)}},
                    "policies": {"development": {"production_write": False, "data_mode": "test"}}, "repositories": {},
                    "credential_sources": {"auth.json": str(self.base / "grok/auth.json")}}
        write_json(self.legacy, self.old)
        init_legacy(self.instance, self.legacy, self.desktop_file, self.app)
        self.config = Config(self.instance)

    def save(self):
        write_json(self.config.path, self.config.data)
        self.config = Config(self.instance)

    def assert_auth_unchanged(self):
        self.assertEqual(digest(self.base / "grok/auth.json"), self.auth_digest)
        self.assertEqual((self.base / "grok/auth.json").stat().st_ino, self.auth_inode)
        self.assertFalse(list(self.instance.rglob("auth.json")))


class ConfigurationTests(Fixture):
    def test_conversion_preserves_auth_and_state(self):
        self.assertEqual(self.config.state, self.root / "states")
        self.assertNotIn("credential_sources", self.config.data)
        self.assertNotEqual(self.config.agent(self.key)["instructions"], str(self.instructions))
        self.assert_auth_unchanged()
        self.assertEqual(json.loads(self.legacy.read_text()), self.old)

    def test_init_refuses_overwrite(self):
        with self.assertRaises(ValueError):
            init_legacy(self.instance, self.legacy, self.desktop_file, self.app)

    def test_identity_and_policy_fail_closed(self):
        with self.assertRaises(ValueError):
            Runtime(self.config, "unknown")
        with self.assertRaises(ValueError):
            Runtime(self.config, self.key).env({"BUZZ_RELAY_URL": "ws://elsewhere"})
        self.config.data["policies"]["development"]["production_write"] = "false"
        with self.assertRaises(ValueError):
            self.save()

    def test_unknown_adapter_fails(self):
        with self.assertRaises(ValueError):
            adapter({"kind": "made-up"})

    def test_generic_acp_is_not_grok(self):
        other = adapter({"kind": "acp-command", "command": str(self.fake), "home_directory": "other",
                         "env": {"EXAMPLE_HOME": "{executor_home}"}})
        other.validate()
        env = other.environment(self.base, self.base / "workspace")
        self.assertEqual(env["EXAMPLE_HOME"], str(self.base / "other"))
        self.assertNotIn("GROK_HOME", env)
        self.assertNotIn("existing-session-store", other.capabilities)

    def test_adapter_cannot_override_runtime(self):
        for name in ("BUZZ_RUNTIME_ID", "PATH", "HOME", "PYTHONPATH"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                adapter({"kind": "acp-command", "command": str(self.fake), "env": {name: "bad"}}).validate()

    def test_prepare_is_thin_and_auth_preserving(self):
        prepare(self.config)
        for launcher in (self.instance / "bin").iterdir():
            self.assertLess(len(launcher.read_text()), 600)
            self.assertIn("-m buzz_team.cli", launcher.read_text())
            self.assertNotIn("legacy", launcher.read_text())
        self.assert_auth_unchanged()

    def test_env_cwd_and_production_policy(self):
        r = Runtime(self.config, self.key)
        env = r.env({"PATH": "/usr/bin", "KAIRO_SERVE_ROOT": "wrong", "XAI_API_KEY": "test-secret"})
        self.assertEqual(env["KAIRO_SERVE_ROOT"], str(self.base / "test-data"))
        self.assertEqual(env["GROK_HOME"], str(self.base / "grok"))
        self.assertNotIn("XAI_API_KEY", env)
        self.assertEqual(r.cwd, self.base / "workspace")

    def test_invalid_worktree_names(self):
        runtime = Runtime(self.config, self.key)
        for task, branch in (("../escape", None), ("valid", "fix/1-test")):
            with self.assertRaises(ValueError):
                runtime.workspace(task, "anything", "HEAD", branch)

    def test_missing_sandbox_does_not_fallback(self):
        with patch.object(Path, "is_file", return_value=False), self.assertRaises(ValueError):
            Runtime(self.config, self.key).command(["true"])


class BindingTests(Fixture):
    def test_bind_and_rollback_no_secret_or_auth_mutation(self):
        prepare(self.config)
        before = self.desktop_file.read_bytes()
        with patch("buzz_team.desktop.live_processes", return_value=[]):
            result = desktop.bind(self.config)
            self.assertEqual(result["changed"], 1)
            after = json.loads(self.desktop_file.read_text())
            self.assertEqual(after[0]["private_key"], self.rows[0]["private_key"])
            self.assertEqual(after[0]["system_prompt"], self.rows[0]["system_prompt"])
            self.assertEqual(after[0]["env_vars"]["BUZZ_ACP_SESSION_POLICY"], "channel")
            self.assertEqual(desktop.bind(self.config)["changed"], 0)
            self.assertTrue(desktop.rollback(self.config, Path(result["receipt"]))["restored"])
        self.assertEqual(self.desktop_file.read_bytes(), before)
        self.assertNotIn("test-only-secret", json.dumps(result))
        self.assert_auth_unchanged()

    def test_live_process_refuses_binding(self):
        with patch("buzz_team.desktop.live_processes", return_value=[123]), self.assertRaises(ValueError):
            desktop.bind(self.config)

    def test_reject_duplicate_and_missing_identity(self):
        for rows in ([], self.rows * 2):
            with self.assertRaises(ValueError):
                desktop.binding_diff(self.config, rows)

    def test_reject_different_executor_home(self):
        rows = copy.deepcopy(self.rows)
        rows[0]["env_vars"]["GROK_HOME"] = "/other/home"
        with self.assertRaises(ValueError):
            desktop.binding_diff(self.config, rows)

    def test_rollback_protects_new_changes(self):
        prepare(self.config)
        with patch("buzz_team.desktop.live_processes", return_value=[]):
            result = desktop.bind(self.config)
            rows = json.loads(self.desktop_file.read_text())
            rows[0]["agent_command"] = "/another/new/executor"
            write_json(self.desktop_file, rows)
            with self.assertRaises(ValueError):
                desktop.rollback(self.config, Path(result["receipt"]))

    def test_rollback_preserves_desktop_metadata_updates(self):
        prepare(self.config)
        with patch("buzz_team.desktop.live_processes", return_value=[]):
            result = desktop.bind(self.config)
            rows = json.loads(self.desktop_file.read_text())
            rows[0]["updated_at"] = "newer-desktop-timestamp"
            rows[0]["env_vars"]["UNRELATED"] = "new-value"
            write_json(self.desktop_file, rows)
            desktop.rollback(self.config, Path(result["receipt"]))
        restored = json.loads(self.desktop_file.read_text())[0]
        self.assertEqual(restored["updated_at"], "newer-desktop-timestamp")
        self.assertEqual(restored["env_vars"]["UNRELATED"], "new-value")
        self.assertEqual(restored["agent_command"], "/old/executor")
        self.assert_auth_unchanged()


class ReplyTests(unittest.TestCase):
    def test_dm_and_channel_forms(self):
        for prefix in ([], ["--format", "compact"], ["--format=compact"], ["--auth-tag", "test-only"]):
            for reply in (["--reply-to", "root"], ["--reply-to=root"]):
                args = prefix + ["messages", "send", "--channel", "channel-id", *reply, "--content", "-"]
                with patch("subprocess.check_output", return_value='{"channel_type":"dm"}'):
                    self.assertFalse(any(x.startswith("--reply-to") for x in buzz_cli.rewrite("/fake", args)))
                with patch("subprocess.check_output", return_value='{"channel_type":"stream"}'):
                    self.assertEqual(buzz_cli.rewrite("/fake", args), args)

    def test_no_send_on_failed_metadata(self):
        args = ["messages", "send", "--channel", "id", "--reply-to", "root"]
        for raw in ("[]", "{}", "invalid"):
            with patch("subprocess.check_output", return_value=raw), self.assertRaises(ValueError):
                buzz_cli.rewrite("/fake", args)


@unittest.skipUnless(sys.platform == "darwin", "macOS kernel integration; run on migration host")
class KernelTests(Fixture):
    def test_real_kernel_write_boundary_and_child(self):
        runtime = Runtime(self.config, self.key)
        target = self.prod / "keep"
        target.write_text("original")
        (runtime.cwd / "alias").symlink_to(self.prod, target_is_directory=True)
        code = f'''from pathlib import Path
import subprocess,sys
Path({str(runtime.cwd / 'allowed')!r}).write_text('ok')
for name in [{str(target)!r}, {str(runtime.cwd / 'alias/keep')!r}, {str(self.instance / 'bad')!r}]:
 try: Path(name).write_text('bad')
 except PermissionError: pass
 else: raise AssertionError('write escaped')
r=subprocess.run([sys.executable,'-c',"from pathlib import Path;Path({str(target)!r}).write_text('bad')"],capture_output=True)
assert r.returncode != 0
'''
        result = subprocess.run(runtime.command([sys.executable, "-c", code]), capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(target.read_text(), "original")

    def test_real_launcher_preserves_arguments_and_home(self):
        prepare(self.config)
        root = str(Path(__file__).resolve().parents[1] / "src")
        env = dict(os.environ, PYTHONPATH=root, BUZZ_RUNTIME_ID=self.key)
        env.pop("BUZZ_RELAY_URL", None)
        result = subprocess.run([str(self.instance / "bin/agent-executor"), "acp", "--test", "two words"],
                                env=env, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["args"], ["acp", "--test", "two words"])
        self.assertEqual(data["home"], str(self.base / "grok"))
        self.assertEqual(data["cwd"], str(self.base / "workspace"))
        self.assert_auth_unchanged()


if __name__ == "__main__":
    unittest.main()
