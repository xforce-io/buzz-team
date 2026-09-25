# 上游 pin（Issue #44 · S1–S3）

## S1 归档

`docs/archive/44-local-fork/MANIFEST.md` 列出每个补丁的 sha256。补丁部署数为 0。补丁内无凭据。

## S2 目标版本

`compatibility.json` 的 `upstream_pin` 与 `docs/runbooks/44-upstream-pin.md` 写下 Desktop `buzz-acp` SHA、`ghcr.io/block/buzz:sha-c507a4d` 和 index digest。`0.2.1` 写在 `rejected_relay`，不是切换目标。`status=applied` 时运行中的二进制应等于该 Desktop SHA。

## S3 收发与规则

`AGENTS.md` 写明「开源组件不 fork，本地只允许配置层规避」。切换后按 `docs/activity-catalog.md` 核对频道收发和 Activity 各项标记。真实 Desktop 中须看见 Thinking 或工具调用，typing 不是通过。把截图或 UI 摘录、测试消息标识及候选 SHA 存在实例 `evidence/<candidate_sha>/`；缺少该精确 SHA 的客户端证据时，S3 不记 pass。

## 入口

读上述文件及 `docs/runbooks/44-upstream-pin.md`，核对当前 relay 镜像 digest、Desktop `buzz-acp` 与 CLI 指纹、9 个身份运行态及实例 doctor。
