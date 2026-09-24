# 桌面库存检查（Issue #46 · S1–S3）

`doctor` 调用 `health.run`，其中 `classify_desktop_inventory` 对照本机实例与 Desktop `managed-agents.json`。检查不删除任何行。

## S1 废弃入口

公钥为空且带启动命令的行使 `inventory_empty_pubkey:*` 为 fail，包括指向 `grok-acp-wrapper` 的行。从库存移除这些行是运维动作；doctor 只判定，不改文件。本票未授权删除，S1 保持 fail。

## S2 四类失败与实例外行

| 异常 | 检查 |
|---|---|
| 缺失 | `inventory_missing:*` fail |
| 空公钥 | `inventory_empty_pubkey:*` fail |
| 重复入口 | `inventory_duplicate:*` fail |
| 绑定不符 | `inventory_binding_mismatch:*` fail |

`inventory_non_instance` 为 pass，summary 含行数与 `not deleted`。同名不当作同一公钥。

## S3 重复行往返

在隔离库存副本追加一条相同公钥与 relay 的启动行后，`health.run(..., depth="doctor")` 的 `ok` 为 false，且出现一条 `inventory_duplicate:*`。写回原字节后，失败 id 集合与追加前相同，不再有 `inventory_duplicate:*`，文件字节与追加前一致。这里不要求整份 doctor 在每个平台都是 `ok=true`。

## 入口

```sh
PYTHONPATH=src:tests python3 -m unittest tests.test_health.InventoryDoctorTests
```
