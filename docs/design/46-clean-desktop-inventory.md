# 桌面库存检查

状态：Draft

## 1 背景

[Issue #46](https://github.com/xforce-io/buzz-team/issues/46)。`doctor` 今天用 `desktop.selected_rows` 跳过空公钥行，因此旧 `grok-acp-wrapper` 启动行可以与本机实例身份并存而仍报通过。

## 2 名词解释

[桌面库存](../glossary.md)。本设计不把同名行推断为同一公钥。

## 3 目标与非目标

目标：本机实例身份的缺失、空公钥、重复入口、绑定不符使 `doctor` 失败；实例外行只报告、不删除。

非目标：删除实例外的 6 行；按同名合并公钥；在 doctor 里改写库存文件。

## 4 能力

### 4.1 UI/UX

N/A。无页面。操作者看到的是 `doctor` JSON：`ok` 与 `inventory_*` 检查。

## 5 思路与折衷

在现有 `health.run` 里先分类再做代理对照。空公钥的启动行算本机异常。没有启动命令、公钥也不属于本实例的行只报告。同名不合并公钥。

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
- `inventory_non_instance`（pass，含 `not deleted`）

## 9 边界

分类不删除行。同名不是同一公钥。实例外行不进入四类 fail。

## 10 迁移/兼容/回滚

N/A。不改库存文件格式。已有干净的单行绑定仍通过。

## 11 测试计划

- E2E：`.agents/skills/verify-buzz-team/features/inventory-doctor.md` 对 S1、S2、S3。
- Integration：`tests/test_health.py` 的 `InventoryDoctorTests` 调用 `health.run`。
- Unit：N/A。分类与 doctor 入口是同一条路径，不另写一份纯函数副本测试。

## 12 开放问题

确认废弃的 13 行从本机 Desktop 库存删除，要单独授权。本设计不执行删除。

## 13 关联

Issue #46。#35 的死 pid 检查保持不变。
