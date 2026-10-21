"""Inspect cron weekday fields using relay cron 0.16 Sunday=1 semantics.

Documented algorithm (not a vendor copy of cron 0.16 source). Faithful to the
mapping proven on Issue #69 L1 section 3:

* 5-field: ``min hour dom month dow``
* 6-field: ``sec min hour dom month dow`` (year appended as ``*``)
* 7-field: ``sec min hour dom month dow year``
* Upstream ``normalize_cron`` only prepends seconds ``0`` and appends year ``*``;
  the DOW field is passed through unchanged.
* DOW ordinals: SUN=1, MON=2, TUE=3, WED=4, THU=5, FRI=6, SAT=7. Range is 1–7.
  Digit ``0`` is rejected (``Days of Week must be greater than or equal to 1``).
* Names are case-insensitive. Prefer names over digits: digits mean Sunday=1
  here, which is not the common 0/7=Sunday convention.
* CST = UTC+8. If the fire clock time falls in CST 00:00–07:59, the CST
  weekday is the next UTC weekday.

This module is pure: no Desktop inventory, no workflow DB, no secrets.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
from typing import Iterable

CST = timezone(timedelta(hours=8))
UTC = timezone.utc

DOW_NAMES = ("SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT")
NAME_TO_ORDINAL = {name: index + 1 for index, name in enumerate(DOW_NAMES)}
ORDINAL_TO_NAME = {index + 1: name for index, name in enumerate(DOW_NAMES)}
DOW_MIN = 1
DOW_MAX = 7

CRON_LINE = re.compile(
    r"""(?P<prefix>^|\n)(?P<indent>[ \t]*)cron:\s*(?P<q>["'])(?P<expr>[^"']+)(?P=q)""",
    re.MULTILINE,
)
NUMERIC_TOKEN = re.compile(r"\d+")

# Templates that must use weekday names after #69. Historical smoke JSON is out.
TEMPLATE_GLOBS = (
    "docs/issue-38/before/**/*.yaml",
    "docs/issue-38/after/**/*.yaml",
    "docs/issue-69/**/*.yaml",
)
TEMPLATE_EXCLUDE_PARTS = ("/examples/", "/evidence/", "/smoke/")


class CronDowError(ValueError):
    """Invalid cron expression or DOW field under cron 0.16 rules."""


def normalize_cron(expr: str) -> str:
    """Match upstream normalize_cron: add seconds and year only."""
    fields = expr.split()
    if len(fields) == 5:
        return "0 " + expr + " *"
    if len(fields) == 6:
        return expr + " *"
    if len(fields) == 7:
        return expr
    raise CronDowError(f"cron must have 5, 6, or 7 fields, got {len(fields)}: {expr!r}")


def split_cron(expr: str) -> tuple[str, ...]:
    return tuple(normalize_cron(expr).split())


def dow_field(expr: str) -> str:
    return split_cron(expr)[5]


def _parse_ordinal(token: str, *, allow_star: bool = False) -> int | None:
    text = token.strip()
    if allow_star and text == "*":
        return None
    if text.isdigit():
        value = int(text)
        if value < DOW_MIN:
            raise CronDowError("Days of Week must be greater than or equal to 1")
        if value > DOW_MAX:
            raise CronDowError("Days of Week must be less than or equal to 7")
        return value
    name = text.upper()
    if name in NAME_TO_ORDINAL:
        return NAME_TO_ORDINAL[name]
    raise CronDowError(f"invalid DOW token {token!r}")


def expand_dow(field: str) -> frozenset[int]:
    """Expand a cron 0.16 DOW field to Sunday=1 ordinals."""
    if field in {"*", "?"}:
        return frozenset(range(DOW_MIN, DOW_MAX + 1))
    values: set[int] = set()
    for part in field.split(","):
        text = part.strip()
        if not text:
            raise CronDowError("empty DOW list item")
        step = 1
        if "/" in text:
            text, step_text = text.split("/", 1)
            if not step_text.isdigit() or int(step_text) < 1:
                raise CronDowError(f"invalid DOW step {part!r}")
            step = int(step_text)
        if text == "*":
            start, end = DOW_MIN, DOW_MAX
        elif "-" in text:
            left, right = text.split("-", 1)
            start = _parse_ordinal(left)
            end = _parse_ordinal(right)
            if start is None or end is None or start > end:
                raise CronDowError(f"invalid DOW range {part!r}")
        else:
            start = end = _parse_ordinal(text)
        assert start is not None and end is not None
        values.update(range(start, end + 1, step))
    return frozenset(values)


def expand_unit(field: str, minimum: int, maximum: int) -> frozenset[int]:
    """Expand a non-DOW cron field (minute/hour). Names are not accepted."""
    if field in {"*", "?"}:
        return frozenset(range(minimum, maximum + 1))
    values: set[int] = set()
    for part in field.split(","):
        text = part.strip()
        step = 1
        if "/" in text:
            text, step_text = text.split("/", 1)
            if not step_text.isdigit() or int(step_text) < 1:
                raise CronDowError(f"invalid step {part!r}")
            step = int(step_text)
        if text == "*":
            start, end = minimum, maximum
        elif "-" in text:
            left, right = text.split("-", 1)
            start, end = int(left), int(right)
        else:
            start = end = int(text)
        if start < minimum or end > maximum or start > end:
            raise CronDowError(f"value out of range {part!r}")
        values.update(range(start, end + 1, step))
    return frozenset(values)


def dow_has_numeric(field: str) -> bool:
    """True when the DOW field contains any digit token."""
    return bool(NUMERIC_TOKEN.search(field))


def cron_has_numeric_dow(expr: str) -> bool:
    return dow_has_numeric(dow_field(expr))


def utc_ordinal(moment: datetime) -> int:
    """Python isoweekday Monday=1..Sunday=7 → cron 0.16 Sunday=1."""
    return (moment.astimezone(UTC).isoweekday() % 7) + 1


def cst_day_shift(utc_hour: int, utc_minute: int) -> tuple[int, int, int]:
    """Return (cst_hour, cst_minute, weekday_shift) for a UTC clock time."""
    cst_minute = utc_minute
    cst_hour = utc_hour + 8
    shift = 0
    if cst_hour >= 24:
        cst_hour -= 24
        shift = 1
    return cst_hour, cst_minute, shift


def shift_ordinals(ordinals: Iterable[int], shift: int) -> frozenset[int]:
    return frozenset(((value - 1 + shift) % 7) + 1 for value in ordinals)


def format_weekdays(ordinals: Iterable[int]) -> str:
    order = sorted(set(ordinals))
    return ",".join(ORDINAL_TO_NAME[value] for value in order)


def explain_cst_weekdays(expr: str) -> dict:
    """Describe UTC and CST weekdays for a schedule cron.

    For hour lists, each hour is explained separately. A CST time in
    00:00–07:59 also sets ``utc_date_differs``.
    """
    fields = split_cron(expr)
    if fields[3] != "*" or fields[4] != "*":
        raise CronDowError("CST weekday explanation requires DOM=* and month=*")
    hours = sorted(expand_unit(fields[2], 0, 23))
    minutes = sorted(expand_unit(fields[1], 0, 59))
    if len(minutes) != 1:
        raise CronDowError("CST weekday explanation requires a single minute")
    utc_days = expand_dow(fields[5])
    slots = []
    utc_date_differs = False
    for hour in hours:
        cst_hour, cst_minute, shift = cst_day_shift(hour, minutes[0])
        if shift:
            utc_date_differs = True
        slots.append({
            "utc": f"{hour:02d}:{minutes[0]:02d}",
            "cst": f"{cst_hour:02d}:{cst_minute:02d}",
            "utc_weekdays": format_weekdays(utc_days),
            "cst_weekdays": format_weekdays(shift_ordinals(utc_days, shift)),
            "utc_date_differs": bool(shift),
        })
    return {
        "cron": expr,
        "normalized": " ".join(fields),
        "numeric_dow": cron_has_numeric_dow(expr),
        "dow_field": fields[5],
        "utc_weekdays": format_weekdays(utc_days),
        "utc_date_differs": utc_date_differs,
        "slots": slots,
    }


def next_fire_times(expr: str, start: datetime, count: int = 14) -> list[datetime]:
    """Next UTC fire instants for DOM=* month=* schedules (Issue #69 golden path)."""
    if count < 1:
        raise CronDowError("count must be >= 1")
    fields = split_cron(expr)
    if fields[3] != "*" or fields[4] != "*":
        raise CronDowError("next_fire_times requires DOM=* and month=*")
    hours = sorted(expand_unit(fields[2], 0, 23))
    minutes = sorted(expand_unit(fields[1], 0, 59))
    days = expand_dow(fields[5])
    origin = start.astimezone(UTC)
    day = origin.date()
    found: list[datetime] = []
    # Two weeks of candidates is enough for 14 weekday fires; cap the walk.
    for _ in range(400):
        for hour in hours:
            for minute in minutes:
                candidate = datetime(day.year, day.month, day.day, hour, minute, tzinfo=UTC)
                if candidate <= origin:
                    continue
                if utc_ordinal(candidate) in days:
                    found.append(candidate)
                    if len(found) == count:
                        return found
        day += timedelta(days=1)
    raise CronDowError(f"could not find {count} fire times for {expr!r}")


def extract_crons(text: str) -> list[str]:
    return [match.group("expr") for match in CRON_LINE.finditer(text)]


def replace_schedule_cron(yaml_text: str, new_cron: str, *, expect: str | None = None) -> str:
    """Replace the single ``cron:`` value in a workflow YAML body."""
    matches = list(CRON_LINE.finditer(yaml_text))
    if len(matches) != 1:
        raise CronDowError(f"expected exactly 1 cron field, found {len(matches)}")
    current = matches[0].group("expr")
    if expect is not None and current != expect:
        raise CronDowError(f"live cron is {current!r}, expected {expect!r}")
    start, end = matches[0].span("expr")
    return yaml_text[:start] + new_cron + yaml_text[end:]


def warning_for_cron(expr: str, *, source: str = "") -> dict | None:
    if not cron_has_numeric_dow(expr):
        return None
    try:
        explanation = explain_cst_weekdays(expr)
    except CronDowError as exc:
        explanation = {"error": str(exc)}
    return {
        "source": source,
        "cron": expr,
        "dow_field": dow_field(expr),
        "detail": (
            f"numeric DOW {dow_field(expr)!r} uses cron 0.16 Sunday=1 "
            f"(1=SUN … 7=SAT); prefer weekday names"
        ),
        "explanation": explanation,
    }


def iter_template_paths(root: Path) -> list[Path]:
    paths: list[Path] = []
    for pattern in TEMPLATE_GLOBS:
        for path in root.glob(pattern):
            text = path.as_posix()
            if any(part in f"/{text}/" or part in text for part in TEMPLATE_EXCLUDE_PARTS):
                continue
            if any(exclude.strip("/") in path.parts for exclude in ("examples", "evidence", "smoke")):
                continue
            paths.append(path)
    return sorted(set(paths))


def lint_template_paths(root: Path) -> list[dict]:
    warnings: list[dict] = []
    for path in iter_template_paths(root):
        for expr in extract_crons(path.read_text()):
            item = warning_for_cron(expr, source=str(path.relative_to(root)))
            if item:
                warnings.append(item)
    return warnings


def collect_warnings(texts: Iterable[tuple[str, str]]) -> list[dict]:
    """``texts`` is (source, body) pairs of YAML or cron-bearing text."""
    warnings: list[dict] = []
    for source, body in texts:
        stripped = body.strip()
        if not stripped:
            continue
        if "cron:" in body:
            exprs = extract_crons(body)
        else:
            exprs = [stripped]
        for expr in exprs:
            item = warning_for_cron(expr, source=source)
            if item:
                warnings.append(item)
    return warnings
