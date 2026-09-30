# #57 周衡 seatbelt 放行 Kairo 必需子目录

依据：Issue #57 L1 评论 5871019270。peng 2026-09-28 21:19（北京时间）授权范围；2026-09-30 13:39 批准该设计并附两项安全措施（见「两项安全措施」）。批准只到开 PR 为止；合入由 peng 手动完成；合入后的生效（重启周衡在本地和元宝两个 relay 上的进程）需要 peng 另行同意，由 Jenny 取得，Hogan 执行。

范围限制：不开放整个 `~/kairo`，不开放 `/private/tmp`；不改另外 8 个席位的 `write_paths`、档位和 prompt；不动 thin-bin pin、runtime/ACP、thin 代码（`src/` 未改），也不改上游 block/buzz。

## 新策略（`zhouheng-seatbelt.json`，sha256 `8b402ff8…0868d`）

只改 `write_paths`，由 `[]` 改为 5 条，其余四个字段逐字不变。thin 把每条路径生成一条 seatbelt `subpath` 例外，并要求路径已经存在（`resolve(strict=True)`）。Kairo 用「写 .tmp 再 `os.replace`」落盘，需要父目录可写，所以只能按目录放行，无法按单个文件放行。

| # | 路径 | 用途（kairo 源码写入点见 L1「证据索引」） |
|---|---|---|
| 1 | `/Users/xupeng/kairo/.kairo` | add：`global-home/.kairo/uploads/`（`--copy`）、`global-home/references/<rid>/manifest.yaml`、`catalog.lock`、`ref-catalog.json`。run：`run.lock`、`run.occupancy.json`，以及 global-home 的 transcript/prose/digest/manifest、`global-home/.kairo/state.json`、`knowledge_review.yaml`、`constitution.yaml`，还有 `notes.jsonl`/`notes.lock` |
| 2 | `/Users/xupeng/kairo/能源梳理/.kairo` | run：topic `state.json`、`history/NNNN/` |
| 3 | `/Users/xupeng/kairo/能源梳理/references` | run：`references/MEETINGS.md` |
| 4 | `/Users/xupeng/kairo/ai-native/.kairo` | 同 2（`150601.m4a` 归 ai-native） |
| 5 | `/Users/xupeng/kairo/ai-native/references` | 同 3 |

参照方维的三条 Kairo 路径，这里只取用途，不取宽度：方维放行的是整个 `/Users/xupeng/kairo`，周衡只放行上面 5 个子目录。5 条路径互不重复、互不嵌套，也不与策略文件或 grok 可执行文件重叠。文件权限保持 0600。JSON 里的「能源梳理」写成 `\u80fd\u6e90\u68b3\u7406` 转义：`json.loads` 结果相同，这样读文件时不依赖进程的 locale。

## 暴露面（供 peng 判断）

放行后周衡可以写入：

- `~/kairo/.kairo` 整体：`global-home/`，包括 1.3G `uploads/`、24M `references/`（所有全局 ref）、**`global-home/constitution.yaml`**、`state.json`、`knowledge_review.yaml`；`ref-catalog.json`、`catalog.lock`、`run.lock`、`kairo-ingest-seen.json`、`kairo-ingest-notified.json`、`tag-rule-252-backup-evidence.json`、`projects/`（2.3M）、`review-work/`（1.4M）。无法再拆细：run 的占用文件和目录索引都在 `.kairo` 下新建或 rename。
- 两个 topic 各自的 `.kairo/` 整体和 `references/` 整体，不只是 `MEETINGS.md`。
- **8787 现役数据**：`kairo serve /Users/xupeng/kairo --port 8787`（pid 76501，kairo-prod venv，9/24 13:39 起）直接服务这份 `~/kairo`。周衡写坏的内容会立刻出现在 8787 服务里。回滚策略只能收回写权限，不能撤销已经写入的内容。
- `.kairo` 下没有 provider 或密钥配置，这类配置在 `~/.config/kairo`，仍然拒写。关键词检索只在 grok 输出文件 `review-work/_grok_stdout.json` 里命中 10 次 `token`，未进一步查看。

仍然拒写（探针已验证）：`~/kairo` 根目录（`glossary.yaml`、`pinned.yaml`、`public-read.json`、其他 19 个 topic）、topic 根目录（`understanding.md`、`constitution.yaml`、`assessment.md`、原始 m4a）、`~/.config/kairo`、`/private/tmp`。另外 `~/.codex`、`~/.buzz` 不在白名单里。

