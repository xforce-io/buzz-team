import copy
import json
import os
import plistlib
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
        self.fake.write_text(f"#!{sys.executable}\nimport json,os,sys\nif '--help' in sys.argv:\n print('--agent-command --agent-args --session-policy --agent-owner')\nelse:\n print(json.dumps({{'args':sys.argv[1:],'cwd':os.getcwd(),'home':os.getenv('GROK_HOME'),'other':os.getenv('EXAMPLE_HOME')}}))\n")
        self.fake.chmod(0o700)
        self.instructions = self.root / "instructions.md"
        self.instructions.write_text("Private instructions\n")
        self.legacy = self.root / "legacy.json"
        self.desktop_file = self.root / "managed-agents.json"
        self.app = self.root / "Buzz.app"
        (self.app / "Contents/MacOS").mkdir(parents=True)
        (self.app / "Contents/Info.plist").write_bytes(plistlib.dumps({"CFBundleExecutable": "Buzz"}))
        (self.app / "Contents/MacOS/Buzz").symlink_to(self.fake)
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
    def test_invalid_input_does_not_leave_partial_instance(self):
        fresh = self.root / "invalid-instance"
        self.old["policies"]["development"]["production_write"] = "false"
        write_json(self.legacy, self.old)
        with self.assertRaises(ValueError):
            init_legacy(fresh, self.legacy, self.desktop_file, self.app)
        self.assertFalse(fresh.exists())

    def test_prepare_refuses_live_bound_instance(self):
        prepare(self.config)
        with patch("buzz_team.desktop.live_processes", return_value=[]):
            desktop.bind(self.config)
        with patch("buzz_team.desktop.live_processes", return_value=[123]), self.assertRaises(ValueError):
            prepare(self.config)

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


