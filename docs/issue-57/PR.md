# feat(#57): 周衡 seatbelt 放行 5 个 Kairo 必需子目录，临时文件改写 $TMPDIR

冻结 head `2ea50404327bdc9c4a50f89c0662f4f9816d3d35`；CI Tests run 36675648114 success。Refs #57（现役验收完成后关闭）。L1：评论 5871019270。授权：peng 2026-09-28 21:19 划定范围；2026-09-30 13:39 经 Jenny 批准设计（peng 在 Jenny 处给出，原文记录在 Scout 职务说明），附两项安全措施；最终放行为 peng 手动合入。**审查：Knox 按「扩大沙箱写入边界」标 `human:required`；合入由 peng 手动完成。**

**合入前结论最高只能是 `PASS human:required`，现役验收待完成。** 现役验收指：生效后，周衡在真实会话里登记 `20260928 140109.m4a`（→ 能源梳理）、`20260928 150601.m4a`（→ ai-native）和 `20260930 093139.m4a`（→ 能源梳理，标题「刚总沟通」），并完成三次 run，全程无 EPERM。周衡在 9/30 11:18 选择的 `20260929 090208.m4a` 实为「算法例会-260928」，经 Jenny 查 Voice Memos 核实为错误选择，不计入验收；两条 9/28 录音的标题已由 Jenny 核对正确。生效需要重启周衡在本地和元宝上的两个进程，这一步要 peng 另行同意（由 Jenny 取得），由 Hogan 执行。本 PR 没有对现役做任何改动。

## 改动

- `docs/issue-57/zhouheng-seatbelt.json`：周衡新策略，只把 `write_paths` 由 `[]` 改成 5 条：
  - `/Users/xupeng/kairo/.kairo`
  - `/Users/xupeng/kairo/能源梳理/.kairo`
  - `/Users/xupeng/kairo/能源梳理/references`
  - `/Users/xupeng/kairo/ai-native/.kairo`
  - `/Users/xupeng/kairo/ai-native/references`

  每条的用途见 README。不放行整个 `~/kairo`，也不放行 `/private/tmp`；另外 8 份策略不改。
- `team/prompts/pj.md` 与 `docs/issue-57/zhouheng-prompt-rule.md`：「长任务执行与恢复」一节末尾加一行规则：
  - 临时文件只写 `$TMPDIR`，不写 `/tmp`、`/private/tmp`；
  - 不用 heredoc；
  - kairo 先 `cd ~/kairo/<主题>`；
  - `KAIRO_PROVIDER` 为空时才在命令前加 `KAIRO_PROVIDER=grok`。
- `docs/issue-57/{apply,rollback,verify,snapshot,probe,rehearse}.sh`、`common.sh`、`issue57.py`：落位、回滚（到 `9e087351`）、按 relay 只读核对、状态快照、seatbelt 写测、临时副本演练。都支持 `--target`；现役需要 `ISSUE57_I_UNDERSTAND_LIVE=yes`，并拒绝所有测试变量。
- `docs/issue-57/README.md`：暴露面、与 L1 的差异、落位与生效步骤、停止条件、回滚。`docs/issue-57/evidence/`：证据。
- `tests/test_issue57_policy.py`：16 项测试，覆盖策略内容、`thin._load_policy`/profile、规则插入、apply/verify/rollback 往返、拒绝路径、按 relay 缺值判 FAIL、重启前后 pid 比对、126 日志检测。
- 功能地图：`.agents/skills/verify-buzz-team/features/zhouheng-kairo-write.md`，README 加一行。
- 不改 `src/`、thin-bin pin、runtime/ACP、上游组件，也不碰 `docs/issue-58/`。

## 两项安全措施怎么落实

1. **`docs/issue-57/` 附重启证据**：
   - 具体重启操作：只在 Desktop 里停、启周衡，不 kill、不退出 Desktop，停止条件 a–f 触发时报 Jenny；
   - 重启前状态快照（18 个 buzz-acp，按 relay 列出 pid、三个核心变量、六个 9567 代理变量、relay 连接状态）；
   - 此前单席重启的日志证据；
   - 副本演练和 seatbelt 写测；
   - 改前 EPERM 证据。

   重启后的证据要等合入后补齐，清单见 `evidence/README.md` 末节。
2. **`verify.sh` 按 relay 核对环境变量和策略**：本地、元宝各要求恰好一个周衡进程；`BUZZ_ACP_AGENT_COMMAND`、`BUZZ_TEAM_POLICY_PATH` 及其文件 sha256、`KAIRO_PROVIDER`、六个代理变量、经 thin 启动的 grok 子进程逐项核对。**缺值即 FAIL**。回滚点 `9e08735172c5…3c23` 由三处保证：apply 前置检查、rollback 替换前后的 sha 校验、`--from-template`。

