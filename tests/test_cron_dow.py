"""Issue #69: cron 0.16 Sunday=1 DOW helper and template lint."""
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from buzz_team.cron_dow import (
    CronDowError,
    collect_warnings,
    cron_has_numeric_dow,
    explain_cst_weekdays,
    extract_crons,
    format_weekdays,
    iter_template_paths,
    lint_template_paths,
    next_fire_times,
    normalize_cron,
    replace_schedule_cron,
    utc_ordinal,
)

ROOT = Path(__file__).resolve().parents[1]
UTC = timezone.utc
GOLDEN_START = datetime(2026, 10, 1, 2, 30, tzinfo=UTC)  # 2026-10-01 10:30 CST

BEFORE_FIRES = [
    (2026, 10, 4, "Sun"),
    (2026, 10, 5, "Mon"),
    (2026, 10, 6, "Tue"),
    (2026, 10, 7, "Wed"),
    (2026, 10, 8, "Thu"),
    (2026, 10, 11, "Sun"),
    (2026, 10, 12, "Mon"),
    (2026, 10, 13, "Tue"),
    (2026, 10, 14, "Wed"),
    (2026, 10, 15, "Thu"),
    (2026, 10, 18, "Sun"),
    (2026, 10, 19, "Mon"),
    (2026, 10, 20, "Tue"),
    (2026, 10, 21, "Wed"),
]
AFTER_FIRES = [
    (2026, 10, 2, "Fri"),
    (2026, 10, 5, "Mon"),
    (2026, 10, 6, "Tue"),
    (2026, 10, 7, "Wed"),
    (2026, 10, 8, "Thu"),
    (2026, 10, 9, "Fri"),
    (2026, 10, 12, "Mon"),
    (2026, 10, 13, "Tue"),
    (2026, 10, 14, "Wed"),
    (2026, 10, 15, "Thu"),
    (2026, 10, 16, "Fri"),
    (2026, 10, 19, "Mon"),
    (2026, 10, 20, "Tue"),
    (2026, 10, 21, "Wed"),
]


class NormalizeAndMapTests(unittest.TestCase):
    def test_normalize_adds_seconds_and_year(self):
        self.assertEqual(normalize_cron("0 1 * * 1-5"), "0 0 1 * * 1-5 *")
        self.assertEqual(normalize_cron("0 1 * * MON-FRI"), "0 0 1 * * MON-FRI *")

    def test_sunday_is_one(self):
        sunday = datetime(2026, 10, 4, 1, 0, tzinfo=UTC)
        self.assertEqual(utc_ordinal(sunday), 1)
        self.assertEqual(utc_ordinal(datetime(2026, 10, 5, 1, 0, tzinfo=UTC)), 2)
        self.assertEqual(utc_ordinal(datetime(2026, 10, 10, 1, 0, tzinfo=UTC)), 7)

    def test_zero_and_eight_rejected(self):
        with self.assertRaisesRegex(CronDowError, "greater than or equal to 1"):
            explain_cst_weekdays("0 1 * * 0")
        with self.assertRaisesRegex(CronDowError, "less than or equal to 7"):
            explain_cst_weekdays("0 1 * * 8")


class NumericWarnTests(unittest.TestCase):
    def test_numeric_sample_lists_one_warning(self):
        warnings = collect_warnings([("sample", 'cron: "0 1 * * 1-5"')])
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0]["dow_field"], "1-5")
        self.assertTrue(cron_has_numeric_dow("0 1 * * 1-5"))

    def test_named_or_star_lists_zero_warnings(self):
        warnings = collect_warnings([
            ("named", 'cron: "0 1 * * MON-FRI"'),
            ("star", 'cron: "30 1 * * *"'),
            ("mixed-case", 'cron: "0 1 * * mon-fri"'),
        ])
        self.assertEqual(warnings, [])
        self.assertFalse(cron_has_numeric_dow("0 1 * * MON-FRI"))
        self.assertFalse(cron_has_numeric_dow("30 1 * * *"))


