# #53 S2 薄运行链路

1. 选无活跃 turn 的身份，记录原配置；在 Desktop 用自定义 Agent harness 指向冻结候选 `buzz-team-thin`，ACP command 保持包内 `buzz-acp`，策略使用原 home。
2. 在真实频道点名该身份，观察原线程回复、Activity 边界和启动日志；确认 Grok 子进程通过唯一薄入口且无 ACP stdio 代理。
3. 用该身份的策略检查身份目录允许写、保护路径拒写和符号链接逃逸拒写。开发与业务分别取证；按身份推广至 2/2 和 7/7。
4. 若任何身份失败，按原配置回退该身份并确认重新 Running 和回复。记录 home/inode 未变。
