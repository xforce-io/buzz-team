"""Preserve existing DM/stream reply placement without hardcoded instance paths."""
from __future__ import annotations

import json
import os
import subprocess


def strip_reply_to(args):
    out, skip = [], False
    for arg in args:
        if skip:
            skip = False
        elif arg == "--reply-to":
            skip = True
        elif not arg.startswith("--reply-to="):
            out.append(arg)
    return out


def command_offset(args):
    values = {"--format", "--relay", "--relay-url", "--private-key", "--auth-tag"}
    index = 0
    while index < len(args) and args[index].startswith("-"):
        index += 2 if args[index] in values else 1
    return index


def channel_id(args):
    for index, arg in enumerate(args):
        if arg == "--channel" and index + 1 < len(args):
            return args[index + 1]
        if arg.startswith("--channel="):
            return arg.split("=", 1)[1]
    return None


def rewrite(real: str, args: list[str]) -> list[str]:
    offset = command_offset(args)
    if args[offset:offset + 2] != ["messages", "send"] or not any(
            a == "--reply-to" or a.startswith("--reply-to=") for a in args):
        return args
    channel = channel_id(args)
    if channel is None:
        return args
    prefix, index = [], 0
    while index < offset:
        arg = args[index]
        if arg == "--format":
            index += 2
        elif arg.startswith("--format="):
            index += 1
        else:
            prefix.append(arg)
            index += 1
    try:
        raw = subprocess.check_output([real, *prefix, "channels", "get", "--channel", channel], text=True, timeout=8,
                                      stderr=subprocess.PIPE)
        info = json.loads(raw)
    except (subprocess.SubprocessError, ValueError, OSError) as exc:
        raise ValueError("cannot confirm channel type; message not sent") from exc
    if not isinstance(info, dict):
        raise ValueError("invalid channel metadata; message not sent")
    kind = info.get("channel_type") or info.get("channelType")
    if kind:
        dm = kind == "dm"
    elif isinstance(info.get("name"), str):
        dm = info["name"].strip().upper() == "DM"
    else:
        raise ValueError("missing channel type; message not sent")
    return strip_reply_to(args) if dm else args


def run(config, args):
    real = config.data["binaries"]["buzz"]
    forwarded = rewrite(real, args)
    os.execv(real, [real, *forwarded])
