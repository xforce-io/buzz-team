# 桌面库存检查

状态：Draft

## 1 背景

[Issue #46](https://github.com/xforce-io/buzz-team/issues/46)。原 `doctor` 只用 `desktop.selected_rows`，会跳过空公钥行，因此旧 `grok-acp-wrapper` 启动行曾与本机实例身份并存而仍报通过。13 条旧 wrapper 行已从本机库存清理，备份在实例目录。

## 2 名词解释

[桌面库存](../glossary.md)。本设计不把同名行推断为同一公钥。

## 3 目标与非目标

目标：本机实例身份的缺失、空公钥、重复入口、绑定不符使 `doctor` 失败；实例外行只报告、不删除。

非目标：删除实例外的 6 行；按同名合并公钥；在 doctor 里改写库存文件。

## 4 能力

### 4.1 UI/UX

N/A。无页面。操作者看到的是 `doctor` JSON：`ok` 与 `inventory_*` 检查。

## 5 思路与折衷

在现有 `health.run` 里先分类再做代理对照。空公钥的启动行算本机异常；无 relay、无 agent 启动命令、无运行标识和启动历史的 Desktop persona 定义只报告，即使 Desktop 填入默认 `acp_command=buzz-acp`。任何实际启动命令中的旧 wrapper 均 fail。身份由规范化的 relay 地址与公钥共同确定，同名不合并。

放弃：让 `selected_rows` 继续把重复和缺失收成一句「unreadable」，调用方无法分辨四类。

## 6 架构

`classify_desktop_inventory` 是纯函数。`health.run` → `_read_desktop_proxy_maps` 调用它。失败路径：任一条 `inventory_*` fail 则 `desktop_inventory` fail，`ok` 为 false，函数不写文件。主路径：每个实例身份恰好一行且绑定一致，分类检查无 fail。

## 7 模块

N/A。检查落在现有 health 模块。

## 8 API/CLI

`buzz-team doctor` 的检查集增加：

- `inventory_missing:<ref>`
- `inventory_empty_pubkey:<index>`
- `inventory_duplicate:<ref>`
- `inventory_binding_mismatch:<ref>`
- `inventory_deprecated_wrapper:<index>`（`agent_command` 或 `acp_command` 指向 `grok-acp-wrapper`，公钥可以不属于本实例）
- `inventory_non_instance`（pass，含 `not deleted`）

## 9 边界

分类不删除行。同名不是同一公钥。实例外、且启动命令不是 `grok-acp-wrapper` 的行不进入 fail。只改 `agent_command_override` 不算启动命令。

## 10 迁移/兼容/回滚

N/A。不改库存文件格式。已有干净的单行绑定仍通过。

## 11 测试计划

- E2E：`.agents/skills/verify-buzz-team/features/inventory-doctor.md` 对 S1、S2、S3。
- Integration：`tests/test_health.py` 的 `InventoryDoctorTests` 调用 `health.run`。
- Unit：N/A。分类与 doctor 入口是同一条路径，不另写一份纯函数副本测试。

## 12 开放问题

13 条旧 wrapper 行已清理，库存备份在实例目录。当前剩余 9 条本实例身份、4 条 persona 定义、2 条其他实例身份；本设计不删除后 6 条。L1/L2 仍为 Draft，合入须先取得真实批准。

## 13 关联

Issue #46。#35 的死 pid 检查保持不变。
