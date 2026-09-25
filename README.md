# buzz-team

buzz-team 为 Buzz Desktop 管理的本机 Grok 身份提供 Seatbelt 薄入口和只读诊断。身份、凭据、作者准入、会话、消息、ACP 进程与生命周期由 Buzz Desktop 和上游 `buzz-acp` 管理。

## 运行链路

```text
Buzz Desktop → Desktop 自带 buzz-acp → buzz-team-thin → Grok
```

`buzz-team-thin` 不代理 ACP stdio，不解析 Grok 私有通知，也不保存任务、turn 或会话状态。没有 Seatbelt 或策略无效时拒绝启动。开发身份与业务身份都须提供本机 Seatbelt 策略。

## 安装与配置

Python 3.11+。从本仓库构建普通 wheel 并安装到仓库外的固定位置。在 Desktop 的 **Agent harness** 中登记 `buzz-team-thin` 的绝对路径和原 Grok `agent … stdio` 参数；**ACP command** 保持 Desktop 自带 `buzz-acp`。逐身份提供原 `GROK_HOME`、`GROK_ACP_CWD` 和新 `BUZZ_TEAM_POLICY_PATH`。策略格式、按身份预览及回退见[运行手册](docs/runbook.md)。

`buzz-team doctor --inventory <Desktop 库存路径> --policies <策略目录>` 只读检查可识别的重复启动身份与本机策略。未知库存结构报告 `unverified`，不写 Desktop 数据。消息请直接使用官方 `buzz` CLI；身份启停在 Desktop 中操作。

## 项目边界

源码不含真实身份、公钥、凭据、生产路径或实例状态。上游版本和镜像 digest 写入部署记录，不作为本包启动门禁。历史设计和证据保留在 Git 历史；当前边界见 [#53 设计](docs/design/53-remove-acp-middle-layer.md)及[名词表](docs/glossary.md)。
