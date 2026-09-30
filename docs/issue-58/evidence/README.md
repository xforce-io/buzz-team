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
| `07-signature-controls.txt` | 签名正反例：现役二进制与原样副本通过；ad-hoc 重签副本（TeamIdentifier not set）和追加 1 字节副本（`--verify --strict` rc=1）被 `bin/buzz` 拒绝（rc=3）且 buzz-health exit 2 |
| `08-health-negatives.txt` | buzz-health 反例（库存临时副本 + 注入 ps/env）：对照组通过；缺值、错值、非本地 relay、对账不符（doctor 报 12、库存副本中一行缺 relay）均 exit 2 |
| `12-agent-harness-retirement.txt` | 18/18 buzz-acp 执行器为 f66ef5e thin，指向 agent-harness 0 个；库存与 custom_harnesses/*.json 中 agent-harness 0 处 |
| `13-old-doctor-contrast.txt` | 595c0cfe 旧 doctor 两项 fail 的来源（第 11 行 `BUZZ_RUNTIME_ID` → `inventory_empty_pubkey:11` → 派生 `desktop_inventory` fail） |
| `health-live-after-apply.json` | 落位后（副本中新 `bin/buzz-health`）对现役数据的一次只读完整输出 |
| `16-redaction-check.txt` | 证据中 `PRIVATE_KEY`/`nsec1`/`BUZZ_PRIVATE` 命中 0（文件自身含检索式字面量） |

副本 README 落位后全文、其余 health JSON 和注入用 ps 夹具只留在 box 的 `/workspace/buzz-team-58-evidence/`（实例 README 属私有内容，不入库）。
