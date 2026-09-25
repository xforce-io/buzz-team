import copy
import json
import os
import plistlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from buzz_team.config import Config, identity
from buzz_team.adapters import adapter
from buzz_team.runtime import Runtime
from buzz_team.sessions import SessionStore
from buzz_team.context import ContextLedger
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
        self.fake.write_text(f"#!{sys.executable}\nimport json,os,sys\nif 'sessions' in sys.argv:\n print(sys.argv[-1])\nelif '--help' in sys.argv:\n print('--agent-command --agent-args --session-policy --agent-owner')\nelse:\n print(json.dumps({{'args':sys.argv[1:],'cwd':os.getcwd(),'home':os.getenv('GROK_HOME'),'other':os.getenv('EXAMPLE_HOME')}}))\n")
        self.fake.chmod(0o700)
        self.instructions = self.root / "instructions.md"
        self.instructions.write_text("Private instructions\n")
        self.legacy = self.root / "legacy.json"
        self.desktop_file = self.root / "managed-agents.json"
        self.app = self.root / "Buzz.app"
        (self.app / "Contents/MacOS").mkdir(parents=True)
        (self.app / "Contents/Info.plist").write_bytes(plistlib.dumps({"CFBundleExecutable": "Buzz",
            "CFBundleIdentifier": "xyz.block.buzz.app", "CFBundleShortVersionString": "0.5.25"}))
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
    def enable_business_boundary(self):
        self.config.data["policies"]["development"].update(production_write=True, data_mode="production",
                                                               write_paths=[str(self.prod)])
        self.config.data["agents"][self.key]["respond_to_allowlist"] = ["b" * 64]
        self.save()

    def test_business_boundary_requires_paired_valid_fields(self):
        self.config.data["agents"][self.key]["respond_to_allowlist"] = ["b" * 64]
        with self.assertRaisesRegex(ValueError, "configured together"):
            self.save()
        self.config.data["policies"]["development"].update(production_write=True, write_paths=[str(self.root)])
        with self.assertRaisesRegex(ValueError, "exceeds approved"):
            self.save()
        self.config.data["policies"]["development"]["write_paths"] = [str(self.prod)]
        self.config.data["agents"][self.key]["respond_to_allowlist"] = ["not-a-key"]
        with self.assertRaisesRegex(ValueError, "invalid business author"):
            self.save()
        self.config.data["agents"][self.key]["respond_to_allowlist"] = ["b" * 64]
        self.save()

    def test_business_boundary_profile_and_command(self):
        self.enable_business_boundary()
        runtime = Runtime(self.config, self.key)
        profile = runtime.profile()
        self.assertIn(str(self.base), profile)
        self.assertIn(str(self.prod), profile)
        self.assertIn("(deny file-write*", profile)
        self.assertEqual(runtime.env({"GROK_SANDBOX": "workspace"})["GROK_SANDBOX"], "off")
        with patch("buzz_team.runtime.underSeatbelt", return_value=False):
            self.assertEqual(runtime.command(["/usr/bin/true"])[0], "/usr/bin/sandbox-exec")
        with patch("buzz_team.runtime.underSeatbelt", return_value=True):
            with self.assertRaisesRegex(ValueError, "unknown Seatbelt profile"):
                runtime.command(["/usr/bin/true"])

    @unittest.skipUnless(sys.platform == "darwin", "Seatbelt requires macOS")
    def test_business_boundary_real_seatbelt_writes(self):
        self.enable_business_boundary()
        runtime = Runtime(self.config, self.key)
        allowed = self.prod / "allowed.txt"
        denied = self.root / "denied.txt"
        script = "from pathlib import Path; import sys; Path(sys.argv[1]).write_text('test')"
        for path, success in ((allowed, True), (denied, False)):
            result = subprocess.run(["/usr/bin/sandbox-exec", "-p", runtime.profile(),
                                     sys.executable, "-c", script, str(path)], capture_output=True)
            self.assertEqual(result.returncode == 0, success, result.stderr)
        self.assertTrue(allowed.exists())
        self.assertFalse(denied.exists())

    def test_instance_and_production_must_not_overlap(self):
        for production in (self.instance, self.instance / "data", self.instance.parent):
            with self.subTest(production=production):
                data = copy.deepcopy(self.config.data)
                data["production"]["data_root"] = str(production)
                with self.assertRaisesRegex(ValueError, "boundaries overlap"):
                    Config(self.instance, data=data)

    def test_init_rejects_production_overlap_without_writes(self):
        target = self.prod / "new-instance"
        with self.assertRaisesRegex(ValueError, "boundaries overlap"):
            init_legacy(target, self.legacy, self.desktop_file, self.app)
        self.assertFalse(target.exists())
        self.assert_auth_unchanged()

    def test_protected_home_must_cover_restricted_and_writer_siblings(self):
        other = identity("ws://localhost:3000", "b" * 64)
        self.config.data["policies"]["writer"] = {"production_write": True, "data_mode": "production"}
        self.config.data["agents"][other] = dict(self.config.agent(self.key), pubkey="b" * 64, policy="writer")
        self.config.data["protected_home"] = str(self.base)
        with self.assertRaisesRegex(ValueError, "entire identity state root"):
            self.save()
        self.config.data["protected_home"] = str(self.config.state)
        self.save()
        self.assertIn(str(self.config.state), Runtime(self.config, self.key).profile())

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

    def test_prepare_refuses_live_unbound_instance(self):
        with patch("buzz_team.desktop.live_processes", return_value=[123]):
            with self.assertRaisesRegex(ValueError, "Desktop is running"):
                prepare(self.config)
        self.assertFalse((self.instance / "bin/agent-harness").exists())

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
        self.assertEqual(env["GROK_SANDBOX"], "off")
        self.assertNotIn("XAI_API_KEY", env)
        self.assertEqual(r.cwd, self.base / "workspace")

    def test_development_grok_forces_sandbox_off(self):
        env = Runtime(self.config, self.key).env({"GROK_SANDBOX": "workspace"})
        self.assertEqual(env["GROK_SANDBOX"], "off")

    def test_business_grok_leaves_sandbox_unset(self):
        self.config.data["policies"]["development"]["production_write"] = True
        self.save()
        env = Runtime(self.config, self.key).env({"GROK_SANDBOX": "workspace"})
        self.assertNotIn("GROK_SANDBOX", env)

    def test_generic_adapter_does_not_set_grok_sandbox(self):
        self.config.data["adapters"] = {"other": {
            "kind": "acp-command", "command": str(self.fake), "home_directory": "other",
            "env": {"EXAMPLE_HOME": "{executor_home}"}}}
        self.config.data["agents"][self.key]["adapter"] = "other"
        self.save()
        env = Runtime(self.config, self.key).env({"GROK_SANDBOX": "workspace"})
        self.assertNotIn("GROK_SANDBOX", env)

    def test_invalid_worktree_names(self):
        runtime = Runtime(self.config, self.key)
        for task, branch in (("../escape", None), ("valid", "fix/1-test")):
            with self.assertRaises(ValueError):
                runtime.workspace(task, "anything", "HEAD", branch)

    def test_missing_sandbox_does_not_fallback(self):
        with patch("buzz_team.runtime.underSeatbelt", return_value=False), \
             patch.object(Path, "is_file", return_value=False), self.assertRaises(ValueError):
            Runtime(self.config, self.key).command(["true"])

    def test_command_inherits_when_already_confined(self):
        with patch("buzz_team.runtime.underSeatbelt", return_value=True), \
             patch.object(Path, "is_file", return_value=False):
            self.assertEqual(Runtime(self.config, self.key).command(["true"]), ["true"])

    def test_command_wraps_unconfined_development(self):
        realIsFile = Path.is_file
        def fakeIsFile(self):
            if str(self) == "/usr/bin/sandbox-exec":
                return True
            return realIsFile(self)
        with patch("buzz_team.runtime.underSeatbelt", return_value=False), \
             patch.object(Path, "is_file", fakeIsFile):
            command = Runtime(self.config, self.key).command(["true", "--flag"])
        self.assertEqual(command[0], "/usr/bin/sandbox-exec")
        self.assertEqual(command[1], "-p")
        self.assertIn("(deny file-write*", command[2])
        self.assertEqual(command[3:], ["true", "--flag"])

    def test_command_business_never_wraps(self):
        self.config.data["policies"]["development"]["production_write"] = True
        self.save()
        runtime = Runtime(self.config, self.key)
        for confined in (False, True):
            with self.subTest(confined=confined), \
                 patch("buzz_team.runtime.underSeatbelt", return_value=confined), \
                 patch.object(Path, "is_file", return_value=True):
                self.assertEqual(runtime.command(["true", "acp"]), ["true", "acp"])

    def test_under_seatbelt_false_off_darwin(self):
        from buzz_team.runtime import underSeatbelt
        if sys.platform != "darwin":
            self.assertFalse(underSeatbelt())
        with patch("buzz_team.runtime.sys.platform", "linux"), \
             patch("buzz_team.runtime.sandboxCheck") as check:
            self.assertFalse(underSeatbelt())
            check.assert_not_called()

    def test_under_seatbelt_uses_sandbox_check(self):
        from buzz_team.runtime import underSeatbelt
        with patch("buzz_team.runtime.sys.platform", "darwin"), \
             patch("buzz_team.runtime.sandboxCheck", return_value=True) as check:
            self.assertTrue(underSeatbelt())
            check.assert_called_once()

    def test_sandbox_check_reads_libsandbox(self):
        from buzz_team.runtime import sandboxCheck
        fake = MagicMock()
        fake.sandbox_check.return_value = 1
        with patch("buzz_team.runtime.ctypes.CDLL", return_value=fake) as cdll:
            self.assertTrue(sandboxCheck(99))
        cdll.assert_called_once_with("/usr/lib/libsandbox.dylib")
        fake.sandbox_check.assert_called_once()
        self.assertEqual(fake.sandbox_check.call_args.args[0], 99)
        self.assertIsNone(fake.sandbox_check.call_args.args[1])
        fake.sandbox_check.return_value = 0
        with patch("buzz_team.runtime.ctypes.CDLL", return_value=fake):
            self.assertFalse(sandboxCheck(1))
        fake.sandbox_check.return_value = -1
        with patch("buzz_team.runtime.ctypes.CDLL", return_value=fake), self.assertRaises(OSError):
            sandboxCheck(1)

    def test_probe_nested_seatbelt_apply_statuses(self):
        from buzz_team.runtime import probeNestedSeatbeltApply

        class FakeExec:
            def __init__(self, exists):
                self.exists = exists
            def is_file(self):
                return self.exists
            def __str__(self):
                return "/usr/bin/sandbox-exec"

        with patch("buzz_team.runtime.SEATBELT_EXEC", FakeExec(False)):
            self.assertEqual(probeNestedSeatbeltApply(), "missing")
        with patch("buzz_team.runtime.SEATBELT_EXEC", FakeExec(True)), \
             patch("buzz_team.runtime.subprocess.run",
                   return_value=subprocess.CompletedProcess([], 0)) as run:
            self.assertEqual(probeNestedSeatbeltApply(), "nested_ok")
            argv = run.call_args.args[0]
            self.assertEqual(argv[0], "/usr/bin/sandbox-exec")
            self.assertEqual(argv.count("/usr/bin/sandbox-exec"), 2)
        with patch("buzz_team.runtime.SEATBELT_EXEC", FakeExec(True)), \
             patch("buzz_team.runtime.subprocess.run",
                   return_value=subprocess.CompletedProcess(
                       [], 1, stderr="sandbox-exec: sandbox_apply: Operation not permitted")):
            self.assertEqual(probeNestedSeatbeltApply(), "inherit_only")
        with patch("buzz_team.runtime.SEATBELT_EXEC", FakeExec(True)), \
             patch("buzz_team.runtime.subprocess.run", side_effect=OSError("gone")):
            self.assertEqual(probeNestedSeatbeltApply(), "missing")


