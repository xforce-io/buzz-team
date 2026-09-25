import json
from pathlib import Path
import tempfile
import unittest

from buzz_team.doctor import inspect_inventory


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "managed-agents.json"
        self.row = {"acp_command": "buzz-acp", "agent_command": "grok",
                    "pubkey": "a" * 64, "relay_url": "ws://127.0.0.1:3000"}

    def read(self, rows):
        self.path.write_text(json.dumps(rows))
        return inspect_inventory(self.path)

    def test_valid_inventory(self):
        self.assertEqual(self.read([self.row])[0]["status"], "pass")

    def test_duplicate_launch_identity_fails(self):
        checks = self.read([self.row, dict(self.row)])
        self.assertTrue(any(c["name"] == "duplicate_identity" and c["status"] == "fail" for c in checks))

    def test_empty_pubkey_fails(self):
        row = dict(self.row, pubkey="")
        self.assertEqual(self.read([row])[0]["status"], "fail")

    def test_unknown_shape_is_unverified(self):
        self.assertEqual(self.read({"agents": []})[0]["status"], "unverified")
        self.assertEqual(self.read([{"unexpected": True}])[0]["status"], "unverified")

    def test_definition_only_row_is_ignored(self):
        row = dict(self.row, acp_command="buzz-acp", agent_command="", pubkey="")
        self.assertEqual(self.read([self.row, row])[0]["status"], "pass")


if __name__ == "__main__":
    unittest.main()
