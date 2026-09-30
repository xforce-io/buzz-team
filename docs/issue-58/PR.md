# feat(#58): 按 cb63521 用法重做 ~/lab/buzz 入口

Closes #58。L1：评论 5902016872（r1）+ 5902035503（r2，K1–K4），peng 2026-09-30 12:33 批准，待定点 1–6 均取 (a)。

## 与 L1 文字的关系

- **签名校验放在 `bin/buzz` 里**（Knox 12:59 定稿）。r1 3.1 写的「`bin/buzz` 改成两行 `exec`」已被 r2 K4 取代：`bin/buzz` 是一个短 bash 脚本，用显式 designated requirement 校验官方二进制：`/usr/bin/codesign --verify --strict -R '=anchor apple generic and identifier "buzz" and certificate leaf[subject.OU] = "EYF346PHUG"'`（Apple 证书链 + Identifier `buzz` + 叶证书 OU `EYF346PHUG`；Identifier 限定防止指向同一发布方的其他二进制），通过才 `exec` 并原样传参；不通过就拒绝、不 exec、不发送、退出码 3。只依赖 bash 内建命令和 `/usr/bin/codesign`。`bin/buzz-health` 与 apply 前置检查（`official_signature_ok`）用同一条 requirement；`codesign -dv` 的 TeamIdentifier / Identifier 只记录，不参与判定（r2，见下）。
- sha256 pin 去掉（待定点 2(a)）；sha256 和 `CFBundleShortVersionString` 只记录，变化标为 "official component updated"，不判失败。
- DM 去 `--reply-to` 不再由 `bin/buzz` 做：席位本来不经过 `bin/buzz`，规则写在席位 prompt 里；运维脚本发 DM 时不要带 `--reply-to`。
- K1 的「本地身份行的 `env_vars.BUZZ_TEAM_POLICY_PATH`」：现役库存把这个值放在定义行（`slug`），实例行（`persona_id` = `slug`）不写。buzz-health 取实例行的值，缺省时取对应定义行，并在输出里标 `policy_source`。
- `custom_harnesses` 实际位置是 `~/Library/Application Support/xyz.block.buzz.app/custom_harnesses`（不在 `~/lab/buzz` 下）。

## 改动

- `docs/issue-58/bin/buzz`、`docs/issue-58/bin/buzz-health`：实例入口新内容。
- `docs/issue-58/{apply,rollback,verify,rehearse}.sh`、`common.sh`：落位、回退、核对、临时副本演练；都支持 `--target DIR`。现役实例要求 `ISSUE58_I_UNDERSTAND_LIVE=yes`，并拒绝任何测试变量。
- `docs/issue-58/README.md`：官方 CLI 路径与更新依据、buzz-health 规则、agent-* 去留、调用方迁移清单、旧 doctor 对照、落位步骤。
- `docs/issue-58/evidence/`：Mac 临时副本演练证据。
- `docs/issue-58/selfsigned-negative.sh`（r2）：自签证书反例脚本（临时钥匙串文件，结束即删）。
- `tests/test_issue58_entries.py`：buzz-health 逻辑、签名 requirement 判定（假 codesign：`-dv` 自称正确团队也不能通过）、`bin/buzz` 缺 codesign 时拒绝、apply/rollback 临时目录演练。
- 功能地图：`.agents/skills/verify-buzz-team/features/instance-entries.md` + README 一行。
- 不改 `src/`、不改包内容、不改 #38 文件。

## 验收表

在冻结候选（本 PR head）的干净工作树上重新运行：

```
S1: pass  bash docs/issue-58/rehearse.sh (Mac 临时副本) + python -m unittest tests.test_issue58_entries  官方二进制满足 codesign --verify --strict -R <requirement>（rc=0），新 bin/buzz --help rc=0；ad-hoc 重签、追加 1 字节、OU=EYF346PHUG 自签证书重签的副本被拒（rc=3，不 exec），buzz-health exit 2（r2 evidence/17–19）；现役调用方中仍经旧包装的为 0（进程 0、launchd/cron 0、relay workflow 0）。未发真实消息（本环节禁止）；DM/频道位置由席位 prompt 决定，席位不经 bin/buzz
S2: pass  ~/lab/buzz 副本 bin/buzz-health（现役数据只读）  exit 0；doctor ok:true，11 = 9 本地 + 2 yuanbao 行；9/9 本地身份各有 1 个有效 buzz-acp；yuanbao 9 个进程只记录；缺值/错值/非本地 relay/对账不符（2 种）均 exit 2
S3: pass  evidence/12-agent-harness-retirement.txt + verify.sh --expect new  3/3 有结论（executor 保留、harness 下线、worktree 保留）；agent-harness 在库存、custom_harnesses、18 个进程中引用均为 0；落位后 agent-harness 移入备份
S4: pass  docs/issue-58/README.md 调用方清单  每项有「现调用 → 新调用/结论」；relay workflow 0 处（Hogan 12:58）；#38 脚本 5 处按 L1 只登记（#38 属 Out），新 bin/buzz 下仍可用
S5: pass  bash docs/issue-58/rehearse.sh  apply→verify→rollback→verify 三次 VERIFY PASS；回滚后 4/4 入口 sha256 = 595c0cfe，README 逐字节一致；18 个 buzz-acp pid 与 managed-agents.json 摘要前后不变；现役 ~/lab/buzz/bin 未动。现役落位待 peng 批准
#53/#54 回归: pass  python -m unittest discover -s tests -v  既有 doctor/thin 测试全部通过（src 未改）
```

## keel-verify（功能地图 `instance-entries.md`）