class CstWeekdayTests(unittest.TestCase):
    def test_one_five_is_sunday_through_thursday(self):
        info = explain_cst_weekdays("0 1 * * 1-5")
        self.assertEqual(info["utc_weekdays"], "SUN,MON,TUE,WED,THU")
        self.assertEqual(info["slots"][0]["cst"], "09:00")
        self.assertEqual(info["slots"][0]["cst_weekdays"], "SUN,MON,TUE,WED,THU")
        self.assertFalse(info["utc_date_differs"])

    def test_mon_fri_names_are_monday_through_friday(self):
        for expr in ("0 1 * * MON-FRI", "0 1 * * mon-fri", "0 1 * * Mon-Fri"):
            info = explain_cst_weekdays(expr)
            self.assertEqual(info["utc_weekdays"], "MON,TUE,WED,THU,FRI")
            self.assertEqual(info["slots"][0]["cst_weekdays"], "MON,TUE,WED,THU,FRI")

    def test_timezone_overlay_shifts_cst_weekday(self):
        # Issue #69 L1 section 3: CST 07:30 is UTC 23:30 previous calendar day.
        wrong = explain_cst_weekdays("30 23 * * MON-FRI")
        self.assertEqual(wrong["slots"][0]["cst_weekdays"], "TUE,WED,THU,FRI,SAT")
        self.assertTrue(wrong["utc_date_differs"])
        right = explain_cst_weekdays("30 23 * * SUN-THU")
        self.assertEqual(right["slots"][0]["cst_weekdays"], "MON,TUE,WED,THU,FRI")

    def test_seven_is_saturday(self):
        info = explain_cst_weekdays("0 1 * * 7")
        self.assertEqual(info["utc_weekdays"], "SAT")

    def test_one_through_seven_is_every_day(self):
        info = explain_cst_weekdays("0 1 * * 1-7")
        self.assertEqual(info["utc_weekdays"], "SUN,MON,TUE,WED,THU,FRI,SAT")


class GoldenFireTests(unittest.TestCase):
    def test_before_1_5_matches_issue_l1_section_3(self):
        fires = next_fire_times("0 1 * * 1-5", GOLDEN_START, 14)
        self.assertEqual(len(fires), 14)
        names = []
        for fire, (year, month, day, name) in zip(fires, BEFORE_FIRES):
            self.assertEqual(fire, datetime(year, month, day, 1, 0, tzinfo=UTC))
            names.append(fire.strftime("%a"))
            self.assertEqual(fire.strftime("%a"), name)
        self.assertNotIn("Fri", names)
        self.assertEqual(names.count("Sun"), 3)

    def test_after_mon_fri_matches_issue_l1_section_3(self):
        fires = next_fire_times("0 1 * * MON-FRI", GOLDEN_START, 14)
        self.assertEqual(len(fires), 14)
        names = []
        for fire, (year, month, day, name) in zip(fires, AFTER_FIRES):
            self.assertEqual(fire, datetime(year, month, day, 1, 0, tzinfo=UTC))
            names.append(fire.strftime("%a"))
            self.assertEqual(fire.strftime("%a"), name)
        self.assertTrue(all(name in {"Mon", "Tue", "Wed", "Thu", "Fri"} for name in names))
        self.assertNotIn("Sun", names)
        self.assertEqual(format_weekdays({2, 3, 4, 5, 6}), "MON,TUE,WED,THU,FRI")


class ReplaceCronTests(unittest.TestCase):
    def test_replaces_single_cron(self):
        text = 'trigger:\n  cron: "0 1 * * 1-5"\n'
        out = replace_schedule_cron(text, "0 1 * * MON-FRI", expect="0 1 * * 1-5")
        self.assertEqual(extract_crons(out), ["0 1 * * MON-FRI"])

    def test_rejects_unexpected_current_cron(self):
        with self.assertRaises(CronDowError):
            replace_schedule_cron('cron: "0 1 * * MON-FRI"\n', "0 1 * * MON-FRI", expect="0 1 * * 1-5")


class TemplateLintTests(unittest.TestCase):
    def test_issue_38_and_69_templates_use_names(self):
        warnings = lint_template_paths(ROOT)
        self.assertEqual(warnings, [], warnings)
        paths = iter_template_paths(ROOT)
        self.assertTrue(any(path.name == "workflow.yaml" and "issue-38" in path.parts for path in paths))
        self.assertTrue(any("issue-69" in path.parts for path in paths))
        for path in paths:
            self.assertIn('cron: "0 1 * * MON-FRI"', path.read_text())

    def test_lint_fails_when_numeric_dow_returns(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            target = root / "docs" / "issue-38" / "after"
            target.mkdir(parents=True)
            (target / "workflow.yaml").write_text(
                'name: x\ntrigger:\n  cron: "0 1 * * 1-5"\n'
            )
            warnings = lint_template_paths(root)
            self.assertEqual(len(warnings), 1)
            self.assertEqual(warnings[0]["dow_field"], "1-5")


if __name__ == "__main__":
    unittest.main()
