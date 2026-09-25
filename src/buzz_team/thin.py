"""Local Seatbelt boundary for a Desktop-managed Grok ACP process."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys


SEATBELT = Path("/usr/bin/sandbox-exec")
_POLICY_ENV = "BUZZ_TEAM_POLICY_PATH"


def _path(value: object, name: str, *, directory: bool = True) -> Path:
    if not isinstance(value, str) or not value or "\0" in value:
        raise ValueError(f"{name} must be an absolute path")
    path = Path(value)
    if not path.is_absolute():
        raise ValueError(f"{name} must be an absolute path")
    resolved = path.resolve(strict=True)
    if directory and not resolved.is_dir():
        raise ValueError(f"{name} must be a directory")
    return resolved


def _overlap(a: Path, b: Path) -> bool:
    return a == b or a.is_relative_to(b) or b.is_relative_to(a)


def _load_policy(env: dict[str, str]) -> tuple[Path, Path, Path, list[Path]]:
    policy_file = _path(env.get(_POLICY_ENV), _POLICY_ENV, directory=False)
    if not policy_file.is_file():
        raise ValueError("Seatbelt policy file missing")
    if policy_file.stat().st_mode & 0o022:
        raise ValueError("Seatbelt policy file is group/world writable")
    policy = json.loads(policy_file.read_text())
    if not isinstance(policy, dict) or set(policy) != {"version", "grok_home", "grok_executable", "mode", "write_paths"}:
        raise ValueError("invalid Seatbelt policy fields")
    if policy["version"] != 1 or policy["mode"] not in {"development", "business"}:
        raise ValueError("unsupported Seatbelt policy")
    grok_home = _path(env.get("GROK_HOME"), "GROK_HOME")
    executable = _path(policy["grok_executable"], "Grok executable", directory=False)
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise ValueError("Grok executable unavailable")
    if grok_home != _path(policy["grok_home"], "policy grok_home"):
        raise ValueError("Seatbelt policy belongs to a different Grok home")
    if not isinstance(policy["write_paths"], list):
        raise ValueError("write_paths must be a list")
    if policy["mode"] == "development" and policy["write_paths"]:
        raise ValueError("development policy cannot write production paths")
    roots = [grok_home.parent, *(_path(value, "write path") for value in policy["write_paths"])]
    if len(roots) != len(set(roots)):
        raise ValueError("duplicate write path")
    if any(_overlap(policy_file, root) for root in roots):
        raise ValueError("Seatbelt policy file overlaps writable path")
    if any(_overlap(executable, root) for root in roots):
        raise ValueError("Grok executable overlaps writable path")
    return policy_file, grok_home, executable, roots


def _profile(roots: list[Path]) -> str:
    # Seatbelt predicates resolve path traversal and symlinks before matching.
    exceptions = " ".join(f"(require-not (subpath {json.dumps(str(root))}))" for root in roots)
    return ("(version 1)\n(allow default)\n"
            f'(deny file-write* (require-all {exceptions} (require-not (literal "/dev/null"))))\n')


def command(env: dict[str, str], args: list[str]) -> tuple[list[str], dict[str, str], Path]:
    if not SEATBELT.is_file():
        raise ValueError("Seatbelt unavailable; refusing unconfined launch")
    if not args or args[0] == "--" and len(args) == 1:
        raise ValueError("missing Grok arguments")
    if args[0] == "--":
        args = args[1:]
    if args[0] != "agent" or any("\0" in arg for arg in args):
        raise ValueError("invalid Grok argument")
    _, grok_home, executable, roots = _load_policy(env)
    cwd = _path(env.get("GROK_ACP_CWD"), "GROK_ACP_CWD")
    if not cwd.is_relative_to(grok_home.parent):
        raise ValueError("Grok working directory outside identity home")
    runtime_env = dict(env)
    runtime_env["GROK_SANDBOX"] = "off"
    tmp = _path(str(grok_home.parent / "tmp"), "TMPDIR")
    cache = _path(str(grok_home.parent / "cache"), "XDG_CACHE_HOME")
    if not tmp.is_relative_to(grok_home.parent) or not cache.is_relative_to(grok_home.parent):
        raise ValueError("temporary or cache directory outside identity home")
    for key, directory in {
        "TMPDIR": tmp,
        "XDG_CACHE_HOME": cache,
        "UV_CACHE_DIR": cache / "uv",
        "CARGO_HOME": cache / "cargo",
        "npm_config_cache": cache / "npm",
    }.items():
        runtime_env[key] = str(directory) + ("/" if key == "TMPDIR" else "")
    return [str(SEATBELT), "-p", _profile(roots), str(executable), *args], runtime_env, cwd


def main() -> int:
    try:
        argv, env, cwd = command(dict(os.environ), sys.argv[1:])
        os.chdir(cwd)
        os.execve(argv[0], argv, env)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"buzz-team-thin: {exc}", file=sys.stderr)
        return 126
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
