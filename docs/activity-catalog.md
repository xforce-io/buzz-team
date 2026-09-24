# Activity 标记

与 #44、#45 共用。typing 不记为 Activity 通过。未测项写「未执行」，不写成已知降级，也不计入通过。

## 两态

| 项 | 标记 | 证据 |
|---|---|---|
| observer 超预算帧 | 已知降级 | 上游 `OBSERVER_MAX_PLAINTEXT_LEN` 为 65536−128。超出该预算的帧在官方 codec 上失败。本地 fork 只把裁剪预算对齐到这个上限。 |

| 上游频道收发 | 已规避 | 2026-09-25 生产 relay 已是 `ghcr.io/block/buzz:sha-c507a4d`。炼丹房收到并读回「上游 relay 收发核对」，event `f1b965d45451b62b`。 |

## 未执行

| 项 | 标记 | 证据 |
|---|---|---|
| Desktop Activity 面板 | 未执行 | 没有单独的面板取证。 |
| 直接成员的 owner 回填 | 未执行 | 成员名单未改。这一项属于 #45 S1。 |
