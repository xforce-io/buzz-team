"""Read-only local diagnostics; Desktop remains the identity authority."""
from __future__ import annotations

import json
from pathlib import Path
import re

from .thin import _load_policy


def _check(name: str, status: str, detail: str) -> dict[str, str]:
    return {"name": name, "status": status, "detail": detail}


def inspect_inventory(path: Path | None) -> list[dict[str, str]]:
    if path is None:
        return [_check("desktop_inventory", "unverified", "inventory path not supplied")]
    try:
        rows = json.loads(path.read_text())
    except (OSError, ValueError):
        return [_check("desktop_inventory", "unverified", "inventory unreadable")]
    if not isinstance(rows, list):
        return [_check("desktop_inventory", "unverified", "inventory structure unknown")]
    checks: list[dict[str, str]] = []
    identities: dict[tuple[str, str], list[int]] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            checks.append(_check(f"row_{index}", "unverified", "inventory row structure unknown"))
            continue
        if not {"acp_command", "agent_command"}.intersection(row):
            checks.append(_check(f"row_{index}", "unverified", "inventory row structure unknown"))
            continue
        # Desktop definitions can name an ACP transport before a concrete
        # executor or identity exists; they are not competing consumers.
        launches = bool(row.get("agent_command"))
        if not launches:
            continue
        pubkey = row.get("pubkey")
        relay = row.get("relay_url")
        if not isinstance(pubkey, str) or not re.fullmatch(r"[0-9a-f]{64}", pubkey):
            checks.append(_check(f"row_{index}", "fail", "launch row has empty or invalid pubkey"))
            continue
        if not isinstance(relay, str) or not relay:
            checks.append(_check(f"row_{index}", "unverified", "relay identity unavailable"))
            continue
        identities.setdefault((relay.rstrip("/"), pubkey), []).append(index)
    for indices in identities.values():
        if len(indices) > 1:
            checks.append(_check("duplicate_identity", "fail", f"identity has {len(indices)} launch rows"))
    if not checks:
        checks.append(_check("desktop_inventory", "pass", f"{len(identities)} launch identities checked"))
    return checks


def inspect_policies(directory: Path | None) -> list[dict[str, str]]:
    if directory is None:
        return [_check("seatbelt_policies", "unverified", "policy directory not supplied")]
    try:
        paths = sorted(directory.glob("*.json"))
    except OSError:
        return [_check("seatbelt_policies", "unverified", "policy directory unreadable")]
    if not paths:
        return [_check("seatbelt_policies", "unverified", "no policy files found")]
    checks: list[dict[str, str]] = []
    for path in paths:
        try:
            policy = json.loads(path.read_text())
            if not isinstance(policy, dict) or not isinstance(policy.get("grok_home"), str):
                raise ValueError("invalid policy")
            _load_policy({"BUZZ_TEAM_POLICY_PATH": str(path), "GROK_HOME": policy["grok_home"]})
        except (OSError, ValueError, TypeError):
            checks.append(_check(path.name, "fail", "invalid Seatbelt policy"))
        else:
            checks.append(_check(path.name, "pass", "Seatbelt policy valid"))
    return checks


def run(inventory: Path | None, policies: Path | None) -> dict:
    checks = inspect_inventory(inventory) + inspect_policies(policies)
    return {"ok": not any(check["status"] == "fail" for check in checks),
            "checks": checks}
