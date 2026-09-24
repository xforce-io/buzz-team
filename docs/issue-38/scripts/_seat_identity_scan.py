#!/usr/bin/env python3
"""Identity-based TEAM seat process matcher (Issue #38 D1 / A15).

Reads ps-style lines from stdin: ``PID COMMAND...`` (pid=,command= / args=).
Matches only if ALL of:
  1. process is a seat executable: ``buzz_team.cli`` (Python wrapper) OR argv0/path
     is ``buzz-acp`` (not arbitrary command text mentioning those strings);
  2. command/env text contains one of the given seat pubkeys;
  3. command/env text contains the team distinguisher
     ``BUZZ_RELAY_URL=<relay>`` (yuanbao duplicates may share pubkeys);
  4. pid is not in the exclude set (scanner $$ and descendants).

Prints matches as: ``pid\\tpubkey\\tvia`` where via is ``env`` and/or ``cmdline``.
Exit 0 always (caller decides abort). Used by common.sh and smoke fixtures.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from typing import Dict, Iterable, List, Set, Tuple


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--relay",
        required=True,
        help="Required BUZZ_RELAY_URL value (team distinguisher), e.g. ws://127.0.0.1:3000",
    )
    p.add_argument(
        "--pubkey",
        action="append",
        default=[],
        help="Seat pubkey (repeatable). Prefer --pubkeys-file for many.",
    )
    p.add_argument(
        "--pubkeys-file",
        default="",
        help="File with one pubkey per line.",
    )
    p.add_argument(
        "--exclude-pid",
        action="append",
        default=[],
        type=int,
        help="Pid to exclude (repeatable). Typically script $$ and descendants.",
    )
    p.add_argument(
        "--self-pid",
        type=int,
        default=0,
        help="If set, also exclude this pid and every descendant found in stdin ppid map.",
    )
    return p.parse_args()


_WRAPPER_RE = re.compile(r"(?:^|[\s/])-m\s+buzz_team\.cli\b|buzz_team\.cli")
# argv0 is first whitespace-separated token; must be the buzz-acp binary itself.
_ACP_ARGV0_RE = re.compile(r"^\S*buzz-acp(?:\s|$)")


def is_seat_executable(command: str) -> bool:
    """True only for the Python wrapper or the buzz-acp binary (argv0/path)."""
    if _WRAPPER_RE.search(command):
        return True
    first = command.split(None, 1)[0] if command.strip() else ""
    if first.endswith("buzz-acp") or first.endswith("/buzz-acp"):
        return True
    # Some ps listings put env immediately after argv0 with no further args.
    if _ACP_ARGV0_RE.match(command.strip()):
        return True
    return False


def load_pubkeys(args: argparse.Namespace) -> List[str]:
    pubs: List[str] = list(args.pubkey)
    if args.pubkeys_file:
        with open(args.pubkeys_file, encoding="utf-8") as fh:
            for line in fh:
                s = line.strip()
                if s and not s.startswith("#"):
                    pubs.append(s)
    # preserve order, unique
    seen: Set[str] = set()
    out: List[str] = []
    for p in pubs:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def parse_ps_lines(text: str) -> Dict[int, str]:
    """Merge pid->command; keep the longest command line per pid (env-rich wins)."""
    by_pid: Dict[int, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = re.match(r"^(\d+)\s+(.*)$", line)
        if not m:
            continue
        pid = int(m.group(1))
        cmd = m.group(2)
        if pid not in by_pid or len(cmd) > len(by_pid[pid]):
            by_pid[pid] = cmd
    return by_pid


def parse_ppid_map(text: str) -> Dict[int, int]:
    """Optional: lines may also be 'pid ppid' — we don't require them.

    Descendants are resolved when stdin includes lines from a separate
    ``ps -o pid=,ppid=`` dump prefixed with 'PPIDMAP ' or when --exclude
    already lists them. For simplicity, common.sh passes all exclude pids.
    """
    return {}


def descendants_of(root: int, pid_to_ppid: Dict[int, int]) -> Set[int]:
    out: Set[int] = set()
    stack = [root]
    while stack:
        cur = stack.pop()
        for pid, ppid in pid_to_ppid.items():
            if ppid == cur and pid not in out:
                out.add(pid)
                stack.append(pid)
    return out


def classify_via(command: str, pubkey: str) -> str:
    """Heuristic: pubkey in a KEY=VALUE token ⇒ env; else cmdline."""
    # BUZZ_RUNTIME_ID=ID/pubkey or GROK_ACP_CWD=.../pubkey/... or bare path
    envish = (
        f"BUZZ_RUNTIME_ID=" in command
        and pubkey in command
        and re.search(rf"BUZZ_RUNTIME_ID=\S*{re.escape(pubkey)}", command)
    ) or (
        re.search(rf"GROK_ACP_CWD=\S*{re.escape(pubkey)}", command) is not None
    ) or (
        re.search(rf"(?:^|\s)[A-Z_][A-Z0-9_]*=\S*{re.escape(pubkey)}", command)
        is not None
    )
    # cmdline path form without KEY=
    cmdlineish = (pubkey in command) and not envish
    # If both path-in-env and also appears elsewhere, still env (observed live).
    if envish and cmdlineish:
        return "env+cmdline"
    if envish:
        return "env"
    if pubkey in command:
        return "cmdline"
    return "unknown"


def match(
    by_pid: Dict[int, str],
    pubkeys: Iterable[str],
    relay: str,
    exclude: Set[int],
) -> List[Tuple[int, str, str]]:
    relay_token = f"BUZZ_RELAY_URL={relay}"
    pubs = list(pubkeys)
    hits: List[Tuple[int, str, str]] = []
    for pid, cmd in by_pid.items():
        if pid in exclude:
            continue
        if not is_seat_executable(cmd):
            continue
        if relay_token not in cmd:
            continue
        for pub in pubs:
            if pub in cmd:
                hits.append((pid, pub, classify_via(cmd, pub)))
                break
    return sorted(hits, key=lambda t: (t[1], t[0]))


def main() -> int:
    args = parse_args()
    pubs = load_pubkeys(args)
    if not pubs:
        print("seat-identity-scan: no pubkeys provided", file=sys.stderr)
        return 2
    raw = sys.stdin.read()
    # Allow an optional PPIDMAP section: lines starting with 'PPIDMAP ' then 'pid ppid'
    ps_body_lines: List[str] = []
    pid_to_ppid: Dict[int, int] = {}
    for line in raw.splitlines():
        if line.startswith("PPIDMAP "):
            rest = line[len("PPIDMAP ") :].strip()
            m = re.match(r"^(\d+)\s+(\d+)$", rest)
            if m:
                pid_to_ppid[int(m.group(1))] = int(m.group(2))
            continue
        ps_body_lines.append(line)
    by_pid = parse_ps_lines("\n".join(ps_body_lines))

    exclude: Set[int] = set(args.exclude_pid)
    # Always exclude this python process
    exclude.add(os.getpid())
    if args.self_pid:
        exclude.add(args.self_pid)
        exclude |= descendants_of(args.self_pid, pid_to_ppid)
    # Also exclude descendants of any explicitly excluded pid
    for ep in list(exclude):
        exclude |= descendants_of(ep, pid_to_ppid)

    for pid, pub, via in match(by_pid, pubs, args.relay, exclude):
        print(f"{pid}\t{pub}\t{via}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