class CLITests(Fixture):
    def test_symlinked_interpreted_commands_block_binding(self):
        link = self.root / "executor-link"
        link.symlink_to(self.fake)
        self.config.data["binaries"]["harness"] = str(link)
        for spec in self.config.data["adapters"].values():
            spec["command"] = str(link)
        with patch("buzz_team.desktop.subprocess.check_output", side_effect=[
                "123 /usr/bin/python3\n", f"123 /usr/bin/python3 {link} acp\n"]):
            self.assertEqual(desktop.live_processes(self.config), [123])

    def test_malformed_adapter_returns_json_not_traceback(self):
        for spec in ([], None, {"kind": "acp-command", "command": str(self.fake), "env": []}):
            with self.subTest(spec=spec):
                self.config.data["adapters"][self.config.agent(self.key)["adapter"]] = spec
                write_json(self.config.path, self.config.data)
                result = self.cli("doctor")
                self.assertEqual(result.returncode, 2)
                self.assertFalse(json.loads(result.stderr)["ok"])
                self.assertNotIn("Traceback", result.stderr)

    def test_generic_launch_cleans_existing_desktop_grok_environment(self):
        (self.base / "other").mkdir()
        self.config.data["adapters"] = {"other": {
            "kind": "acp-command", "command": str(self.fake), "home_directory": "other",
            "env": {"EXAMPLE_HOME": "{executor_home}"}}}
        self.config.data["agents"][self.key]["adapter"] = "other"
        self.config.data["compatibility"]["executor_sha256"] = {"other": digest(self.fake)}
        self.config.data["policies"]["development"]["production_write"] = True
        self.save()
        prepare(self.config)
        with patch("buzz_team.desktop.live_processes", return_value=[]):
            receipt = desktop.bind(self.config)["receipt"]
            row = json.loads(self.desktop_file.read_text())[0]
            self.assertIn("GROK_HOME", row["env_vars"])
            result = self.cli("launch", "executor", "--", "acp", **row["env_vars"])
            self.assertEqual(result.returncode, 0, result.stderr)
            output = json.loads(result.stdout)
            self.assertIsNone(output["home"])
            self.assertEqual(output["other"], str(self.base / "other"))
            desktop.rollback(self.config, Path(receipt))
        self.assert_auth_unchanged()

    def test_doctor_rejects_non_executable_adapter(self):
        executor = self.root / "adapter-no-exec"
        executor.write_text("not executable")
        for name, spec in self.config.data["adapters"].items():
            spec["command"] = str(executor)
            self.config.data["compatibility"]["executor_sha256"][name] = digest(executor)
        self.save()
        checked = self.cli("doctor")
        self.assertEqual(checked.returncode, 2)
        self.assertIn("not executable", checked.stdout)
        original = self.desktop_file.read_bytes()
        self.assertEqual(self.cli("bind").returncode, 2)
        self.assertEqual(self.desktop_file.read_bytes(), original)

    def test_doctor_rejects_invalid_app_before_binding(self):
        original = self.desktop_file.read_bytes()
        for value in (None, {"CFBundleExecutable": "missing"}, {"CFBundleExecutable": "../escape"}):
            with self.subTest(value=value):
                info = self.app / "Contents/Info.plist"
                info.write_bytes(b"invalid" if value is None else plistlib.dumps(value))
                self.assertEqual(self.cli("doctor").returncode, 2)
                self.assertEqual(self.cli("bind").returncode, 2)
                self.assertEqual(self.desktop_file.read_bytes(), original)

    def test_buzz_rejects_drift_before_metadata_or_send(self):
        self.fake.write_text("changed")
        with patch("buzz_team.buzz_cli.rewrite") as rewrite, patch("os.execv") as execute:
            with self.assertRaisesRegex(ValueError, "pinned baseline"):
                buzz_cli.run(self.config, ["messages", "send"])
            rewrite.assert_not_called()
            execute.assert_not_called()

    def test_buzz_rechecks_drift_after_metadata(self):
        def change_binary(real, args):
            self.fake.write_text("changed")
            return args
        with patch("buzz_team.buzz_cli.rewrite", side_effect=change_binary), patch("os.execv") as execute:
            with self.assertRaisesRegex(ValueError, "pinned baseline"):
                buzz_cli.run(self.config, ["messages", "send"])
            execute.assert_not_called()

    def test_orphan_executor_blocks_binding(self):
        prepare(self.config)
        original = self.desktop_file.read_bytes()
        for command in (str(self.fake), "/usr/bin/python3 " + str(self.fake)):
            with self.subTest(command=command), patch("buzz_team.desktop.subprocess.check_output",
                    return_value=f"123 {command} acp\n456 /unrelated unrelated\n"):
                self.assertEqual(desktop.live_processes(self.config), [123])
                with self.assertRaisesRegex(ValueError, "executor still running"):
                    desktop.bind(self.config)
                self.assertEqual(self.desktop_file.read_bytes(), original)

    def test_process_columns_are_not_truncated_or_double_counted(self):
        executable = str(self.app / "Contents/MacOS/Buzz")
        with patch("buzz_team.desktop.subprocess.check_output", side_effect=[
                f"123 {executable}\n", f"123 {executable} --arg\n"]) as ps:
            self.assertEqual(desktop.live_processes(self.config), [123])
            self.assertEqual(ps.call_args_list[0].args[0][-1], "pid=,comm=")
            self.assertEqual(ps.call_args_list[1].args[0][-1], "pid=,args=")

    def test_short_executor_title_scoped_to_identity_workspace(self):
        for cwd, expected in ((self.base / "workspace", [123]), (self.root, [])):
            with self.subTest(cwd=cwd), patch("buzz_team.desktop.subprocess.check_output", side_effect=[
                    "123 fake-executor\n", "", f"p123\nfcwd\nn{cwd}\n"]):
                self.assertEqual(desktop.live_processes(self.config), expected)

    def test_rollback_restores_absent_env_container_and_retains_new_values(self):
        prepare(self.config)
        for added in (False, True):
            with self.subTest(added=added), patch("buzz_team.desktop.live_processes", return_value=[]):
                rows = copy.deepcopy(self.rows)
                del rows[0]["env_vars"]
                write_json(self.desktop_file, rows)
                result = desktop.bind(self.config)
                if added:
                    current = json.loads(self.desktop_file.read_text())
                    current[0]["env_vars"]["NEW_SETTING"] = "keep"
                    write_json(self.desktop_file, current)
                desktop.rollback(self.config, Path(result["receipt"]))
                restored = json.loads(self.desktop_file.read_text())
                if added:
                    rows[0]["env_vars"] = {"NEW_SETTING": "keep"}
                self.assertEqual(restored, rows)

    def cli(self, *args, **extra_env):
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"), **extra_env)
        env.pop("BUZZ_RELAY_URL", None)
        return subprocess.run([sys.executable, "-m", "buzz_team.cli", "--instance", str(self.instance), *args],
                              cwd=self.root, env=env, capture_output=True, text=True, timeout=20)

    def test_doctor_and_status_through_cli(self):
        checked = self.cli("doctor")
        if sys.platform == "darwin":
            self.assertEqual(checked.returncode, 0, checked.stderr)
            self.assertTrue(json.loads(checked.stdout)["ok"])
        else:
            self.assertEqual(checked.returncode, 2)
            self.assertIn("Seatbelt unavailable", json.loads(checked.stdout)["errors"])
        status = self.cli("status")
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertFalse(json.loads(status.stdout)["bound"])
        self.assert_auth_unchanged()

    def test_doctor_detects_binary_drift(self):
        self.fake.write_text(self.fake.read_text() + "# changed after init\n")
        result = self.cli("doctor")
        self.assertEqual(result.returncode, 2)
        self.assertFalse(json.loads(result.stdout)["ok"])

    def test_launch_checks_pin_even_without_doctor(self):
        self.fake.write_text(self.fake.read_text() + "# changed after init\n")
        result = self.cli("launch", "executor", "--", "test", BUZZ_RUNTIME_ID=self.key)
        self.assertEqual(result.returncode, 2)
        self.assertIn("pinned baseline", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_cli_errors_are_structured_without_sensitive_values(self):
        self.config.path.write_text('["test-secret-content"]')
        result = self.cli("doctor")
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("test-secret-content", result.stderr)
        self.assertFalse(json.loads(result.stderr)["ok"])

    def test_generic_adapter_executes_without_grok_environment(self):
        spec = {"kind": "acp-command", "command": str(self.fake), "home_directory": "other",
                "env": {"EXAMPLE_HOME": "{executor_home}"}}
        (self.base / "other").mkdir()
        self.config.data["adapters"] = {"other": spec}
        self.config.data["agents"][self.key]["adapter"] = "other"
        self.config.data["compatibility"]["executor_sha256"] = {"other": digest(self.fake)}
        # Cross-platform contract test explicitly uses the unrestricted fixture policy.
        self.config.data["policies"]["development"]["production_write"] = True
        self.save()
        result = self.cli("launch", "executor", "--", "acp", "two words", BUZZ_RUNTIME_ID=self.key)
        self.assertEqual(result.returncode, 0, result.stderr)
        value = json.loads(result.stdout)
        self.assertIsNone(value["home"])
        self.assertEqual(value["other"], str(self.base / "other"))
        self.assertEqual(value["args"], ["acp", "two words"])

    def test_workspace_real_git_and_reuse_rejection(self):
        source = self.root / "git-source"
        subprocess.run(["git", "init", "-b", "main", str(source)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(source), "remote", "add", "origin", "https://github.com/example/fixture.git"], check=True)
        subprocess.run(["git", "-C", str(source), "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                        "commit", "--allow-empty", "-m", "fixture"], check=True, capture_output=True)
        self.config.data["repositories"]["fixture"] = {"source": str(source), "origin": "https://github.com/example/fixture.git"}
        self.save()
        result = self.cli("workspace", "1-cli-test", "--repo", "fixture", "--branch", "feat/1-cli-test", "--id", self.key)
        self.assertEqual(result.returncode, 0, result.stderr)
        path = Path(json.loads(result.stdout)["path"])
        self.assertTrue((path / ".git").is_file())
        retry = self.cli("workspace", "1-cli-test", "--repo", "fixture", "--id", self.key)
        self.assertEqual(retry.returncode, 2)
        self.assertIn("refusing overwrite", retry.stderr)


class BindingTests(Fixture):
    def test_optional_grok_flags_are_runtime_owned_not_binding_fields(self):
        prepare(self.config)
        for persisted in ({}, {"GROK_MEMORY": "0", "GROK_AGENT_DASHBOARD": "0"}):
            with self.subTest(persisted=persisted):
                rows = copy.deepcopy(self.rows)
                rows[0]["env_vars"].update(persisted)
                write_json(self.desktop_file, rows)
                with patch("buzz_team.desktop.live_processes", return_value=[]):
                    result = desktop.bind(self.config)
                    bound = json.loads(self.desktop_file.read_text())
                    for name in ("GROK_MEMORY", "GROK_AGENT_DASHBOARD"):
                        self.assertEqual(bound[0]["env_vars"].get(name), persisted.get(name))
                        bound[0]["env_vars"].pop(name, None)
                    write_json(self.desktop_file, bound)
                    self.assertTrue(desktop.status(self.config)["bound"])
                    self.assertEqual(desktop.bind(self.config)["changed"], 0)
                    desktop.rollback(self.config, Path(result["receipt"]))
                launched = Runtime(self.config, self.key).env({"GROK_MEMORY": "1", "GROK_AGENT_DASHBOARD": "1"})
                self.assertEqual(launched["GROK_MEMORY"], "0")
                self.assertEqual(launched["GROK_AGENT_DASHBOARD"], "0")
                self.assert_auth_unchanged()

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
