# #61 删除沈予 binding_environment 中 #47 的两个遗留键

依据：Issue #61。只改实例文件 `~/lab/buzz/instance.local.json`，不改 buzz-team 代码（`src/` 未动）。该文件不在仓库里，所以本 PR 只提供落位、核验、回滚脚本和说明。

## 背景

#47 灰度期间，沈予的实例配置里加了两个上游会话变量。灰度候选 `feat/47-canary-thread-sessions` 的 bind 扩展没有合入，所以当前 pin 的 595c0cf `desktop.binding_diff` 只认 `ALLOWED_BINDING_KEYS = {BUZZ_ACP_CONFIG, BUZZ_TASK_ID, BUZZ_TASK_SCOPE, BUZZ_WAKE_*}`，遇到这两个键就抛错，`status`（以及 `bind`）一直失败：

```
$ PYTHONDONTWRITEBYTECODE=1 ~/.local/share/buzz-team/releases/595c0cfe…/bin/python -m buzz_team.cli --instance ~/lab/buzz status
{"ok": false, "error": "unsupported binding environment override"}   # exit=2
```

`bin/buzz` 自 #58 起直接转交官方 CLI，官方 CLI 没有 `status` 子命令。验收用的是上面这条 595c0cf 的 `buzz_team.cli status`。

Issue #61 的只读核实结论：当前 pin 下这两个键唯一的读取方就是 595c0cf 的 `binding_diff`，而它只会拒绝并报错，没有组件真正使用这两个值。沈予活进程（buzz-acp）环境里的 `thread`/`4` 来自 Desktop 自己的存储（identity 行的 `session_policy`，以及 `managed-agents.json` 里沈予定义行的 `env_vars`），和 `instance.local.json` 无关。

## 改什么（只有这一处）

| 项 | 值 |
|---|---|
| 文件 | `/Users/xupeng/lab/buzz/instance.local.json`（0600） |
| 改前 sha256 | `5e372c4da16b6221dc6b959fd170e15bbbbee381d6d8bd9ff443874d26cef3b2` |
| JSON 路径 | `.agents["a558771623f29898/a2fe5d4920dd476e82a17e2cbcab6be525b211e5e3c9a1402a1792436af62587"].binding_environment`（label `沈予`） |
| 删除 | `BUZZ_ACP_SESSION_POLICY` = `"thread"`、`BUZZ_ACP_MAX_TURNS_PER_SESSION` = `"4"` |
| 保留 | 同一对象的 `BUZZ_ACP_CONFIG`；其他 8 个席位和所有顶层字段一个字节都不动 |

现役文件正好是 `jq .` 的输出格式（`jq . 文件` 能逐字节复现，2026-10-01 只读核实），所以 jq 写回后，原始 diff 只有沈予对象里的 3 行删除、1 行新增（`BUZZ_ACP_CONFIG` 行去掉行尾逗号）。

## 授权范围与限制

授权原文（peng 经 Jenny，2026-10-01 00:05，北京时间）见 Issue #61。仅限本项，一次性。

- 只删上面两个键。不碰其他席位、`managed-agents.json`、thin-bin pin、channel_wake、代理、upstream block/buzz、buzz 本身。
- 不重启任何进程，不动 Desktop。沈予活进程的 thread/4 来自 Desktop 存储，删键不影响；回滚同样不需要重启。
- **活机落位的前提（三条都要满足）**：Knox 审查 PASS；peng 手动合入（建议按 `human:required` 处理）；Jenny 宣布 #57 已结束。三条都满足前，任何人都不要在 Mac 上运行 `apply.sh` / `rollback.sh`。
- 执行人：Hogan。

## 文件

