#!/usr/bin/env python3
"""Sibling read-only missed-fire reconcile. Not doctor, not buzz-health.

Fixture mode (CI / replay): --workflows --fires --pmset [--now] [--since|--cursor].
Never calls live pmset or postgres in fixture mode.

Live mode (Hogan, human:required): no fixture flags. Read-only SQL via
docker exec + ``pmset -g log``. Writes only the cursor file.

Exit 0 if no miss_awake (sleep / pmset-rolled / rewind skip are ok).
Exit 2 on miss_awake or bad input. Never exit 1.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from buzz_team.missed_fires import (  # noqa: E402
    DEFAULT_CURSOR_PATH,
    GRACE_SECONDS,
    LOCAL_COMMUNITY_ID,
    MissedFiresError,
    exit_code,
    format_iso,
    load_fires,
    load_workflows,
    parse_iso,
    parse_pmset,
    read_cursor_file,
    reconcile,
    resolve_window,
    write_cursor_file,
)

READ_SQL = Path(__file__).resolve().parent / "read.sql"
LIVE_PSQL = (
    "docker",
    "exec",
    "-i",
    "-e",
    "PGOPTIONS=-c default_transaction_read_only=on",
    "buzz-prod-postgres-1",
    "psql",
    "-U",
    "buzz",
    "-d",
    "buzz",
    "-X",
    "-v",
    "ON_ERROR_STOP=1",
    "-At",
    "-f",
    "-",
)


def _load_json(path: Path) -> object:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise MissedFiresError(f"unreadable JSON: {path}") from exc


def _read_text(path: Path, *, field: str) -> str:
    try:
        return path.read_text()
    except OSError as exc:
        raise MissedFiresError(f"unreadable {field}: {path}") from exc


def _fixture_mode(args: argparse.Namespace) -> bool:
    return any([args.workflows, args.fires, args.pmset])


def _require_fixtures(args: argparse.Namespace) -> None:
    missing = [name for name in ("workflows", "fires", "pmset") if getattr(args, name) is None]
    if missing:
        raise MissedFiresError(
            "fixture mode requires --workflows, --fires, and --pmset "
            f"(missing {', '.join('--' + name for name in missing)}); "
            "will not substitute live pmset or SQL"
        )


def _read_live_sql(window_start, window_end) -> tuple[list[dict], list[dict]]:
    if not READ_SQL.exists():
        raise MissedFiresError(f"missing {READ_SQL}")
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "PGOPTIONS": "-c default_transaction_read_only=on",
    }
    proc = subprocess.run(
        (
            *LIVE_PSQL,
            "-v",
            f"window_start={format_iso(window_start)}",
            "-v",
            f"window_end={format_iso(window_end)}",
            "-v",
            f"community_id={LOCAL_COMMUNITY_ID}",
        ),
        input=_read_text(READ_SQL, field="read.sql"),
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    if proc.returncode != 0:
        raise MissedFiresError("read-only SQL failed")
    lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    if not lines:
        raise MissedFiresError("read-only SQL returned no JSON")
    try:
        payload = json.loads(lines[-1])
    except ValueError as exc:
        raise MissedFiresError("read-only SQL returned non-JSON") from exc
    if not isinstance(payload, dict):
        raise MissedFiresError("read-only SQL returned a non-object")
    return load_workflows(payload), load_fires(payload.get("fires", []))


def _read_live_pmset() -> str:
    proc = subprocess.run(
        ("pmset", "-g", "log"),
        text=True,
        capture_output=True,
        check=False,
        env={"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", "")},
    )
    if proc.returncode != 0:
        raise MissedFiresError("pmset -g log failed")
    return proc.stdout


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--now", help="clock override (ISO, timezone required)")
    parser.add_argument("--since", help="window left edge when no cursor (ISO)")
    parser.add_argument("--cursor", help="in-memory cursor ISO; do not read the cursor file")
    parser.add_argument("--cursor-file", type=Path, help="cursor JSON path (default live path)")
    parser.add_argument("--workflows", type=Path, help="frozen workflows JSON")
    parser.add_argument("--fires", type=Path, help="frozen scheduled_workflow_fires JSON")
    parser.add_argument("--pmset", type=Path, help="frozen Sleep/Wake/DarkWake log")
    parser.add_argument("--no-advance", action="store_true", help="compute and print; do not write cursor")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 2
        return 2 if code not in (0, 2) else code

    try:
        if args.cursor and args.since:
            raise MissedFiresError("pass only one of --cursor or --since")
        fixture = _fixture_mode(args)
        now = parse_iso(args.now, field="--now") if args.now else datetime.now(tz=timezone.utc)
        since = parse_iso(args.since, field="--since") if args.since else None
        if args.cursor:
            cursor_before = parse_iso(args.cursor, field="--cursor")
        elif args.cursor_file is not None:
            cursor_before = read_cursor_file(args.cursor_file)
        elif fixture:
            cursor_before = None
        else:
            cursor_before = read_cursor_file(DEFAULT_CURSOR_PATH)

        if fixture:
            _require_fixtures(args)
            workflows = load_workflows(_load_json(args.workflows))
            fires = load_fires(_load_json(args.fires))
            intervals, horizon = parse_pmset(_read_text(args.pmset, field="pmset"))
        else:
            window = resolve_window(now=now, cursor_before=cursor_before, since=since)
            if window["skipped_clock_rewind"]:
                workflows, fires, intervals, horizon = [], [], [], now
            else:
                workflows, fires = _read_live_sql(window["window_start"], window["now"])
                intervals, horizon = parse_pmset(_read_live_pmset())

        result = reconcile(
            workflows=workflows,
            fires=fires,
            intervals=intervals,
            pmset_horizon=horizon,
            now=now,
            cursor_before=cursor_before,
            since=since,
            grace_seconds=GRACE_SECONDS,
        )
    except MissedFiresError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2

    print(json.dumps(result, ensure_ascii=False, indent=2))

    should_write = (
        not args.no_advance
        and not result.get("skipped_clock_rewind")
        and result.get("cursor_after")
        and (not fixture or args.cursor_file is not None)
    )
    if should_write:
        target = args.cursor_file if args.cursor_file is not None else DEFAULT_CURSOR_PATH
        try:
            write_cursor_file(
                target,
                reconciled_to=parse_iso(result["cursor_after"], field="cursor_after"),
                updated_at=parse_iso(result["now"], field="now"),
                grace_seconds=GRACE_SECONDS,
            )
        except (MissedFiresError, OSError) as exc:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
            return 2
    return exit_code(result)


if __name__ == "__main__":
    raise SystemExit(main())
