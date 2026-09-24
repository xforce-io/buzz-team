# 停用本地 fork，记下上游 pin

状态：Draft

## 1 背景

[Issue #44](https://github.com/xforce-io/buzz-team/issues/44)。生产 relay 是 `buzz-local:4937-activity-recovery`。运行中的 `buzz-acp` 与 Desktop 自带二进制 SHA 不同。

## 2 名词解释

[兼容清单](../glossary.md) 的 `observed_baseline` 仍是正在跑的本地 fork。未应用的目标写在同一文件的 `upstream_pin`。[已知降级](../glossary.md) 只用于已经写明边界的项；未测不占用这个标记。

## 3 目标与非目标

目标：未提交的 fork 改动归档为可校验补丁且部署数为 0；目标 `buzz-acp` SHA 与官方 relay tag、digest 写进记录；仓库写明开源组件不 fork。

非目标：在未授权时切换生产 relay 或 9 个进程；把补丁部署回去；用滚动 `:main` 当 pin。

## 4 能力

### 4.1 UI/UX

N/A。无新页面。频道收发与 Activity 标记见 `docs/activity-catalog.md`。

## 5 思路与折衷

先归档再谈切换。relay pin 用与现库迁移 0045 对齐的官方镜像 `ghcr.io/block/buzz:sha-c507a4d`，不用 2026-08-08 的 `0.2.1`，也不用滚动的 `:main`。`buzz-acp` pin 用这次 Desktop 包内文件的 SHA，不写成「永远等于 Desktop 当前文件」。

放弃：把本地镜像继续当作生产事实源。

## 6 架构

补丁在 `docs/archive/44-local-fork/`。目标版本在 `docs/runbooks/44-upstream-pin.md`。规则在 `AGENTS.md`。主路径是记录与归档。失败路径是未授权的切换：不执行，并在发布记录里标 BLOCKED。

## 7 模块

N/A。

## 8 API/CLI

N/A。

## 9 边界

补丁不含凭据。部署数为 0。9/9 进程对齐只在真正切换之后才成立。

## 10 迁移/兼容/回滚

未切换，因此没有新的运行态需要回滚。记录本身的回滚是撤回本文件所在提交。

## 11 测试计划

- E2E：`.agents/skills/verify-buzz-team/features/upstream-pin.md` 对 S1、S2、S3。
- Integration：N/A。
- Unit：N/A。归档是补丁文件，校验值写在 MANIFEST。

## 12 开放问题

生产切换与默认分支合入尚未授权。

## 13 关联

#45 共用 Activity 标记。#24 的在线路径不在本票。
