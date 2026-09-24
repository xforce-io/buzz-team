# Issue #38 live apply runbook（合入后与 Hogan 一起执行）

**现在不要执行。** 合入门禁 + Knox human:required 通过后，再跑。

## Environment assumptions

Scripts rely on these live facts. Each needs evidence (or is marked PENDING).

**Renumber note (Knox interim 2026-09-24):** former **A8** (other 8 pids unchanged) → **A9**; former **A9** (thin-bin pin) → **A10**. New **A8** = prompt-read timing (announced publicly; Scout #42 refs #41 A8). **A11–A13** added after Hogan 2026-09-24 14:54 CST whole-app reopen sample (`~/lab/buzz/evidence/issue-38-live-reverify/zhouheng-restart-20260924/`).

| # | Assumption | Evidence |
|---|---|---|
| A1 | Buzz Desktop does **not** auto-respawn an agent ACP after `kill` | Confirmed live 2026-09-24: apply safe-kill of 周衡 pid 81513; 60s wait timed out; Desktop never rewrote a new pid. See `~/lab/buzz/evidence/issue-38-live-reverify/zhouheng-restart-20260924/` |
| A2 | `buzz workflows update --yaml` takes **YAML content**, not a file path | Confirmed: path form → relay 400 `expected struct WorkflowDef`; content form (`$(cat ...)`) succeeds. Help text in `docs/issue-38/smoke/buzz-workflows-update-help.txt` |
| A3 | Exact 周衡 pid file is `${PUB}__${TEAM}.json`; other `${PUB}__*.json` are stale and must abort | Hogan live rule (pid-file format) |
| A4 | After Desktop start, Desktop rewrites the **same** pid file (`${PUB}__${TEAM}.json`, name unchanged) with a **new** pid | **CONFIRMED** Hogan sample 2026-09-24 14:54 CST (`~/lab/buzz/evidence/issue-38-live-reverify/zhouheng-restart-20260924/`). Note: pid in the file is the Python **wrapper** (周衡 wrapper 836); real `buzz-acp` is its child (853). |
| A5 | New ACP/wrapper process env exposes `BUZZ_ACP_EFFORT_LEVEL`, `BUZZ_ACP_IDLE_TIMEOUT`, `BUZZ_ACP_MAX_TURN_DURATION` matching managed-agents.json | **CONFIRMED** 14:54 sample (post-rollback values): `BUZZ_ACP_EFFORT_LEVEL=low`, `BUZZ_ACP_IDLE_TIMEOUT=1500`, `BUZZ_ACP_MAX_TURN_DURATION=7200`. Mode A requires **all three** visible; otherwise Mode B. |
| A6 | Mode B start-time check: process start **after** apply's `config_written_at` (never managed-agents.json mtime) | **CONFIRMED with correction** (14:54 sample): macOS `ps -o etimes=` errors `etimes: keyword not found`; use `ps -o lstart=` (sample `Thu Sep 24 14:54:38 2026`) and parse with `date -j -f '%a %b %d %T %Y'`. Desktop rewrites `managed-agents.json` on start (`last_started_at`/`updated_at`), so its mtime must **NOT** be used as config-write time — only apply's `config_written_at`. |
| A7 | Timing: Desktop reopen → pid files → ACP ready | **CONFIRMED (timing only)** 14:54 sample: whole-app reopen start 14:54:30, pid files written 14:54:38 (~8s). Agent pool is lazy — init only on first message (14:58:06→14:58:17, ~11s). Ability to reply text **NOT** yet measured (blocked by proxy issue). |
| A8 | Prompt read timing: Desktop/ACP reads managed `system_prompt`, `pj.md`, workspace `AGENTS.md`, and `instructions-1.md` **only at process start** (not per new session) — why a Desktop restart is required after config write | **PENDING** — 14:54 sample cannot distinguish start-only vs per-session read (prompt files restored ~14:03 before 14:54 start). Needs a separate controlled live experiment with separate approval. **Conservative rule:** restart immediately after config write; minimize mixed window. |
| A9 | Other 8 TEAM seats' pids stay unchanged across apply/rollback when using `--restart-mode single` (周衡-only restart) | Confirmed on 2026-09-24 rollback (other 8 unchanged). *(formerly A8)*. Default quit-first flow uses `--restart-mode app` instead (see A12). |
| A10 | Thin wrappers stay on pin `046ac43` (`PIN_FULL`) for this change | Confirmed pre/post 2026-09-24. *(formerly A9)* |
| A11 | On start, Desktop rewrites `managed-agents.json` — does it write back **file** values or **stale in-memory** values? | **PENDING evidence.** Mitigated by quitting Desktop **before** writing (flow below). Post-reopen read-back of 周衡 row is the check. **If overwritten:** STOP, report, do **not** re-apply; run rollback flow. |
| A12 | Restart may be whole-app (Cmd+Q + reopen) rather than single-seat; then all 9 pids change | **CONFIRMED** observed 2026-09-24 14:54 (all 9 pid files rewritten 14:54:38). Default live flow uses `--restart-mode app`. |
| A13 | Desktop process env must inherit a **listening** system proxy; otherwise doctor reports `proxy_contrast` and seats cannot reply | **CONFIRMED problem / fix PENDING peng.** 14:54 relaunch carried `HTTP(S)_PROXY=127.0.0.1:6478` (not listening) vs system `127.0.0.1:9567` → doctor `ok:false` `proxy_contrast`. Source most likely **Dock's stale env** (Dock started 9/9 with 6478): `launchctl getenv` already 9567 at 15:00 yet Desktop got 6478; LaunchAgent `com.user.proxy-env` loaded job still 6478 though plist on disk is 9567. Fix method PENDING peng (options: reload LaunchAgent; `open -a Buzz` with explicit `--env` from terminal; or logout). **Post-reopen gate:** Desktop main process env `HTTP(S)_PROXY` → listening proxy (9567) AND doctor ok with **no** `proxy_contrast`. Do **not** hard-code Dock/Launchpad as the reopen method. |
| A14 | After Cmd+Q, relay `ws://127.0.0.1:3000` stays up | **CONFIRMED (process chain)** by Hogan 2026-09-24 15:36 CST: only listener on `:3000` is pid 76585 `ssh: ~/.colima/_lima/colima/ssh.sock [mux]`, ppid=1 (launchd), started 9/16 22:38; relay runs in colima VM with ssh port-forward, **not** in Desktop (99050) process chain; its start time unchanged across the 14:54 whole-app reopen. Evidence `~/lab/buzz/evidence/issue-38-live-reverify/a14-relay-3000-20260924-1536/`. **Notes:** relay depends on colima running; after logout/reboot colima auto-start **NOT** verified — confirm `:3000` listening before running anything (`lsof -nP -iTCP:3000 -sTCP:LISTEN`; scripts abort via `require_relay_3000_listening`). *Pending sub-note:* a measurement during an actual Cmd+Q window is still to be added by Hogan. |
| A15 | TEAM seat processes are identifiable in `ps -E` by exact env token **`BUZZ_RUNTIME_ID=${ID_TEAM}/<pubkey>`** (not by pid-file kill/`pgrep -P`, and not by pubkey+`BUZZ_RELAY_URL` alone) | **CONFIRMED** read-only observations Quill 2026-09-24 ~15:40 CST and Hogan ~15:45 CST: every seat process env has `BUZZ_RUNTIME_ID=a558771623f29898/<pubkey>` (`ID_TEAM=a558771623f29898`); wrappers (`Python -m buzz_team.cli … launch harness`) and `buzz-acp` children match; executor children like `python -m buzz_team.cli` under buzz-acp also match — **total match count may exceed 18**. Match rule (all required): seat executable (`buzz_team.cli` wrapper OR argv0 `buzz-acp`) AND exact `BUZZ_RUNTIME_ID=${ID_TEAM}/<pubkey>` for one of the 9 seat pubkeys AND not self/descendants. Full `TEAM` hex is **not** present in env/cmdline. Pubkeys are **not** visible in `ps` without `-E`. `BUZZ_RELAY_URL=ws://127.0.0.1:3000` remains a supplementary observation only (not the primary distinguisher). **Positive control:** `--baseline-only` (Desktop UP) requires each of the 9 seat pubkeys has ≥1 match and writes `$BACKUP/seat-scan-positive-control.txt` with a `PASS` marker; mutate/rollback refuse to trust a 0-match scan unless that PASS artifact exists. Scanner/ps failure or empty ps ⇒ abort (fail-closed). |
| M1 | `buzz` CLI path `/Users/xupeng/lab/buzz/bin` and `PJ_PRIVATE_KEY` from `~/.local/share/buzz/config/agents.env` | In code: `apply.sh` / `rollback.sh` env bootstrap |
| M2 | `BUZZ_RELAY_URL` default `ws://127.0.0.1:3000` (stays up across Cmd+Q — see **A14**); mutate/rollback abort if `:3000` not listening | In code: `apply.sh` / `rollback.sh` export default + `require_relay_3000_listening` |
| M3 | `buzz workflows get` returns JSON with `.content` string | In code: apply/rollback python read-back |
| M4 | `ps eww -p` exposes env as `KEY=VAL` whitespace tokens (and contains full PUB) | In code: `common.sh` / `verify-after-restart.sh` |
| M5 | `ps -o lstart=` available; parse with macOS `date -j -f '%a %b %d %T %Y'` (Linux CI: GNU `date -d`). Empty/unparseable ⇒ FAIL (never 0). `etimes` is **not** used | In code: `verify-after-restart.sh` Mode B |
| M6 | `managed-agents.json` schema: array of objects with `pubkey`/`name`/`idle_timeout_seconds`/`env_vars`/`agent_args`/`system_prompt`/`max_turn_duration_seconds` | In code: apply row patch / verify Mode B |
| M7 | Desktop loads managed-agents.json + prompt files at ACP **process start** (same family as A8/A11) | Implied by quit-first + restart requirement; see A8/A11 PENDING |
| M8 | doctor 9/9 ≡ nine `*__${TEAM}.json` pid files all `kill -0` / `os.kill(pid,0)` alive (baseline enforces via `require_all_team_alive`; verify counts live TEAM pids — does not call `buzz_team doctor` for 9/9; proxy_contrast checked via doctor CLI as a RUNBOOK gate) | In code: `common.sh`; RUNBOOK post-reopen gate |
| M9 | `config_written_at` format UTC `%Y-%m-%dT%H:%M:%SZ` via `date -u`. Never use managed-agents.json mtime | In code: `common.sh` `record_config_written_at` |
| M10 | Hardcoded `WF_ID`/`CH_ID`/`PUB`/`TEAM`/paths under Application Support and `lab/buzz` | In code: `common.sh` constants |
| M11 | Pid JSON shape `{"pid": <int>}` (pid = Python wrapper; buzz-acp is child) | In code: `common.sh` / verify pid reads |
| M12 | Mode A only if effort **and** idle **and** max_turn all visible in process env; else Mode B (no partial Mode A) | In code: `verify-after-restart.sh` |
| M13 | `--restart-mode single\|app` is **required** (no auto-guess). `single`: other 8 unchanged+alive, 周衡 new — **only for experiments without Cmd+Q**. `app`: all 9 changed+alive. Quit-first flow **always** uses `app`. Mismatch ⇒ FAIL (single + other seats changed mentions quit-first ⇒ app) | In code: `verify-after-restart.sh` / `common.sh` `verify_restart_pids` |
| M14 | Mutate/rollback require Desktop **not** running (`require_desktop_not_running`; matcher: `Buzz.app/Contents/MacOS` or exact `Buzz`) **and** no TEAM seat still alive by **identity scan** (exact `BUZZ_RUNTIME_ID=${ID_TEAM}/<pubkey>` + `buzz_team.cli`/`buzz-acp` argv0; see **A15**). 0-match trusted only if `$BACKUP/seat-scan-positive-control.txt` has `PASS`. Scanner/ps failure ⇒ abort. **No** pid-file `kill -0` / `pgrep -P`. **No** Desktop-check escape hatch | In code: `common.sh`; documented here |
| M15 | Baseline freshness: `--baseline-only` writes `$BACKUP/baseline_at` (epoch). Mutate rejects missing or age > `BASELINE_MAX_AGE_S=1800`. Mutate also re-asserts live workflow == `before/workflow.yaml` via `buzz` CLI before any write (`assert_live_workflow_matches_before`) | In code: `common.sh` / `apply.sh` |
| M16 | Mutate/rollback require TCP `:3000` LISTEN (`require_relay_3000_listening` / `lsof -nP -iTCP:3000 -sTCP:LISTEN`) before writes — see **A14** | In code: `common.sh` / `apply.sh` / `rollback.sh` |

**PENDING after 14:54 sample:** A8 (prompt-read timing), A11 (MA file vs memory on Desktop rewrite), A13 fix method (peng).

## Operating flow (quit-first — Knox/Jenny 2026-09-24)

Default live path is **whole-app quit → write → reopen**, not single-seat restart. `--restart-mode single` is only for experiments without Cmd+Q; the quit-first flow always uses `app`.

### Apply

1. **Baseline (Desktop UP, seats alive):**
   ```bash
   cd /Users/xupeng/dev/github/buzz-team
   python -m buzz_team --instance /Users/xupeng/lab/buzz doctor   # expect 9/9
   ISSUE38_I_UNDERSTAND_LIVE=yes docs/issue-38/scripts/apply.sh --baseline-only
   ```
   Captures `all-pids-before.tsv`, `zhou-pid-before.txt`, `others-before.tsv`, MA/prompts/workflow snapshots into `evidence/issue-38/backup-<ts>/`. Prints BACKUP path. Does **not** mutate.

2. **peng: Cmd+Q** fully quit Buzz Desktop (all 9 ACP pids go away).

3. **Mutate (Desktop DOWN):**
   ```bash
   ISSUE38_I_UNDERSTAND_LIVE=yes docs/issue-38/scripts/apply.sh --backup /Users/xupeng/lab/buzz/evidence/issue-38/backup-<ts>
   ```
   Aborts unless Desktop is not running **and** no TEAM seat still matches the identity scan (A15 exact `BUZZ_RUNTIME_ID`; positive-control PASS required; no escape hatch), **and** relay `:3000` is listening (A14). Also rejects a backup whose `baseline_at` is missing or older than `BASELINE_MAX_AGE_S` (1800s), and re-asserts live workflow == `before/workflow.yaml` via `buzz workflows get` before any write. Does **not** require seats alive. Writes workflow + 周衡 row + prompt files; records `config_written_at`.

4. **peng reopens** Buzz Desktop using the method peng approved for the **2026-09-24 proxy fix** (see A13). Do **not** assume Dock/Launchpad is safe.

5. **Post-reopen gates (before verify):**
   - Desktop main process env `HTTP(S)_PROXY` points at listening system proxy (`127.0.0.1:9567`).
   - `python -m buzz_team --instance /Users/xupeng/lab/buzz doctor` → ok, **no** `proxy_contrast`.
   - Read back `managed-agents.json` 周衡 row → still `effort=medium` `idle=180` `max_turn=7200` (A11). If overwritten: **STOP**, report, do not re-apply; run rollback flow.

6. **Verify:**
   ```bash
   docs/issue-38/scripts/verify-after-restart.sh \
     /Users/xupeng/lab/buzz/evidence/issue-38/backup-<ts> \
     --expect after --restart-mode app
   ```

7. Hogan S1–S3 only after verify passes.

### Rollback

Same quit-first shape:

1. peng Cmd+Q (if Desktop up).
2. `ISSUE38_I_UNDERSTAND_LIVE=yes docs/issue-38/scripts/rollback.sh --backup <backup-dir>` (requires Desktop down).
3. peng reopens via approved proxy-fix method.
4. Same proxy + doctor + MA read-back gates (expect `effort=low` `idle=1500` `max_turn=7200`).
5. `verify-after-restart.sh <backup> --expect before --restart-mode app`.

### Why quit-first

- Avoids mixed window (old ACP + new files).
- Mitigates A11 (Desktop cannot rewrite MA from stale in-memory values while quit).
- Matches observed whole-app reopen (A12).

## Preflight notes

- thin-bin still `046ac43`
- Scout: no parallel dirty 周衡 edits
- No Desktop-check escape hatch — mutate/rollback always require a full Cmd+Q quit (Desktop main + TEAM seats dead by identity scan — A15)
- Test fixtures are smoke-only and are refused on live runs.
- Relay `:3000` must be listening before mutate/rollback (`require_relay_3000_listening`; A14). After **logout/reboot**, confirm colima/`lsof -nP -iTCP:3000 -sTCP:LISTEN` before running anything (colima auto-start NOT verified)
- Baseline freshness: `baseline_at` (epoch) recorded by `--baseline-only`; mutate rejects missing/older than `BASELINE_MAX_AGE_S=1800` (30 min). Documented in M15.

## Script smoke (no live apply)

```bash
docs/issue-38/scripts/smoke-test.sh
# Live Mac extras: SMOKE_LIVE=1 docs/issue-38/scripts/smoke-test.sh
```
