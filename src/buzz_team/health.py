"""Structured health checks: pass / fail / unverified / na with component axes."""
from __future__ import annotations

import importlib.resources
import json
import os
import re
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from . import __version__
from .config import Config
from . import desktop
from .instance import digest
from .runtime import Runtime, SEATBELT_EXEC, probeNestedSeatbeltApply, underSeatbelt

STATUSES = frozenset({"pass", "fail", "unverified", "na"})
COMPONENTS = frozenset({"dev_env", "install", "buzz_runtime", "external_deps", "proxy"})

# Proxy-related keys compared by name; values are redacted to host:port only.
PROXY_ENV_KEYS = (
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
    "http_proxy", "https_proxy", "all_proxy", "no_proxy",
    "SOCKS_PROXY", "socks_proxy",
)

UNVERIFIED_SURFACES = (
    "role_dialogue",
    "model_upstream_request",
    "external_bridge_live_request",
    "desktop_activity_ui",
    "channel_thread_attribution",
    "skills_memory_readiness",
    "upstream_cache_behavior",
)


def check(id: str, status: str, component: str, summary: str) -> dict[str, str]:
    if status not in STATUSES:
        raise ValueError(f"invalid check status: {status}")
    if component not in COMPONENTS:
        raise ValueError(f"invalid check component: {component}")
    return {"id": id, "status": status, "component": component, "summary": summary}


_DEPRECATED_WRAPPER = "grok-acp-wrapper"


def _inventory_pubkey(row: dict) -> str:
    value = row.get("pubkey")
    if isinstance(value, str):
        return value.strip()
    return ""


def _inventory_commands(row: dict) -> str:
    parts = []
    for key in ("agent_command", "agent_command_override", "acp_command"):
        value = row.get(key)
        if isinstance(value, str):
            parts.append(value)
    return "\n".join(parts)


def _inventory_runtime_id(row: dict) -> str:
    env = row.get("env_vars")
    if isinstance(env, dict):
        value = env.get("BUZZ_RUNTIME_ID")
        if isinstance(value, str):
            return value
    return ""


def classify_desktop_inventory(agents: dict, rows: list) -> list[dict[str, str]]:
    """Classify a Desktop inventory against this instance. Does not mutate rows.

    Empty-pubkey launch rows are attributed to this instance only when they
    point at the retired grok-acp-wrapper or already carry this instance's
    BUZZ_RUNTIME_ID. Same display name is not treated as the same pubkey.
    Rows outside that set are reported and left in place.
    """
    if not isinstance(rows, list):
        return [check(
            "inventory_shape", "fail", "buzz_runtime",
            "Desktop inventory is not a list")]
    by_pubkey: dict[str, str] = {}
    relays: dict[str, str] = {}
    for key, agent in agents.items():
        if not isinstance(agent, dict):
            continue
        pubkey = agent.get("pubkey")
        relay = agent.get("relay_url")
        if isinstance(pubkey, str) and pubkey:
            by_pubkey[pubkey] = key
        if isinstance(relay, str):
            relays[key] = relay
    seen: dict[str, list[int]] = {key: [] for key in agents}
    checks: list[dict[str, str]] = []
    outside = 0
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            checks.append(check(
                f"inventory_shape:{index}", "fail", "buzz_runtime",
                f"inventory row {index} is not an object"))
            continue
        pubkey = _inventory_pubkey(row)
        commands = _inventory_commands(row)
        runtime_id = _inventory_runtime_id(row)
        if not pubkey:
            if _DEPRECATED_WRAPPER in commands or runtime_id in seen:
                reason = "empty pubkey"
                if _DEPRECATED_WRAPPER in commands:
                    reason += " on a grok-acp-wrapper launch row"
                checks.append(check(
                    f"inventory_empty_pubkey:{index}", "fail", "buzz_runtime",
                    f"inventory row {index} has {reason}"))
            else:
                outside += 1
            continue
        key = by_pubkey.get(pubkey)
        if key is None:
            outside += 1
            continue
        seen[key].append(index)
        reasons = []
        relay = row.get("relay_url")
        expected = relays.get(key)
        if isinstance(expected, str) and relay != expected:
            reasons.append("relay_url")
        if runtime_id and runtime_id != key:
            reasons.append("BUZZ_RUNTIME_ID")
        if reasons:
            checks.append(check(
                f"inventory_binding_mismatch:{key[:20]}", "fail", "buzz_runtime",
                f"inventory row for {key[:20]} disagrees on {', '.join(reasons)}"))
    for key, indexes in seen.items():
        if not indexes:
            checks.append(check(
                f"inventory_missing:{key[:20]}", "fail", "buzz_runtime",
                f"instance identity {key[:20]} has no inventory row"))
        elif len(indexes) > 1:
            checks.append(check(
                f"inventory_duplicate:{key[:20]}", "fail", "buzz_runtime",
                f"instance identity {key[:20]} has {len(indexes)} launch rows"))
    checks.append(check(
        "inventory_non_instance", "pass", "buzz_runtime",
        f"reported {outside} inventory row(s) outside this instance; not deleted"))
    return checks


