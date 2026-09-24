# #42 活激活清单（Hogan）

**何时：** PR 合入 `main` 之后；**必须**在独立时间窗执行，且排在 **#38 reverify 完成之后**。  
**谁：** Hogan 操作；**peng** 按席手工 Desktop 重启（`auto_restart_on_config_change=false`；kill 后 Desktop **不**自动拉起）。  
**本清单不改** upstream / pin / workflow；默认 **手工**改 managed，不提供改 `managed-agents.json` 的脚本。

## 0 前置

- [ ] #38 活复检已通过或明确让路。
- [ ] 本票已合入；记下 `main` SHA。
- [ ] 只读打开合入后的：
  - `team/prompts/light-keel.md`
  - `team/prompts/pm.md`
  - `team/prompts/qa.md`
- [ ] 备份：复制当前  
  `~/Library/Application Support/xyz.block.buzz.app/agents/managed-agents.json`  
  → 同目录 `managed-agents.json.bak-42-<date>`。

## 1 按席同步

| 席位 | slug（若有） | 同步什么 | 怎么做（手工） |
|---|---|---|---|
| 苏晴 | `zhufeng-pm` | **SP 内联角色段** = 合入后 `pm.md` 全文，保持其后「回复规则 / 对外表达 / 技能」尾段不动 | 在 managed 该席 `system_prompt` 中：用新 `pm.md` **替换**原角色前缀（旧前缀曾与 lab `pm.md` 一致）；勿丢尾段 |
| 沈予 | `zhufeng-qa` | **SP 内联角色段** = 合入后 `qa.md`，同上保留尾段 | 同苏晴手法 |
| 周衡 / 陆深 / 方维 | `zhufeng-pj` / `eng` / `ops` | **不改 SP 角色段**（本票未改 `pj`/`eng`/`ops`） | — |
| **五席共同** | 炼丹房全部 | **lab 文件** `~/lab/buzz-team/team/prompts/light-keel.md`（及 pm/qa 与仓对齐，避免漂移） | 将合入后三文件拷到 lab 同名路径（覆盖前可先 diff） |

说明：五席 SP/`AGENTS.md` 均路径引用 `light-keel.md`；苏晴/沈予的 S1/S2 义务还依赖 SP 内联段，故二人必须改 SP。

## 2 重启（peng）

对**每个**受影响席位（至少：苏晴、沈予；建议五席都启一次以便重载 lab `light-keel` 上下文）：

1. Desktop 停该席 → 确认旧 pid 退出。
2. 再启 → 记录**新 pid**。
3. `buzz-team doctor`（或实例惯用 doctor）：目标 **9/9**（以当时实例口径为准）。

回滚：恢复 `managed-agents.json.bak-42-*`；lab 三文件回备份；再按席手工重启。

## 3 受控验证（每重启席一条消息）

在约定频道或 DM，对每个已重启席发**一条**受控问句（勿刷屏）：

| 席位 | 期望 |
|---|---|
| **苏晴** | 回复体现 **「观感通过」门**（实现门后、合入门前；真机/Console；L2 不可代） |
| **沈予** | 回复体现 **cache-param 更新 + 生产抽检**（#411/#416） |
| 周衡 / 陆深 / 方维 | 回复能反映新 `light-keel` 中「观感签收门」与「测试门清单」存在（不必代苏晴签观感） |

记录：席位、新 pid、doctor、消息 id、是否命中期望。未命中 → 不宣称激活完成；查 SP 是否漏同步或是否未重启（见 L1 **A8**）。

## 4 完成定义

- [ ] 备份存在且可回滚  
- [ ] 苏晴/沈予 SP 角色段已替换；lab `light-keel`（及 pm/qa）与合入 SHA 一致  
- [ ] 计划内席位均已手工重启，新 pid + doctor 达标  
- [ ] 受控消息：苏晴观感门、沈予缓存条、其余席知会新 light-keel 节  
- [ ] 本窗与 #38 reverify 未互相踩踏  

**活证明 = 本清单**；仓内 keel-verify 对 prompt-only 变更 skip（见 PR 验收表）。
