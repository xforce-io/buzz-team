# 停用本地 fork，记下上游 pin

状态：Approved（2026-09-25，用户确认）；#53 后仅作历史设计归档。

本设计记录 #44 切换当时的模块、CLI 与验收路径。#53 已删除下文提到的 `instance.prepare`、`desktop.live_processes`、`buzz-team status/prepare` 和 `features/upstream-pin.md`；它们不再是可执行的现行操作。当前运行和回退边界见[运行手册](../runbook.md)及[#53 设计](53-remove-acp-middle-layer.md)。本文件中的版本、指纹与回退目标只适用于 2026-09-25 那次切换。

## 1 背景

[Issue #44](https://github.com/xforce-io/buzz-team/issues/44)。切换前生产 relay 是 `buzz-local:4937-activity-recovery`，运行中的 `buzz-acp` 与 Desktop 自带二进制 SHA 不同；2026-09-25 已按 `docs/archive/issue-44/upstream-cutover.md` 切换。

## 2 名词解释

[兼容清单](../glossary.md) 的 `observed_baseline` 记录当前 Desktop 0.5.25；已应用的上游目标写在同一文件的 `upstream_pin`。[已知降级](../glossary.md) 只用于已经写明边界的项；未测不占用这个标记。

## 3 目标与非目标

目标：未提交的 fork 改动归档为可校验补丁且部署数为 0；目标 `buzz-acp` SHA 与官方 relay tag、digest 写进记录；仓库写明开源组件不 fork。

非目标：把补丁部署回去；用滚动 `:main` 当 pin。

## 4 能力

### 4.1 UI/UX

N/A。无新页面。频道收发与 Activity 标记见 `docs/activity-catalog.md`。

## 5 思路与折衷

先归档再谈切换。relay pin 用与现库迁移 0045 对齐的官方镜像 `ghcr.io/block/buzz:sha-c507a4d`，不用 2026-08-08 的 `0.2.1`，也不用滚动的 `:main`。`buzz-acp` pin 用这次 Desktop 包内文件的 SHA，不写成「永远等于 Desktop 当前文件」。

放弃：把本地镜像继续当作生产事实源。

## 6 架构

补丁在 `docs/archive/44-local-fork/`。目标版本和切换、回退记录在 `docs/archive/issue-44/upstream-cutover.md`。规则在 `AGENTS.md`。进程检查把 Desktop 的内置 `acp_command=buzz-acp` 解析为包内程序，`prepare` 在 Desktop 运行时拒绝改写薄入口。主路径是归档、切换、核对运行态。失败路径是指纹或迁移不匹配：停止切换，按 runbook 回退。

## 7 模块

`desktop.live_processes` 识别 Desktop 内置 `buzz-acp`；`instance.prepare` 在 Desktop 有运行进程时拒绝改写薄入口。

## 8 API/CLI

`buzz-team status` 接受 Desktop 库存中的内置 `buzz-acp` 命令；`buzz-team prepare` 在 Desktop 运行时返回明确错误。其他相对启动命令仍拒绝。

## 9 边界

补丁不含凭据。部署数为 0。9/9 进程对齐仅针对这次 Desktop 0.5.25 包内 SHA。

## 10 迁移/兼容/回滚

2026-09-25 已切换。生产 relay 旧镜像与库存备份、迁移检查及回退目标见 `docs/archive/issue-44/upstream-cutover.md`；不得把 `0.2.1` 用作现库回退目标。buzz-team 自身 release 尚未切换。

## 11 测试计划

- E2E：`.agents/skills/verify-buzz-team/features/upstream-pin.md` 对 S1、S2、S3。
- Integration：进程检查与 `prepare` 的活动进程门禁。
- Unit：N/A。归档是补丁文件，校验值写在 MANIFEST。

## 12 开放问题

L1/L2 已由用户在 2026-09-25 确认；默认分支尚未合入。当前运行态记录须与精确候选 SHA 的验收分别核对。

## 13 关联

#45 共用 Activity 标记。#24 的在线路径不在本票。
