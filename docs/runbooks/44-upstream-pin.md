# 上游版本记录（未切换）

本次 pin 的目标，不是当前正在跑的进程。机器可读字段是 `src/buzz_team/compatibility.json` 的 `upstream_pin`。`observed_baseline.harness_sha256` 仍是本地 fork，doctor 继续按它对照现网二进制。

| 项 | 记录 |
|---|---|
| Desktop 自带 `buzz-acp` | `/Applications/Buzz.app/Contents/MacOS/buzz-acp` |
| Desktop SHA256 | `c114569d8f79accbfc44671366f46dd7cb8f91ffc0c0aec7698e3af06c763b64`（0.5.25；早先的 `7c52822c…` 已过时） |
| 官方 relay 镜像 | `ghcr.io/block/buzz:sha-c507a4d` |
| 官方 relay index digest | `sha256:1cf32474cb798ab2dec07b60835424c5895c4edf49b38f24ef052860c447d19f` |
| 对应提交 | `c507a4d488ca27796e78d876b9c24ee38442cc1b`（2026-09-16） |
| 补丁部署数 | 0 |

`sha-c507a4d` 是上游 CI 推到 `ghcr.io/block/buzz` 的不可变标签，index 含 `linux/arm64` 与 `linux/amd64`。origin 上没有比 `relay-v0.2.1` 更新的 `relay-v*` 标签，所以不能用更新的 semver 代替它。

## 拒绝 0.2.1

`ghcr.io/block/buzz:0.2.1`（index `sha256:4e31b7c7abb7d00b6f513dc559e58d2b980416f1dc400aa01bcf762cf2989cfc`，git `relay-v0.2.1` = `6e5c462`，2026-08-08）不再是切换目标。该提交的迁移停在 `0028_long_reaction_payloads.sql`。`c507a4d` 在它之后，多出 `0029`–`0045`。`:latest` 目前与 `0.2.1` 同一个 index，同样不能用。`:main` 是滚动标签，指向 2026-09-23 的 `d01e5f8`（index `sha256:295bf4f5fa93fb253c6f40cbdb7d5d391895240314469d0b49d8105d78126a83`），迁移已到 `0049`，这次不选。

## 迁移与回退核对（2026-09-25，未切换）

生产库 `buzz-prod-postgres` 的 `_sqlx_migrations`：成功 45 条，最高 version 45，description 为 `retain push revocation tombstones`。version 29–45 与 `c507a4d` 上 `0029`–`0045` 的文件名一致。该提交的 `migrations/` 共 45 个文件，没有 `0046` 及以后。本地 fork 归档补丁不改迁移文件。

因此把运行中的镜像换成 `sha-c507a4d` 时，schema 集合与现库相同，不需要再执行迁移，也不需要把库从 0045 往回迁。没有在生产库或副本上启动这只镜像。schema 回退到 `0.2.1` 没有执行，也不作为回退路径。

镜像回退目标仍是当前生产镜像 `buzz-local:4937-activity-recovery`（`sha256:df31bcb1b77426e7688376a57e12d86c49879b9b66f0cfe542c3575df7c6af3d`）。切换还没有做。

## 2026-09-25 已切换

生产 relay 容器 `buzz-prod-relay-1` 已换成 `ghcr.io/block/buzz:sha-c507a4d@sha256:1cf32474cb798ab2dec07b60835424c5895c4edf49b38f24ef052860c447d19f`。启动日志有 `Database migrations complete`。`_sqlx_migrations` 仍是成功 45 条，最高 version 45。健康检查为 running healthy。

Desktop 现为 0.5.25。包内 `buzz-acp` 的 SHA256 是 `c114569d8f79accbfc44671366f46dd7cb8f91ffc0c0aec7698e3af06c763b64`，不再是早先记下的 `7c52822c…`。9 个本实例身份的日志在切换后都出现 `presence set to online`，进程二进制是这个 Desktop 文件。回退镜像仍是备份里的 `buzz-local:4937-activity-recovery`。库存备份在 `/Users/xupeng/lab/buzz/backups/20260925-cutover/`。

炼丹房 `9bdc9fa2-48b7-4352-8b1f-7baf70ba6bd3` 在新 relay 上收发了一条「上游 relay 收发核对」，event `f1b965d45451b62b`。Activity 面板没有单独取证。合入默认分支没有做。

Desktop 以后如果更新，上面的 SHA 不会自动跟着变。9/9 对齐指的是对齐这次记下的 SHA。
