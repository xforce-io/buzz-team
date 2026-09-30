# #58 按 cb63521 用法重做 `~/lab/buzz` 入口

L1：Issue #58 评论 5902016872（r1）与 5902035503（r2，K1–K4）；peng 2026-09-30 12:33（北京时间）批准，6 个待定点均取 (a)。r2 覆盖 r1 的对应段落：签名校验放进 `bin/buzz`，因此 r1 3.1 的「两行 exec」改为「签名校验 + exec」的短脚本（Knox 12:59 定稿）。

## 文件

| 文件 | 作用 |
|---|---|
| `bin/buzz` | 实例 `bin/buzz` 新内容。bash 内建命令 + `/usr/bin/codesign`（绝对路径），无 python、无 release 依赖、不调用 sed 等其他外部命令。用显式 designated requirement 校验官方 CLI（见下「签名校验」），通过后 `exec` 官方 CLI 并原样传参；不通过即拒绝、不 exec、不发送、退出码 3。 |
| `bin/buzz-health` | 实例 `bin/buzz-health`，只读健康检查（见下）。`/usr/bin/python3`（3.9 兼容），不写文件、不连 relay、不需要私钥。 |
| `apply.sh` / `rollback.sh` / `verify.sh` | 落位、回退、核对；`--target DIR` 可指向临时副本。`common.sh` 为共用常量。 |
| `rehearse.sh` | 在 `/tmp` 下临时副本上演练 apply → verify → rollback → verify，并生成 keel-verify 证据。 |
| `selfsigned-negative.sh` | r2 反例：在 `$HOME` 下临时目录建临时钥匙串文件（随机密码，不加入搜索列表、不改信任设置），用 OU=`EYF346PHUG` 的自签代码签名证书重签官方二进制的副本，验证 `bin/buzz` 退出 3、buzz-health 退出 2；结束时删除钥匙串和临时目录。macOS codesign 不能使用该身份时（本机实测如此），可用 `SELFSIGNED_PRESIGNED` 传入在别处用同类证书重签的副本（`evidence/18`）；副本未被重签时跳过判定段。 |
| `instance-readme-line.md` | apply 写入实例 README 的入口说明（替换第 3 行「当前 buzz-team release pin」段）。 |
| `evidence/` | Mac 临时副本演练证据（已脱敏）。 |
| `PR.md` | PR 描述草稿。 |

## 官方 CLI 路径

- `/Applications/Buzz.app/Contents/MacOS/buzz`：Desktop 包 `xyz.block.buzz.app` 的 `externalBin`（上游 `desktop/src-tauri/tauri.conf.json`），每个 Desktop 版本都在同一位置。`~/.local/bin/buzz` 是指向它的软链。
- Desktop 用 `tauri-plugin-updater` 2.10.1 更新（端点 `https://github.com/block/buzz/releases/download/buzz-desktop-latest/latest.json`，包内无 Sparkle）。Tauri 在 macOS 上整体替换 `/Applications/Buzz.app`，路径和软链目标不变；本机自 2026-09-25 以来没有发生过 Desktop 更新，「更新后仍在原位」尚无实测，只有上述依据。更新后 `bin/buzz-health` 会把新的 sha256 和 `CFBundleShortVersionString` 标为「official component updated」，不判失败；不满足下面的 designated requirement 才失败。
- 路径只能用测试变量 `BUZZ58_TEST_OFFICIAL_BUZZ` 覆盖，覆盖后仍要过同一签名校验；apply/rollback 在现役实例上拒绝任何测试变量。

## 签名校验（Knox r2 P2）

`bin/buzz`、`common.sh` 的 `official_signature_ok`（apply 前置检查）和 `bin/buzz-health` 用同一条命令、同一条 requirement 判定：

```sh
/usr/bin/codesign --verify --strict -R '=anchor apple generic and identifier "buzz" and certificate leaf[subject.OU] = "EYF346PHUG"' <官方 CLI>
```

- requirement 以 `=` 开头表示后面是 requirement 文本；`-R` 与参数分开写（`-R '=…'`）。退出码 0 才通过。`anchor apple generic` 要求证书链锚定到 Apple 根证书，`certificate leaf[subject.OU]` 取叶证书的团队 OU，`identifier "buzz"` 约束签名标识。
- `codesign --verify --strict` 不带 `-R` 只证明签名自洽：ad-hoc 重签的副本也返回 0；`codesign -dv` 打印的 TeamIdentifier / Identifier 由签名者自己写入，自签证书只要 OU 写成 `EYF346PHUG` 就能冒充。所以 `-dv` 只用于记录（buzz-health 输出 `team_identifier`、`identifier`），从不参与判定。
- `-R='=…'`（等号紧贴、再以 `=` 开头）在 macOS codesign 上是 requirement 语法错误（rc=1），不要这样写；`-R='…'` 或 `--test-requirement='=…'` 等价可用（`evidence/17`）。
- Mac 实测（`evidence/17`–`19`）：官方二进制 rc=0；ad-hoc 重签、追加 1 字节、OU=`EYF346PHUG` 的自签证书重签三种副本均不满足，`bin/buzz` 退出 3、buzz-health 退出 2。自签副本 `-dv` 自称 TeamIdentifier=`EYF346PHUG`，旧判定（r1）会放行它。
- 这条 requirement 不含官方 DR 里的 Developer ID 两个 OID 条件，所以同一团队的其他 Apple 签发证书（如 Apple Development）签的 `buzz` 也会通过；与 K4「同一发布方签名挡不住」属同一类，已接受。

