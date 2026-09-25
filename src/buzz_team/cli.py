"""Read-only diagnostics for the local Seatbelt boundary."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import __version__
from .doctor import run


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(prog="buzz-team")
    command.add_argument("--version", action="version", version=__version__)
    actions = command.add_subparsers(dest="command", required=True)
    for name in ("doctor", "diagnose"):
        item = actions.add_parser(name, help="只读检查 Desktop 库存和本机 Seatbelt 策略")
        item.add_argument("--inventory", type=Path, help="Desktop 库存路径；不写入")
        item.add_argument("--policies", type=Path, help="本机 Seatbelt 策略目录")
    return command


def main() -> int:
    args = parser().parse_args()
    result = run(args.inventory, args.policies)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
