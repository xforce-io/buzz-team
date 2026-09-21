# 事务秘书处当日简报契约

与 `team/daily-blocker-digest.md` 同类：这是发帖正文规则，不是 workflow 引擎。
检查器只认本文 `prefixes` / `uncollected-forbidden` 围栏，见 `team/secretariat_briefing.py`。

## 谁发、发到哪

- 发帖人：秘书长（裴昭），不得由业务线秘书代发正式简报。
- 频道：`freeman事务秘书处` stream。禁止发到炼丹房（UUID `9bdc9fa2-48b7-4352-8b1f-7baf70ba6bd3`）。
- 形态：顶级帖，不要 `--reply-to`。

## 合法正文

Buzz 按 GitHub Flavored Markdown 渲染。简报必须是**分级标题 + 列表**，禁止把四条线挤成一段或四行超长纯文本。

首行必须是当日简报标题（可带最多两个 `#` 标题标记）：

`【当日简报】YYYY-MM-DD`

空一行后，恰好四个二级标题，顺序固定。检查器唯一事实源是下面围栏：

```prefixes
## 能源
## 中台PBU
## 技术
## 需拍板
```

每节标题下至少一行正文。已收集的节用短句 + 无序列表写来源，例如：

```
【当日简报】2026-09-17

## 能源

运营端 10 月底窗口有风险；智控 Demo 参数下发未通。

- 来源：kairo status 能源梳理；understanding.md
- 企微：不可用：control status connection=startup_failed
- git：不适用：/Users/xupeng/kairo 为未纳入 Git 的资料目录

## 中台PBU

…

## 技术

…

## 需拍板

- 能源一张网 10 月底窗口是否让步
```

点名：只允许 `@freeman`。禁止 `@human`，禁止把 CLI 身份 `human` 写进简报或需拍板。

## 缺收集与来源

- 某线还没有该线秘书的有效收集：该行值必须是 `未收集`（可附简短原因，但必须以 `未收集` 开头）。
- 禁止用下列字样冒充已收集或无事（检查器事实源）：

```uncollected-forbidden
无阻塞
无事
无
```

- 已收集的能源 / 中台PBU / 技术节：正文必须含 `来源：` 或 `不可用`。源命令失败、未授权、或不在 PATH 时写 `不可用` + 原因，禁止编造成功。
- `需拍板`：秘书长综合，写给 `@freeman`。三线有任一条为 `未收集` 时，本节必须出现 `未收集`，不得写成「无拍板 / 无」。三线都已收集且确无决策项时，可以写具体「无拍板项」类句子，但不得只用禁用字 `无`。

## 业务线秘书收集（点名后回帖）

被 @ 收集时：只报自己的业务线；用 `--reply-to` 回当前帖；不要发当日简报标题。
正文须能通过收集检查：出现本线前缀、含 `来源：` 或 `不可用`，且不得用其它线的前缀当自己的汇报行。

只读数据面：

- kairo：`list` / `status` / 读 `understanding.md`；能源线额外 `kairo project list`，能读则 `project context` / `project read`（含 Notion datasource）。禁止 `step` / `run` / 写 Notion / 改 datasource。
- **未折叠会议强制摘要（P0，peng 2026-09-21）**：若 `kairo status` 显示距上次综合有积压、或 `references/` 下存在当日/近 48h 的 `digest.md` 尚未写入 understanding 来源索引，业务线秘书必须**打开这些 digest 读正文**，在收集里用短句写出「会议名 + 结论变化 + 对窗口/拍板的含义」；秘书长简报能源/中台/技术节必须吸收这些变化，**禁止只报 plan/stale/fold 计数或 understanding 旧结论冒充今日**。digest 不可用时写 `不可用` + 路径/原因。understanding 因 `compose-*` blocked 未折，不免除读 digest。
- 企微：`control status`（`/Users/xupeng/lab/wecom-grok/control`）。
- 代码库：技术对 `/Users/xupeng/dev/github/buzz` 执行 `git status -sb`。能源 `/Users/xupeng/kairo` 与中台PBU `/Users/xupeng/lab/wecom-grok` 先用 `git rev-parse --is-inside-work-tree` 检查；未纳入 Git 时写 `不适用：资料/服务目录未纳入 Git`，不据此判断 Git 工具不可用，不自动 git init。

## 非目标

- 不把简报发进炼丹房，不改产研每日阻塞摘要。
- 不代 freeman 拍板、改产品范围、发版。
- 不让 buzz-workflow 发固定文案冒充简报。