class CLITests(Fixture):
    def test_business_binding_sets_author_allowlist(self):
        self.config.data["policies"]["development"].update(production_write=True, data_mode="production",
                                                               write_paths=[str(self.prod)])
        self.config.data["agents"][self.key]["respond_to_allowlist"] = ["b" * 64]
        self.save()
        original = copy.deepcopy(self.rows)
        updated, changed = desktop.binding_diff(self.config, self.rows)
        self.assertEqual(self.rows, original)
        self.assertEqual(changed, 1)
        self.assertEqual(updated[0]["acp_command"], "buzz-acp")
        self.assertEqual(updated[0]["respond_to"], "allowlist")
        self.assertEqual(updated[0]["respond_to_allowlist"], ["b" * 64])

    def test_business_executor_applies_profile_from_unconfined_acp(self):
        self.config.data["policies"]["development"].update(production_write=True, data_mode="production",
                                                               write_paths=[str(self.prod)])
        self.config.data["agents"][self.key]["respond_to_allowlist"] = ["b" * 64]
        self.save()
        runtime = Runtime(self.config, self.key)
        with patch("buzz_team.runtime.underSeatbelt", return_value=False), \
             patch("os.chdir"), patch("buzz_team.runtime.runTurnGate", return_value=0) as gated:
            self.assertEqual(runtime.launch("executor", ["acp"]), 0)
        self.assertEqual(gated.call_args.args[0][:2], ["/usr/bin/sandbox-exec", "-p"])

    def test_task_launch_consumes_mapping_and_handoff_contract(self):
        task = "launch-task"
        SessionStore(self.instance).bind(community="ws://localhost:3000", identity=self.key,
                                          scope="channel-1", task_id=task,
                                          workspace=str(self.base / "workspace"), session_id="11111111-1111-4111-8111-111111111111")
        ledger = ContextLedger(self.instance, task)
        ledger.start()
        ledger.record(turn_id="turn-1", provider="provider", model="model",
                      values={"input_tokens": 1, "output_tokens": 1})
        ledger.handoff(goal="goal", next_step="next", workspace_ref="HEAD", approval_state="approved")
        runtime = Runtime(self.config, self.key)
        with self.assertRaisesRegex(ValueError, "context handoff ready"):
            runtime.launch("executor", [], task_id=task)
        with patch.object(runtime, "command", side_effect=lambda argv: argv), \
             patch("os.fork", side_effect=RuntimeError("fork-reached")):
            with self.assertRaisesRegex(RuntimeError, "fork-reached"):
                runtime.launch("executor", [], task_id=task, consume_handoff=True)
        self.assertEqual(ledger.report()["handoff"], "consumed")

    def test_task_launch_hard_stops_on_budget_exceeded(self):
        task = "budget-task"
        SessionStore(self.instance).bind(community="ws://localhost:3000", identity=self.key,
                                          scope="channel-budget", task_id=task,
                                          workspace=str(self.base / "workspace"), session_id="33333333-3333-4333-8333-333333333333")
        ledger = ContextLedger(self.instance, task)
        ledger.start(max_input_tokens=1)
        ledger.record(turn_id="turn-1", provider="provider", model="model",
                      values={"input_tokens": 2, "output_tokens": 1})
        runtime = Runtime(self.config, self.key)
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("BUZZ_WAKE_FUSE", None)
            with self.assertRaisesRegex(ValueError, "task budget exceeded"):
                runtime.launch("executor", [], task_id=task)
            self.assertEqual(os.environ.get("BUZZ_WAKE_FUSE"), "input_tokens")
        self.assertTrue(any(item.get("type") == "budget_gate" for item in ledger.report()["events"]))

    def test_launch_executor_inherits_when_already_confined(self):
        runtime = Runtime(self.config, self.key)
        with patch("buzz_team.runtime.underSeatbelt", return_value=True), \
             patch("os.chdir"), patch("buzz_team.runtime.runTurnGate", return_value=0) as gated:
            self.assertEqual(runtime.launch("executor", ["acp"]), 0)
        argv = gated.call_args.args[0]
        self.assertEqual(argv[0], str(self.fake))
        self.assertNotEqual(argv[0], "/usr/bin/sandbox-exec")
        self.assertEqual(argv[1:], ["acp"])
        self.assertEqual(gated.call_args.args[1]["GROK_SANDBOX"], "off")

    def test_launch_executor_wraps_when_unconfined(self):
        runtime = Runtime(self.config, self.key)
        realIsFile = Path.is_file
        def fakeIsFile(self):
            if str(self) == "/usr/bin/sandbox-exec":
                return True
            return realIsFile(self)
        with patch("buzz_team.runtime.underSeatbelt", return_value=False), \
             patch.object(Path, "is_file", fakeIsFile), \
             patch("os.chdir"), patch("buzz_team.runtime.runTurnGate", return_value=0) as gated:
            self.assertEqual(runtime.launch("executor", ["acp"]), 0)
        argv = gated.call_args.args[0]
        self.assertEqual(argv[0], "/usr/bin/sandbox-exec")
        self.assertEqual(argv[1], "-p")
        self.assertEqual(argv[-2:], [str(self.fake), "acp"])
        self.assertEqual(gated.call_args.args[1]["GROK_SANDBOX"], "off")

    def test_harness_launch_allows_plain_acp_without_task(self):
        self.config.data["policies"]["development"]["production_write"] = True
        self.save()
        runtime = Runtime(self.config, self.key)
        with patch.dict(os.environ, {}, clear=False):
            for name in ("BUZZ_TASK_ID", "BUZZ_TASK_SCOPE", "BUZZ_TASK_WORKSPACE",
                         "BUZZ_WAKE_SURFACE", "BUZZ_WAKE_PAYLOAD", "BUZZ_CONSUME_HANDOFF"):
                os.environ.pop(name, None)
            with patch("os.chdir"), patch("buzz_team.runtime.runTurnGate", return_value=0) as gated:
                self.assertEqual(runtime.launch("harness", ["acp"]), 0)
            env = gated.call_args.args[1]
            self.assertNotIn("BUZZ_TASK_ID", env)
            self.assertNotIn("BUZZ_TASK_SCOPE", env)
            self.assertNotIn("BUZZ_TASK_WORKSPACE", env)
            self.assertNotIn("GROK_SANDBOX", env)
        result = self.cli("launch", "harness", "--", "acp", BUZZ_RUNTIME_ID=self.key)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("requires task_id", result.stderr)
        self.assertEqual(json.loads(result.stdout)["args"], ["acp"])

    def test_harness_launch_requires_task_id_for_stream_wake(self):
        runtime = Runtime(self.config, self.key)
        with patch.dict(os.environ, {"BUZZ_WAKE_SURFACE": "stream"}, clear=False):
            os.environ.pop("BUZZ_TASK_ID", None)
            with self.assertRaisesRegex(ValueError, "requires task_id"):
                runtime.launch("harness", [])
            result = self.cli("launch", "harness", "--", "acp",
                              BUZZ_RUNTIME_ID=self.key, BUZZ_WAKE_SURFACE="stream")
            self.assertEqual(result.returncode, 2)
            self.assertIn("requires task_id", result.stderr)

    def test_harness_launch_requires_task_id_for_consume(self):
        runtime = Runtime(self.config, self.key)
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("BUZZ_TASK_ID", None)
            os.environ.pop("BUZZ_WAKE_SURFACE", None)
            with self.assertRaisesRegex(ValueError, "requires task_id"):
                runtime.launch("harness", [], consume_handoff=True)
            os.environ["BUZZ_CONSUME_HANDOFF"] = "1"
            with self.assertRaisesRegex(ValueError, "requires task_id"):
                runtime.launch("harness", [])

    def test_desktop_binding_allows_task_env(self):
        self.config.data["agents"][self.key]["binding_environment"] = {
            "BUZZ_ACP_CONFIG": str(self.root / "acp.json"),
            "BUZZ_TASK_ID": "desktop-task",
            "BUZZ_TASK_SCOPE": "channel-desktop",
        }
        (self.root / "acp.json").write_text("{}\n")
        self.save()
        with patch("buzz_team.desktop.live_processes", return_value=[]):
            prepare(self.config)
            desktop.bind(self.config)
        bound = json.loads(self.desktop_file.read_text())
        env = bound[0]["env_vars"]
        self.assertEqual(env["BUZZ_TASK_ID"], "desktop-task")
        self.assertEqual(env["BUZZ_TASK_SCOPE"], "channel-desktop")

    def test_desktop_binding_allows_wake_env(self):
        self.config.data["agents"][self.key]["binding_environment"] = {
            "BUZZ_WAKE_SURFACE": "stream",
            "BUZZ_WAKE_CHANNEL": "channel-desktop",
            "BUZZ_WAKE_POST_REF": "post-desktop",
            "BUZZ_WAKE_BODY": "@agent-one please",
        }
        self.save()
        with patch("buzz_team.desktop.live_processes", return_value=[]):
            prepare(self.config)
            desktop.bind(self.config)
        env = json.loads(self.desktop_file.read_text())[0]["env_vars"]
        self.assertEqual(env["BUZZ_WAKE_SURFACE"], "stream")
        self.assertEqual(env["BUZZ_WAKE_CHANNEL"], "channel-desktop")
        self.assertEqual(env["BUZZ_WAKE_POST_REF"], "post-desktop")
        self.assertEqual(env["BUZZ_WAKE_BODY"], "@agent-one please")

    def test_desktop_binding_rejects_unknown_wake_key(self):
        self.config.data["agents"][self.key]["binding_environment"] = {
            "BUZZ_WAKE_FUSE": "budget_exceeded",
        }
        self.save()
        with self.assertRaisesRegex(ValueError, "unsupported binding environment"):
            desktop.binding_diff(self.config, copy.deepcopy(self.rows))

    def test_apply_wake_payload_expands_allowlisted_fields(self):
        env = {
            "BUZZ_WAKE_PAYLOAD": json.dumps({
                "surface": "stream",
                "channel": "channel-payload",
                "post_ref": "post-payload",
                "body": "please look",
            }),
        }
        desktop.applyWakePayload(env)
        self.assertEqual(env["BUZZ_WAKE_SURFACE"], "stream")
        self.assertEqual(env["BUZZ_WAKE_CHANNEL"], "channel-payload")
        self.assertEqual(env["BUZZ_WAKE_POST_REF"], "post-payload")
        self.assertEqual(env["BUZZ_WAKE_BODY"], "please look")
        with self.assertRaisesRegex(ValueError, "invalid wake payload"):
            desktop.applyWakePayload({"BUZZ_WAKE_PAYLOAD": json.dumps({"channel_id": "invented"})})

    def test_desktop_identity_and_version_fail_closed(self):
        original = self.desktop_file.read_bytes()
        info_path = self.app / "Contents/Info.plist"
        baseline = plistlib.loads(info_path.read_bytes())
        for field, value in (("CFBundleIdentifier", "example.other.app"),
                             ("CFBundleShortVersionString", "9.9.9")):
            with self.subTest(field=field):
                info_path.write_bytes(plistlib.dumps(dict(baseline, **{field: value})))
                for command in ("doctor", "bind", "start"):
                    result = self.cli(command)
                    self.assertEqual(result.returncode, 2)
                    self.assertFalse(json.loads(result.stderr or result.stdout)["ok"])
                self.assertEqual(self.desktop_file.read_bytes(), original)

    def test_init_rejects_non_object_inventory_environment(self):
        for value in ([], ["item"], "invalid", 42, None, False):
            with self.subTest(value=value):
                rows = copy.deepcopy(self.rows)
                rows[0]["env_vars"] = value
                write_json(self.desktop_file, rows)
                target = self.root / "new-instance"
                result = self.cli("--instance", str(target), "init", "--legacy", str(self.legacy),
                                  "--desktop-config", str(self.desktop_file), "--app", str(self.app))
                self.assertEqual(result.returncode, 2)
                self.assertFalse(json.loads(result.stderr)["ok"])
                self.assertNotIn("Traceback", result.stderr)
                self.assertFalse(target.exists())
                self.assertEqual(json.loads(self.desktop_file.read_text()), rows)

    def test_invalid_compatibility_maps_return_json_before_binding(self):
        original = self.desktop_file.read_bytes()
        baseline = copy.deepcopy(self.config.data)
        for name in ("sha256", "executor_sha256"):
            for value in ([], None, "invalid", 1, False):
                with self.subTest(name=name, value=value):
                    data = copy.deepcopy(baseline)
                    data["compatibility"][name] = value
                    write_json(self.config.path, data)
                    for command in ("doctor", "bind"):
                        result = self.cli(command)
                        self.assertEqual(result.returncode, 2)
                        self.assertFalse(json.loads(result.stderr)["ok"])
                        self.assertNotIn("Traceback", result.stderr)
                    self.assertEqual(self.desktop_file.read_bytes(), original)

    def test_invalid_policy_objects_return_json_without_changing_binding(self):
        original = self.desktop_file.read_bytes()
        baseline = copy.deepcopy(self.config.data)
        for name in ("development", "unused"):
            for value in ([], None, "invalid", 1, False):
                with self.subTest(name=name, value=value):
                    data = copy.deepcopy(baseline)
                    data["policies"][name] = value
                    write_json(self.config.path, data)
                    for command in ("doctor", "bind"):
                        result = self.cli(command)
                        self.assertEqual(result.returncode, 2)
                        self.assertFalse(json.loads(result.stderr)["ok"])
                        self.assertNotIn("Traceback", result.stderr)
                    self.assertEqual(self.desktop_file.read_bytes(), original)
                    self.assertFalse((self.instance / "backups").exists())

    def test_credential_environment_is_rejected_before_binding(self):
        original = self.desktop_file.read_bytes()
        baseline = copy.deepcopy(self.config.data)
        name = self.config.agent(self.key)["adapter"]
        for kind in ("grok", "acp-command"):
            for variable in ("XAI_API_KEY", "GROK_CODE_XAI_API_KEY"):
                for section in ("adapter", "data"):
                    with self.subTest(kind=kind, variable=variable, section=section):
                        data = copy.deepcopy(baseline)
                        data["adapters"][name]["kind"] = kind
                        if section == "adapter":
                            data["adapters"][name]["env"] = {variable: "test-only-secret"}
                        else:
                            data["data_environment"][variable] = {"test": "test-only-secret"}
                        write_json(self.config.path, data)
                        for command in ("doctor", "bind"):
                            result = self.cli(command)
                            self.assertEqual(result.returncode, 2)
                            self.assertFalse(json.loads(result.stderr)["ok"])
                            self.assertNotIn("test-only-secret", result.stdout + result.stderr)
                        self.assertEqual(self.desktop_file.read_bytes(), original)
                        self.assertFalse((self.instance / "backups").exists())

    def test_invalid_adapter_environment_cannot_change_binding(self):
        original = self.desktop_file.read_bytes()
        name = self.config.agent(self.key)["adapter"]
        for env in ({"EXAMPLE": "bad\0value"}, {"CARGO_HOME": "/ignored"}, {"UV_CACHE_DIR": "/ignored"}):
            with self.subTest(env=env):
                self.config.data["adapters"][name]["env"] = env
                write_json(self.config.path, self.config.data)
                for command in ("doctor", "bind"):
                    result = self.cli(command)
                    self.assertEqual(result.returncode, 2)
                    self.assertFalse(json.loads(result.stderr)["ok"])
                self.assertEqual(self.desktop_file.read_bytes(), original)

    def test_symlinked_interpreted_commands_block_binding(self):
        link = self.root / "executor-link"
        link.symlink_to(self.fake)
        self.config.data["binaries"]["harness"] = str(link)
        for spec in self.config.data["adapters"].values():
            spec["command"] = str(link)
        with patch("buzz_team.desktop.subprocess.check_output", side_effect=[
                "123 /usr/bin/python3\n", f"123 /usr/bin/python3 {link} acp\n", ""]):
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
                f"123 {executable}\n", f"123 {executable} --arg\n", ""]) as ps:
            self.assertEqual(desktop.live_processes(self.config), [123])
            self.assertEqual(ps.call_args_list[0].args[0][-1], "pid=,comm=")
            self.assertEqual(ps.call_args_list[1].args[0][-1], "pid=,args=")

    def test_desktop_builtin_acp_command_is_resolved_for_process_guard(self):
        rows = json.loads(self.desktop_file.read_text())
        rows[0]["acp_command"] = "buzz-acp"
        self.desktop_file.write_text(json.dumps(rows))
        builtin = str(self.app / "Contents/MacOS/buzz-acp")
        with patch("buzz_team.desktop.subprocess.check_output", side_effect=[
                f"123 {builtin}\n", f"123 {builtin}\n", ""]):
            self.assertEqual(desktop.live_processes(self.config), [123])

        rows[0]["acp_command"] = "unknown-relative-command"
        self.desktop_file.write_text(json.dumps(rows))
        with patch("buzz_team.desktop.subprocess.check_output", return_value=""):
            with self.assertRaisesRegex(ValueError, "absolute path"):
                desktop.live_processes(self.config)

    def test_short_executor_title_scoped_to_identity_workspace(self):
        for cwd, expected in ((self.base / "workspace", [123]), (self.root, [])):
            with self.subTest(cwd=cwd), patch("buzz_team.desktop.subprocess.check_output", side_effect=[
                    "123 fake-executor\n", "", f"p123\nfcwd\nn{cwd}\n"]):
                self.assertEqual(desktop.live_processes(self.config), expected)

    def test_old_binding_command_survives_adapter_removal(self):
        original = self.desktop_file.read_bytes()
        with patch("buzz_team.desktop.subprocess.check_output", side_effect=[
                "123 /usr/bin/python3\n", "123 /usr/bin/python3 /old/executor acp\n", ""]):
            with self.assertRaisesRegex(ValueError, "still running"):
                desktop.bind(self.config)
        self.assertEqual(self.desktop_file.read_bytes(), original)

    def test_unknown_old_executor_in_identity_workspace_blocks_binding(self):
        original = self.desktop_file.read_bytes()
        with patch("buzz_team.desktop.subprocess.check_output", side_effect=[
                "123 renamed-old-agent\n", "123 renamed-old-agent\n",
                f"p123\nfcwd\nn{self.base / 'workspace'}\np456\nfcwd\nn{self.root}\n"]):
            with self.assertRaisesRegex(ValueError, "still running"):
                desktop.bind(self.config)
        self.assertEqual(self.desktop_file.read_bytes(), original)

    def test_invalid_data_environment_rejected_before_binding(self):
        original = self.desktop_file.read_bytes()
        for value in ([], None, {"EXAMPLE": []}, {"EXAMPLE": {"production": "path"}},
                      {"EXAMPLE": {"test": 12}}, {"EXAMPLE": {"test": "bad\0value"}},
                      {"EXAMPLE": {"test": "ok", "other": "bad"}}, {"PATH": {"test": "/bad"}}):
            with self.subTest(value=value):
                self.config.data["data_environment"] = value
                write_json(self.config.path, self.config.data)
                for command in ("doctor", "bind"):
                    result = self.cli(command)
                    self.assertEqual(result.returncode, 2)
                    self.assertFalse(json.loads(result.stderr)["ok"])
                    self.assertNotIn("Traceback", result.stderr)
                self.assertEqual(self.desktop_file.read_bytes(), original)

    def test_data_environment_valid_modes_expand_on_launch(self):
        self.config.data["data_environment"] = {"EXAMPLE": {"test": "{identity_root}/test-data"}}
        self.save()
        self.assertEqual(Runtime(self.config, self.key).env({})["EXAMPLE"], str(self.base / "test-data"))

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
        subprocess.run(["git", "-C", str(source), "remote", "add", "origin", "https://git.example.invalid/fixture.git"], check=True)
        subprocess.run(["git", "-C", str(source), "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                        "commit", "--allow-empty", "-m", "fixture"], check=True, capture_output=True)
        self.config.data["repositories"]["fixture"] = {"source": str(source), "origin": "https://git.example.invalid/fixture.git"}
        self.save()
        result = self.cli("workspace", "1-cli-test", "--repo", "fixture", "--branch", "feat/1-cli-test", "--id", self.key)
        self.assertEqual(result.returncode, 0, result.stderr)
        path = Path(json.loads(result.stdout)["path"])
        self.assertTrue((path / ".git").is_file())
        retry = self.cli("workspace", "1-cli-test", "--repo", "fixture", "--id", self.key)
        self.assertEqual(retry.returncode, 2)
        self.assertIn("refusing overwrite", retry.stderr)

    def test_task_session_cli_is_stable_and_conflict_safe(self):
        common = ("--community", "ws://localhost:3000", "--identity", self.key,
                  "--scope", "channel-1", "--workspace", str(self.base / "workspace"))
        for task, session in (("task-a", "11111111-1111-4111-8111-111111111111"), ("task-b", "22222222-2222-4222-8222-222222222222")):
            result = self.cli("session", "bind", "--task", task, *common, "--session", session)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("session_ref", json.loads(result.stdout))
        resolved = self.cli("session", "resolve", "--task", "task-a", *common)
        self.assertEqual(resolved.returncode, 0, resolved.stderr)
        self.assertIn("session_ref", json.loads(resolved.stdout))
        conflict = self.cli("session", "bind", "--task", "task-a", *common, "--session", "33333333-3333-4333-8333-333333333333")
        self.assertEqual(conflict.returncode, 2)
        self.assertIn("conflict", conflict.stderr)
        listed = self.cli("session", "list")
        self.assertEqual(listed.returncode, 0, listed.stderr)
        self.assertEqual(len(json.loads(listed.stdout)["bindings"]), 2)
        self.assertTrue(all(set(row) == {"task_ref", "session_ref", "state"}
                            for row in json.loads(listed.stdout)["bindings"]))

    def test_context_cli_requires_session_and_preserves_handoff_safety(self):
        common = ("--community", "ws://localhost:3000", "--identity", self.key,
                  "--scope", "channel-context", "--workspace", str(self.base / "workspace"))
        missing = self.cli("context", "start", "--task", "task-context")
        self.assertEqual(missing.returncode, 2)
        self.assertIn("session mapping not found", missing.stderr)
        bound = self.cli("session", "bind", "--task", "task-context", *common, "--session", "22222222-2222-4222-8222-222222222222")
        self.assertEqual(bound.returncode, 0, bound.stderr)
        started = self.cli("context", "start", "--task", "task-context", "--max-context-tokens", "100")
        self.assertEqual(started.returncode, 0, started.stderr)
        recorded = self.cli("context", "record", "--task", "task-context", "--turn", "turn-1",
                            "--provider", "test", "--model", "test-model", "--input-tokens", "20",
                            "--output-tokens", "5", "--context-tokens", "50")
        self.assertEqual(recorded.returncode, 0, recorded.stderr)
        rejected = self.cli("context", "handoff", "--task", "task-context", "--goal", "goal",
                            "--next-step", "next", "--workspace-ref", "HEAD", "--approval-state", "approved",
                            "--open-tool-calls", "1")
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("open tool calls", rejected.stderr)
        handoff = self.cli("context", "handoff", "--task", "task-context", "--goal", "goal",
                           "--next-step", "next", "--workspace-ref", "HEAD", "--approval-state", "approved",
                           "--fact", "verified", "--constraint", "preserve behavior")
        self.assertEqual(handoff.returncode, 0, handoff.stderr)
        report = self.cli("context", "report", "--task", "task-context")
        self.assertEqual(report.returncode, 0, report.stderr)
        self.assertEqual(json.loads(report.stdout)["handoff"], "available")
        restored = self.cli("context", "restore", "--task", "task-context")
        self.assertEqual(restored.returncode, 0, restored.stderr)
        self.assertEqual(json.loads(restored.stdout)["goal"], "goal")


class BindingTests(Fixture):
    def test_crlf_desktop_configuration_can_rollback(self):
        prepare(self.config)
        self.desktop_file.write_bytes(json.dumps(self.rows, indent=2).replace("\n", "\r\n").encode())
        with patch("buzz_team.desktop.live_processes", return_value=[]):
            result = desktop.bind(self.config)
            receipt = Path(result["receipt"])
            self.assertEqual(json.loads(receipt.read_text())["before_sha256"],
                             digest(receipt.parent / "managed-agents.before.json"))
            desktop.rollback(self.config, receipt)
        self.assertEqual(json.loads(self.desktop_file.read_text()), self.rows)
        self.assert_auth_unchanged()

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
                    self.assertNotIn("GROK_SANDBOX", bound[0]["env_vars"])
                    for name in ("GROK_MEMORY", "GROK_AGENT_DASHBOARD"):
                        self.assertEqual(bound[0]["env_vars"].get(name), persisted.get(name))
                        bound[0]["env_vars"].pop(name, None)
                    write_json(self.desktop_file, bound)
                    self.assertTrue(desktop.status(self.config)["bound"])
                    self.assertEqual(desktop.bind(self.config)["changed"], 0)
                    desktop.rollback(self.config, Path(result["receipt"]))
                launched = Runtime(self.config, self.key).env({
                    "GROK_MEMORY": "1", "GROK_AGENT_DASHBOARD": "1", "GROK_SANDBOX": "workspace"})
                self.assertEqual(launched["GROK_MEMORY"], "0")
                self.assertEqual(launched["GROK_AGENT_DASHBOARD"], "0")
                self.assertEqual(launched["GROK_SANDBOX"], "off")
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

    def test_reactions_and_unknown_commands_pass_through(self):
        event = "c" * 64
        reactions = ["reactions", "add", "--event", event, "--emoji", "👀"]
        self.assertEqual(buzz_cli.rewrite("/fake", reactions), reactions)
        unknown = ["whatever", "cmd", "--reply-to", "root"]
        self.assertEqual(buzz_cli.rewrite("/fake", unknown), unknown)


@unittest.skipUnless(sys.platform == "darwin", "macOS kernel integration; run on migration host")
class KernelTests(Fixture):
    def test_control_files_outside_home_are_write_protected(self):
        prepare(self.config)
        self.config.data["protected_home"] = str(self.config.state)
        self.save()
        package = self.root / "external-code" / "buzz_team"
        package.mkdir(parents=True)
        module = package / "runtime.py"
        module.write_text("test-only code")
        installation = self.root / "external-install"
        installation.mkdir()
        installed = installation / "installed-marker"
        installed.write_text("original")
        link = self.root / "install-link"
        link.symlink_to(installation, target_is_directory=True)
        targets = [self.config.path, self.instance / "bin/agent-executor", module, installed,
                   self.desktop_file, self.fake]
        original = {path: path.read_bytes() for path in targets}
        runtime = Runtime(self.config, self.key)
        with patch("buzz_team.runtime.__file__", str(module)), patch("buzz_team.runtime.sys.prefix", str(link)):
            command = runtime.command([sys.executable, "-c", f'''
from pathlib import Path
for name in {[str(p) for p in targets]!r}:
 try: Path(name).write_text('bad')
 except PermissionError: pass
 else: raise AssertionError('control file writable: ' + name)
for name in {[str(self.instance), str(package), str(link)]!r}:
 try: Path(name).rename(name + '-moved')
 except PermissionError: pass
 else: raise AssertionError('control path replaceable: ' + name)
Path({str(runtime.cwd / 'allowed-control-test')!r}).write_text('ok')
'''])
        result = subprocess.run(command, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        for path, value in original.items():
            self.assertEqual(path.read_bytes(), value)
        self.assertTrue(link.is_symlink())
        self.assert_auth_unchanged()

    def test_production_root_outside_home_is_always_write_protected(self):
        self.config.data["protected_home"] = str(self.config.state)
        self.config.data["production"]["protected_paths"] = []
        self.save()
        target = self.prod / "keep"
        target.write_text("original")
        runtime = Runtime(self.config, self.key)
        result = subprocess.run(runtime.command([sys.executable, "-c",
            f"from pathlib import Path; Path({str(target)!r}).write_text('bad')"]),
            capture_output=True, text=True, timeout=20)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(target.read_text(), "original")

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

    def test_already_confined_launch_does_not_rewrap(self):
        runtime = Runtime(self.config, self.key)
        root = str(Path(__file__).resolve().parents[1] / "src")
        inner = (
            "from buzz_team.runtime import Runtime, underSeatbelt\n"
            "from buzz_team.config import Config\n"
            "from pathlib import Path\n"
            "assert underSeatbelt()\n"
            f"cmd = Runtime(Config(Path({str(self.instance)!r})), {self.key!r}).command(['/usr/bin/true'])\n"
            "assert cmd == ['/usr/bin/true'], cmd\n"
            "print('inherited')\n"
        )
        result = subprocess.run(
            runtime.command([sys.executable, "-c", inner]),
            capture_output=True, text=True, timeout=20,
            env=dict(os.environ, PYTHONPATH=root))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("inherited", result.stdout)

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
