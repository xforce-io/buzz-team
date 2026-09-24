# #42 活激活清单（Hogan）

**何时：** PR #43 合入 `main` **之后**；且 **仅当 PR #41 已合入 main**（提供 `docs/issue-38/scripts/common.sh` + `_seat_identity_scan.py`）并完成其活窗之后。#41 未合入 → **停**，不要手搓席位扫描。  
**基线：** 2026-09-24 **16:13** proxy fix 全量重开已改写全部 **9** 席 pid；旧 baseline **全部作废**。激活前必须重新跑 `#41` 的 `apply.sh --baseline-only`（或等价）拿到**新鲜** 9-pid 基线。  
**谁：** Hogan 操作；peng 配合退出/重开 Desktop。`auto_restart_on_config_change=false`。  
**本清单不改** upstream / pin / workflow；managed 手工改；无改 `managed-agents.json` 的脚本。  
**证据：** `~/lab/buzz/evidence/issue-38-live-reverify/zhouheng-restart-20260924/`；proxy fix `~/lab/buzz/evidence/proxy-fix-9567-20260924/`（16:13:53 重开）。

## 0 前置硬门

- [ ] **#41 已合入 main**（否则停）。
- [ ] #41 活窗已结束；本窗不与 #38/#41 踩踏。
- [ ] 本票（#43）已合入；记下 `main` SHA。
- [ ] **事前声明**（禁止事后推断）：

  ```text
  restart-mode: app
  ```

  本流程会 **退出整个 Desktop**，故激活默认 **`app`**。`single` 仅用于**不** Cmd+Q / 不退整 app 的试验窗，不适用于本清单主路径。  
  声明与实际不符 → **FAIL → 停 → 回滚**（§5）。

- [ ] **新鲜 baseline：** Desktop 仍在线、doctor 9/9 时执行 `#41` `apply.sh --baseline-only`（含席位扫描 **positive control**：9 席各至少一进程命中）。写完后立刻记下墙钟。16:13 之后的旧备份勿用。
- [ ] **colima `:3000` 在听**（A14）：退出前后均确认 `lsof`/等价显示 LISTEN（样例：Desktop quit 不杀该 relay）。
- [ ] 备份：`managed-agents.json.bak-42-<date>`；lab `team/prompts/{pm,qa,light-keel}.md` 旁路拷贝。
- [ ] 只读核对合入后仓内三 prompt。

## 1 退出 → 确认已停 → 再编辑

**危险（A11）：** Desktop relaunch 可能把**内存态**写回 `managed-agents.json`。Desktop **运行中**改苏晴/沈予 `system_prompt` 可能被覆盖。

### 1.1 退出 Desktop（永不 kill）

```bash
osascript -e 'quit app "Buzz"'
# 或 GUI Cmd+Q。禁止 kill / kill -9 / 强杀。
```

### 1.2 停席确认（复用 #41，禁止手搓）

在 `#41` 已合入的树里调用（路径以 main 为准）：

- `docs/issue-38/scripts/common.sh` 中的席位停机门（如 `require_desktop_stopped` / `require_team_seats_not_running`）
- `docs/issue-38/scripts/_seat_identity_scan.py`

扫描规则（#41 已实现，此处不重写逻辑）：仅当进程是 `buzz_team.cli` wrapper 或 `buzz-acp`，且环境带完整 token  
`BUZZ_RUNTIME_ID=a558771623f29898/<seat pubkey>` 才算命中；排除扫描脚本自身。  
**Positive control**（Desktop 在线、baseline 时）：9 席各 ≥1 命中；扫描报错或 `ps` 空输出 → **ABORT**。  
停机门：在已有 PASS 的 positive-control 工件上，确认团队席匹配为空。  
**禁止：** `kill -0` 旧 pid、`pgrep -P`、机器级裸 `buzz-acp` 扫描。

### 1.3 编辑（仅 Desktop 已停）

