# Issue #38 live apply runbook（合入后与 Hogan 一起执行）

**现在不要执行。** 合入门禁 + Knox human:required 通过后，再跑。

## Environment assumptions

Scripts rely on these live facts. Each needs evidence (or is marked PENDING).

**Renumber note (Knox interim 2026-09-24):** former **A8** (other 8 pids unchanged) → **A9**; former **A9** (thin-bin pin) → **A10**. New **A8** = prompt-read timing (announced publicly; Scout #42 refs #41 A8).

| # | Assumption | Evidence |
|---|---|---|
| A1 | Buzz Desktop does **not** auto-respawn an agent ACP after `kill` | Confirmed live 2026-09-24: apply safe-kill of 周衡 pid 81513; 60s wait timed out; Desktop never rewrote a new pid. See `~/lab/buzz/evidence/issue-38-live-reverify/RESULT.md` |
| A2 | `buzz workflows update --yaml` takes **YAML content**, not a file path | Confirmed: path form → relay 400 `expected struct WorkflowDef`; content form (`$(cat ...)`) succeeds. Help text in `docs/issue-38/smoke/buzz-workflows-update-help.txt` |
| A3 | Exact 周衡 pid file is `${PUB}__${TEAM}.json`; other `${PUB}__*.json` are stale and must abort | Hogan live rule (pid-file format) |
| A4 | After Desktop **Start 周衡**, Desktop rewrites the **same** pid file with a **new** pid | **PENDING live evidence** (Hogan observing peng's manual restart) |
| A5 | New ACP process exposes effort/idle in cmdline and/or env (`BUZZ_ACP_EFFORT_LEVEL`, `BUZZ_ACP_IDLE_TIMEOUT`) | **PENDING live evidence** — `verify-after-restart.sh` Mode A prefers this; falls back to A6 |
| A6 | If effort/idle are not visible on the process, `managed-agents.json` 周衡 row values + process start time **after** `backup/config_written_at.txt` are sufficient (code uses `ps -o etimes=`) | Fallback implemented; **PENDING live confirmation**. Knox asked Hogan for raw `ps -o etimes= -p <newpid>` sample |
| A7 | Timing: Desktop click → pid file update → ACP ready for text reply | **PENDING live evidence** |
| A8 | Prompt read timing: Desktop/ACP reads managed `system_prompt`, `pj.md`, workspace `AGENTS.md`, and `instructions-1.md` **only at process start** (not per new session) — why a Desktop restart is required after config write | **PENDING live evidence** (publicly announced A8; Scout #42 refs #41 A8) |
| A9 | Other 8 TEAM seats' pids stay unchanged across apply/rollback/restart of 周衡 only | Confirmed on 2026-09-24 rollback (other 8 unchanged). *(formerly A8)* |
| A10 | Thin wrappers stay on pin `046ac43` (`PIN_FULL`) for this change | Confirmed pre/post 2026-09-24. *(formerly A9)* |
| M1 | `buzz` CLI path `/Users/xupeng/lab/buzz/bin` and `PJ_PRIVATE_KEY` from `~/.local/share/buzz/config/agents.env` | In code: `apply.sh` / `rollback.sh` env bootstrap |
| M2 | `BUZZ_RELAY_URL` default `ws://127.0.0.1:3000` | In code: `apply.sh` export default |
| M3 | `buzz workflows get` returns JSON with `.content` string | In code: apply/rollback python read-back |
| M4 | `ps eww -p` exposes env as `KEY=VAL` whitespace tokens (and contains full PUB) | In code: `common.sh` / `verify-after-restart.sh` |
| M5 | `ps -o etimes=` available on macOS and returns integer seconds (Mode B; avoids `lstart` locale) | In code: `verify-after-restart.sh` Mode B |
| M6 | `managed-agents.json` schema: array of objects with `pubkey`/`name`/`idle_timeout_seconds`/`env_vars`/`agent_args`/`system_prompt`/`max_turn_duration_seconds` | In code: apply row patch / verify Mode B |
| M7 | Desktop loads managed-agents.json + prompt files at ACP **process start** (same family as A8) | Implied by no-kill restart requirement; see A8 PENDING |
| M8 | doctor 9/9 ≡ nine `*__${TEAM}.json` pid files all `kill -0` / `os.kill(pid,0)` alive (apply enforces via `require_all_team_alive`; verify counts live TEAM pids — does not call `buzz_team doctor`) | In code: `common.sh` `require_all_team_alive`; `verify-after-restart.sh` |
| M9 | `config_written_at` format UTC `%Y-%m-%dT%H:%M:%SZ` via `date -u` | In code: `common.sh` `record_config_written_at` |
| M10 | Hardcoded `WF_ID`/`CH_ID`/`PUB`/`TEAM`/paths under Application Support and `lab/buzz` | In code: `common.sh` constants |
| M11 | Pid JSON shape `{"pid": <int>}` | In code: `common.sh` / verify pid reads |

**PENDING for Hogan fill-in after peng's manual 周衡 restart:** A4–A8 (and A6 etimes sample).

## 0. Arrange peng **before** apply

**REQUIRED:** peng must be present at the keyboard **before** you run `apply.sh`, ready to restart **ONLY 周衡** from Buzz Desktop immediately after apply finishes (not the whole app).

Why: apply writes new config to disk but **does not kill**. Until 周衡 is restarted, the running ACP still has the **old** config while files have the **new** config (mixed window). Same rule for rollback.

## 1. Preflight

```bash
cd /Users/xupeng/dev/github/buzz-team
python -m buzz_team --instance /Users/xupeng/lab/buzz doctor   # expect 9/9
# apply enforces doctor 9/9 (all *__TEAM.json pids alive) + 周衡 pubkey-confirmed
```

- thin-bin still `046ac43`
- Scout: no parallel dirty 周衡 edits

## 2. apply (config only — no kill)

```bash
cd /Users/xupeng/dev/github/buzz-team
ISSUE38_I_UNDERSTAND_LIVE=yes docs/issue-38/scripts/apply.sh
```

Script behavior:

1. Guard + thin-pin + exact 周衡 pid file; **require doctor 9/9** (all TEAM pids alive) + 周衡 pubkey-confirmed (else abort: restart first)
2. Assert live workflow == `before/workflow.yaml`
3. Create `evidence/issue-38/backup-<ts>/` (snapshots only)
4. **First** `workflows update --yaml "$(cat after/workflow.yaml)"` + get read-back
5. Only then: patch 周衡 managed-agents row + pj/AGENTS/instructions-1; read-back verify
6. Record `config_written_at.txt` immediately after first successful workflow mutation (refresh after local writes); verify other 8 pids unchanged. ERR/EXIT trap prints BACKUP + rollback command
7. **STOP.** Print backup path, rollback command, and ask peng to restart ONLY 周衡

## 3. peng restarts ONLY 周衡 (Desktop)

Immediately after apply prints the banner: peng → Buzz Desktop → restart **only** 周衡 (do not relaunch the app).

## 4. verify-after-restart

```bash
docs/issue-38/scripts/verify-after-restart.sh \
  /Users/xupeng/lab/buzz/evidence/issue-38/backup-<ts> \
  --expect after
```

Checks: doctor 9/9; 周衡 **new** alive pid containing full pubkey; effort=medium idle=180 max=7200 (process env/cmdline if visible, else managed-agents row + start time after `config_written_at`); other 8 pids unchanged vs backup.

## 5. Hogan S1–S3

Only after verify-after-restart passes.

## 6. Rollback (if needed)

```bash
ISSUE38_I_UNDERSTAND_LIVE=yes docs/issue-38/scripts/rollback.sh \
  /Users/xupeng/lab/buzz/evidence/issue-38/backup-<ts>
```

Restores workflow (compare/skip) + 周衡 row + prompt files; **no kill**. Tolerates dead/stale 周衡 pid. Then:

**REQUIRED:** if 周衡 was restarted with new config, peng restarts 周衡 again from Desktop.

```bash
docs/issue-38/scripts/verify-after-restart.sh \
  /Users/xupeng/lab/buzz/evidence/issue-38/backup-<ts> \
  --expect before
```

Expect effort=low idle=1500.

## Script smoke (no live apply)

```bash
docs/issue-38/scripts/smoke-test.sh
```
