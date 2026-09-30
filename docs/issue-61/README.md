# #61 删除沈予 binding_environment 中 #47 的两个遗留键

依据：Issue #61。只改实例文件 `~/lab/buzz/instance.local.json`，不改 buzz-team 代码（`src/` 未动）。该文件不在仓库里，所以本 PR 只提供落位、核验、回滚脚本和说明。

## 背景

#47 灰度期间，沈予的实例配置里加了两个上游会话变量。灰度候选 `feat/47-canary-thread-sessions` 的 bind 扩展没有合入，所以当前 pin 的 595c0cf `desktop.binding_diff` 只认 `ALLOWED_BINDING_KEYS = {BUZZ_ACP_CONFIG, BUZZ_TASK_ID, BUZZ_TASK_SCOPE, BUZZ_WAKE_*}`，遇到这两个键就抛错，`status`（以及 `bind`）一直失败：

```
$ PYTHONDONTWRITEBYTECODE=1 ~/.local/share/buzz-team/releases/595c0cfe…/bin/python -m buzz_team.cli --instance ~/lab/buzz status
{"ok": false, "error": "unsupported binding environment override"}   # exit=2
```

`bin/buzz` 自 #58 起直接转交官方 CLI，官方 CLI 没有 `status` 子命令。验收用的是上面这条 595c0cf 的 `buzz_team.cli status`。

## 这两个值由谁读、从哪来（上游核实，block/buzz tag `desktop-v0.5.25` = `c8f73213089cbd5a0f1e675d3193558280d46e10`）

更正 Issue #61 里「当前 pin 下无读取方」的说法：上游 buzz-acp 0.5.25 **会读**这两个变量，但只从**进程环境**读，不读任何文件。

