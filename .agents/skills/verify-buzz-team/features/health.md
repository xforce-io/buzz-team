# 健康检查语义（Issue #11 · S1–S5）

静态 `doctor` / 诊断深度 `diagnose` 的结果分类、组件归因与文档边界。二者共用同一检查内核；`diagnose` 额外做已声明代理端点的 TCP 探测，并显式列出 `unverified_surfaces`。

## 结果分类（S1）

每项检查为 `{id, status, component, summary}`，`status` 仅为：

| status | 含义 |
|---|---|
| `pass` | 本项证据已覆盖且通过 |
| `fail` | 本项证据已覆盖且失败 |
| `unverified` | 本深度未取证；不得当作通过 |
| `na` | 不适用（例如非仓库目录上的 Git、非 macOS 的 Seatbelt 工具轴） |

顶层 `ok` **仅当没有任何 `fail`**。存在 `unverified` **不**表示整体环境健康。退出码与失败结论一致（有 fail → 非零）。

覆盖范围见输出字段 `coverage`（按四类列出 check id）与 `warnings`。

## 组件轴（S2）

| component | 覆盖 |
|---|---|
| `dev_env` | 本机工具（lsof、Seatbelt 可用性与嵌套 apply / inherit 语义等） |
| `install` | Desktop 基线、二进制/executor 相对 pin 的指纹与 harness 能力 |
| `buzz_runtime` | 实例身份目录、执行器 home、**凭据文件存在性**、工作区、策略 |
| `external_deps` | 声明依赖与未做的上游/对话面（多为 unverified） |
| `proxy` | **Desktop ACP 进程/绑定代理 vs CLI/诊断进程代理对照** |

### 死代理 ≠ auth 缺失

- `grok_credentials_files*`：仅检查 `GROK_HOME` 下 `config.toml` / `auth.json` **文件是否存在**；不读内容、不发 LLM。
- `proxy_contrast` / `proxy_tcp:*`：对照 Desktop `managed-agents.json` 中绑定 `env_vars` 与当前 CLI 进程代理环境的**键名**及脱敏端点（**仅 host:port**）；`diagnose` 可对声明端点做 TCP 连接超时探测。
- 当凭据文件存在但代理不可达时，失败归因到 `proxy`（或 Desktop 代理 fail/unverified），**不得**仅报成 auth 文件失败。
- 不回显令牌、完整 URL 用户信息或进程环境机密值。

安装差异按实例 pin / 部署目标判断，不以仓库 HEAD 代替实际运行版本。

macOS `tool_seatbelt` 不只报 `sandbox-exec` 存在：`tool_seatbelt_nested` 会做廉价的二次 `sandbox_apply` 探测。development 启动在进程已 confined 时继承现有 Seatbelt，不再套第二层 `sandbox-exec`；Grok 在该外层下设 `GROK_SANDBOX=off`，避免再走 Grok 自己的 Seatbelt。嵌套 apply 失败时检查仍可通过，但 summary 必须写明 inherit-only，不得只报「present」。business / `production_write=true` 仍不包裹 sandbox-exec，也不写入 `GROK_SANDBOX`。



## 频道只读（S3）

桌面控制失败时，优先复用既有授权下的 Buzz CLI `channels` / `messages` **只读**路径做排查。

- CLI 频道读取成功 **≠** 客户端 Activity / UI 验收通过。
- 认证不可用、目标不可见或不存在须给出具体失败原因。
- 只读路径不发送业务消息；证据中不泄露凭据。

## 目录 vs Git（S4）

| 场景 | 预期 |
|---|---|
| 真实 Git 仓库 | 报告实际 `git` 状态 |
| 非仓库资料/服务目录 | **不适用（na）**，不是「Git 不可用」 |
| Git 命令/访问/执行失败 | 报告相应故障 |

本票 Runtime/文档只标定边界（见 check `git_directory_boundary`）；**不**改写业务提示词内容。

## Skill / 文档一致（S5）

须与下列表述对齐：

1. CLI 帮助与 JSON（`depth`、`checks`、`coverage`、`unverified_surfaces`）
2. 本功能地图与 `SKILL.md`
3. 仓库 `README.md`
4. `docs/runbook.md`

服务连接、模型请求、角色收发、线程归属、Activity 各自需要对应证据，或明确标为 `unverified`。CLI 返回成功、进程存在或本地记录读写 **不能** 代替未执行的真实功能验证。正向与依赖失败场景均须可复核；未测项不得标 pass。

## 验收命令提示

```sh
buzz-team --instance /absolute/instance doctor
buzz-team --instance /absolute/instance diagnose
```

单元覆盖见 `tests/test_health.py`（分类字段、doctor≠扁平 diagnose、auth 文件缺失消息 ≠ 代理失败、代理对照/不可达归因）。Desktop ACP 活体代理对照由 Hogan 复验。

## Desktop 代理对照

`diagnose` 必须同时看 managed-agents **binding** `env_vars` 与 live ACP **进程**环境（`runtime_pid`）；仅 binding 键不能覆盖 Desktop 烘焙死代理事故。死代理不得只报成 auth 缺失。

`desktop_agent_pids` 只计入 `os.kill(pid, 0)` 仍存活的 ACP pid。agent-pid 文件指向已退出进程时，对应 `desktop_agent_pid:*` 为 **fail**（顶层 `ok` 为 false），不得仅凭 `pid>0` 报 live / 假绿。活 pid 仍通过该检查。
