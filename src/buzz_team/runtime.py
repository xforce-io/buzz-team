"""Identity-level boundaries, preserving existing executor homes and credentials."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys

from .adapters import adapter
from .config import Config, overlap


class Runtime:
    def __init__(self, config: Config, key: str):
        self.config = config
        self.key = key
        self.agent = config.agent(key)
        self.policy = config.data["policies"][self.agent["policy"]]
        self.base = config.state / key
        self.cwd = self.base / "workspace"
        self.executor = adapter(config.data["adapters"][self.agent["adapter"]])

    def env(self, inherited: dict[str, str]) -> dict[str, str]:
        env = dict(inherited)
        relay = env.get("BUZZ_RELAY_URL")
        if relay and relay.rstrip("/") != self.agent["relay_url"].rstrip("/"):
            raise ValueError("runtime identity belongs to a different community")
        self.executor.clean_inherited(env)
        env.update(self.executor.environment(self.base, self.cwd))
        env.update(BUZZ_RUNTIME_ID=self.key, BUZZ_TEAM_INSTANCE=str(self.config.instance),
                   TMPDIR=str(self.base / "tmp") + "/", XDG_CACHE_HOME=str(self.base / "cache"),
                   UV_CACHE_DIR=str(self.base / "cache/uv"), npm_config_cache=str(self.base / "cache/npm"),
                   CARGO_HOME=str(self.base / "cache/cargo"),
                   BUZZ_RUNTIME_LOG=str(self.base / "buzz-wrapper.log"),
                   BUZZ_REAL=self.config.data["binaries"]["buzz"],
                   BUZZ_DM_FILE=str(self.config.instance / "private/dm-channels.txt"),
                   PATH=str(self.config.instance / "bin") + os.pathsep + inherited.get("PATH", "/usr/bin:/bin"))
        # Project-specific application environment is instance data, not role-name logic.
        for name, values in self.config.data.get("data_environment", {}).items():
            value = values[self.policy["data_mode"]]
            env[name] = value.replace("{identity_root}", str(self.base))
        return env

    def profile(self) -> str:
        if self.policy["production_write"]:
            return "(version 1)\n(allow default)\n"
        q = json.dumps
        home = self.config.home
        lines = ["(version 1)", "(allow default)",
                 f"(deny file-write* (require-all (subpath {q(str(home))}) (require-not (subpath {q(str(self.base))}))))"]
        denied = {str(p) for p in self.base.parents if p != Path("/")}
        for item in self.config.data["production"]["protected_paths"]:
            path = Path(item).resolve()
            if overlap(path, self.base):
                raise ValueError("protected path overlaps runtime")
            lines.append(f"(deny file-write* (subpath {q(str(path))}))")
            denied.update(str(p) for p in path.parents if p != Path("/"))
        lines.extend(f"(deny file-write* (literal {q(p)}))" for p in sorted(denied))
        for port in self.config.data["production"]["blocked_ports"]:
            lines.extend(f'(deny network-outbound (remote {proto} "*:{port}"))' for proto in ("tcp", "udp"))
        lines.append('(deny process-exec (literal "/bin/launchctl") (literal "/usr/bin/osascript"))')
        return "\n".join(lines) + "\n"

    def command(self, argv: list[str]) -> list[str]:
        if self.policy["production_write"]:
            return argv
        if not Path("/usr/bin/sandbox-exec").is_file():
            raise ValueError("Seatbelt unavailable; refusing unconfined launch")
        return ["/usr/bin/sandbox-exec", "-p", self.profile(), *argv]

    def launch(self, mode: str, args: list[str]):
        from .instance import digest
        spec = self.config.data["compatibility"]
        pins = [(Path(self.executor.spec["command"]), spec.get("executor_sha256", {}).get(self.agent["adapter"]))]
        if mode == "harness":
            pins.append((Path(self.config.data["binaries"]["harness"]), spec["sha256"].get("harness")))
        for path, expected in pins:
            if not expected or not path.is_file() or digest(path) != expected:
                raise ValueError("launch executable differs from pinned baseline; run doctor")
        errors = self.executor.check(self.base)
        if errors:
            raise ValueError("; ".join(errors))
        if not self.cwd.is_dir():
            raise ValueError("existing identity workspace missing")
        env = self.env(dict(os.environ))
        binary = self.executor.spec["command"]
        if mode == "harness":
            binary = self.config.data["binaries"]["harness"]
            env["BUZZ_ACP_AGENT_COMMAND"] = str(self.config.instance / "bin/agent-executor")
        os.chdir(self.cwd)
        command = self.command([binary, *args])
        print(f"buzz-team: launching {mode} with bound identity", file=sys.stderr)
        os.execve(command[0], command, env)

    def git(self, args: list[str], cwd: Path) -> str:
        return subprocess.check_output(["git", *args], cwd=cwd, env=self.env(dict(os.environ)), text=True, timeout=120).strip()

    def workspace(self, task: str, name: str, ref: str, branch: str | None) -> Path:
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", task):
            raise ValueError("invalid task name")
        if branch and not re.fullmatch(r"feat/[0-9]+-[a-z0-9]+(?:-[a-z0-9]+)*", branch):
            raise ValueError("branch must use feat/<issue>-<description>")
        if name not in self.config.data["repositories"]:
            raise ValueError("unregistered repository")
        spec = self.config.data["repositories"][name]
        source = self.base / "repos" / name
        if not source.exists():
            original = Path(spec["source"])
            if self.git(["remote", "get-url", "origin"], original) != spec["origin"]:
                raise ValueError("source origin mismatch")
            source.parent.mkdir(parents=True, exist_ok=True)
            self.git(["clone", "--no-hardlinks", "--no-checkout", str(original), str(source)], source.parent)
            self.git(["remote", "set-url", "origin", spec["origin"]], source)
        if self.git(["remote", "get-url", "origin"], source) != spec["origin"]:
            raise ValueError("private origin mismatch")
        target = self.base / "worktrees" / f"{name}-{task}"
        if target.exists() or target.is_symlink():
            raise ValueError("task workspace exists; refusing overwrite")
        sha = self.git(["rev-parse", "--verify", "--end-of-options", ref + "^{commit}"], source)
        opts = ["-b", branch] if branch else ["--detach"]
        self.git(["worktree", "add", *opts, str(target), sha], source)
        return target
