# #57 证据（已脱敏；所有时间为北京时间）

## `eperm-before/`：改前 EPERM（只读取自现役）

| 文件 | 内容 |
|---|---|
| `session-01a0e741-excerpt.txt` | 周衡会话 `01a0e741…` `updates.jsonl` 中带 EPERM 的工具输出行：9/28 17:05 heredoc 写 `/tmp`、17:06 `mkdir /tmp/memo-id`、17:15 kairo add `PermissionError`（global-home uploads）、18:39 global-home/topic/`/private/tmp` 写测。**9/30 11:18 同一会话再次复现**（登记 `20260929 090208.m4a`） |
| `terminal-excerpts.txt` | Hogan 9/28 保存的 6 份终端日志（`~/lab/buzz/evidence/zhouheng-seatbelt-eperm-20260928/terminal/`），去掉 ANSI，traceback 只保留错误行和调用栈 |
| `write-test.txt`、`policies-sha256.txt`、`profile-from-live-policy.sb` | Hogan `baseline-before/`（9/28 21:20:31）：cb63521 thin 用现役策略生成 profile 后的写测。身份 `tmp/` 可写；global-home、`能源梳理`、`.kairo`、`~/kairo`、`/private/tmp` 全部 EPERM；9 份策略 sha256 |
| `all-seat-write-paths.txt`、`effective-profile.sb` | 9 份策略的 mode 与 `write_paths`；周衡现役 profile |

## `rehearsal/`：Mac 临时副本演练（`rehearse.sh`，2026-09-30 13:49:20–13:49:45）

工作目录 `~/scout57-rehearsal-20260930/run`，用后已删除。apply/rollback 只作用于其中的 `policies/` 和 `managed-agents.json` 副本。`00-meta.txt` 列出了被演练文件的 git blob id，与本分支 `docs/issue-57/` 同名文件逐一相同。`repo_sha` c7a016b 是整理前的本地提交，未推送。

| 文件 | 内容 |
|---|---|
| `02-live-before.txt` / `15-live-after.txt` / `17-live-diff.txt` | 现役 9 份策略 sha256、`managed-agents.json` sha256、18 个 buzz-acp pid；前后 IDENTICAL |
| `03-snapshot-before.txt` / `16-snapshot-after.txt` | **重启前状态快照**（`snapshot.sh`，只读）：按 relay 列出 18 个 buzz-acp 的 pid、启动时间、`BUZZ_ACP_AGENT_COMMAND`、`BUZZ_TEAM_POLICY_PATH`、`KAIRO_PROVIDER`、六个 9567 代理变量、relay 连接状态（本地 9 个 ESTABLISHED :3000；元宝 9 个 CLOSED，日志显示 403 重连中）、grok 子进程；周衡子进程的 `TMPDIR`/`GROK_SANDBOX`；周衡两条库存行的 prompt sha（`e02d8ae1…`，规则计数 0） |
| `04-verify-live-pre-old.txt` | 对现役做只读 `verify.sh --expect old --prompt absent`：VERIFY PASS。本地 56568、元宝 56430 的环境变量和策略（`9e087351`）逐项通过 |
| `05`、`06` → `07-apply.txt` → `08` → `10-rollback.txt` → `11`、`12` | 副本 verify(old) → apply → verify(new, prompt present) → rollback → verify(old)，全部 PASS。回滚后周衡策略 = `9e087351`，与现役逐字节一致；`managed-agents.json` 副本与现役逐字节一致 |
| `09-probe/` | **seatbelt 写测**：`profile.sb`（sha256 `478b02f3…0a80`）由现役 venv 的 `buzz_team.thin.command` 生成（cb63521，`thin.py` sha256 `7bbc026d…`），输入是新策略的临时副本。5/5 新目录建探针、删探针成功，身份 `tmp/` 对照成功；`~/kairo`、`~/kairo/能源梳理`、`~/kairo/ai-native`、`~/.config/kairo`、`/private/tmp` 5/5 EPERM；遗留探针 0 |
| `13-template-rollback.txt` | apply 后用 `rollback.sh --from-template` 回滚 → `9e087351` |
| `14-negatives.txt` | 新策略指向不存在的目录 → apply 拒绝，文件未变；Desktop 运行时 apply 拒绝写现役 `managed-agents.json`；缺 `ISSUE57_I_UNDERSTAND_LIVE` 时拒绝写现役目录；夹具中本地周衡进程缺 `BUZZ_TEAM_POLICY_PATH` → verify FAIL |
| `18-redaction-check.txt` | `PRIVATE_KEY`/`nsec1`/`BUZZ_PRIVATE`/`BUZZ_AUTH_TAG=` 命中 0 |

探针的副作用：5 个放行目录的 mtime 变成了 2026-09-30 13:49（建探针再删掉所致），目录内容没有变化。

## `restart-prior/`：此前的单席重启

`desktop-single-seat-restarts.txt`：
- 9/25 23:24–23:26，Desktop 只停、启了周衡（两个 relay），另外 8 席没有动；
- 9/26 21:25–21:26 是逐席滚动重启，也就是现在这批进程；
- Desktop 主进程环境里有 `KAIRO_PROVIDER=grok` 和六个 9567 代理变量，由它启动的席位进程都继承了这些变量；
- #38 反例：kill 之后 Desktop 不会重新拉起；
- 缺口：日志没有记下是哪一个 UI 操作触发的重启。

## 待合入后补齐（Hogan，按 README「落位与生效」）

`01-snapshot-before.txt`、`01-verify-old.txt`、`02-apply.txt`、`05-verify-new.txt`、`05-snapshot-after.txt`、`06-probe/`，以及 S1/S2/S4 真实会话的核对结果。
