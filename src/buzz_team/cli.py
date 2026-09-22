"""Stable CLI; ACP protocol output is never mixed with management diagnostics."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from . import __version__
from .config import Config
from . import desktop
from .instance import init_legacy, prepare
from .runtime import Runtime
from .sessions import SessionStore
from .context import ContextLedger
from . import health


def _ref(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:12]


def _public_session(record: dict[str, str]) -> dict[str, str]:
    return {"task_ref": _ref(record["task_id"]), "session_ref": _ref(record["session_id"]),
            "state": record["state"]}

def _metric_value(value: str) -> int | str:
    if value == "unavailable":
        return value
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError("metric must be a non-negative integer or unavailable") from exc
    if parsed < 0:
        raise ValueError("metric must be a non-negative integer or unavailable")
    return parsed


def doctor(config: Config, *, depth: str = "doctor"):
    """Static/install health. diagnose uses the same kernel with deeper proxy probes."""
    return health.run(config, depth=depth)


def parser():
    p = argparse.ArgumentParser(prog="buzz-team", description="Buzz 本机运行管理；进程生命周期归 Buzz Desktop")
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--instance", type=Path, default=os.environ.get("BUZZ_TEAM_INSTANCE"))
    sub = p.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="从旧配置创建私有实例，不复制认证或绑定客户端")
    init.add_argument("--legacy", type=Path, required=True)
    init.add_argument("--desktop-config", type=Path, required=True)
    init.add_argument("--app", type=Path, required=True)
    sub.add_parser(
        "doctor",
        help="静态预检：安装/指纹/身份目录与代理键对照；ok 仅表示无 fail，含 unverified 不代表整体健康",
    )
    sub.add_parser(
        "diagnose",
        help="诊断深度：与 doctor 同内核，另含代理 TCP 探测与 unverified_surfaces 列表；非角色对话验证",
    )
    for name in ("status", "prepare", "bind", "start"):
        sub.add_parser(name)
    stop = sub.add_parser("stop", help="请求 Desktop 退出；先确认任务空闲")
    stop.add_argument("--idle-confirmed", action="store_true")
    rollback = sub.add_parser("rollback")
    rollback.add_argument("--receipt", type=Path, required=True)
    launch = sub.add_parser("launch", help="内部入口：由 Desktop 调用，不手动并行启动")
    launch.add_argument("--task")
    launch.add_argument("--scope")
    launch.add_argument("--consume-handoff", action="store_true")
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
    context = sub.add_parser("context", help="记录任务上下文成本与安全交接")
    context_sub = context.add_subparsers(dest="context_command", required=True)
    start = context_sub.add_parser("start")
    start.add_argument("--task", required=True); start.add_argument("--max-input-tokens", type=int); start.add_argument("--max-context-tokens", type=int)
    record = context_sub.add_parser("record")
    record.add_argument("--task", required=True); record.add_argument("--turn", required=True); record.add_argument("--provider", required=True); record.add_argument("--model", required=True)
    for name in ("input", "output", "cached-input", "uncached-input", "context", "duration"):
        record.add_argument(f"--{name}-tokens" if name != "duration" else "--duration-ms", required=name in {"input", "output"}, default=None if name in {"input", "output"} else "unavailable")
        record.add_argument(f"--{name}-quality", choices=("actual", "estimated", "unavailable"), default="actual")
    record.add_argument("--tool-rounds", type=int, default=0); record.add_argument("--retries", type=int, default=0); record.add_argument("--result-status", default="success")
    handoff = context_sub.add_parser("handoff")
    for name in ("task", "goal", "next-step", "workspace-ref", "approval-state"): handoff.add_argument(f"--{name}", required=True)
    for name in ("constraint", "fact", "pending", "tool-result"): handoff.add_argument(f"--{name}", action="append", default=[])
    handoff.add_argument("--open-tool-calls", type=int, default=0)
    report = context_sub.add_parser("report"); report.add_argument("--task", required=True)
    restore = context_sub.add_parser("restore"); restore.add_argument("--task", required=True)
    consume = context_sub.add_parser("consume"); consume.add_argument("--task", required=True)
    wake = sub.add_parser("wake", help="频道点名门控判定与会话游标（只读）")
    wake_sub = wake.add_subparsers(dest="wake_command", required=True)
    decide = wake_sub.add_parser("decide", help="判定本帖是否允许该身份进入执行向长跑")
    decide.add_argument("--identity", required=True)
    decide.add_argument("--channel", required=True)
    decide.add_argument("--post-ref", required=True)
    decide.add_argument("--body", required=True)
    decide.add_argument("--surface", default="stream")
    decide.add_argument("--mentions", help="非空则 fail-closed：尚无结构化 mention")
    cursor = wake_sub.add_parser("cursor", help="读取频道会话游标")
    cursor.add_argument("--identity", required=True)
    cursor.add_argument("--scope", required=True)
    cursor.add_argument("--community")
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
                result = doctor(config, depth=args.command)
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
                        if not runtime.executor.supports_task_sessions:
                            raise ValueError("executor adapter cannot restore task sessions")
                        args.session_id = runtime.executor.validate_task_session_binding(args.session_id, runtime.base, workspace)
                        result = _public_session(store.bind(**values, session_id=args.session_id))
                    elif args.session_command == "claim":
                        result = _public_session(store.claim(**values, owner=args.owner))
                    elif args.session_command == "release":
                        result = _public_session(store.release(**values, owner=args.owner))
                    else:
                        result = _public_session(store.resolve(**values))
            elif args.command == "context":
                ledger = ContextLedger(config.instance, args.task)
                if args.context_command == "report":
                    result = ledger.report()
                elif args.context_command == "restore":
                    result = ledger.read_handoff()
                elif args.context_command == "consume":
                    result = ledger.consume_handoff()
                else:
                    if not any(item["task_id"] == args.task for item in SessionStore(config.instance).list()):
                        raise ValueError("task session mapping not found")
                    if args.context_command == "start":
                        result = ledger.start(max_input_tokens=args.max_input_tokens, max_context_tokens=args.max_context_tokens)
                    elif args.context_command == "record":
                        names = {"input": "input_tokens", "output": "output_tokens", "cached-input": "cached_input_tokens", "uncached-input": "uncached_input_tokens", "context": "context_tokens", "duration": "duration_ms"}
                        values = {target: _metric_value(getattr(args, source.replace("-", "_") + ("_tokens" if source != "duration" else "_ms"))) for source, target in names.items()}
                        qualities = {target: getattr(args, source.replace("-", "_") + "_quality") for source, target in names.items()}
                        result = ledger.record(turn_id=args.turn, provider=args.provider, model=args.model, values=values, qualities=qualities, tool_rounds=args.tool_rounds, retries=args.retries, result_status=args.result_status)
                    else:
                        result = ledger.handoff(goal=args.goal, next_step=args.next_step, workspace_ref=args.workspace_ref, approval_state=args.approval_state, constraints=args.constraint, facts=args.fact, pending=args.pending, tool_results=args.tool_result, open_tool_calls=args.open_tool_calls)
            elif args.command == "wake":
                from .wake import ChannelCursorStore, decideWake, publicCursor
                if args.wake_command == "decide":
                    mentions = None
                    if args.mentions is not None:
                        mentions = json.loads(args.mentions)
                    result = decideWake(config, identity=args.identity, channel=args.channel,
                                        postRef=args.post_ref, body=args.body,
                                        surface=args.surface, mentions=mentions)
                else:
                    agent = config.agent(args.identity)
                    community = args.community or agent["relay_url"]
                    store = ChannelCursorStore(config.instance)
                    try:
                        record = store.resolve(community=community, identity=args.identity, scope=args.scope)
                    except ValueError as exc:
                        if str(exc) != "channel cursor not found":
                            raise
                        result = publicCursor(None)
                    else:
                        result = publicCursor(record)
            elif args.command == "launch":
                from .wake import ChannelWakeSilent
                task_id = args.task or os.environ.get("BUZZ_TASK_ID")
                launch_args = args.args[1:] if args.args[:1] == ["--"] else args.args
                consume = args.consume_handoff or os.environ.get("BUZZ_CONSUME_HANDOFF") == "1"
                try:
                    result = Runtime(config, os.environ.get("BUZZ_RUNTIME_ID")).launch(
                        args.mode, launch_args, task_id, args.scope or os.environ.get("BUZZ_TASK_SCOPE"),
                        consume_handoff=consume)
                except ChannelWakeSilent as exc:
                    print(json.dumps(exc.payload, ensure_ascii=False, indent=2), file=sys.stderr)
                    return 0
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
