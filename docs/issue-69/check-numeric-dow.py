#!/usr/bin/env python3
"""Read-only numeric DOW checker. Warn only; exit 0 unless --strict.

Reads workflow YAML, a buzz workflows list JSON, or raw cron lines. No secrets,
no Desktop inventory, no database. Prints cron 0.16 Sunday=1 CST interpretation.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from buzz_team.cron_dow import collect_warnings, extract_crons  # noqa: E402


def _load_list_json(path: Path) -> list[tuple[str, str]]:
    data = json.loads(path.read_text())
    rows = data["workflows"] if isinstance(data, dict) and "workflows" in data else data
    if not isinstance(rows, list):
        raise SystemExit(f"{path}: expected a list or {{workflows: [...]}}")
    texts = []
    for index, row in enumerate(rows):
        if isinstance(row, str):
            texts.append((f"{path}#{index}", row))
            continue
        if not isinstance(row, dict):
            raise SystemExit(f"{path}: row {index} is not an object")
        label = str(row.get("workflow_id") or row.get("id") or row.get("name") or index)
        body = row.get("content") or row.get("definition") or row.get("yaml")
        if body is None and isinstance(row.get("cron"), str):
            body = f'cron: "{row["cron"]}"'
        if not isinstance(body, str):
            raise SystemExit(f"{path}: row {label} has no cron-bearing text")
        texts.append((f"{path}:{label}", body))
    return texts


def _load_path(path: Path) -> list[tuple[str, str]]:
    if path.suffix == ".json":
        return _load_list_json(path)
    return [(str(path), path.read_text())]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path, help="YAML / list JSON / cron text files")
    parser.add_argument("--strict", action="store_true", help="exit 2 when any numeric DOW is found")
    args = parser.parse_args(argv)
    texts: list[tuple[str, str]] = []
    if args.paths:
        for path in args.paths:
            texts.extend(_load_path(path))
    else:
        body = sys.stdin.read()
        if body.strip():
            texts.append(("stdin", body))
    warnings = collect_warnings(texts)
    if not texts:
        print("numeric DOW checker: no input")
        return 0
    scanned = 0
    for source, body in texts:
        scanned += len(extract_crons(body)) or (1 if body.strip() and "cron:" not in body else 0)
    print(f"numeric DOW checker: scanned={scanned} warnings={len(warnings)}")
    for item in warnings:
        print(f"WARN {item['source']}: {item['detail']}")
        explanation = item.get("explanation") or {}
        slots = explanation.get("slots") or []
        for slot in slots:
            extra = " (UTC date differs from CST)" if slot.get("utc_date_differs") else ""
            print(
                f"  UTC {slot['utc']} {slot['utc_weekdays']} -> "
                f"CST {slot['cst']} {slot['cst_weekdays']}{extra}"
            )
        if explanation.get("error"):
            print(f"  interpret-error: {explanation['error']}")
    if not warnings:
        print("OK: no numeric DOW fields")
    if args.strict and warnings:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