- `BUZZ_ACP_SESSION_POLICY`：clap 参数 `env = "BUZZ_ACP_SESSION_POLICY"`，默认 `channel`（[`crates/buzz-acp/src/config.rs:359-365`](https://github.com/block/buzz/blob/c8f73213089cbd5a0f1e675d3193558280d46e10/crates/buzz-acp/src/config.rs#L359-L365)）。
- `BUZZ_ACP_MAX_TURNS_PER_SESSION`：`env = "BUZZ_ACP_MAX_TURNS_PER_SESSION"`，默认 `0`（关闭主动轮换）（[`config.rs:390-394`](https://github.com/block/buzz/blob/c8f73213089cbd5a0f1e675d3193558280d46e10/crates/buzz-acp/src/config.rs#L390-L394)）。启动时打印一行配置摘要，含 `session_policy=… max_turns_per_session=…`（[`config.rs:1229`](https://github.com/block/buzz/blob/c8f73213089cbd5a0f1e675d3193558280d46e10/crates/buzz-acp/src/config.rs#L1229)）。

沈予活进程里的 thread/4 由 Desktop 按 `managed-agents.json` 注入（2026-10-01 只读核实：该文件 sha256 `ebde4ecb…a7a7`，第 11 行是沈予定义行，`slug=zhufeng-qa`、pubkey 为空；第 17 行是沈予 identity 行，`persona_id=zhufeng-qa`）：

- `thread`：定义行 `session_policy="thread"`。Desktop 启动时解析后硬写入进程环境（[`desktop/src-tauri/src/managed_agents/runtime.rs:783-784`](https://github.com/block/buzz/blob/c8f73213089cbd5a0f1e675d3193558280d46e10/desktop/src-tauri/src/managed_agents/runtime.rs#L783-L784)），写在用户 env 之后；`BUZZ_ACP_SESSION_POLICY` 是保留键（[`reserved_env_keys.rs:65-67`](https://github.com/block/buzz/blob/c8f73213089cbd5a0f1e675d3193558280d46e10/desktop/src-tauri/src/managed_agents/reserved_env_keys.rs#L65-L67)），persona/agent 的用户 env 里即使写了也会被丢弃（[`env_vars.rs:220-235`](https://github.com/block/buzz/blob/c8f73213089cbd5a0f1e675d3193558280d46e10/desktop/src-tauri/src/managed_agents/env_vars.rs#L220-L235)）。
- `4`：定义行 `env_vars.BUZZ_ACP_MAX_TURNS_PER_SESSION="4"`，按 floor→runtime→definition→global→persona→agent 分层后写入进程环境（[`runtime.rs:777-780`](https://github.com/block/buzz/blob/c8f73213089cbd5a0f1e675d3193558280d46e10/desktop/src-tauri/src/managed_agents/runtime.rs#L777-L780)）。

Desktop 从不读 `instance.local.json` / `binding_environment`（官方 `buzz`、`buzz-acp`、`buzz-desktop` 三个二进制 `strings` 里 `binding_environment|instance.local` 均为 0 命中，见 Issue #61）。两者之间唯一的桥是 buzz-team 595c0cf 的 `bind`：`desktop.py:163-185` 的 `binding_diff` 只会把允许的键新增/覆盖进 Desktop 行的 `env_vars`，从不删除；而现在它遇到这两个键直接报错，所以这座桥目前是断的。

结论：删除这两个键不改变沈予的 thread/4，之后沈予重启也仍会是 thread/4（值来自 `managed-agents.json`）。守门的是 S3（`managed-agents.json` sha256 不变、沈予进程两个变量仍是 thread/4）；如果 S3 显示活机值变了，停下并报告 Jenny。注意：删键本身**不会**让沈予重启，所以「重启后仍是 thread/4」目前只有上游源码和二进制 strings 作依据，还没有活机证据，见「落位后观察」。

## 改什么（只有这一处）

| 项 | 值 |
|---|---|
| 文件 | `/Users/xupeng/lab/buzz/instance.local.json`（0600） |
| 改前 sha256 | `5e372c4da16b6221dc6b959fd170e15bbbbee381d6d8bd9ff443874d26cef3b2` |
| JSON 路径 | `.agents["a558771623f29898/a2fe5d4920dd476e82a17e2cbcab6be525b211e5e3c9a1402a1792436af62587"].binding_environment`（label `沈予`） |
| 删除 | `BUZZ_ACP_SESSION_POLICY` = `"thread"`、`BUZZ_ACP_MAX_TURNS_PER_SESSION` = `"4"` |
| 保留 | 同一对象的 `BUZZ_ACP_CONFIG`；其他 8 个席位和所有顶层字段一个字节都不动 |
| 改后预期 sha256 | `0c500b5969693f1611ff6c07f3fb9b4122b0684917a7af01fc37499b9673ff3b`（2026-10-01 Mac 演练对现役副本 apply 的结果；apply 是确定性的） |

现役文件正好是 `jq .` 的输出格式（`jq . 文件` 能逐字节复现，2026-10-01 只读核实），所以 jq 写回后，原始 diff 只有沈予对象里的 3 行删除、1 行新增（`BUZZ_ACP_CONFIG` 行去掉行尾逗号）。

## 授权范围与限制

授权原文（peng 经 Jenny，2026-10-01 00:05，北京时间）见 Issue #61。仅限本项，一次性。

- 只删上面两个键。不碰其他席位、`managed-agents.json`、thin-bin pin、channel_wake、代理、upstream block/buzz、buzz 本身。
- 不重启任何进程，不动 Desktop。沈予活进程的 thread/4 由 Desktop 按 `managed-agents.json` 注入，删键不影响（见上文上游核实）；回滚同样不需要重启。
- **活机落位的前提（三条都要满足）**：Knox 审查 PASS；peng 手动合入（建议按 `human:required` 处理）；Jenny 宣布 #57 已结束。三条都满足前，任何人都不要在 Mac 上运行 `apply.sh` / `rollback.sh`。
- 执行人：Hogan。

## 文件

| 文件 | 作用 |
|---|---|
| `common.sh` | 共用常量（目标路径、改前 sha256、沈予 key、jq 删除表达式）和函数；由下面三个脚本 source |
| `apply.sh` | 门禁 `ISSUE61_I_UNDERSTAND_LIVE=yes`；校验改前 sha256，不符就退出（exit 3），不动任何文件；备份到 `~/lab/buzz/backups/<ts>-issue61/`（目录 0700，`cp -p`，不放 /tmp）；用 jq 只删这两个键；同目录临时文件 + `mv` 原子替换，保持原 mode；替换前后都用 `jq -S` 断言「结果 == 原文件去掉这两个键」；打印新 sha256，写 `manifest.txt`、`raw.diff`、`jq-S.diff` |
| `rollback.sh` | 同样的门禁；先确认备份文件 sha256 等于改前值，再原子恢复；若现役文件既不是改前值、也不是 apply 写入的值（说明 apply 之后又被改过），默认拒绝（exit 3），需人工确认后加 `ISSUE61_FORCE_ROLLBACK=yes`；替换前把当前文件另存为备份目录下的 `pre-rollback-<ts>.json` |
| `verify.sh` | 只读核验（只写证据目录）。`--expect old|new --evidence DIR [--backup DIR] [--shenyu-pid PID]`，见下文 |
| `rehearse.sh` | 演练全部脚本（假 HOME，所有备份都在演练目录内，碰不到现役文件）：默认用合成的 `instance.local.json`；`ISSUE61_REHEARSE_FROM=<现役文件的副本>` 时改用该副本，并追加 L 段：在假 HOME 的现役路径放一份原样副本，不加任何覆盖变量，按现役默认值跑 apply / verify / rollback |

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
echo "$PID" > "$EVID/shenyu-pid-at-landing.txt"   # 供「落位后观察」判断沈予是否已自然重启

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

完成后在 Issue #61 贴：apply 输出（新旧 sha256、备份目录）、两次 verify 的 `summary.txt`、`managed-agents.json` 前后 sha256、沈予进程两个变量、buzz-health 前后退出码、落位时沈予的 pid。

## 落位后观察（Knox P3，非阻塞）

删键本身不会让沈予重启，所以落位当时的 S3 只能证明「现有进程没变」。「沈予重启后仍是 thread/4」要等沈予下一次**自然**重启（Desktop 重启、保存配置触发的 auto restart、Mac 重启等；不要为此主动重启）后再补证据：

1. 落位时已记下沈予 buzz-acp 的 pid（`$EVID/shenyu-pid-at-landing.txt`；2026-09-30 起为 37915）。
2. 发现 pid 变了之后，只读检查：
   - 新进程环境里的两个变量（同落位步骤第 0 步的 `ps eww` 过滤，只摘这两个变量）；
   - 新进程 buzz-acp 启动摘要日志行里的 `session_policy=` 和 `max_turns_per_session=`（上游 `config.rs:1229` 打印的那一行）。
3. 仍是 `thread` / `4`：在 Issue #61 补一条证据评论（新旧 pid、两个变量、日志行、观察时间）。
4. 值变了：**停下并报告 Jenny**，同时只读记录：`managed-agents.json` 的 sha256；沈予定义行（第 11 行，`slug=zhufeng-qa`）和 identity 行（第 17 行）的 `session_policy` 与 `env_vars`（只摘 `BUZZ_ACP_*` 相关键），用来定位真正的来源。Desktop 不读 `binding_environment`，所以把这两个键加回 `instance.local.json` 并不能恢复 thread/4；只有证据指向 #61 本身时才运行 `rollback.sh`。

## 验收标准（与 Issue #61 一致）

- **S1 只删两键**：`verify.sh --expect new` 的 S1 项全部 PASS，`jq-S.diff` 只有沈予对象里这两个键被删（`BUZZ_ACP_CONFIG` 行只少一个逗号）；其他 8 个 `agents.*` 以及 `channel_wake`、`binaries`、`compatibility` 等顶层字段完全相同。
- **S2 status 不再报错**：`status.out` 里没有 `unsupported binding environment override`，返回 `identities: 9`。`bound` 照实记录，不作为失败条件（`bound:false` 是 #58 之后的既有状态）。
- **S3 活机不受影响**：两次 verify 记录的 `managed-agents.json` sha256 相同（2026-10-01 改前为 `ebde4ecb4274bad4dfc1c203750e78810066dc620cd1dbbd260173a48468a7a7`，以落位时的值为准）；沈予进程两个变量落位前后都是 `thread` / `4`；落位导致的重启 0 次。S3 显示活机值变了就停下并报告 Jenny。注意删键本身不会让沈予重启：S3 只覆盖现有进程；「重启后仍是 thread/4」目前只有上游源码和二进制 strings 作依据，没有活机证据，由上面的「落位后观察」补（Knox P3，非阻塞）。
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
- 回滚只恢复文件。沈予的活机值由 `managed-agents.json` 决定，回滚不会改变它；活机值异常时按「落位后观察」第 4 条处理。

## 演练

```bash
docs/issue-61/rehearse.sh [空目录]
```

在合成实例上跑：否定用例（无门禁、现役路径 sha 不符、现役路径不许覆盖 sha、现役路径不许把备份放 /tmp、错误 sha、符号链接目标）→ verify old → apply → 重复 apply 被拒 → verify new → 回滚否定用例（无门禁、被篡改的备份、apply 后又被改过的目标）→ rollback → verify old → 重复 rollback 为空操作 → 再次 apply。status 一步用仓库里 595c0cfe 的真实 `buzz_team` 源码（`git archive`）。合成文件与现役结构相同：同样的 9 个 identity key、同样的字段和嵌套，无关字段用占位值。

需要 `jq`、`python3`、`git`（Linux 上没有 `lsof` 时用空桩，`desktop_pids` 为空）。

在 Mac 上用现役文件的副本、系统 `/bin/bash` 3.2、真实 `lsof` 和 595c0cfe 的 release python 演练（目录模式 700，结束后删除，因为里面有现役文件内容）：

```bash
T=/Users/xupeng/agent-tools/issue61-rehearse-$(date +%Y%m%dT%H%M%S); mkdir -m 700 "$T" "$T/src"
cp -p ~/lab/buzz/instance.local.json "$T/src/live-copy.json"      # 只读现役文件
ISSUE61_REHEARSE_FROM="$T/src/live-copy.json" \
ISSUE61_REHEARSE_PY="$(ls -d ~/.local/share/buzz-team/releases/595c0cfe*/bin/python)" \
  /bin/bash docs/issue-61/rehearse.sh "$T/run"
rm -rf "$T"
```

2026-10-01 01:28（北京时间）结果：GNU bash 3.2.57(1)-release (arm64-apple-darwin25)，**PASS 53 / FAIL 0**（含 L 段：按现役默认值 apply 后新 sha256 为 `0c500b59…3ff3b`，status 返回 `identities: 9`、`bound: false`、10 个 desktop_pids，rollback 回到 `5e372c4d…`）。现役文件前后 sha256 都是 `5e372c4d…`，`managed-agents.json` 前后都是 `ebde4ecb…a7a7`，演练目录已删除。

## 已知限制

- box 演练没有 `lsof`（空桩，`desktop_pids` 为空）；这部分由上面的 Mac 演练覆盖（真实 `lsof`）。
- 沈予的 pid 靠 buzz-acp 进程环境里 `BUZZ_ACP_SESSION_POLICY=thread` 找；匹配多于一个时要人工确认。
- 以后 Desktop 重新同步定义（例如 persona 定义更新后重写 `managed-agents.json`），或者有人做一个把 `binding_environment` 镜像进 Desktop 的 bind，都可能改变沈予的 thread/4，这与 #67 无关；「落位后观察」和 S3 用来区分。

## 与 Issue #61 文字的差异

1. 备份位置由 Issue 里的 `~/lab/buzz/instance.local.json.bak-issue61-<ts>` 改为 `~/lab/buzz/backups/<ts>-issue61/instance.local.json`（按本次派单要求：持久目录，附 manifest 和 diff）。
2. 证据目录用 `~/lab/buzz/evidence/issue-61/`，每次 verify 单独一个 `<ts>-verify-<old|new>/` 子目录。
3. 多了 `rollback.sh` 的漂移保护（apply 之后又被改过就默认拒绝）和 `rehearse.sh`。
4. Issue 里「当前 pin 下无读取方」不准确：上游 buzz-acp 会从进程环境读这两个变量，值由 Desktop 按 `managed-agents.json` 注入，见上文上游核实。结论（可以删、删后沈予仍是 thread/4）不变。
