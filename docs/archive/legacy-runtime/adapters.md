> 历史运行层记录（#53 前）。下述模块已退出当前交付包，现行边界见 [运行手册](../../runbook.md)。

# Coding-agent 适配器契约

通用层负责身份、权限、目录、实例、Desktop 绑定；适配器负责执行器专用环境和现有 home 检查。ACP 参数由 Desktop 原绑定传入，不擅自改模型、effort 或会话策略。

| kind | 能力 | 当前状态 |
|---|---|---|
| grok | ACP stdio、原 home/认证/会话复用 | 迁移候选，需客户端验证 |
| acp-command | 显式命令与环境的 ACP stdio | 契约测试；不等于所有 ACP 产品认证 |
| Claude Code / Codex | 需对应 ACP 接入程序及专用能力核实 | 未认证，不接受假品牌适配器名 |

适配器实现 validate、home、environment、check；不得覆盖通用运行层拥有的环境。generic ACP 的 env 可用 `{executor_home}` 和 `{workspace}` 占位符，不进行 shell 求值。认证始终由执行器拥有，模块不安装、不获取、不刷新认证。

新增适配器必须有参数转发、home/身份隔离、缺失配置失败、认证不被改写和能力负向测试，再登记实测版本。支持某执行器不能仅凭可执行文件存在来宣布。
