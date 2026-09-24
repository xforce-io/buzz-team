#!/usr/bin/env python3
"""Identity-based TEAM seat process matcher (Issue #38 D1 / A15).

Reads ps-style lines from stdin: ``PID COMMAND...`` (pid=,command= / args=).
Matches only if ALL of:
  1. process is a seat executable: ``buzz_team.cli`` (Python wrapper) OR argv0/path
     is ``buzz-acp`` (not arbitrary command text mentioning those strings);
  2. env/cmdline contains the exact token
     ``BUZZ_RUNTIME_ID=<team_id>/<pubkey>`` for one of the given seat pubkeys
     (team distinguisher; yuanbao / other instances use a different team id prefix);
  3. pid is not in the exclude set (scanner $$ and descendants).

Prints matches as: ``pid\\tpubkey\\tvia`` where via is the matched token form
``BUZZ_RUNTIME_ID=<team_id>/<pubkey>`` (no secret values).
Then prints a final summary line: ``SCAN_OK matches=<n> ps_lines=<m>``.

Exit codes:
  0 = scan ok (matches may be zero; caller require SCAN_OK + ps_lines>0)
  2 = error (bad args / I/O / internal failure)

Used by common.sh and smoke fixtures. Fail-closed: never treat a crash as
"no seats alive".
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
        "--team-id",
        required=True,
        help="Short team id prefix for BUZZ_RUNTIME_ID=<team-id>/<pubkey> "
        "(e.g. a558771623f29898 / ID_TEAM).",
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
    p.add_argument(
        "--report-counts",
        action="store_true",
        help="Also print per-seat count lines: COUNT\\t<pubkey>\\t<n> (after matches, "
        "before SCAN_OK). Used for positive-control / live read-only checks.",
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


def runtime_token(team_id: str, pubkey: str) -> str:
    """Exact env token that identifies this team's seat."""
    return f"BUZZ_RUNTIME_ID={team_id}/{pubkey}"


def match(
    by_pid: Dict[int, str],
    pubkeys: Iterable[str],
    team_id: str,
    exclude: Set[int],
) -> List[Tuple[int, str, str]]:
    pubs = list(pubkeys)
    hits: List[Tuple[int, str, str]] = []
    for pid, cmd in by_pid.items():
        if pid in exclude:
            continue
        if not is_seat_executable(cmd):
            continue
        for pub in pubs:
            token = runtime_token(team_id, pub)
            # Exact token match (whitespace-bounded or start/end); avoid partial prefix hits.
            if re.search(rf"(?:^|\s){re.escape(token)}(?:\s|$)", cmd) or token in cmd.split():
                hits.append((pid, pub, token))
                break
            # ps -E may glue env as KEY=VAL without clean whitespace splits; substring
            # of the exact token is still required (full team_id/pubkey, not pubkey alone).
            if token in cmd:
                hits.append((pid, pub, token))
                break
    return sorted(hits, key=lambda t: (t[1], t[0]))


def main() -> int:
    try:
        args = parse_args()
        team_id = args.team_id.strip()
        if not team_id or "/" in team_id:
            print("seat-identity-scan: --team-id must be a non-empty id without '/'", file=sys.stderr)
            return 2
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
        ps_lines = len(by_pid)

        exclude: Set[int] = set(args.exclude_pid)
        # Always exclude this python process
        exclude.add(os.getpid())
        if args.self_pid:
            exclude.add(args.self_pid)
            exclude |= descendants_of(args.self_pid, pid_to_ppid)
        # Also exclude descendants of any explicitly excluded pid
        for ep in list(exclude):
            exclude |= descendants_of(ep, pid_to_ppid)

        hits = match(by_pid, pubs, team_id, exclude)
        for pid, pub, via in hits:
            print(f"{pid}\t{pub}\t{via}")

        if args.report_counts:
            counts: Dict[str, int] = {p: 0 for p in pubs}
            for _pid, pub, _via in hits:
                counts[pub] = counts.get(pub, 0) + 1
            for pub in pubs:
                print(f"COUNT\t{pub}\t{counts[pub]}")

        print(f"SCAN_OK matches={len(hits)} ps_lines={ps_lines}")
        return 0
    except BrokenPipeError:
        return 2
    except OSError as exc:
        print(f"seat-identity-scan: I/O error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 — fail closed with exit 2
        print(f"seat-identity-scan: error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
