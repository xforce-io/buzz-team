"""Issue #68: expected fires vs fires + pmset + cursor. Fixtures only."""
from datetime import timedelta
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from buzz_team.cron_dow import UTC
from buzz_team.doctor import inspect_inventory
from buzz_team.missed_fires import (
    DISPLAY_SLEEP,
    LABEL_AWAKE,
    LABEL_PMSET_ROLLED,
    LABEL_SLEEP,
    MissedFiresError,
    covering_sleep,
    enumerate_expected_fires,
    load_fires,
    load_workflows,
    parse_iso,
    parse_pmset,
    read_cursor_file,
    reconcile,
    write_cursor_file,
)

ROOT = Path(__file__).resolve().parents[1]
ISSUE = ROOT / "docs" / "issue-68"
FIXTURE = ISSUE / "fixtures" / "0930-replay"
CLI = ISSUE / "check-missed-fires.py"
DOCTOR = ROOT / "src" / "buzz_team" / "doctor.py"
BUZZ_HEALTH = ROOT / "docs" / "issue-58" / "bin" / "buzz-health"

EVENING_IDS = [
    "97152434-1ec3-4b51-b55d-4159ecec4162",
    "cd608a18-6254-41cc-a0d7-c23879b1fe79",
    "2d75251c-48bc-46b7-9bec-8e06d2989c85",
    "50d27eb7-e768-4401-af80-8fc95b5f0bae",
]
F5 = "f5cc62c0-3756-419e-8a3f-8e694df2e93e"
BRIEF_0930 = "7d90ca75-51a1-40a6-8966-8fffc9c523c3"

SLEEP_1716 = "16:58:00 Maintenance Sleep → 17:16:32 Wake"
SLEEP_1735 = "17:17:44 Clamshell Sleep → 17:35:33 Wake"


def _load_base():
    workflows = load_workflows(json.loads((FIXTURE / "workflows.json").read_text()))
    fires = load_fires(json.loads((FIXTURE / "fires.json").read_text()))
    intervals, horizon = parse_pmset((FIXTURE / "pmset.txt").read_text())
    return workflows, fires, intervals, horizon


def _run(args, env=None):
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _fixture_args(*extra):
    return [
        "--workflows", str(FIXTURE / "workflows.json"),
        "--fires", str(FIXTURE / "fires.json"),
        "--pmset", str(FIXTURE / "pmset.txt"),
        *extra,
    ]


class EveningReplayTests(unittest.TestCase):
    def test_four_sleep_misses_in_how_order(self):
        workflows, fires, intervals, horizon = _load_base()
        result = reconcile(
            workflows=workflows,
            fires=fires,
            intervals=intervals,
            pmset_horizon=horizon,
            now=parse_iso("2026-09-30T17:40:00+08:00", field="now"),
            cursor_before=None,
            since=parse_iso("2026-09-30T08:50:00+08:00", field="since"),
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["counts"]["miss_sleep"], 4)
        self.assertEqual(result["counts"]["miss_awake"], 0)
        ids = [row["definition_id"] for row in result["misses"]]
        self.assertEqual(ids, EVENING_IDS)
        for row in result["misses"]:
            self.assertEqual(row["label"], LABEL_SLEEP)
            self.assertEqual(row["display"], DISPLAY_SLEEP)
        self.assertEqual(result["misses"][0]["planned_at_cst"], "2026-09-30T17:00:00+08:00")
        self.assertEqual(result["misses"][1]["planned_at_cst"], "2026-09-30T17:10:00+08:00")
        self.assertEqual(result["misses"][2]["planned_at_cst"], "2026-09-30T17:15:00+08:00")
        self.assertEqual(result["misses"][3]["planned_at_cst"], "2026-09-30T17:30:00+08:00")
        self.assertEqual(result["misses"][0]["sleep_interval"], SLEEP_1716)
        self.assertEqual(result["misses"][1]["sleep_interval"], SLEEP_1716)
        self.assertEqual(result["misses"][2]["sleep_interval"], SLEEP_1716)
        self.assertEqual(result["misses"][3]["sleep_interval"], SLEEP_1735)

    def test_evening_cli_exits_zero(self):
        proc = _run(_fixture_args(
            "--since", "2026-09-30T08:50:00+08:00",
            "--now", "2026-09-30T17:40:00+08:00",
            "--no-advance",
        ))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(data["counts"]["miss_sleep"], 4)
        self.assertEqual([row["display"] for row in data["misses"]], [DISPLAY_SLEEP] * 4)