已知降级（L1 待定点 3）：digest 做知识抽取时可能写 `~/kairo/glossary.yaml`，这一步会 EPERM。异常被吞掉，只记入 `knowledge_review.yaml`，run 本身不失败。因此 S2 的「EPERM 0 次」限定为 CLI 输出。

## 与 L1 文字的差异

1. **周衡 prompt 的现役落点改由 Desktop UI 编辑，不由 apply.sh 写 `managed-agents.json`。** L1 原计划让 apply.sh 往两条 system_prompt 插入规则。但 #38 已实测：Desktop 启动 agent 时会重写 `managed-agents.json`（A6），并且可能用内存中的旧值覆盖（A11，未排除）。本单又不能退出 Desktop（退出会丢掉 `KAIRO_PROVIDER` 和 9567 代理变量），所以在 Desktop 运行时直接写文件，改动可能被悄悄覆盖。现做法：
   - `apply.sh --inventory FILE` 只接受副本，或 Desktop 未运行时的现役文件；Desktop 运行时拒绝写现役文件（演练 `14-negatives.txt` 已验证）。
   - 现役由 peng 在 Desktop 里停止周衡后编辑 System prompt，再启动（见落位第 4 步）。
   - `verify.sh --prompt present` 核对两条 system_prompt 各含规则一次。
   - 插入逻辑已在 `managed-agents.json` 副本上演练，两条同时写入；回滚后副本与现役逐字节一致。
2. **规则行的内容**。按调用方转述的 peng 对待定点 4–6 的决定，规则在 L1 那一行的基础上补了三点：用 `$TMPDIR`、禁用 heredoc；kairo 先 `cd ~/kairo/<主题>`；只有 `KAIRO_PROVIDER` 为空时才在命令前加 `KAIRO_PROVIDER=grok`。全文见 `zhouheng-prompt-rule.md`，仓库 `team/prompts/pj.md` 已插入同一行。
3. **插入位置**。现役 prompt 里「## 长任务执行与恢复」出现了两次（现役相对仓库 `pj.md` 已漂移，本单不同步）。规则插在最后一节的最后一条之后，也就是 prompt 的末尾。仓库 `pj.md` 里这一节只出现一次，插在该节末尾。
4. **待定点 1–3 按 L1 默认取**：放行整个 `~/kairo/.kairo`；topic 只开 `.kairo` 和 `references`；接受 glossary 降级。批准原文没有逐条写明，如果 peng 当时另有取舍，请在审查时指出。
5. **写测反例比 L1 多两个**：除了 `~/kairo` 根目录和 `/private/tmp`，还加了两个 topic 根目录和 `~/.config/kairo`；另外用身份目录 `tmp/` 做正向对照。

## 两项安全措施（peng 2026-09-30 13:39）

1. **`docs/issue-57/` 附重启证据。** 现役重启尚未获准，所以本 PR 附的是合入前能取得的全部证据：
   - 逐步写明的重启操作和停止条件（下节）；
   - 当前现役状态的只读快照，按 relay 列出 18 个 buzz-acp（`evidence/rehearsal/03-snapshot-before.txt`）；
   - Desktop 此前做过单席重启、其他席位不受影响的日志证据（`evidence/restart-prior/`）；
   - 在副本上演练过的 apply/verify/rollback 和 seatbelt 探针；
   - 改前 EPERM 证据（`evidence/eperm-before/`）。

   重启后的成功证据要等合入后由 Hogan 按下节补齐。
2. **`verify.sh` 按 relay 核对环境变量和策略；缺 `BUZZ_TEAM_POLICY_PATH` 判 FAIL；回滚点 `9e087351`。**
   - verify 在本地和元宝两个 relay 上各要求恰好一个周衡进程，并逐项核对：`BUZZ_ACP_AGENT_COMMAND`、`BUZZ_TEAM_POLICY_PATH`（及该文件的 sha256）、`KAIRO_PROVIDER`、六个 9567 代理变量，以及经 thin 启动的 grok 子进程（`TMPDIR` 指向身份目录 `tmp/`、`GROK_SANDBOX=off`）。缺值按错值处理，判 FAIL（演练 `14-negatives.txt` 和单测已覆盖）。
   - 回滚点在三处强制：
     - apply 前置检查要求现文件 sha256 = `9e087351…`，否则拒绝；
     - rollback 在替换前后都校验 sha256 = `9e087351…`；
     - `--from-template` 从 `zhouheng-seatbelt.before.json` 重建，该文件逐字节等于 `9e087351…`。

