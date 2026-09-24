# Issue #38 live apply runbook（合入后与 Hogan 一起执行）

**现在不要执行。** 合入门禁 + Knox human:required 通过后，再跑。

## Environment assumptions

Scripts rely on these live facts. Each needs evidence (or is marked PENDING):

| # | Assumption | Evidence |
|---|---|---|
| A1 | Buzz Desktop does **not** auto-respawn an agent ACP after `kill` | Confirmed live 2026-09-24: apply safe-kill of 周衡 pid 81513; 60s wait timed out; Desktop never rewrote a new pid. See `~/lab/buzz/evidence/issue-38-live-reverify/RESULT.md` |
| A2 | `buzz workflows update --yaml` takes **YAML content**, not a file path | Confirmed: path form → relay 400 `expected struct WorkflowDef`; content form (`$(cat ...)`) succeeds. Help text in `docs/issue-38/smoke/buzz-workflows-update-help.txt` |
| A3 | Exact 周衡 pid file is `${PUB}__${TEAM}.json`; other `${PUB}__*.json` are stale and must abort | Hogan live rule (pid-file format) |
| A4 | After Desktop **Start 周衡**, Desktop rewrites the same pid file with a **new** pid | **PENDING live evidence** (Hogan observing peng's manual restart) |
| A5 | New ACP process exposes effort/idle in cmdline and/or env (`BUZZ_ACP_EFFORT_LEVEL`, `BUZZ_ACP_IDLE_TIMEOUT`) | **PENDING live evidence** — `verify-after-restart.sh` prefers this; falls back to A6 |
| A6 | If effort/idle are not visible on the process, `managed-agents.json` 周衡 row values + process start time **after** `backup/config_written_at.txt` are sufficient | Fallback implemented; **PENDING live confirmation** of start-time behavior |
| A7 | Timing: Desktop click → pid file update → ACP ready for text reply | **PENDING live evidence** |
| A8 | Other 8 TEAM seats' pids stay unchanged across apply/rollback/restart of 周衡 only | Confirmed on 2026-09-24 rollback (other 8 unchanged) |
| A9 | Thin wrappers stay on pin `046ac43` (`PIN_FULL`) for this change | Confirmed pre/post 2026-09-24 |

## 0. Arrange peng **before** apply

**REQUIRED:** peng must be present at the keyboard **before** you run `apply.sh`, ready to restart **ONLY 周衡** from Buzz Desktop immediately after apply finishes (not the whole app).

Why: apply writes new config to disk but **does not kill**. Until 周衡 is restarted, the running ACP still has the **old** config while files have the **new** config (mixed window). Same rule for rollback.

## 1. Preflight

```bash
cd /Users/xupeng/dev/github/buzz-team
python -m buzz_team --instance /Users/xupeng/lab/buzz doctor   # expect 9/9
# 周衡 ACP must be alive; apply aborts if pid file points at a dead process
```

- thin-bin still `046ac43`
- Scout: no parallel dirty 周衡 edits

## 2. apply (config only — no kill)

```bash
cd /Users/xupeng/dev/github/buzz-team
ISSUE38_I_UNDERSTAND_LIVE=yes docs/issue-38/scripts/apply.sh
```

Script behavior:

1. Guard + thin-pin + exact 周衡 pid file; **require 周衡 alive** (else abort: restart first)
2. Assert live workflow == `before/workflow.yaml`
3. Create `evidence/issue-38/backup-<ts>/` (snapshots only)
4. **First** `workflows update --yaml "$(cat after/workflow.yaml)"` + get read-back
5. Only then: patch 周衡 managed-agents row + pj/AGENTS/instructions-1; read-back verify
6. Record `config_written_at.txt`; verify other 8 pids unchanged
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