class MorningReplayTests(unittest.TestCase):
    def test_morning_miss_awake_zero(self):
        workflows, fires, intervals, horizon = _load_base()
        result = reconcile(
            workflows=workflows,
            fires=fires,
            intervals=intervals,
            pmset_horizon=horizon,
            now=parse_iso("2026-09-30T09:35:00+08:00", field="now"),
            cursor_before=None,
            since=parse_iso("2026-09-30T08:40:00+08:00", field="since"),
        )
        self.assertEqual(result["counts"]["miss_awake"], 0)
        self.assertEqual(result["counts"]["fired_ok"], 6)
        self.assertEqual(result["misses"], [])
        self.assertTrue(result["ok"])


class AwakeMissTests(unittest.TestCase):
    def test_drop_one_morning_fire_is_awake_miss(self):
        workflows, _, intervals, horizon = _load_base()
        fires = load_fires(json.loads((FIXTURE / "fires-morning-awake-miss.json").read_text()))
        result = reconcile(
            workflows=workflows,
            fires=fires,
            intervals=intervals,
            pmset_horizon=horizon,
            now=parse_iso("2026-09-30T09:35:00+08:00", field="now"),
            cursor_before=None,
            since=parse_iso("2026-09-30T08:40:00+08:00", field="since"),
        )
        self.assertEqual(result["counts"]["miss_awake"], 1)
        self.assertEqual(result["counts"]["miss_sleep"], 0)
        self.assertFalse(result["ok"])
        self.assertEqual(result["misses"][0]["definition_id"], BRIEF_0930)
        self.assertEqual(result["misses"][0]["label"], LABEL_AWAKE)

    def test_evening_sleep_rows_are_not_awake(self):
        workflows, fires, intervals, horizon = _load_base()
        result = reconcile(
            workflows=workflows,
            fires=fires,
            intervals=intervals,
            pmset_horizon=horizon,
            now=parse_iso("2026-09-30T17:40:00+08:00", field="now"),
            cursor_before=None,
            since=parse_iso("2026-09-30T08:50:00+08:00", field="since"),
        )
        self.assertEqual(result["counts"]["miss_awake"], 0)
        self.assertTrue(all(row["label"] == LABEL_SLEEP for row in result["misses"]))

    def test_awake_cli_exits_two(self):
        proc = _run([
            "--workflows", str(FIXTURE / "workflows.json"),
            "--fires", str(FIXTURE / "fires-morning-awake-miss.json"),
            "--pmset", str(FIXTURE / "pmset.txt"),
            "--since", "2026-09-30T08:40:00+08:00",
            "--now", "2026-09-30T09:35:00+08:00",
            "--no-advance",
        ])
        self.assertEqual(proc.returncode, 2, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(data["counts"]["miss_awake"], 1)


class PmsetHorizonTests(unittest.TestCase):
    def test_before_horizon_is_rolled_not_awake(self):
        workflows, _, intervals, horizon = _load_base()
        result = reconcile(
            workflows=workflows,
            fires=[],
            intervals=intervals,
            pmset_horizon=horizon,
            now=parse_iso("2026-09-29T17:40:00+08:00", field="now"),
            cursor_before=None,
            since=parse_iso("2026-09-29T16:50:00+08:00", field="since"),
        )
        self.assertGreaterEqual(result["counts"]["miss_pmset_rolled"], 4)
        self.assertEqual(result["counts"]["miss_awake"], 0)
        self.assertTrue(all(row["label"] == LABEL_PMSET_ROLLED for row in result["misses"]))
        self.assertTrue(result["ok"])

    def test_darkwake_does_not_end_sleep(self):
        _, _, intervals, _ = _load_base()
        planned = parse_iso("2026-09-30T17:00:00+08:00", field="planned")
        cover = covering_sleep(planned, intervals)
        self.assertIsNotNone(cover)
        self.assertEqual(cover.display(), SLEEP_1716)


class FridaySkipTests(unittest.TestCase):
    def test_f5cc62c0_friday_before_69_is_not_expected(self):
        workflows, _, intervals, horizon = _load_base()
        friday = next(row for row in workflows if row["id"] == F5)
        self.assertEqual(friday["cron"], "0 1 * * 1-5")
        window_start = parse_iso("2026-10-02T08:50:00+08:00", field="since")
        window_end = parse_iso("2026-10-02T09:03:00+08:00", field="end")
        planned = enumerate_expected_fires(workflows, window_start, window_end)
        ids = [item.definition_id for item in planned]
        self.assertNotIn(F5, ids)
        self.assertIn("97152434-1ec3-4b51-b55d-4159ecec4162", ids)
        result = reconcile(
            workflows=workflows,
            fires=[],
            intervals=intervals,
            pmset_horizon=horizon,
            now=parse_iso("2026-10-02T09:05:00+08:00", field="now"),
            cursor_before=None,
            since=window_start,
        )
        miss_ids = [row["definition_id"] for row in result["misses"]]
        self.assertNotIn(F5, miss_ids)


class CursorJumpTests(unittest.TestCase):
    def test_forward_jump_lists_gap_and_advances_to_now_minus_grace(self):
        workflows, fires, intervals, horizon = _load_base()
        t0 = parse_iso("2026-09-30T16:50:00+08:00", field="cursor")
        now = t0 + timedelta(hours=3)
        result = reconcile(
            workflows=workflows,
            fires=fires,
            intervals=intervals,
            pmset_horizon=horizon,
            now=now,
            cursor_before=t0,
        )
        self.assertEqual(result["counts"]["miss_sleep"], 4)
        self.assertEqual([row["definition_id"] for row in result["misses"]], EVENING_IDS)
        self.assertEqual(parse_iso(result["cursor_after"], field="cursor_after"), now.astimezone(UTC) - timedelta(seconds=120))
        self.assertEqual(parse_iso(result["cursor_before"], field="cursor_before"), t0.astimezone(UTC))


class CursorRewindTests(unittest.TestCase):
    def test_rewind_skips_and_does_not_retreat(self):
        workflows, fires, intervals, horizon = _load_base()
        cursor = parse_iso("2026-09-30T09:38:00+00:00", field="cursor")
        now = parse_iso("2026-09-30T09:30:00+00:00", field="now")
        result = reconcile(
            workflows=workflows,
            fires=fires,
            intervals=intervals,
            pmset_horizon=horizon,
            now=now,
            cursor_before=cursor,
        )
        self.assertTrue(result["skipped_clock_rewind"])
        self.assertEqual(result["cursor_before"], result["cursor_after"])
        self.assertEqual(result["cursor_after"], "2026-09-30T09:38:00+00:00")
        self.assertEqual(result["misses"], [])
        self.assertTrue(result["ok"])

    def test_rewind_does_not_rewrite_cursor_file(self):
        workflows, fires, intervals, horizon = _load_base()
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "cursor.json"
            original = parse_iso("2026-09-30T09:38:00+00:00", field="cursor")
            write_cursor_file(path, reconciled_to=original, updated_at=original, grace_seconds=120)
            proc = _run(_fixture_args(
                "--cursor-file", str(path),
                "--now", "2026-09-30T09:30:00+00:00",
                "--no-advance",
            ))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            data = json.loads(proc.stdout)
            self.assertTrue(data["skipped_clock_rewind"])
            self.assertEqual(read_cursor_file(path), original)


class LongSleepTests(unittest.TestCase):
    def test_hours_long_window_lists_all_misses_once(self):
        workflows, fires, intervals, horizon = _load_base()
        result = reconcile(
            workflows=workflows,
            fires=fires,
            intervals=intervals,
            pmset_horizon=horizon,
            now=parse_iso("2026-09-30T17:40:00+08:00", field="now"),
            cursor_before=parse_iso("2026-09-30T08:50:00+08:00", field="cursor"),
        )
        self.assertEqual(result["counts"]["miss_sleep"], 4)
        self.assertEqual(result["counts"]["miss_awake"], 0)
        self.assertEqual([row["definition_id"] for row in result["misses"]], EVENING_IDS)
        self.assertEqual(len(result["misses"]), 4)


class GraceLateTests(unittest.TestCase):
    def test_slot_inside_grace_is_not_a_miss(self):
        workflows, _, intervals, horizon = _load_base()
        fires = load_fires(json.loads((FIXTURE / "fires-morning-awake-miss.json").read_text()))
        result = reconcile(
            workflows=workflows,
            fires=fires,
            intervals=intervals,
            pmset_horizon=horizon,
            now=parse_iso("2026-09-30T09:31:00+08:00", field="now"),
            cursor_before=None,
            since=parse_iso("2026-09-30T08:40:00+08:00", field="since"),
        )
        self.assertEqual(result["counts"]["miss_awake"], 0)
        self.assertGreaterEqual(result["counts"]["skipped_not_due"], 1)
        self.assertNotIn(BRIEF_0930, [row["definition_id"] for row in result["misses"]])
        self.assertTrue(result["ok"])


class NoCursorTests(unittest.TestCase):
    def test_no_cursor_no_since_is_nonzero(self):
        workflows, fires, intervals, horizon = _load_base()
        with self.assertRaises(MissedFiresError):
            reconcile(
                workflows=workflows,
                fires=fires,
                intervals=intervals,
                pmset_horizon=horizon,
                now=parse_iso("2026-09-30T17:40:00+08:00", field="now"),
                cursor_before=None,
            )

    def test_cli_no_cursor_no_since_exits_two(self):
        proc = _run(_fixture_args("--now", "2026-09-30T17:40:00+08:00", "--no-advance"))
        self.assertEqual(proc.returncode, 2)
        self.assertNotEqual(proc.returncode, 1)
        self.assertIn("no cursor and no --since", proc.stderr)


class CursorAdvanceFileTests(unittest.TestCase):
    def test_successful_run_writes_now_minus_grace(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "cursor.json"
            proc = _run(_fixture_args(
                "--since", "2026-09-30T08:50:00+08:00",
                "--now", "2026-09-30T17:40:00+08:00",
                "--cursor-file", str(path),
            ))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            written = json.loads(path.read_text())
            self.assertEqual(written["reconciled_to"], "2026-09-30T09:38:00+00:00")
            self.assertEqual(written["grace_seconds"], 120)

    def test_no_advance_does_not_write(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "cursor.json"
            proc = _run(_fixture_args(
                "--since", "2026-09-30T08:50:00+08:00",
                "--now", "2026-09-30T17:40:00+08:00",
                "--cursor-file", str(path),
                "--no-advance",
            ))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertFalse(path.exists())


class FixtureIsolationTests(unittest.TestCase):
    def test_fixture_mode_does_not_call_live_tools(self):
        env = {**os.environ, "PATH": str(Path(sys.executable).parent)}
        proc = _run(_fixture_args(
            "--since", "2026-09-30T08:50:00+08:00",
            "--now", "2026-09-30T17:40:00+08:00",
            "--no-advance",
        ), env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_partial_fixture_does_not_fall_back_to_live(self):
        proc = _run([
            "--workflows", str(FIXTURE / "workflows.json"),
            "--since", "2026-09-30T08:50:00+08:00",
            "--now", "2026-09-30T17:40:00+08:00",
            "--no-advance",
        ])
        self.assertEqual(proc.returncode, 2)
        self.assertIn("will not substitute live", proc.stderr)

    def test_non_dom_cron_fails_fast(self):
        workflows, fires, intervals, horizon = _load_base()
        workflows = [dict(workflows[0], cron="0 1 15 * *")]
        with self.assertRaises(MissedFiresError):
            reconcile(
                workflows=workflows,
                fires=fires,
                intervals=intervals,
                pmset_horizon=horizon,
                now=parse_iso("2026-09-30T09:35:00+08:00", field="now"),
                cursor_before=None,
                since=parse_iso("2026-09-30T08:40:00+08:00", field="since"),
            )


class DoctorBoundaryTests(unittest.TestCase):
    def test_doctor_source_has_no_workflow_or_pmset(self):
        text = DOCTOR.read_text()
        self.assertNotIn("missed_fires", text)
        self.assertNotIn("pmset", text)
        self.assertNotIn("postgres", text)
        self.assertNotIn("scheduled_workflow", text)

    def test_doctor_inventory_still_passes(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "managed-agents.json"
            path.write_text(json.dumps([{
                "acp_command": "buzz-acp",
                "agent_command": "grok",
                "pubkey": "a" * 64,
                "relay_url": "ws://127.0.0.1:3000",
            }]))
            checks = inspect_inventory(path)
        self.assertEqual(checks[0]["status"], "pass")

    def test_buzz_health_is_untouched_sibling(self):
        text = BUZZ_HEALTH.read_text()
        self.assertNotIn("missed_fires", text)
        self.assertNotIn("scheduled_workflow_fires", text)
        self.assertNotIn("issue-68", text)


class S3StubTests(unittest.TestCase):
    def test_readme_marks_s3_stub(self):
        text = (ISSUE / "README.md").read_text()
        self.assertIn("S3 stub", text)
        self.assertNotIn("workflows trigger", text.split("## S3 stub")[1])


if __name__ == "__main__":
    unittest.main()
