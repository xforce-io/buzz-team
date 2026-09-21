# 安装、预览迁移与发布

## 所有权与认证

Desktop 管理 agent 生命周期，buzz-team 不运行额外守护进程。通用包安装到实例之外，实例仅含私有配置、薄入口、备份及证据。执行器认证和会话保持原地；不复制、不改写、不回退 auth.json，不调用登录命令。

## 安装

使用 Python >=3.11 创建仓库外虚拟环境，通过 `python -m pip install --no-cache-dir <源码目录>` 或 `uv pip install --no-cache --python <虚拟环境/python> <源码目录>` 非 editable 安装。记录实际源 SHA；工作树必须干净。同版本本地源码可能命中旧构建缓存，必须禁用缓存，并逐文件比较安装后的 `buzz_team` 与候选 `src/buzz_team`（忽略 `__pycache__`）；目录名或版本号不能替代产物核验。下文 `buzz-team` 指该安装生成的绝对可执行文件路径，`INSTANCE` 等参数由操作者填写，不预置机器路径。

```sh
buzz-team --instance /absolute/instance init --legacy /absolute/legacy/runtime.local.json --desktop-config /absolute/managed-agents.json --app /Applications/Buzz.app
buzz-team --instance /absolute/instance prepare
buzz-team --instance /absolute/instance doctor
buzz-team --instance /absolute/instance status
```

init 不绑定客户端，prepare 不重写身份状态。路径不得重叠。已有实例拒绝覆盖。不要拷贝整个旧目录。

## 预合入验证环境

本项目允许有界的**本机迁移预览**：使用现有 Desktop 和相同身份状态，先观察空闲、停止旧进程，再临时切换新绑定，绝不启动并行身份消费者。该预览用于 S3/S4，不算生产发布；完成后恢复旧绑定。用户已批准迁移预览和原地认证复用；真实业务变更不在授权范围。

```sh
buzz-team --instance /absolute/instance stop --idle-confirmed
buzz-team --instance /absolute/instance status
buzz-team --instance /absolute/instance bind
buzz-team --instance /absolute/instance start
```

status 必须确认进程退出；bind 也会强制检查。保存返回的 receipt 路径，按项目验证手册完成客户端验证。进程尚未退出时等待，不能强杀活跃任务。CLI start 返回请求已发出，不代表客户端健康通过。

## 回退

```sh
buzz-team --instance /absolute/instance stop --idle-confirmed
buzz-team --instance /absolute/instance rollback --receipt /absolute/instance/backups/receipt-id/receipt.json
open -a /Applications/Buzz.app
```

回退后 CLI start 会因新实例未绑定而拒绝，使用 Desktop 正常入口启动旧环境。rollback 只还原本次修改的绑定字段，保留 Desktop 时间戳和无关设置更新；这些绑定字段本身若被后续修改则拒绝覆盖，交操作者核对。不可整体覆盖后续设置或恢复备份 OAuth。

## 正式发布

冻结候选 → 测试与客户端预览 → 独立审查 PASS → 当前候选人工批准 → CI/交付校验 → 合入 → 从合入版本安装 → 空闲停机切换 → 客户端健康核验。升级安装放实例之外；不改写旧安装以保留回退能力。不满足门禁不能把预览称作已发布。

## 健康检查语义

`doctor` 做静态/安装预检与 Desktop↔CLI 代理键对照；`diagnose` 共用同一内核，并增加已声明代理端点的 TCP 探测及 `unverified_surfaces` 列表。输出含 `checks[{id,status,component,summary}]`，`status` 为 pass / fail / unverified / na。顶层 `ok` **仅当无 fail**；存在 unverified **不**表示整体健康。

- `grok_credentials_files`：仅检查 auth.json / config.toml 文件存在，与代理可达性、上游请求分开。
- 死代理或端点不可达归因到 `proxy` 组件，不得只报成 auth 缺失。
- CLI 频道/消息只读成功 ≠ Desktop Activity/UI 通过；静态检查 ≠ 角色对话验证。
- Git：真实仓库报告状态；非仓库目录为不适用（na），不是「Git 不可用」。详见验证 Skill `features/health.md`。

```sh
buzz-team --instance /absolute/instance doctor
buzz-team --instance /absolute/instance diagnose
```

## 已知限制

受限身份的沙箱是身份级，不是任务级；具有 production_write 的身份沿用原有权限。尚无完整 skills 白名单或 memory ready 门禁。doctor/diagnose 的兼容指纹与代理对照不证明模型质量、缓存效率、角色对话或客户端 Activity 端到端成功。这些项目以独立 Issue 跟踪。