| Story | 入口 | 结果 | 证据 |
|---|---|---|---|
| S1 | 副本 `bin/buzz --help`，`BUZZ58_TEST_OFFICIAL_BUZZ` 指向 ad-hoc / 改字节 / 自签副本 | pass | `evidence/17-signature-requirement.txt`、`18-selfsigned-negative.txt`、`19-rehearsal-r2.txt`（r1：`07`） |
| S2 | 副本 `bin/buzz-health`（现役只读）+ 注入夹具反例 | pass | `evidence/health-live-after-apply.json`、`08-health-negatives.txt` |
| S3 | `verify.sh --expect new`、grep、进程 env | pass | `evidence/05-verify-1-new.txt`、`12-agent-harness-retirement.txt` |
| S4 | 清单核对 | pass | `docs/issue-58/README.md`、`12-agent-harness-retirement.txt` |
| S5 | `rehearse.sh`（apply/verify/rollback/verify） | pass | `evidence/03`–`05`、`09`–`11`、`15-live-diff.txt`；r2 重跑 `19-rehearsal-r2.txt`、`21-live-session-r2.txt` |

## 未决与剩余风险

- 签名校验挡不住同一发布方签名的新版本（K4，peng 接受）；新版本行为靠 sha/版本记录和产品日志发现。
- r2 requirement 不含官方 DR 中 Developer ID 的两个 OID 条件：同一团队其他 Apple 签发证书签的 `buzz` 也会通过，与上一条同类。
- Desktop 更新后官方 CLI 仍在原路径：依据是 `buzz` 为 Tauri `externalBin`、更新器整体替换 `Buzz.app`；本机 9/25 以来未发生更新，没有实测。
- 校验与 exec 之间有极短的 TOCTOU 窗口（官方二进制位于用户可写的 `/Applications/Buzz.app`）；与原 sha256 pin 同等。
- #38 脚本（`smoke-real-workflow.sh` 20/22/38 行、`common.sh` 24–25 行、`apply.sh` 50/181 行、`rollback.sh` 77 行）只登记，随 #38 重写处理；`common.sh` 的 `verify_thin_pin` 自 595c0cfe 起已不成立。
- `agent-worktree` 下线和 9 席 AGENTS.md 第 11 行修改需 peng 另批。

## r2 修复轮（Knox CHANGES_REQUESTED）

- **P2（阻塞）**：`codesign --verify --strict` 对 ad-hoc 副本也返回 0，`codesign -dv` 的 TeamIdentifier / Identifier 是签名者自填的。三处校验（`bin/buzz`、`common.sh` `official_signature_ok`、`bin/buzz-health`）统一改为显式 designated requirement：
  `/usr/bin/codesign --verify --strict -R '=anchor apple generic and identifier "buzz" and certificate leaf[subject.OU] = "EYF346PHUG"' <bin>`
  只看它的退出码；`-dv` 只用于 buzz-health 的记录字段。`bin/buzz`：通过 → `exec` 并原样传参；不通过 → 拒绝、不 exec、退出码 3。写法注意：评审中的 `-R='=…'` 在 macOS 上是 requirement 语法错误（rc=1），实际用 `-R '=…'`（`evidence/17`）。
- **P3(a)**：`bin/buzz` 不再调用 sed（`-dv` 解析整段删除），除 bash 内建命令外只用 `/usr/bin/codesign` 绝对路径；测试断言脚本里没有裸 `sed/grep/awk/printf` 调用。
- **P3(b)**：`rollback.sh --from-template` 在选源时和结束时各打印一行「README.md 未恢复，须手动恢复」（`evidence/20`）；README「落位」同步写明。
- **证据（Mac，临时目录，已删除；现役只读，前后 IDENTICAL）**：官方二进制 `-R` rc=0、新 `bin/buzz --help` rc=0；ad-hoc 副本 `-R` rc=3、追加字节副本 rc=1 → `bin/buzz` rc=3、health exit 2；OU=`EYF346PHUG` 自签副本：`-dv` 自称 TeamIdentifier=`EYF346PHUG`、无 `-R` 的 verify rc=0，旧 gate 放行（旧 `bin/buzz` exec 后被 macOS SIGKILL，旧 health exit 0），新 `bin/buzz` rc=3、health exit 2。自签副本最终由 box 上 rcodesign 签出（macOS codesign 拒绝使用不在搜索列表里的临时钥匙串身份，按名称和 SHA-1 都是 `no identity found`；未改搜索列表和信任设置），`security list-keychains` 前后一致。`rehearse.sh` 重跑三次 VERIFY PASS，回滚后 4/4 = 595c0cfe、README 逐字节一致、18 个 buzz-acp pid 与库存摘要不变。
- **测试**：`SignatureTests` 改为 requirement 判定（假 runner：`-dv` 自称正确团队但 `-R` 失败 → 不通过；`-dv` 乱写但 `-R` 通过 → 通过）；新增 `RequirementGateTests`：把 `bin/buzz`、`common.sh` 的临时副本里 `/usr/bin/codesign` 换成假 codesign（不给正式脚本加测试钩子），验证 requirement 文本三处一致、通过时原样传参 exec、不通过时 rc=3 且不 exec；`--from-template` 提示有断言。

## 落位与回退（Hogan，peng 批准后）

见 `docs/issue-58/README.md`「落位」。apply 不重启 Desktop、不碰 managed-agents.json、channel_wake、workflow、代理、colima、:3000、:4500、9 席与 18 个 buzz-acp；rollback 一步恢复 595c0cfe 四个入口（逐字节校验），`--from-template` 可在备份不可用时重建。