def redact_endpoint(value: str | None) -> str | None:
    """Return host:port only; never credentials, paths, or query strings.

    Bypass lists (NO_PROXY) and malformed values must never raise — they become
    opaque markers so doctor/diagnose cannot crash on operator environment.
    """
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    # Comma/CIDR bypass lists are not single URLs (common NO_PROXY shape).
    if "," in text or "/" in text.split(":")[0]:
        return "<bypass-list>"
    if "://" not in text and "@" not in text and re.fullmatch(r"[^/\s:]+(?::\d+)?", text):
        return text
    try:
        parsed = urlparse(text if "://" in text else f"http://{text}")
        host = parsed.hostname
        if not host:
            return "<redacted>"
        port = parsed.port
    except ValueError:
        return "<redacted>"
    if port is None:
        return host
    return f"{host}:{port}"


def _proxy_map(env: dict[str, str]) -> dict[str, str | None]:
    result: dict[str, str | None] = {}
    for key in PROXY_ENV_KEYS:
        if key not in env or not env[key]:
            continue
        # NO_PROXY is a bypass list — record key presence with opaque marker only.
        if key.lower() == "no_proxy":
            result[key] = "<bypass-list>"
        else:
            result[key] = redact_endpoint(env[key])
    return result



def _canonical_proxy_endpoints(proxy: dict[str, str | None]) -> dict[str, str]:
    """Collapse HTTP(S)/ALL proxy env aliases to one endpoint per family (ignore NO_PROXY)."""
    families = {
        "HTTP_PROXY": ("HTTP_PROXY", "http_proxy"),
        "HTTPS_PROXY": ("HTTPS_PROXY", "https_proxy"),
        "ALL_PROXY": ("ALL_PROXY", "all_proxy", "SOCKS_PROXY", "socks_proxy"),
    }
    out: dict[str, str] = {}
    for canon, aliases in families.items():
        for alias in aliases:
            value = proxy.get(alias)
            if value and value not in {"<redacted>", "<bypass-list>"}:
                out[canon] = value
                break
    return out

def _parse_host_port(endpoint: str | None) -> tuple[str, int] | None:
    if not endpoint or endpoint in {"<redacted>", "<bypass-list>"}:
        return None
    if ":" in endpoint:
        host, _, port_text = endpoint.rpartition(":")
        try:
            return host, int(port_text)
        except ValueError:
            return None
    return None


