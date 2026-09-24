# 切回上游后的 Activity 与 idle

状态：Draft

## 1 背景

[Issue #45](https://github.com/xforce-io/buzz-team/issues/45)。本地 fork 补上了直接成员的 NIP-OA owner 回填，并把 observer 明文预算对齐到 NIP-44 可加密上限。切回上游后这两处会回到上游行为。#38 曾准备把周衡 idle 从 1500 秒收到 180 秒，尚未 apply。

## 2 名词解释

[已知降级](../glossary.md)、[已规避](../glossary.md)。typing 不是 Activity 通过。

## 3 目标与非目标

目标：一份 Activity 标记；owner 缺口的配置规避步骤；在任何 1500→180 apply 之前改写 idle 决策，并保留单独的 turn 绝对上限。

非目标：部署上游 relay；把 typing 记成 Activity 通过；在本设计里放宽全部身份的 idle。

## 4 能力

### 4.1 UI/UX

N/A。无新页面。频道里能看到的是一次收发，以及静默任务的一句完成回帖。Activity 面板里超预算 observer 帧保持不可用。

## 5 思路与折衷

owner 缺口用「测试身份退出直接成员、只走 NIP-OA 委托」规避，不把 fork 补丁部署回去。observer 超预算帧写成已知降级。idle 维持周衡 1500 秒；绝对上限仍是 `BUZZ_ACP_MAX_TURN_DURATION`（现为 7200 秒），与 idle 分开。

放弃：先把 idle 收到 180 秒再观察。#38 已有约 1222 秒的静默挂起，180 秒会在合法长工具结束前撕掉会话。

## 6 架构

标记写在 `docs/activity-catalog.md`。idle 决策只写在 `docs/issue-38/IDLE-DECISION.md`。主路径：`sleep 1490` 在 ACP turn 内跑完并只回一条。失败路径：命令被送去后台、turn 先合上、idle 撕池，或出现第二条回帖，则 S3 不通过。

## 7 模块

N/A。本票不改运行时代码。

## 8 API/CLI

N/A。无新命令。成员变更沿用现有 relay 成员操作，本设计不新增接口。

## 9 边界

不改生产 relay 镜像。不删除现有直接成员，除非另有授权。静默任务只覆盖已测到的合法上限，不把 180 秒当成测量值。

## 10 迁移/兼容/回滚

idle 决策回滚就是继续维持现状，不需要 apply。成员规避若执行，回滚是把该测试身份加回直接成员。

## 11 测试计划

- E2E：`.agents/skills/verify-buzz-team/features/activity-idle.md` 对 S1、S2、S3。
- Integration：N/A。
- Unit：N/A。

## 12 开放问题

直接成员名单的移除尚未授权。未执行前，owner 项不能标已规避。

## 13 关联

#44 的 Activity 标记与本文同一份。#38 的 idle apply 等本文决策之后。
