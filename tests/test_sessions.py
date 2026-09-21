import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from buzz_team.sessions import SessionStore


class SessionStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.instance = Path(self.tmp.name) / "instance"
        self.workspace = Path(self.tmp.name) / "workspace"
        self.workspace.mkdir(parents=True)
        self.store = SessionStore(self.instance)
        self.common = {
            "community": "ws://relay.example",
            "identity": "a" * 16 + "/" + "a" * 64,
            "scope": "channel-1",
            "workspace": str(self.workspace),
        }

    def bind(self, task="a", session="11111111-1111-4111-8111-111111111111", **overrides):
        values = {**self.common, "task_id": task, "session_id": session, **overrides}
        return self.store.bind(**values)

    def test_bind_is_idempotent_and_resolve_verifies_ownership(self):
        first = self.bind()
        self.assertEqual(self.bind(), first)
        self.assertEqual(self.store.resolve(task_id="a", **self.common), first)
        with self.assertRaisesRegex(ValueError, "ownership mismatch"):
            self.store.resolve(task_id="a", **{**self.common, "scope": "channel-2"})

    def test_tasks_are_isolated_and_conflicts_do_not_overwrite(self):
        self.bind()
        other = self.bind(task="b", session="22222222-2222-4222-8222-222222222222")
        self.assertEqual([item["task_id"] for item in self.store.list()], ["a", "b"])
        with self.assertRaisesRegex(ValueError, "conflict"):
            self.bind(task="a", session="33333333-3333-4333-8333-333333333333")
        self.assertEqual(self.store.resolve(task_id="a", **self.common)["session_id"], "11111111-1111-4111-8111-111111111111")
        self.assertEqual(self.store.resolve(task_id="b", **self.common), other)

    def test_task_is_globally_unique_and_restore_claim_is_atomic(self):
        self.bind()
        with self.assertRaisesRegex(ValueError, "conflict"):
            self.bind(identity="b" * 16 + "/" + "b" * 64, session="other-session")
        owner_a = f"{os.getpid()}-" + "a" * 32
        owner_b = f"{os.getpid()}-" + "b" * 32
        claimed = self.store.claim(owner=owner_a, task_id="a", **self.common)
        self.assertEqual(claimed["state"], "restoring")
        with patch("buzz_team.sessions.os.kill") as kill, self.assertRaisesRegex(ValueError, "already restoring"):
            kill.return_value = None
            self.store.claim(owner=owner_b, task_id="a", **self.common)
        released = self.store.release(owner=owner_a, task_id="a", **self.common)
        self.assertEqual(released["state"], "restored")
        with self.assertRaisesRegex(ValueError, "conflict"):
            self.bind(task="b", session="11111111-1111-4111-8111-111111111111")

    def test_corrupt_file_fails_closed(self):
        self.instance.mkdir()
        (self.instance / "private").mkdir()
        (self.instance / "private/task-sessions.json").write_text("not json")
        with self.assertRaisesRegex(ValueError, "invalid session mapping file"):
            self.store.list()

    def test_mapping_is_private_and_does_not_store_transcript(self):
        self.bind()
        self.assertEqual((self.store.path.stat().st_mode & 0o777), 0o600)
        data = json.loads(self.store.path.read_text())
        self.assertNotIn("prompt", json.dumps(data))
        self.assertNotIn("transcript", json.dumps(data))


if __name__ == "__main__":
    unittest.main()
