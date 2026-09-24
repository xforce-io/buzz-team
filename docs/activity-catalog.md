# Activity 标记

与 #44 S3、#45 S2 共用。typing 不记为 Activity 通过。

| 项 | 标记 | 证据 |
|---|---|---|
| 频道收发 | 已规避 | 2026-09-24 16:47:42 freeman 在炼丹房点名周衡（event `f79e57f8dcedd34e9a7eb9d321c17ad02903db2083919cc0789afded2b025bc8`）。16:48:05 周衡回「周衡在线」。会话 `01a0d299`，`grok-4.7`，`completed`。 |
| observer 超预算帧 | 已知降级 | 上游 `OBSERVER_MAX_PLAINTEXT_LEN` 为 65536−128。超出该预算的帧在官方 codec 上失败。本地 fork 只把裁剪预算对齐到这个上限，不能把更大的帧变成通过。 |
| Activity 面板 | 已知降级 | 上面一轮是 CLI 收发。没有单独的 Desktop Activity 面板取证。不用 typing 填这一项。 |
| 直接成员的 owner 回填 | 未执行 | 上游只在 NIP-OA 委托准入时记下 owner。规避步骤是：一个测试身份退出直接成员，只靠委托进入，然后读目标频道并回一条。本次没有改成员名单。当前 fork relay 上的「周衡在线」不能标成上游已规避。 |
