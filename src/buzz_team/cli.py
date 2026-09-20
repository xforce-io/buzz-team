"""Stable CLI; ACP protocol output is never mixed with management diagnostics."""
from __future__ import annotations

import argparse
import importlib.resources
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys

from . import __version__
from .config import Config
from . import desktop
from .instance import digest, init_legacy, prepare
from .runtime import Runtime


def doctor(config: Config):
    errors = desktop.check_app(config)
    if not shutil.which("lsof"):
        errors.append("lsof unavailable; cannot verify idle identity workspaces")
    for name, path in config.data["binaries"].items():
        file = Path(path)
        if not file.is_file() or not os.access(file, os.X_OK):
            errors.append(f"{name}: missing executable")
        elif digest(file) != config.data["compatibility"]["sha256"].get(name):
            errors.append(f"{name}: executable differs from pinned baseline")
    manifest = json.loads(importlib.resources.files("buzz_team").joinpath("compatibility.json").read_text())
    if not errors:
        result = subprocess.run([config.data["binaries"]["harness"], "--help"], capture_output=True, text=True, timeout=15)
        if result.returncode or any(flag not in result.stdout for flag in manifest["required_harness_options"]):
            errors.append("harness: required CLI capability missing")
    counts = {}
    for name, spec in config.data["adapters"].items():
        pin = config.data["compatibility"].get("executor_sha256", {}).get(name)
        if (not pin or not Path(spec["command"]).is_file() or not os.access(spec["command"], os.X_OK)
                or digest(Path(spec["command"])) != pin):
            errors.append("executor differs from pinned baseline or is not pinned")
    for key in config.data["agents"]:
        runtime = Runtime(config, key)
        counts[runtime.executor.kind] = counts.get(runtime.executor.kind, 0) + 1
        errors.extend(runtime.executor.check(runtime.base))
        if not runtime.cwd.is_dir():
            errors.append("identity workspace missing")
        if not runtime.policy["production_write"] and not Path("/usr/bin/sandbox-exec").is_file():
            errors.append("Seatbelt unavailable")
        runtime.profile()
    return {"ok": not errors, "version": __version__, "identities": len(config.data["agents"]),
            "adapters": counts, "errors": sorted(set(errors)),
            "authentication": "existing home checked; contents never copied or output",
            "warnings": ["identity isolation only; task-level enforcement pending",
                         "skills/memory readiness and upstream cache behavior are not certified by this check",
                         "pinned binaries are a migration baseline, not proof of client verification"]}


def parser():
    p = argparse.ArgumentParser(prog="buzz-team", description="Buzz 本机运行管理；进程生命周期归 Buzz Desktop")
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--instance", type=Path, default=os.environ.get("BUZZ_TEAM_INSTANCE"))
    sub = p.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="从旧配置创建私有实例，不复制认证或绑定客户端")
    init.add_argument("--legacy", type=Path, required=True)
    init.add_argument("--desktop-config", type=Path, required=True)
    init.add_argument("--app", type=Path, required=True)
    for name in ("doctor", "status", "prepare", "bind", "start", "diagnose"):
        sub.add_parser(name)
    stop = sub.add_parser("stop", help="请求 Desktop 退出；先确认任务空闲")
    stop.add_argument("--idle-confirmed", action="store_true")
    rollback = sub.add_parser("rollback")
    rollback.add_argument("--receipt", type=Path, required=True)
    launch = sub.add_parser("launch", help="内部入口：由 Desktop 调用，不手动并行启动")
    launch.add_argument("mode", choices=["harness", "executor"])
    launch.add_argument("args", nargs=argparse.REMAINDER)
    buzz = sub.add_parser("buzz", help="内部入口：保留 DM/频道回复行为")
    buzz.add_argument("args", nargs=argparse.REMAINDER)
    workspace = sub.add_parser("workspace")
    workspace.add_argument("task")
    workspace.add_argument("--repo", required=True)
    workspace.add_argument("--ref", default="HEAD")
    workspace.add_argument("--branch")
    workspace.add_argument("--id", default=os.environ.get("BUZZ_RUNTIME_ID"))
    return p


def main():
    args = parser().parse_args()
    try:
        if args.instance is None:
            raise ValueError("--instance or BUZZ_TEAM_INSTANCE is required")
        if args.command == "init":
            result = init_legacy(args.instance, args.legacy, args.desktop_config, args.app)
        else:
            config = Config(args.instance)
            if args.command in {"doctor", "diagnose"}:
                result = doctor(config)
            elif args.command == "prepare":
                result = prepare(config)
            elif args.command in {"status", "start"}:
                result = getattr(desktop, args.command)(config)
            elif args.command == "stop":
                result = desktop.stop(config, args.idle_confirmed)
            elif args.command == "bind":
                checked = doctor(config)
                if not checked["ok"]:
                    raise ValueError("doctor failed; binding unchanged")
                result = desktop.bind(config)
            elif args.command == "rollback":
                result = desktop.rollback(config, args.receipt)
            elif args.command == "workspace":
                result = {"path": str(Runtime(config, args.id).workspace(args.task, args.repo, args.ref, args.branch))}
            elif args.command == "launch":
                Runtime(config, os.environ.get("BUZZ_RUNTIME_ID")).launch(args.mode, args.args[1:] if args.args[:1] == ["--"] else args.args)
                return 0
            elif args.command == "buzz":
                from .buzz_cli import run
                run(config, args.args[1:] if args.args[:1] == ["--"] else args.args)
                return 0
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ok", True) else 2
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError) as exc:
        # Subprocess exceptions may contain argv with secrets. Do not echo them.
        message = "invalid JSON configuration" if isinstance(exc, json.JSONDecodeError) else (
            str(exc) if isinstance(exc, ValueError) else type(exc).__name__ + ": operation failed; inspect private configuration")
        print(json.dumps({"ok": False, "error": message}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
