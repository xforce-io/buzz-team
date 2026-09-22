"""Desktop owns processes; bindings are changed offline with conflict-aware rollback."""
from __future__ import annotations

import copy
import datetime
import importlib.resources
import json
import os
import plistlib
import shutil
from pathlib import Path
import subprocess
import uuid

from .config import Config, identity
from .instance import digest, write_json, write_private
from .runtime import Runtime


WAKE_BINDING_KEYS = (
    "BUZZ_WAKE_SURFACE",
    "BUZZ_WAKE_CHANNEL",
    "BUZZ_WAKE_POST_REF",
    "BUZZ_WAKE_BODY",
    "BUZZ_WAKE_SCOPE",
)
ALLOWED_BINDING_KEYS = {
    "BUZZ_ACP_CONFIG", "BUZZ_TASK_ID", "BUZZ_TASK_SCOPE", *WAKE_BINDING_KEYS,
}
_WAKE_PAYLOAD_FIELDS = {
    "surface": "BUZZ_WAKE_SURFACE",
    "channel": "BUZZ_WAKE_CHANNEL",
    "post_ref": "BUZZ_WAKE_POST_REF",
    "postRef": "BUZZ_WAKE_POST_REF",
    "body": "BUZZ_WAKE_BODY",
    "scope": "BUZZ_WAKE_SCOPE",
}


def applyWakePayload(env: dict[str, str]) -> dict[str, str]:
    """Expand Desktop ACP wake JSON into BUZZ_WAKE_* env. Does not invent channel IDs."""
    raw = env.get("BUZZ_WAKE_PAYLOAD")
    if raw is None:
        return env
    if not isinstance(raw, str) or not raw or "\0" in raw:
        raise ValueError("invalid wake payload")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("invalid wake payload") from exc
    if not isinstance(payload, dict) or set(payload) - set(_WAKE_PAYLOAD_FIELDS):
        raise ValueError("invalid wake payload")
    for src, dest in _WAKE_PAYLOAD_FIELDS.items():
        if src not in payload:
            continue
        value = payload[src]
        if not isinstance(value, str) or "\0" in value:
            raise ValueError("invalid wake payload field")
        if dest != "BUZZ_WAKE_BODY" and not value:
            raise ValueError("invalid wake payload field")
        env[dest] = value
    return env


def live_processes(config: Config) -> list[int]:
    # macOS truncates comm when followed by args, even with -ww. Read them separately.
    raw = "\n".join(subprocess.check_output(["ps", "-ww", "-axo", fields], text=True,
                                          errors="surrogateescape", timeout=15)
                    for fields in ("pid=,comm=", "pid=,args="))
    app = str(Path(config.data["desktop"]["app"]).resolve()) + "/"
    executors = {spec["command"] for spec in config.data["adapters"].values()}
    rows = selected_rows(config, json.loads(Path(config.data["desktop"]["managed_agents"]).read_text()))
    for row in rows.values():
        for field in ("agent_command", "acp_command"):
            value = row.get(field)
            if value:
                if not isinstance(value, str) or not Path(value).is_absolute():
                    raise ValueError("Desktop binding command must be an absolute path")
                executors.add(value)
    executors.update(str(Path(path).resolve()) for path in tuple(executors))
    harness = config.data["binaries"]["harness"]
    commands = executors | {harness, str(Path(harness).resolve())}
    result = set()
    # Identity workspaces remain authoritative even after the adapter changes or
    # an executor replaces argv with a short title. Do not depend on its old name.
    lsof = shutil.which("lsof")
    if not lsof:
        raise ValueError("lsof unavailable; cannot prove identity workspaces are idle")
    cwd_info = subprocess.check_output([lsof, "-nP", "-d", "cwd", "-Fpn"],
                                       text=True, errors="surrogateescape", timeout=15)
    pid = None
    for line in cwd_info.splitlines():
        if line.startswith("p") and line[1:].isdigit():
            pid = int(line[1:])
        elif pid is not None and line.startswith("n/") and Path(line[1:]).resolve().is_relative_to(config.state):
            result.add(pid)
    for line in raw.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2:
            # ps does not quote argv; match full configured paths at token boundaries,
            # including interpreted executors whose comm is Python/Node/a shell.
            command = parts[1]
            matched = command.startswith(app) or any(
                command == path or command.startswith(path + " ") or
                (" " + path + " ") in (" " + command + " ")
                for path in commands)
            if matched:
                result.add(int(parts[0]))
    return sorted(result)