| 文件 | 作用 |
|---|---|
| `common.sh` | 共用常量（目标路径、改前 sha256、沈予 key、jq 删除表达式）和函数；由下面三个脚本 source |
| `apply.sh` | 门禁 `ISSUE61_I_UNDERSTAND_LIVE=yes`；校验改前 sha256，不符就退出（exit 3），不动任何文件；备份到 `~/lab/buzz/backups/<ts>-issue61/`（目录 0700，`cp -p`，不放 /tmp）；用 jq 只删这两个键；同目录临时文件 + `mv` 原子替换，保持原 mode；替换前后都用 `jq -S` 断言「结果 == 原文件去掉这两个键」；打印新 sha256，写 `manifest.txt`、`raw.diff`、`jq-S.diff` |
| `rollback.sh` | 同样的门禁；先确认备份文件 sha256 等于改前值，再原子恢复；若现役文件既不是改前值、也不是 apply 写入的值（说明 apply 之后又被改过），默认拒绝（exit 3），需人工确认后加 `ISSUE61_FORCE_ROLLBACK=yes`；替换前把当前文件另存为备份目录下的 `pre-rollback-<ts>.json` |
| `verify.sh` | 只读核验（只写证据目录）。`--expect old|new --evidence DIR [--backup DIR] [--shenyu-pid PID]`，见下文 |
| `rehearse.sh` | 在任意机器上用合成的 `instance.local.json` 演练全部脚本（假 HOME，碰不到现役文件） |

退出码：0 成功；1 verify 有 FAIL；2 门禁/参数/环境问题（未改动）；3 前置条件不符（未改动）；4 断言失败。

`verify.sh` 检查项：

- `--expect old`：sha256 等于改前值；沈予 `BUZZ_ACP_SESSION_POLICY == "thread"`、`BUZZ_ACP_MAX_TURNS_PER_SESSION == "4"`、`BUZZ_ACP_CONFIG` 非空。
- `--expect new`：两个键都不存在；`BUZZ_ACP_CONFIG` 仍在；备份 sha256 等于改前值；`jq -S 现役 == jq -S (备份去掉两个键)`；sha256 等于 manifest 里的 new_sha256；595c0cf status 输出里**没有** `unsupported binding environment override`。
- 两种模式都会只读运行 `PYTHONDONTWRITEBYTECODE=1 ~/.local/share/buzz-team/releases/595c0cfe*/bin/python -m buzz_team.cli --instance ~/lab/buzz status`，记录输出和退出码；记录 `managed-agents.json` 的 sha256（路径取自 `.desktop.managed_agents`）；给了 `--shenyu-pid` 时，只摘取该进程环境里的 `BUZZ_ACP_SESSION_POLICY` / `BUZZ_ACP_MAX_TURNS_PER_SESSION` 两个变量（`ps eww`），不保存其他环境变量。
- 每次运行写入 `DIR/<ts>-verify-<old|new>/`：`summary.txt`、`target.txt`、`shenyu-binding-environment.json`、`status.cmd/out/exit`、`managed-agents.sha256`、`jq-S.diff`（new）、`shenyu-process-env.txt`（给了 pid 时）。

## 落位步骤（Hogan；三条前提都满足后）

在合入后 main 的检出目录执行（下文 `D=<检出目录>/docs/issue-61`）。全程不重启、不动 Desktop。

```bash
D=<检出目录>/docs/issue-61
EVID=~/lab/buzz/evidence/issue-61
mkdir -p "$EVID"

# 0) 找沈予的 buzz-acp pid（Desktop 重启后会变；2026-09-30 为 37915）。
#    只看这两个变量，不保存其他环境变量。环境里带 thread 的通常只有沈予，多于一个时按 Issue #61 的方法人工确认。
for p in $(pgrep -f 'Contents/MacOS/buzz-acp'); do
  ps eww -p "$p" -o command= | tr ' ' '\n' | grep -q '^BUZZ_ACP_SESSION_POLICY=thread$' && echo "$p"
done
PID=<上面确认的 pid>

# 1) 落位前健康检查（S4 基线）
~/lab/buzz/bin/buzz-health > "$EVID/health-before.txt" 2>&1; echo $? > "$EVID/health-before.exit"

# 2) 落位前核验：必须 RESULT PASS (old)；status 预期仍报 unsupported（记录用）
"$D/verify.sh" --expect old --evidence "$EVID" --shenyu-pid "$PID"

# 3) 落位
ISSUE61_I_UNDERSTAND_LIVE=yes "$D/apply.sh" 2>&1 | tee "$EVID/apply.txt"

# 4) 落位后核验：必须 RESULT PASS (new)
"$D/verify.sh" --expect new --evidence "$EVID" --shenyu-pid "$PID"

# 5) 落位后健康检查（S4）：退出码和失败项应与 health-before 一致
~/lab/buzz/bin/buzz-health > "$EVID/health-after.txt" 2>&1; echo $? > "$EVID/health-after.exit"
diff "$EVID/health-before.exit" "$EVID/health-after.exit"
```

