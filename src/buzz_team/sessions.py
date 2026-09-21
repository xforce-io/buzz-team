"""Durable, validated task-to-session mappings.

This module stores routing metadata only. It never stores prompts, transcripts,
credentials, or executor output.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time
import uuid
from typing import Iterator

import fcntl


_TASK = re.compile(r"[a-z0-9][a-z0-9-]{0,79}\Z")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}\Z")
_IDENTITY = re.compile(r"[0-9a-f]{16}/[0-9a-f]{64}\Z")
_STATES = {"bound", "restoring", "restored", "conflict", "failed"}


def _text(name: str, value: object, pattern: re.Pattern[str] = _IDENTIFIER) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ValueError(f"invalid {name}")
    return value


def _community(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 2048 or "\0" in value:
        raise ValueError("invalid community")
    if not value.startswith(("ws://", "wss://")) or any(char.isspace() for char in value):
        raise ValueError("invalid community")
    return value.rstrip("/")


def _workspace(value: object) -> str:
    if not isinstance(value, str) or not value or "\0" in value:
        raise ValueError("invalid workspace")
    path = Path(value)
    if not path.is_absolute():
        raise ValueError("workspace must be absolute")
    return str(path.resolve())


def _task(value: object) -> str:
    return _text("task", value, _TASK)


def _identity(value: object) -> str:
    if not isinstance(value, str) or not _IDENTITY.fullmatch(value):
        raise ValueError("invalid identity")
    return value


def _record_key(record: dict[str, str]) -> str:
    identity = {name: record[name] for name in ("community", "identity", "scope", "task_id")}
    encoded = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _validate_record(record: object) -> dict[str, str]:
    if not isinstance(record, dict):
        raise ValueError("invalid session mapping")
    result = {
        "community": _community(record.get("community")),
        "identity": _identity(record.get("identity")),
        "scope": _text("scope", record.get("scope")),
        "task_id": _task(record.get("task_id")),
        "workspace": _workspace(record.get("workspace")),
        "session_id": _text("session", record.get("session_id")),
        "state": _text("state", record.get("state", "bound")),
    }
    if result["state"] not in _STATES:
        raise ValueError("invalid session state")
    owner = record.get("restore_owner")
    if owner is not None:
        owner = _text("restore owner", owner)
    result["restore_owner"] = owner
    started = record.get("restore_started_at")
    if started is not None and (type(started) not in (int, float) or started < 0):
        raise ValueError("invalid restore start")
    result["restore_started_at"] = started
    return result


class SessionStore:
    """Atomic JSON store for routing metadata under an instance's private area."""

    def __init__(self, instance: Path):
        self.root = Path(instance).resolve() / "private"
        self.path = self.root / "task-sessions.json"
        self.lock_path = self.root / "task-sessions.lock"

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
            return {"version": 1, "bindings": {}}
        try:
            data = json.loads(self.path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("invalid session mapping file") from exc
        if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("bindings"), dict):
            raise ValueError("invalid session mapping file")
        for key, record in data["bindings"].items():
            if not isinstance(key, str) or key != _record_key(_validate_record(record)):
                raise ValueError("invalid session mapping file")
        return data

    def _write(self, data: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, name = tempfile.mkstemp(prefix=".task-sessions.", dir=self.root)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(data, stream, ensure_ascii=False, sort_keys=True, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
            os.chmod(self.path, 0o600)
            directory_fd = os.open(self.root, os.O_RDONLY)
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

    @staticmethod
    def _record(community: object, identity: object, scope: object, task_id: object,
                workspace: object, session_id: object, state: str = "bound",
                restore_owner: str | None = None, restore_started_at: float | None = None) -> dict[str, str]:
        return _validate_record({"community": community, "identity": identity, "scope": scope,
                                 "task_id": task_id, "workspace": workspace,
                                 "session_id": session_id, "state": state,
                                 "restore_owner": restore_owner,
                                 "restore_started_at": restore_started_at})

    def bind(self, *, community: object, identity: object, scope: object, task_id: object,
             workspace: object, session_id: object) -> dict[str, str]:
        record = self._record(community, identity, scope, task_id, workspace, session_id)
        key = _record_key(record)
        with self._lock():
            data = self._read()
            existing = data["bindings"].get(key)
            if existing is not None:
                existing = _validate_record(existing)
                immutable = ("community", "identity", "scope", "task_id", "workspace", "session_id")
                if any(existing[name] != record[name] for name in immutable):
                    raise ValueError("session mapping conflict")
                return existing
            for candidate in data["bindings"].values():
                candidate = _validate_record(candidate)
                if candidate["task_id"] == record["task_id"]:
                    raise ValueError("session mapping conflict")
                if candidate["identity"] == record["identity"] and candidate["session_id"] == record["session_id"]:
                    raise ValueError("session mapping conflict")
            data["bindings"][key] = record
            self._write(data)
            return record

    def resolve(self, *, community: object, identity: object, scope: object, task_id: object,
                workspace: object) -> dict[str, str]:
        expected = self._record(community, identity, scope, task_id, workspace, "session-placeholder")
        key = _record_key(expected)
        with self._lock():
            data = self._read()
            record = data["bindings"].get(key)
            if record is None:
                for candidate in data["bindings"].values():
                    candidate = _validate_record(candidate)
                    if candidate["identity"] == expected["identity"] and candidate["task_id"] == expected["task_id"]:
                        raise ValueError("session mapping ownership mismatch")
                raise ValueError("session mapping not found")
            record = _validate_record(record)
            if any(record[name] != expected[name] for name in ("community", "identity", "scope", "task_id", "workspace")):
                raise ValueError("session mapping ownership mismatch")
            return record

    def list(self) -> list[dict[str, str]]:
        with self._lock():
            return sorted((_validate_record(item) for item in self._read()["bindings"].values()),
                          key=lambda item: (item["identity"], item["scope"], item["task_id"]))

    def claim(self, *, community: object, identity: object, scope: object, task_id: object,
              workspace: object, owner: str | None = None) -> dict[str, str]:
        expected = self._record(community, identity, scope, task_id, workspace, "session-placeholder")
        owner = owner or uuid.uuid4().hex
        _text("restore owner", owner)
        key = _record_key(expected)
        with self._lock():
            data = self._read()
            record = data["bindings"].get(key)
            if record is None:
                raise ValueError("session mapping not found")
            record = _validate_record(record)
            if any(record[name] != expected[name] for name in ("community", "identity", "scope", "task_id", "workspace")):
                raise ValueError("session mapping ownership mismatch")
            if record["state"] == "restoring" and record["restore_owner"] != owner:
                current_owner = record["restore_owner"]
                alive = False
                if isinstance(current_owner, str) and current_owner.split("-", 1)[0].isdigit():
                    try:
                        os.kill(int(current_owner.split("-", 1)[0]), 0)
                    except ProcessLookupError:
                        alive = False
                    except PermissionError:
                        alive = True
                    except OSError:
                        alive = False
                else:
                    # Unknown owner formats are not safely reclaimable.
                    alive = True
                if alive:
                    raise ValueError("session mapping already restoring")
            record["state"], record["restore_owner"], record["restore_started_at"] = "restoring", owner, time.time()
            data["bindings"][key] = record
            self._write(data)
            return record

    def release(self, *, community: object, identity: object, scope: object, task_id: object,
                workspace: object, owner: str) -> dict[str, str]:
        expected = self._record(community, identity, scope, task_id, workspace, "session-placeholder")
        owner = _text("restore owner", owner)
        key = _record_key(expected)
        with self._lock():
            data = self._read()
            record = data["bindings"].get(key)
            if record is None:
                raise ValueError("session mapping not found")
            record = _validate_record(record)
            if any(record[name] != expected[name] for name in ("community", "identity", "scope", "task_id", "workspace")):
                raise ValueError("session mapping ownership mismatch")
            if record["state"] != "restoring" or record["restore_owner"] != owner:
                raise ValueError("session mapping restore ownership mismatch")
            record["state"], record["restore_owner"], record["restore_started_at"] = "restored", None, None
            data["bindings"][key] = record
            self._write(data)
            return record

    def resolve_task(self, *, task_id: object, identity: object, community: object) -> dict[str, str]:
        task_id = _task(task_id)
        identity = _identity(identity)
        community = _community(community)
        with self._lock():
            matches = [_validate_record(item) for item in self._read()["bindings"].values()
                       if _validate_record(item)["task_id"] == task_id]
            if not matches:
                raise ValueError("session mapping not found")
            record = matches[0]
            if record["identity"] != identity or record["community"] != community:
                raise ValueError("session mapping ownership mismatch")
            return record
