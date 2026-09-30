# #58 S1–S5 实例入口

入口：`~/lab/buzz/bin/buzz`（官方 CLI 签名闸门）、`~/lab/buzz/bin/buzz-health`（只读健康检查）、`docs/issue-58/{apply,rollback,verify,rehearse}.sh`。

1. **S1 发消息**：`bin/buzz --help` 返回 0；官方二进制 `codesign --verify --strict` 通过且 TeamIdentifier 为 `EYF346PHUG`。反例：临时目录中 ad-hoc 重签和追加 1 字节的副本经 `BUZZ58_TEST_OFFICIAL_BUZZ` 指定后，`bin/buzz` 拒绝（退出码 3、不执行），buzz-health 失败。只用临时副本做反例，不发真实消息。
2. **S2 健康检查**：对现役数据只读运行一次 `bin/buzz-health`，要求 doctor `ok:true`、对账「doctor 启动身份 = 本地 identities + 其他 relay 行」、每个本地身份至少 1 个有效 buzz-acp、yuanbao 只记录。反例用库存临时副本和注入的 ps/env：缺值、错值、非本地 relay、对账不符，均须失败。输出不得含私钥。
3. **S3 agent-* 去留**：18 个 buzz-acp 的 `BUZZ_ACP_AGENT_COMMAND` 不指向 `agent-harness`；库存和 `custom_harnesses/*.json` 中 `agent-harness` 引用数为 0；`agent-executor`、`agent-worktree` 保持 595c0cfe。
4. **S4 调用方**：按 `docs/issue-58/README.md` 清单逐项核对；现役进程命令行含 `lab/buzz/bin` 的为 0。
5. **S5 落位与回滚**：只在 `/tmp` 临时副本上跑 `rehearse.sh`：apply → verify → rollback → verify；回滚后四个入口 sha256 与 595c0cfe 一致，README 逐字节恢复；前后 buzz-acp pid 集合与 `managed-agents.json` 摘要不变；现役 `~/lab/buzz/bin` 前后一致。现役落位须 peng 批准，由 Hogan 按 README 执行。
