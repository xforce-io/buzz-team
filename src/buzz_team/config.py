"""Validate trusted administrator configuration; never load a fallback identity."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re


def identity(relay: str, pubkey: str) -> str:
    if not isinstance(pubkey, str) or not re.fullmatch(r"[0-9a-f]{64}", pubkey):
        raise ValueError("invalid public key")
    if not isinstance(relay, str) or not relay.startswith(("ws://", "wss://")):
        raise ValueError("invalid relay URL")
    return hashlib.sha256(relay.rstrip("/").encode()).hexdigest()[:16] + "/" + pubkey


def absolute(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise ValueError("configured paths must be absolute")
    return path.resolve()


def overlap(a: Path, b: Path) -> bool:
    return a.is_relative_to(b) or b.is_relative_to(a)


class Config:
    def __init__(self, instance: Path, *, data: dict | None = None):
        self.instance = instance.resolve()
        self.path = self.instance / "instance.local.json"
        if data is None and not self.path.is_file():
            raise ValueError("instance missing; run init first")
        self.data = json.loads(self.path.read_text()) if data is None else data
        c = self.data
        if not isinstance(c, dict):
            raise ValueError("instance configuration must be an object")
        if c.get("version") != 2:
            raise ValueError("unsupported instance configuration version")
        for name in ("production", "policies", "repositories", "agents", "adapters", "binaries", "desktop", "compatibility"):
            if not isinstance(c.get(name), dict):
                raise ValueError("missing or invalid configuration section")
        for name in ("sha256", "executor_sha256"):
            if not isinstance(c["compatibility"].get(name), dict):
                raise ValueError("compatibility digest maps must be objects")
        self.state = absolute(c["state_root"])
        self.home = absolute(c["protected_home"])
        self.production = absolute(c["production"]["data_root"])
        if (overlap(self.state, self.production) or overlap(self.instance, self.state)
                or overlap(self.instance, self.production)):
            raise ValueError("instance, runtime and production boundaries overlap")
        for port in c["production"]["blocked_ports"]:
            if type(port) is not int or not 0 < port < 65536:
                raise ValueError("invalid protected port")
        for path in c["production"]["protected_paths"]:
            if overlap(self.state, absolute(path)):
                raise ValueError("protected path overlaps runtime")
        if not isinstance(c["agents"], dict) or not c["agents"]:
            raise ValueError("no registered identities")
        if any(not isinstance(policy, dict) for policy in c["policies"].values()):
            raise ValueError("policy configuration must be an object")
        from .adapters import adapter
        for key, agent in c["agents"].items():
            if identity(agent["relay_url"], agent["pubkey"]) != key:
                raise ValueError("identity binding mismatch")
            policy = c["policies"][agent["policy"]]
            if type(policy.get("production_write")) is not bool:
                raise ValueError("production_write must be explicit boolean")
            if policy.get("data_mode") not in {"test", "production"}:
                raise ValueError("unknown data_mode")
            selected = adapter(c["adapters"][agent["adapter"]])
            selected.validate()
            if not policy["production_write"] and not self.state.is_relative_to(self.home):
                raise ValueError("protected_home must cover the entire identity state root")
        for name, repo in c["repositories"].items():
            if not re.fullmatch(r"[a-z0-9-]+", name):
                raise ValueError("invalid repository name")
            absolute(repo["source"])
            if not isinstance(repo["origin"], str) or not repo["origin"]:
                raise ValueError("missing repository origin")
        for path in c["binaries"].values():
            absolute(path)
        environment = c.get("data_environment", {})
        if not isinstance(environment, dict):
            raise ValueError("data environment must be an object")
        modes = {c["policies"][agent["policy"]]["data_mode"] for agent in c["agents"].values()}
        for name, values in environment.items():
            if (not isinstance(name, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]*", name)
                    or name.startswith(("BUZZ_", "GROK_", "DYLD_", "LD_", "PYTHON"))
                    or name in {"HOME", "PATH", "TMPDIR", "XDG_CACHE_HOME", "CARGO_HOME", "UV_CACHE_DIR", "XAI_API_KEY"}):
                raise ValueError("invalid or conflicting data environment")
            if (not isinstance(values, dict) or not modes.issubset(values)
                    or any(mode not in {"test", "production"} or not isinstance(value, str) or "\0" in value
                           for mode, value in values.items())):
                raise ValueError("data environment requires string values for configured data modes")
        absolute(c["desktop"]["managed_agents"])
        absolute(c["desktop"]["app"])

    def agent(self, key: str) -> dict:
        if key not in self.data["agents"]:
            raise ValueError("unregistered identity; shared fallback is forbidden")
        return self.data["agents"][key]
