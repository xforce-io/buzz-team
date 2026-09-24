# 上游 pin（Issue #44 · S1–S3）

## S1 归档

`docs/archive/44-local-fork/MANIFEST.md` 列出每个补丁的 sha256。补丁部署数为 0。补丁内无凭据。

## S2 目标版本

`compatibility.json` 的 `upstream_pin` 与 `docs/runbooks/44-upstream-pin.md` 写下 Desktop `buzz-acp` SHA、`ghcr.io/block/buzz:sha-c507a4d` 和 index digest。`0.2.1` 写在 `rejected_relay`，不是切换目标。`observed_baseline.harness_sha256` 仍是正在跑的本地 fork。未切换时 S2 为 fail。

## S3 收发与规则

`AGENTS.md` 只写「开源组件不 fork」。`docs/activity-catalog.md` 在切换前把频道收发和 Activity 面板标为未执行。S3 在 S2 完成前为 fail。typing 不是通过。

## 入口

读上述文件。运行态切换不在未授权时执行。
