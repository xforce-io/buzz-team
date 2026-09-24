# 上游版本记录（未切换）

本次 pin 的目标，不是当前正在跑的进程。机器可读字段是 `src/buzz_team/compatibility.json` 的 `upstream_pin`。`observed_baseline.harness_sha256` 仍是本地 fork，doctor 继续按它对照现网二进制。

| 项 | 记录 |
|---|---|
| Desktop 自带 `buzz-acp` | `/Applications/Buzz.app/Contents/MacOS/buzz-acp` |
| Desktop SHA256 | `7c52822c5e450d99b421d4f9616ad573453b676cedc1a893720faeb2e7455a3c` |
| 官方 relay tag | `ghcr.io/block/buzz:0.2.1` |
| 官方 relay index digest | `sha256:4e31b7c7abb7d00b6f513dc559e58d2b980416f1dc400aa01bcf762cf2989cfc` |
| 对应 git tag | `relay-v0.2.1` |
| 补丁部署数 | 0 |

当前生产仍是本地镜像 `buzz-local:4937-activity-recovery`（`sha256:df31bcb1b77426e7688376a57e12d86c49879b9b66f0cfe542c3575df7c6af3d`）。9 个运行中的 `buzz-acp` 仍是 `e0d7bbcfc3128657ef5442e478629f36f9f89944b77920c13422994272a95366`。切换生产和合入默认分支都还没有授权。

`ghcr.io/block/buzz:main` 是滚动标签，不是这次 pin。`v0.5.2` 在 ghcr 上不存在。

Desktop 以后如果更新，上面的 SHA 不会自动跟着变。9/9 对齐指的是对齐这次记下的 SHA。
