# #57 S1–S5 周衡 Kairo 写入

入口：周衡真实会话（本地 relay 与元宝 relay 各一个进程）；`docs/issue-57/{snapshot,verify,apply,rollback,probe,rehearse}.sh`。

1. **S1 登记录音**：生效后，peng 在真实会话请周衡按 prompt 规则把 `20260928 140109.m4a` 转码（`$TMPDIR`）并登记到「能源梳理」，把 `20260928 150601.m4a` 登记到「ai-native」，把 `20260930 093139.m4a`（标题「刚总沟通」）登记到「能源梳理」。CLI 输出无 EPERM/PermissionError，`~/kairo/.kairo/ref-catalog.json` 里出现这三条 ref。周衡 9/30 11:18 选择的 `20260929 090208.m4a` 实为「算法例会-260928」，不计入验收；两条 9/28 录音的标题已由 Jenny 核对正确。
2. **S2 跑 run**：同一会话 `cd ~/kairo/<主题> && kairo run --ref <rid>`，三条各跑一次。CLI 无 EPERM；生成 transcript/digest，topic `state.json` 更新。glossary 降级只记入 `knowledge_review.yaml`，不计入。
3. **S3 边界不外扩**：`probe.sh` 输入策略临时副本，用现役 venv 的 `buzz_team.thin.command` 生成 profile。5 个新目录建探针、删探针成功；`~/kairo`、topic 根目录、`~/.config/kairo`、`/private/tmp` 均 EPERM；遗留探针 0。`verify.sh` 核对另外 8 份策略 sha256 等于 `baseline-before`，`_load_policy` 通过。合入前在副本上跑，生效后对现役文件的副本再跑一次。
4. **S4 不碰 /tmp**：两条 system_prompt 与仓库 `pj.md` 各含规则行一次（`verify.sh --prompt present`）；S1/S2 会话 `updates.jsonl` 中写 `/tmp`、`/private/tmp` 的尝试（包括 heredoc 报错）为 0。
5. **S5 落位与生效**：合入前用 `rehearse.sh` 在 `~` 下临时副本走 apply → verify → probe → rollback → verify，回滚后 sha256 = `9e087351`，现役前后一致。生效按 `docs/issue-57/README.md` 执行：Jenny 取得 peng 同意后才重启，只在 Desktop 停、启周衡，不 kill、不退出 Desktop。`verify.sh --compare-state --restarted` 按 relay 核对：周衡新 pid 带新策略 sha、`KAIRO_PROVIDER`、六个 9567 变量；另外 16 个 pid 不变；缺 `BUZZ_TEAM_POLICY_PATH` 判 FAIL。回滚用 `rollback.sh`（到 `9e087351`）。