## 与 L1 文字的差异（详见 README）

1. 现役周衡 prompt 由 peng 在 Desktop UI 里修改，apply.sh 不在 Desktop 运行时写 `managed-agents.json`。原因是 #38 的 A6/A11：Desktop 启动 agent 时会重写该文件，可能覆盖外部改动；本单又不能退出 Desktop。插入逻辑已在库存副本上演练。
2. 规则行按转述的 peng 对待定点 4–6 的决定补充了内容。
3. 现役 prompt 中「长任务执行与恢复」出现两次，规则插在最后一处的末尾。
4. 待定点 1–3 按 L1 默认取值。
5. 写测反例多了 topic 根目录和 `~/.config/kairo`。

## 待定点逐条取值与依据

- 待定点 1：取 L1 默认——放行整个 `~/kairo/.kairo`。依据：13:39 批准由 peng 在 Jenny 处给出，未逐条列明，按 L1 默认；**待 peng 合入时明确确认**。
- 待定点 2：取 L1 默认——topic 只开 `.kairo` 和 `references`。依据：13:39 批准由 peng 在 Jenny 处给出，未逐条列明，按 L1 默认；**待 peng 合入时明确确认**。
- 待定点 3：取 L1 默认——接受 glossary 降级。依据：13:39 批准由 peng 在 Jenny 处给出，未逐条列明，按 L1 默认；**待 peng 合入时明确确认**。
- 待定点 4：取现有规则行的决定——临时文件只写 `$TMPDIR`，不写 `/tmp`、`/private/tmp`，且不用 heredoc。依据：现有 README/PR 仅记为调用方经 Jenny 转述的 peng 对待定点 4–6 的决定，未逐点记录，待 peng 确认。
- 待定点 5：取现有规则行的决定——kairo 先 `cd ~/kairo/<主题>`。依据：现有 README/PR 仅记为调用方经 Jenny 转述的 peng 对待定点 4–6 的决定，未逐点记录，待 peng 确认。
- 待定点 6：取现有规则行的决定——仅在 `KAIRO_PROVIDER` 为空时才在命令前加 `KAIRO_PROVIDER=grok`。依据：现有 README/PR 仅记为调用方经 Jenny 转述的 peng 对待定点 4–6 的决定，未逐点记录，待 peng 确认。

**合入时请 peng 明确确认**
- (a) 待定点 1 放开 `~/kairo/.kairo` 即放开整个 global-home，含 1.3G uploads、其他全局 ref、constitution.yaml、projects/、review-work/。
- (b) 这些内容由 8787 的 `kairo serve`（pid 76501）直接对外提供，写坏立即可见——L1 未写。
- (c) 回滚只收回写权限，收不回已写入内容——L1 未写。

## r2 修订（Knox @f97b16e）

- **P2 落位顺序**：Hogan 已在房间同意新顺序；先由 Jenny 取得 peng 对重启的同意，再在同一获准窗口内 apply、立即由 Desktop 停/启周衡、双 relay verify、probe 和现役验收。未获同意、窗口中止或任一验收失败，都立即 rollback 并确认 sha256 回到 `9e087351`，不把新文件留给后续重启。
- 原因：周衡定义行有 `auto_restart_on_config_change=true`；若新策略留在现役目录，保存配置、Desktop 重启或 Mac 重启都可能绕过同意门槛而激活它。
- **Knox P3 已知项（本轮不改，以保持 rehearsal blob ids 对齐）**：`apply.sh` 在最后“另外 8 份策略 sha”检查退出非 0 时不会自动恢复周衡策略文件，操作者必须立即运行 `rollback.sh` 并确认 `9e087351`；`rollback.sh` 使用裸 `sed`，运行时应确保 PATH 中 `/usr/bin` 优先（或显式记录这一点）。

## 验收表

新跑，均在冻结候选的干净树上：单测在 box 上跑，Mac 演练用的是同一批 blob。

