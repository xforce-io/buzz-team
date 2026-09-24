# 角色头衔绑定周衡 p（#33 S1）

## 入口

仓库外非 editable 安装的 `buzz-team --instance INSTANCE wake resolve|decide`。唯一配置面：实例私有 `agents.<identity>.mention_aliases`（精确 token `项目经理` 只挂周衡）。不新增 `role_titles`。真实 pubkey / 生产 alias 不得写入 git。

S1 证据面 **A**：本仓解析 JSON 含 `pubkey` 即为验收。Online ACP 只认 `#p`；纯正文 `@项目经理` 无 `#p` 不醒，**不**标 S1 fail。

## 通过条件

1. 实例把 `项目经理` 只挂周衡后：`wake resolve --body "请 @项目经理 开窗"` 的 `resolved` 恰好 1 条，且 `pubkey` 等于该身份 `agents.*.pubkey`。
2. 同正文：周衡 `wake decide` 为 `allowed=true` / `reason=mentioned`，并带 `identity` / `pubkey` / `tokens=["项目经理"]`。方维 `not_mentioned`，不发明头衔 p。
3. `@「项目经理」`、`@项目经理，`（全角逗号）、双方同挂 alias、`--mentions` 非空：不命中或 fail-closed（冲突 / structured mentions unsupported）。
4. `single_owner` / `dm` / `not_mentioned` 不带解析 p。不打开结构化 mention。

## 证据

记录命令、返回码、`{token, identity, pubkey}` 或 `{allowed, reason, pubkey?}`；不记录认证、prompt。CLI 解析成功不能冒充 Desktop ACP `#p` mentioned。未实跑不得 pass。
