# 本机薄入口运行手册

## 当前链路

Buzz Desktop 启动自带 `buzz-acp`；`buzz-acp` 通过 Desktop 的 Agent harness 配置启动 `buzz-team-thin`；薄入口施加 macOS Seatbelt 后 `exec` Grok。Desktop 管身份、凭据、会话、作者准入和进程生命周期。官方 `buzz` CLI 直接负责消息操作。

## 安装

将本仓库以普通 wheel 安装在仓库外目录，记录安装提交及上一个可用目录。Desktop 的自定义 Agent harness 选择安装后 `buzz-team-thin` 的绝对路径，Arguments 沿用原 `agent --always-approve --no-leader --reasoning-effort <值> stdio`。ACP command 保持 Desktop 自带 `buzz-acp`。不要把薄入口登记为 ACP command。

先在 Desktop Settings 中登记自定义 Agent harness，再单独编辑身份。当前 Desktop 在身份编辑弹窗内直接“Add custom harness…”会同时保存该身份，预览中曾清空其环境变量；每次保存后须检查变更摘要及原环境变量仍在，异常时先恢复原值，不重启该身份。

本机策略文件须在身份可写目录外，权限不允许 group/world 写。每个身份在 Desktop 环境变量中提供原 `GROK_HOME`、`GROK_ACP_CWD` 和 `BUZZ_TEAM_POLICY_PATH`。示例仅展示格式；实际路径在本机私有文件中填写：

```json
{
  "version": 1,
  "grok_home": "/absolute/identity/grok",
  "grok_executable": "/absolute/grok",
  "mode": "development",
  "write_paths": []
}
```

业务身份使用 `"mode": "business"` 并逐项列出批准的生产写路径；无需生产写入时可留空。开发身份在 `write_paths` 中逐项列出确需写入的项目路径。两种策略均允许本身份目录写入；`mode` 仅用于记录身份类别，不自动扩大权限。策略文件、Grok 可执行文件和其他身份 home 不得位于允许写入的根下。缺 Seatbelt、路径不存在、home 不匹配或策略无效时拒启。读取和网络能力沿用当前系统与上游行为，策略只限定文件写入。

## 逐身份预览

1. 记录目标身份原 Agent harness、ACP command、参数、环境、作者准入、home 和 Desktop 状态。确认无正在执行的 turn。
2. 在该身份的私有目录外写入策略文件，先运行 `buzz-team-thin agent --help` 验证执行路径，再用真实 Desktop 自定义 harness 只切该身份；其他身份保持原配置。
3. 核对 Desktop 日志里 ACP 命令仍为包内 `buzz-acp`，执行器为薄入口；发送一次真实提及并检查原线程回复。检查身份目录允许写、外部路径拒写、符号链接逃逸拒写。记录 Activity 已知降级。
4. 成功后按身份推广。失败时只在 Desktop 恢复该身份原 harness 与环境，等待其回到 Running 并核对回复；不要启动平行消费者，不复制认证文件。

## 只读诊断

```sh
buzz-team doctor --inventory '<Desktop managed-agents.json 路径>' --policies '<本机策略目录>'
```

`fail` 表示可识别的异常；`unverified` 表示未提供路径、不可读取或库存结构未知。`ok` 仅表示没有 `fail`。诊断不修改 Desktop 配置，也不能代替真实消息和沙箱验证。

## 官方升级

记录实际 Desktop、Grok、relay 版本和镜像 digest，按官方发布渠道及其回退方式升级。正常升级不修改本仓库代码或包内版本清单。升级后用原身份检查启动、回复和沙箱边界；上游公开契约不兼容时回退相应组件并反馈上游。
