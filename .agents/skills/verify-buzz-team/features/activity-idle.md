# Activity 与 idle（Issue #45 · S1–S3）

## S1 owner

测试身份退出直接 relay 成员，只走 NIP-OA 委托，然后对目标频道各完成一次读取和一条回复。成功后把该项标为已规避。未改成员名单时保持未执行，S1 为 fail。2026-09-25 沈予在 `relay_members` 为 0 时仍凭 `BUZZ_AUTH_TAG` 登记 owner，订阅炼丹房并回「成员规避完成」；核对后该成员行已加回。

## S2 Activity 标记

`docs/activity-catalog.md` 的「两态」表只允许已规避或已知降级。未测项放在「未执行」，不能写成已知降级，也不能算 S2 通过。只要还存在未执行的 Activity 项，S2 为 fail。typing 不出现在通过列。

## S3 长静默

现行决策在 `docs/issue-38/IDLE-DECISION.md`：不 apply 1500→180。周衡 idle 保持 1500 秒。`BUZZ_ACP_MAX_TURN_DURATION=7200` 是另一项绝对 turn 上限，不是这次静默的标尺。通过条件是：一次 `sleep 1490`（低于 1500、高于已观测的 1222）在 ACP turn 内跑完，无 idle 取消，原线程只有一条完成回帖。harness 在 15 秒后把命令送去后台、turn 先合上的，不算通过。

## 入口

炼丹房频道消息。决策文件本身无命令。
