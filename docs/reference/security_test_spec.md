# 安全验收用例契约（S1–S9）

> 来源：原 Odoo 版 `M1模块设计.md` §9.3（第 747-761 行），对应 `架构设计.md` §4.13。
> 本文档为 FastAPI 版 `tests/test_security.py` 的**验收契约**——用例语义、验收标准 100% 继承，仅实现层从 Odoo 集成测试切换为 pytest + FastAPI TestClient + SQLAlchemy。
> **铁律**：S1–S9 任一失败 = 整体不通过，不得交付。安全用例优先级高于功能用例。

---

## 总则

- **除 S8（备份演练，需真实数据，M2 完成）外，全部在 M1 结束前通过。**
- 每个用例必须有对应的自动化测试（`tests/test_security.py`），不得仅靠人工核对。
- 用例编号 S1–S9 为永久标识，测试函数名须包含对应编号（如 `test_s1_source_unchanged`）。

---

## S1 · 导入不改源文件

| 项 | 内容 |
|---|---|
| **风险** | 导入代码写坏源文件（openpyxl 默认可写、可 `save()`），原始 Excel 不可重建 → 不可逆数据损失 |
| **操作** | 记录源文件 SHA256 → 执行导入 → 再算 SHA256 |
| **验收标准** | 两次哈希**完全相同** |
| **实现要点** | 所有 `load_workbook` 必须带 `read_only=True, data_only=True`；代码审查红线禁 `wb.save(` 写源文件；导入前后双次哈希校验 |
| **对应测试** | `test_s1_source_unchanged` |

## S2 · 源文件已归档

| 项 | 内容 |
|---|---|
| **风险** | 归档目录被误删，或源文件后来被改/删/挪，溯源断链 |
| **操作** | 导入后检查归档目录 |
| **验收标准** | 文件存在，且 SHA256 == `import_batch.file_hash` |
| **实现要点** | 归档放应用之外的独立受管目录 + 操作系统只读权限；归档即复制（原封不动），不改名不移动；`verify_archive()` 能发现人为篡改的归档文件 |
| **对应测试** | `test_s2_archive_consistent` |

## S3 · 重导不丢人工标注

| 项 | 内容 |
|---|---|
| **风险** | 重导摧毁人工标注（delete+insert 幂等），人工智慧资产永久丢失 |
| **操作** | 建批次 → 给 10 行填 `std_name`（B 类字段）→ 重导同一文件 |
| **验收标准** | 10 行 `std_name` **仍在**；返回计数 `preserved_manual >= 10` |
| **实现要点** | 分层 Upsert（A 类可覆盖、B 类禁静默覆盖）；B_FIELDS 常量定义在 `data/field_spec.py`，单一事实源；孤儿行进待确认不自动删 |
| **对应测试** | `test_s3_preserve_manual_on_reimport` |

## S4 · 删除可回收

| 项 | 内容 |
|---|---|
| **风险** | 手一抖点了删除，几千行数据 + 人工标注瞬间归零 |
| **操作** | 软删除批次 → 查回收站 → 还原 |
| **验收标准** | 回收站可见；还原后行数与删除前一致 |
| **实现要点** | 删除 = `active=False`（软删），不是物理删除；回收站可一键还原；硬删须先导出 CSV 快照，快照失败不得放行（Odoo 版 R1 缺陷教训，本项目从第一天锁死）；30 天宽限期 |
| **对应测试** | `test_s4_soft_delete_and_restore` |

## S5 · 修改可追溯

| 项 | 内容 |
|---|---|
| **风险** | 单价被改过但说不清谁改的、从多少改成多少，审计对不上 |
| **操作** | 改一条 `unit_rate_num` |
| **验收标准** | `audit_log` 出现该字段 `old → new` 记录，含操作人与时间 |
| **实现要点** | 所有写操作必带审计四元组（operator / reason / trace_id / timestamp）；B 类字段变更无 reason 则拒绝；`audit_log` 表 append-only |
| **对应测试** | `test_s5_audit_log_on_modify` |

## S6 · 批次校验和

