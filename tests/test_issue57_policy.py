"""Issue #57: 周衡 Kairo write paths, prompt rule, apply/rollback/verify on temp copies."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from buzz_team import thin

ROOT = Path(__file__).resolve().parents[1]
ISSUE = ROOT / "docs" / "issue-57"
OLD_SHA = "9e08735172c519e25a44c2ee92479a1fcedd9b031adfbd98c10336b005a13c23"
NEW_SHA = "8b402ff8063fe761af8db1cef4fb5979a8320c097b64de2da53d77408ca0868d"
PUB = "51fb6cd8eb6a72674998d5be5b1e8e826e2d60c870337cffc3278225e4297d9e"
APPROVED = ["/Users/xupeng/kairo/.kairo", "/Users/xupeng/kairo/能源梳理/.kairo", "/Users/xupeng/kairo/能源梳理/references",
            "/Users/xupeng/kairo/ai-native/.kairo", "/Users/xupeng/kairo/ai-native/references"]
SEATS = ["fangwei", "hanchuan", "lushen", "peizhao", "qinmu", "shenyu", "suqing", "weiping", "zhouheng"]
RELAYS = {"local": "ws://127.0.0.1:3000", "yuanbao": "wss://yuanbao.communities.buzz.xyz"}
PROXIES = {"HTTP_PROXY": "http://127.0.0.1:9567", "HTTPS_PROXY": "http://127.0.0.1:9567", "ALL_PROXY": "socks5://127.0.0.1:9567",
           "http_proxy": "http://127.0.0.1:9567", "https_proxy": "http://127.0.0.1:9567", "all_proxy": "socks5://127.0.0.1:9567"}


def load_helper():
    spec = importlib.util.spec_from_file_location("issue57_helper", ISSUE / "issue57.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


helper = load_helper()
RULE = (ISSUE / "zhouheng-prompt-rule.md").read_text()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class PolicyContentTests(unittest.TestCase):
    def test_before_policy_is_the_rollback_point(self):
        self.assertEqual(sha(ISSUE / "zhouheng-seatbelt.before.json"), OLD_SHA)

    def test_new_policy_adds_exactly_the_approved_paths(self):
        self.assertEqual(sha(ISSUE / "zhouheng-seatbelt.json"), NEW_SHA)
        new = json.loads((ISSUE / "zhouheng-seatbelt.json").read_text())
        old = json.loads((ISSUE / "zhouheng-seatbelt.before.json").read_text())
        self.assertEqual(set(new), {"version", "grok_home", "grok_executable", "mode", "write_paths"})
        self.assertEqual({k: v for k, v in new.items() if k != "write_paths"}, {k: v for k, v in old.items() if k != "write_paths"})
        self.assertEqual(old["write_paths"], [])
        self.assertEqual(new["write_paths"], APPROVED)
        self.assertEqual(new["mode"], "business")
        for banned in ("/Users/xupeng/kairo", "/private/tmp", "/tmp", "/Users/xupeng/.config/kairo", "/Users/xupeng/kairo/能源梳理"):
            self.assertNotIn(banned, new["write_paths"])
        paths = [Path(p) for p in new["write_paths"]]
        for i, a in enumerate(paths):
            for b in paths[i + 1:]:
                self.assertFalse(helper._relative(a, b) or helper._relative(b, a), (a, b))
        (ISSUE / "zhouheng-seatbelt.json").read_bytes().decode("ascii")  # no locale dependency

    def test_prompt_rule_in_repo_pj_md(self):
        text = (ROOT / "team/prompts/pj.md").read_text()
        self.assertEqual(text.count(RULE.strip()), 1)
        section = text.split("## 长任务执行与恢复", 1)[1].split("\n## ", 1)[0]
        self.assertIn(RULE.strip(), section)
        for word in ("$TMPDIR", "/private/tmp", "heredoc", "cd ~/kairo/<主题>", "KAIRO_PROVIDER=grok"):
            self.assertIn(word, RULE)

    def test_insert_rule_targets_last_section_once(self):
        prompt = "a\n\n## 长任务执行与恢复（1）\n\n- x\n- y\n\n## 其他\n- z\n\n## 长任务执行与恢复（1）\n\n- x\n- y\n"
        out = helper.insert_rule(prompt, RULE)
        self.assertEqual(out.count(RULE.strip()), 1)
        self.assertTrue(out.rstrip("\n").endswith(RULE.strip()))
        self.assertEqual(out.replace(RULE.strip() + "\n", "", 1), prompt)
        with self.assertRaisesRegex(ValueError, "already present"):
            helper.insert_rule(out, RULE)
        with self.assertRaisesRegex(ValueError, "section not found"):
            helper.insert_rule("no section", RULE)


class Env:
    """A HOME with 周衡's identity, Kairo dirs, 9 policies and a live-shaped inventory."""

    def __init__(self, home: Path):
        self.home = home
        self.identity = home / ".local/share/buzz/agent-runtime/identities/a558771623f29898" / PUB
        for child in ("grok", "tmp", "cache", "workspace"):
            (self.identity / child).mkdir(parents=True)
        self.grok = home / "bin/grok"
        self.grok.parent.mkdir()
        self.grok.write_text("#!/bin/sh\n")
        self.grok.chmod(0o700)
        self.kairo = [p.replace("/Users/xupeng", str(home)) for p in APPROVED]
        for p in self.kairo:
            Path(p).mkdir(parents=True, exist_ok=True)
        self.live = home / "lab/buzz/policies"
        self.copy = home / "copy/policies"
        self.old = home / "old.json"
        self.new = home / "new.json"
        self.old.write_text(self.policy([]))
        self.new.write_text(self.policy(self.kairo))
        for directory in (self.live, self.copy):
            directory.mkdir(parents=True)
            directory.chmod(0o700)
            for seat in SEATS:
                path = directory / f"{seat}-seatbelt.json"
                path.write_text(self.old.read_text() if seat == "zhouheng" else json.dumps({"seat": seat}))
                path.chmod(0o600)
        self.baseline = home / "baseline.json"
        self.baseline.write_text(json.dumps({f"{s}-seatbelt.json": sha(self.live / f"{s}-seatbelt.json") for s in SEATS if s != "zhouheng"}))
        self.inventory = home / "managed-agents.json"
        prompt = (ROOT / "team/prompts/pj.md").read_text().replace(RULE.strip() + "\n", "")
        rows = [{"name": "周衡", "slug": "zhufeng-pj", "system_prompt": prompt},
                {"name": "周衡", "persona_id": "zhufeng-pj", "relay_url": "ws://127.0.0.1:3000", "system_prompt": prompt},
                {"name": "陆深", "slug": "zhufeng-eng", "system_prompt": "x"}]
        self.inventory.write_text(json.dumps(rows, ensure_ascii=False, indent=2))
        self.logs = home / "Library/Application Support/xyz.block.buzz.app/agents/logs"
        self.logs.mkdir(parents=True)
        for relay in ("aaaa", "bbbb"):
            (self.logs / f"{PUB}__{relay}.log").write_text("start\n")

    def policy(self, paths):
        return json.dumps({"version": 1, "grok_home": str(self.identity / "grok"), "grok_executable": str(self.grok),
                           "mode": "business", "write_paths": paths}, indent=2)

    def processes(self, seed=100):
        procs, pid = [], seed
        thin_cmd = str(self.home / "lab/buzz/evidence/f66ef5e-preview/venv/bin/buzz-team-thin")
        for relay, url in RELAYS.items():
            for seat in SEATS:
                env = {"BUZZ_RELAY_URL": url, "BUZZ_ACP_AGENT_COMMAND": thin_cmd, "KAIRO_PROVIDER": "grok",
                       "BUZZ_TEAM_POLICY_PATH": str(self.live / f"{seat}-seatbelt.json"), **PROXIES}
                child = {"pid": pid + 1000, "comm": "grok", "env": {}}
                if seat == "zhouheng":
                    env["GROK_HOME"] = str(self.identity / "grok")
                    child["env"] = {"TMPDIR": str(self.identity / "tmp") + "/", "GROK_SANDBOX": "off"}
                tcp = ["127.0.0.1:5000->127.0.0.1:3000 (ESTABLISHED)"] if relay == "local" else ["TCP 1.2.3.4:1->5.6.7.8:443 (CLOSED)"]
                procs.append({"pid": pid, "ppid": 1, "lstart": "x", "env": env, "tcp": tcp, "children": [child]})
                pid += 1
        return procs


class ScriptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = Env(Path(self.tmp.name).resolve())
        self.base = {"HOME": str(self.env.home), "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                     "PYTHONPATH": str(ROOT / "src"), "ISSUE57_THIN_PYTHON": sys.executable,
                     "ISSUE57_TEST_NEW_POLICY": str(self.env.new), "ISSUE57_TEST_OLD_POLICY": str(self.env.old),
                     "ISSUE57_TEST_BASELINE": str(self.env.baseline)}

    def run_script(self, name, *args, **extra):
        env = dict(self.base, **extra)
        return subprocess.run(["bash", str(ISSUE / name), *args], capture_output=True, text=True, env=env)

    def fixture(self, procs):
        path = self.env.home / "ps.json"
        path.write_text(json.dumps(procs))
        return str(path)

    def test_thin_accepts_new_policy_and_profile_names_each_path(self):
        target = self.env.copy / "zhouheng-seatbelt.json"
        target.write_text(self.env.new.read_text())
        info = helper.precheck(target, self.env.identity / "grok", self.env.identity / "workspace", self.env.home / "p.sb")
        profile = (self.env.home / "p.sb").read_text()
        self.assertEqual(profile, thin._profile([Path(r) for r in info["roots"]]))
        for p in self.env.kairo:
            self.assertIn(f'(require-not (subpath {json.dumps(p, ensure_ascii=False)}))', profile)
        self.assertNotIn(f'(subpath "{self.env.home}/kairo")', profile)
        self.assertEqual(len(info["roots"]), 6)

    def test_apply_verify_rollback_round_trip(self):
        copy, inv = self.env.copy, self.env.inventory
        before_inv, others = sha(inv), {s: sha(copy / f"{s}-seatbelt.json") for s in SEATS if s != "zhouheng"}
        r = self.run_script("apply.sh", "--target", str(copy), "--inventory", str(inv))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(sha(copy / "zhouheng-seatbelt.json"), sha(self.env.new))
        self.assertEqual(oct((copy / "zhouheng-seatbelt.json").stat().st_mode & 0o777), "0o600")
        backups = list(copy.glob("zhouheng-seatbelt.json.issue57-*.bak"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(sha(backups[0]), sha(self.env.old))
        rows = json.loads(inv.read_text())
        self.assertEqual([r["system_prompt"].count(RULE.strip()) for r in rows], [1, 1, 0])
        v = self.run_script("verify.sh", "--target", str(copy), "--expect", "new", "--static-only", "--inventory", str(inv), "--prompt", "present")
        self.assertEqual(v.returncode, 0, v.stdout + v.stderr)
        self.assertIn("VERIFY PASS", v.stdout)
        r = self.run_script("rollback.sh", "--target", str(copy), "--inventory", str(inv))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(sha(copy / "zhouheng-seatbelt.json"), sha(self.env.old))
        self.assertEqual(sha(inv), before_inv)
        self.assertEqual(others, {s: sha(copy / f"{s}-seatbelt.json") for s in SEATS if s != "zhouheng"})
        v = self.run_script("verify.sh", "--target", str(copy), "--expect", "old", "--static-only", "--inventory", str(inv), "--prompt", "absent")
        self.assertEqual(v.returncode, 0, v.stdout + v.stderr)

    def test_rollback_from_template(self):
        self.assertEqual(self.run_script("apply.sh", "--target", str(self.env.copy)).returncode, 0)
        r = self.run_script("rollback.sh", "--target", str(self.env.copy), "--from-template")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(sha(self.env.copy / "zhouheng-seatbelt.json"), sha(self.env.old))

    def test_real_template_reproduces_9e087351(self):
        self.assertEqual(sha(ISSUE / "zhouheng-seatbelt.before.json"), OLD_SHA)

    def test_apply_refusals_leave_policy_untouched(self):
        broken = self.env.home / "broken.json"
        broken.write_text(self.env.policy(self.env.kairo + [str(self.env.home / "kairo/missing")]))
        r = self.run_script("apply.sh", "--target", str(self.env.copy), ISSUE57_TEST_NEW_POLICY=str(broken))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("fails thin._load_policy", r.stderr)
        self.assertEqual(sha(self.env.copy / "zhouheng-seatbelt.json"), sha(self.env.old))
        self.assertEqual(list(self.env.copy.glob("*.bak")), [])
        overlap = self.env.home / "overlap.json"
        overlap.write_text(self.env.policy(self.env.kairo + [self.env.kairo[0]]))
        self.assertNotEqual(self.run_script("apply.sh", "--target", str(self.env.copy), ISSUE57_TEST_NEW_POLICY=str(overlap)).returncode, 0)
        self.assertEqual(self.run_script("apply.sh", "--target", str(self.env.copy)).returncode, 0)
        again = self.run_script("apply.sh", "--target", str(self.env.copy))
        self.assertNotEqual(again.returncode, 0)
        self.assertIn("not the rollback point", again.stderr)

    def test_live_guard_and_test_hooks(self):
        r = self.run_script("apply.sh")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("ISSUE57_I_UNDERSTAND_LIVE=yes", r.stderr)
        r = self.run_script("apply.sh", ISSUE57_I_UNDERSTAND_LIVE="yes")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("test-only", r.stderr)
        r = self.run_script("rollback.sh", "--from-template")
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(sha(self.env.live / "zhouheng-seatbelt.json"), sha(self.env.old))

    def verify_live(self, procs, *args):
        return self.run_script("verify.sh", "--expect", "old", *args, ISSUE57_TEST_PS_FIXTURE=self.fixture(procs))

    def test_verify_per_relay_env_pass(self):
        r = self.verify_live(self.env.processes())
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("[yuanbao]", r.stdout)
        self.assertIn("[local]", r.stdout)

    def test_verify_missing_values_fail(self):
        cases = [("BUZZ_TEAM_POLICY_PATH", "local"), ("BUZZ_TEAM_POLICY_PATH", "yuanbao"), ("KAIRO_PROVIDER", "local"),
                 ("BUZZ_ACP_AGENT_COMMAND", "yuanbao"), ("https_proxy", "local")]
        for key, relay in cases:
            with self.subTest(key=key, relay=relay):
                procs = self.env.processes()
                for p in procs:
                    if p["env"].get("GROK_HOME") and p["env"]["BUZZ_RELAY_URL"] == RELAYS[relay]:
                        p["env"].pop(key)
                r = self.verify_live(procs)
                self.assertEqual(r.returncode, 1, r.stdout)
                self.assertIn(f"{key}=<missing>" if key != "BUZZ_TEAM_POLICY_PATH" else "BUZZ_TEAM_POLICY_PATH=<missing>", r.stdout)

    def test_verify_fails_without_process_or_thin_child_or_relay(self):
        procs = [p for p in self.env.processes() if not (p["env"].get("GROK_HOME") and "yuanbao" in p["env"]["BUZZ_RELAY_URL"])]
        r = self.verify_live(procs)
        self.assertEqual(r.returncode, 1)
        self.assertIn("FAIL [yuanbao] exactly one 周衡 buzz-acp ([])", r.stdout)
        procs = self.env.processes()
        for p in procs:
            if p["env"].get("GROK_HOME"):
                p["children"] = []
        self.assertEqual(self.verify_live(procs).returncode, 1)
        procs = self.env.processes()
        for p in procs:
            if p["env"].get("GROK_HOME") and "127.0.0.1" in p["env"]["BUZZ_RELAY_URL"]:
                p["tcp"] = []
        self.assertEqual(self.verify_live(procs).returncode, 1)

    def test_verify_policy_sha_must_match_expectation(self):
        r = self.run_script("verify.sh", "--expect", "new", ISSUE57_TEST_PS_FIXTURE=self.fixture(self.env.processes()))
        self.assertEqual(r.returncode, 1)
        self.assertIn("policy-in-env sha256", r.stdout)

    def test_verify_restart_compare(self):
        state = self.env.home / "state.json"
        before = self.env.processes()
        saved = self.run_script("snapshot.sh", "--out", str(state), ISSUE57_TEST_PS_FIXTURE=self.fixture(before))
        self.assertEqual(saved.returncode, 0, saved.stderr)
        after = self.env.processes()
        for p in after:
            if p["env"].get("GROK_HOME"):
                p["pid"] += 500
        ok = self.verify_live(after, "--compare-state", str(state), "--restarted")
        self.assertEqual(ok.returncode, 0, ok.stdout)
        self.assertEqual(self.verify_live(before, "--compare-state", str(state), "--restarted").returncode, 1)
        moved = self.env.processes()
        for p in moved:
            if p["env"].get("GROK_HOME"):
                p["pid"] += 500
        moved[0]["pid"] = 9999
        self.assertEqual(self.verify_live(moved, "--compare-state", str(state), "--restarted").returncode, 1)
        log = next(self.env.logs.glob("*.log"))
        with log.open("a") as handle:
            handle.write("buzz-team-thin: BUZZ_TEAM_POLICY_PATH must be an absolute path\n")
        bad = self.verify_live(after, "--compare-state", str(state), "--restarted")
        self.assertEqual(bad.returncode, 1)
        self.assertIn("STOP, rollback, report to Jenny", bad.stdout)

    def test_snapshot_keeps_only_whitelisted_env(self):
        self.assertEqual(helper._env_subset("cmd BUZZ_PRIVATE_KEY=redacted-test-value KAIRO_PROVIDER=grok X=1", helper.ACP_KEYS), {"KAIRO_PROVIDER": "grok"})


if __name__ == "__main__":
    unittest.main()
