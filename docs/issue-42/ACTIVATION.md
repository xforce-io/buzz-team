# #42 活激活清单（Hogan）

**何时：** PR 合入 `main` 之后；**必须**在独立时间窗执行，且排在 **#38 / #41 活窗完成之后**（先 #38 reverify，再本清单；勿与 #38/#41 同窗踩踏）。  
**前置活条件（硬）：** 仅当 **doctor `ok:true` 且 `proxy_contrast` 绿**、席位已能正常回复时，才开始本票活激活。今日（2026-09-24）全量重开样例曾全部 ACP 进程落到错误代理 `127.0.0.1:6478`——**proxy 未绿不得发受控消息**。  
**谁：** Hogan 操作；**peng** 执行重启（见 §2；`auto_restart_on_config_change=false`；单席 kill 后 Desktop **不**自动拉起）。  
**本清单不改** upstream / pin / workflow；默认 **手工**改 managed，不提供改 `managed-agents.json` 的脚本。  
**证据参考（只读）：** `~/lab/buzz/evidence/issue-38-live-reverify/zhouheng-restart-20260924/`（全量重开样例；A8 仍未分清）。

## 0 前置

- [ ] #38 活复检已通过或明确让路；#41 活窗已让路或不冲突。
- [ ] 本票已合入；记下 `main` SHA 与计划编辑时刻（墙钟，CST）。
- [ ] **先声明**本窗重启模式（**事前**填写，禁止事后推断）：

  ```text
  restart-mode: single|app
  ```

  | 声明 | 事后必须满足，否则 **FAIL → 停 → 回滚** |
  |---|---|
  | `single` | 仅目标席 pid 变；**其余 8 席 pid 不变** |
  | `app` | **全部 9 席 pid 均变**且均存活（全量 Cmd+Q + 重开可一次覆盖五席 light-keel 引用方） |

- [ ] 只读打开合入后的仓内：`team/prompts/{light-keel,pm,qa}.md`。
- [ ] **备份（Desktop 仍可开着时先拷，随后必须退出再改）：**
  - `managed-agents.json` → 同目录 `managed-agents.json.bak-42-<date>`
  - lab 三文件 → `~/lab/buzz-team/team/prompts/*.bak-42-<date>`（或等价旁路拷贝）
- [ ] 记录当前 **9 席 pid 基线**（见 §2.1），供声明校验。

## 1 编辑窗口（必须先退出 Desktop）

**危险：** Buzz Desktop 在 **launch/relaunch 时会回写** `managed-agents.json`（样例：全量重开后各席 `last_started_at` / `updated_at` 被改写）。在 Desktop **仍在运行**时改苏晴/沈予 `system_prompt`，有被 Desktop **内存态覆盖**的风险。

**顺序（强制）：**

1. **完全退出 Desktop**：Cmd+Q；确认无 Desktop / buzz-acp 相关进程（`pgrep`/`ps`）。
2. **再**改文件：
   - lab：合入后三文件 → `~/lab/buzz-team/team/prompts/{light-keel,pm,qa}.md`
   - managed：苏晴 `system_prompt` 角色前缀 ← 新 `pm.md`（保留「回复规则 / 对外表达 / 技能」尾段）
   - managed：沈予同上 ← 新 `qa.md`
   - 周衡 / 陆深 / 方维：**不改** SP 角色段（本票未改 `pj`/`eng`/`ops`）
3. 记下**编辑完成墙钟**（CST）。**不要**用 `managed-agents.json` 的 mtime 当「配置写完时间」（Desktop 重开会改该文件）。
4. **再开 Desktop**：从 **Dock / Launchpad** 打开（不要用终端冷启路径，除非运维另有钉死口径）。
5. **回读存活证明（重开后立刻）：**
   - 苏晴 `system_prompt` 仍含「观感通过」相关句（如 `grep` / 只读 JSON 抽头）
   - 沈予 `system_prompt` 仍含 cache-param / 现网抽检相关句  
   若回读失败 → **FAIL**：按 §5 回滚，勿继续。

