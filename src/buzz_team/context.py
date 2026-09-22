"""Per-task context cost ledger and safe handoff artifacts."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Iterator


_TASK = re.compile(r"[a-z0-9][a-z0-9-]{0,79}\Z")
_TURN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}\Z")
_QUALITY = {"actual", "estimated", "unavailable"}
_METRICS = ("input_tokens", "output_tokens", "cached_input_tokens", "uncached_input_tokens",
            "context_tokens", "duration_ms")
FUSE_REASONS = frozenset({"turns", "usd", "input_tokens", "budget_exceeded"})


def _task(value: object) -> str:
    if not isinstance(value, str) or not _TASK.fullmatch(value):
        raise ValueError("invalid task")
    return value


def _turn(value: object) -> str:
    if not isinstance(value, str) or not _TURN.fullmatch(value):
        raise ValueError("invalid turn")
    return value


def _text(name: str, value: object, *, required: bool = True, limit: int = 4096) -> str:
    if not isinstance(value, str) or (required and not value.strip()) or len(value) > limit or "\0" in value:
        raise ValueError(f"invalid {name}")
    return value


def measurement(value: object, quality: str = "actual") -> dict[str, object]:
    if value == "unavailable" or quality == "unavailable":
        if value not in (None, "unavailable"):
            raise ValueError("unavailable metric cannot have a value")
        return {"value": None, "quality": "unavailable"}
    if type(value) is not int or value < 0 or quality not in {"actual", "estimated"}:
        raise ValueError("invalid metric")
    return {"value": value, "quality": quality}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _empty(task_id: str, max_input_tokens: int | None, max_context_tokens: int | None) -> dict:
    return {
        "version": 1,
        "task_id": task_id,
        "status": "collecting",
        "created_at": _now(),
        "updated_at": _now(),
        "budget": {"max_input_tokens": max_input_tokens, "max_context_tokens": max_context_tokens},
        "totals": {name: {"actual": 0, "estimated": 0, "unavailable": 0} for name in _METRICS},
        "peak_context": measurement("unavailable", "unavailable"),
        "turns": [],
        "events": [],
        "handoff": None,
        "handoff_status": "unavailable",
    }


def _validate_budget(value: object, name: str) -> int | None:
    if value is None:
        return None
    if type(value) is not int or value <= 0:
        raise ValueError(f"invalid {name}")
    return value


def _validate_ledger(data: object, task_id: str) -> dict:
    if not isinstance(data, dict) or data.get("version") != 1 or data.get("task_id") != task_id:
        raise ValueError("invalid context ledger")
    if data.get("status") not in {"collecting", "budget_warning", "budget_exceeded"}:
        raise ValueError("invalid context ledger")
    if data.get("handoff_status") not in {"unavailable", "ready", "consumed"}:
        raise ValueError("invalid context ledger")
    if not isinstance(data.get("turns"), list) or not isinstance(data.get("events"), list):
        raise ValueError("invalid context ledger")
    if not isinstance(data.get("totals"), dict) or not isinstance(data.get("budget"), dict):
        raise ValueError("invalid context ledger")
    for name in _METRICS:
        totals = data["totals"].get(name)
        if (not isinstance(totals, dict) or set(totals) != _QUALITY
                or any(type(value) is not int or value < 0 for value in totals.values())):
            raise ValueError("invalid context ledger")
    for name in ("max_input_tokens", "max_context_tokens"):
        value = data["budget"].get(name)
        if value is not None and (type(value) is not int or value <= 0):
            raise ValueError("invalid context ledger")
    peak = data.get("peak_context")
    if (not isinstance(peak, dict) or set(peak) != {"value", "quality"}
            or (peak["value"] is not None and (type(peak["value"]) is not int or peak["value"] < 0))
            or peak["quality"] not in _QUALITY
            or (peak["quality"] == "unavailable" and peak["value"] is not None)
            or (peak["quality"] != "unavailable" and (type(peak["value"]) is not int or peak["value"] < 0))):
        raise ValueError("invalid context ledger")
    seen_turns = set()
    for turn in data["turns"]:
        if not isinstance(turn, dict) or not isinstance(turn.get("turn_id"), str) or turn["turn_id"] in seen_turns:
            raise ValueError("invalid context ledger")
        seen_turns.add(turn["turn_id"])
        for name in ("provider", "model", "result_status", "recorded_at"):
            if not isinstance(turn.get(name), str):
                raise ValueError("invalid context ledger")
        for name in _METRICS:
            value = turn.get(name)
            if (not isinstance(value, dict) or set(value) != {"value", "quality"}
                    or value["quality"] not in _QUALITY
                    or (value["quality"] == "unavailable" and value["value"] is not None)
                    or (value["quality"] != "unavailable" and (type(value["value"]) is not int or value["value"] < 0))):
                raise ValueError("invalid context ledger")
        for name in ("tool_rounds", "retries"):
            if type(turn.get(name)) is not int or turn[name] < 0:
                raise ValueError("invalid context ledger")
    handoff = data.get("handoff")
    if data["handoff_status"] == "unavailable":
        if handoff is not None:
            raise ValueError("invalid context ledger")
    elif data["handoff_status"] in {"ready", "consumed"}:
        if handoff is None:
            raise ValueError("invalid context ledger")
    else:
        raise ValueError("invalid context ledger")
    if handoff is not None:
        required = ("version", "task_id", "created_at", "goal", "constraints", "verified_facts",
                    "workspace_ref", "tool_results", "pending", "approval_state", "next_step")
        if (not isinstance(handoff, dict) or any(key not in handoff for key in required)
                or handoff.get("version") != 1 or handoff.get("task_id") != task_id
                or any(not isinstance(handoff[key], str) for key in ("created_at", "goal", "workspace_ref", "approval_state", "next_step"))
                or any(not isinstance(handoff[key], list) or any(not isinstance(item, str) for item in handoff[key])
                       for key in ("constraints", "verified_facts", "tool_results", "pending"))):
            raise ValueError("invalid context ledger")
    expected = {name: {"actual": 0, "estimated": 0, "unavailable": 0} for name in _METRICS}
    expected_peak = None
    expected_peak_quality = None
    for turn in data["turns"]:
        for name in _METRICS:
            metric = turn[name]
            if metric["value"] is None:
                expected[name]["unavailable"] += 1
            else:
                expected[name][metric["quality"]] += metric["value"]
        metric = turn["context_tokens"]
        if metric["value"] is not None and (expected_peak is None or metric["value"] > expected_peak):
            expected_peak = metric["value"]
            expected_peak_quality = metric["quality"]
    if data["totals"] != expected:
        raise ValueError("invalid context ledger")
    expected_peak_metric = measurement("unavailable", "unavailable") if expected_peak is None else \
        {"value": expected_peak, "quality": expected_peak_quality}
    if data["peak_context"] != expected_peak_metric:
        raise ValueError("invalid context ledger")
    input_total = sum(data["totals"]["input_tokens"][q] for q in ("actual", "estimated"))
    max_input = data["budget"].get("max_input_tokens")
    max_context = data["budget"].get("max_context_tokens")
    exceeded = ((max_input is not None and input_total > max_input)
                or (max_context is not None and expected_peak is not None and expected_peak > max_context))
    warning = ((max_input is not None and input_total >= max_input * 0.9)
               or (max_context is not None and expected_peak is not None and expected_peak >= max_context * 0.9))
    expected_status = "budget_exceeded" if exceeded else "budget_warning" if warning else "collecting"
    if data["status"] != expected_status:
        raise ValueError("invalid context ledger")
    return data


class ContextLedger:
    def __init__(self, instance: Path, task_id: str):
        self.instance = Path(instance).resolve()
        self.task_id = _task(task_id)
        self.root = self.instance / "private" / "context"
        self.path = self.root / f"{self.task_id}.json"
        self.lock_path = self.root / f"{self.task_id}.lock"

    @contextmanager
    def _lock(self) -> Iterator[None]:
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(self.lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            os.chmod(self.lock_path, 0o600)
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _read(self) -> dict:
        if not self.path.exists():
            raise ValueError("context ledger not found")
        try:
            data = json.loads(self.path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("invalid context ledger") from exc
        return _validate_ledger(data, self.task_id)

    def _write(self, data: dict, path: Path | None = None) -> None:
        target = path or self.path
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(data, stream, ensure_ascii=False, sort_keys=True, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, target)
            os.chmod(target, 0o600)
            directory_fd = os.open(target.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except Exception:
            try:
                os.unlink(name)
            except FileNotFoundError:
                pass
            raise

    def start(self, *, max_input_tokens: int | None = None,
              max_context_tokens: int | None = None) -> dict:
        max_input_tokens = _validate_budget(max_input_tokens, "max input tokens")
        max_context_tokens = _validate_budget(max_context_tokens, "max context tokens")
        with self._lock():
            if self.path.exists():
                data = self._read()
                if (max_input_tokens is not None and data["budget"].get("max_input_tokens") != max_input_tokens
                        or max_context_tokens is not None and data["budget"].get("max_context_tokens") != max_context_tokens):
                    raise ValueError("context budget conflict")
                return data
            data = _empty(self.task_id, max_input_tokens, max_context_tokens)
            self._write(data)
            return data

    def record(self, *, turn_id: str, provider: str, model: str,
               values: dict[str, object], qualities: dict[str, str] | None = None,
               tool_rounds: int = 0, retries: int = 0, result_status: str = "success") -> dict:
        turn_id = _turn(turn_id)
        provider = _text("provider", provider, limit=256)
        model = _text("model", model, limit=256)
        if type(tool_rounds) is not int or tool_rounds < 0 or type(retries) is not int or retries < 0:
            raise ValueError("invalid turn counters")
        result_status = _text("result status", result_status, limit=128)
        qualities = qualities or {}
        metrics = {name: measurement(values.get(name, "unavailable"), qualities.get(name, "actual"))
                   for name in _METRICS}
        with self._lock():
            data = self._read()
            if any(turn.get("turn_id") == turn_id for turn in data["turns"]):
                raise ValueError("turn already recorded")
            turn = {"turn_id": turn_id, "provider": provider, "model": model,
                    **metrics, "tool_rounds": tool_rounds, "retries": retries,
                    "result_status": result_status, "recorded_at": _now()}
            data["turns"].append(turn)
            for name, value in metrics.items():
                quality = value["quality"]
                if value["value"] is None:
                    data["totals"][name]["unavailable"] += 1
                else:
                    data["totals"][name][quality] += value["value"]
            context = metrics["context_tokens"]
            peak = data["peak_context"]
            if context["value"] is not None and (peak["value"] is None or context["value"] > peak["value"]):
                data["peak_context"] = context
            max_input = data["budget"].get("max_input_tokens")
            max_context = data["budget"].get("max_context_tokens")
            input_total = sum(data["totals"]["input_tokens"][q] for q in ("actual", "estimated"))
            context_value = data["peak_context"]["value"]
            exceeded = ((max_input is not None and input_total > max_input)
                        or (max_context is not None and context_value is not None and context_value > max_context))
            warning = ((max_input is not None and input_total >= max_input * 0.9)
                       or (max_context is not None and context_value is not None and context_value >= max_context * 0.9))
            data["status"] = "budget_exceeded" if exceeded else "budget_warning" if warning else "collecting"
            data["updated_at"] = _now()
            self._write(data)
            return turn

    def handoff(self, *, goal: str, next_step: str, workspace_ref: str, approval_state: str,
                constraints: list[str] | None = None, facts: list[str] | None = None,
                pending: list[str] | None = None, tool_results: list[str] | None = None,
                open_tool_calls: int = 0) -> dict:
        if type(open_tool_calls) is not int or open_tool_calls < 0:
            raise ValueError("invalid open tool calls")
        if open_tool_calls:
            raise ValueError("handoff requires no open tool calls")
        payload = {
            "version": 1, "task_id": self.task_id, "created_at": _now(),
            "goal": _text("goal", goal), "constraints": [_text("constraint", item) for item in (constraints or [])],
            "verified_facts": [_text("fact", item) for item in (facts or [])],
            "workspace_ref": _text("workspace ref", workspace_ref, limit=1024),
            "tool_results": [_text("tool result", item) for item in (tool_results or [])],
            "pending": [_text("pending item", item) for item in (pending or [])],
            "approval_state": _text("approval state", approval_state, limit=256),
            "next_step": _text("next step", next_step),
        }
        with self._lock():
            data = self._read()
            if not data["turns"]:
                raise ValueError("handoff requires a completed turn")
            data["handoff"] = payload
            data["handoff_status"] = "ready"
            data["events"].append({"type": "handoff_committed", "at": payload["created_at"]})
            data["updated_at"] = _now()
            self._write(data)
            return payload

    def report(self) -> dict:
        with self._lock():
            data = self._read()
            result = {key: data[key] for key in ("version", "task_id", "status", "created_at", "updated_at",
                                                   "budget", "totals", "peak_context", "turns", "events")}
            result["budget_status"] = data["status"]
            if data["handoff_status"] == "ready":
                result["handoff"] = "available"
            elif data["handoff_status"] == "consumed":
                result["handoff"] = "consumed"
            else:
                result["handoff"] = "unavailable"
            return result

    def read_handoff(self) -> dict:
        with self._lock():
            data = self._read()
            if data["handoff_status"] != "ready" or data.get("handoff") is None:
                raise ValueError("context handoff unavailable")
            return data["handoff"]

    def consume_handoff(self) -> dict:
        with self._lock():
            data = self._read()
            if data["handoff_status"] != "ready" or data.get("handoff") is None:
                raise ValueError("context handoff unavailable")
            payload = data["handoff"]
            data["handoff_status"] = "consumed"
            data["events"].append({"type": "handoff_consumed", "at": _now()})
            data["updated_at"] = _now()
            self._write(data)
            return payload

    def record_budget_gate(self, *, reason: str = "budget_exceeded") -> dict:
        with self._lock():
            data = self._read()
            event = {"type": "budget_gate", "reason": _text("gate reason", reason, limit=256), "at": _now()}
            data["events"].append(event)
            data["updated_at"] = _now()
            self._write(data)
            return event


def fuseReason(report: dict, *, rotate: dict | None = None) -> str | None:
    """Map ledger + #15 rotate caps to a fuse reason. unavailable amounts fail-closed."""
    if not isinstance(report, dict):
        raise ValueError("invalid context ledger")
    rotate = rotate or {}
    if not isinstance(rotate, dict):
        raise ValueError("invalid channel_wake rotate")
    totals = report.get("totals") if isinstance(report.get("totals"), dict) else {}
    turns = report.get("turns") if isinstance(report.get("turns"), list) else []
    budget = report.get("budget") if isinstance(report.get("budget"), dict) else {}
    maxTurns = rotate.get("max_turns")
    if type(maxTurns) is int and len(turns) >= maxTurns:
        return "turns"
    if rotate.get("max_usd") is not None and turns:
        usd = totals.get("usd") if isinstance(totals.get("usd"), dict) else {}
        if not usd.get("actual") and not usd.get("estimated"):
            return "usd"
    item = totals.get("input_tokens") if isinstance(totals.get("input_tokens"), dict) else {}
    inputTotal = int(item.get("actual") or 0) + int(item.get("estimated") or 0)
    inputUnavailable = int(item.get("unavailable") or 0)
    rotateMaxInput = rotate.get("max_input_tokens")
    if rotateMaxInput is not None and (inputUnavailable or inputTotal > rotateMaxInput):
        return "input_tokens"
    budgetMaxInput = budget.get("max_input_tokens")
    if budgetMaxInput is not None and inputTotal > budgetMaxInput:
        return "input_tokens"
    if report.get("status") == "budget_exceeded":
        return "budget_exceeded"
    return None


def setWakeFuse(reason: str) -> str:
    if reason not in FUSE_REASONS:
        raise ValueError("invalid fuse reason")
    os.environ["BUZZ_WAKE_FUSE"] = reason
    return reason
