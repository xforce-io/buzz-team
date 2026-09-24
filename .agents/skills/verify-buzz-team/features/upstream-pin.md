# 上游 pin（Issue #44 · S1–S3）

## S1 归档

`docs/archive/44-local-fork/MANIFEST.md` 列出每个补丁的 sha256。补丁部署数为 0。补丁内无凭据。

## S2 目标版本

`docs/runbooks/44-upstream-pin.md` 写下 Desktop `buzz-acp` SHA、`ghcr.io/block/buzz:0.2.1` 和 index digest。未授权时不切换正在运行的 9 个进程和本地 relay。

## S3 收发与规则

`AGENTS.md` 写明开源组件不 fork，规避只在配置层。`docs/activity-catalog.md` 给频道收发和 Activity 项标已规避或已知降级。typing 不是通过。

## 入口

读上述文件。运行态切换不在未授权时执行。
