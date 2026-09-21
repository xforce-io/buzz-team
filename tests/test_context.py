import json
from pathlib import Path
import tempfile
import unittest

from buzz_team.context import ContextLedger


class ContextLedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.instance = Path(self.tmp.name) / "instance"
        self.ledger = ContextLedger(self.instance, "task-a")

    def test_records_quality_totals_peak_and_budget_without_prompt(self):
        self.ledger.start(max_input_tokens=100, max_context_tokens=80)
        self.ledger.record(
            turn_id="turn-1", provider="provider", model="model",
            values={"input_tokens": 60, "output_tokens": 10, "cached_input_tokens": 40,
                    "uncached_input_tokens": 20, "context_tokens": 70, "duration_ms": 1000},
            qualities={"input_tokens": "actual", "output_tokens": "actual",
                       "cached_input_tokens": "actual", "uncached_input_tokens": "actual",
                       "context_tokens": "actual", "duration_ms": "actual"})
        self.ledger.record(
            turn_id="turn-2", provider="provider", model="model",
            values={"input_tokens": "unavailable", "output_tokens": 10, "context_tokens": 90},
            qualities={"output_tokens": "estimated", "context_tokens": "estimated"})
        report = self.ledger.report()
        self.assertEqual(report["status"], "budget_exceeded")
        self.assertEqual(report["totals"]["input_tokens"]["actual"], 60)
        self.assertEqual(report["totals"]["input_tokens"]["unavailable"], 1)
        self.assertEqual(report["peak_context"], {"value": 90, "quality": "estimated"})
        self.assertNotIn("prompt", json.dumps(report))

    def test_handoff_requires_closed_tools_and_is_atomic(self):
        self.ledger.start()
        with self.assertRaisesRegex(ValueError, "open tool calls"):
            self.ledger.handoff(goal="goal", next_step="next", workspace_ref="HEAD",
                                approval_state="approved", open_tool_calls=1)
        self.assertFalse(self.ledger.handoff_path.exists())
        handoff = self.ledger.handoff(goal="goal", next_step="next", workspace_ref="HEAD",
                                      approval_state="approved", constraints=["keep behavior"],
                                      facts=["test passed"], pending=["review"],
                                      tool_results=["result digest"])
        self.assertEqual(handoff["task_id"], "task-a")
        self.assertEqual(self.ledger.handoff_path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.ledger.report()["handoff"], "available")

    def test_corrupt_ledger_fails_closed(self):
        self.ledger.root.mkdir(parents=True)
        self.ledger.path.write_text("not json")
        with self.assertRaisesRegex(ValueError, "invalid context ledger"):
            self.ledger.report()


if __name__ == "__main__":
    unittest.main()