## `bin/buzz-health`

默认输入：库存 `~/Library/Application Support/xyz.block.buzz.app/agents/managed-agents.json`、策略 `~/lab/buzz/policies`、harness `~/Library/Application Support/xyz.block.buzz.app/custom_harnesses`、doctor `~/.local/share/buzz-team/releases/cb63521aa8572831691e823c4745b34c2bb6a696/bin/buzz-team`、本地 relay `ws://127.0.0.1:3000`（均可用参数覆盖）。输出一份 JSON，退出码 0 通过、2 失败。

1. **doctor**：`buzz-team doctor --inventory <库存> --policies <策略>`，原样收录，要求 `ok:true`。
2. **identities（K1）**：库存中 `agent_command` 或 `agent_command_override` 非空、且 `relay_url` 去掉末尾斜杠后等于本地 relay 的行，运行时现算。其他 relay 的启动行只记录。要求 doctor 的「N launch identities」= 本地 identities + 其他 relay 行，且没有缺 `relay_url` 的启动行。无启动命令的定义行逐行列出（序号、名字）后跳过（K2）。
3. **策略交叉核对**：每个本地身份的生效 `BUZZ_TEAM_POLICY_PATH` 必须是策略目录里存在、doctor 判 pass 的文件，且不同身份不共用。**实现说明**：现役库存把 `env_vars.BUZZ_TEAM_POLICY_PATH` 放在定义行（`slug`），实例行（`persona_id` = 定义行 `slug`）不重复写；生效值取实例行，缺省时取对应定义行。输出里的 `policy_source` 标明取自哪一行。
4. **进程（K3）**：逐个 buzz-acp 进程只读取 `BUZZ_RELAY_URL`、`BUZZ_ACP_AGENT_COMMAND`、`BUZZ_TEAM_POLICY_PATH`（`ps -E` 原始输出在函数内丢弃，`BUZZ_PRIVATE_KEY` 等从不保存或打印）。有效 ACP = relay 为本地、策略等于某本地身份的策略、执行器等于该身份 `custom_harnesses/<runtime>.json` 的 `command`；缺值按错值处理。每个本地身份至少 1 个有效进程才通过。其他 relay（yuanbao）的进程逐个记录，不计数、不告警（peng 9/30 08:53）。
5. **签名（K4）**：与 `bin/buzz` 相同的 `-R` 校验，只有它的退出码决定通过与否；`codesign -dv` 的 TeamIdentifier / Identifier、sha256 和版本只记录。

## 三个 agent-* 入口（S3）

| 入口 | 结论 | 依据 |
|---|---|---|
| `agent-executor` | 保留，仍指向 595c0cfe，弃用 | 只被库存第 14–22 行 `agent_command` 引用（9 处），已被 `runtime` 覆盖；0 个进程使用。清理该字段另开票。 |
| `agent-harness` | 下线，apply 把它移入 `backups/<ts>-issue58/retired/` | 库存 0 处、`custom_harnesses/*.json` 0 处、18/18 个 buzz-acp 的 `BUZZ_ACP_AGENT_COMMAND` 都是 `…/f66ef5e-preview/venv/bin/buzz-team-thin`（证据 `12-agent-harness-retirement.txt`）。仓库里只剩历史文档和 #38 脚本（见下表）。 |
| `agent-worktree` | 保留，仍指向 595c0cfe | 9 席 workspace/AGENTS.md 第 11 行引用；8 个历史会话出现过。下线或改 AGENTS.md 需 peng 另行批准，本票不做。 |

## 调用方迁移清单（S1、S4）

