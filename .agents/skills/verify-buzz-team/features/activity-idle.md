# Activity 与 idle（Issue #45 · S1–S3）

## S1 owner

测试身份退出直接 relay 成员，只走 NIP-OA 委托，然后对目标频道各完成一次读取和一条回复。成功后在 `docs/activity-catalog.md` 把该项标为已规避。未改成员名单时保持「未执行」。

## S2 Activity 标记

`docs/activity-catalog.md` 每一项是已规避或已知降级。typing 不出现在通过列。

## S3 长静默

`docs/issue-45/idle-decision.md` 写明不 apply 1500→180，且绝对 turn 上限另计。受控任务 `sleep 1490` 结束后原线程只有一条完成回帖，进程没有被 idle 撕掉。

## 入口

炼丹房频道消息。决策文件本身无命令。
