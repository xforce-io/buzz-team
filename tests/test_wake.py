import json
from pathlib import Path
import unittest
from unittest.mock import patch

from buzz_team.config import Config, identity
from buzz_team.wake import (
    ChannelCursorStore, applyFuse, channelWakeConfigured, decideWake,
    extractAliasTokens, formatFuseReply, isExecutionOriented, mentionAck,
    resetMentionAckMemory, resolveMentions, sendMentionAck, sessionRef,
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
        self.assertEqual(mentioned, {"allowed": True, "reason": "mentioned",
                                    "identity": self.key, "pubkey": "a" * 64,
                                    "tokens": ["agent-one"]})
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
        cold = self.cli("launch", "executor", "--", "acp", BUZZ_RUNTIME_ID=self.key)
        self.assertEqual(cold.returncode, 0, cold.stderr)
        self.assertNotIn("channel wake context missing", cold.stderr)
        self.assertIn("args", json.loads(cold.stdout))
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

    def test_configured_cold_start_allows_harness(self):
        self.enableWake()
        self.assertTrue(channelWakeConfigured(self.config))
        harness = self.cli("launch", "harness", "--", "acp", BUZZ_RUNTIME_ID=self.key)
        self.assertEqual(harness.returncode, 0, harness.stderr)
        self.assertNotIn("channel wake context missing", harness.stderr)
        self.assertNotIn("requires task_id", harness.stderr)
        self.assertIn("args", json.loads(harness.stdout))
        self.assertEqual(self.config.data["channel_wake"]["channels"]["channel-owned"]["single_owner_identity"],
                         self.key)
        self.assertEqual(self.config.data["agents"][self.key]["mention_aliases"], ["agent-one"])
        nonStream = self.cli("launch", "harness", "--", "acp", BUZZ_RUNTIME_ID=self.key,
                             BUZZ_WAKE_SURFACE="desktop")
        self.assertEqual(nonStream.returncode, 0, nonStream.stderr)
        self.assertNotIn("channel wake context missing", nonStream.stderr)

    def test_stream_incomplete_wake_context_refuses(self):
        self.enableWake()
        missing = self.cli("launch", "executor", "--", "acp", BUZZ_RUNTIME_ID=self.key,
                           BUZZ_WAKE_SURFACE="stream")
        self.assertEqual(missing.returncode, 2)
        self.assertIn("wake context", missing.stderr)
        partial = self.cli("launch", "executor", "--", "acp", BUZZ_RUNTIME_ID=self.key,
                           BUZZ_WAKE_SURFACE="stream", BUZZ_WAKE_CHANNEL="channel-fixture")
        self.assertEqual(partial.returncode, 2)
        self.assertIn("wake context", partial.stderr)

    def test_fuse_incomplete_context_refuses(self):
        self.enableWake()
        missing = self.cli("launch", "executor", "--", "acp", BUZZ_RUNTIME_ID=self.key,
                           BUZZ_WAKE_FUSE="turns")
        self.assertEqual(missing.returncode, 2)
        self.assertIn("fuse context missing", missing.stderr)
        partial = self.cli("launch", "executor", "--", "acp", BUZZ_RUNTIME_ID=self.key,
                           BUZZ_WAKE_FUSE="turns", BUZZ_WAKE_CHANNEL="channel-fixture")
        self.assertEqual(partial.returncode, 2)
        self.assertIn("fuse context missing", partial.stderr)

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


class TitleBindTests(Fixture):
    def enableTitle(self):
        other = identity("ws://localhost:3000", "b" * 64)
        self.other = other
        self.config.data["agents"][self.key]["mention_aliases"] = ["项目经理"]
        self.config.data["agents"][other] = dict(self.config.agent(self.key), pubkey="b" * 64,
                                                mention_aliases=["agent-two"])
        self.config.data["channel_wake"] = {
            "default": {"require_mention": True, "allow_short_ack": False},
            "channels": {},
        }
        self.save()

    def cli(self, *args, **extra_env):
        import os
        import subprocess
        import sys
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"), **extra_env)
        env.pop("BUZZ_RELAY_URL", None)
        return subprocess.run([sys.executable, "-m", "buzz_team.cli", "--instance", str(self.instance), *args],
                              cwd=self.root, env=env, capture_output=True, text=True, timeout=20)

    def test_title_token_extracts_only_undecorated_form(self):
        self.assertEqual(extractAliasTokens("请 @项目经理 开窗"), ["项目经理"])
        self.assertEqual(extractAliasTokens("请 @「项目经理」 开窗"), ["「项目经理」"])
        self.assertEqual(extractAliasTokens("@项目经理，开窗"), ["项目经理，开窗"])

    def test_resolve_and_decide_bind_title_to_one_pubkey(self):
        self.enableTitle()
        hits = resolveMentions(self.config, body="请 @项目经理 开窗")
        self.assertEqual(hits, {"resolved": [{"token": "项目经理", "identity": self.key,
                                             "pubkey": "a" * 64}]})
        empty = resolveMentions(self.config, body="请 @「项目经理」 开窗")
        self.assertEqual(empty, {"resolved": []})
        comma = resolveMentions(self.config, body="@项目经理，开窗")
        self.assertEqual(comma, {"resolved": []})
        mentioned = decideWake(self.config, identity=self.key, channel="channel-fixture",
                               postRef="post-title", body="请 @项目经理 开窗")
        self.assertEqual(mentioned, {"allowed": True, "reason": "mentioned",
                                    "identity": self.key, "pubkey": "a" * 64,
                                    "tokens": ["项目经理"]})
        other = decideWake(self.config, identity=self.other, channel="channel-fixture",
                           postRef="post-title", body="请 @项目经理 开窗")
        self.assertEqual(other, {"allowed": False, "reason": "not_mentioned"})
        self.assertNotIn("pubkey", other)
        owner = decideWake(self.config, identity=self.key, channel="channel-fixture",
                           postRef="post-title", body="plain discussion")
        self.assertEqual(owner, {"allowed": False, "reason": "not_mentioned"})
        self.assertNotIn("pubkey", owner)

    def test_title_alias_conflict_fails_closed(self):
        other = identity("ws://localhost:3000", "b" * 64)
        self.config.data["agents"][self.key]["mention_aliases"] = ["项目经理"]
        self.config.data["agents"][other] = dict(self.config.agent(self.key), pubkey="b" * 64,
                                                mention_aliases=["项目经理"])
        with self.assertRaisesRegex(ValueError, "mention alias conflict"):
            self.save()

    def test_wake_resolve_cli_outputs_pubkey(self):
        self.enableTitle()
        hit = self.cli("wake", "resolve", "--body", "请 @项目经理 开窗")
        self.assertEqual(hit.returncode, 0, hit.stderr)
        body = json.loads(hit.stdout)
        self.assertEqual(body["resolved"], [{"token": "项目经理", "identity": self.key,
                                            "pubkey": "a" * 64}])
        miss = self.cli("wake", "resolve", "--body", "plain talk")
        self.assertEqual(miss.returncode, 0, miss.stderr)
        self.assertEqual(json.loads(miss.stdout)["resolved"], [])
        structured = self.cli("wake", "resolve", "--body", "@项目经理", "--mentions", '["项目经理"]')
        self.assertEqual(structured.returncode, 2)
        self.assertIn("structured mentions unsupported", structured.stderr)
        decide = self.cli("wake", "decide", "--identity", self.key, "--channel", "channel-fixture",
                          "--post-ref", "post-cli", "--body", "请 @项目经理 开窗")
        self.assertEqual(decide.returncode, 0, decide.stderr)
        payload = json.loads(decide.stdout)
        self.assertEqual(payload["reason"], "mentioned")
        self.assertEqual(payload["pubkey"], "a" * 64)
        self.assertEqual(payload["tokens"], ["项目经理"])
        other = self.cli("wake", "decide", "--identity", self.other, "--channel", "channel-fixture",
                         "--post-ref", "post-cli", "--body", "请 @项目经理 开窗")
        self.assertEqual(other.returncode, 0, other.stderr)
        self.assertEqual(json.loads(other.stdout), {"allowed": False, "reason": "not_mentioned"})


class MentionAckTests(Fixture):
    EVENT = "c" * 64

    def enableTitle(self):
        other = identity("ws://localhost:3000", "b" * 64)
        self.other = other
        self.config.data["agents"][self.key]["mention_aliases"] = ["项目经理"]
        self.config.data["agents"][other] = dict(self.config.agent(self.key), pubkey="b" * 64,
                                                mention_aliases=["agent-two"])
        self.config.data["channel_wake"] = {
            "default": {"require_mention": True, "allow_short_ack": False},
            "channels": {},
        }
        self.config.data["policies"]["development"]["production_write"] = True
        self.save()
        resetMentionAckMemory()

    def cli(self, *args, **extra_env):
        import os
        import subprocess
        import sys
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"), **extra_env)
        env.pop("BUZZ_RELAY_URL", None)
        return subprocess.run([sys.executable, "-m", "buzz_team.cli", "--instance", str(self.instance), *args],
                              cwd=self.root, env=env, capture_output=True, text=True, timeout=20)

    def installRecorder(self):
        import sys
        from buzz_team.instance import digest, write_json
        recorder = self.root / "buzz-recorder"
        log = self.root / "buzz-argv.json"
        recorder.write_text(
            f"#!{sys.executable}\n"
            "import json, sys\n"
            f"from pathlib import Path\n"
            f"Path({str(log)!r}).write_text(json.dumps(sys.argv[1:], ensure_ascii=False))\n"
        )
        recorder.chmod(0o700)
        self.config.data["binaries"]["buzz"] = str(recorder)
        self.config.data["compatibility"]["sha256"]["buzz"] = digest(recorder)
        write_json(self.config.path, self.config.data)
        self.config = Config(self.instance)
        return log

    def test_ack_calls_reactions_add_on_resolve_hit(self):
        self.enableTitle()
        log = self.installRecorder()
        hit = self.cli("wake", "ack", "--identity", self.key, "--post-ref", self.EVENT,
                       "--channel", "channel-fixture", "--body", "请 @项目经理 开窗")
        self.assertEqual(hit.returncode, 0, hit.stderr)
        payload = json.loads(hit.stdout)
        self.assertEqual(payload["reacted"], True)
        self.assertEqual(payload["emoji"], "👀")
        self.assertEqual(payload["event_ref"], sessionRef(self.EVENT))
        self.assertNotIn(self.EVENT, hit.stdout)
        self.assertEqual(json.loads(log.read_text()),
                         ["reactions", "add", "--event", self.EVENT, "--emoji", "👀"])

    def test_ack_refuses_miss_non_hex_and_pin_mismatch(self):
        self.enableTitle()
        log = self.installRecorder()
        miss = self.cli("wake", "ack", "--identity", self.key, "--post-ref", self.EVENT,
                        "--channel", "channel-fixture", "--body", "plain talk")
        self.assertEqual(miss.returncode, 2)
        self.assertIn("mention not resolved", miss.stderr)
        self.assertFalse(log.exists())
        other = self.cli("wake", "ack", "--identity", self.other, "--post-ref", self.EVENT,
                         "--channel", "channel-fixture", "--body", "请 @项目经理 开窗")
        self.assertEqual(other.returncode, 2)
        self.assertIn("mention not resolved", other.stderr)
        self.assertFalse(log.exists())
        badRef = self.cli("wake", "ack", "--identity", self.key, "--post-ref", "post-not-hex",
                          "--body", "请 @项目经理 开窗", "--channel", "channel-fixture")
        self.assertEqual(badRef.returncode, 2)
        self.assertIn("invalid event id", badRef.stderr)
        self.assertFalse(log.exists())
        missingChannel = self.cli("wake", "ack", "--identity", self.key, "--post-ref", self.EVENT,
                                  "--body", "请 @项目经理 开窗")
        self.assertEqual(missingChannel.returncode, 2)
        self.assertIn("channel is required", missingChannel.stderr)
        self.config.data["compatibility"]["sha256"]["buzz"] = "0" * 64
        self.save()
        pin = self.cli("wake", "ack", "--identity", self.key, "--post-ref", self.EVENT)
        self.assertEqual(pin.returncode, 2)
        self.assertIn("pinned baseline", pin.stderr)
        self.assertFalse(log.exists())

    def test_send_mention_ack_rejects_unknown_emoji(self):
        self.enableTitle()
        with self.assertRaisesRegex(ValueError, "unsupported mention ack emoji"):
            sendMentionAck(self.config, self.EVENT, emoji="👍")

    def test_auto_ack_on_allowed_hex_post_ref_and_failure_does_not_deny(self):
        import io
        import os
        from buzz_team.runtime import Runtime
        from buzz_team.wake import ChannelWakeSilent, enforceChannelWake
        self.enableTitle()
        resetMentionAckMemory()
        runtime = Runtime(self.config, self.key)
        env = {
            "BUZZ_WAKE_SURFACE": "stream",
            "BUZZ_WAKE_CHANNEL": "channel-fixture",
            "BUZZ_WAKE_POST_REF": self.EVENT,
            "BUZZ_WAKE_BODY": "请 @项目经理 开窗",
        }
        with patch("buzz_team.wake.sendMentionAck") as ack, patch.dict(os.environ, env):
            extra = enforceChannelWake(runtime, "executor", None)
            ack.assert_called_once_with(self.config, self.EVENT)
            self.assertIsInstance(extra, dict)
            enforceChannelWake(runtime, "executor", None)
            self.assertEqual(ack.call_count, 1)
        resetMentionAckMemory()
        stderr = io.StringIO()
        with patch("buzz_team.wake.sendMentionAck", side_effect=ValueError("buzz executable differs from pinned baseline")):
            with patch("buzz_team.wake.sys.stderr", stderr), patch.dict(os.environ, env):
                extra = enforceChannelWake(runtime, "executor", None)
        self.assertIsInstance(extra, dict)
        failure = json.loads(stderr.getvalue())
        self.assertFalse(failure["reacted"])
        self.assertIn("pinned baseline", failure["error"])
        skipped = io.StringIO()
        with patch("buzz_team.wake.sendMentionAck") as ack, patch("buzz_team.wake.sys.stderr", skipped):
            with patch.dict(os.environ, {**env, "BUZZ_WAKE_POST_REF": "post-not-hex"}):
                extra = enforceChannelWake(runtime, "executor", None)
        ack.assert_not_called()
        self.assertEqual(skipped.getvalue(), "")
        self.assertIsInstance(extra, dict)
        with patch("buzz_team.wake.sendMentionAck") as ack, patch.dict(os.environ, {
            **env, "BUZZ_WAKE_BODY": "plain talk",
        }):
            with self.assertRaises(ChannelWakeSilent):
                enforceChannelWake(runtime, "executor", None)
        ack.assert_not_called()

    def test_mention_ack_without_body_still_requires_hex(self):
        self.enableTitle()
        with patch("buzz_team.wake.subprocess.run") as run:
            payload = mentionAck(self.config, identity=self.key, postRef=self.EVENT)
        run.assert_called_once()
        args = run.call_args[0][0]
        self.assertEqual(args[1:], ["reactions", "add", "--event", self.EVENT, "--emoji", "👀"])
        self.assertEqual(payload["event_ref"], sessionRef(self.EVENT))
        with self.assertRaisesRegex(ValueError, "invalid event id"):
            mentionAck(self.config, identity=self.key, postRef="POST" + "c" * 60)


if __name__ == "__main__":
    unittest.main()
