import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from buzz_team.config import Config, identity
from buzz_team.instance import init_legacy, write_json
from buzz_team.turn_gate import (
    DEFAULT_POLL_SECONDS, DEFAULT_TIMEOUT_SECONDS, LongToolPolicy, LongToolWatch,
    canCloseTurn, extractBarePids, extractPids, isBackgroundMarker, longToolPolicy,
    parseAcpLine, runTurnGate, turnCloseKind, validateLongTool,
)


FAKE_AGENT = r"""
import json, os, subprocess, sys, time
spec = json.loads(os.environ["FAKE_AGENT_SPEC"])
child = subprocess.Popen([sys.executable, "-c", spec["child"]])
req = json.loads(sys.stdin.readline())
update = {
    "jsonrpc": "2.0",
    "method": "session/update",
    "params": {
        "sessionId": req["params"]["sessionId"],
        "update": {
            "sessionUpdate": "tool_call_update",
            "toolCallId": "call-bg",
            "status": "completed",
            "title": "shell [bg] pid=%d" % child.pid,
            "content": [{"type": "content", "content": {"type": "text", "text": "[bg] pid=%d" % child.pid}}],
        },
    },
}
print(json.dumps(update), flush=True)
print(json.dumps({"jsonrpc": "2.0", "id": req["id"], "result": {"stopReason": "end_turn"}}), flush=True)
if spec.get("wait_child"):
    child.wait()
else:
    time.sleep(spec.get("linger", 30))
"""

GATE_WRAPPER = r"""
import json, os, sys
from buzz_team.turn_gate import LongToolPolicy, runTurnGate
policy = LongToolPolicy(timeoutSeconds=int(os.environ["GATE_TIMEOUT"]),
                        pollSeconds=float(os.environ["GATE_POLL"]))
raise SystemExit(runTurnGate(json.loads(os.environ["GATE_CMD"]), dict(os.environ),
                             policy=policy, mode="executor"))
"""

FAKE_NATURAL_BG = r"""
import json, os, subprocess, sys, time
spec = json.loads(os.environ.get("FAKE_AGENT_SPEC", "{}"))
real = subprocess.Popen([sys.executable, "-c", spec.get("real", "import time; time.sleep(20)")])
ephem = subprocess.Popen([sys.executable, "-c", spec.get("ephem", "import time; time.sleep(0.4)")])
req = json.loads(sys.stdin.readline())
sid = req["params"]["sessionId"]
tid = "call-599f0ca3-7f3c-4fa2-9c0e-aaaaaaaaaaaa"
print(json.dumps({
    "jsonrpc": "2.0", "method": "session/update",
    "params": {"sessionId": sid, "update": {
        "sessionUpdate": "tool_call_update", "toolCallId": tid,
        "status": "completed", "title": "[bg] nohup sleep 900",
        "content": [{"type": "content", "content": {"type": "text",
            "text": "Background task started (task_id 01a0ce6c-3d9f-7351-b8ad-c6c699b68a20)"}}],
    }},
}), flush=True)
if spec.get("emit_bare_pid", True):
    print(json.dumps({
        "jsonrpc": "2.0", "method": "session/update",
        "params": {"sessionId": sid, "update": {
            "sessionUpdate": "tool_call_update", "toolCallId": tid,
            "status": "in_progress",
            "content": [{"type": "content", "content": {"type": "text",
                "text": "%d\n" % real.pid}}],
        }},
    }), flush=True)
print(json.dumps({"jsonrpc": "2.0", "id": req["id"], "result": {"stopReason": "end_turn"}}), flush=True)
print(json.dumps({"jsonrpc": "2.0", "method": "_x.ai/session/prompt_complete",
                  "params": {"sessionId": sid, "stopReason": "end_turn"}}), flush=True)
print(json.dumps({"jsonrpc": "2.0", "method": "session/update",
                  "params": {"sessionId": sid, "update": {
                      "sessionUpdate": "turn_completed", "stopReason": "end_turn"}}}), flush=True)
print(json.dumps({"jsonrpc": "2.0", "method": "_x.ai/session_notification",
                  "params": {"sessionId": sid, "update": {
                      "sessionUpdate": "turn_completed", "prompt_id": "247e8338",
                      "stop_reason": "end_turn"}}}), flush=True)
print("REAL_PID=%d EPHEM_PID=%d" % (real.pid, ephem.pid), file=sys.stderr, flush=True)
ephem.wait()
time.sleep(spec.get("linger", 8))
"""

