# 桌面库存检查（Issue #46 · S1–S3）

`doctor` 调用 `health.run`，其中 `classify_desktop_inventory` 对照本机实例与 Desktop `managed-agents.json`。检查不删除任何行。

## S1 废弃入口

确认指向 `grok-acp-wrapper` 且公钥为空的启动行使 `inventory_empty_pubkey:*` 为 fail。从库存移除这些行是运维动作；doctor 只判定，不改文件。移除并经 Desktop 回写后，每个本机实例身份应只剩一行。

## S2 四类失败与实例外行

| 异常 | 检查 |
|---|---|
| 缺失 | `inventory_missing:*` fail |
| 空公钥 | `inventory_empty_pubkey:*` fail |
| 重复入口 | `inventory_duplicate:*` fail |
| 绑定不符 | `inventory_binding_mismatch:*` fail |

`inventory_non_instance` 为 pass，summary 含行数与 `not deleted`。同名不当作同一公钥。

## S3 重复行往返

在隔离库存副本追加一条相同公钥与 relay 的启动行后，`health.run(..., depth="doctor")` 的 `ok` 为 false。写回原字节后 `ok` 为 true，且文件与追加前一致。

## 入口

```sh
PYTHONPATH=src:tests python3 -m unittest tests.test_health.InventoryDoctorTests
```
