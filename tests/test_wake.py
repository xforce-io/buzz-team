import json
from pathlib import Path
import unittest
from unittest.mock import patch

from buzz_team.config import Config, identity
from buzz_team.wake import (
    ChannelCursorStore, applyFuse, decideWake, extractAliasTokens,
    formatFuseReply, isExecutionOriented, sessionRef,
)
from test_runtime import Fixture


class MentionGateTests(Fixture):
    def enableWake(self, ownerChannel=None):
        other = identity("ws://localhost:3000", "b" * 64)
        self.other = other
        self.config.data["agents"][self.key]["mention_aliases"] = ["agent-one"]
        self.config.data["agents"][other] = dict(self.config.agent(self.key), pubkey="b" * 64,
                                                mention_aliases=["agent-two"])
        wake = {"default": {"require_mention": True, "allow_short_ack": False,
                            "rotate": {"max_turns": 8, "max_usd": 3, "max_input_tokens": 1000}},
                "channels": {}}
        if ownerChannel:
            wake["channels"][ownerChannel] = {"single_owner_identity": self.key}
        self.config.data["channel_wake"] = wake
        self.save()

    def test_config_rejects_default_owner_and_human_alias(self):
        self.config.data["channel_wake"] = {"default": {"single_owner_identity": self.key}}
        with self.assertRaisesRegex(ValueError, "per-channel only"):
            self.save()
        self.config.data["channel_wake"] = {"default": {"require_mention": True}}
        self.config.data["agents"][self.key]["mention_aliases"] = ["freeman"]
        with self.assertRaisesRegex(ValueError, "human mention alias"):
            self.save()

    def test_alias_conflict_fails_closed(self):
        other = identity("ws://localhost:3000", "b" * 64)
        self.config.data["agents"][self.key]["mention_aliases"] = ["shared-bot"]
        self.config.data["agents"][other] = dict(self.config.agent(self.key), pubkey="b" * 64,
                                                mention_aliases=["shared-bot"])
        with self.assertRaisesRegex(ValueError, "mention alias conflict"):
            self.save()

    def test_tokens_are_exact_and_ignore_humans_and_email(self):
        self.assertEqual(extractAliasTokens("see @agent-one, then @freeman and user@host"),
                         ["agent-one", "freeman"])
        self.enableWake()
        mentioned = decideWake(self.config, identity=self.key, channel="channel-fixture",
                               postRef="post-1", body="please @agent-one look")
        self.assertEqual(mentioned, {"allowed": True, "reason": "mentioned"})
        other = decideWake(self.config, identity=self.other, channel="channel-fixture",
                           postRef="post-1", body="please @agent-one look")
        self.assertEqual(other, {"allowed": False, "reason": "not_mentioned"})
        human = decideWake(self.config, identity=self.key, channel="channel-fixture",
                           postRef="post-2", body="ask @freeman only")
        self.assertEqual(human, {"allowed": False, "reason": "not_mentioned"})

    def test_single_owner_is_per_channel_and_empty_agent_mentions_only(self):
        self.enableWake(ownerChannel="channel-owned")
        allow = decideWake(self.config, identity=self.key, channel="channel-owned",
                           postRef="post-3", body="plain discussion")
        self.assertEqual(allow, {"allowed": True, "reason": "single_owner"})
        other = decideWake(self.config, identity=self.other, channel="channel-owned",
                           postRef="post-3", body="plain discussion")
        self.assertEqual(other, {"allowed": False, "reason": "not_mentioned"})
        elsewhere = decideWake(self.config, identity=self.key, channel="channel-other",
                               postRef="post-3", body="plain discussion")
        self.assertEqual(elsewhere, {"allowed": False, "reason": "not_mentioned"})
        mentionedOther = decideWake(self.config, identity=self.key, channel="channel-owned",
                                    postRef="post-4", body="hey @agent-two")
        self.assertEqual(mentionedOther, {"allowed": False, "reason": "not_mentioned"})

    def test_structured_mentions_and_unknown_surface_fail_closed(self):
        self.enableWake()
        with self.assertRaisesRegex(ValueError, "structured mentions unsupported"):
            decideWake(self.config, identity=self.key, channel="channel-fixture",
                       postRef="post-5", body="@agent-one", mentions=["agent-one"])
        with self.assertRaisesRegex(ValueError, "unknown wake surface"):
            decideWake(self.config, identity=self.key, channel="channel-fixture",
                       postRef="post-5", body="@agent-one", surface="mystery")
        dm = decideWake(self.config, identity=self.key, channel="channel-fixture",
                        postRef="post-5", body="plain", surface="dm")
        self.assertEqual(dm, {"allowed": True, "reason": "dm"})

    def test_unknown_tool_is_execution_oriented(self):
        self.assertTrue(isExecutionOriented("shell"))
        self.assertFalse(isExecutionOriented("read_post"))


class CursorAndFuseTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.instance = Path(self.folder.name) / "instance"
        self.store = ChannelCursorStore(self.instance)
        self.common = {
            "community": "ws://relay.example",
            "identity": "a" * 16 + "/" + "a" * 64,
            "scope": "channel-fixture",
        }

    def test_fuse_allocates_new_session_and_retires_old(self):
        old = "11111111-1111-4111-8111-111111111111"
        self.store.bind(**self.common, sessionId=old)
        fused = self.store.fuse(**self.common, reason="usd", sessionId=old)
        self.assertNotEqual(fused["session_id"], old)
        self.assertEqual(fused["state"], "fused")
        self.assertEqual(fused["previous_session_id"], old)
        self.assertTrue(self.store.isRetired(self.common["identity"], old))
        self.assertFalse(self.store.isRetired(self.common["identity"], fused["session_id"]))
        self.assertEqual((self.store.path.stat().st_mode & 0o777), 0o600)
        reply = formatFuseReply("usd", old, fused["session_id"])
        self.assertTrue(reply.startswith("【熔断】"))
        self.assertIn(sessionRef(old), reply)
        self.assertIn(sessionRef(fused["session_id"]), reply)
        self.assertNotIn(old, reply)

    def test_corrupt_cursor_fails_closed(self):
        self.instance.mkdir()
        (self.instance / "private").mkdir()
        (self.instance / "private/channel-cursors.json").write_text("not json")
        with self.assertRaisesRegex(ValueError, "invalid channel cursor file"):
            self.store.list()

    def test_fuse_mismatch_does_not_overwrite(self):
        old = "11111111-1111-4111-8111-111111111111"
        self.store.bind(**self.common, sessionId=old)
        with self.assertRaisesRegex(ValueError, "session mismatch"):
            self.store.fuse(**self.common, reason="turns", sessionId="22222222-2222-4222-8222-222222222222")
        self.assertEqual(self.store.resolve(**self.common)["session_id"], old)