```
S1: pending-live  README 第 6 步（真实会话登记三条录音）  合入前代理证据：09-probe 中 ~/kairo/.kairo（global-home/uploads 所在目录）在新 profile 下可写
S2: pending-live  README 第 6 步（三条录音各跑一次 run：能源梳理两次、ai-native一次）  合入前代理证据：09-probe 中两个 topic 的 .kairo 和 references 可写
S3: pass          bash docs/issue-57/rehearse.sh（Mac 临时副本）+ python -m unittest tests.test_issue57_policy  profile 由现役 venv 的 buzz_team.thin.command 生成（cb63521，profile sha256 478b02f3…）；5/5 新目录建探针、删探针成功；~/kairo、两个 topic 根目录、~/.config/kairo、/private/tmp 5/5 EPERM；遗留探针 0；另外 8 份 sha256 = baseline-before，演练前后现役 IDENTICAL；_load_policy 通过。生效后需对现役文件副本再跑一次 probe.sh
S4: pass / pending-live  tests.test_issue57_policy（pj.md 含规则一次，覆盖 $TMPDIR/heredoc/cd/KAIRO_PROVIDER）+ 副本 verify --prompt present（两条库存行各一次）  真实会话中写 /tmp 次数为 0 待生效后核对
S5: pass / pending-live  docs/issue-57/README.md + rehearse.sh  落位、备份、预检、回滚、停止条件都写明；副本 apply→verify→rollback→verify 全部 PASS，回滚后 sha256 = 9e087351，与现役逐字节一致；--from-template 也回到 9e087351；各拒绝路径生效；现役 verify --expect old PASS。「重启前由 Jenny 取得 peng 同意」和重启本身待合入后执行
#53/#48 回归: pass  python -m unittest discover -s tests -v  既有 thin/doctor 测试全部通过（src 未改）
```

## keel-verify（功能地图 `zhouheng-kairo-write.md`）

| Story | 入口 | 结果 | 证据 |
|---|---|---|---|
| S1 | 周衡真实会话 | pending-live | 生效后补 |
| S2 | 周衡真实会话 | pending-live | 生效后补 |
| S3 | `probe.sh`（策略临时副本，现役 thin 代码）+ `verify.sh` | pass（合入前） | `evidence/rehearsal/09-probe/`、`04`、`17-live-diff.txt` |
| S4 | `verify.sh --prompt present`（副本）+ 单测 | pass（文本）/ pending-live（会话） | `evidence/rehearsal/08-verify-copy-1-new.txt` |
| S5 | `rehearse.sh` | pass（演练）/ pending-live（重启） | `evidence/rehearsal/07`、`10`–`14` |

## 改前证据

- 周衡会话 `01a0e741…`：9/28 17:05–18:39 heredoc、`/tmp/memo-id`、global-home `PermissionError`、topic 和 `/private/tmp` 写测全部 EPERM；**9/30 11:18 再次复现**（`evidence/eperm-before/session-01a0e741-excerpt.txt`）。
- Hogan 9/28 21:20 `baseline-before/`：现役 profile 下 global-home、`能源梳理`、`.kairo`、`~/kairo`、`/private/tmp` 全部 EPERM；9 份策略 sha256（`evidence/eperm-before/`）。

## 暴露面（peng 知悉）

- 整个 `~/kairo/.kairo` 可写，包括 global-home 的 1.3G uploads、所有全局 ref、**`global-home/constitution.yaml`**、`ref-catalog.json`、`projects/`、`review-work/`；两个 topic 的 `.kairo/` 和 `references/` 整体可写。
- 这份数据由 **8787 上的 `kairo serve`（pid 76501）直接对外服务**：写坏的内容会立刻可见，回滚只能收回写权限，不能撤销已写入的内容。
- `.kairo` 下没有 provider 或密钥配置（在 `~/.config/kairo`，仍然拒写）。
- glossary 写入仍会 EPERM，但异常被吞，run 不失败。

## 未决与剩余风险

- Desktop 单席停、启的效果有日志为证（9/25 23:24–23:26 只有周衡重启，另外 8 席没有动），但日志没有记下是哪个 UI 操作触发的；第一次现役执行本身就是对这一步的验证，停止条件已覆盖失败情形。
- 元宝 relay 目前 403、连接 CLOSED：只记录，不作为通过条件，但周衡在元宝上的进程也会按 relay 核对环境变量和策略。
- UI 编辑 System prompt 实际改的是定义行还是实例行尚不确定；verify 两行都查，不一致时按停止条件 f 处理。
- 周衡定义行的 `auto_restart_on_config_change=true` 意味着，若新策略文件留在现役目录，保存周衡配置、Desktop 重启或 Mac 重启都可能使它绕过同意门槛而生效；因此同意必须先于 apply，窗口中止或验收失败必须立即回滚到 `9e087351`。
- 功能地图 README 与 #59（#58）都在末尾加了一行，先合入的一方之后另一方需要简单 rebase。

## 落位与回退（Hogan，peng 同意后）

见 `docs/issue-57/README.md`「落位与生效」第 0–7 步、停止条件 a–f 和回滚 R。