| 席位 | slug（若有） | 同步什么 |
|---|---|---|
| 苏晴 | `zhufeng-pm` | SP 角色段 = 新 `pm.md` + 保留尾段；lab `pm.md` |
| 沈予 | `zhufeng-qa` | SP 角色段 = 新 `qa.md` + 保留尾段；lab `qa.md` |
| 周衡 / 陆深 / 方维 | pj / eng / ops | 仅 lab `light-keel.md`（及与仓对齐的 pm/qa 文件树）；**不改**其 SP 角色段 |
| 五席共同 | 炼丹房 | lab `light-keel.md` 与仓一致（路径引用） |

## 2 重启与 pid

### 2.1 pid 语义

- pid **文件**里通常是 **Python wrapper** pid；真正的 **buzz-acp** 是其子进程。核对存活时跟到子进程。
- macOS `ps` **无** `etimes`；用：  
  `ps -o etime=,lstart= -p <pid>`  
  与「编辑完成墙钟」对照，确认进程晚于编辑时刻启动。

### 2.2 执行声明的模式

- **`restart-mode: app`（推荐覆盖五席 light-keel）：** 已在 §1 用 Cmd+Q + Dock/Launchpad 全量重开即可；样例约 **~8s** 拉起席位池，agent pool **懒初始化**（首条消息约再 **~11s**）。重开后 **重采全部 9 席 pid** 作新基线。
- **`restart-mode: single`：** 仅停/启声明目标席；其余 8 席 pid 必须与 §0 基线一致。

校验：实际结果与事前 `restart-mode` **不一致 → FAIL：停止并回滚**（§5）。记录实际模式与 9 pid 表。

### 2.3 doctor（发消息前）

- [ ] `doctor ok:true`
- [ ] **`proxy_contrast` 绿**（ACP 进程代理与 CLI 一致；错误样例勿放过）
- [ ] **9/9 alive**（口径以当时 doctor 为准）

未绿 / 未 9/9 → **不得**进入 §3。

## 3 受控验证

**发送身份：** 必须用 **非周衡** 身份发探针；**不得**用目标席自己发（本机 CLI 默认身份常为周衡——Hogan 14:57 样例曾自提及）。从非周衡身份 @ 目标席。

每个相关席 **一条**受控问句（勿刷屏）：

| 席位 | 期望 |
|---|---|
| **苏晴** | 回复体现 **「观感通过」门**（实现门后、合入门前；真机/Console；L2 不可代） |
| **沈予** | 回复体现 **cache-param 更新 + 生产抽检**（#411/#416） |
| 周衡 / 陆深 / 方维 | 能反映新 `light-keel`「观感签收门」与「测试门清单」（不必代签观感） |

记录：`restart-mode`、编辑墙钟、9 pid 表、doctor/proxy、发送身份、消息 id、是否命中。未命中 → 不宣称完成；查 SP 回读 / 是否未按退出-编辑-重开（见 L1 **A8**，仍待分清）。

## 4 完成定义

- [ ] 事前已声明 `restart-mode`，且实际与声明一致  
- [ ] 备份可回滚；§1 退出 Desktop → 编辑 → Dock/Launchpad 重开 → SP 回读通过  
- [ ] lab 三文件与合入 SHA 一致；苏晴/沈予 SP 角色段已换且尾段保留  
- [ ] doctor `ok:true` + `proxy_contrast` 绿 + 9/9；pid/`etime,lstart` 相对编辑墙钟合理  
- [ ] 受控消息：非周衡发送；苏晴观感门、沈予缓存条、其余席知会新 light-keel 节  
- [ ] 本窗在 #38/#41 活窗之后，未互相踩踏  

**活证明 = 本清单**；仓内 keel-verify 对 prompt-only skip（见 PR 验收表）。

## 5 回滚

与激活同序：**Cmd+Q 确认无 Desktop/buzz-acp →** 恢复 `managed-agents.json.bak-42-*` 与 lab 三文件备份 → **Dock/Launchpad 重开** → 回读确认旧文案恢复 → 按原声明模式校验 pid → doctor/proxy 再绿后再歇。

## 6 A8

「prompt 何时读」（启动一次 vs 每会话重读）**仍待活机证据**（Knox：2026-09-24 周衡重开样例**不能**区分）。本票 **不做 A8 实验**。保守策略即上文：**仅在 Desktop 完全退出时编辑，再重开**，避免半窗混读。
