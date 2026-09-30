# #58 keel-verify 证据（Mac 临时副本演练，已脱敏）

2026-09-30 13:12–13:13（北京时间）在 peng 的 Mac 上运行 `bash docs/issue-58/rehearse.sh /tmp/buzz58-rehearsal-20260930-130602/final`。apply/rollback 只作用于 `/tmp` 下 `~/lab/buzz/{bin,README.md}` 的副本；现役实例只读。演练后临时目录已删除。被演练文件的 git blob id 见 `00-meta.txt`（其中 `repo_sha` a6a1a72 是整理提交前的本地提交，未推送）；这 8 个 blob id 与本分支 `docs/issue-58/` 下同名文件逐一相同，即演练的就是本分支代码。

| 文件 | 内容 |
|---|---|
| `00-meta.txt` | 时间、系统、被演练文件 blob id |
| `01-live-before.txt` / `14-live-after.txt` / `15-live-diff.txt` | 现役 `ls -l ~/lab/buzz/bin`、四个入口与 README 的 sha256、18 个 buzz-acp pid、`managed-agents.json` sha256；前后一致（IDENTICAL） |
| `02-copy-entries-before.txt` | 副本四个入口 sha256 = 595c0cfe 记录值 |
| `03-verify-0-old.txt` → `04-apply.txt` → `05-verify-1-new.txt` → `09-rollback.txt` → `10-verify-2-old.txt` | verify → apply → verify → rollback → verify，三次 VERIFY PASS；pid 集合与库存摘要两次比对均不变 |
| `11-copy-entries-after-rollback.txt` | 回滚后四个入口 sha256 = 595c0cfe = 现役；README 逐字节一致 |
| `06-official-path.txt` | 官方 CLI 路径、软链、bundle id、版本、更新机制（tauri-plugin-updater，无 Sparkle） |
| `07-signature-controls.txt` | （r1，旧判定）签名正反例：现役二进制与原样副本通过；ad-hoc 重签副本（TeamIdentifier not set）和追加 1 字节副本（`--verify --strict` rc=1）被 `bin/buzz` 拒绝（rc=3）且 buzz-health exit 2。文末附 r2 说明：旧判定已被 `-R` 取代，重跑见 19 |
| `08-health-negatives.txt` | buzz-health 反例（库存临时副本 + 注入 ps/env）：对照组通过；缺值、错值、非本地 relay、对账不符（doctor 报 12、库存副本中一行缺 relay）均 exit 2 |
| `12-agent-harness-retirement.txt` | 18/18 buzz-acp 执行器为 f66ef5e thin，指向 agent-harness 0 个；库存与 custom_harnesses/*.json 中 agent-harness 0 处 |
| `13-old-doctor-contrast.txt` | 595c0cfe 旧 doctor 两项 fail 的来源（第 11 行 `BUZZ_RUNTIME_ID` → `inventory_empty_pubkey:11` → 派生 `desktop_inventory` fail） |
| `health-live-after-apply.json` | 落位后（副本中新 `bin/buzz-health`）对现役数据的一次只读完整输出 |
| `16-redaction-check.txt` | 证据中 `PRIVATE_KEY`/`nsec1`/`BUZZ_PRIVATE` 命中 0（文件自身含检索式字面量） |

副本 README 落位后全文、其余 health JSON 和注入用 ps 夹具只留在 box 的 `/workspace/buzz-team-58-evidence/`（实例 README 属私有内容，不入库）。

## r2 修复轮（Knox P2/P3，2026-09-30 13:56–14:28 北京时间）

签名判定改为 `/usr/bin/codesign --verify --strict -R '=anchor apple generic and identifier "buzz" and certificate leaf[subject.OU] = "EYF346PHUG"' <bin>`（`bin/buzz`、`common.sh` `official_signature_ok`、`bin/buzz-health` 同一条）。全部在 peng 的 Mac 上的临时目录（`~/buzz58-r2-<ts>`、`/tmp/buzz58-r2-<ts>`）进行，结束后已删除；现役 `~/lab/buzz` 只读。演练的 8 个文件 blob id 见 `19` 开头的 `00-meta.txt`，与本提交同名文件逐一相同；`selfsigned-negative.sh` blob `b62e42ba`。

| 文件 | 内容 |
|---|---|
| `17-signature-requirement.txt` | `-R` 写法实测：`-R '=<req>'`（采用）rc=0；评审里写的 `-R='=<req>'` 在 macOS codesign 上是语法错误（`unexpected token: =`，rc=1），`-R='<req>'` 与 `--test-requirement='=<req>'` rc=0。错 OU、错 identifier、`buzz-acp` 二进制均 rc=3。官方二进制自带 DR、`-dvv` 证书链（Developer ID Application: Block, Inc. (EYF346PHUG) → Developer ID CA → Apple Root CA）。新 `bin/buzz --help` rc=0，`official_signature_ok` rc=0 |
| `18-selfsigned-negative.txt` | 自签反例：临时钥匙串文件 + OU=`EYF346PHUG` 自签代码签名证书。macOS codesign 用临时钥匙串里的身份签名失败（按名称和按 SHA-1 都是 `no identity found`，证书为 CSSMERR_TP_NOT_TRUSTED）；不改搜索列表和信任设置的前提下，改在 box 上用 rcodesign 以同类证书重签副本，再在 Mac 上检查。副本 `-dv` 自称 Identifier=buzz、TeamIdentifier=EYF346PHUG，不带 `-R` 的 `--verify --strict` rc=0；`-R` rc=3。旧 `bin/buzz`（9802f52）放行并 exec（被 macOS 在启动时 SIGKILL，rc=137），旧 buzz-health exit 0（被骗）；新 `bin/buzz` rc=3、不 exec，`official_signature_ok` 非 0，新 buzz-health exit 2。`security list-keychains`、默认钥匙串、用户信任设置摘要前后一致，临时钥匙串已删除 |
| `19-rehearsal-r2.txt` | r2 代码重跑 `rehearse.sh`：三次 VERIFY PASS；签名正反例（现役、原样副本 rc=0；ad-hoc 副本 `-R` rc=3、追加字节副本 rc=1 → `bin/buzz` rc=3、health exit 2）；health 反例同 r1；回滚后 4/4 入口 = 595c0cfe、README 逐字节一致；18 个 buzz-acp pid 与 `managed-agents.json` 摘要不变；现役 IDENTICAL |
| `20-rollback-from-template.txt` | P3(b)：`rollback.sh --from-template` 在临时副本上输出「README.md is NOT restored and must be restored manually」两处提示 |
| `21-live-session-r2.txt` | 整个 r2 会话前后现役快照（入口与 README sha256、ls -l、pid、库存摘要、官方二进制 sha256、`security list-keychains`）：IDENTICAL |
