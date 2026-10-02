"""Issue #58: ~/lab/buzz entries (bin/buzz gate, bin/buzz-health, apply/rollback)."""
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
ISSUE = ROOT / "docs" / "issue-58"
LOCAL = "ws://127.0.0.1:3000"
THIN = "/opt/thin/bin/buzz-team-thin"


def load_health():
    loader = importlib.machinery.SourceFileLoader("issue58_buzz_health", str(ISSUE / "bin" / "buzz-health"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


health = load_health()


def completed(returncode=0, stdout="", stderr=""):
    return types.SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


class Fixture:
    """Inventory shaped like the live one: definitions, yuanbao rows, local seats."""

    def __init__(self, root: Path, seats=("alpha", "beta", "gamma")):
        self.root = root
        self.policies = root / "policies"
        self.harnesses = root / "custom_harnesses"
        self.policies.mkdir()
        self.harnesses.mkdir()
        (self.harnesses / "seatbelt.json").write_text(json.dumps({"id": "seatbelt", "command": THIN}))
        self.seats = list(seats)
        rows = []
        for seat in self.seats:  # definition rows carry the policy
            rows.append({"name": seat, "slug": f"slug-{seat}", "acp_command": "buzz-acp", "agent_command": "",
                         "pubkey": "", "relay_url": "", "runtime": "seatbelt",
                         "env_vars": {"BUZZ_TEAM_POLICY_PATH": str(self.policy(seat))}})
            self.policy(seat).write_text("{}")
        rows.append({"name": "Honey", "slug": "builtin:honey", "acp_command": "buzz-acp", "agent_command": ""})
        for name, key in (("Fizz", "e"), ("Pollen", "f")):
            rows.append({"name": name, "acp_command": "buzz-acp", "agent_command": "buzz-agent", "runtime": "grok",
                         "pubkey": key * 64, "relay_url": "wss://yuanbao.example/"})
        for number, seat in enumerate(self.seats):
            rows.append({"name": seat, "persona_id": f"slug-{seat}", "acp_command": "buzz-acp",
                         "agent_command": "/lab/bin/agent-executor", "runtime": "seatbelt",
                         "pubkey": f"{number:x}" * 64, "relay_url": LOCAL + "/", "env_vars": {}})
        self.rows = rows
        self.inventory = root / "managed-agents.json"
        self.write()

    def policy(self, seat):
        return self.policies / f"{seat}-seatbelt.json"

    def write(self):
        self.inventory.write_text(json.dumps(self.rows, ensure_ascii=False))

    def doctor(self, launch=None, ok=True):
        launch = len(self.seats) + 2 if launch is None else launch
        checks = [{"name": "desktop_inventory", "status": "pass", "detail": f"{launch} launch identities checked"}]
        checks += [{"name": self.policy(s).name, "status": "pass", "detail": "Seatbelt policy valid"} for s in self.seats]
        return {"command": ["doctor"], "exit_code": 0 if ok else 2, "ok": ok, "result": {"ok": ok, "checks": checks}}

    def processes(self):
        procs = []
        for number, seat in enumerate(self.seats):
            procs.append({"pid": 100 + number, "env": {"BUZZ_RELAY_URL": LOCAL, "BUZZ_ACP_AGENT_COMMAND": THIN,
                                                       "BUZZ_TEAM_POLICY_PATH": str(self.policy(seat))}})
            procs.append({"pid": 200 + number, "env": {"BUZZ_RELAY_URL": "wss://yuanbao.example",
                                                       "BUZZ_ACP_AGENT_COMMAND": THIN,
                                                       "BUZZ_TEAM_POLICY_PATH": str(self.policy(seat))}})
        return procs


GOOD_SIGNATURE = {"ok": True, "problems": []}


class BuzzHealthTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.fx = Fixture(Path(temp.name))

    def evaluate(self, doctor=None, processes=None, signature=None, probe=None):
        return health.evaluate(inventory=self.fx.inventory, policies=self.fx.policies, harnesses=self.fx.harnesses,
                               local_relay=LOCAL, doctor=doctor or self.fx.doctor(),
                               processes=self.fx.processes() if processes is None else processes,
                               signature=signature or GOOD_SIGNATURE, probe=probe or health.probe_tcp)

    def test_live_shape_passes_and_lists_skipped_rows(self):
        report = self.evaluate()
        self.assertTrue(report["ok"], report["failures"])
        ids = report["identities"]
        self.assertEqual((ids["local_count"], ids["other_relay_count"]), (3, 2))
        self.assertEqual([r["index"] for r in ids["skipped_definition_rows"]], [0, 1, 2, 3])
        self.assertEqual(ids["skipped_definition_rows"][3]["name"], "Honey")
        self.assertEqual({i["policy_source"] for i in ids["local"]}, {"definition_row_0", "definition_row_1", "definition_row_2"})
        self.assertEqual(report["processes"]["other_relay_recorded"], 3)

    def test_identity_count_is_computed_not_hardcoded(self):
        self.fx.rows = [r for r in self.fx.rows if r.get("name") != "gamma" or not r.get("pubkey")]
        self.fx.write()
        report = self.evaluate(doctor=self.fx.doctor(launch=4))
        self.assertEqual(report["identities"]["local_count"], 2)
        self.assertTrue(report["ok"], report["failures"])

    def test_definition_row_with_launch_command_is_not_skipped(self):
        self.fx.rows[0]["agent_command"] = "/x/thin"
        self.fx.write()
        report = self.evaluate()
        self.assertNotIn(0, [r["index"] for r in report["identities"]["skipped_definition_rows"]])
        self.assertFalse(report["ok"])

    def test_reconciliation_mismatch_fails(self):
        report = self.evaluate(doctor=self.fx.doctor(launch=6))
        self.assertFalse(report["ok"])
        self.assertFalse(report["identities"]["reconciliation"]["ok"])
        self.assertIn("doctor launch identities != local identities + other-relay rows", report["failures"])

    def test_doctor_not_ok_fails(self):
        self.assertFalse(self.evaluate(doctor=self.fx.doctor(ok=False))["ok"])

    def mutate_first_local(self, key, value):
        procs = self.fx.processes()
        if value is None:
            del procs[0]["env"][key]
        else:
            procs[0]["env"][key] = value
        return self.evaluate(processes=procs)

    def test_missing_env_value_fails(self):
        for key in health.ENV_KEYS:
            with self.subTest(key=key):
                report = self.mutate_first_local(key, None)
                self.assertFalse(report["ok"])
                self.assertEqual(report["processes"]["identities_without_valid_process"], ["alpha#6"])

    def test_wrong_env_value_fails(self):
        for key, value in (("BUZZ_ACP_AGENT_COMMAND", "/lab/buzz/bin/agent-executor"),
                           ("BUZZ_TEAM_POLICY_PATH", "/elsewhere/alpha-seatbelt.json")):
            with self.subTest(key=key):
                self.assertFalse(self.mutate_first_local(key, value)["ok"])

    def test_non_local_relay_is_not_counted(self):
        report = self.mutate_first_local("BUZZ_RELAY_URL", "ws://10.0.0.2:3000")
        self.assertFalse(report["ok"])
        self.assertIn(100, [p["pid"] for p in report["processes"]["other_relay"]])

    def test_extra_processes_cannot_cover_a_missing_identity(self):
        procs = self.fx.processes()
        procs[0]["env"]["BUZZ_TEAM_POLICY_PATH"] = str(self.fx.policy("beta"))
        report = self.evaluate(processes=procs)
        self.assertFalse(report["ok"])
        self.assertEqual(report["processes"]["per_identity"]["beta#7"], [100, 101])

    def test_yuanbao_never_counted_or_failing(self):
        procs = [p for p in self.fx.processes() if p["pid"] < 200]
        self.assertTrue(self.evaluate(processes=procs)["ok"])
        procs = self.fx.processes() + [{"pid": 999, "env": {"BUZZ_RELAY_URL": "wss://yuanbao.example"}}]
        report = self.evaluate(processes=procs)
        self.assertTrue(report["ok"], report["failures"])
        self.assertEqual(report["processes"]["valid_local"], 3)

    def test_shared_policy_fails(self):
        self.fx.rows[1]["env_vars"]["BUZZ_TEAM_POLICY_PATH"] = str(self.fx.policy("alpha"))
        self.fx.write()
        report = self.evaluate()
        self.assertFalse(report["policies"]["ok"])
        self.assertFalse(report["ok"])

    def test_policy_outside_directory_fails(self):
        outside = self.fx.root / "alpha-seatbelt.json"
        outside.write_text("{}")
        self.fx.rows[0]["env_vars"]["BUZZ_TEAM_POLICY_PATH"] = str(outside)
        self.fx.write()
        self.assertFalse(self.evaluate()["policies"]["ok"])

    def test_launch_row_env_overrides_definition(self):
        self.fx.rows[-1]["env_vars"]["BUZZ_TEAM_POLICY_PATH"] = str(self.fx.policy("gamma"))
        self.fx.write()
        report = self.evaluate()
        self.assertEqual(report["identities"]["local"][-1]["policy_source"], "launch_row")

    def test_missing_harness_fails(self):
        (self.fx.harnesses / "seatbelt.json").unlink()
        self.assertFalse(self.evaluate()["ok"])

    def test_signature_failure_fails(self):
        self.assertFalse(self.evaluate(signature={"ok": False, "problems": ["x"]})["ok"])

    def test_report_never_contains_private_key(self):
        def runner(argv, **_):
            if "comm=" in argv:
                return completed(stdout="  100 /Applications/Buzz.app/Contents/MacOS/buzz-acp\n  7 /bin/zsh\n")
            return completed(stdout=f"/x/buzz-acp BUZZ_PRIVATE_KEY=nsecSECRET BUZZ_RELAY_URL={LOCAL} "
                                    f"BUZZ_ACP_AGENT_COMMAND={THIN} BUZZ_TEAM_POLICY_PATH={self.fx.policy('alpha')}\n")
        procs = health.collect_processes(runner)
        self.assertEqual([p["pid"] for p in procs], [100])
        self.assertEqual(set(procs[0]["env"]), set(health.ENV_KEYS + health.PROXY_KEYS))
        self.assertNotIn("SECRET", json.dumps(self.evaluate(processes=procs)))

    def with_proxy(self, value, pids=(100, 101, 102, 200)):
        procs = self.fx.processes()
        for proc in procs:
            if proc["pid"] in pids:
                proc["env"]["HTTPS_PROXY"] = value
        return procs

    def test_unreachable_proxy_fails_and_is_probed_once(self):
        calls = []
        def probe(endpoint):
            calls.append(endpoint)
            return "ConnectionRefusedError: refused"
        report = self.evaluate(processes=self.with_proxy("http://127.0.0.1:6478"), probe=probe)
        self.assertFalse(report["ok"])
        self.assertEqual(calls, ["http://127.0.0.1:6478"])
        self.assertIn("buzz-acp proxy unreachable: http://127.0.0.1:6478", report["failures"])
        self.assertEqual(report["processes"]["identities_without_valid_process"], ["alpha#6", "beta#7", "gamma#8"])

    def test_reachable_proxy_passes(self):
        report = self.evaluate(processes=self.with_proxy("http://127.0.0.1:9567"), probe=lambda endpoint: None)
        self.assertTrue(report["ok"], report["failures"])
        self.assertEqual(report["processes"]["proxy_probes"], {"http://127.0.0.1:9567": "ok"})

    def test_other_relay_proxy_is_not_probed(self):
        def probe(endpoint):
            raise AssertionError("must not probe")
        report = self.evaluate(processes=self.with_proxy("http://127.0.0.1:6478", pids=(200,)), probe=probe)
        self.assertTrue(report["ok"], report["failures"])

    def test_unparseable_proxy_fails(self):
        report = self.evaluate(processes=self.with_proxy("<unparseable>", pids=(100,)), probe=lambda endpoint: None)
        self.assertFalse(report["ok"])
        self.assertEqual(report["processes"]["identities_without_valid_process"], ["alpha#6"])

    def test_proxy_credentials_are_dropped(self):
        def runner(argv, **_):
            if "comm=" in argv:
                return completed(stdout="  100 /Applications/Buzz.app/Contents/MacOS/buzz-acp\n")
            return completed(stdout=f"/x/buzz-acp HTTPS_PROXY=http://user:hunter2@10.0.0.1:8080 "
                                    f"http_proxy=127.0.0.1:9567 BUZZ_RELAY_URL={LOCAL}\n")
        env = health.collect_processes(runner)[0]["env"]
        self.assertEqual(env["HTTPS_PROXY"], "http://10.0.0.1:8080")
        self.assertEqual(env["http_proxy"], "http://127.0.0.1:9567")
        self.assertIsNone(env["HTTP_PROXY"])
        self.assertNotIn("hunter2", json.dumps(env))

    def test_probe_tcp_reports_refused_port(self):
        import socket
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        self.assertIsNotNone(health.probe_tcp(f"http://127.0.0.1:{port}"))
        with socket.socket() as server:
            server.bind(("127.0.0.1", 0))
            server.listen(1)
            self.assertIsNone(health.probe_tcp(f"http://127.0.0.1:{server.getsockname()[1]}"))


REQUIREMENT = '=anchor apple generic and identifier "buzz" and certificate leaf[subject.OU] = "EYF346PHUG"'
SELF_ASSERTED = "Identifier=buzz\nTeamIdentifier=EYF346PHUG\n"


class SignatureTests(unittest.TestCase):
    """buzz-health: only `codesign --verify --strict -R <requirement>` decides; -dv is recorded."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.binary = Path(temp.name) / "buzz"
        self.binary.write_bytes(b"binary")

    def check(self, requirement_ok=True, plain_verify_rc=0, info=SELF_ASSERTED):
        calls = []

        def runner(argv, **_):
            calls.append(argv)
            if "--verify" in argv:
                if "-R" in argv:  # the requirement must be exactly ours and precede the path
                    i = argv.index("-R")
                    ok = requirement_ok and argv[i + 1] == REQUIREMENT and argv[-1] == str(self.binary)
                    return completed(returncode=0 if ok else 3)
                return completed(returncode=plain_verify_rc)
            return completed(stderr=info)
        result = health.check_signature(str(self.binary), runner)
        self.assertTrue(all(call[0] == "/usr/bin/codesign" for call in calls))
        self.calls = calls
        return result

    def test_requirement_text_matches_knox_p2(self):
        self.assertEqual(health.REQUIREMENT, REQUIREMENT)

    def test_valid_signature_passes_and_records_update(self):
        result = self.check()
        self.assertTrue(result["ok"])
        self.assertEqual(result["requirement"], REQUIREMENT)
        self.assertEqual((result["team_identifier"], result["identifier"]), ("EYF346PHUG", "buzz"))
        self.assertTrue(result["updated"])
        self.assertIn("official component updated", result["note"])
        verify = [c for c in self.calls if "--verify" in c]
        self.assertEqual(verify, [["/usr/bin/codesign", "--verify", "--strict", "-R", REQUIREMENT, str(self.binary)]])

    def test_self_asserted_team_cannot_pass_without_requirement(self):
        # Self-signed cert with OU=EYF346PHUG or an ad-hoc copy: plain --verify passes (rc 0) and
        # -dv says the right team/identifier, but the Apple-anchored requirement fails.
        result = self.check(requirement_ok=False, plain_verify_rc=0, info=SELF_ASSERTED)
        self.assertFalse(result["ok"])
        self.assertEqual(result["codesign_verify"], "fail")
        self.assertEqual(result["problems"], ["codesign --verify --strict -R <requirement> failed"])

    def test_dv_output_is_not_part_of_the_decision(self):
        result = self.check(info="Identifier=buzz-5555\nSignature=adhoc\nTeamIdentifier=not set\n")
        self.assertTrue(result["ok"])
        self.assertEqual(result["team_identifier"], "not set")  # recorded only

    def test_missing_codesign_fails(self):
        def runner(argv, **_):
            raise FileNotFoundError(argv[0])
        self.assertFalse(health.check_signature(str(self.binary), runner)["ok"])

    def test_missing_binary_fails(self):
        self.assertFalse(health.check_signature(str(self.binary) + ".gone")["ok"])


FAKE_CODESIGN = r"""#!/bin/sh
# Fake codesign for tests. Logs argv (one per line, then ---). Plain --verify always passes and
# -dv always self-asserts the right team, like an ad-hoc or self-signed copy on macOS; only the
# requirement check honours FAKE_REQUIREMENT_OK.
for a in "$@"; do printf '%s\n' "$a" >> "$FAKE_LOG"; done; echo --- >> "$FAKE_LOG"
case " $* " in
  *" -dv "*) printf 'Identifier=buzz\nTeamIdentifier=EYF346PHUG\n' >&2; exit 0 ;;
esac
prev=""; for a in "$@"; do
  if [ "$prev" = "-R" ]; then
    [ "$a" = "$FAKE_EXPECTED_REQ" ] && [ "${FAKE_REQUIREMENT_OK:-0}" = 1 ] && exit 0
    exit 3
  fi
  prev="$a"
done
exit 0
"""


def code_lines(text):
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


class RequirementGateTests(unittest.TestCase):
    """bin/buzz and common.sh official_signature_ok, run from temp copies whose absolute
    /usr/bin/codesign path is rewritten to a fake (no test hook is added to the real scripts)."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir = Path(temp.name)
        self.fake = self.dir / "fake-codesign"
        self.fake.write_text(FAKE_CODESIGN)
        self.fake.chmod(0o755)
        self.log = self.dir / "codesign.log"
        self.marker = self.dir / "ran"
        self.official = self.dir / "official-buzz"
        self.official.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > "{self.marker}"\n')
        self.official.chmod(0o755)
        self.buzz = self.rewrite(ISSUE / "bin" / "buzz", "buzz")
        self.common = self.rewrite(ISSUE / "common.sh", "common.sh")

    def rewrite(self, src, name):
        text = src.read_text()
        code = code_lines(text)
        self.assertIn("/usr/bin/codesign --verify --strict -R ", code)
        self.assertNotIn("-dv", code)  # -dv output is self-asserted; it must not feed the decision
        self.assertNotIn("TeamIdentifier", code)
        out = self.dir / name
        out.write_text(text.replace("/usr/bin/codesign", str(self.fake)))
        out.chmod(0o755)
        return out

    def env(self, requirement_ok):
        return dict(os.environ, BUZZ58_TEST_OFFICIAL_BUZZ=str(self.official), FAKE_LOG=str(self.log),
                    FAKE_EXPECTED_REQ=REQUIREMENT, FAKE_REQUIREMENT_OK="1" if requirement_ok else "0")

    def calls(self):
        chunks = self.log.read_text().split("---\n") if self.log.exists() else []
        return [c.splitlines() for c in chunks if c]

    def test_requirement_text_is_identical_in_all_three_checks(self):
        self.assertIn(f"requirement='{REQUIREMENT}'", (ISSUE / "bin" / "buzz").read_text())
        self.assertIn(f"ISSUE58_REQUIREMENT='{REQUIREMENT}'", (ISSUE / "common.sh").read_text())
        self.assertEqual(health.REQUIREMENT, REQUIREMENT)

    def test_bin_buzz_uses_only_absolute_external_tools(self):
        text = code_lines((ISSUE / "bin" / "buzz").read_text())
        for tool in ("sed", "grep", "awk", "printf"):
            self.assertNotRegex(text, rf"(^|[|;(\s]){tool}\s")
        self.assertIn("/usr/bin/codesign --verify --strict -R \"$requirement\" \"$official\"", text)

    def test_bin_buzz_passes_and_execs_with_all_args(self):
        proc = subprocess.run(["bash", str(self.buzz), "messages", "send", "a b", "--x"], env=self.env(True),
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.marker.read_text(), "messages\nsend\na b\n--x\n")
        self.assertEqual(self.calls(), [["--verify", "--strict", "-R", REQUIREMENT, str(self.official)]])

    def test_bin_buzz_refuses_when_requirement_fails_even_if_dv_says_team(self):
        proc = subprocess.run(["bash", str(self.buzz), "messages", "send"], env=self.env(False),
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 3)
        self.assertIn("refused, nothing sent", proc.stderr)
        self.assertIn(REQUIREMENT, proc.stderr)
        self.assertFalse(self.marker.exists())

    def test_bin_buzz_refuses_missing_binary(self):
        env = self.env(True)
        env["BUZZ58_TEST_OFFICIAL_BUZZ"] = str(self.dir / "gone")
        proc = subprocess.run(["bash", str(self.buzz), "--help"], env=env, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 3)
        self.assertEqual(self.calls(), [])

    def test_official_signature_ok_uses_requirement(self):
        for ok, rc in ((True, 0), (False, 1)):
            with self.subTest(requirement_ok=ok):
                self.log.unlink(missing_ok=True)
                proc = subprocess.run(["bash", "-c", f'source "{self.common}"; official_signature_ok'],
                                      env=self.env(ok), capture_output=True, text=True)
                self.assertEqual(proc.returncode != 0, rc != 0, proc.stderr)
                self.assertEqual(self.calls(), [["--verify", "--strict", "-R", REQUIREMENT, str(self.official)]])


@unittest.skipIf(Path("/usr/bin/codesign").exists(), "fail-closed path needs a host without codesign")
class BuzzEntryFailClosedTests(unittest.TestCase):
    def test_refuses_without_codesign_and_never_execs(self):
        with tempfile.TemporaryDirectory() as temp:
            marker = Path(temp) / "ran"
            fake = Path(temp) / "buzz"
            fake.write_text(f"#!/bin/sh\ntouch {marker}\n")
            fake.chmod(0o755)
            env = dict(os.environ, BUZZ58_TEST_OFFICIAL_BUZZ=str(fake))
            proc = subprocess.run(["bash", str(ISSUE / "bin" / "buzz"), "messages", "send"], env=env,
                                  capture_output=True, text=True)
            self.assertEqual(proc.returncode, 3)
            self.assertIn("refused, nothing sent", proc.stderr)
            self.assertFalse(marker.exists())


class ApplyRollbackTests(unittest.TestCase):
    """Rehearse apply/rollback on a temp target (signature precheck skipped by test hook)."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name) / "home"
        self.target = Path(temp.name) / "copy"
        (self.target / "bin").mkdir(parents=True)
        (self.target / "backups").mkdir()
        for name in ("buzz", "agent-executor", "agent-harness", "agent-worktree"):
            text = self.sh(f'source "{ISSUE}/common.sh"; entry_595_text {name}').stdout
            path = self.target / "bin" / name
            path.write_text(text)
            path.chmod(0o700)
        (self.target / "bin" / "buzz.bak-pin-x").write_text("old")
        (self.target / "README.md").write_text("# Buzz 本机实例\n\n**当前 buzz-team release pin（…）**：595c0cf …\n\n其余内容\n")
        self.original = {p.name: p.read_bytes() for p in (self.target / "bin").iterdir()}
        self.original_readme = (self.target / "README.md").read_bytes()

    def env(self, **extra):
        env = dict(os.environ, HOME=str(self.home), ISSUE58_TEST_SKIP_SIGNATURE="1")
        env.pop("ISSUE58_I_UNDERSTAND_LIVE", None)
        env.update(extra)
        return env

    def sh(self, script, **extra):
        return subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=self.env(**extra))

    def run_script(self, name, *args, **extra):
        return subprocess.run(["bash", str(ISSUE / name), "--target", str(self.target), *args],
                              capture_output=True, text=True, env=self.env(**extra))

    def test_template_matches_recorded_595_hashes(self):
        out = self.sh(f'source "{ISSUE}/common.sh"; for e in $ENTRIES; do '
                      f'[ "$(sha256_of "{self.target}/bin/$e")" = "$(expected_595_sha $e)" ] || echo BAD $e; done')
        self.assertEqual(out.stdout, "")

    def test_apply_then_rollback_is_byte_identical(self):
        applied = self.run_script("apply.sh")
        self.assertEqual(applied.returncode, 0, applied.stderr)
        bin_dir = self.target / "bin"
        self.assertEqual((bin_dir / "buzz").read_bytes(), (ISSUE / "bin" / "buzz").read_bytes())
        self.assertTrue((bin_dir / "buzz-health").exists())
        self.assertFalse((bin_dir / "agent-harness").exists())
        self.assertEqual((bin_dir / "agent-executor").read_bytes(), self.original["agent-executor"])
        self.assertEqual((bin_dir / "buzz.bak-pin-x").read_text(), "old")
        readme = (self.target / "README.md").read_text()
        self.assertIn("当前入口（#58", readme)
        self.assertNotIn("当前 buzz-team release pin", readme)
        self.assertTrue(readme.endswith("其余内容\n"))
        rolled = self.run_script("rollback.sh")
        self.assertEqual(rolled.returncode, 0, rolled.stderr)
        self.assertEqual({p.name: p.read_bytes() for p in bin_dir.iterdir()}, self.original)
        self.assertEqual((self.target / "README.md").read_bytes(), self.original_readme)

    def test_rollback_from_template(self):
        self.assertEqual(self.run_script("apply.sh").returncode, 0)
        rolled = self.run_script("rollback.sh", "--from-template")
        self.assertEqual(rolled.returncode, 0, rolled.stderr)
        self.assertEqual({p.name: p.read_bytes() for p in (self.target / "bin").iterdir()}, self.original)
        self.assertIn("README.md is NOT restored and must be restored manually", rolled.stdout)
        self.assertIn("README.md NOT restored (--from-template)", rolled.stdout.splitlines()[-1])

    def test_rollback_refuses_tampered_backup(self):
        self.assertEqual(self.run_script("apply.sh").returncode, 0)
        backup = Path((self.target / "backups" / "issue58-latest").read_text().strip())
        (backup / "bin" / "buzz").write_text("tampered")
        rolled = self.run_script("rollback.sh")
        self.assertNotEqual(rolled.returncode, 0)
        self.assertEqual((self.target / "bin" / "buzz").read_bytes(), (ISSUE / "bin" / "buzz").read_bytes())

    def test_apply_refuses_non_595_entries_without_changes(self):
        (self.target / "bin" / "agent-worktree").write_text("#!/bin/sh\nexec /tmp/gone\n")
        applied = self.run_script("apply.sh")
        self.assertNotEqual(applied.returncode, 0)
        self.assertIn("not the 595c0cfe entry", applied.stderr)
        self.assertEqual((self.target / "bin" / "buzz").read_bytes(), self.original["buzz"])
        self.assertEqual(list((self.target / "backups").iterdir()), [])

    def test_apply_twice_refused(self):
        self.assertEqual(self.run_script("apply.sh").returncode, 0)
        self.assertNotEqual(self.run_script("apply.sh").returncode, 0)

    def test_live_target_needs_ack_and_refuses_test_hooks(self):
        (self.home / "lab").mkdir(parents=True)
        (self.home / "lab" / "buzz").symlink_to(self.target)
        refused = self.run_script("apply.sh")
        self.assertIn("ISSUE58_I_UNDERSTAND_LIVE", refused.stderr)
        hooked = self.run_script("apply.sh", ISSUE58_I_UNDERSTAND_LIVE="yes")
        self.assertIn("test-only", hooked.stderr)
        self.assertEqual({p.name: p.read_bytes() for p in (self.target / "bin").iterdir()}, self.original)


if __name__ == "__main__":
    unittest.main()
