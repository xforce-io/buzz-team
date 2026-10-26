"""Expected scheduled fires vs fire rows, pmset sleep, and reconcile cursor.

Pure functions only: no Desktop inventory, no postgres, no live ``pmset``,
no secrets. Sibling CLI in ``docs/issue-68/check-missed-fires.py`` loads
fixtures or read-only SQL. Cron weekday semantics come from ``cron_dow``
(cron 0.16, Sunday=1). Python names and JSON keys stay snake_case.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import re
from typing import Iterable

from .cron_dow import CST, UTC, CronDowError, next_fire_times

GRACE_SECONDS = 120
WAKE_GRACE_SECONDS = 60
LOCAL_COMMUNITY_ID = "14a17e2d-40ae-4182-86c1-7dde01da0f03"
DEFAULT_CURSOR_PATH = Path.home() / "lab" / "buzz" / "var" / "issue68-reconcile-cursor.json"

LABEL_SLEEP = "未知（休眠）"
DISPLAY_SLEEP = "休眠期间"
LABEL_AWAKE = "异常（醒着漏触发）"
LABEL_PMSET_ROLLED = "未知（pmset 已滚动）"

PMSET_LINE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} [+-]\d{4})\s+"
    r"(?P<kind>Sleep|Wake|DarkWake)\b"
    r"(?P<rest>.*)$"
)
SLEEP_REASON = re.compile(r"'([^']+)'")


class MissedFiresError(ValueError):
    """Bad input or unsupported cron for missed-fire reconcile."""


@dataclass(frozen=True)
class SleepInterval:
    start: datetime
    end: datetime | None
    start_reason: str
    end_kind: str | None = None

    def display(self) -> str:
        start_clock = self.start.astimezone(CST).strftime("%H:%M:%S")
        if self.end is None:
            return f"{start_clock} {self.start_reason} → (still sleeping)"
        end_clock = self.end.astimezone(CST).strftime("%H:%M:%S")
        end_label = self.end_kind or "Wake"
        return f"{start_clock} {self.start_reason} → {end_clock} {end_label}"


@dataclass(frozen=True)
class PlannedFire:
    definition_id: str
    name: str
    owner_seat: str
    cron: str
    planned_at: datetime


def parse_iso(value: str | datetime, *, field: str) -> datetime:
    if isinstance(value, datetime):
        moment = value
    else:
        text = value.strip()
        if not text:
            raise MissedFiresError(f"{field} is empty")
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            moment = datetime.fromisoformat(text)
        except ValueError as exc:
            raise MissedFiresError(f"{field} is not ISO-8601: {value!r}") from exc
    if moment.tzinfo is None:
        raise MissedFiresError(f"{field} must include a timezone: {value!r}")
    return moment.astimezone(UTC)


def format_iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat()


def format_cst(moment: datetime) -> str:
    return moment.astimezone(CST).isoformat()


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes"}
    return False


def load_workflows(raw: object) -> list[dict]:
    if isinstance(raw, dict):
        rows = raw.get("workflows", raw.get("items"))
    else:
        rows = raw
    if not isinstance(rows, list):
        raise MissedFiresError("workflows fixture must be a list or {workflows: [...]}")
    workflows: list[dict] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise MissedFiresError(f"workflows[{index}] is not an object")
        definition_id = row.get("id") or row.get("definition_id") or row.get("workflow_id")
        cron = row.get("cron")
        created_at = row.get("created_at")
        if not definition_id or not isinstance(cron, str) or not created_at:
            raise MissedFiresError(f"workflows[{index}] missing id/cron/created_at")
        trigger = row.get("trigger") if isinstance(row.get("trigger"), dict) else {}
        on = trigger.get("on") or row.get("trigger_on") or "schedule"
        if on != "schedule":
            continue
        if not _as_bool(row.get("enabled", True)):
            continue
        if str(row.get("status", "active")) != "active":
            continue
        workflows.append({
            "id": str(definition_id),
            "name": str(row.get("name") or definition_id),
            "owner_seat": str(row.get("owner_seat") or row.get("owner") or ""),
            "cron": cron,
            "created_at": parse_iso(created_at, field=f"workflows[{index}].created_at"),
            "status": "active",
            "enabled": True,
        })
    return workflows


def load_fires(raw: object) -> list[dict]:
    if isinstance(raw, dict):
        rows = raw.get("fires", raw.get("items"))
    else:
        rows = raw
    if not isinstance(rows, list):
        raise MissedFiresError("fires fixture must be a list or {fires: [...]}")
    fires: list[dict] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise MissedFiresError(f"fires[{index}] is not an object")
        workflow_id = row.get("workflow_id") or row.get("definition_id") or row.get("id")
        scheduled_for = row.get("scheduled_for") or row.get("planned_at")
        if not workflow_id or not scheduled_for:
            raise MissedFiresError(f"fires[{index}] missing workflow_id/scheduled_for")
        fires.append({
            "workflow_id": str(workflow_id),
            "scheduled_for": parse_iso(scheduled_for, field=f"fires[{index}].scheduled_for"),
        })
    return fires


def fire_key_set(fires: Iterable[dict]) -> set[tuple[str, datetime]]:
    return {(row["workflow_id"], row["scheduled_for"].astimezone(UTC)) for row in fires}


def parse_pmset_timestamp(text: str) -> datetime:
    stamp = datetime.strptime(text, "%Y-%m-%d %H:%M:%S %z")
    return stamp.astimezone(UTC)


def _sleep_reason(rest: str) -> str:
    match = SLEEP_REASON.search(rest)
    if match:
        return match.group(1)
    return "Sleep"


def parse_pmset(text: str) -> tuple[list[SleepInterval], datetime]:
    """Parse Sleep / Wake / DarkWake lines into coverage intervals.

    A new Sleep while already sleeping starts a new interval (previous ends
    at that Sleep). DarkWake does not end coverage. Only a full Wake does.
    """
    events: list[tuple[datetime, str, str]] = []
    for raw_line in text.splitlines():
        match = PMSET_LINE.match(raw_line.strip())
        if not match:
            continue
        kind = match.group("kind")
        events.append((
            parse_pmset_timestamp(match.group("ts")),
            kind,
            _sleep_reason(match.group("rest")) if kind == "Sleep" else kind,
        ))
    if not events:
        raise MissedFiresError("pmset log has no Sleep/Wake/DarkWake lines")
    events.sort(key=lambda item: item[0])
    horizon = events[0][0]
    intervals: list[SleepInterval] = []
    open_start: datetime | None = None
    open_reason = "Sleep"
    for stamp, kind, reason in events:
        if kind == "DarkWake":
            continue
        if kind == "Sleep":
            if open_start is not None:
                intervals.append(SleepInterval(open_start, stamp, open_reason, "Sleep"))
            open_start = stamp
            open_reason = reason
            continue
        if kind == "Wake" and open_start is not None:
            intervals.append(SleepInterval(open_start, stamp, open_reason, "Wake"))
            open_start = None
    if open_start is not None:
        intervals.append(SleepInterval(open_start, None, open_reason, None))
    return intervals, horizon


def covering_sleep(
    planned_at: datetime,
    intervals: Iterable[SleepInterval],
    *,
    wake_grace_seconds: int = WAKE_GRACE_SECONDS,
) -> SleepInterval | None:
    planned = planned_at.astimezone(UTC)
    grace = timedelta(seconds=wake_grace_seconds)
    for interval in intervals:
        start = interval.start.astimezone(UTC)
        end = interval.end.astimezone(UTC) if interval.end is not None else None
        if end is None:
            if planned >= start:
                return interval
            continue
        if start <= planned < end:
            return interval
        if end <= planned <= end + grace:
            return interval
    return None


def enumerate_fire_times(expr: str, window_start: datetime, window_end: datetime) -> list[datetime]:
    """Planned instants in the half-open window ``(window_start, window_end]``."""
    start = window_start.astimezone(UTC)
    end = window_end.astimezone(UTC)
    if end <= start:
        return []
    found: list[datetime] = []
    cursor = start
    # A week of daily slots is plenty; fail fast if cron cannot produce one.
    for _ in range(400):
        try:
            nxt = next_fire_times(expr, cursor, 1)
        except CronDowError as exc:
            raise MissedFiresError(str(exc)) from exc
        candidate = nxt[0].astimezone(UTC)
        if candidate > end:
            return found
        found.append(candidate)
        cursor = candidate
    raise MissedFiresError(f"could not finish enumerating {expr!r}")


def enumerate_expected_fires(
    workflows: Iterable[dict],
    window_start: datetime,
    window_end: datetime,
) -> list[PlannedFire]:
    planned: list[PlannedFire] = []
    start = window_start.astimezone(UTC)
    end = window_end.astimezone(UTC)
    for row in workflows:
        created_at = row["created_at"]
        if isinstance(created_at, str):
            created_at = parse_iso(created_at, field="created_at")
        for stamp in enumerate_fire_times(row["cron"], start, end):
            if stamp < created_at.astimezone(UTC):
                continue
            planned.append(PlannedFire(
                definition_id=row["id"],
                name=row["name"],
                owner_seat=row["owner_seat"],
                cron=row["cron"],
                planned_at=stamp,
            ))
    planned.sort(key=lambda item: (item.planned_at, item.definition_id))
    return planned


def resolve_window(
    *,
    now: datetime,
    cursor_before: datetime | None,
    since: datetime | None = None,
    grace_seconds: int = GRACE_SECONDS,
) -> dict:
    """Return window bounds or a clock-rewind skip. Fail fast without a left edge."""
    now_utc = now.astimezone(UTC)
    due_until = now_utc - timedelta(seconds=grace_seconds)
    if cursor_before is None:
        if since is None:
            raise MissedFiresError("no cursor and no --since")
        left = since.astimezone(UTC)
        if due_until < left:
            raise MissedFiresError("--since is after now - grace")
        return {
            "skipped_clock_rewind": False,
            "cursor_before": None,
            "cursor_after": due_until,
            "window_start": left,
            "window_end": due_until,
            "now": now_utc,
        }
    left = cursor_before.astimezone(UTC)
    if due_until < left:
        return {
            "skipped_clock_rewind": True,
            "cursor_before": left,
            "cursor_after": left,
            "window_start": left,
            "window_end": due_until,
            "now": now_utc,
        }
    return {
        "skipped_clock_rewind": False,
        "cursor_before": left,
        "cursor_after": due_until,
        "window_start": left,
        "window_end": due_until,
        "now": now_utc,
    }


def _empty_counts() -> dict[str, int]:
    return {
        "fired_ok": 0,
        "miss_sleep": 0,
        "miss_awake": 0,
        "miss_pmset_rolled": 0,
        "skipped_not_due": 0,
    }


def classify_miss(
    planned: PlannedFire,
    *,
    intervals: Iterable[SleepInterval],
    pmset_horizon: datetime,
    wake_grace_seconds: int = WAKE_GRACE_SECONDS,
) -> dict:
    planned_at = planned.planned_at.astimezone(UTC)
    horizon = pmset_horizon.astimezone(UTC)
    if planned_at < horizon:
        return {
            "definition_id": planned.definition_id,
            "name": planned.name,
            "owner_seat": planned.owner_seat,
            "cron": planned.cron,
            "planned_at_cst": format_cst(planned_at),
            "planned_at_utc": format_iso(planned_at),
            "label": LABEL_PMSET_ROLLED,
            "display": LABEL_PMSET_ROLLED,
            "sleep_interval": None,
        }
    interval = covering_sleep(planned_at, intervals, wake_grace_seconds=wake_grace_seconds)
    if interval is not None:
        return {
            "definition_id": planned.definition_id,
            "name": planned.name,
            "owner_seat": planned.owner_seat,
            "cron": planned.cron,
            "planned_at_cst": format_cst(planned_at),
            "planned_at_utc": format_iso(planned_at),
            "label": LABEL_SLEEP,
            "display": DISPLAY_SLEEP,
            "sleep_interval": interval.display(),
        }
    return {
        "definition_id": planned.definition_id,
        "name": planned.name,
        "owner_seat": planned.owner_seat,
        "cron": planned.cron,
        "planned_at_cst": format_cst(planned_at),
        "planned_at_utc": format_iso(planned_at),
        "label": LABEL_AWAKE,
        "display": LABEL_AWAKE,
        "sleep_interval": None,
    }


def reconcile(
    *,
    workflows: list[dict],
    fires: list[dict],
    intervals: list[SleepInterval],
    pmset_horizon: datetime,
    now: datetime,
    cursor_before: datetime | None,
    since: datetime | None = None,
    grace_seconds: int = GRACE_SECONDS,
) -> dict:
    """Classify expected fires in ``(cursor, now - grace]``. Never writes files."""
    window = resolve_window(
        now=now,
        cursor_before=cursor_before,
        since=since,
        grace_seconds=grace_seconds,
    )
    counts = _empty_counts()
    result = {
        "ok": True,
        "cursor_before": format_iso(window["cursor_before"]) if window["cursor_before"] else None,
        "cursor_after": format_iso(window["cursor_after"]) if window["cursor_after"] else None,
        "now": format_iso(window["now"]),
        "grace_seconds": grace_seconds,
        "counts": counts,
        "misses": [],
    }
    if window["skipped_clock_rewind"]:
        result["skipped_clock_rewind"] = True
        return result

    keys = fire_key_set(fires)
    due = enumerate_expected_fires(workflows, window["window_start"], window["window_end"])
    not_due = enumerate_expected_fires(workflows, window["window_end"], window["now"])
    counts["skipped_not_due"] = len(not_due)
    misses: list[dict] = []
    for item in due:
        key = (item.definition_id, item.planned_at.astimezone(UTC))
        if key in keys:
            counts["fired_ok"] += 1
            continue
        miss = classify_miss(item, intervals=intervals, pmset_horizon=pmset_horizon)
        if miss["label"] == LABEL_SLEEP:
            counts["miss_sleep"] += 1
        elif miss["label"] == LABEL_PMSET_ROLLED:
            counts["miss_pmset_rolled"] += 1
        else:
            counts["miss_awake"] += 1
        misses.append(miss)
    result["misses"] = misses
    result["ok"] = counts["miss_awake"] == 0
    return result


def read_cursor_file(path: Path) -> datetime | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise MissedFiresError(f"cursor file unreadable: {path}") from exc
    if not isinstance(data, dict) or not data.get("reconciled_to"):
        raise MissedFiresError(f"cursor file missing reconciled_to: {path}")
    return parse_iso(data["reconciled_to"], field="reconciled_to")


def write_cursor_file(path: Path, *, reconciled_to: datetime, updated_at: datetime, grace_seconds: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "reconciled_to": format_iso(reconciled_to),
        "updated_at": format_iso(updated_at),
        "grace_seconds": grace_seconds,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def exit_code(result: dict) -> int:
    """0 when no awake miss (sleep / rolled / rewind ok); 2 on awake miss. Never 1."""
    if result.get("counts", {}).get("miss_awake", 0):
        return 2
    return 0
