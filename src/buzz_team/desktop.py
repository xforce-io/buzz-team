"""Desktop owns processes; bindings are changed offline with conflict-aware rollback."""
from __future__ import annotations

import copy
import datetime
import json
import os
from pathlib import Path
import subprocess
import uuid

from .config import Config, identity
from .instance import digest, write_json, write_private
from .runtime import Runtime


def live_processes(config: Config) -> list[int]:
    raw = subprocess.check_output(["ps", "-axo", "pid=,comm="], text=True)
    app = str(Path(config.data["desktop"]["app"]).resolve()) + "/"
    harness = str(Path(config.data["binaries"]["harness"]).resolve())
    result = []
    for line in raw.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2 and (parts[1].startswith(app) or parts[1] == harness):
            result.append(int(parts[0]))
    return result


def require_stopped(config: Config):
    if live_processes(config):
        raise ValueError("Desktop or harness still running; wait for idle and stop before binding")


def selected_rows(config: Config, rows: list) -> dict:
    selected = {}
    if not isinstance(rows, list):
        raise ValueError("invalid Desktop inventory")
    for row in rows:
        if not row.get("pubkey") or not row.get("relay_url"):
            continue
        key = identity(row["relay_url"], row["pubkey"])
        if key in config.data["agents"]:
            if key in selected:
                raise ValueError("duplicate Desktop identity")
            selected[key] = row
    if set(selected) != set(config.data["agents"]):
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
            if name != "BUZZ_ACP_CONFIG":
                raise ValueError("unsupported binding environment override")
            env[name] = value
        # The executor home, existing session settings and credentials remain untouched.
        for name, value in runtime.executor.environment(runtime.base, runtime.cwd).items():
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
               "before_sha256": digest(path), "after_sha256": digest(backup / "managed-agents.after.json")})
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