## 文件

| 文件 | 作用 |
|---|---|
| `zhouheng-seatbelt.json` | 新策略全文（sha256 `8b402ff8063fe761af8db1cef4fb5979a8320c097b64de2da53d77408ca0868d`） |
| `zhouheng-seatbelt.before.json` | 回滚点，与现役逐字节一致（sha256 `9e08735172c519e25a44c2ee92479a1fcedd9b031adfbd98c10336b005a13c23`） |
| `zhouheng-prompt-rule.md` | 周衡 prompt 规则行（仓库 `team/prompts/pj.md` 已插入） |
| `apply.sh` | 落位：前置检查（sha = 回滚点、9 份策略、先把新策略放到同目录暂存文件并跑 `_load_policy`），同目录备份（0600）加 `../backups/issue57-<ts>/`，原子替换，再跑一次 `_load_policy`，失败自动回滚；输出 9 份 sha256，另 8 份必须不变。现役需要 `ISSUE57_I_UNDERSTAND_LIVE=yes`，并拒绝所有测试变量 |
| `rollback.sh` | 回滚到 `9e087351`（优先用备份，或 `--from-template`）；替换前后都校验 sha，再跑 `_load_policy` |
| `verify.sh` | 只读核对（见上）；`--save-state`、`--compare-state [--restarted]` 比对重启前后的 pid，并扫描周衡日志里的 thin 启动失败 |
| `snapshot.sh` | 只读快照：按 relay 列出 18 个 buzz-acp 的 pid、启动时间、三个核心变量、六个代理变量、relay 连接状态、grok 子进程，9 份策略 sha256，周衡两条库存行 |
| `probe.sh` | seatbelt 写测：从策略临时副本、用现役 thin 代码生成 profile，逐目录建一个探针文件并立即删除 |
| `rehearse.sh` | Mac 临时副本演练，生成 `evidence/rehearsal/` |
| `issue57.py` | 上述脚本共用的 Python（兼容 3.9）；`precheck` 在现役 thin venv 里运行 |
| `evidence/` | 证据（索引见 `evidence/README.md`） |
| `PR.md` | PR 描述草稿 |

profile 生成方式：`issue57.py precheck` 由 `~/lab/buzz/evidence/f66ef5e-preview/venv/bin/python` 执行，导入的正是现役 `buzz-team-thin` 使用的 `buzz_team.thin`（cb63521 wheel，`thin.py` sha256 `7bbc026d…d180`，与 cb63521 源码一致）。调用 `thin._load_policy(env)` 后取 `thin.command(env, ['agent','stdio'])[2]`，即现役启动器传给 `sandbox-exec -p` 的那段文本，并断言它等于 `thin._profile(roots)`。

## 落位与生效（合入后；Hogan 执行，重启前 Jenny 取得 peng 同意）

原则：只停、启周衡，不退出 Desktop，不 kill 任何进程（Desktop 不会拉起被 kill 的 agent，#38 已实测）。出现任何停止条件，照实报 Jenny，不即兴处理。

0. 准备：`D=~/issue57-$(date +%Y%m%d-%H%M%S); mkdir -m 700 $D; git -C <仓库> archive <合入 SHA> docs/issue-57 | tar -x -C $D; cd $D/docs/issue-57`。确认周衡没有进行中的任务（问 peng 或看周衡最近一次回复）。
1. 改前快照（只读）：`bash snapshot.sh --out $D/state-before.json > $D/01-snapshot-before.txt`，然后 `bash verify.sh --expect old --prompt absent > $D/01-verify-old.txt`，必须是 VERIFY PASS，否则停止。
2. 落位策略：`ISSUE57_I_UNDERSTAND_LIVE=yes bash apply.sh > $D/02-apply.txt 2>&1`，不带 `--inventory`。退出码非 0 就停止；apply 失败时已经自动恢复 `9e087351`。随后 `bash verify.sh --expect new --static-only` 必须 PASS。此时运行中的席位不受影响，thin 只在启动时读策略。
3. **报 Jenny，取得 peng 对重启周衡（本地和元宝各一个进程）的同意。** 未获同意就停在这里：可以用 `rollback.sh` 恢复，也可以保持新文件待后续重启。
4. peng 在 Desktop 里只操作周衡：
   1. 停止周衡；
   2. 在周衡的 System prompt 末尾（最后一条「完成标准是获得退出结果……」之后）另起一行，粘贴 `zhouheng-prompt-rule.md` 的内容，保存；
   3. 启动周衡。

   本地社区、元宝社区各做一次。Hogan 同时看 `ps -p 56568`（本地）和 `ps -p 56430`（元宝）确认旧进程退出，并看 `agents/logs/51fb6cd8…__*.log` 出现 `=== starting 周衡 … ===`。先停再改 prompt，这样即使定义行设置了 `auto_restart_on_config_change` 引发重启，也会用新 prompt 启动。
