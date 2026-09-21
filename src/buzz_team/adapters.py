"""Explicit executor adapters. Generic ACP support is not a brand certification."""
from __future__ import annotations

from pathlib import Path
import os
import re

from .config import absolute


class ACPCommand:
    kind = "acp-command"
    capabilities = ("acp-stdio",)
    supports_task_sessions = False

    def __init__(self, spec: dict):
        self.spec = spec

    def validate(self):
        absolute(self.spec["command"])
        segment = self.spec.get("home_directory", "executor")
        if not re.fullmatch(r"[a-z][a-z0-9-]*", segment):
            raise ValueError("invalid executor home directory")
        environment = self.spec.get("env", {})
        if not isinstance(environment, dict):
            raise ValueError("adapter environment must be an object")
        for key, value in environment.items():
            if (not isinstance(key, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]*", key)
                    or not isinstance(value, str) or "\0" in value):
                raise ValueError("invalid adapter environment")
            if key.startswith(("BUZZ_", "DYLD_", "LD_", "PYTHON")) or key in {
                "HOME", "PATH", "TMPDIR", "XDG_CACHE_HOME", "CARGO_HOME", "UV_CACHE_DIR", "KAIRO_SERVE_ROOT",
                "XAI_API_KEY", "GROK_CODE_XAI_API_KEY",
            }:
                raise ValueError("adapter cannot override runtime-owned environment")

    def home(self, base: Path) -> Path:
        return base / self.spec.get("home_directory", "executor")

    def environment(self, base: Path, cwd: Path) -> dict[str, str]:
        return {key: value.replace("{executor_home}", str(self.home(base))).replace("{workspace}", str(cwd))
                for key, value in self.spec.get("env", {}).items()}

    def clean_inherited(self, env: dict[str, str]):
        """Executor-specific inherited settings are owned by its adapter."""
        for name in tuple(env):
            if name.startswith("GROK_") or name == "XAI_API_KEY":
                env.pop(name)

    def binding_environment(self, base: Path, cwd: Path) -> dict[str, str]:
        """Stable settings persisted by Desktop, distinct from launch-time policy."""
        return self.environment(base, cwd)

    def check(self, base: Path) -> list[str]:
        if not Path(self.spec["command"]).is_file() or not os.access(self.spec["command"], os.X_OK):
            return ["executor binary missing or not executable"]
        if not self.home(base).is_dir():
            return ["executor home missing; initialization is executor-specific"]
        return []


class Grok(ACPCommand):
    kind = "grok"
    capabilities = ("acp-stdio", "existing-home", "existing-session-store")
    supports_task_sessions = True

    def task_session_args(self, session_id: str) -> list[str]:
        return ["--resume", session_id]

    def home(self, base: Path) -> Path:
        return base / "grok"

    def clean_inherited(self, env: dict[str, str]):
        for name in ("XAI_API_KEY", "GROK_CODE_XAI_API_KEY", "GROK_AGENT", "GROK_SESSION_ID", "GROK_SANDBOX"):
            env.pop(name, None)

    def environment(self, base: Path, cwd: Path) -> dict[str, str]:
        return {**super().environment(base, cwd), "GROK_HOME": str(self.home(base)),
                "GROK_ACP_CWD": str(cwd), "GROK_MEMORY": "0", "GROK_AGENT_DASHBOARD": "0"}

    def binding_environment(self, base: Path, cwd: Path) -> dict[str, str]:
        # Desktop may normalize optional launch flags out of its persisted inventory.
        # The wrapper enforces these flags on every launch; they are not identity bindings.
        return {key: value for key, value in self.environment(base, cwd).items()
                if key not in {"GROK_MEMORY", "GROK_AGENT_DASHBOARD"}}

    def check(self, base: Path) -> list[str]:
        errors = super().check(base)
        for name in ("config.toml", "auth.json"):
            if not (self.home(base) / name).is_file():
                errors.append(f"existing Grok {name} missing; no automatic login or credential copy")
        return errors


def adapter(spec: dict) -> ACPCommand:
    if not isinstance(spec, dict):
        raise ValueError("adapter configuration must be an object")
    classes = {"grok": Grok, "acp-command": ACPCommand}
    kind = spec.get("kind")
    if kind not in classes:
        raise ValueError("unsupported adapter; no implicit Grok fallback")
    return classes[kind](spec)
