"""Hold ACP turn close while a long tool is still undecided. No job ledger."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import select
import signal
import subprocess
import sys
import threading
import time


DEFAULT_TIMEOUT_SECONDS = 1200
DEFAULT_POLL_SECONDS = 60
MAX_POLL_SECONDS = 120
_LOOP_SECONDS = 0.25
_BG = re.compile(r"\[bg\]|backgrounded|running in background", re.I)
_PID = re.compile(r"\bpid[=:\s]+(\d+)\b", re.I)
_OPEN = frozenset({"pending", "in_progress", "background"})
_CLOSED = frozenset({"completed", "failed", "cancelled", "timeout", "exited"})
_TOOL_UPDATES = frozenset({"tool_call", "tool_call_update"})


@dataclass(frozen=True)
class LongToolPolicy:
    timeoutSeconds: int
    pollSeconds: float


@dataclass
class LongTool:
    toolCallId: str
    status: str
    startedAt: float
    pid: int | None = None
    marker: str | None = None
    background: bool = False
    lastReason: str | None = None


@dataclass
class LongToolWatch:
    policy: LongToolPolicy
    tools: dict[str, LongTool] = field(default_factory=dict)
    _seq: int = 0

    def apply(self, update: dict, *, agentPid: int | None = None, now: float | None = None) -> LongTool | None:
        if not isinstance(update, dict):
            raise ValueError("invalid tool update")
        now = time.monotonic() if now is None else now
        toolCallId = update.get("toolCallId")
        if not isinstance(toolCallId, str) or not toolCallId or "\0" in toolCallId:
            self._seq += 1
            toolCallId = f"anon-{self._seq}"
        text = collectText(update)
        pids = extractPids(text)
        background = isBackgroundMarker(text)
        status = update.get("status")
        if status is not None and (not isinstance(status, str) or status not in (_OPEN | _CLOSED)):
            raise ValueError("invalid tool status")
        current = self.tools.get(toolCallId)
        if current is None:
            resolved = "background" if background and status in {None, "completed"} else (status or "pending")
            if resolved == "completed" and background:
                resolved = "background"
            tool = LongTool(toolCallId=toolCallId, status=resolved, startedAt=now, background=background)
            self.tools[toolCallId] = tool
        else:
            tool = current
            if background:
                tool.background = True
            if status in _OPEN:
                tool.status = status
            elif status == "completed" and (background or tool.background):
                tool.status = "background"
                tool.background = True
            elif status in _CLOSED:
                tool.status = status
        if pids and tool.pid is None:
            tool.pid = pids[0]
            tool.marker = processMarker(tool.pid)
        elif background and tool.pid is None and agentPid is not None:
            child = newestChild(agentPid)
            if child is not None:
                tool.pid = child
                tool.marker = processMarker(child)
        return tool

    def poll(self, *, now: float | None = None) -> list[dict]:
        now = time.monotonic() if now is None else now
        events = []
        for tool in list(self.tools.values()):
            if tool.status not in _OPEN:
                continue
            elapsed = now - tool.startedAt
            if elapsed >= self.policy.timeoutSeconds:
                tool.status = "timeout"
                tool.lastReason = "timeout"
                events.append(_event(tool, "timeout", elapsed))
                continue
            if tool.pid is None:
                continue
            if processGone(tool.pid, tool.marker):
                tool.status = "exited"
                tool.lastReason = "exited"
                events.append(_event(tool, "exited", elapsed))
        return events


def canCloseTurn(watch: LongToolWatch) -> bool:
    return all(tool.status not in _OPEN for tool in watch.tools.values())


def isBackgroundMarker(text: str) -> bool:
    return bool(text and _BG.search(text))


def extractPids(text: str) -> list[int]:
    if not text:
        return []
    return [int(match.group(1)) for match in _PID.finditer(text)]


def collectText(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(collectText(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(collectText(item) for item in value)
    return ""


def toolUpdateFromMessage(message: object) -> dict | None:
    if not isinstance(message, dict) or message.get("method") != "session/update":
        return None
    params = message.get("params")
    if not isinstance(params, dict):
        return None
    update = params.get("update")
    if not isinstance(update, dict) or update.get("sessionUpdate") not in _TOOL_UPDATES:
        return None
    return update


def sessionIdFromMessage(message: object) -> str | None:
    if not isinstance(message, dict):
        return None
    params = message.get("params")
    if isinstance(params, dict) and isinstance(params.get("sessionId"), str):
        return params["sessionId"]
    return None


def turnCloseKind(message: object) -> str | None:
    if not isinstance(message, dict):
        return None
    result = message.get("result")
    if isinstance(result, dict) and "stopReason" in result and "id" in message:
        return "prompt_result"
    if message.get("method") != "session/update":
        return None
    params = message.get("params")
    if not isinstance(params, dict):
        return None
    update = params.get("update")
    if not isinstance(update, dict):
        return None
    if "stopReason" in update:
        return "state_stop"
    if update.get("sessionUpdate") == "state" and update.get("state") == "idle":
        return "state_idle"
    return None


def isCancelMessage(message: object) -> bool:
    return isinstance(message, dict) and message.get("method") == "session/cancel"


def parseAcpLine(raw: bytes) -> object | None:
    text = raw.strip()
    if not text:
        return None
    try:
        return json.loads(text.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def alertMessage(sessionId: str | None, event: dict) -> dict:
    reason = event["reason"]
    text = (f"【长工具】\n原因: {reason}\n"
            f"tool: {event['tool_ref']}\n"
            f"elapsed_s: {event['elapsed_s']}\n")
    update = {
        "sessionUpdate": "agent_message_chunk",
        "content": {"type": "text", "text": text},
    }
    params: dict[str, object] = {"update": update}
    if sessionId:
        params["sessionId"] = sessionId
    return {"jsonrpc": "2.0", "method": "session/update", "params": params}


def formatAlertLine(event: dict) -> str:
    return json.dumps({"type": "long_tool_alert", **event}, ensure_ascii=False)


def validateLongTool(data: dict) -> None:
    if "long_tool" not in data:
        return
    block = data["long_tool"]
    if not isinstance(block, dict) or set(block) - {"timeout_seconds", "poll_seconds"}:
        raise ValueError("invalid long_tool")
    if "timeout_seconds" in block:
        _positiveInt(block["timeout_seconds"], "timeout_seconds")
    if "poll_seconds" in block:
        poll = _positiveInt(block["poll_seconds"], "poll_seconds")
        if poll > MAX_POLL_SECONDS:
            raise ValueError("poll_seconds exceeds 2 minutes")


def longToolPolicy(data: dict, env: dict[str, str] | None = None) -> LongToolPolicy:
    env = env or {}
    validateLongTool(data)
    block = data.get("long_tool") or {}
    timeout = _envOrConfig(env.get("BUZZ_LONG_TOOL_TIMEOUT_SECONDS"),
                           block.get("timeout_seconds"), DEFAULT_TIMEOUT_SECONDS, "timeout_seconds")
    poll = _envOrConfig(env.get("BUZZ_LONG_TOOL_POLL_SECONDS"),
                        block.get("poll_seconds"), DEFAULT_POLL_SECONDS, "poll_seconds")
    if poll > MAX_POLL_SECONDS:
        raise ValueError("poll_seconds exceeds 2 minutes")
    return LongToolPolicy(timeoutSeconds=timeout, pollSeconds=float(poll))


def runTurnGate(command: list[str], env: dict[str, str], *, policy: LongToolPolicy,
                mode: str, config=None, taskId: str | None = None,
                stdin=None, stdout=None, stderr=None) -> int:
    if mode not in {"harness", "executor"}:
        raise ValueError("invalid launch mode")
    stdin = sys.stdin.buffer if stdin is None else stdin
    stdout = sys.stdout.buffer if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr
    if mode == "harness":
        return _runInherited(command, env)
    return _runExecutorGate(command, env, policy=policy, config=config, taskId=taskId,
                            stdin=stdin, stdout=stdout, stderr=stderr)


def sendLongToolAlert(config, channel: str, postRef: str, text: str) -> None:
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


def processMarker(pid: int) -> str | None:
    try:
        stat = Path(f"/proc/{pid}").stat()
        return f"proc:{stat.st_dev}:{stat.st_ino}:{stat.st_ctime_ns}"
    except OSError:
        try:
            return subprocess.check_output(["ps", "-p", str(pid), "-o", "lstart="], text=True,
                                           stderr=subprocess.DEVNULL, timeout=2).strip() or None
        except (OSError, subprocess.SubprocessError):
            return None


def processGone(pid: int, marker: str | None) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    except OSError:
        return True
    current = processMarker(pid)
    if marker is not None and current is not None and marker != current:
        return True
    return False


def newestChild(pid: int) -> int | None:
    children = listChildren(pid)
    return max(children) if children else None


def listChildren(pid: int) -> list[int]:
    path = Path(f"/proc/{pid}/task/{pid}/children")
    try:
        text = path.read_text()
    except OSError:
        text = ""
    if text.strip():
        return [int(item) for item in text.split() if item.isdigit()]
    try:
        output = subprocess.check_output(["pgrep", "-P", str(pid)], text=True,
                                         stderr=subprocess.DEVNULL, timeout=2)
    except (OSError, subprocess.SubprocessError):
        return []
    return [int(item) for item in output.split() if item.isdigit()]


def _runInherited(command: list[str], env: dict[str, str]) -> int:
    child = subprocess.Popen(command, env=env)
    return _waitChild(child)


def _runExecutorGate(command: list[str], env: dict[str, str], *, policy: LongToolPolicy,
                     config, taskId: str | None, stdin, stdout, stderr) -> int:
    child = subprocess.Popen(command, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=None, bufsize=0)
    watch = LongToolWatch(policy)
    hold: list[bytes] = []
    sessionId: str | None = None
    cancelled = False
    lock = threading.Lock()

    def emit(raw: bytes) -> None:
        stdout.write(raw if raw.endswith(b"\n") else raw + b"\n")
        stdout.flush()

    def releaseHeld(*, force: bool = False) -> None:
        if not force and not canCloseTurn(watch):
            return
        pending = list(hold)
        hold.clear()
        for raw in pending:
            emit(raw)

    def handleAlert(event: dict) -> None:
        print(formatAlertLine(event), file=stderr, flush=True)
        injected = json.dumps(alertMessage(sessionId, event), ensure_ascii=False).encode("utf-8")
        emit(injected)
        _recordLedgerAlert(config, taskId, event)
        channel = env.get("BUZZ_WAKE_CHANNEL")
        postRef = env.get("BUZZ_WAKE_POST_REF")
        if config is not None and channel and postRef:
            text = alertMessage(sessionId, event)["params"]["update"]["content"]["text"]
            try:
                sendLongToolAlert(config, channel, postRef, text)
            except (ValueError, OSError, subprocess.SubprocessError) as exc:
                print(json.dumps({"type": "long_tool_alert", "reason": "send_failed",
                                  "error": type(exc).__name__}, ensure_ascii=False),
                      file=stderr, flush=True)

    stopRead, stopWrite = os.pipe()
    os.set_blocking(stopRead, False)

    def inbound() -> None:
        nonlocal cancelled, sessionId
        try:
            for raw in _readLines(stdin, stopFd=stopRead):
                parsed = parseAcpLine(raw)
                if isCancelMessage(parsed):
                    with lock:
                        cancelled = True
                        releaseHeld(force=True)
                sid = sessionIdFromMessage(parsed)
                if sid:
                    sessionId = sid
                if child.stdin is not None:
                    child.stdin.write(raw if raw.endswith(b"\n") else raw + b"\n")
                    child.stdin.flush()
        except BrokenPipeError:
            pass
        finally:
            if child.stdin is not None:
                try:
                    child.stdin.close()
                except OSError:
                    pass

    def outbound() -> None:
        nonlocal sessionId
        try:
            assert child.stdout is not None
            for raw in _readLines(child.stdout):
                parsed = parseAcpLine(raw)
                sid = sessionIdFromMessage(parsed)
                if sid:
                    sessionId = sid
                update = toolUpdateFromMessage(parsed)
                with lock:
                    if update is not None:
                        watch.apply(update, agentPid=child.pid)
                    if cancelled:
                        emit(raw)
                        continue
                    if turnCloseKind(parsed) and not canCloseTurn(watch):
                        hold.append(raw if raw.endswith(b"\n") else raw + b"\n")
                        continue
                    emit(raw)
        except BrokenPipeError:
            pass

    inboundThread = threading.Thread(target=inbound, name="acp-in", daemon=False)
    outboundThread = threading.Thread(target=outbound, name="acp-out", daemon=False)
    inboundThread.start()
    outboundThread.start()

    def wakeInbound() -> None:
        try:
            os.write(stopWrite, b"x")
        except OSError:
            pass

    def joinRelays() -> None:
        outboundThread.join(timeout=2)
        inboundThread.join(timeout=2)
        if inboundThread.is_alive() or outboundThread.is_alive():
            raise RuntimeError("ACP relay threads did not stop")

    previous = {}

    def forward(signum, _frame):
        try:
            child.send_signal(signum)
        except OSError:
            pass

    for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        previous[signum] = signal.signal(signum, forward)
    try:
        lastPoll = 0.0
        tick = min(_LOOP_SECONDS, float(policy.pollSeconds))
        while True:
            try:
                code = child.wait(timeout=tick)
            except subprocess.TimeoutExpired:
                code = None
            now = time.monotonic()
            with lock:
                if now - lastPoll >= policy.pollSeconds:
                    for event in watch.poll():
                        handleAlert(event)
                    lastPoll = now
                releaseHeld(force=cancelled)
            if code is not None:
                wakeInbound()
                joinRelays()
                with lock:
                    for tool in watch.tools.values():
                        if tool.status in _OPEN:
                            tool.status = "exited"
                            tool.lastReason = "exited"
                            handleAlert(_event(tool, "exited", time.monotonic() - tool.startedAt))
                    releaseHeld(force=cancelled)
                return code
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)
        wakeInbound()
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        joinRelays()
        for fd in (stopRead, stopWrite):
            try:
                os.close(fd)
            except OSError:
                pass


def _waitChild(child: subprocess.Popen) -> int:
    previous = {}

    def forward(signum, _frame):
        try:
            child.send_signal(signum)
        except OSError:
            pass

    for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        previous[signum] = signal.signal(signum, forward)
    try:
        return child.wait()
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


def _readLines(stream, stopFd=None):
    streamFd = _streamFd(stream)
    if stopFd is None or streamFd is None:
        while True:
            line = stream.readline()
            if not line:
                return
            yield line
        return
    leftover = b""
    while True:
        try:
            ready, _, _ = select.select([streamFd, stopFd], [], [])
        except (ValueError, OSError):
            return
        if stopFd in ready:
            try:
                os.read(stopFd, 4096)
            except OSError:
                pass
            return
        if streamFd not in ready:
            continue
        try:
            chunk = os.read(streamFd, 4096)
        except OSError:
            return
        if not chunk:
            if leftover:
                yield leftover
            return
        leftover += chunk
        while b"\n" in leftover:
            line, leftover = leftover.split(b"\n", 1)
            yield line + b"\n"


def _streamFd(stream):
    try:
        return stream.fileno()
    except (AttributeError, OSError, ValueError):
        return None


def _recordLedgerAlert(config, taskId: str | None, event: dict) -> None:
    if config is None or not taskId:
        return
    from .context import ContextLedger
    try:
        ContextLedger(config.instance, taskId).record_long_tool_alert(
            reason=event["reason"], tool_ref=event["tool_ref"], elapsed_s=event["elapsed_s"])
    except ValueError:
        return


def _event(tool: LongTool, reason: str, elapsed: float) -> dict:
    return {
        "reason": reason,
        "tool_ref": tool.toolCallId[:12],
        "status": tool.status,
        "elapsed_s": int(elapsed),
        "pid": tool.pid,
    }


def _positiveInt(value: object, name: str) -> int:
    if type(value) is not int or isinstance(value, bool) or value <= 0:
        raise ValueError(f"invalid {name}")
    return value


def _envOrConfig(raw: str | None, configured: object, default: int, name: str) -> int:
    if raw is not None:
        try:
            parsed = int(raw)
        except ValueError as exc:
            raise ValueError(f"invalid {name}") from exc
        return _positiveInt(parsed, name)
    if configured is None:
        return default
    return _positiveInt(configured, name)
