# 造价数据门户（FastAPI 版）

> **一句话定位**：面向造价咨询团队的「工程量清单历史单价数据门户」——用 FastAPI + PostgreSQL 把散落在各工程 Excel 里的清单项沉淀为可检索、可复用、可审计的成本资产，支持团队共享查询，可作为公司网页的一部分。核心回答一个问题：**「这个清单项，我们以前做过多少钱？」**

> 本项目从 Odoo 19 版（`zaojia_boq` 模块，M0–M3 已完成）迁移而来。业务契约、数据安全铁律、纯函数层（720 行）100% 继承；技术栈从 Odoo 切换为 FastAPI + SQLAlchemy + Jinja2。原 Odoo 版已归档：git tag `legacy-odoo-final`，数据库备份 `zaojia_db_20260905.dump`。

当前状态：**M0–M3 核心功能已完成**（M0 迁移准备 + M1 数据模型 + M2 导入查询 + M3 匹配确认），**匹配效率优化已完成**（第一阶段3项 + 第二阶段3项，三算法融合 + 学习引擎权重自适应），M4 成本库待启动。

---

## 目录

- [项目概览](#项目概览)
- [技术栈](#技术栈)
- [整体架构](#整体架构)
- [核心模块（M0–M4）](#核心模块m0m4)
- [关键设计机制](#关键设计机制)
- [文档索引](#文档索引)
- [里程碑路线图](#里程碑路线图)
- [快速启动](#快速启动)
- [许可与协作约定](#许可与协作约定)

---

## 项目概览

造价工程师日常手头有大量历史工程量清单 Excel，但「同类清单项历史单价」难以沉淀复用。本工具把它们统一入库，并用一套严谨的**数据性质分层 + 同类项聚合键（match_key）+ 审计溯源**机制，让历史单价可统计、可解释、可回溯。

| 维度 | 说明 |
|---|---|
| 核心价值 | 同类清单项历史单价聚合、可解释统计、审计溯源 |
| 目标用户 | 造价咨询团队（多人共享查询，对接公司 OA 统一登录） |
| 部署形态 | 公司内网服务器，可作为公司网页子路径/子域名嵌入 |
| 框架 | FastAPI + SQLAlchemy 2.0 + PostgreSQL 15 + Jinja2 模板 |
| 认证 | 公司 OA 统一登录（易达 ECMS，待厂商确认 SSO 协议）；开发期独立账号占位 |
| 当前状态 | M0–M3 核心功能 ✅ + 匹配效率优化 ✅ → M4 成本库 ⏸ |

---

## 技术栈

| 项 | 选择 | 理由 |
|---|---|---|
| Web 框架 | **FastAPI** | 异步高性能、自动 OpenAPI 文档、Pydantic 校验、AI 写代码质量高 |
| ORM | **SQLAlchemy 2.0** | 成熟稳定、显式事务、迁移工具 Alembic |
| 数据库 | **PostgreSQL 15+** | `numeric` 精确，无 SQLite REAL 退化 |
| 模板引擎 | **Jinja2** | 服务端渲染，AI 最熟、维护成本低；可渐进升级为前后端分离 |
| 纯函数层 | `data/` 目录 720 行（从 Odoo 版原样复用） | 零框架依赖，90 条 pytest 全绿作为回归基线 |
| 前端 | 深空科技设计系统（`app/static/demo/`，从 Odoo 版原样复用） | 主色 #4D7CFE / 辅色 #22D3EE / 底 #0B0F1A |
| 相似度匹配 | **三算法融合**（2026-09-07 升级）：rapidfuzz + TF-IDF + FAISS，权重由学习引擎自适应 | 老清单无编码时的候选召回，越用越准 |
| 向量检索 | **FAISS**（已集成）+ LanceDB（P2，外部独立文件库，**不入库 PG**） | 语义检索，亿级数据毫秒级检索，避免加重数据库 |
| 学习机制 | **学习引擎权重自适应**（2026-09-07 新增）：每次人工确认后自动调整三算法权重，支持持久化 | 越用越准，人工确认量持续下降 |
| 测试 | pytest（纯函数 + FastAPI 集成 TestClient） | 统一测试框架，比 Odoo `--test-enable` 简单可靠 |
| 许可 | **自有闭源**（FastAPI 项目无框架传染义务） | 业务代码完全自写 |

> **为什么从 Odoo 迁到 FastAPI**：Odoo 19 框架复杂度高、AI 写代码 bug 率高（ORM/views/OWL/SCSS 跨层）、前端定制困难、测试通道堵（全量测试被删除守卫杀死须分批）。FastAPI 业务代码 AI 写得好，且公司有 OA 统一登录消除了"自建认证"这一最大短板。纯函数层零语言转换，资产复用率 ~80%。

---

## 整体架构

系统自上而下分为：原始 Excel（真相源）→ 只读导入 / 归档服务 → FastAPI 应用（模型 + Service + API + 模板）→ PostgreSQL（业务数据，唯一权威）→ 外部 LanceDB（仅语义检索候选，非权威）。

认证层：公司 OA 统一登录（易达 ECMS）→ `get_current_user` 依赖注入 → 三角色权限（admin / estimator / viewer）。

```
┌─────────────────────────────────────────────────────┐
│  公司 OA（易达 ECMS）—— 统一登录源                    │
└──────────────────┬──────────────────────────────────┘
                   │ SSO（待厂商确认协议）
┌──────────────────▼──────────────────────────────────┐
│  FastAPI 应用（zaojia_fastapi）                      │
│  ┌──────────┐ ┌──────────┐ ┌──────────────────────┐ │
│  │ Jinja2   │ │ REST API │ │ 静态资源（demo/CSS）  │ │
│  │ 模板页面 │ │ /api/*   │ │ /static/*            │ │
│  └────┬─────┘ └────┬─────┘ └──────────────────────┘ │
│       │            │                                │
│  ┌────▼────────────▼─────┐  ┌────────────────────┐  │
│  │ Service 层（业务逻辑） │  │ core/security.py   │  │
│  │ import/query/price/   │  │ 三角色 + 权限依赖   │  │
│  │ match/audit/archive   │  │ core/audit.py      │  │
│  └────┬──────────────────┘  │ 审计四元组 append   │  │
│       │                     └────────────────────┘  │
│  ┌────▼──────────────────┐  ┌────────────────────┐  │
│  │ SQLAlchemy 模型        │  │ data/ 纯函数层     │  │
│  │ boq_item/import_batch/│  │ 720行 零框架依赖   │  │
│  │ material_dict/audit_log│ │ 90条 pytest 全绿   │  │
│  └────┬──────────────────┘  └────────────────────┘  │
└───────┼─────────────────────────────────────────────┘
        │
┌───────▼──────────┐     ┌──────────────────────┐
│ PostgreSQL 15    │     │ LanceDB（外部向量库） │
│ 业务数据（权威）  │     │ 语义检索候选（非权威）│
└──────────────────┘     └──────────────────────┘
```

---

## 核心模块（M0–M4）

| 阶段 | 交付内容 | 完成标准 | 状态 |
|---|---|---|---|
| **M0 迁移准备** | FastAPI 骨架 + 纯函数迁移（720行）+ 90条测试全绿 + 前端 demo 复用 + Odoo 版归档（tag + pg_dump） | pure_tests 90 passed；FastAPI app 加载成功；demo 可访问 | ✅ 完成 |
| **M1 数据模型** | SQLAlchemy 四模型（boq_item/import_batch/material_dict/audit_log）+ biz_id + 编码解析 + 分层 Upsert + 审计落库 + 三角色权限 | 模型可 create_all；安全用例 S1–S9 通过；权限用例通过 | ⏸ 待启动 |
| **M2 导入与查询** | 导入向导（只读打开/归档/分层Upsert/校验和/合并单元格/汇总行/异常标记/预览不写库）+ 搜索 + 导出（>1000行二次确认） | 真实清单导入→查询→导出闭环；批次校验和与 Excel 合计一致 | ⏸ 依赖 M1 |
| **M2.5 UI 页面** | 数据概览/清单检索/导入向导/批次管理/单价分析/物料字典/匹配确认/系统设置——深空科技风格 | 8 张基线截图 + 核对清单通过 | ⏸ 依赖 M2 |
| **M3 单价分析** | KPI 卡片 + 同类项聚合统计（默认只用「已完工程」）+ 匹配向导（rapidfuzz 候选+人工确认）+ 质量仪表盘 | 日常自用一周无阻塞；统计口径可解释 | ⏸ 依赖 M2 |
| **M4 成本库检索** | cost_catalog 模型 + LanceDB 语义检索 + PG↔LanceDB 一致性协议 | 语义检索可用；一致性对账通过 | 📋 设计完成 |
| **OA SSO 对接** | 易达 ECMS 统一登录对接，替换 `get_current_user` | OA 登录可直接访问门户；三角色映射正确 | ⏸ 待厂商文档（独立线，不阻塞 M1–M4） |
| **数据迁移** | Odoo 版 zaojia_db → 新库 ETL + 三重校验（行数/B类逐字段/SHA256） | 迁移后数据零丢失；B 类标注完整 | ⏸ 依赖 M1 模型定稿 |

> **安全是 M1 的交付内容，不是事后补丁**：一旦库里存进真实工程数据，再回头补软删除和审计日志，历史损失已无法追回。

各模块详细设计见 [`架构设计.md`](架构设计.md)（业务契约继承，技术栈已适配）及原 Odoo 版 M1–M4 模块设计稿（业务逻辑可参考，实现需重写为 FastAPI/SQLAlchemy）。

---

## 关键设计机制

### 1. 同类项聚合键 `match_key`（核心概念）

「什么算同一个清单项」是本系统最核心的概念，由 `match_key` 统一裁决，优先级为 **字典 > 标准化 > 编码 > 原始名称**，并记录 `match_key_source` 让统计口径可解释（如「本次统计 60% 来自编码匹配、30% 来自标准化」）。

### 2. 国标编码解析 `parse_gb_code()`

支持 9 位（系统真值）/ 12 位（含自编顺序码，入库保留完整 12 位溯源、匹配取前 9 位）/ 11 位（补前导 0）/ 10 位异常 / 2024 版 Z 前缀，统一返回 `(code_9, code_full)`。纯函数在 `data/gb_code.py`，90 条测试覆盖。

### 3. 字段分层（A / B / C 类）

- **A 类（可重建）**：从原始文件解析出的派生物，允许覆盖。
- **B 类（不可重建）**：人工标注资产（`std_name` / `std_spec` / `material_dict_id` / `anomaly_*` / `data_source_type`），**绝不静默覆盖**，需显式理由。
- **C 类（系统元数据）**：`write_date` / `active` 等。

### 4. 数据安全（第一性原理）

回到第一性原理：**原始 Excel 与人工标注是不可重建的真相源，数据库只是有损派生物**。由此导出安全设计（详见 [`架构设计.md` §四](架构设计.md)）：

- 只读导入（绝不改写源文件）
- 原始文件归档（逐字溯源）
- 分层 Upsert（替代 delete+insert）
- 软删除 + 回收站（30 天宽限 → 硬删，CSV 快照先行）
- 数据性质隔离（`pending_review` 不得污染历史单价库）
- 备份与恢复演练（3-2-1 + 每季度演练）
- 不可变审计日志（append-only，operator/reason/trace_id/timestamp 四元组）
- 批次校验和（检测漂移与篡改）
- 机密性（加密盘，密钥异地备份）
- **硬删闸门**：CSV 快照失败时物理删除必须被拒绝（Odoo 版 R1 缺陷教训，本项目从第一天锁死）

### 5. PG ↔ LanceDB 一致性协议（M4）

PG 与 LanceDB 无跨系统原子事务，一致性由 5 机制保障：**写序 / 幂等 upsert / `vector_sync_pending` 补偿 / 孤儿向量清理 / `embedding_version` 漂移检测 + `reconcile_vectors()` 对账**。审计与统计口径一律以 PG 为准，向量检索结果仅作候选、须标注来源且可能存在同步延迟。

---

## 文档索引

| 文档 | 内容 |
|---|---|
| [`项目总控.md`](项目总控.md) | 项目唯一事实源：目标/架构基线/分工/WBS/评审/变更/ADR/待决事项（v1.0） |
| [`架构设计.md`](架构设计.md) | 总架构、技术栈、数据安全、数据模型、接口契约（v6.7 → FastAPI 适配版） |
| [`产品设计文档.md`](产品设计文档.md) | 产品通俗说明、场景、功能清单、界面设计语言（v6.2 → FastAPI 适配版） |
| [`AGENTS.md`](AGENTS.md) | AI 协作硬规则、测试命令约定、数据安全基线 |
| [`app/static/demo/index.html`](app/static/demo/index.html) | 前端 demo（深空科技方案 C，8 个业务页面，从 Odoo 版原样复用） |
| [`data/`](data/) | 纯函数层 720 行（gb_code/aliases/unit_normalize/match_score/price_calc/quality_metrics/cost_catalog_gate） |
| [`pure_tests/`](pure_tests/) | 纯函数测试 90 条（迁移无损回归基线） |

> 原 Odoo 版 M1–M4 模块设计稿在 `E:\DEEPSEEK学习\造价数据库\`（已归档，业务契约可参考，实现需重写）。

---

## 里程碑路线图

```
M0 迁移准备 ✅ (2026-09-05)
  ├─ FastAPI 骨架 + 依赖安装
  ├─ 纯函数迁移 720行 + 90测试全绿
  ├─ 前端 demo 复用
  ├─ Odoo 版归档（tag + pg_dump）
  └─ 项目总控 v1.0 + 文档适配

M1 数据模型 ⏸ (下一步)
  ├─ SQLAlchemy 四模型 + biz_id
  ├─ 编码解析 + match_key
  ├─ 分层 Upsert + 孤儿处理
  ├─ 审计落库（append-only）
  └─ 三角色权限体系

M2 导入与查询 ⏸
M2.5 UI 页面 ⏸
M3 单价分析 ⏸
M4 成本库检索 📋
OA SSO 对接 ⏸ (独立线)
数据迁移 ⏸ (M1 后)
```

---

## 快速启动

```bash
# 1. 安装依赖
cd E:\DEEPSEEK学习\zaojia_fastapi
C:\Users\ht835\AppData\Local\Programs\Python\Python312\python.exe -m pip install -r requirements.txt

# 2. 跑纯函数测试（90 条，应全绿）
C:\Users\ht835\AppData\Local\Programs\Python\Python312\python.exe -m pytest pure_tests/ -v

# 3. 启动服务
C:\Users\ht835\AppData\Local\Programs\Python\Python312\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

# 4. 访问
#    前端 demo:  http://127.0.0.1:8000/  （自动跳转 /static/demo/index.html）
#    API 文档:   http://127.0.0.1:8000/docs
#    健康检查:   http://127.0.0.1:8000/health
```

> PostgreSQL 非 Windows 服务，需手动启动：`& "E:\PostgreSQL\pgsql\bin\pg_ctl.exe" start -D "E:\PostgreSQL\data"`

---

## 许可与协作约定

- **许可**：自有闭源。FastAPI（MIT）、SQLAlchemy（MIT）、Jinja2（BSD）均无传染义务。业务代码完全自写。
- **协作约定**（见 [`AGENTS.md`](AGENTS.md)）：总控角色铁律（不写实现代码）；每次改动必须 commit + 测试 + Self-Improving 审查；敏感文件（xlsx/xls/sql/dump）禁止入仓；安全用例 S1–S9 优先级高于功能用例。
- **原 Odoo 版**：`E:\DEEPSEEK学习\造价数据库\`（git tag `legacy-odoo-final`，只读归档，M2 完成前作为数据回滚兜底）。

---

*本 README 依据原 Odoo 版设计文档与迁移决策整理，作为 FastAPI 版项目入口概览。*
