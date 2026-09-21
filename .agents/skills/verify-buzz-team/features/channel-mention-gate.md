# 频道点名门控（#15 S1）

## 入口

仓库外非 editable 安装的 `buzz-team --instance INSTANCE wake decide`；真客户端走 Desktop ACP 频道路径。实例私有 `channel_wake` 与 `mention_aliases` 不得写入 git。

Desktop 剩余钩子：ACP 唤醒须注入 `BUZZ_WAKE_SURFACE=stream`、`BUZZ_WAKE_CHANNEL`、`BUZZ_WAKE_POST_REF`、`BUZZ_WAKE_BODY`。已配置门控而缺这些变量时 launch fail-closed。本票不实现 #16 映射/ledger。

## 通过条件

1. 多身份 Online 的真实频道里，不含本身份 `@alias` 的讨论帖：该身份执行向 tool_call = 0，默认静默。
2. 精确 `@alias` 命中时仅该身份进入执行；其它身份仍为 0。
3. `@freeman` / `@human` 不唤醒任何 agent。`single_owner_identity` 只在该频道、且帖内无任何可解析 agent 点名时生效。
4. 传入结构化 mention、未知频道类型、别名冲突：不启动执行器。
5. 线程回复不继承父帖 @；每帖独立判定。

## 证据

记录命令、返回码、`{allowed, reason}`、Desktop Activity 是否出现执行向工具；不记录认证、prompt 或会话正文。CLI 只读成功不能冒充 Desktop UI。
