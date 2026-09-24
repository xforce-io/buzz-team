# 提及确认 👀（#33 S2）

## 入口

`buzz-team --instance INSTANCE wake ack --identity ID --post-ref EVENT [--body TEXT] [--channel CHANNEL]`。发送缝校验 `binaries.buzz` pin 后调用已有 `buzz reactions add --event <hex64> --emoji 👀`。不改 `block/buzz`，不发明 event id。

S2 以 CLI `wake ack` 验收。等价信号关闭：必须 UI 或 `reactions get` 看见真实 👀。CLI stdout 单独不能冒充 Desktop UI。

## 通过条件

1. `--post-ref` 必须是 64 位小写 hex。否则 exit 2，不调用 buzz。
2. 若给了 `--body`：必须先 resolve 命中该 identity；未命中不得发 👀。`--channel` 在 `--body` 在场时必填。
3. pin 不符、超时、buzz 非零：fail，不写 👀。
4. 成功 JSON：`{ "reacted": true, "emoji": "👀", "event_ref": "<12 hex>" }`（`event_ref` 为 sha256 前 12 位，不回传完整 event id）。
5. `enforceChannelWake` 在 `allowed` 且 `BUZZ_WAKE_POST_REF` 为合法 hex 时自动 ack 一次；同一进程同一 event 不连发。自动 ack 失败写 stderr JSON，**不**把 mentioned 改成 deny。
6. 禁止用 `messages send` / 熔断帖 / Activity tool 名冒充实反应。

## 证据

单元：mock / recorder CLI，断言 argv 为 `reactions add --event <hex> --emoji 👀`。活机（Hogan / Mac）：命中后 ≤30s UI 或 `reactions get` 可见 ≥1 条该身份 👀。未实跑 Desktop 不得标 E2E pass。