def probe_tcp(host: str, port: int, timeout: float = 1.0) -> str:
    """Return pass|fail for a TCP connect; never raises on network errors."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return "pass"
    except OSError:
        return "fail"


def _parse_ps_environ(blob: str) -> dict[str, str]:
    """Extract KEY=VALUE pairs of interest from a `ps eww` command blob."""
    found: dict[str, str] = {}
    for token in blob.split():
        if "=" not in token:
            continue
        key, _, value = token.partition("=")
        if key in PROXY_ENV_KEYS and value:
            found[key] = value
    return found


def _read_process_environ(pid: object) -> dict[str, str]:
    """Read proxy-related env from a live process; never raises; never returns secrets beyond proxy URLs."""
    try:
        pid_i = int(pid)
    except (TypeError, ValueError):
        return {}
    if pid_i <= 0:
        return {}
    proc = Path(f"/proc/{pid_i}/environ")
    if proc.is_file():
        try:
            raw = proc.read_bytes().split(b"\0")
        except OSError:
            return {}
        out: dict[str, str] = {}
        for item in raw:
            if not item or b"=" not in item:
                continue
            key_b, _, val_b = item.partition(b"=")
            try:
                key = key_b.decode()
                val = val_b.decode(errors="replace")
            except UnicodeDecodeError:
                continue
            if key in PROXY_ENV_KEYS and val:
                out[key] = val
        return out
    try:
        completed = subprocess.run(
            ["ps", "ewww", "-p", str(pid_i), "-o", "command="],
            capture_output=True, text=True, timeout=2, check=False)
    except (OSError, subprocess.SubprocessError):
        return {}
    if completed.returncode != 0 or not completed.stdout:
        return {}
    return _parse_ps_environ(completed.stdout)



def _agent_pids_dir(managed_agents: Path) -> Path:
    """Desktop writes live ACP pids next to managed-agents.json (not runtime_pid)."""
    return managed_agents.resolve().parent / "agent-pids"


def _pidIsAlive(pid: int) -> bool:
    """True only when the process exists. pid>0 is not sufficient (stale Desktop leftovers)."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _load_agent_pid_index(
    managed_agents: Path,
    *,
    pidIsAlive=_pidIsAlive,
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    """Map agent pubkey -> live pid; collect dead agent-pid files separately.

    A numeric pid>0 is not live. Stale leftovers (e.g. dead `__283d*` files)
    must not be counted as healthy ACP processes.
    """
    live: dict[str, int] = {}
    dead: list[dict[str, Any]] = []
    root = _agent_pids_dir(managed_agents)
    if not root.is_dir():
        return live, dead
    for path in sorted(root.glob("*.json")):
        pubkey = path.name.split("__", 1)[0]
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError, TypeError):
            continue
        if not isinstance(data, dict):
            continue
        pid = data.get("pid")
        try:
            pidI = int(pid)
        except (TypeError, ValueError):
            continue
        if pidI <= 0 or not re.fullmatch(r"[0-9a-f]{64}", pubkey):
            continue
        if not pidIsAlive(pidI):
            dead.append({"pubkey": pubkey, "pid": pidI, "file": path.name})
            continue
        live[pubkey] = pidI
    return live, dead


def _resolve_acp_pid(row: dict, pid_index: dict[str, int]) -> int | None:
    raw = row.get("runtime_pid")
    try:
        if raw is not None and int(raw) > 0:
            return int(raw)
    except (TypeError, ValueError):
        pass
    pubkey = row.get("pubkey")
    if isinstance(pubkey, str) and pubkey in pid_index:
        return pid_index[pubkey]
    return None

