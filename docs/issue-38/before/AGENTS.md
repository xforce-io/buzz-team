# 炼丹房

这是 Buzz 私聊/频道的工作目录。不要扫描 `~/dev/github/buzz` 源码树，不要为闲聊读仓库。
被问到再动手。短答用当前对话，不要开工具。
处理 Issue、开票、设计、开发、审查、合入走 keel；开票/开工必须标明泳道 `cli-contract` / `hotfix` / `full`（见 lab `team/prompts/light-keel.md`）。禁止未选型时套五人开工仪式。

## 本机运行边界

统一说明：`/Users/xupeng/lab/buzz-team/AGENT_RUNTIME.md`。
代码任务使用本身份独立仓库的 worktree；不要在共享源码或生产检出目录开发、测试。
创建入口：`agent-worktree <任务名> --repo <已登记仓库>`，默认 detached；新分支需显式 `--branch feat/{issue-no}-{issue-desc}`。
权限失败请报告目标和操作，不改路径、不另起未受限进程绕过。
本身份可正常操作真实业务数据（如已确认的资料登记）；不需要逐次申请系统提权。部署、删除、恢复、批量覆盖等高影响操作仍需用户明确授权；已有授权继续有效，不重复索要。业务职责由身份提示决定。