第 2 步不是 PASS（比如 sha256 已经不是 `5e372c4d…`）就停，不要执行第 3 步，把证据贴回 Issue #61。第 3 步任何非 0 退出都表示没有改动或需要回滚（看输出提示）。第 4、5 步不通过就按下文回滚。

完成后在 Issue #61 贴：apply 输出（新旧 sha256、备份目录）、两次 verify 的 `summary.txt`、`managed-agents.json` 前后 sha256、沈予进程两个变量、buzz-health 前后退出码。

## 验收标准（与 Issue #61 一致）

- **S1 只删两键**：`verify.sh --expect new` 的 S1 项全部 PASS，`jq-S.diff` 只有沈予对象里这两个键被删（`BUZZ_ACP_CONFIG` 行只少一个逗号）；其他 8 个 `agents.*` 以及 `channel_wake`、`binaries`、`compatibility` 等顶层字段完全相同。
- **S2 status 不再报错**：`status.out` 里没有 `unsupported binding environment override`，返回 `identities: 9`。`bound` 照实记录，不作为失败条件（`bound:false` 是 #58 之后的既有状态）。
- **S3 活机不受影响**：两次 verify 记录的 `managed-agents.json` sha256 相同（2026-10-01 改前为 `ebde4ecb4274bad4dfc1c203750e78810066dc620cd1dbbd260173a48468a7a7`，以落位时的值为准）；沈予进程两个变量落位前后都是 `thread` / `4`；落位导致的重启 0 次。
- **S4 健康检查不退化**：`buzz-health` 落位前后退出码和失败项一致。
- **S5 流程**：Knox PASS、peng 手动合入、Jenny 宣布 #57 结束之后才落位；备份目录和回滚命令写进证据。

## 回滚

不需要重启（没有运行中的进程从 `instance.local.json` 读这两个键）。

```bash
ISSUE61_I_UNDERSTAND_LIVE=yes "$D/rollback.sh" --backup ~/lab/buzz/backups/<ts>-issue61   # 不给 --backup 时取最新的 *-issue61
"$D/verify.sh" --expect old --evidence "$EVID"
```

- 手工备选：`cp -p ~/lab/buzz/backups/<ts>-issue61/instance.local.json ~/lab/buzz/instance.local.json`，然后确认 `shasum -a 256` 回到 `5e372c4da16b6221dc6b959fd170e15bbbbee381d6d8bd9ff443874d26cef3b2`。
- 再备选：在沈予的 `binding_environment` 里加回 `"BUZZ_ACP_SESSION_POLICY": "thread"`、`"BUZZ_ACP_MAX_TURNS_PER_SESSION": "4"`（这样 sha256 不一定回到原值）。

## 演练

```bash
docs/issue-61/rehearse.sh [空目录]
```

在合成实例上跑：否定用例（无门禁、现役路径 sha 不符、现役路径不许覆盖 sha、现役路径不许把备份放 /tmp、错误 sha、符号链接目标）→ verify old → apply → 重复 apply 被拒 → verify new → 回滚否定用例（无门禁、被篡改的备份、apply 后又被改过的目标）→ rollback → verify old → 重复 rollback 为空操作 → 再次 apply。status 一步用仓库里 595c0cfe 的真实 `buzz_team` 源码（`git archive`）。合成文件与现役结构相同：同样的 9 个 identity key、同样的字段和嵌套，无关字段用占位值。

需要 `jq`、`python3`、`git`（Linux 上没有 `lsof` 时用空桩，`desktop_pids` 为空）。

## 与 Issue #61 文字的差异

1. 备份位置由 Issue 里的 `~/lab/buzz/instance.local.json.bak-issue61-<ts>` 改为 `~/lab/buzz/backups/<ts>-issue61/instance.local.json`（按本次派单要求：持久目录，附 manifest 和 diff）。
2. 证据目录用 `~/lab/buzz/evidence/issue-61/`，每次 verify 单独一个 `<ts>-verify-<old|new>/` 子目录。
3. 多了 `rollback.sh` 的漂移保护（apply 之后又被改过就默认拒绝）和 `rehearse.sh`。