5. 改后核对（只读）：`bash verify.sh --expect new --prompt present --compare-state $D/state-before.json --restarted > $D/05-verify-new.txt`，必须 PASS。该检查要求：
   - 两个 relay 各有一个**新 pid** 的周衡进程；
   - 环境变量、策略 sha（`8b402ff8…`）、`KAIRO_PROVIDER=grok`、六个 9567 代理变量都正确；
   - 有经 thin 启动的 grok 子进程；
   - 本地 relay 为 ESTABLISHED；
   - 另外 16 个 buzz-acp 的 pid 不变；
   - 周衡日志没有 thin 启动失败；
   - 两条 system_prompt 各含规则一次。

   另跑一次 `bash snapshot.sh > $D/05-snapshot-after.txt`。
6. 现役验收（S1/S2/S4/S3 复测）：
   - peng 在真实会话里请周衡登记 `20260928 140109.m4a`（→ 能源梳理）和 `20260928 150601.m4a`（→ ai-native），各跑一次 `cd ~/kairo/<主题> && kairo run --ref <rid>`；
   - 核对 CLI 输出无 EPERM/PermissionError，`ref-catalog.json` 里有两条 ref，会话 `updates.jsonl` 中写 `/tmp` 的尝试为 0；
   - `cp ~/lab/buzz/policies/zhouheng-seatbelt.json $D/copy.json && bash probe.sh --policy $D/copy.json --workdir $D/probe --out $D/06-probe`，结果必须是 PROBE PASS。
7. 收尾：`rm -rf $D`，先把证据拷走。备份留在 `~/lab/buzz/policies/zhouheng-seatbelt.json.issue57-<ts>.bak` 和 `~/lab/buzz/backups/issue57-<ts>/`。

**停止条件（任一出现：停止，报 Jenny，不 kill、不退出 Desktop、不动其他席位）：**

| # | 现象 | 处理 |
|---|---|---|
| a | 第 4 步启动后 60 秒内，某个 relay 没有新的周衡 buzz-acp（verify「exactly one 周衡」FAIL，或 pid 未变） | 停止，报 Jenny；经同意 peng 可以在 UI 里再点一次启动；仍然不行就执行 R |
| b | 周衡日志出现 `buzz-team-thin: …`，尤其是 `BUZZ_TEAM_POLICY_PATH must be an absolute path`（thin 退出 126），或周衡进程没有 grok 子进程 | 立即执行 R，报 Jenny |
| c | 另外 8 个席位中有 pid 变化，或 buzz-acp 总数不是 18 | 停止，报 Jenny；不去碰那些席位 |
| d | 新周衡进程缺 `BUZZ_TEAM_POLICY_PATH`、`KAIRO_PROVIDER` 或任一 9567 代理变量（缺值即 FAIL） | 停止，报 Jenny；缺 `BUZZ_TEAM_POLICY_PATH` 时执行 R |
| e | 本地 relay 60 秒内没有 ESTABLISHED | 停止，报 Jenny |
| f | system_prompt 规则计数不是 1/1 | 报 Jenny；策略可以保留，prompt 在 UI 里修正 |

**回滚 R：**
1. `ISSUE57_I_UNDERSTAND_LIVE=yes bash rollback.sh`（输出必须是 sha256 `9e087351…`，`_load_policy` 通过）；
2. peng 在 UI 里停止周衡，删除规则行，再启动（两个 relay 各一次）；
3. `bash verify.sh --expect old --prompt absent --compare-state $D/state-before.json --restarted` 必须 PASS。

备份不可用时用 `rollback.sh --from-template`。
