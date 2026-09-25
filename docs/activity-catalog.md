# Activity 标记

与 #44、#45 共用。typing 不记为 Activity 通过。未测项写「未执行」，不写成已知降级，也不计入通过。

## 两态

| 项 | 标记 | 证据 |
|---|---|---|
| 上游频道收发 | 已规避 | 2026-09-25 生产 relay 已是 `ghcr.io/block/buzz:sha-c507a4d`。炼丹房收到并读回「上游 relay 收发核对」，event `f1b965d45451b62b`。 |
| 直接成员的 owner 回填 | 已规避 | 2026-09-25 沈予的直接 relay 成员记录清为 0；Desktop 重启后，上游 `buzz-acp` 凭 `BUZZ_AUTH_TAG` 登记 owner，订阅炼丹房，真实频道消息触发 Activity 并回到原线程。仅该试验身份持续应用；其他直接成员路径仍有上游缺口。 |
| 普通回合的 observer | 已规避 | 该回合日志有 `relay observer enabled`。没有把 typing 记为 Activity 通过。 |
| observer 超预算帧 | 已知降级 | 上游 `OBSERVER_MAX_PLAINTEXT_LEN` 为 65536−128。超出该预算的帧在官方 codec 上失败，面板上看不见。 |

typing 不是 Activity 通过。