- lab ← 合入后 `team/prompts/{light-keel,pm,qa}.md`
- managed 苏晴：`system_prompt` 角色前缀 ← 新 `pm.md`，**保留**「回复规则 / 对外表达 / 技能」尾段
- managed 沈予：同上 ← 新 `qa.md`
- 周衡/陆深/方维：**不改** SP 角色段

记下**编辑完成墙钟**（CST）。**不要**用 `managed-agents.json` mtime 当写完时间。

## 2 重开 Desktop（Hogan 16:13:53 实测；与 #41 `common.sh` 同字面）

**禁止** Dock / Launchpad 重开（A13：Dock 会带陈旧代理 `6478`）。**禁止** `open -n`（会第二实例）。App：`/Applications/Buzz.app`（bundle `xyz.block.buzz.app`）。

**退出后**执行（六键、带 `http://`、无 `-n`）——与 Hogan 16:13:53 及 #41 `docs/issue-38/scripts/common.sh` **逐字一致**：

```bash
X=http://127.0.0.1:9567; open -a Buzz --env HTTP_PROXY=$X --env HTTPS_PROXY=$X --env ALL_PROXY=$X --env http_proxy=$X --env https_proxy=$X --env all_proxy=$X
```

### 2.1 重开后门禁

- [ ] Desktop 主进程与各席进程环境：上述 **六键** 均等于 `http://127.0.0.1:9567`
- [ ] `doctor` → `ok:true`，**无** `proxy_contrast`
- [ ] **9/9 alive**；按 `restart-mode: app` 校验 **9 席 pid 相对 baseline 全部变化**
- [ ] 苏晴 SP 回读仍含「观感通过」相关句；沈予 SP 仍含 cache-param / 现网抽检相关句
- [ ] `:3000` 仍在听（A14）

任一门失败 → **FAIL**，§5 回滚，**不得**发探针。

### 2.2 pid / 启动时刻

- pid 文件多为 Python wrapper；buzz-acp 为其子进程（跟到子进程看代理/存活）。
- 启动时刻（对照编辑墙钟）：

```bash
LC_ALL=C LANG=C ps -o etime=,lstart= -p <pid>
```

## 3 受控探针（规则现在就钉死）

**规则（现在写入，激活时执行）：**

1. 探针**发送方不得是被测席本身**（禁止目标席自 @ / 自测）。
2. 若 Mac CLI **无私钥**（Hogan 16:14：`auth_error` / `BUZZ_PRIVATE_KEY is required`）：由 **peng 在 Desktop 手动发送**，或将该席探针显式标为 **「暂时无法测」**——二者择一记入记录；**不要**在文档里写死某一密钥来源。
3. 具体用哪个非被测身份，激活时与 Hogan 确认即可。

每相关席至多一条问句：

| 席位 | 期望 |
|---|---|
| 苏晴 | 体现「观感通过」门（真机/Console；L2 不可代；合入前） |
| 沈予 | 体现 cache-param + 生产抽检（#411/#416） |
| 周衡 / 陆深 / 方维 | 知会新 light-keel「观感签收门」「测试门清单」 |

合入前产品门禁：观感通过与测试门 **均须完成** 方可合入；二者相对顺序不固定（见 prompt / L1）。

## 4 完成定义

- [ ] #41 已合入；新鲜 `--baseline-only`；`restart-mode: app` 声明与实际一致  
- [ ] 退出（osascript/Cmd+Q）→ #41 停席扫描 PASS → 编辑 → 上节六键 `open -a Buzz` → 回读 SP  
- [ ] doctor ok、无 proxy_contrast、9/9、九 pid 皆变、:3000 LISTEN  
- [ ] 探针：非被测席发送；或 peng Desktop 手发；或标明「暂时无法测」  
- [ ] 在 #41 活窗之后执行  

## 5 回滚

同序：**osascript quit（勿 kill）→ #41 停席扫描确认已停 →** 恢复 managed/lab 备份 → **同一六键 `open -a Buzz` 命令** → 回读旧文案 → doctor/proxy/9 pid 按 `app` 校验。

## 6 A8

「prompt 何时读」**仍待证**（Knox：14:54 样例不能区分）。本票不做 A8 实验。保守策略即退出后编辑再重开。
