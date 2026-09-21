"""Structured health checks: pass / fail / unverified / na with component axes."""
from __future__ import annotations

import importlib.resources
import json
import os
import re
import shutil
import socket
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from . import __version__
from .config import Config
from . import desktop
from .instance import digest
from .runtime import Runtime

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


def redact_endpoint(value: str | None) -> str | None:
    """Return host:port only; never credentials, paths, or query strings."""
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    if "://" not in text and "@" not in text and re.fullmatch(r"[^/\s:]+(?::\d+)?", text):
        return text
    parsed = urlparse(text if "://" in text else f"http://{text}")
    host = parsed.hostname
    if not host:
        # Opaque or malformed — do not leak raw value.
        return "<redacted>"
    port = parsed.port
    if port is None:
        return host
    return f"{host}:{port}"


def _proxy_map(env: dict[str, str]) -> dict[str, str | None]:
    return {key: redact_endpoint(env[key]) for key in PROXY_ENV_KEYS if key in env and env[key]}


def _parse_host_port(endpoint: str | None) -> tuple[str, int] | None:
    if not endpoint or endpoint == "<redacted>":
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


def _read_desktop_proxy_maps(config: Config) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Load per-identity Desktop env proxy maps; missing inventory → empty + fail check."""
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
        selected = desktop.selected_rows(config, rows)
    except (OSError, ValueError, json.JSONDecodeError, TypeError, KeyError):
        checks.append(check(
            "desktop_inventory", "fail", "buzz_runtime",
            "Desktop managed-agents inventory unreadable or mismatched"))
        return maps, checks
    checks.append(check(
        "desktop_inventory", "pass", "buzz_runtime",
        "Desktop managed-agents inventory readable for bound identities"))
    for key, row in selected.items():
        env = row.get("env_vars") or {}
        if not isinstance(env, dict):
            checks.append(check(
                f"desktop_env_vars:{key[:20]}", "fail", "buzz_runtime",
                "Desktop env_vars is not an object for a bound identity"))
            continue
        maps.append({
            "identity_ref": key[:20],
            "proxy": _proxy_map({str(k): str(v) for k, v in env.items() if isinstance(v, str)}),
            "proxy_keys": sorted(k for k in PROXY_ENV_KEYS if k in env),
        })
    return maps, checks


def _cli_proxy_map(env: dict[str, str] | None = None) -> dict[str, str | None]:
    return _proxy_map(env if env is not None else dict(os.environ))


def contrast_proxies(
    config: Config,
    *,
    process_env: dict[str, str] | None = None,
    probe: bool = False,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Compare Desktop ACP binding proxy keys/endpoints vs CLI process proxy env.

    Values are host:port only. Dead/unreachable endpoints are attributed to proxy,
    never to auth-file absence.
    """
    checks: list[dict[str, str]] = []
    desktop_maps, inventory_checks = _read_desktop_proxy_maps(config)
    checks.extend(inventory_checks)
    cli_map = _cli_proxy_map(process_env)
    cli_keys = sorted(cli_map)
    desktop_key_sets = [tuple(item["proxy_keys"]) for item in desktop_maps]
    mismatches: list[str] = []
    for item in desktop_maps:
        d_keys = set(item["proxy_keys"])
        c_keys = set(cli_keys)
        if d_keys != c_keys and (d_keys or c_keys):
            only_desktop = sorted(d_keys - c_keys)
            only_cli = sorted(c_keys - d_keys)
            parts = []
            if only_desktop:
                parts.append("desktop_only_keys=" + ",".join(only_desktop))
            if only_cli:
                parts.append("cli_only_keys=" + ",".join(only_cli))
            mismatches.append(f"{item['identity_ref']}:{' '.join(parts)}")
        for key, endpoint in item["proxy"].items():
            cli_ep = cli_map.get(key)
            if endpoint and cli_ep and endpoint != cli_ep:
                mismatches.append(
                    f"{item['identity_ref']}:{key} desktop={endpoint} cli={cli_ep}")

    if not desktop_maps:
        # Inventory failed already, or no rows — still report CLI side.
        status = "unverified" if any(c["status"] == "fail" for c in inventory_checks) else "na"
        checks.append(check(
            "proxy_contrast", status, "proxy",
            "Desktop proxy contrast unavailable; CLI process proxy keys recorded only"))
    elif mismatches:
        checks.append(check(
            "proxy_contrast", "fail", "proxy",
            "Desktop ACP proxy settings differ from CLI process proxy "
            f"({len(mismatches)} difference(s)); dead proxy is not auth-file failure"))
    elif not any(item["proxy_keys"] for item in desktop_maps) and not cli_keys:
        checks.append(check(
            "proxy_contrast", "na", "proxy",
            "No proxy environment keys declared on Desktop bindings or CLI process"))
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
        "cli_process": {"keys": cli_keys, "endpoints": cli_map},
        "desktop_bindings": [
            {"identity_ref": m["identity_ref"], "keys": m["proxy_keys"], "endpoints": m["proxy"]}
            for m in desktop_maps
        ],
        "mismatches": mismatches,
        "tcp_probes": probes,
        "note": (
            "Proxy contrast uses key names and host:port only; "
            "credentials and full URLs are never emitted. "
            "Auth-file presence does not prove proxy health."
        ),
    }
    return contrast, checks


def _git_boundary_check() -> dict[str, str]:
    """Document S4 boundary: non-git directories are na, not git tool failure."""
    return check(
        "git_directory_boundary", "na", "buzz_runtime",
        "Git status applies only inside a real repository; non-repo source dirs are "
        "not applicable (na), not 'git unavailable'. Business prompts are out of scope.")


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
    if sys.platform == "darwin":
        if Path("/usr/bin/sandbox-exec").is_file():
            checks.append(check("tool_seatbelt", "pass", "dev_env", "Seatbelt sandbox-exec present"))
        else:
            checks.append(check("tool_seatbelt", "fail", "dev_env", "Seatbelt unavailable"))
    else:
        checks.append(check(
            "tool_seatbelt", "na", "dev_env",
            "Seatbelt applies on macOS only; not applicable on this platform for unrestricted writer identities"))

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
            if Path("/usr/bin/sandbox-exec").is_file():
                checks.append(check(
                    f"seatbelt_policy:{key[:20]}", "pass", "buzz_runtime",
                    "restricted identity has Seatbelt available"))
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