class WakeCLITests(Fixture):
    def cli(self, *args, **extra_env):
        import os
        import subprocess
        import sys
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"), **extra_env)
        env.pop("BUZZ_RELAY_URL", None)
        return subprocess.run([sys.executable, "-m", "buzz_team.cli", "--instance", str(self.instance), *args],
                              cwd=self.root, env=env, capture_output=True, text=True, timeout=20)

    def enableWake(self):
        self.config.data["agents"][self.key]["mention_aliases"] = ["agent-one"]
        self.config.data["channel_wake"] = {
            "default": {"require_mention": True, "rotate": {"max_input_tokens": 50}},
            "channels": {"channel-owned": {"single_owner_identity": self.key}},
        }
        self.config.data["policies"]["development"]["production_write"] = True
        self.save()

    def test_wake_decide_and_cursor_cli(self):
        self.enableWake()
        hit = self.cli("wake", "decide", "--identity", self.key, "--channel", "channel-fixture",
                       "--post-ref", "post-cli", "--body", "hi @agent-one")
        self.assertEqual(hit.returncode, 0, hit.stderr)
        self.assertTrue(json.loads(hit.stdout)["allowed"])
        miss = self.cli("wake", "decide", "--identity", self.key, "--channel", "channel-fixture",
                        "--post-ref", "post-cli", "--body", "plain talk")
        self.assertEqual(miss.returncode, 0, miss.stderr)
        self.assertFalse(json.loads(miss.stdout)["allowed"])
        structured = self.cli("wake", "decide", "--identity", self.key, "--channel", "channel-fixture",
                              "--post-ref", "post-cli", "--body", "@agent-one",
                              "--mentions", '["agent-one"]')
        self.assertEqual(structured.returncode, 2)
        self.assertIn("structured mentions unsupported", structured.stderr)
        absent = self.cli("wake", "cursor", "--identity", self.key, "--scope", "channel-fixture")
        self.assertEqual(absent.returncode, 0, absent.stderr)
        self.assertEqual(json.loads(absent.stdout)["state"], "absent")

    def test_launch_gate_before_executor(self):
        self.enableWake()
        missing = self.cli("launch", "executor", "--", "acp", BUZZ_RUNTIME_ID=self.key)
        self.assertEqual(missing.returncode, 2)
        self.assertIn("channel wake context missing", missing.stderr)
        denied = self.cli("launch", "executor", "--", "acp", BUZZ_RUNTIME_ID=self.key,
                          BUZZ_WAKE_SURFACE="stream", BUZZ_WAKE_CHANNEL="channel-fixture",
                          BUZZ_WAKE_POST_REF="post-launch", BUZZ_WAKE_BODY="no mention here")
        self.assertEqual(denied.returncode, 0, denied.stderr)
        payload = json.loads(denied.stderr)
        self.assertFalse(payload["allowed"])
        self.assertEqual(payload["exec_tool_calls"], 0)
        self.assertEqual(denied.stdout.strip(), "")
        allowed = self.cli("launch", "executor", "--", "acp", BUZZ_RUNTIME_ID=self.key,
                           BUZZ_WAKE_SURFACE="stream", BUZZ_WAKE_CHANNEL="channel-fixture",
                           BUZZ_WAKE_POST_REF="post-launch", BUZZ_WAKE_BODY="run @agent-one")
        self.assertEqual(allowed.returncode, 0, allowed.stderr)
        self.assertIn("args", json.loads(allowed.stdout))

    def test_task_path_is_not_rewritten_by_mention_gate(self):
        self.enableWake()
        from buzz_team.sessions import SessionStore
        SessionStore(self.instance).bind(community="ws://localhost:3000", identity=self.key,
                                          scope="channel-1", task_id="task-wake",
                                          workspace=str(self.base / "workspace"),
                                          session_id="11111111-1111-4111-8111-111111111111")
        result = self.cli("launch", "--task", "task-wake", "executor", "--",
                          BUZZ_RUNTIME_ID=self.key)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("args", json.loads(result.stdout))
        self.assertNotIn("channel wake context missing", result.stderr)

    def test_fuse_rotates_immediately_and_blocks_old_session(self):
        self.enableWake()
        old = "11111111-1111-4111-8111-111111111111"
        sent = []
        payload = applyFuse(self.config, identity=self.key, channel="channel-fixture",
                            scope="channel-fixture", reason="input_tokens",
                            postRef="post-fuse", sessionId=old, send=True,
                            sender=lambda config, channel, postRef, text: sent.append(text))
        self.assertEqual(len(sent), 1)
        self.assertIn("【熔断】", sent[0])
        self.assertIn(payload["old_session_ref"], sent[0])
        self.assertIn(payload["session_ref"], sent[0])
        self.assertNotEqual(payload["session_ref"], payload["old_session_ref"])
        cursor = self.cli("wake", "cursor", "--identity", self.key, "--scope", "channel-fixture")
        self.assertEqual(cursor.returncode, 0, cursor.stderr)
        body = json.loads(cursor.stdout)
        self.assertEqual(body["state"], "fused")
        self.assertEqual(body["session_ref"], payload["session_ref"])
        blocked = self.cli("launch", "executor", "--", "acp", BUZZ_RUNTIME_ID=self.key,
                           BUZZ_ACP_SESSION_ID=old, BUZZ_WAKE_SURFACE="stream",
                           BUZZ_WAKE_CHANNEL="channel-fixture", BUZZ_WAKE_POST_REF="post-fuse",
                           BUZZ_WAKE_BODY="@agent-one")
        self.assertEqual(blocked.returncode, 2)
        self.assertIn("refusing fused channel session", blocked.stderr)

    def test_fuse_signal_on_launch_does_not_start_executor(self):
        import os
        from buzz_team.runtime import Runtime
        from buzz_team.wake import ChannelWakeSilent
        self.enableWake()
        old = "aaaaaaaa-1111-4111-8111-111111111111"
        ChannelCursorStore(self.instance).bind(community="ws://localhost:3000", identity=self.key,
                                               scope="channel-fixture", sessionId=old)
        with patch("buzz_team.wake.sendFuseReply") as sender:
            with patch.dict(os.environ, {
                "BUZZ_WAKE_FUSE": "budget_exceeded",
                "BUZZ_WAKE_CHANNEL": "channel-fixture",
                "BUZZ_WAKE_POST_REF": "post-hard-stop",
                "BUZZ_ACP_SESSION_ID": old,
            }):
                with self.assertRaises(ChannelWakeSilent) as raised:
                    Runtime(self.config, self.key).launch("executor", ["acp"])
        payload = raised.exception.payload
        self.assertEqual(payload["exec_tool_calls"], 0)
        self.assertEqual(payload["reason"], "budget_exceeded")
        self.assertNotEqual(payload["session_ref"], payload["old_session_ref"])
        sender.assert_called_once()

    def test_task_hard_stop_sets_fuse_and_lets_wake_consume(self):
        import os
        from buzz_team.context import ContextLedger
        from buzz_team.runtime import Runtime
        from buzz_team.sessions import SessionStore
        from buzz_team.wake import ChannelWakeSilent
        self.enableWake()
        self.config.data["channel_wake"]["default"]["rotate"] = {"max_input_tokens": 50}
        self.save()
        old = "bbbbbbbb-1111-4111-8111-111111111111"
        SessionStore(self.instance).bind(community="ws://localhost:3000", identity=self.key,
                                          scope="channel-fixture", task_id="wake-budget",
                                          workspace=str(self.base / "workspace"), session_id=old)
        ChannelCursorStore(self.instance).bind(community="ws://localhost:3000", identity=self.key,
                                               scope="channel-fixture", sessionId=old)
        ledger = ContextLedger(self.instance, "wake-budget")
        ledger.start(max_input_tokens=1)
        ledger.record(turn_id="turn-1", provider="provider", model="model",
                      values={"input_tokens": 2, "output_tokens": 1})
        with patch("buzz_team.wake.sendFuseReply") as sender:
            with patch.dict(os.environ, {
                "BUZZ_WAKE_SURFACE": "stream",
                "BUZZ_WAKE_CHANNEL": "channel-fixture",
                "BUZZ_WAKE_POST_REF": "post-hard-stop",
                "BUZZ_WAKE_BODY": "@agent-one",
            }, clear=False):
                os.environ.pop("BUZZ_WAKE_FUSE", None)
                with self.assertRaises(ChannelWakeSilent) as raised:
                    Runtime(self.config, self.key).launch("executor", ["acp"], task_id="wake-budget")
                self.assertEqual(os.environ.get("BUZZ_WAKE_FUSE"), "input_tokens")
        payload = raised.exception.payload
        self.assertEqual(payload["reason"], "input_tokens")
        self.assertEqual(payload["exec_tool_calls"], 0)
        sender.assert_called_once()
        self.assertTrue(any(item.get("type") == "budget_gate" for item in ledger.report()["events"]))

    def test_unavailable_usd_hard_stop_sets_fuse(self):
        import os
        from buzz_team.context import ContextLedger
        from buzz_team.runtime import Runtime
        from buzz_team.sessions import SessionStore
        from buzz_team.wake import ChannelWakeSilent
        self.enableWake()
        self.config.data["channel_wake"]["default"]["rotate"] = {"max_usd": 3}
        self.save()
        old = "cccccccc-1111-4111-8111-111111111111"
        SessionStore(self.instance).bind(community="ws://localhost:3000", identity=self.key,
                                          scope="channel-fixture", task_id="wake-usd",
                                          workspace=str(self.base / "workspace"), session_id=old)
        ChannelCursorStore(self.instance).bind(community="ws://localhost:3000", identity=self.key,
                                               scope="channel-fixture", sessionId=old)
        ledger = ContextLedger(self.instance, "wake-usd")
        ledger.start()
        ledger.record(turn_id="turn-1", provider="provider", model="model",
                      values={"input_tokens": 1, "output_tokens": 1})
        with patch("buzz_team.wake.sendFuseReply") as sender:
            with patch.dict(os.environ, {
                "BUZZ_WAKE_SURFACE": "stream",
                "BUZZ_WAKE_CHANNEL": "channel-fixture",
                "BUZZ_WAKE_POST_REF": "post-usd",
                "BUZZ_WAKE_BODY": "@agent-one",
            }, clear=False):
                os.environ.pop("BUZZ_WAKE_FUSE", None)
                with self.assertRaises(ChannelWakeSilent) as raised:
                    Runtime(self.config, self.key).launch("executor", ["acp"], task_id="wake-usd")
                self.assertEqual(os.environ.get("BUZZ_WAKE_FUSE"), "usd")
        self.assertEqual(raised.exception.payload["reason"], "usd")
        sender.assert_called_once()

    def test_wake_payload_is_expanded_before_mention_gate(self):
        self.enableWake()
        denied = self.cli(
            "launch", "executor", "--", "acp", BUZZ_RUNTIME_ID=self.key,
            BUZZ_WAKE_PAYLOAD=json.dumps({
                "surface": "stream",
                "channel": "channel-fixture",
                "post_ref": "post-payload",
                "body": "no mention here",
            }))
        self.assertEqual(denied.returncode, 0, denied.stderr)
        payload = json.loads(denied.stderr)
        self.assertFalse(payload["allowed"])
        self.assertEqual(payload["exec_tool_calls"], 0)


if __name__ == "__main__":
    unittest.main()
