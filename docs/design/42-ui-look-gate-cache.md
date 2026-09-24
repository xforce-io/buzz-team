# #42 UI 票合入前观感签收门 + 测试门缓存检查

状态：**L1 Approved（peng 2026-09-24，Jenny 确认；范围仅 S1+S2）**。

Owner：Scout · Product（instance/config/skills）。关联：[Issue #42](https://github.com/xforce-io/buzz-team/issues/42)。Review：Knox；human merge gate：peng；live 激活：Hogan。

## 1 背景

炼丹房最大返工环 #411（2026-09-21）：L2 上「负责人已 Approved 交互」后合入部署，现网以「廉价表单感」等驳回；其后约四轮，其中一轮 `app.css` 已改但 `base.html` 查询参数未更新，生产继续旧 CSS（PR #416）。炼丹房无独立 UI/UX 席；苏晴只写可勾选验收；沈予只对照书面 S\*。peng 仅批准下列两项（仅本仓 `team/prompts/`）。

## 2 名词

- **观感通过**：频道可见回复原文含「观感通过」；依据为真机截图或本地 Console 实看，不是 L2 markdown。
- **cache-bust**：引用 css/js 的查询参数（或等价版本键）；改静态资源时必须同步更新，并抽检生产实发版本。

## 3 目标与非目标

目标（字面）：

- **S1**：`full` 且用户可见 UI 的票，实现门之后、合入门之前，苏晴或票 owner 基于真机截图/本地 Console 回复「观感通过」；L2 不得代替。
- **S2**：UI 票改动 css/js 时，测试门须确认 cache-bust 已更新，并抽检生产拿到新版本（引 #411/#416）。

非目标（越权则 flag，不写入）：

- 上线后变更纪律；新 UI/UX 席；改签收人集合、超时/降级/代签规则。
- 扩大到非 `full` 或非用户可见 UI。
- #38 周衡三栏 / `pj.md` / workflow / effort·idle；thin-bin pin `046ac43`；upstream `block/buzz`；runtime/ACP。

## 4 改动面

| 路径 | 动作 |
|---|---|
| `team/prompts/pm.md` | 基线入仓 + S1 苏晴义务 |
| `team/prompts/light-keel.md` | 基线入仓 +「观感签收门」+「测试门清单」 |
| `team/prompts/qa.md` | 基线入仓 + S2 缓存条款 |
| `docs/issue-42/ACTIVATION.md` | Hogan 活激活清单（合入后另窗） |

基线：从 Mac lab `/Users/xupeng/lab/buzz-team/team/prompts/` 三文件 verbatim 导入（此前 GitHub `main` 仅有 `pj.md`）。

## 5 活加载与 SP 对照（只读证据 2026-09-24）

| 文件 | 活引用 | 与 managed `system_prompt` |
|---|---|---|
| `light-keel.md` | 炼丹房五席 SP 与 workspace `AGENTS.md` 均路径引用 | **未**内联；席位按需读文件（何时读见 A8） |
| `pm.md` | 无路径引用 | 苏晴 SP：**角色文件正文是 SP 的精确前缀**；其后另接「回复规则 / 对外表达 / 技能」共约 +1288 字。整段 SP ≠ 文件（非 byte-for-byte 全等） |
| `qa.md` | 无路径引用 | 沈予 SP：同上模式（文件为前缀，+1288 字共用尾） |

因此：只改仓内/lab 的 `pm.md`/`qa.md` **不会**自动改活行为；须 Hogan 把对应角色段同步进 managed `system_prompt` 后再重启。`light-keel.md` 改文件后，仍取决于席位是否重读文件（A8）及进程是否仍持旧上下文。

五席 `auto_restart_on_config_change=false`。Desktop kill 后**不**自动 restart；激活 = peng 按席手工重启。

**不把** live SP 全文导入本仓（避免凭据/实例私货）；ACTIVATION 只描述替换角色段。

## 6 环境假设

| ID | 假设 | 状态 |
|---|---|---|
| A1 | 炼丹房五席仍为苏晴/周衡/陆深/沈予/方维；秘书处不走 light-keel | 已活机核对 SP+AGENTS |
| A2 | 频道门名仍为：设计通过 → 实现门 → 测试门 → 合入门 → 部署窗 | 频道惯例；本票只钉观感插入点与测试清单条 |
| A3 | `pm`/`qa` 活执行值在 managed `system_prompt` | 已核对 |
| A4 | `auto_restart_on_config_change=false`；单席 kill 后 Desktop 不自动拉起；**全量 Cmd+Q+重开**可一次换齐 9 pid（~8s 拉起；池懒初始化，首消息 ~11s） | 已读 managed；2026-09-24 周衡重开样例（Hogan） |
| A5 | 合入本 PR 不自动改 Mac lab / managed；活激活另窗 | 流程约束 |
| A6 | 本票活激活在 **#41 合入 + 其活窗之后**；16:13 proxy fix 后须**新鲜** `--baseline-only`（旧 9-pid 基线作废） | 运维约定；Hogan 16:13 |
| A7 | 不修改 `managed-agents.json` 的自动化脚本进入本 PR | 本票仅文档化手工步骤 |
| **A8** | **「prompt 什么时候读」**（进程启动一次 vs 每会话/每工具重读文件） | **仍待活机证据**（与 [#41](https://github.com/xforce-io/buzz-team/issues/41) A8 共享）。Knox：2026-09-24 周衡全量重开样例**不能**区分启动读 vs 每会话重读；本票**不做 A8 实验**。激活保守策略：仅 Desktop **完全退出**时改 managed/lab，再 Dock/Launchpad 重开并回读 SP（见 ACTIVATION） |
| **A11** | Desktop 可能在 relaunch 时把**内存态**写回 `managed-agents.json`（如 `last_started_at` / `updated_at`） | **待系统化活证**（Knox A11）；2026-09-24 样例见 managed 在 14:54:38 被重开改写。故 ACTIVATION **禁止**在 Desktop 运行中改 SP，并在重开后回读「观感通过」/cache 句是否仍在 |
| **A13** | Dock/Launchpad 重开可能带入陈旧代理（样例 `6478`）；须用终端六键 `open -a Buzz --env …9567`（Hogan 16:13:53；与 #41 `common.sh` 同字面） | **CONFIRMED** 问题与 option-1 修复（peng 16:11 选定，Hogan 16:13 落地；证据 `proxy-fix-9567-20260924/`）。重开后六键=`http://127.0.0.1:9567` 且 doctor 无 `proxy_contrast` |
| **A14** | colima（或等价）`:3000` relay 在 Desktop quit 后仍 LISTEN | **CONFIRMED** 同证据窗；激活前后均检查 |

## 7 门禁顺序

```text
（full + 用户可见 UI）
  实现门通过
    → 「观感通过」（苏晴或 owner：真机截图/本地 Console）
    → 测试门（若改 css/js：cache-bust + 生产抽检）
    （观感与测试门相对顺序不固定；二者均须完成）
      → 合入门
```

## 8 边界

- 只改上述 prompt 与文档；不改产品 UI、不改上游。
- 签收人保持「苏晴或票 owner」；不引入代签/超时降级。
- 与 #38 文件集不相交（#38：`pj.md` / 周衡 AGENTS / instructions / workflow）。

## 9 测试计划 / 活机复检

本票无用户可摸产品界面；仓内无新 verify feature 文件（prompt 合同）。

- 预合入：diff 审读 + dry-read 三文件含「观感通过」与 cache 条。
- 合入后活证明：见 [`docs/issue-42/ACTIVATION.md`](../issue-42/ACTIVATION.md)（Hogan）：依赖 #41 扫描；`restart-mode: app`；osascript 退出后编辑；六键 `open -a Buzz` 重开；doctor 无 proxy_contrast；探针发送方≠被测席（CLI 无钥则 peng Desktop 手发或标「暂时无法测」）。

## 10 开放问题

1. A8 读时机 — 仍待活机（样例未分清）；激活已钉「退出后编辑 + 重开回读」，本票不做 A8 实验。
2. A11 Desktop relaunch 回写 managed — 待系统化活证；ACTIVATION 已按最坏情况避让。
3. lab 与 git 双份 — 激活时 Hogan 以合入后的仓内文件为准拷回 lab（或等价），避免 lab 漂移。

## 11 关联

- [Issue #42](https://github.com/xforce-io/buzz-team/issues/42)
- [Issue #38](https://github.com/xforce-io/buzz-team/issues/38)（不重叠；激活错开）
- [Issue #41](https://github.com/xforce-io/buzz-team/issues/41)（A8 共享）
- 证据：#411 / PR #416（kairo 史）；`/workspace/zhouheng-rework-analysis.md`
