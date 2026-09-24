"""Channel mention-gate, session cursor, mention ack, and fuse reply. No credentials or prompts."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Iterator
import uuid

from .config import Config


_IDENTITY = re.compile(r"[0-9a-f]{16}/[0-9a-f]{64}\Z")
_EVENT_HEX = re.compile(r"[0-9a-f]{64}\Z")
_HUMAN = frozenset({"freeman", "human"})
_FUSE_REASONS = frozenset({"turns", "usd", "input_tokens", "budget_exceeded"})
_WAKE_STATES = frozenset({"active", "fused", "retired"})
_SHORT_READ_TOOLS = frozenset({"read_post", "read_thread_meta"})
_START_BOUNDARY = frozenset("([{<,;:!?\"'`")
_END_BOUNDARY = frozenset(")]}>.,;:!?\"'`")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}\Z")
_MENTION_ACK_EMOJI = "👀"
_ackedEventKeys: set[tuple[str, str]] = set()


def sessionRef(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:12]


def isExecutionOriented(toolName: str) -> bool:
    if not isinstance(toolName, str) or not toolName or "\0" in toolName:
        raise ValueError("invalid tool name")
    return toolName not in _SHORT_READ_TOOLS


class ChannelWakeSilent(Exception):
    """Allowed to return without launching; exec-oriented tool count stays 0."""

    def __init__(self, payload: dict):
        self.payload = payload
        super().__init__(payload.get("reason", "channel wake denied"))


def validateMentionAlias(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 64 or "\0" in value:
        raise ValueError("invalid mention alias")
    if value.startswith("@") or any(char.isspace() for char in value):
        raise ValueError("invalid mention alias")
    if value.lower() in _HUMAN:
        raise ValueError("human mention alias is forbidden")
    return value


def _channelId(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 128 or "\0" in value:
        raise ValueError("invalid channel")
    if any(char.isspace() for char in value):
        raise ValueError("invalid channel")
    return value


def _postRef(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 200 or "\0" in value:
        raise ValueError("invalid post ref")
    return value


def isEventId(value: object) -> bool:
    return isinstance(value, str) and bool(_EVENT_HEX.fullmatch(value))


def eventId(value: object) -> str:
    if not isEventId(value):
        raise ValueError("invalid event id")
    return value


def resetMentionAckMemory() -> None:
    _ackedEventKeys.clear()


def _identity(value: object) -> str:
    if not isinstance(value, str) or not _IDENTITY.fullmatch(value):
        raise ValueError("invalid identity")
    return value


def _scope(value: object) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise ValueError("invalid scope")
    return value


def _community(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 2048 or "\0" in value:
        raise ValueError("invalid community")
    if not value.startswith(("ws://", "wss://")) or any(char.isspace() for char in value):
        raise ValueError("invalid community")
    return value.rstrip("/")


def _rotate(value: object) -> dict:
    if not isinstance(value, dict) or set(value) - {"max_turns", "max_usd", "max_input_tokens"}:
        raise ValueError("invalid channel_wake rotate")
    result = {}
    for name in ("max_turns", "max_input_tokens"):
        if name not in value:
            continue
        amount = value[name]
        if type(amount) is not int or amount <= 0:
            raise ValueError(f"invalid {name}")
        result[name] = amount
    if "max_usd" in value:
        amount = value["max_usd"]
        if type(amount) not in (int, float) or isinstance(amount, bool) or amount <= 0:
            raise ValueError("invalid max_usd")
        result["max_usd"] = amount
    return result


def _wakeBlock(value: object, *, allowOwner: bool, agents: dict) -> dict:
    if not isinstance(value, dict):
        raise ValueError("invalid channel_wake")
    allowed = {"require_mention", "single_owner_identity", "allow_short_ack", "rotate"}
    if set(value) - allowed:
        raise ValueError("invalid channel_wake")
    owner = value.get("single_owner_identity")
    if owner is not None:
        if not allowOwner:
            raise ValueError("single_owner_identity is per-channel only")
        owner = _identity(owner)
        if owner not in agents:
            raise ValueError("single_owner_identity is not a registered identity")
    requireMention = value.get("require_mention", True)
    if type(requireMention) is not bool:
        raise ValueError("require_mention must be an explicit boolean")
    allowAck = value.get("allow_short_ack", False)
    if type(allowAck) is not bool:
        raise ValueError("allow_short_ack must be an explicit boolean")
    rotate = _rotate(value["rotate"]) if "rotate" in value else {}
    return {"require_mention": requireMention, "single_owner_identity": owner,
            "allow_short_ack": allowAck, "rotate": rotate}


def validateChannelWake(data: dict) -> None:
    if "channel_wake" not in data:
        return
    wake = data["channel_wake"]
    if not isinstance(wake, dict) or set(wake) - {"default", "channels"}:
        raise ValueError("invalid channel_wake")
    agents = data.get("agents")
    if not isinstance(agents, dict):
        raise ValueError("invalid channel_wake")
    if "default" in wake:
        _wakeBlock(wake["default"], allowOwner=False, agents=agents)
    channels = wake.get("channels", {})
    if not isinstance(channels, dict):
        raise ValueError("invalid channel_wake")
    for channelId, block in channels.items():
        _channelId(channelId)
        _wakeBlock(block, allowOwner=True, agents=agents)


def validateMentionAliases(data: dict) -> None:
    seen: dict[str, str] = {}
    for key, agent in data.get("agents", {}).items():
        aliases = agent.get("mention_aliases", [])
        if "mention_aliases" not in agent:
            continue
        if not isinstance(aliases, list):
            raise ValueError("mention_aliases must be a list")
        for alias in aliases:
            alias = validateMentionAlias(alias)
            if alias in seen and seen[alias] != key:
                raise ValueError("mention alias conflict")
            seen[alias] = key


def channelWakeConfigured(config: Config) -> bool:
    if isinstance(config.data.get("channel_wake"), dict):
        return True
    return any(agent.get("mention_aliases") for agent in config.data["agents"].values())


def aliasIndex(config: Config) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for key, agent in config.data["agents"].items():
        for alias in agent.get("mention_aliases") or []:
            alias = validateMentionAlias(alias)
            if alias in mapping and mapping[alias] != key:
                raise ValueError("mention alias conflict")
            mapping[alias] = key
    return mapping


def extractAliasTokens(body: str) -> list[str]:
    if not isinstance(body, str) or "\0" in body:
        raise ValueError("invalid post body")
    tokens: list[str] = []
    index = 0
    while index < len(body):
        if body[index] == "@" and _startsMention(body, index):
            end = index + 1
            while end < len(body) and not _endsMention(body[end]):
                end += 1
            if end > index + 1:
                tokens.append(body[index + 1:end])
            index = end
        else:
            index += 1
    return tokens


def _startsMention(body: str, index: int) -> bool:
    if index == 0:
        return True
    previous = body[index - 1]
    return previous.isspace() or previous in _START_BOUNDARY


def _endsMention(char: str) -> bool:
    return char.isspace() or char in _END_BOUNDARY


def channelPolicy(config: Config, channel: str) -> dict:
    wake = config.data.get("channel_wake") or {}
    merged = _wakeBlock(wake.get("default") or {"require_mention": True},
                        allowOwner=False, agents=config.data["agents"])
    override = (wake.get("channels") or {}).get(channel)
    if override is None:
        return merged
    block = _wakeBlock(override, allowOwner=True, agents=config.data["agents"])
    result = dict(merged)
    if "require_mention" in override:
        result["require_mention"] = block["require_mention"]
    if "allow_short_ack" in override:
        result["allow_short_ack"] = block["allow_short_ack"]
    if "single_owner_identity" in override:
        result["single_owner_identity"] = block["single_owner_identity"]
    if "rotate" in override:
        result["rotate"] = block["rotate"]
    return result


def _aliasHits(config: Config, body: str) -> list[tuple[str, str]]:
    aliases = aliasIndex(config)
    hits: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for token in extractAliasTokens(body):
        if token.lower() in _HUMAN:
            continue
        target = aliases.get(token)
        if target is None:
            continue
        item = (token, target)
        if item in seen:
            continue
        seen.add(item)
        hits.append(item)
    return hits


def resolveMentions(config: Config, *, body: str, channel: str | None = None,
                    mentions: object = None) -> dict:
    if channel is not None:
        _channelId(channel)
    if mentions not in (None, [], {}):
        raise ValueError("structured mentions unsupported")
    if not isinstance(body, str) or "\0" in body:
        raise ValueError("invalid post body")
    resolved = []
    for token, identityKey in _aliasHits(config, body):
        resolved.append({
            "token": token,
            "identity": identityKey,
            "pubkey": config.agent(identityKey)["pubkey"],
        })
    return {"resolved": resolved}


def decideWake(config: Config, *, identity: str, channel: str, postRef: str,
               body: str, surface: str = "stream", mentions: object = None) -> dict:
    identity = _identity(identity)
    channel = _channelId(channel)
    _postRef(postRef)
    config.agent(identity)
    if surface == "dm":
        return {"allowed": True, "reason": "dm"}
    if surface != "stream":
        raise ValueError("unknown wake surface")
    if mentions not in (None, [], {}):
        raise ValueError("structured mentions unsupported")
    if not isinstance(body, str) or "\0" in body:
        raise ValueError("invalid post body")
    policy = channelPolicy(config, channel)
    hits = _aliasHits(config, body)
    tokens = [token for token, target in hits if target == identity]
    if tokens:
        return {"allowed": True, "reason": "mentioned", "identity": identity,
                "pubkey": config.agent(identity)["pubkey"], "tokens": tokens}
    owner = policy.get("single_owner_identity")
    if not hits and owner == identity:
        return {"allowed": True, "reason": "single_owner"}
    return {"allowed": False, "reason": "not_mentioned"}


def formatFuseReply(reason: str, oldSessionId: str, newSessionId: str) -> str:
    if reason not in _FUSE_REASONS:
        raise ValueError("invalid fuse reason")
    if oldSessionId == newSessionId:
        raise ValueError("fuse requires a new session")
    return (f"【熔断】\n原因: {reason}\n"
            f"旧 session: {sessionRef(oldSessionId)}\n"
            f"新 session: {sessionRef(newSessionId)}\n")


def sendFuseReply(config: Config, channel: str, postRef: str, text: str) -> None:
    from .buzz_cli import rewrite
    from .instance import digest
    real = config.data["binaries"]["buzz"]
    expected = config.data["compatibility"]["sha256"].get("buzz")
    if digest(Path(real)) != expected:
        raise ValueError("buzz executable differs from pinned baseline")
    args = ["messages", "send", "--channel", channel, "--reply-to", postRef, "--content", text]
    forwarded = rewrite(real, args)
    if digest(Path(real)) != expected:
        raise ValueError("buzz executable differs from pinned baseline")
    subprocess.run([real, *forwarded], check=True, timeout=20, capture_output=True, text=True)


def sendMentionAck(config: Config, postRef: str, *, emoji: str = _MENTION_ACK_EMOJI) -> dict:
    eventRef = eventId(postRef)
    if emoji != _MENTION_ACK_EMOJI:
        raise ValueError("unsupported mention ack emoji")
    from .buzz_cli import rewrite
    from .instance import digest
    real = config.data["binaries"]["buzz"]
    expected = config.data["compatibility"]["sha256"].get("buzz")
    if digest(Path(real)) != expected:
        raise ValueError("buzz executable differs from pinned baseline")
    args = ["reactions", "add", "--event", eventRef, "--emoji", emoji]
    forwarded = rewrite(real, args)
    if digest(Path(real)) != expected:
        raise ValueError("buzz executable differs from pinned baseline")
    subprocess.run([real, *forwarded], check=True, timeout=20, capture_output=True, text=True)
    return {"reacted": True, "emoji": emoji, "event_ref": sessionRef(eventRef)}


def mentionAck(config: Config, *, identity: str, postRef: str, body: str | None = None,
               channel: str | None = None) -> dict:
    identity = _identity(identity)
    config.agent(identity)
    eventRef = eventId(postRef)
    if body is not None:
        if channel is None:
            raise ValueError("channel is required when body is present")
        hits = resolveMentions(config, body=body, channel=channel)
        if not any(item["identity"] == identity for item in hits["resolved"]):
            raise ValueError("mention not resolved; refusing mention ack")
    return sendMentionAck(config, eventRef)


class ChannelCursorStore:
    """Atomic channel session cursors. Metadata only; no transcripts."""

    def __init__(self, instance: Path):
        self.root = Path(instance).resolve() / "private"
        self.path = self.root / "channel-cursors.json"
        self.lockPath = self.root / "channel-cursors.lock"

    @contextmanager
    def _lock(self) -> Iterator[None]:
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(self.lockPath, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            os.chmod(self.lockPath, 0o600)
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _read(self) -> dict:
        if not self.path.exists():
            return {"version": 1, "cursors": {}}
        try:
            data = json.loads(self.path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("invalid channel cursor file") from exc
        if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("cursors"), dict):
            raise ValueError("invalid channel cursor file")
        for key, record in data["cursors"].items():
            if not isinstance(key, str) or key != _cursorKey(_validateCursor(record)):
                raise ValueError("invalid channel cursor file")
        return data

    def _write(self, data: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, name = tempfile.mkstemp(prefix=".channel-cursors.", dir=self.root)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(data, stream, ensure_ascii=False, sort_keys=True, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
            os.chmod(self.path, 0o600)
            directoryFd = os.open(self.root, os.O_RDONLY)
            try:
                os.fsync(directoryFd)
            finally:
                os.close(directoryFd)
        except Exception:
            try:
                os.unlink(name)
            except FileNotFoundError:
                pass
            raise

    def bind(self, *, community: object, identity: object, scope: object,
             sessionId: object) -> dict:
        record = _validateCursor({
            "community": community, "identity": identity, "scope": scope,
            "session_id": sessionId, "generation": 1, "state": "active",
            "previous_session_id": None, "retired_session_ids": [],
            "fuse_reason": None, "updated_at": _now(),
        })
        key = _cursorKey(record)
        with self._lock():
            data = self._read()
            existing = data["cursors"].get(key)
            if existing is not None:
                existing = _validateCursor(existing)
                if existing["session_id"] != record["session_id"] or existing["state"] != "active":
                    raise ValueError("channel cursor conflict")
                return existing
            data["cursors"][key] = record
            self._write(data)
            return record

    def resolve(self, *, community: object, identity: object, scope: object) -> dict:
        expected = {"community": _community(community), "identity": _identity(identity),
                    "scope": _scope(scope)}
        key = hashlib.sha256(json.dumps(expected, ensure_ascii=False, sort_keys=True,
                                        separators=(",", ":")).encode()).hexdigest()
        with self._lock():
            record = self._read()["cursors"].get(key)
            if record is None:
                raise ValueError("channel cursor not found")
            return _validateCursor(record)

    def list(self) -> list[dict]:
        with self._lock():
            return sorted((_validateCursor(item) for item in self._read()["cursors"].values()),
                          key=lambda item: (item["identity"], item["scope"]))

    def isRetired(self, identity: str, sessionId: str) -> bool:
        identity = _identity(identity)
        for record in self.list():
            if record["identity"] != identity:
                continue
            if sessionId in record["retired_session_ids"] or record.get("previous_session_id") == sessionId:
                return True
        return False

    def fuse(self, *, community: object, identity: object, scope: object,
             reason: str, sessionId: object, newSessionId: str | None = None) -> dict:
        if reason not in _FUSE_REASONS:
            raise ValueError("invalid fuse reason")
        oldId = _sessionId(sessionId)
        newId = _sessionId(newSessionId or str(uuid.uuid4()))
        if newId == oldId:
            raise ValueError("fuse requires a new session")
        expected = {
            "community": _community(community), "identity": _identity(identity),
            "scope": _scope(scope), "session_id": newId, "generation": 1,
            "state": "fused", "previous_session_id": oldId,
            "retired_session_ids": [oldId], "fuse_reason": reason, "updated_at": _now(),
        }
        record = _validateCursor(expected)
        key = _cursorKey(record)
        with self._lock():
            data = self._read()
            existing = data["cursors"].get(key)
            generation = 1
            retired = [oldId]
            if existing is not None:
                existing = _validateCursor(existing)
                if existing["session_id"] != oldId:
                    raise ValueError("channel cursor session mismatch")
                generation = existing["generation"] + 1
                retired = list(dict.fromkeys([*existing["retired_session_ids"], oldId]))
            record = _validateCursor({**expected, "generation": generation,
                                      "retired_session_ids": retired, "updated_at": _now()})
            data["cursors"][key] = record
            self._write(data)
            return record


def applyFuse(config: Config, *, identity: str, channel: str, scope: str, reason: str,
              postRef: str, sessionId: str, community: str | None = None,
              send: bool = True, sender=None) -> dict:
    agent = config.agent(identity)
    community = _community(community or agent["relay_url"])
    store = ChannelCursorStore(config.instance)
    record = store.fuse(community=community, identity=identity, scope=scope,
                        reason=reason, sessionId=sessionId)
    reply = formatFuseReply(reason, record["previous_session_id"], record["session_id"])
    if send:
        (sender or sendFuseReply)(config, channel, postRef, reply)
    return {
        "reason": reason,
        "state": record["state"],
        "session_ref": sessionRef(record["session_id"]),
        "old_session_ref": sessionRef(record["previous_session_id"]),
        "reply": reply,
        "exec_tool_calls": 0,
    }


def publicCursor(record: dict | None) -> dict:
    if record is None:
        return {"state": "absent", "session_ref": None}
    return {"state": record["state"], "session_ref": sessionRef(record["session_id"])}


def enforceChannelWake(runtime, mode: str, taskId: str | None) -> dict[str, str]:
    """Gate Desktop/ACP channel launches. Remaining hook: Desktop must set BUZZ_WAKE_*."""
    config = runtime.config
    identity = runtime.key
    extra: dict[str, str] = {}
    store = ChannelCursorStore(config.instance)
    _refuseRetired(store, identity)

    inherited = os.environ.get("BUZZ_ACP_SESSION_OWNER")
    if taskId or inherited:
        _attachCursorEnv(store, identity, extra)
        return extra

    fuseReason = os.environ.get("BUZZ_WAKE_FUSE")
    surface = os.environ.get("BUZZ_WAKE_SURFACE")
    if surface == "dm":
        return extra
    # Cold-start ACP has no BUZZ_WAKE_*. channel_wake config alone must not gate those launches.
    needsGate = surface == "stream" or bool(fuseReason)
    if not needsGate:
        return extra
    channel = os.environ.get("BUZZ_WAKE_CHANNEL")
    postRef = os.environ.get("BUZZ_WAKE_POST_REF")
    body = os.environ.get("BUZZ_WAKE_BODY")
    if fuseReason:
        sessionId = (os.environ.get("BUZZ_ACP_SESSION_ID") or os.environ.get("GROK_SESSION_ID")
                     or os.environ.get("BUZZ_CHANNEL_SESSION_ID"))
        if not channel or not postRef or not sessionId:
            raise ValueError("channel fuse context missing; refusing launch")
        payload = applyFuse(config, identity=identity, channel=channel,
                            scope=os.environ.get("BUZZ_WAKE_SCOPE") or channel,
                            reason=fuseReason, postRef=postRef, sessionId=sessionId)
        payload["allowed"] = False
        raise ChannelWakeSilent(payload)

    if not surface or not channel or not postRef or body is None:
        raise ValueError("channel wake context missing; refusing launch")
    mentionsRaw = os.environ.get("BUZZ_WAKE_MENTIONS")
    mentions = None
    if mentionsRaw:
        try:
            mentions = json.loads(mentionsRaw)
        except json.JSONDecodeError as exc:
            raise ValueError("structured mentions unsupported") from exc
    decision = decideWake(config, identity=identity, channel=channel, postRef=postRef,
                          body=body, surface=surface, mentions=mentions)
    if not decision["allowed"]:
        raise ChannelWakeSilent({**decision, "exec_tool_calls": 0})
    _autoMentionAck(config, identity, postRef)
    _attachCursorEnv(store, identity, extra, scope=os.environ.get("BUZZ_WAKE_SCOPE") or channel)
    return extra


def _autoMentionAck(config: Config, identity: str, postRef: str) -> None:
    if not isEventId(postRef):
        return
    key = (identity, postRef)
    if key in _ackedEventKeys:
        return
    _ackedEventKeys.add(key)
    try:
        sendMentionAck(config, postRef)
    except Exception as exc:
        error = str(exc) if isinstance(exc, ValueError) else (
            type(exc).__name__ + ": mention ack failed")
        print(json.dumps({"ok": False, "reacted": False, "error": error},
                         ensure_ascii=False), file=sys.stderr)


def _refuseRetired(store: ChannelCursorStore, identity: str) -> None:
    for name in ("BUZZ_ACP_SESSION_ID", "GROK_SESSION_ID", "BUZZ_CHANNEL_SESSION_ID"):
        sessionId = os.environ.get(name)
        if sessionId and store.isRetired(identity, sessionId):
            raise ValueError("refusing fused channel session")


def _attachCursorEnv(store: ChannelCursorStore, identity: str, extra: dict[str, str],
                     scope: str | None = None) -> None:
    for record in store.list():
        if record["identity"] != identity:
            continue
        if scope and record["scope"] != scope:
            continue
        extra["BUZZ_CHANNEL_SESSION_ID"] = record["session_id"]
        return


def _sessionId(value: object) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise ValueError("invalid session")
    return value


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _cursorKey(record: dict) -> str:
    encoded = json.dumps({name: record[name] for name in ("community", "identity", "scope")},
                         ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _validateCursor(record: object) -> dict:
    if not isinstance(record, dict):
        raise ValueError("invalid channel cursor")
    retired = record.get("retired_session_ids") or []
    if not isinstance(retired, list) or any(not isinstance(item, str) or not _IDENTIFIER.fullmatch(item)
                                            for item in retired):
        raise ValueError("invalid channel cursor")
    previous = record.get("previous_session_id")
    if previous is not None:
        previous = _sessionId(previous)
    reason = record.get("fuse_reason")
    if reason is not None and reason not in _FUSE_REASONS:
        raise ValueError("invalid channel cursor")
    generation = record.get("generation", 1)
    if type(generation) is not int or generation < 1:
        raise ValueError("invalid channel cursor")
    result = {
        "community": _community(record.get("community")),
        "identity": _identity(record.get("identity")),
        "scope": _scope(record.get("scope")),
        "session_id": _sessionId(record.get("session_id")),
        "generation": generation,
        "state": record.get("state"),
        "previous_session_id": previous,
        "retired_session_ids": list(retired),
        "fuse_reason": reason,
        "updated_at": record.get("updated_at") or _now(),
    }
    if result["state"] not in _WAKE_STATES:
        raise ValueError("invalid channel cursor")
    if not isinstance(result["updated_at"], str) or not result["updated_at"]:
        raise ValueError("invalid channel cursor")
    return result