| 项 | 内容 |
|---|---|
| **风险** | 入库总额与 Excel 合计不一致（解析漏行/重复行/公式错误），数据漂移 undetected |
| **操作** | 导入后比对 `checksum_total` 与 Excel 合计行 |
| **验收标准** | 差值 ≤ 0.01 元 或 ≤ 0.1% |
| **实现要点** | 导入时计算批次合计（quantity × unit_rate 求和），与 Excel 合计行比对；不一致标 warning 不阻断，但必须记录；批次校验和存入 `import_batch.checksum_total` |
| **对应测试** | `test_s6_batch_checksum` |

## S7 · 待审不污染

| 项 | 内容 |
|---|---|
| **风险** | 待审清单的报价是别人的、没定稿的、可能虚高的，混入历史均价后误差一轮轮放大 |
| **操作** | 先记历史均价 → 导入 `pending_review` 批次 → 再算均价 |
| **验收标准** | 均价**不变**（默认域已排除 `pending_review`） |
| **实现要点** | `data_source_type` 字段 required 且无默认值（导入向导强制选，不选不让入库）；历史均价默认只用 `completed`；`PRICE_STAT_TYPES` 常量在 `data/field_spec.py` |
| **对应测试** | `test_s7_pending_review_not_pollute` |

## S8 · 备份可恢复（M2）

| 项 | 内容 |
|---|---|
| **风险** | 备份存在但恢复不了，等于没有备份 |
| **操作** | 临时库恢复 `pg_dump` → 抽样 10 条 |
| **验收标准** | 与原始 Excel **逐字一致** |
| **实现要点** | 每季度一次真实恢复演练，结果记入 `docs/backup_drill.md`；**未演练过的备份视为无效**；3-2-1 备份策略（3 份副本 / 2 种介质 / 1 份异地）；加密密钥异地备份 |
| **对应测试** | 无自动化（人工演练），审查时须如实标注「S8 本季度已/未演练」 |

## S9 · 审计日志不可改

| 项 | 内容 |
|---|---|
| **风险** | 审计日志自身被篡改或删除，失去追溯价值，无法自证数据未被改 |
| **操作** | 调 `audit_log` 表的 update / delete |
| **验收标准** | **抛异常**；且数据库层 update/delete 权限均为 0（或应用层禁止） |
| **实现要点** | append-only 三重保障：①模型层/SQLAlchemy 事件监听禁止 update/delete；②权限层三角色均无 audit_log 写权限；③数据库层 REVOKE UPDATE/DELETE；应用服务绑定内网不暴露公网；仓库内无真实数据文件 |
| **对应测试** | `test_s9_audit_log_immutable` |

---

## 反向用例（N1–N4，待补，P1）

> 原 Odoo 版缺口：N1–N3 无自动化用例，随 M2+/M3 测试扩展补齐。

| 编号 | 用例 | 验收标准 |
|---|---|---|
| N1 | 导入含宏文件（.xlsm） | 直接拒收，不入库 |
| N2 | 导出超 1000 行 | 二次确认闸门触发，未确认不导出 |
| N3 | viewer 角色尝试导出 | 被拒绝（403） |
| N4 | 孤儿行不自动删 | 重导后孤儿行进待确认，不物理删除 |

---

## 用例与模块映射

| 模块 | 覆盖用例 |
|---|---|
| 导入服务（import_service） | S1, S2, S6 |
| 分层 Upsert（upsert_service） | S3, N4 |
| 批次管理（batch_service） | S4 |
| 审计服务（audit_service） | S5, S9 |
| 单价统计（price_service） | S7 |
| 备份策略（运维） | S8 |

---

## FastAPI 版实现差异说明

| Odoo 版 | FastAPI 版 |
|---|---|
| Odoo 集成测试（`--test-enable`） | pytest + FastAPI TestClient + SQLAlchemy |
| `odoo.exceptions.UserError` | `HTTPException(400/403)` 或自定义 `BusinessError` |
| Odoo `ir.model.access.csv` 权限 | FastAPI `Depends(require_role(...))` 依赖注入 |
| Odoo `mail.thread` 审计 | 自写 `audit_log` 表 + SQLAlchemy 事件监听 |
| Odoo `active=False` 软删 | SQLAlchemy `active` 列 + 查询过滤器 |
| Odoo 服务绑定 `127.0.0.1` | uvicorn 绑定 `127.0.0.1`（开发）/ Nginx 反向代理（生产） |

> **用例语义不变，仅实现层替换。** 验收标准（哈希一致、标注仍在、均价不变等）是永久契约，不因技术栈变化而放宽。
