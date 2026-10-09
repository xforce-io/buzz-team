# #63 沙箱写拒绝验收证据（选项 b）

设计门：peng 经 Jenny 于 2026-10-09 批准选项 **(b)**。  
Knox 审 L1 Draft **PASS**（[评论 6073497046](https://github.com/xforce-io/buzz-team/issues/63#issuecomment-6073497046)）；Quill L1（[评论 6073466728](https://github.com/xforce-io/buzz-team/issues/63#issuecomment-6073466728)）。

本目录只固化验收契约。不改 `thin.py` profile、策略、`write_paths`、managed-agents、活机或上游。TMPDIR / R1 / R2 / R3 **未批准**，不在本 PR。

## 受理证据

沙箱写拒绝的受理证据只有：

1. run / 会话日志中的 EPERM（或等价，如 `Operation not permitted` / `PermissionError`）
2. `docs/issue-57/probe.sh` 式 `sandbox-exec` 允许 / 拒绝写测（探针创建并删除成功，或拒绝路径出现 EPERM）

二者对照即可判定拒绝是否发生。`probe.sh` / `verify.sh` 本来就不查统一日志。

## 禁止

**禁止**把「macOS 统一日志里查不到 `sender == "Sandbox"` 的 deny」当作：

- 拒绝未发生的证明；或
- 验收通过 / 失败的依据。

选项 (b) 是验收契约，不是「已证实写拒绝无法进入统一日志」。缺 deny 的**根因仍为未知**（Knox P3）。本文件不猜测 `(with report)`、日志级别、限流或 sender 差异。

## `/usr/bin/log`

在 peng Mac 的 zsh 上，`log` 是 shell 内建命令，不是统一日志工具。若要查统一日志，必须用 `/usr/bin/log`。查不到 deny 仍不得改写上面的受理口径。

## 只读样本索引（不作为再跑义务）

| 样本 | 链接 / 路径 | 说明 |
|---|---|---|
| 秦牧 2026-10-07 | [评论 6035523143](https://github.com/xforce-io/buzz-team/issues/63#issuecomment-6035523143) | EPERM 窗口 `/usr/bin/log show … sender == "Sandbox"` → 0 entries |
| 裴昭 / 卫平 / 韩川 2026-10-08 | [评论 6052358214](https://github.com/xforce-io/buzz-team/issues/63#issuecomment-6052358214) | 同窗口 Sandbox 2 entries、0 deny、0 file-write deny |
| #57 Hogan 续跑 | `~/lab/buzz/evidence/issue57-live-20260930-151341/11-*`、`12-*` | probe PASS、5 次 EPERM；统一日志 0 条写拒绝；同窗可见一条 grok 读拒绝 |

这些样本说明：写拒绝可以在 run 日志 / probe 里出现，同时统一日志可以没有 deny。它们是只读索引，不是活机复跑任务。

## 不在范围

- 不改 `src/buzz_team/thin.py` 的 profile 生成式。
- 不实施 TMPDIR / empty `write_paths` 相关推断，也不实施 R1 / R2 / R3。
- 评论 6052358214 末句「Seats with empty `write_paths` cannot write their own `TMPDIR`」由策略字段 + buzz-acp 环境变量推出，**未经**临时 profile / 临时进程复现，**不是**已证实结论。buzz-acp 环境里的 Darwin `TMPDIR` 也不等于 thin 包装后 grok 子进程的 `TMPDIR`（`command()` 会把子进程 `TMPDIR` 设为 `grok_home.parent/tmp/`）。
- 不活机 apply；不改策略 / prompt / Desktop / `managed-agents.json`。
- 不重判 #57 PASS / FAIL。

若以后另开 (a) 并证实稳定统一日志，再增可选对照；probe + run 日志仍为必要。
