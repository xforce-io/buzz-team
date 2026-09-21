"""Stable CLI; ACP protocol output is never mixed with management diagnostics."""
from __future__ import annotations

import argparse
import hashlib
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
from .sessions import SessionStore


def _ref(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:12]


def _public_session(record: dict[str, str]) -> dict[str, str]:
    return {"task_ref": _ref(record["task_id"]), "session_ref": _ref(record["session_id"]),
            "state": record["state"]}


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
    launch.add_argument("--task")
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
    session = sub.add_parser("session", help="管理经过校验的任务会话映射")
    session_sub = session.add_subparsers(dest="session_command", required=True)
    bind = session_sub.add_parser("bind", help="绑定任务与执行器会话")
    bind.add_argument("--task", required=True)
    bind.add_argument("--community", required=True)
    bind.add_argument("--identity", required=True)
    bind.add_argument("--scope", required=True)
    bind.add_argument("--workspace", required=True)
    bind.add_argument("--session", required=True, dest="session_id")
    resolve = session_sub.add_parser("resolve", help="解析任务会话映射")
    for name in ("task", "community", "identity", "scope", "workspace"):
        resolve.add_argument(f"--{name}", required=True)
    for command in ("claim", "release"):
        action = session_sub.add_parser(command, help="原子占用或释放任务会话")
        for name in ("task", "community", "identity", "scope", "workspace"):
            action.add_argument(f"--{name}", required=True)
        action.add_argument("--owner", required=True)
    session_sub.add_parser("list", help="列出任务会话映射")
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
            elif args.command == "session":
                store = SessionStore(config.instance)
                if args.session_command == "list":
                    result = {"bindings": [_public_session(row) for row in store.list()]}
                else:
                    agent = config.agent(args.identity)
                    if args.community.rstrip("/") != agent["relay_url"].rstrip("/"):
                        raise ValueError("community does not match identity")
                    workspace = Path(args.workspace).resolve()
                    runtime = Runtime(config, args.identity)
                    if not workspace.is_dir() or not workspace.is_relative_to(runtime.base):
                        raise ValueError("workspace does not belong to identity")
                    values = {"community": args.community, "identity": args.identity,
                              "scope": args.scope, "task_id": args.task,
                              "workspace": str(workspace)}
                    if args.session_command == "bind":
                        result = _public_session(store.bind(**values, session_id=args.session_id))
                    elif args.session_command == "claim":
                        result = _public_session(store.claim(**values, owner=args.owner))
                    elif args.session_command == "release":
                        result = _public_session(store.release(**values, owner=args.owner))
                    else:
                        result = _public_session(store.resolve(**values))
            elif args.command == "launch":
                launch_args = args.args[1:] if args.args[:1] == ["--"] else list(args.args)
                task_id = args.task or os.environ.get("BUZZ_TASK_ID")
                if not task_id and "--task" in launch_args:
                    index = launch_args.index("--task")
                    if index + 1 >= len(launch_args):
                        raise ValueError("--task requires a value")
                    task_id = launch_args.pop(index + 1)
                    launch_args.pop(index)
                result = Runtime(config, os.environ.get("BUZZ_RUNTIME_ID")).launch(
                    args.mode, launch_args, task_id)
                return result if isinstance(result, int) else 0
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