def require_stopped(config: Config):
    if live_processes(config):
        raise ValueError("Desktop, harness or executor still running; wait for idle and stop before binding")


def check_app(config: Config) -> list[str]:
    app = Path(config.data["desktop"]["app"])
    try:
        info = plistlib.loads((app / "Contents/Info.plist").read_bytes())
        if not isinstance(info, dict):
            return ["Desktop: invalid application metadata"]
        manifest = json.loads(importlib.resources.files("buzz_team").joinpath("compatibility.json").read_text())
        baseline = manifest["observed_baseline"]
        if (info.get("CFBundleIdentifier") != baseline["desktop_bundle_id"]
                or info.get("CFBundleShortVersionString") != baseline["desktop"]):
            return ["Desktop: identity or version differs from compatibility baseline"]
        name = info.get("CFBundleExecutable")
        if not isinstance(name, str) or not name or Path(name).name != name:
            return ["Desktop: invalid application executable"]
        executable = app / "Contents/MacOS" / name
        if not executable.is_file() or not os.access(executable, os.X_OK):
            return ["Desktop: missing executable"]
    except (OSError, ValueError, plistlib.InvalidFileException):
        return ["Desktop: missing or invalid application bundle"]
    return []


def selected_rows(config: Config | dict, rows: list) -> dict:
    data = config if isinstance(config, dict) else config.data
    selected = {}
    if not isinstance(rows, list):
        raise ValueError("invalid Desktop inventory")
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("invalid Desktop inventory row")
        if not row.get("pubkey") or not row.get("relay_url"):
            continue
        key = identity(row["relay_url"], row["pubkey"])
        if key in data["agents"]:
            if "env_vars" in row and not isinstance(row["env_vars"], dict):
                raise ValueError("Desktop env_vars must be an object")
            if key in selected:
                raise ValueError("duplicate Desktop identity")
            selected[key] = row
    if set(selected) != set(data["agents"]):
        raise ValueError("Desktop identity inventory mismatch")
    return selected


def binding_diff(config: Config, rows: list) -> tuple[list, int]:
    result = copy.deepcopy(rows)
    chosen = selected_rows(config, result)
    changed = 0
    for key, row in chosen.items():
        before = copy.deepcopy(row)
        runtime = Runtime(config, key)
        row["acp_command"] = str(config.instance / "bin/agent-harness")
        row["agent_command"] = str(config.instance / "bin/agent-executor")
        env = row.setdefault("env_vars", {})
        env["BUZZ_RUNTIME_ID"] = key
        env["BUZZ_TEAM_INSTANCE"] = str(config.instance)
        for name, value in runtime.agent.get("binding_environment", {}).items():
            if name not in ALLOWED_BINDING_KEYS:
                raise ValueError("unsupported binding environment override")
            if not isinstance(value, str) or not value or "\0" in value:
                raise ValueError("invalid binding environment value")
            env[name] = value
        # The executor home, existing session settings and credentials remain untouched.
        for name, value in runtime.executor.binding_environment(runtime.base, runtime.cwd).items():
            if name in env and env[name] != value:
                raise ValueError("executor environment differs from existing Desktop binding")
            env[name] = value
        if row != before:
            changed += 1
    return result, changed