FAKE_LIVE_SESSION_NOTIFICATION = r"""
import json, sys, time
req = json.loads(sys.stdin.readline())
sid = req["params"]["sessionId"]
tid = "call-56b62bfc-8922-49ea-8344-bb99b14a6c1d-0"
print(json.dumps({
    "jsonrpc": "2.0", "method": "session/update",
    "params": {"sessionId": sid, "update": {
        "sessionUpdate": "tool_call_update", "toolCallId": tid,
        "status": "completed",
        "title": "[bg] nohup sleep 900 >/dev/null 2>&1 & echo $!",
        "content": [{"type": "content", "content": {"type": "text",
            "text": "Background task started (task_id 01a0ce91-e5a3-7663-93f6-6ee7921c50b9)"}}],
    }},
}), flush=True)
print(json.dumps({
    "jsonrpc": "2.0", "method": "_x.ai/session_notification",
    "params": {"sessionId": sid, "update": {
        "sessionUpdate": "turn_completed",
        "prompt_id": "247e8338-b366-4efd-894d-7b394ad20dc7",
        "stop_reason": "end_turn",
    }},
}), flush=True)
time.sleep(8)
"""


class TurnGateUnitTests(unittest.TestCase):
    def test_background_marker_and_pid_extraction(self):
        self.assertTrue(isBackgroundMarker("sleep 3600 [bg]"))
        self.assertTrue(isBackgroundMarker("Command backgrounded"))
        self.assertFalse(isBackgroundMarker("echo done"))
        self.assertEqual(extractPids("shell [bg] pid=4321 extra"), [4321])
        self.assertEqual(extractBarePids("79588\n"), [79588])
        self.assertEqual(extractBarePids(
            "Background task started (task_id 01a0ce6c-3d9f-7351-b8ad-c6c699b68a20)"), [])

    def test_cannot_close_turn_while_background_tool_runs(self):
        watch = LongToolWatch(LongToolPolicy(timeoutSeconds=1200, pollSeconds=60))
        watch.apply({
            "sessionUpdate": "tool_call_update",
            "toolCallId": "call-1",
            "status": "completed",
            "title": "kairo [bg] pid=1",
            "content": [{"type": "content", "content": {"type": "text", "text": "[bg] pid=1"}}],
        }, now=10)
        self.assertFalse(canCloseTurn(watch))
        self.assertEqual(watch.tools["call-1"].status, "background")
        self.assertEqual(watch.tools["call-1"].pid, 1)

    def test_plain_completed_tool_allows_turn_close(self):
        watch = LongToolWatch(LongToolPolicy(timeoutSeconds=1200, pollSeconds=60))
        watch.apply({"sessionUpdate": "tool_call", "toolCallId": "call-1", "status": "in_progress"}, now=1)
        self.assertFalse(canCloseTurn(watch))
        watch.apply({"sessionUpdate": "tool_call_update", "toolCallId": "call-1", "status": "completed"}, now=2)
        self.assertTrue(canCloseTurn(watch))

    def test_timeout_and_vanished_are_decidable_failures(self):
        watch = LongToolWatch(LongToolPolicy(timeoutSeconds=5, pollSeconds=1))
        watch.apply({
            "toolCallId": "slow",
            "status": "in_progress",
            "title": "sleep [bg] pid=1",
        }, now=0)
        events = watch.poll(now=5)
        self.assertEqual([item["reason"] for item in events], ["timeout"])
        self.assertTrue(canCloseTurn(watch))
        gone = LongToolWatch(LongToolPolicy(timeoutSeconds=30, pollSeconds=1))
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        gone.apply({
            "toolCallId": "dead",
            "status": "completed",
            "title": "[bg] pid=%d" % child.pid,
        }, now=0)
        child.kill()
        child.wait()
        events = gone.poll(now=1)
        self.assertEqual([item["reason"] for item in events], ["exited"])
        self.assertTrue(canCloseTurn(gone))

    def test_prompt_result_is_the_turn_close(self):
        self.assertEqual(turnCloseKind({"id": 2, "result": {"stopReason": "end_turn"}}), "prompt_result")
        self.assertIsNone(turnCloseKind({"method": "session/update", "params": {
            "update": {"sessionUpdate": "agent_message_chunk"}}}))
        self.assertIsNone(parseAcpLine(b"not-json\n"))

    def test_bg_without_pid_does_not_guess_newest_child(self):
        watch = LongToolWatch(LongToolPolicy(timeoutSeconds=30, pollSeconds=1))
        ephemeral = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(0.05)"])
        ephemeral.wait()
        watch.apply({
            "sessionUpdate": "tool_call_update",
            "toolCallId": "call-599f0ca3",
            "status": "completed",
            "title": "[bg] nohup sleep 900",
            "content": [{"type": "content", "content": {
                "type": "text",
                "text": "Background task started (task_id 01a0ce6c-3d9f-7351-b8ad-c6c699b68a20)",
            }}],
        }, now=0)
        self.assertIsNone(watch.tools["call-599f0ca3"].pid)
        self.assertEqual(watch.tools["call-599f0ca3"].status, "background")
        self.assertFalse(canCloseTurn(watch))
        events = watch.poll(now=1)
        self.assertEqual(events, [])
        self.assertFalse(canCloseTurn(watch))
        self.assertNotEqual(watch.tools["call-599f0ca3"].status, "exited")

    def test_bare_numeric_content_binds_live_pid(self):
        watch = LongToolWatch(LongToolPolicy(timeoutSeconds=1200, pollSeconds=1))
        real = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        wrapper = subprocess.Popen([sys.executable, "-c", "pass"])
        wrapper.wait()
        try:
            watch.apply({
                "sessionUpdate": "tool_call_update",
                "toolCallId": "call-bg",
                "status": "completed",
                "title": "[bg] nohup sleep 900",
                "content": [{"type": "content", "content": {
                    "type": "text",
                    "text": "Background task started (task_id 01a0ce6c-3d9f-7351-b8ad-c6c699b68a20)",
                }}],
            }, now=0)
            self.assertIsNone(watch.tools["call-bg"].pid)
            watch.apply({
                "sessionUpdate": "tool_call_update",
                "toolCallId": "call-bg",
                "status": "in_progress",
                "content": [{"type": "content", "content": {
                    "type": "text", "text": "%d\n" % real.pid,
                }}],
            }, now=1)
            self.assertEqual(watch.tools["call-bg"].pid, real.pid)
            self.assertFalse(canCloseTurn(watch))
            events = watch.poll(now=2)
            self.assertEqual(events, [])
        finally:
            real.kill()
            real.wait()
        events = watch.poll(now=3)
        self.assertEqual([item["reason"] for item in events], ["exited"])
        self.assertTrue(canCloseTurn(watch))

    def test_zombie_pid_counts_as_gone(self):
        from buzz_team.turn_gate import processGone
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        watch = LongToolWatch(LongToolPolicy(timeoutSeconds=1200, pollSeconds=1))
        watch.apply({
            "toolCallId": "call-bg",
            "status": "completed",
            "title": "[bg] pid=%d" % child.pid,
        }, now=0)
        self.assertEqual(watch.tools["call-bg"].pid, child.pid)
        os.kill(child.pid, 9)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and not processGone(child.pid, watch.tools["call-bg"].marker):
            time.sleep(0.02)
        events = watch.poll(now=1)
        child.wait()
        self.assertEqual([item["reason"] for item in events], ["exited"])
        self.assertTrue(canCloseTurn(watch))

    def test_dead_pid_equals_is_not_bound(self):
        watch = LongToolWatch(LongToolPolicy(timeoutSeconds=30, pollSeconds=1))
        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait()
        live = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        try:
            watch.apply({
                "toolCallId": "call-bg",
                "status": "completed",
                "title": "[bg] pid=%d" % dead.pid,
            }, now=0)
            self.assertIsNone(watch.tools["call-bg"].pid)
            self.assertFalse(canCloseTurn(watch))
            watch.apply({
                "toolCallId": "call-bg",
                "status": "in_progress",
                "content": [{"type": "content", "content": {
                    "type": "text", "text": "%d\n" % live.pid,
                }}],
            }, now=1)
            self.assertEqual(watch.tools["call-bg"].pid, live.pid)
        finally:
            live.kill()
            live.wait()

    def test_proprietary_turn_close_kinds(self):
        self.assertEqual(turnCloseKind({
            "jsonrpc": "2.0",
            "method": "_x.ai/session/prompt_complete",
            "params": {"sessionId": "sess", "stopReason": "end_turn"},
        }), "prompt_complete")
        self.assertEqual(turnCloseKind({
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {"sessionId": "sess", "update": {
                "sessionUpdate": "turn_completed", "stopReason": "end_turn",
            }},
        }), "turn_completed")
        self.assertEqual(turnCloseKind({
            "method": "session/update",
            "params": {"stopReason": "end_turn", "update": {
                "sessionUpdate": "agent_message_chunk",
            }},
        }), "state_stop")

    def test_live_session_notification_turn_completed_is_close(self):
        # Hogan live re-verify 2026-09-23 ~22:01 CST: grok forwarded this ~8s
        # after natural [bg] because turnCloseKind only knew prompt_complete /
        # session/update turn_completed.
        live = {
            "jsonrpc": "2.0",
            "method": "_x.ai/session_notification",
            "params": {
                "sessionId": "01a0ce91-95cf-7462-9083-4936f25940c1",
                "update": {
                    "sessionUpdate": "turn_completed",
                    "prompt_id": "247e8338-b366-4efd-894d-7b394ad20dc7",
                    "stop_reason": "end_turn",
                    "usage": {"inputTokens": 62525, "outputTokens": 1220},
                },
            },
        }
        self.assertEqual(turnCloseKind(live), "turn_completed")
        self.assertEqual(turnCloseKind({
            "method": "_x.ai/session_notification",
            "params": {"sessionId": "sess", "stop_reason": "end_turn",
                       "update": {"sessionUpdate": "agent_message_chunk"}},
        }), "state_stop")
        self.assertIsNone(turnCloseKind({
            "method": "_x.ai/session_notification",
            "params": {"sessionId": "sess", "update": {
                "sessionUpdate": "tool_call_update", "status": "completed",
            }},
        }))
        self.assertIsNone(turnCloseKind({
            "method": "_x.ai/task_completed",
            "params": {"sessionId": "sess", "update": {
                "sessionUpdate": "task_completed",
                "tool_call_id": "call-56b62bfc",
            }},
        }))

    def test_policy_defaults_and_fail_closed_config(self):
        self.assertEqual(longToolPolicy({}).timeoutSeconds, DEFAULT_TIMEOUT_SECONDS)
        self.assertEqual(longToolPolicy({}).pollSeconds, float(DEFAULT_POLL_SECONDS))
        with self.assertRaisesRegex(ValueError, "poll_seconds exceeds"):
            validateLongTool({"long_tool": {"poll_seconds": 121}})
        with self.assertRaisesRegex(ValueError, "invalid long_tool"):
            validateLongTool({"long_tool": {"timeout_seconds": 1200, "extra": 1}})
        with self.assertRaisesRegex(ValueError, "invalid timeout_seconds"):
            longToolPolicy({}, {"BUZZ_LONG_TOOL_TIMEOUT_SECONDS": "0"})
        policy = longToolPolicy({"long_tool": {"timeout_seconds": 900, "poll_seconds": 30}},
                                {"BUZZ_LONG_TOOL_POLL_SECONDS": "15"})
        self.assertEqual(policy.timeoutSeconds, 900)
        self.assertEqual(policy.pollSeconds, 15.0)


