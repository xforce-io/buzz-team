"""Health-check taxonomy, doctor/diagnose depth, and proxy vs auth-file attribution."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from buzz_team import health
from buzz_team.adapters import Grok
from test_runtime import Fixture


class HealthTaxonomyTests(Fixture):
    def cli(self, *args, **extra_env):
        import os, subprocess, sys
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"), **extra_env)
        env.pop("BUZZ_RELAY_URL", None)
        return subprocess.run([sys.executable, "-m", "buzz_team.cli", "--instance", str(self.instance), *args],
                              cwd=self.root, env=env, capture_output=True, text=True, timeout=20)


    def test_doctor_exposes_taxonomy_and_ok_ignores_unverified(self):
        result = health.run(self.config, depth="doctor")
        self.assertIn(result["depth"], ("doctor",))
        self.assertIn("checks", result)
        self.assertTrue(result["checks"])
        for item in result["checks"]:
            self.assertEqual(set(item), {"id", "status", "component", "summary"})
            self.assertIn(item["status"], health.STATUSES)
            self.assertIn(item["component"], health.COMPONENTS)
        self.assertEqual(set(result["coverage"]), {"pass", "fail", "unverified", "na"})
        unverified = [c for c in result["checks"] if c["status"] == "unverified"]
        self.assertTrue(unverified)
        # Presence of unverified must not by itself force ok false.
        fails = [c for c in result["checks"] if c["status"] == "fail"]
        self.assertEqual(result["ok"], not fails)
        self.assertIn("ok means no fail only", result["warnings"][0])
        self.assertNotIn("unverified_surfaces", result)

    def test_diagnose_differs_from_doctor_or_lists_unverified(self):
        doctor = health.run(self.config, depth="doctor")
        diagnose = health.run(self.config, depth="diagnose")
        self.assertEqual(doctor["depth"], "doctor")
        self.assertEqual(diagnose["depth"], "diagnose")
        self.assertIn("unverified_surfaces", diagnose)
        self.assertTrue(diagnose["unverified_surfaces"])
        self.assertNotEqual(
            {c["id"] for c in doctor["checks"]},
            {c["id"] for c in diagnose["checks"]},
        )
        # Same kernel fields remain.
        self.assertIn("checks", diagnose)
        self.assertIn("coverage", diagnose)
        self.assertIn("proxy_contrast", diagnose)

    def test_cli_doctor_and_diagnose_json(self):
        doctor = self.cli("doctor")
        diagnose = self.cli("diagnose")
        self.assertNotEqual(doctor.stdout, "")
        d_out = json.loads(doctor.stdout)
        g_out = json.loads(diagnose.stdout)
        self.assertEqual(d_out["depth"], "doctor")
        self.assertEqual(g_out["depth"], "diagnose")
        self.assertIn("checks", d_out)
        self.assertIn("unverified_surfaces", g_out)
        self.assertNotIn("unverified_surfaces", d_out)

    def test_missing_auth_file_is_credentials_not_proxy(self):
        auth = self.base / "grok/auth.json"
        auth.unlink()
        result = health.run(self.config, depth="doctor")
        cred = [c for c in result["checks"] if c["id"].startswith("grok_credentials_files")]
        self.assertTrue(cred)
        self.assertEqual(cred[0]["status"], "fail")
        self.assertEqual(cred[0]["component"], "buzz_runtime")
        self.assertIn("credential files", cred[0]["summary"])
        self.assertIn("distinct from proxy", cred[0]["summary"])
        # Must not classify solely as proxy failure.
        proxy_fails = [
            c for c in result["checks"]
            if c["status"] == "fail" and c["component"] == "proxy"
            and "auth" in c["summary"].lower()
        ]
        self.assertEqual(proxy_fails, [])
        # Adapter-level message stays distinct as well.
        messages = Grok(self.config.data["adapters"]["grok"]).check(self.base)
        self.assertTrue(any("credential files" in m and "proxy" in m for m in messages))

    def test_auth_present_dead_proxy_attributes_proxy(self):
        # Keep auth.json; inject unreachable proxy on Desktop binding and empty CLI env.
        rows = json.loads(self.desktop_file.read_text())
        rows[0]["env_vars"]["HTTPS_PROXY"] = "http://127.0.0.1:9"
        self.desktop_file.write_text(json.dumps(rows, indent=2) + "\n")
        # Ensure credential files still present.
        self.assertTrue((self.base / "grok/auth.json").is_file())
        with patch.object(health, "probe_tcp", return_value="fail"):
            result = health.run(self.config, depth="diagnose", process_env={})
        cred = [c for c in result["checks"] if c["id"].startswith("grok_credentials_files")]
        self.assertTrue(cred)
        self.assertEqual(cred[0]["status"], "pass")
        proxy_fails = [c for c in result["checks"] if c["status"] == "fail" and c["component"] == "proxy"]
        self.assertTrue(proxy_fails)
        joined = " ".join(c["summary"] for c in proxy_fails)
        self.assertIn("proxy", joined.lower())
        self.assertTrue(
            any("not auth" in c["summary"].lower() or "auth.json" in c["summary"] for c in proxy_fails)
        )
        # No fail id should be grok_credentials_files when files exist.
        self.assertFalse(any(c["status"] == "fail" and "grok_credentials" in c["id"] for c in result["checks"]))
        # Redaction: contrast must not contain scheme credentials.
        blob = json.dumps(result["proxy_contrast"])
        self.assertNotIn("http://", blob)
        self.assertIn("127.0.0.1:9", blob)

    def test_proxy_key_mismatch_between_desktop_and_cli(self):
        rows = json.loads(self.desktop_file.read_text())
        rows[0]["env_vars"]["HTTPS_PROXY"] = "http://proxy.example:8080"
        self.desktop_file.write_text(json.dumps(rows, indent=2) + "\n")
        result = health.run(
            self.config, depth="doctor",
            process_env={"HTTPS_PROXY": "http://other.example:9090"},
        )
        contrast = [c for c in result["checks"] if c["id"] == "proxy_contrast"]
        self.assertEqual(len(contrast), 1)
        self.assertEqual(contrast[0]["status"], "fail")
        self.assertEqual(contrast[0]["component"], "proxy")
        self.assertTrue(result["proxy_contrast"]["mismatches"])

    def test_redact_endpoint_strips_secrets(self):
        self.assertEqual(health.redact_endpoint("http://user:token@host.example:8080/path"), "host.example:8080")
        self.assertEqual(health.redact_endpoint("127.0.0.1:9"), "127.0.0.1:9")
        self.assertIsNone(health.redact_endpoint(""))
        self.assertEqual(health.redact_endpoint("socks5://secret@10.0.0.1:1080"), "10.0.0.1:1080")

    def test_git_boundary_is_na(self):
        result = health.run(self.config, depth="doctor")
        git = [c for c in result["checks"] if c["id"] == "git_directory_boundary"]
        self.assertEqual(len(git), 1)
        self.assertEqual(git[0]["status"], "na")
        self.assertIn("not applicable", git[0]["summary"].lower())

    def test_ok_false_when_binary_drifts(self):
        self.fake.write_text(self.fake.read_text() + "# drift\n")
        result = health.run(self.config, depth="doctor")
        self.assertFalse(result["ok"])
        self.assertTrue(result["errors"])
        self.assertTrue(any(c["status"] == "fail" and c["component"] == "install" for c in result["checks"]))

    def test_tool_seatbelt_reports_inherit_semantics(self):
        from buzz_team.health import _seatbeltDevEnvChecks
        with patch("buzz_team.health.sys.platform", "linux"):
            checks = _seatbeltDevEnvChecks()
            self.assertEqual(len(checks), 1)
            self.assertEqual(checks[0]["id"], "tool_seatbelt")
            self.assertEqual(checks[0]["status"], "na")
        with patch("buzz_team.health.sys.platform", "darwin"), \
             patch("buzz_team.health.SEATBELT_EXEC") as binary:
            binary.is_file.return_value = False
            checks = _seatbeltDevEnvChecks()
            self.assertEqual(checks[0]["status"], "fail")
            self.assertEqual(checks[0]["summary"], "Seatbelt unavailable")
            binary.is_file.return_value = True
            with patch("buzz_team.health.underSeatbelt", return_value=False), \
                 patch("buzz_team.health.probeNestedSeatbeltApply", return_value="inherit_only"):
                checks = _seatbeltDevEnvChecks()
            ids = {c["id"]: c for c in checks}
            self.assertEqual(ids["tool_seatbelt"]["status"], "pass")
            self.assertIn("inherits", ids["tool_seatbelt"]["summary"])
            self.assertEqual(ids["tool_seatbelt_nested"]["status"], "pass")
            self.assertIn("inherit", ids["tool_seatbelt_nested"]["summary"])
            self.assertIn("unavailable", ids["tool_seatbelt_nested"]["summary"])
            with patch("buzz_team.health.underSeatbelt", return_value=True), \
                 patch("buzz_team.health.probeNestedSeatbeltApply", return_value="nested_ok"):
                checks = _seatbeltDevEnvChecks()
            nested = [c for c in checks if c["id"] == "tool_seatbelt_nested"][0]
            self.assertIn("already confined", nested["summary"])
            self.assertIn("inherits", nested["summary"])

    def test_seatbelt_policy_documents_inherit_for_restricted(self):
        result = health.run(self.config, depth="doctor")
        policy = [c for c in result["checks"] if c["id"].startswith("seatbelt_policy:")]
        self.assertTrue(policy)
        if sys.platform == "darwin":
            self.assertEqual(policy[0]["status"], "pass")
            self.assertIn("inherit", policy[0]["summary"])
            self.assertIn("GROK_SANDBOX=off", policy[0]["summary"])
        else:
            self.assertEqual(policy[0]["status"], "fail")
            self.assertIn("Seatbelt unavailable", policy[0]["summary"])
        self.config.data["policies"]["development"]["production_write"] = True
        self.save()
        writer = health.run(self.config, depth="doctor")
        self.assertFalse(any(c["id"].startswith("seatbelt_policy:") for c in writer["checks"]))

    def test_no_proxy_bypass_list_does_not_crash(self):
        from buzz_team.health import redact_endpoint, run
        self.assertEqual(redact_endpoint("localhost,127.0.0.1,::1,192.168.0.0/16"), "<bypass-list>")
        env = dict(os.environ)
        env["NO_PROXY"] = "localhost,127.0.0.1,::1,192.168.0.0/16,10.0.0.0/8"
        env["HTTP_PROXY"] = "http://127.0.0.1:9"
        # Should not raise even when process env has IPv6-ish NO_PROXY.
        payload = run(self.config, depth="doctor", process_env=env)
        self.assertIn("checks", payload)


    def _seed_agent_pids(self, pid: int | None = None, *, suffix: str = "test"):
        from buzz_team import desktop
        if pid is None:
            pid = os.getpid()
        ma = Path(self.config.data["desktop"]["managed_agents"])
        rows = json.loads(ma.read_text())
        selected = desktop.selected_rows(self.config, rows)
        pids_dir = ma.parent / "agent-pids"
        pids_dir.mkdir(parents=True, exist_ok=True)
        for row in selected.values():
            pubkey = row["pubkey"]
            (pids_dir / f"{pubkey}__{suffix}.json").write_text(json.dumps({
                "pid": pid, "key": pubkey, "desktopInstanceId": "t", "startedAt": "x"}))
            row["runtime_pid"] = None
        ma.write_text(json.dumps(rows))
        return selected

    def _reapedPid(self) -> int:
        child = subprocess.Popen(
            [sys.executable, "-c", "pass"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        child.wait()
        return child.pid

    def _deadPidChecks(self, checks):
        return [
            c for c in checks
            if c["id"].startswith("desktop_agent_pid:") and c["status"] == "fail"
        ]

    def test_acp_process_proxy_mismatch_fails_contrast(self):
        """Live ACP process proxy differing from CLI is fail — not auth."""
        from buzz_team import health as health_mod

        livePid = os.getpid()

        def fake_reader(pid):
            self.assertEqual(pid, livePid)
            return {"HTTP_PROXY": "http://127.0.0.1:6478", "HTTPS_PROXY": "http://127.0.0.1:6478"}

        self._seed_agent_pids(livePid)
        cli_env = {"HTTP_PROXY": "http://127.0.0.1:9567", "HTTPS_PROXY": "http://127.0.0.1:9567"}
        contrast, checks = health_mod.contrast_proxies(
            self.config, process_env=cli_env, probe=False, process_reader=fake_reader)
        proxy_checks = [c for c in checks if c["id"] == "proxy_contrast"]
        self.assertTrue(proxy_checks)
        self.assertEqual(proxy_checks[0]["status"], "fail")
        self.assertIn("process", proxy_checks[0]["summary"].lower())
        self.assertNotIn("auth.json", proxy_checks[0]["summary"].lower())
        self.assertTrue(contrast.get("process_mismatches"))

    def test_acp_process_proxy_aligns_with_cli(self):
        from buzz_team import health as health_mod

        livePid = os.getpid()

        def fake_reader(pid):
            self.assertEqual(pid, livePid)
            return {"HTTP_PROXY": "http://127.0.0.1:9567"}

        self._seed_agent_pids(livePid)
        cli_env = {"HTTP_PROXY": "http://127.0.0.1:9567"}
        contrast, checks = health_mod.contrast_proxies(
            self.config, process_env=cli_env, probe=False, process_reader=fake_reader)
        proxy_checks = [c for c in checks if c["id"] == "proxy_contrast"]
        self.assertEqual(proxy_checks[0]["status"], "pass")
        self.assertTrue(any(c["id"] == "desktop_acp_process_env" and c["status"] == "pass" for c in checks))

    def test_agent_pids_file_supplies_runtime_pid(self):
        from buzz_team import health as health_mod
        livePid = os.getpid()
        ma = Path(self.config.data["desktop"]["managed_agents"])
        pids_dir = ma.parent / "agent-pids"
        pids_dir.mkdir(parents=True, exist_ok=True)
        # pick first agent pubkey from selected inventory
        rows = json.loads(ma.read_text())
        from buzz_team import desktop
        selected = desktop.selected_rows(self.config, rows)
        self.assertTrue(selected)
        key, row = next(iter(selected.items()))
        pubkey = row["pubkey"]
        # fake reader records which pid it was asked for
        seen = {}
        def fake_reader(pid):
            seen["pid"] = pid
            return {"HTTP_PROXY": "http://127.0.0.1:9567"}
        (pids_dir / f"{pubkey}__testdesktop.json").write_text(json.dumps({
            "pid": livePid, "key": pubkey, "desktopInstanceId": "t", "startedAt": "x"}))
        # clear runtime_pid on disk copy? selected_rows reads live file — patch row via rewriting managed agents temp is hard;
        # instead call _read_desktop_proxy_maps with process_reader after ensuring runtime_pid null in file
        for r in rows:
            if r.get("pubkey") == pubkey:
                r["runtime_pid"] = None
        ma.write_text(json.dumps(rows))
        maps, checks = health_mod._read_desktop_proxy_maps(self.config, process_reader=fake_reader)
        self.assertEqual(seen.get("pid"), livePid)
        self.assertTrue(any(c["id"] == "desktop_agent_pids" and c["status"] == "pass" for c in checks))
        self.assertFalse(self._deadPidChecks(checks))
        self.assertTrue(any(m.get("process_proxy_keys") for m in maps))

    def test_pid_is_alive_uses_kill_zero(self):
        from buzz_team import health as health_mod
        self.assertTrue(health_mod._pidIsAlive(os.getpid()))
        self.assertFalse(health_mod._pidIsAlive(self._reapedPid()))
        self.assertFalse(health_mod._pidIsAlive(0))
        self.assertFalse(health_mod._pidIsAlive(-1))
        with patch.object(health_mod.os, "kill", side_effect=PermissionError):
            self.assertTrue(health_mod._pidIsAlive(1))
        with patch.object(health_mod.os, "kill", side_effect=ProcessLookupError):
            self.assertFalse(health_mod._pidIsAlive(1))

    def test_dead_agent_pid_fails_doctor(self):
        """S1: dead pid file → fail mentioning identity/pid; not silent ok."""
        from buzz_team import health as health_mod
        deadPid = self._reapedPid()
        selected = self._seed_agent_pids(deadPid, suffix="283dleftover")
        key = next(iter(selected))
        maps, checks = health_mod._read_desktop_proxy_maps(
            self.config, process_reader=lambda pid: {})
        deadChecks = self._deadPidChecks(checks)
        self.assertEqual(len(deadChecks), 1)
        self.assertIn(str(deadPid), deadChecks[0]["id"])
        self.assertIn(key[:20], deadChecks[0]["id"])
        self.assertIn(str(deadPid), deadChecks[0]["summary"])
        self.assertIn(key[:20], deadChecks[0]["summary"])
        self.assertIn("283dleftover", deadChecks[0]["summary"])
        self.assertFalse(any(
            c["id"] == "desktop_agent_pids" and c["status"] == "pass" for c in checks))
        isolated = health_mod.summarize(checks)
        self.assertFalse(isolated["ok"])
        self.assertTrue(any(str(deadPid) in error for error in isolated["errors"]))
        result = health_mod.run(self.config, depth="doctor")
        self.assertFalse(result["ok"])
        self.assertTrue(any(
            c["status"] == "fail" and str(deadPid) in c["summary"] and key[:20] in c["summary"]
            for c in result["checks"]))
        self.assertTrue(any(str(deadPid) in error for error in result["errors"]))

    def test_live_agent_pid_still_passes(self):
        """S2: live pid file → desktop_agent_pids pass for that check."""
        from buzz_team import health as health_mod
        livePid = os.getpid()
        selected = self._seed_agent_pids(livePid)
        key = next(iter(selected))

        def fake_reader(pid):
            self.assertEqual(pid, livePid)
            return {"HTTP_PROXY": "http://127.0.0.1:9567"}

        maps, checks = health_mod._read_desktop_proxy_maps(
            self.config, process_reader=fake_reader)
        self.assertTrue(any(
            c["id"] == "desktop_agent_pids" and c["status"] == "pass" for c in checks))
        self.assertEqual(self._deadPidChecks(checks), [])
        self.assertEqual(maps[0]["runtime_pid"], livePid)
        isolated = health_mod.summarize([
            c for c in checks if c["id"].startswith("desktop_agent_pid")
        ])
        self.assertTrue(isolated["ok"])
        result = health_mod.run(self.config, depth="doctor")
        self.assertTrue(any(
            c["id"] == "desktop_agent_pids" and c["status"] == "pass" for c in result["checks"]))
        self.assertFalse(any(
            c["status"] == "fail" and "dead process" in c["summary"] for c in result["checks"]))
        self.assertIn(key[:20], json.dumps(result["proxy_contrast"]))

    def test_mixed_live_and_leftover_dead_agent_pids(self):
        """Live file still supplies pid; leftover dead __283d* file still fails."""
        from buzz_team import health as health_mod
        livePid = os.getpid()
        deadPid = self._reapedPid()
        selected = self._seed_agent_pids(livePid, suffix="a558live")
        key, row = next(iter(selected.items()))
        pubkey = row["pubkey"]
        ma = Path(self.config.data["desktop"]["managed_agents"])
        leftover = ma.parent / "agent-pids" / f"{pubkey}__283dleftover.json"
        leftover.write_text(json.dumps({
            "pid": deadPid, "key": pubkey, "desktopInstanceId": "t", "startedAt": "x"}))
        seen = []

        def fake_reader(pid):
            seen.append(pid)
            return {"HTTP_PROXY": "http://127.0.0.1:9567"}

        maps, checks = health_mod._read_desktop_proxy_maps(
            self.config, process_reader=fake_reader)
        self.assertEqual(seen, [livePid])
        self.assertTrue(any(
            c["id"] == "desktop_agent_pids" and c["status"] == "pass" for c in checks))
        deadChecks = self._deadPidChecks(checks)
        self.assertEqual(len(deadChecks), 1)
        self.assertIn(str(deadPid), deadChecks[0]["summary"])
        self.assertIn("283dleftover", deadChecks[0]["summary"])
        self.assertIn(key[:20], deadChecks[0]["summary"])
        self.assertFalse(health_mod.summarize(checks)["ok"])

    def test_load_agent_pid_index_fake_liveness_fixtures(self):
        """Fake probe: pid>0 still dead unless the liveness hook says alive."""
        from buzz_team import health as health_mod
        livePid, deadPid = 7, 9
        selected = self._seed_agent_pids(livePid, suffix="alive")
        pubkey = next(iter(selected.values()))["pubkey"]
        ma = Path(self.config.data["desktop"]["managed_agents"])
        (ma.parent / "agent-pids" / f"{pubkey}__283ddead.json").write_text(json.dumps({
            "pid": deadPid, "key": pubkey, "desktopInstanceId": "t", "startedAt": "x"}))

        def fakeAlive(pid: int) -> bool:
            return pid == livePid

        live, dead = health_mod._load_agent_pid_index(ma, pidIsAlive=fakeAlive)
        self.assertEqual(live, {pubkey: livePid})
        self.assertEqual(len(dead), 1)
        self.assertEqual(dead[0]["pid"], deadPid)
        self.assertIn("283ddead", dead[0]["file"])
        liveOnly, deadOnly = health_mod._load_agent_pid_index(
            ma, pidIsAlive=lambda pid: False)
        self.assertEqual(liveOnly, {})
        self.assertEqual({entry["pid"] for entry in deadOnly}, {livePid, deadPid})
