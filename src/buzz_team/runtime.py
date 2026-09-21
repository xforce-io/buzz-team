"""Identity-level boundaries, preserving existing executor homes and credentials."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import signal
import time
import uuid

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

    def env(self, inherited: dict[str, str], cwd: Path | None = None) -> dict[str, str]:
        cwd = cwd or self.cwd
        env = dict(inherited)
        relay = env.get("BUZZ_RELAY_URL")
        if relay and relay.rstrip("/") != self.agent["relay_url"].rstrip("/"):
            raise ValueError("runtime identity belongs to a different community")
        self.executor.clean_inherited(env)
        env.update(self.executor.environment(self.base, cwd))
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
        # The policy and the code enforcing it cannot be writable by its subject,
        # even when the administrator places them outside protected_home.
        control_paths = [self.config.instance, Path(__file__).absolute().parent,
                         sys.prefix, sys.base_prefix, sys.executable, self.executor.spec["command"],
                         *self.config.data["binaries"].values(),
                         self.config.data["desktop"]["managed_agents"],
                         self.config.data["desktop"]["app"]]
        protected = [self.config.production, *control_paths,
                     *self.config.data["production"]["protected_paths"]]
        # Protect both a symlink entry and its destination against replacement.
        paths = {path for item in protected for path in (Path(item).absolute(), Path(item).resolve())}
        for path in sorted(paths):
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

    def launch(self, mode: str, args: list[str], task_id: str | None = None,
               task_scope: str | None = None):
        from .instance import digest
        spec = self.config.data["compatibility"]
        pins = [(Path(self.executor.spec["command"]), spec.get("executor_sha256", {}).get(self.agent["adapter"]))]
        if mode == "harness":
            pins.append((Path(self.config.data["binaries"]["harness"]), spec["sha256"].get("harness")))
        for path, expected in pins:
            if not expected or not path.is_file() or digest(path) != expected:
                raise ValueError("launch executable differs from pinned baseline; run doctor")
        launch_cwd = self.cwd
        session = None
        store = None
        owner = None
        if task_id:
            from .context import ContextLedger
            from .sessions import SessionStore
            task_scope = task_scope or os.environ.get("BUZZ_TASK_SCOPE")
            if not self.executor.supports_task_sessions:
                raise ValueError("executor adapter cannot restore task sessions")
            inherited_owner = os.environ.get("BUZZ_ACP_SESSION_OWNER")
            if inherited_owner:
                workspace = os.environ.get("BUZZ_TASK_WORKSPACE")
                session_id = os.environ.get("BUZZ_ACP_SESSION_ID")
                if not workspace or not session_id:
                    raise ValueError("incomplete inherited task session")
                store = SessionStore(self.config.instance)
                session = store.resolve_task(task_id=task_id, identity=self.key,
                                             community=self.agent["relay_url"], scope=task_scope,
                                             read_only=True)
                if (session["state"] != "restoring" or session["restore_owner"] != inherited_owner
                        or session["session_id"] != session_id or session["workspace"] != str(Path(workspace).resolve())):
                    raise ValueError("session mapping restore ownership mismatch")
            else:
                store = SessionStore(self.config.instance)
                session = store.resolve_task(task_id=task_id, identity=self.key,
                                             community=self.agent["relay_url"], scope=task_scope)
            task_scope = session["scope"]
            launch_cwd = Path(session["workspace"]).resolve()
            if not launch_cwd.is_relative_to(self.base.resolve()) or not launch_cwd.is_dir():
                raise ValueError("task workspace missing or outside identity")
            session["session_id"] = self.executor.validate_task_session_id(session["session_id"], launch_cwd)
            self.executor.validate_task_session_binding(session["session_id"], self.base, launch_cwd)
            try:
                ContextLedger(self.config.instance, task_id).read_handoff()
            except ValueError as exc:
                if str(exc) not in {"context handoff unavailable", "context ledger not found"}:
                    raise
            else:
                raise ValueError("executor adapter cannot consume context handoff")
        errors = self.executor.check(self.base)
        if errors:
            raise ValueError("; ".join(errors))
        if not launch_cwd.is_dir():
            raise ValueError("existing identity workspace missing")
        inherited_owner = os.environ.get("BUZZ_ACP_SESSION_OWNER") if session else None
        claimed = False
        if session:
            owner = inherited_owner
            if inherited_owner and session["restore_owner"] != inherited_owner:
                raise ValueError("session mapping restore ownership mismatch")
        env = self.env(dict(os.environ), launch_cwd)
        if session:
            env.update(BUZZ_TASK_ID=task_id, BUZZ_ACP_SESSION_ID=session["session_id"],
                       BUZZ_ACP_SESSION_SCOPE=session["scope"], BUZZ_TASK_SCOPE=session["scope"],
                       BUZZ_TASK_WORKSPACE=str(launch_cwd))
            if self.executor.kind == "grok":
                env["GROK_SESSION_ID"] = session["session_id"]
            if owner:
                env["BUZZ_ACP_SESSION_OWNER"] = owner
        binary = self.executor.spec["command"]
        if mode == "harness":
            binary = self.config.data["binaries"]["harness"]
            env["BUZZ_ACP_AGENT_COMMAND"] = str(self.config.instance / "bin/agent-executor")
        task_args = self.executor.task_session_args(session["session_id"]) if session and mode == "executor" else []
        command = self.command([binary, *task_args, *args])
        print(f"buzz-team: launching {mode} with bound identity", file=sys.stderr)
        if task_id and not inherited_owner:
            ready_r, ready_w = os.pipe()
            token = uuid.uuid4().hex
            child = os.fork()
            if child == 0:
                os.close(ready_w)
                os.setpgid(0, 0)
                child_owner = f"{os.getpid()}-{token}"
                env["BUZZ_ACP_SESSION_OWNER"] = child_owner
                try:
                    if os.read(ready_r, 1) != b"1":
                        os._exit(126)
                    os.close(ready_r)
                    os.chdir(launch_cwd)
                    os.execve(command[0], command, env)
                finally:
                    os._exit(127)
            os.close(ready_r)
            try:
                os.setpgid(child, child)
            except ProcessLookupError:
                pass
            owner = f"{child}-{token}"
            exit_code = None
            try:
                session = store.claim(community=session["community"], identity=session["identity"],
                                      scope=session["scope"], task_id=session["task_id"],
                                      workspace=session["workspace"], owner=owner)
                claimed = True
                os.write(ready_w, b"1")
                os.close(ready_w)
                previous = {}
                def forward(signum, _frame):
                    try:
                        os.killpg(child, signum)
                    except ProcessLookupError:
                        pass
                for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
                    previous[signum] = signal.signal(signum, forward)
                try:
                    _, status = os.waitpid(child, 0)
                    exit_code = os.waitstatus_to_exitcode(status)
                    return 128 + (-exit_code) if exit_code < 0 else exit_code
                finally:
                    try:
                        os.killpg(child, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                    deadline = time.monotonic() + 2
                    while time.monotonic() < deadline:
                        try:
                            os.killpg(child, 0)
                        except ProcessLookupError:
                            break
                        time.sleep(0.01)
                    else:
                        try:
                            os.killpg(child, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                    for signum, handler in previous.items():
                        signal.signal(signum, handler)
            except Exception:
                try:
                    os.kill(child, signal.SIGTERM)
                    os.waitpid(child, 0)
                except (ProcessLookupError, ChildProcessError):
                    pass
                raise
            finally:
                try:
                    os.close(ready_w)
                except OSError:
                    pass
                if claimed and store and owner:
                    finish = store.release if exit_code == 0 else store.fail
                    finish(community=session["community"], identity=session["identity"],
                           scope=session["scope"], task_id=session["task_id"],
                           workspace=session["workspace"], owner=owner)
        os.chdir(launch_cwd)
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