def bind(config: Config):
    require_stopped(config)
    for name in ("agent-harness", "agent-executor", "buzz", "agent-worktree"):
        if not os.access(config.instance / "bin" / name, os.X_OK):
            raise ValueError("run prepare before bind")
    path = Path(config.data["desktop"]["managed_agents"])
    original = path.read_text()
    rows = json.loads(original)
    updated, count = binding_diff(config, rows)
    if not count:
        return {"changed": 0, "bound": True}
    backup = config.instance / "backups" / uuid.uuid4().hex
    backup.mkdir(parents=True, mode=0o700)
    write_private(backup / "managed-agents.before.json", original)
    planned = json.dumps(updated, ensure_ascii=False, indent=2) + "\n"
    write_private(backup / "managed-agents.after.json", planned)
    write_json(backup / "receipt.json", {"instance": str(config.instance), "target": str(path),
               "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
               "before_sha256": digest(backup / "managed-agents.before.json"),
               "after_sha256": digest(backup / "managed-agents.after.json")})
    require_stopped(config)
    if path.read_text() != original:
        raise ValueError("Desktop configuration changed during bind; no overwrite")
    write_private(path, planned)
    return {"changed": count, "bound": True, "receipt": str(backup / "receipt.json")}


def rollback(config: Config, receipt: Path):
    require_stopped(config)
    receipt = receipt.resolve()
    if not receipt.is_relative_to(config.instance / "backups"):
        raise ValueError("receipt is outside this instance")
    data = json.loads(receipt.read_text())
    path = Path(config.data["desktop"]["managed_agents"])
    if data["instance"] != str(config.instance) or data["target"] != str(path):
        raise ValueError("receipt target mismatch")
    before = receipt.parent / "managed-agents.before.json"
    if digest(before) != data["before_sha256"]:
        raise ValueError("backup integrity mismatch")
    after = receipt.parent / "managed-agents.after.json"
    if digest(after) != data["after_sha256"]:
        raise ValueError("binding snapshot integrity mismatch")
    current_text = path.read_text()
    rows = json.loads(current_text)
    current = selected_rows(config, rows)
    old_rows = selected_rows(config, json.loads(before.read_text()))
    new_rows = selected_rows(config, json.loads(after.read_text()))
    missing = object()
    def restore_fields(target, old, new):
        for name in old.keys() | new.keys():
            was, planned = old.get(name, missing), new.get(name, missing)
            if was == planned:
                continue
            value = target.get(name, missing)
            if value == was:
                continue
            if value != planned:
                raise ValueError("binding field changed since migration; refusing conflicting rollback")
            if was is missing:
                target.pop(name, None)
            else:
                target[name] = was
    for key, row in current.items():
        old, new = old_rows[key], new_rows[key]
        restore_fields(row, {k: v for k, v in old.items() if k != "env_vars"},
                       {k: v for k, v in new.items() if k != "env_vars"})
        restore_fields(row.setdefault("env_vars", {}), old.get("env_vars", {}), new.get("env_vars", {}))
        if "env_vars" not in old and not row["env_vars"]:
            row.pop("env_vars")
    require_stopped(config)
    if path.read_text() != current_text:
        raise ValueError("Desktop configuration changed during rollback")
    write_json(path, rows)
    return {"restored": True, "credentials_restored": False}


def status(config: Config):
    rows = json.loads(Path(config.data["desktop"]["managed_agents"]).read_text())
    _, changes = binding_diff(config, rows)
    return {"desktop_pids": live_processes(config), "identities": len(config.data["agents"]),
            "bound": changes == 0, "lifecycle_owner": "Buzz Desktop"}


def start(config: Config):
    errors = check_app(config)
    if errors:
        raise ValueError("; ".join(errors))
    if not status(config)["bound"]:
        raise ValueError("instance not bound; refusing to start old binding")
    if live_processes(config):
        return {"running": True, "already_running": True}
    subprocess.run(["open", "-a", config.data["desktop"]["app"]], check=True)
    return {"start_requested": True, "lifecycle_owner": "Buzz Desktop"}


def stop(config: Config, idle_confirmed: bool):
    if not idle_confirmed:
        raise ValueError("confirm no active work with --idle-confirmed before stopping")
    # The executable path is a separate argv item; no user content is interpolated into AppleScript.
    script = 'on run argv\n tell application (item 1 of argv) to quit\nend run'
    subprocess.run(["osascript", "-e", script, config.data["desktop"]["app"]], check=True)
    return {"stop_requested": True, "remaining_pids": live_processes(config)}
