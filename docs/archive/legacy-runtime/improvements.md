> 历史运行层记录（#53 前）。下述模块已退出当前交付包，现行边界见 [运行手册](../../runbook.md)。

# 优化状态

本次迁移已经实现的保护必须以当前候选测试和验收为证，以下未实现项不算作迁移安全保证。

| 优先级 | 方向 | 当前边界 | 后续 Issue |
|---|---|---|---|
| P0 | 任务工作区强隔离 | 已迁移身份级沙箱与可选 worktree，未实现任务级强隔离 | [#2](https://github.com/xforce-io/buzz-team/issues/2) |
| P0 | SHA 验收门禁 | 尚未提供不可绕过的合入入口 | [#3](https://github.com/xforce-io/buzz-team/issues/3) |
| P1 | skills 白名单 | 保留现有技能行为；doctor 明确不认证白名单 | [#4](https://github.com/xforce-io/buzz-team/issues/4) |
| P1 | memory 身份及就绪 | 保留上游 memory 行为；本次不初始化/修改 core | [#5](https://github.com/xforce-io/buzz-team/issues/5) |
| P1 | 任务会话隔离 | 原会话策略和身份 home 原样复用 | [#6](https://github.com/xforce-io/buzz-team/issues/6) |
| P2 | 上下文预算与成本 | 不宣称缓存优化；建立专票验收 | [#7](https://github.com/xforce-io/buzz-team/issues/7) |

本票落实：通用代码/私有配置分离、显式适配器、认证原地复用、身份与权限校验、二进制指纹与能力检查、离线原子绑定、差异保护回退、客户端验证手册。