def _read_desktop_proxy_maps(
    config: Config,
    *,
    process_reader=_read_process_environ,
    pidIsAlive=_pidIsAlive,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Load per-identity Desktop binding + live ACP process proxy maps."""
    checks: list[dict[str, str]] = []
    maps: list[dict[str, Any]] = []
    path = Path(config.data["desktop"]["managed_agents"])
    if not path.is_file():
        checks.append(check(
            "desktop_inventory", "fail", "buzz_runtime",
            "Desktop managed-agents inventory missing; cannot contrast proxy settings"))
        return maps, checks
    try:
        rows = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError, TypeError):
        checks.append(check(
            "desktop_inventory", "fail", "buzz_runtime",
            "Desktop managed-agents inventory unreadable or mismatched"))
        return maps, checks
    inventory = classify_desktop_inventory(config.data.get("agents") or {}, rows)
    checks.extend(inventory)
    anomaly = any(
        item["status"] == "fail" and item["id"].startswith("inventory_")
        for item in inventory)
    try:
        selected = desktop.selected_rows(config, rows)
    except (ValueError, TypeError, KeyError):
        checks.append(check(
            "desktop_inventory", "fail", "buzz_runtime",
            "Desktop managed-agents inventory has instance anomalies"
            if anomaly else
            "Desktop managed-agents inventory unreadable or mismatched"))
        return maps, checks
    if anomaly:
        checks.append(check(
            "desktop_inventory", "fail", "buzz_runtime",
            "Desktop managed-agents inventory has instance anomalies"))
    else:
        checks.append(check(
            "desktop_inventory", "pass", "buzz_runtime",
            "Desktop managed-agents inventory readable for bound identities"))
    pidIndex, deadPids = _load_agent_pid_index(path, pidIsAlive=pidIsAlive)
    pubkeyToRef = {
        row["pubkey"]: key[:20]
        for key, row in selected.items()
        if isinstance(row.get("pubkey"), str)
    }
    for entry in deadPids:
        identityRef = pubkeyToRef.get(entry["pubkey"], entry["pubkey"][:20])
        checks.append(check(
            f"desktop_agent_pid:{identityRef}:{entry['pid']}",
            "fail",
            "proxy",
            f"agent-pid file {entry['file']} for {identityRef} references dead process "
            f"pid={entry['pid']}; pid>0 is not proof of liveness"))
    if pidIndex:
        checks.append(check(
            "desktop_agent_pids", "pass", "proxy",
            f"Loaded {len(pidIndex)} live ACP pid(s) from agent-pids next to managed-agents"))
    elif selected and not deadPids and not any(
            (row.get("runtime_pid") not in (None, "", 0, "0")) for row in selected.values()):
        checks.append(check(
            "desktop_agent_pids", "unverified", "proxy",
            f"No agent-pids index at {_agent_pids_dir(path)} and managed-agents runtime_pid empty"))
    process_reads = 0
    for key, row in selected.items():
        env = row.get("env_vars") or {}
        if not isinstance(env, dict):
            checks.append(check(
                f"desktop_env_vars:{key[:20]}", "fail", "buzz_runtime",
                "Desktop env_vars is not an object for a bound identity"))
            continue
        binding_proxy = _proxy_map({str(k): str(v) for k, v in env.items() if isinstance(v, str)})
        binding_keys = sorted(k for k in PROXY_ENV_KEYS if k in env)
        pid = _resolve_acp_pid(row, pidIndex)
        proc_env = process_reader(pid) if pid is not None else {}
        if proc_env:
            process_reads += 1
        process_proxy = _proxy_map(proc_env)
        process_keys = sorted(process_proxy)
        maps.append({
            "identity_ref": key[:20],
            "proxy": binding_proxy,
            "proxy_keys": binding_keys,
            "process_proxy": process_proxy,
            "process_proxy_keys": process_keys,
            "runtime_pid": pid,
        })
    if selected and process_reads == 0:
        checks.append(check(
            "desktop_acp_process_env", "unverified", "proxy",
            "No live ACP process proxy env readable "
            "(tried managed-agents runtime_pid and agent-pids/*.json); "
            "binding JSON alone cannot cover Desktop-baked proxy accidents"))
    elif process_reads:
        checks.append(check(
            "desktop_acp_process_env", "pass", "proxy",
            f"Read proxy-related env from {process_reads} live ACP process(es) "
            "(runtime_pid or agent-pids)"))
    return maps, checks


def _cli_proxy_map(env: dict[str, str] | None = None) -> dict[str, str | None]:
    return _proxy_map(env if env is not None else dict(os.environ))


def contrast_proxies(
    config: Config,
    *,
    process_env: dict[str, str] | None = None,
    probe: bool = False,
    process_reader=_read_process_environ,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Compare Desktop ACP binding + live process proxy vs CLI process proxy env.

    Values are host:port only. Dead/unreachable endpoints are attributed to proxy,
    never to auth-file absence. Binding JSON without process env is insufficient for
    Desktop-baked proxy accidents (see issue #11 repro #6).
    """
    checks: list[dict[str, str]] = []
    desktop_maps, inventory_checks = _read_desktop_proxy_maps(config, process_reader=process_reader)
    checks.extend(inventory_checks)
    cli_map = _cli_proxy_map(process_env)
    cli_keys = sorted(k for k in cli_map if k.lower() != "no_proxy")
    mismatches: list[str] = []
    process_mismatches: list[str] = []
    for item in desktop_maps:
        d_keys = set(item["proxy_keys"])
        c_keys = set(cli_keys)
        if d_keys and d_keys != c_keys:
            only_desktop = sorted(d_keys - c_keys)
            only_cli = sorted(c_keys - d_keys)
            parts = []
            if only_desktop:
                parts.append("desktop_only_keys=" + ",".join(only_desktop))
            if only_cli:
                parts.append("cli_only_keys=" + ",".join(only_cli))
            mismatches.append(f"{item['identity_ref']}:{' '.join(parts)}")
        for key, endpoint in item["proxy"].items():
            if key.lower() == "no_proxy":
                continue
            cli_ep = cli_map.get(key)
            if endpoint and cli_ep and endpoint != cli_ep:
                mismatches.append(
                    f"{item['identity_ref']}:{key} binding={endpoint} cli={cli_ep}")
        proc_canon = _canonical_proxy_endpoints(item.get("process_proxy") or {})
        cli_canon = _canonical_proxy_endpoints(cli_map)
        cli_endpoints = set(cli_canon.values())
        for key, endpoint in proc_canon.items():
            cli_ep = cli_canon.get(key)
            if endpoint and cli_ep and endpoint != cli_ep:
                process_mismatches.append(
                    f"{item['identity_ref']}:{key} acp_process={endpoint} cli={cli_ep}")
            elif endpoint and key not in cli_canon:
                # ALL_PROXY-only on ACP is fine when CLI already uses same host:port via HTTP(S)_PROXY.
                if key == "ALL_PROXY" and endpoint in cli_endpoints:
                    continue
                if key in {"HTTP_PROXY", "HTTPS_PROXY"}:
                    process_mismatches.append(
                        f"{item['identity_ref']}:{key} acp_process={endpoint} cli=<absent>")

    desktop_declares = any(item["proxy_keys"] for item in desktop_maps)
    process_declares = any(item.get("process_proxy_keys") for item in desktop_maps)

    if not desktop_maps:
        status = "unverified" if any(c["status"] == "fail" for c in inventory_checks) else "na"
        checks.append(check(
            "proxy_contrast", status, "proxy",
            "Desktop proxy contrast unavailable; CLI process proxy keys recorded only"))
    elif process_mismatches:
        checks.append(check(
            "proxy_contrast", "fail", "proxy",
            "Desktop ACP *process* proxy differs from CLI process proxy "
            f"({len(process_mismatches)} difference(s)); dead/baked proxy is not auth-file failure"))
    elif mismatches and desktop_declares:
        checks.append(check(
            "proxy_contrast", "fail", "proxy",
            "Desktop ACP *binding* proxy differs from CLI process proxy "
            f"({len(mismatches)} difference(s)); dead proxy is not auth-file failure"))
    elif process_declares and not process_mismatches:
        checks.append(check(
            "proxy_contrast", "pass", "proxy",
            "Desktop ACP process proxy aligns with CLI process proxy (host:port); "
            "binding JSON may still omit proxy keys"))
    elif not desktop_declares and not process_declares and cli_keys:
        checks.append(check(
            "proxy_contrast", "unverified", "proxy",
            "Neither Desktop binding nor readable ACP process declared proxy keys; "
            "CLI process proxy present — contrast incomplete; dead proxy still not auth-file failure"))
    elif not desktop_declares and not process_declares and not cli_keys:
        checks.append(check(
            "proxy_contrast", "na", "proxy",
            "No proxy environment keys on Desktop binding, ACP process, or CLI"))
    else:
        checks.append(check(
            "proxy_contrast", "pass", "proxy",
            "Desktop ACP and CLI process proxy key names and redacted endpoints align"))

    probes: list[dict[str, str]] = []
    if probe:
        seen: set[tuple[str, int]] = set()
        endpoints: list[str | None] = list(cli_map.values())
        for item in desktop_maps:
            endpoints.extend(item["proxy"].values())
            endpoints.extend((item.get("process_proxy") or {}).values())
        for endpoint in endpoints:
            target = _parse_host_port(endpoint)
            if not target or target in seen:
                continue
            seen.add(target)
            host, port = target
            result = probe_tcp(host, port)
            probes.append({"endpoint": f"{host}:{port}", "tcp": result})
            if result == "fail":
                checks.append(check(
                    f"proxy_tcp:{host}:{port}", "fail", "proxy",
                    f"Proxy endpoint {host}:{port} unreachable (TCP); "
                    "attribute to proxy/endpoint, not auth.json absence"))
            else:
                checks.append(check(
                    f"proxy_tcp:{host}:{port}", "pass", "proxy",
                    f"Proxy endpoint {host}:{port} accepts TCP connect"))
        if not seen:
            checks.append(check(
                "proxy_tcp", "unverified", "proxy",
                "No redacted proxy host:port to probe; upstream request still unverified"))

    contrast = {
        "cli_process": {"keys": cli_keys, "endpoints": {k: cli_map[k] for k in cli_keys}},
        "desktop_bindings": [
            {"identity_ref": m["identity_ref"], "keys": m["proxy_keys"], "endpoints": m["proxy"]}
            for m in desktop_maps
        ],
        "desktop_acp_processes": [
            {
                "identity_ref": m["identity_ref"],
                "runtime_pid": m.get("runtime_pid"),
                "keys": m.get("process_proxy_keys") or [],
                "endpoints": m.get("process_proxy") or {},
            }
            for m in desktop_maps
        ],
        "mismatches": mismatches,
        "process_mismatches": process_mismatches,
        "tcp_probes": probes,
        "note": (
            "Proxy contrast uses key names and host:port only; "
            "credentials and full URLs are never emitted. "
            "Auth-file presence does not prove proxy health. "
            "Binding JSON and live ACP process env are contrasted separately."
        ),
    }
    return contrast, checks



def _git_boundary_check() -> dict[str, str]:
    """Document S4 boundary: non-git directories are na, not git tool failure."""
    return check(
        "git_directory_boundary", "na", "buzz_runtime",
        "Git status applies only inside a real repository; non-repo source dirs are "
        "not applicable (na), not 'git unavailable'. Business prompts are out of scope.")


def _seatbeltDevEnvChecks() -> list[dict[str, str]]:
    """Seatbelt presence plus nested-apply / inherit semantics."""
    if sys.platform != "darwin":
        return [check(
            "tool_seatbelt", "na", "dev_env",
            "Seatbelt applies on macOS only; not applicable on this platform for unrestricted writer identities")]
    if not SEATBELT_EXEC.is_file():
        return [check("tool_seatbelt", "fail", "dev_env", "Seatbelt unavailable")]
    confined = underSeatbelt()
    nested = probeNestedSeatbeltApply()
    if nested == "nested_ok":
        nestedSummary = (
            "nested sandbox_apply works; development launch still inherits when already confined")
    else:
        nestedSummary = (
            "nested sandbox_apply unavailable; development launch inherits existing confinement")
    if confined:
        nestedSummary += "; this process is already confined"
    return [
        check(
            "tool_seatbelt", "pass", "dev_env",
            "Seatbelt sandbox-exec present; development launch wraps once then inherits"),
        check("tool_seatbelt_nested", "pass", "dev_env", nestedSummary),
    ]


def collect_checks(config: Config, *, depth: str = "doctor",
                   process_env: dict[str, str] | None = None) -> tuple[list[dict[str, str]], dict[str, Any]]:
    if depth not in {"doctor", "diagnose"}:
        raise ValueError("depth must be doctor or diagnose")
    checks: list[dict[str, str]] = []
    extras: dict[str, Any] = {}

    # --- Component: install (Desktop app + pinned binaries) ---
    app_errors = desktop.check_app(config)
    if app_errors:
        for message in app_errors:
            checks.append(check("desktop_app", "fail", "install", message))
    else:
        checks.append(check(
            "desktop_app", "pass", "install",
            "Desktop app bundle matches compatibility baseline"))

    for name, path in config.data["binaries"].items():
        file = Path(path)
        pin = config.data["compatibility"]["sha256"].get(name)
        if not file.is_file() or not os.access(file, os.X_OK):
            checks.append(check(
                f"binary:{name}", "fail", "install", f"{name}: missing executable"))
        elif not pin or digest(file) != pin:
            checks.append(check(
                f"binary:{name}", "fail", "install",
                f"{name}: executable differs from pinned baseline"))
        else:
            checks.append(check(
                f"binary:{name}", "pass", "install",
                f"{name}: matches pinned baseline digest"))

    for name, spec in config.data["adapters"].items():
        pin = config.data["compatibility"].get("executor_sha256", {}).get(name)
        command = Path(spec["command"])
        if (not pin or not command.is_file() or not os.access(command, os.X_OK)
                or digest(command) != pin):
            checks.append(check(
                f"executor_pin:{name}", "fail", "install",
                "executor differs from pinned baseline or is not pinned"))
        else:
            checks.append(check(
                f"executor_pin:{name}", "pass", "install",
                f"executor {name} matches pinned baseline"))

    # Harness CLI capability — only attempt when install surface otherwise clean enough.
    install_fails = [c for c in checks if c["component"] == "install" and c["status"] == "fail"]
    if not install_fails:
        try:
            manifest = json.loads(
                importlib.resources.files("buzz_team").joinpath("compatibility.json").read_text())
            result = __import__("subprocess").run(
                [config.data["binaries"]["harness"], "--help"],
                capture_output=True, text=True, timeout=15)
            if result.returncode or any(
                    flag not in result.stdout for flag in manifest["required_harness_options"]):
                checks.append(check(
                    "harness_capability", "fail", "install",
                    "harness: required CLI capability missing"))
            else:
                checks.append(check(
                    "harness_capability", "pass", "install",
                    "harness exposes required CLI options"))
        except (OSError, ValueError, KeyError) as exc:
            checks.append(check(
                "harness_capability", "fail", "install",
                f"harness: capability probe failed ({type(exc).__name__})"))
    else:
        checks.append(check(
            "harness_capability", "unverified", "install",
            "harness capability not probed because install checks already failed"))

    # --- Component: dev_env ---
    if shutil.which("lsof"):
        checks.append(check("tool_lsof", "pass", "dev_env", "lsof available for idle workspace checks"))
    else:
        checks.append(check(
            "tool_lsof", "fail", "dev_env",
            "lsof unavailable; cannot verify idle identity workspaces"))
    checks.extend(_seatbeltDevEnvChecks())

    # --- Component: buzz_runtime (per-identity) ---
    counts: dict[str, int] = {}
    for key in config.data["agents"]:
        runtime = Runtime(config, key)
        counts[runtime.executor.kind] = counts.get(runtime.executor.kind, 0) + 1
        # Prefer structured credential-file reporting for Grok.
        from .adapters import Grok
        if isinstance(runtime.executor, Grok):
            home = runtime.executor.home(runtime.base)
            if not Path(runtime.executor.spec["command"]).is_file() or not os.access(
                    runtime.executor.spec["command"], os.X_OK):
                checks.append(check(
                    f"executor_binary:{key[:20]}", "fail", "buzz_runtime",
                    "executor binary missing or not executable"))
            elif not home.is_dir():
                checks.append(check(
                    f"executor_home:{key[:20]}", "fail", "buzz_runtime",
                    "executor home missing; initialization is executor-specific"))
            else:
                checks.append(check(
                    f"executor_home:{key[:20]}", "pass", "buzz_runtime",
                    "executor home directory present"))
            missing = [name for name in ("config.toml", "auth.json") if not (home / name).is_file()]
            if missing:
                checks.append(check(
                    f"grok_credentials_files:{key[:20]}", "fail", "buzz_runtime",
                    "Grok credential files missing (" + ", ".join(missing)
                    + "); file presence only — distinct from proxy/upstream_request"))
            else:
                checks.append(check(
                    f"grok_credentials_files:{key[:20]}", "pass", "buzz_runtime",
                    "Grok config.toml and auth.json present (file presence only; "
                    "contents unread; proxy/LLM not certified)"))
        else:
            executor_errors = runtime.executor.check(runtime.base)
            if executor_errors:
                for message in executor_errors:
                    checks.append(check(
                        f"executor_check:{key[:20]}", "fail", "buzz_runtime", message))
            else:
                checks.append(check(
                    f"executor_check:{key[:20]}", "pass", "buzz_runtime",
                    "executor home/binary checks passed"))

        if not runtime.cwd.is_dir():
            checks.append(check(
                f"workspace:{key[:20]}", "fail", "buzz_runtime",
                "identity workspace missing"))
        else:
            checks.append(check(
                f"workspace:{key[:20]}", "pass", "buzz_runtime",
                "identity workspace directory present"))

        if not runtime.policy["production_write"]:
            if SEATBELT_EXEC.is_file():
                checks.append(check(
                    f"seatbelt_policy:{key[:20]}", "pass", "buzz_runtime",
                    "restricted identity wraps with sandbox-exec unless already confined (inherit); "
                    "GROK_SANDBOX=off under that fence"))
            else:
                checks.append(check(
                    f"seatbelt_policy:{key[:20]}", "fail", "buzz_runtime",
                    "Seatbelt unavailable"))
        try:
            runtime.profile()
            checks.append(check(
                f"policy_profile:{key[:20]}", "pass", "buzz_runtime",
                "identity sandbox/policy profile builds"))
        except (ValueError, OSError, TypeError) as exc:
            checks.append(check(
                f"policy_profile:{key[:20]}", "fail", "buzz_runtime",
                f"identity policy profile failed ({type(exc).__name__})"))

    extras["adapters"] = counts
    extras["identities"] = len(config.data["agents"])

    # --- Component: external_deps (declared only; live request unverified) ---
    checks.append(check(
        "external_deps_declared", "unverified", "external_deps",
        "Declared external dependency versions/connectivity are not live-probed by static doctor; "
        "diagnose may add proxy TCP only — model/bridge requests remain unverified"))

    # --- Component: proxy ---
    contrast, proxy_checks = contrast_proxies(
        config, process_env=process_env, probe=(depth == "diagnose"))
    checks.extend(proxy_checks)
    extras["proxy_contrast"] = contrast

    # Always include S4 boundary marker.
    checks.append(_git_boundary_check())

    # Surfaces never certified by static/install checks.
    for surface in UNVERIFIED_SURFACES:
        checks.append(check(
            f"surface:{surface}", "unverified", "external_deps",
            f"{surface} not certified by this check depth"))

    return checks, extras


def summarize(checks: list[dict[str, str]]) -> dict[str, Any]:
    by_status = {status: [c for c in checks if c["status"] == status] for status in STATUSES}
    fails = by_status["fail"]
    unverified = by_status["unverified"]
    return {
        "ok": not fails,
        "fail_count": len(fails),
        "unverified_count": len(unverified),
        "coverage": {
            "pass": [c["id"] for c in by_status["pass"]],
            "fail": [c["id"] for c in by_status["fail"]],
            "unverified": [c["id"] for c in by_status["unverified"]],
            "na": [c["id"] for c in by_status["na"]],
        },
        "errors": sorted({c["summary"] for c in fails}),
    }

def run(config: Config, *, depth: str = "doctor",
        process_env: dict[str, str] | None = None) -> dict[str, Any]:
    """Run health checks. ok is true only when no fail; unverified does not imply healthy."""
    checks, extras = collect_checks(config, depth=depth, process_env=process_env)
    summary = summarize(checks)
    warnings = [
        "ok means no fail only; unverified surfaces do not imply whole-environment health",
        "identity isolation only; task-level enforcement pending",
        "skills/memory readiness and upstream cache behavior are not certified by this check",
        "pinned binaries are a migration baseline, not proof of client verification",
        "CLI channel/message read success is not Desktop Activity/UI pass",
        "static doctor/diagnose is not role dialogue verification",
        "Grok auth.json/config.toml presence is file-level only; distinct from proxy reachability",
    ]
    if depth == "doctor":
        warnings.append(
            "doctor depth is static/install/proxy-contrast without TCP probe; "
            "use diagnose for deeper proxy TCP and explicit unverified_surfaces list")
    result: dict[str, Any] = {
        "ok": summary["ok"],
        "version": __version__,
        "depth": depth,
        "identities": extras.get("identities", 0),
        "adapters": extras.get("adapters", {}),
        "checks": checks,
        "coverage": summary["coverage"],
        "errors": summary["errors"],
        "warnings": warnings,
        "authentication": "existing home checked; contents never copied or output",
        "proxy_contrast": extras.get("proxy_contrast"),
    }
    if depth == "diagnose":
        result["unverified_surfaces"] = list(UNVERIFIED_SURFACES)
        result["depth_note"] = (
            "diagnose shares the doctor kernel but adds proxy TCP probes when endpoints "
            "are declared, and lists unverified_surfaces explicitly")
    return result