| 调用方 | 现调用 | 结论 / 新调用 |
|---|---|---|
| 9 席 prompt（库存定义行和实例行） | 官方 `buzz messages send`，不经 `bin/buzz`；DM 不带 `--reply-to` 写在 prompt 中 | 不动 |
| 库存第 14–22 行 `agent_command` | `lab/buzz/bin/agent-executor` | 被 `runtime` 覆盖、未执行；字段属 Out，不改 |
| `custom_harnesses/grok.json` | `lab/buzz/bin/grok-acp-wrapper`（文件已不存在） | 无行使用该 runtime，只记录 |
| 9 席 workspace/AGENTS.md 第 11 行 | `agent-worktree <任务名> --repo <仓>` | 入口保留，不改（需 peng 另批） |
| `docs/issue-38/scripts/smoke-real-workflow.sh` 第 20 行 | `PATH=/Users/xupeng/lab/buzz/bin:$PATH` | 按 L1 只登记，随 #38 重写改为官方 CLI；新 `bin/buzz` 仍可用（签名校验后转交官方 CLI） |
| 同上 第 22、38 行 | `BUZZ_BIN` 默认 `/Users/xupeng/lab/buzz/bin/buzz` | 同上；新写法 `BUZZ_BIN=/Applications/Buzz.app/Contents/MacOS/buzz` |
| `docs/issue-38/scripts/common.sh` 第 24–25 行 | `EXEC_WRAP=…/bin/agent-executor`、`HARNESS_WRAP=…/bin/agent-harness`（供 `verify_thin_pin` 检查 046ac43） | 按 L1 只登记。该检查自 595c0cfe 起已不成立（入口不含 046ac43）；`agent-harness` 下线后 #38 重写须删除 `HARNESS_WRAP` |
| `docs/issue-38/scripts/apply.sh` 第 50、181 行，`rollback.sh` 第 77 行 | `PATH=/Users/xupeng/lab/buzz/bin:$PATH` 后调用 `buzz` | 按 L1 只登记；新 `bin/buzz` 仍可用 |
| relay workflow（9 个） | Hogan 2026-09-30 12:58 只读核对生产 relay postgres：无 workflow 引用 `~/lab/buzz/bin/*`，workflow_runs 无 `lab/buzz/bin` | 无调用，无需迁移 |
| launchd / crontab / shell rc / `~/lab` 下脚本 | 0 处 | — |
| 现役进程 | 命令行含 `lab/buzz/bin` 的进程 0 个；buzz-acp 执行器 0 个指向 `lab/buzz/bin/*` | — |
| 历史会话 `updates.jsonl`（3 个提到 `lab/buzz/bin/buzz`） | 周衡一次 `bin/buzz messages get`（只读），沈予 `ls`/`readlink`，裴昭 `strings`；都是会话内一次性操作 | 不是常驻调用方；新 `bin/buzz` 下同样可用 |
| 实例 README 第 3 行 | 描述四个入口指向 595c0cf | apply 替换为 `instance-readme-line.md`，rollback 恢复原文 |

去掉的两项旧功能：sha256 pin（改为签名 designated requirement，sha256 只记录，K4/待定点 2(a)）；DM 去 `--reply-to`（该规则在席位 prompt 中；运维脚本发 DM 时不要带 `--reply-to`）。

## 旧 doctor 的两项 fail（K2 对照）

595c0cfe `health.py`：`classify_desktop_inventory` 把第 11 行（沈予定义行）判为 `inventory_empty_pubkey:11`，因为该行 `env_vars.BUZZ_RUNTIME_ID` 非空且等于实例身份键，`_inventory_definition_only` 因此为假，空 pubkey 被当作启动行。`_read_desktop_proxy_maps` 只要有任何 `inventory_*` fail 就追加 `desktop_inventory` fail（「inventory has instance anomalies」），`selected_rows` 本身没有报错（9 个身份）。所以 `desktop_inventory` 不是独立问题，而是 `inventory_empty_pubkey:11` 的派生项。cb63521 doctor 只看启动命令，跳过该行，两项都消失；沈予那一行的数据没有变化（口径变化，不是修好了）。证据：`evidence/13-old-doctor-contrast.txt`。

## 落位（Hogan 执行，需 peng 批准）

```sh
cd <buzz-team 仓库 @ 合入提交>/docs/issue-58
bash verify.sh --expect old --save-state /tmp/issue58-before.txt
ISSUE58_I_UNDERSTAND_LIVE=yes bash apply.sh
bash verify.sh --expect new --compare-state /tmp/issue58-before.txt
# 回退（一步）：
ISSUE58_I_UNDERSTAND_LIVE=yes bash rollback.sh            # 用 backups/issue58-latest 指向的备份
ISSUE58_I_UNDERSTAND_LIVE=yes bash rollback.sh --from-template   # 备份不可用时按模板重建 595c0cfe 入口；README.md 不恢复，须手动恢复（脚本会打印提示）
bash verify.sh --expect old --compare-state /tmp/issue58-before.txt
```

apply 只写 `bin/buzz`、`bin/buzz-health`、移走 `bin/agent-harness`、改 README 第 3 行，并在 `backups/<ts>-issue58/` 留备份和 `manifest.sha256`。前置检查全部通过才动文件：四个入口必须与 595c0cfe 入口 sha256 一致、官方 CLI 必须满足上面的 designated requirement（`common.sh` 的 `official_signature_ok`，与 `bin/buzz` 同一条 requirement）。`--from-template` 只重建四个入口，不恢复 README.md，须手动恢复（脚本输出里有明确提示）。不重启 Desktop，不读写 `managed-agents.json`，不碰 channel_wake、workflow、代理、colima、:3000、:4500、9 席和 18 个 buzz-acp。rollback 恢复的四个入口必须逐字节等于 595c0cfe 版本（sha256 见 `common.sh`），否则不恢复。Hogan 的 `backups/20260930-verify47-broken/` 是 `/tmp` 版入口（已失效），不作为回退来源。