class TurnGateRelayTests(unittest.TestCase):
    def _runGate(self, *, child: str, waitChild: bool, linger: int,
                 timeout: int, poll: float):
        spec = json.dumps({"child": child, "wait_child": waitChild, "linger": linger})
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"),
                   FAKE_AGENT_SPEC=spec, GATE_TIMEOUT=str(timeout), GATE_POLL=str(poll),
                   GATE_CMD=json.dumps([sys.executable, "-c", FAKE_AGENT]))
        proc = subprocess.Popen([sys.executable, "-c", GATE_WRAPPER], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
                                bufsize=0)
        prompt = json.dumps({
            "jsonrpc": "2.0", "id": 2, "method": "session/prompt",
            "params": {"sessionId": "sess-test", "prompt": [{"type": "text", "text": "run long"}]},
        }) + "\n"
        proc.stdin.write(prompt.encode())
        proc.stdin.flush()
        return proc

    def _readUntil(self, proc, predicate, timeout):
        import select
        deadline = time.monotonic() + timeout
        buf = b""
        lines = []
        while time.monotonic() < deadline:
            remaining = max(0.05, deadline - time.monotonic())
            ready, _, _ = select.select([proc.stdout], [], [], min(0.2, remaining))
            if not ready:
                if proc.poll() is not None:
                    break
                continue
            chunk = os.read(proc.stdout.fileno(), 4096)
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                lines.append(line.decode())
                if predicate(lines):
                    return lines
        if buf:
            lines.append(buf.decode())
        return lines

    def _runNaturalGate(self, *, emitBarePid: bool, timeout: int, poll: float,
                        linger: int = 8):
        spec = json.dumps({"emit_bare_pid": emitBarePid, "linger": linger})
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"),
                   FAKE_AGENT_SPEC=spec, GATE_TIMEOUT=str(timeout), GATE_POLL=str(poll),
                   GATE_CMD=json.dumps([sys.executable, "-c", FAKE_NATURAL_BG]))
        proc = subprocess.Popen([sys.executable, "-c", GATE_WRAPPER], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
                                bufsize=0)
        prompt = json.dumps({
            "jsonrpc": "2.0", "id": 3, "method": "session/prompt",
            "params": {"sessionId": "sess-natural", "prompt": [{"type": "text", "text": "bg"}]},
        }) + "\n"
        proc.stdin.write(prompt.encode())
        proc.stdin.flush()
        return proc

    def _closeGate(self, proc, extraPids=None):
        if proc.stdin:
            try:
                proc.stdin.close()
            except OSError:
                pass
        proc.kill()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        for stream in (proc.stdout, proc.stderr):
            if stream:
                try:
                    stream.close()
                except OSError:
                    pass
        for pid in extraPids or []:
            try:
                os.kill(pid, 9)
            except OSError:
                pass

    def _closeMarkers(self, rows):
        return [row for row in rows if (
            '"stopReason": "end_turn"' in row or '"stopReason":"end_turn"' in row
            or '"stop_reason": "end_turn"' in row or '"stop_reason":"end_turn"' in row
            or "prompt_complete" in row or "turn_completed" in row
            or "session_notification" in row)]

    def test_s1_holds_end_turn_until_background_pid_exits(self):
        proc = self._runGate(child="import time; time.sleep(1.2)", waitChild=True,
                             linger=0, timeout=30, poll=0.1)
        started = time.monotonic()
        lines = self._readUntil(proc, lambda rows: any("end_turn" in row for row in rows), 8)
        elapsed = time.monotonic() - started
        self.assertTrue(any("end_turn" in row for row in lines), lines)
        self.assertGreaterEqual(elapsed, 1.0)
        try:
            _, err = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            _, err = proc.communicate(timeout=5)
        self.assertNotIn("timeout", err.decode() if isinstance(err, bytes) else err)

    def test_s1_cancel_immediately_releases_held_end_turn(self):
        proc = self._runGate(child="import time; time.sleep(30)", waitChild=False,
                             linger=30, timeout=60, poll=0.1)
        lines = self._readUntil(proc, lambda rows: any("tool_call_update" in row for row in rows), 4)
        self.assertTrue(any("tool_call_update" in row for row in lines), lines)
        self.assertFalse(any("end_turn" in row for row in lines), lines)
        cancel = json.dumps({
            "jsonrpc": "2.0", "method": "session/cancel",
            "params": {"sessionId": "sess-test"},
        }) + "\n"
        proc.stdin.write(cancel.encode())
        proc.stdin.flush()
        started = time.monotonic()
        released = self._readUntil(proc, lambda rows: any("end_turn" in row for row in rows), 3)
        elapsed = time.monotonic() - started
        pids = [pid for row in lines for pid in extractPids(row)]
        if proc.stdin:
            proc.stdin.close()
        proc.kill()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        for stream in (proc.stdout, proc.stderr):
            if stream:
                stream.close()
        for pid in pids:
            try:
                os.kill(pid, 9)
            except OSError:
                pass
        self.assertTrue(any("end_turn" in row for row in released), released)
        self.assertLess(elapsed, 1.5)

    def _stderrPids(self, text: str) -> list[int]:
        found = []
        for part in text.split():
            if part.startswith("REAL_PID=") or part.startswith("EPHEM_PID="):
                found.append(int(part.split("=", 1)[1]))
        return found

    def _contentPids(self, rows):
        found = []
        for row in rows:
            try:
                found.extend(extractBarePids(json.loads(row)))
            except json.JSONDecodeError:
                continue
        return found

    def test_s1_natural_bg_ephemeral_child_does_not_release(self):
        proc = self._runNaturalGate(emitBarePid=False, timeout=60, poll=0.1, linger=8)
        extra = []
        err = b""
        try:
            lines = self._readUntil(
                proc, lambda rows: any("[bg]" in row for row in rows), 4)
            self.assertTrue(any("[bg]" in row for row in lines), lines)
            time.sleep(0.7)
            more = self._readUntil(
                proc, lambda rows: bool(self._closeMarkers(rows)), 0.3)
            lines.extend(more)
            if proc.stderr:
                import select as sel
                if sel.select([proc.stderr], [], [], 0.05)[0]:
                    err = os.read(proc.stderr.fileno(), 8192)
            extra.extend(self._stderrPids(err.decode(errors="replace")))
            self.assertFalse(self._closeMarkers(lines), lines)
            self.assertNotIn(b'"reason": "exited"', err)
            self.assertFalse(any("【长工具】" in row for row in lines), lines)
            cancel = json.dumps({
                "jsonrpc": "2.0", "method": "session/cancel",
                "params": {"sessionId": "sess-natural"},
            }) + "\n"
            proc.stdin.write(cancel.encode())
            proc.stdin.flush()
            released = self._readUntil(
                proc, lambda rows: bool(self._closeMarkers(rows)), 3)
            self.assertTrue(self._closeMarkers(released), released)
        finally:
            if proc.stderr:
                try:
                    leftover = proc.stderr.read()
                    extra.extend(self._stderrPids(
                        leftover.decode(errors="replace") if leftover else ""))
                except OSError:
                    pass
            self._closeGate(proc, extra)

    def test_s1_natural_bg_bare_pid_and_proprietary_hold(self):
        proc = self._runNaturalGate(emitBarePid=True, timeout=60, poll=0.1, linger=8)
        extra = []
        try:
            lines = self._readUntil(
                proc, lambda rows: bool(self._contentPids(rows)), 4)
            self.assertTrue(any("[bg]" in row for row in lines), lines)
            time.sleep(0.7)
            more = self._readUntil(
                proc, lambda rows: bool(self._closeMarkers(rows)), 0.3)
            lines.extend(more)
            self.assertFalse(self._closeMarkers(lines), lines)
            self.assertFalse(any("【长工具】" in row for row in lines), lines)
            realPids = self._contentPids(lines)
            self.assertTrue(realPids, lines)
            extra.extend(realPids)
            os.kill(realPids[0], 9)
            released = self._readUntil(
                proc, lambda rows: (
                    any("end_turn" in row for row in rows)
                    and any("prompt_complete" in row for row in rows)
                    and any("turn_completed" in row for row in rows)
                ), 4)
            self.assertTrue(any("end_turn" in row for row in released), released)
            self.assertTrue(any("prompt_complete" in row for row in released), released)
            self.assertTrue(any("turn_completed" in row for row in released), released)
            self.assertTrue(any("session_notification" in row for row in released), released)
        finally:
            self._closeGate(proc, extra)

    def test_s1_holds_live_session_notification_close(self):
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"),
                   GATE_TIMEOUT="60", GATE_POLL="0.1",
                   GATE_CMD=json.dumps([sys.executable, "-c", FAKE_LIVE_SESSION_NOTIFICATION]))
        proc = subprocess.Popen([sys.executable, "-c", GATE_WRAPPER], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
                                bufsize=0)
        prompt = json.dumps({
            "jsonrpc": "2.0", "id": 4, "method": "session/prompt",
            "params": {"sessionId": "sess-live-notify", "prompt": [
                {"type": "text", "text": "bg"},
            ]},
        }) + "\n"
        proc.stdin.write(prompt.encode())
        proc.stdin.flush()
        try:
            lines = self._readUntil(
                proc, lambda rows: any("[bg]" in row for row in rows), 4)
            self.assertTrue(any("[bg]" in row for row in lines), lines)
            leaked = self._readUntil(
                proc, lambda rows: any("session_notification" in row for row in rows), 0.4)
            lines.extend(leaked)
            self.assertFalse(any("session_notification" in row for row in lines), lines)
            self.assertFalse(self._closeMarkers(lines), lines)
            cancel = json.dumps({
                "jsonrpc": "2.0", "method": "session/cancel",
                "params": {"sessionId": "sess-live-notify"},
            }) + "\n"
            proc.stdin.write(cancel.encode())
            proc.stdin.flush()
            released = self._readUntil(
                proc, lambda rows: any("session_notification" in row for row in rows), 3)
            self.assertTrue(any("session_notification" in row for row in released), released)
            self.assertTrue(any("turn_completed" in row for row in released), released)
            self.assertTrue(any("end_turn" in row for row in released), released)
        finally:
            self._closeGate(proc)

    def test_s2_timeout_alerts_and_then_allows_close(self):
        proc = self._runGate(child="import time; time.sleep(30)", waitChild=False,
                             linger=30, timeout=1, poll=0.1)
        lines = self._readUntil(proc, lambda rows: any("end_turn" in row for row in rows), 6)
        proc.kill()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            pass
        err = proc.stderr.read().decode() if proc.stderr else ""
        self.assertTrue(any("end_turn" in row for row in lines), lines)
        self.assertTrue(any("【长工具】" in row and "timeout" in row for row in lines) or
                        any("原因: timeout" in row for row in lines), lines)
        self.assertTrue("long_tool_alert" in err or "timeout" in err or
                        any("timeout" in row for row in lines), err or lines)

    def test_s2_killed_pid_alerts_within_poll(self):
        watch = LongToolWatch(LongToolPolicy(timeoutSeconds=1200, pollSeconds=0.1))
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        watch.apply({
            "toolCallId": "live",
            "status": "completed",
            "title": "[bg] pid=%d" % child.pid,
        })
        self.assertFalse(canCloseTurn(watch))
        child.kill()
        child.wait()
        started = time.monotonic()
        events = []
        while time.monotonic() - started < 2:
            events = watch.poll()
            if events:
                break
            time.sleep(0.05)
        self.assertEqual([item["reason"] for item in events], ["exited"])
        self.assertLess(time.monotonic() - started, 2)

    def test_harness_inherits_and_returns_child_status(self):
        script = "import json,sys; print(json.dumps({'ok': True})); raise SystemExit(0)"
        code = runTurnGate([sys.executable, "-c", script], dict(os.environ),
                           policy=LongToolPolicy(1200, 60), mode="harness")
        self.assertEqual(code, 0)

    def test_non_acp_stdout_is_forwarded(self):
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"),
                   GATE_TIMEOUT="30", GATE_POLL="0.1",
                   GATE_CMD=json.dumps([sys.executable, "-c",
                                        "import json; print(json.dumps({'args':['acp']}))"]))
        proc = subprocess.Popen([sys.executable, "-c", GATE_WRAPPER], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        out, err = proc.communicate(input=b"", timeout=5)
        self.assertEqual(proc.returncode, 0, err)
        self.assertEqual(json.loads(out.decode())["args"], ["acp"])

    def test_cold_executor_exits_cleanly_with_open_stdin(self):
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"),
                   GATE_TIMEOUT="30", GATE_POLL="0.1",
                   GATE_CMD=json.dumps([sys.executable, "-c",
                                        "import json; print(json.dumps({'ok': True}))"]))
        readFd, writeFd = os.pipe()
        try:
            proc = subprocess.Popen([sys.executable, "-c", GATE_WRAPPER], stdin=readFd,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        finally:
            os.close(readFd)
        try:
            out, err = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, err = proc.communicate(timeout=5)
            os.close(writeFd)
            self.fail("gate hung on open stdin: %r" % err)
        os.close(writeFd)
        self.assertEqual(proc.returncode, 0, err)
        self.assertEqual(json.loads(out.decode())["ok"], True)


class LongToolConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.instance = self.root / "instance"
        self.key = identity("ws://localhost:3000", "a" * 64)
        self.base = self.root / "states" / self.key
        for name in ("grok", "workspace"):
            (self.base / name).mkdir(parents=True)
        (self.base / "grok/auth.json").write_text("{}\n")
        (self.base / "grok/config.toml").write_text("#\n")
        self.fake = self.root / "fake"
        self.fake.write_text("#!/bin/sh\n")
        self.fake.chmod(0o700)
        self.app = self.root / "Buzz.app"
        (self.app / "Contents/MacOS").mkdir(parents=True)
        import plistlib
        (self.app / "Contents/Info.plist").write_bytes(plistlib.dumps({
            "CFBundleExecutable": "Buzz", "CFBundleIdentifier": "xyz.block.buzz.app",
            "CFBundleShortVersionString": "0.5.23"}))
        (self.app / "Contents/MacOS/Buzz").write_text("")
        desktop = self.root / "managed-agents.json"
        write_json(desktop, [{"pubkey": "a" * 64, "relay_url": "ws://localhost:3000"}])
        legacy = self.root / "legacy.json"
        write_json(legacy, {
            "version": 1, "state_root": str(self.root / "states"), "protected_home": str(self.root),
            "production": {"data_root": str(self.root / "production"), "protected_paths": [],
                           "blocked_ports": []},
            "binaries": {"buzz": str(self.fake), "harness": str(self.fake), "grok": str(self.fake)},
            "agents": {self.key: {"pubkey": "a" * 64, "relay_url": "ws://localhost:3000",
                                  "policy": "development"}},
            "policies": {"development": {"production_write": False, "data_mode": "test"}},
            "repositories": {},
        })
        (self.root / "production").mkdir()
        init_legacy(self.instance, legacy, desktop, self.app)
        self.config = Config(self.instance)

    def test_instance_rejects_slow_poll(self):
        data = copy.deepcopy(self.config.data)
        data["long_tool"] = {"timeout_seconds": 1200, "poll_seconds": 180}
        with self.assertRaisesRegex(ValueError, "poll_seconds exceeds"):
            Config(self.instance, data=data)
        data["long_tool"] = {"timeout_seconds": 1800, "poll_seconds": 30}
        Config(self.instance, data=data)


if __name__ == "__main__":
    unittest.main()
