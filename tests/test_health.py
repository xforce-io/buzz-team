"""Health-check taxonomy, doctor/diagnose depth, and proxy vs auth-file attribution."""
from __future__ import annotations

import json
import os
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

    def test_no_proxy_bypass_list_does_not_crash(self):
        from buzz_team.health import redact_endpoint, run
        self.assertEqual(redact_endpoint("localhost,127.0.0.1,::1,192.168.0.0/16"), "<bypass-list>")
        env = dict(os.environ)
        env["NO_PROXY"] = "localhost,127.0.0.1,::1,192.168.0.0/16,10.0.0.0/8"
        env["HTTP_PROXY"] = "http://127.0.0.1:9"
        # Should not raise even when process env has IPv6-ish NO_PROXY.
        payload = run(self.config, depth="doctor", process_env=env)
        self.assertIn("checks", payload)

    def test_acp_process_proxy_mismatch_fails_contrast(self):
        """Live ACP process proxy differing from CLI is fail — not auth."""
        from buzz_team import health as health_mod

        def fake_reader(pid):
            return {"HTTP_PROXY": "http://127.0.0.1:6478", "HTTPS_PROXY": "http://127.0.0.1:6478"}

        # Patch inventory read by writing managed agents with runtime_pid
        agents = Path(self.config.data["desktop"]["managed_agents"])
        rows = json.loads(agents.read_text()) if agents.is_file() else []
        # Ensure at least one selected row has runtime_pid — reuse fixture inventory
        # Fall back: inject via monkeypatch of _read_desktop_proxy_maps pieces
        cli_env = {"HTTP_PROXY": "http://127.0.0.1:9567", "HTTPS_PROXY": "http://127.0.0.1:9567"}
        # Build minimal maps path: call contrast with process_reader
        # Need selected rows — doctor fixture should have managed agents
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

        def fake_reader(pid):
            return {"HTTP_PROXY": "http://127.0.0.1:9567"}

        cli_env = {"HTTP_PROXY": "http://127.0.0.1:9567"}
        contrast, checks = health_mod.contrast_proxies(
            self.config, process_env=cli_env, probe=False, process_reader=fake_reader)
        proxy_checks = [c for c in checks if c["id"] == "proxy_contrast"]
        self.assertEqual(proxy_checks[0]["status"], "pass")
        self.assertTrue(any(c["id"] == "desktop_acp_process_env" and c["status"] == "pass" for c in checks))
