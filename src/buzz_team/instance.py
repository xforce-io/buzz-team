"""Private instance conversion. Deliberately never copies an executor home."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile

from .config import Config


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_private(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise ValueError("refusing symlink write target")
    fd, name = tempfile.mkstemp(prefix=".buzz-team-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def write_json(path: Path, value):
    write_private(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def init_legacy(instance: Path, legacy: Path, desktop: Path, app: Path):
    instance = instance.resolve()
    if (instance / "instance.local.json").exists():
        raise ValueError("instance already configured; refusing overwrite")
    if instance.exists() and any(p.name != "README.md" for p in instance.iterdir()):
        raise ValueError("target must be empty apart from README.md")
    old = json.loads(legacy.read_text())
    if old.get("version") != 1:
        raise ValueError("expected legacy configuration version 1")
    state = Path(old["state_root"]).resolve()
    if instance.is_relative_to(state) or state.is_relative_to(instance):
        raise ValueError("instance cannot contain or overlap retained state")
    instance.mkdir(parents=True, exist_ok=True, mode=0o700)
    instance.chmod(0o700)
    c = {k: old[k] for k in ("state_root", "protected_home", "production", "policies", "repositories", "agents")}
    c.update(version=2, binaries={k: old["binaries"][k] for k in ("buzz", "harness")},
             adapters={"grok": {"kind": "grok", "command": old["binaries"]["grok"]}},
             desktop={"managed_agents": str(desktop.resolve()), "app": str(app.resolve())},
             data_environment={"KAIRO_SERVE_ROOT": {"test": "{identity_root}/test-data", "production": old["production"]["data_root"]}},
             compatibility={"sha256": {k: digest(Path(old["binaries"][k])) for k in ("buzz", "harness")}})
    from .desktop import selected_rows
    inventory = selected_rows(type("Inventory", (), {"data": c})(), json.loads(desktop.read_text()))
    c["compatibility"]["executor_sha256"] = {"grok": digest(Path(old["binaries"]["grok"]))}
    for index, agent in enumerate(c["agents"].values()):
        agent["adapter"] = "grok"
        if "instructions" in agent:
            source = Path(agent["instructions"])
            target = instance / "private" / f"instructions-{index}.md"
            write_private(target, source.read_text())
            agent["instructions"] = str(target)
        # Skills are existing private resources, not recursively copied or installed.
    for key, row in inventory.items():
        existing_env = row.get("env_vars") or {}
        if existing_env.get("BUZZ_ACP_CONFIG"):
            source = Path(existing_env["BUZZ_ACP_CONFIG"]).resolve()
            if not source.is_file():
                raise ValueError("existing ACP rules file missing")
            # Resolve legacy compatibility links without changing the rule contents.
            c["agents"][key]["binding_environment"] = {"BUZZ_ACP_CONFIG": str(source)}
    # No credential_sources or configuration regeneration in v2. Existing adapter homes are authoritative.
    write_json(instance / "instance.local.json", c)
    Config(instance)
    write_json(instance / "migration-origin.json", {"legacy_config": str(legacy.resolve()),
               "legacy_config_sha256": digest(legacy), "state_root": str(state),
               "authentication": "reuse-in-place; never copy or restore"})
    return {"instance": str(instance), "identities": len(c["agents"]), "bound": False,
            "authentication": "unchanged: existing executor homes retained"}


def prepare(config: Config):
    """Only thin launchers; never rewrite credentials, instructions or adapter settings."""
    executable = Path(sys.executable).absolute()
    q = shlex.quote
    prefix = f"exec {q(str(executable))} -m buzz_team.cli --instance {q(str(config.instance))} "
    commands = {"agent-harness": "launch harness --", "agent-executor": "launch executor --",
                "buzz": "buzz --", "agent-worktree": "workspace"}
    for name, command in commands.items():
        target = config.instance / "bin" / name
        write_private(target, f'#!/bin/sh\nset -eu\n{prefix}{command} "$@"\n')
        target.chmod(0o700)
    return {"prepared": list(commands), "authentication_modified": False}
