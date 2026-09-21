# 任务会话（#6）

## 入口

使用仓库外非 editable 安装的 `buzz-team --instance INSTANCE session ...`。

## 通过条件

1. 同一身份和范围绑定任务 A、B 后，交替解析仍返回各自 session，输出不含另一任务的正文。
2. 相同绑定重复执行幂等；改变 session、workspace、identity 或 scope 的冲突绑定退出码为 2，且旧映射不变。
3. 删除或破坏映射文件后解析失败，不发送任何执行请求；恢复有效文件后原映射可解析。
4. DM/频道既有路由测试和现有测试套件通过。

## 证据

记录命令、返回码、脱敏 task/session 标识和映射文件权限；不记录认证、prompt 或会话正文。
