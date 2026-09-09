# 造价数据门户（FastAPI 版）

> **一句话定位**：面向造价咨询团队的「工程量清单历史单价数据门户」——用 FastAPI + PostgreSQL 把散落在各工程 Excel 里的清单项沉淀为可检索、可复用、可审计的成本资产，支持团队共享查询，可作为公司网页的一部分。核心回答一个问题：**「这个清单项，我们以前做过多少钱？」**

> 本项目从 Odoo 19 版（`zaojia_boq` 模块）迁移而来。业务契约、数据安全铁律、纯函数层（720 行）100% 继承；技术栈从 Odoo 切换为 FastAPI + SQLAlchemy + Jinja2。原 Odoo 版已归档：git tag `legacy-odoo-final`，数据库备份 `zaojia_db_20260905.dump`。

**当前状态**：**M0–M4 核心功能全部完成** + 方案 A 前后端分离 + M2 导入深化四大模块 + 学习引擎 v2/v3 + 体验增强四模块 + 安全加固 + Alembic 版本化迁移 + S8 备份恢复自动化。全量测试 **551 passed**，零失败。

---

## 目录

- [项目概览](#项目概览)
- [技术栈](#技术栈)
- [整体架构](#整体架构)
- [核心模块（M0–M4 + 增强）](#核心模块m0m4--增强)
- [关键设计机制](#关键设计机制)
- [文档索引](#文档索引)
- [里程碑路线图](#里程碑路线图)
- [快速启动](#快速启动)
- [常用命令](#常用命令)
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
| 认证 | 公司 OA 统一登录（易达 ECMS，方案已完成待厂商文档）；开发期 dev_token 占位 |
| 前后端分离 | 方案 A：单应用 + 路由前缀（`/portal/*` 展示页 + `/admin/*` 管理页） |
| 当前状态 | M0–M4 ✅ + 前后端分离 ✅ + M2 深化 ✅ + 学习引擎 v2/v3 ✅ + 体验增强 ✅ + 安全加固 ✅ + Alembic ✅ |

---

## 技术栈

| 项 | 选择 | 理由 |
|---|---|---|
| Web 框架 | **FastAPI 0.141** | 异步高性能、自动 OpenAPI 文档、Pydantic 校验、AI 写代码质量高 |
| ORM | **SQLAlchemy 2.0** | 成熟稳定、显式事务、迁移工具 Alembic |
| 数据库迁移 | **Alembic 1.19** | 版本化 schema 演进、可回滚、可审计（2026-09-09 引入） |
| 数据库 | **PostgreSQL 15+** | `numeric` 精确，无 SQLite REAL 退化 |
| 模板引擎 | **Jinja2** | 服务端渲染，AI 最熟、维护成本低 |
| 纯函数层 | `data/` 目录 720 行（从 Odoo 版原样复用） | 零框架依赖，236 条 pytest 全绿作为回归基线 |
| 前端 | 深空科技设计系统 + ECharts 5.5 交互图表 | 主色 #4D7CFE / 辅色 #22D3EE / 底 #0B0F1A |
| 相似度匹配 | **三算法融合**：rapidfuzz + TF-IDF + FAISS，权重由学习引擎自适应 | 老清单无编码时的候选召回，越用越准 |
| 学习引擎 | **v2 + v3**：概念漂移检测、多策略集成、元学习自动调参 | 持续优化匹配准确率，人工确认量持续下降 |
| 测试 | pytest（纯函数 236 + 集成 315 = 551） | 统一测试框架，安全用例 `@pytest.mark.security` marker |
| CI | GitHub Actions（3 job：纯函数/集成/安全用例） | 自动回归，PR 自动检查 |
| 许可 | **自有闭源**（FastAPI 项目无框架传染义务） | 业务代码完全自写 |

> **为什么从 Odoo 迁到 FastAPI**：Odoo 19 框架复杂度高、AI 写代码 bug 率高（ORM/views/OWL/SCSS 跨层）、前端定制困难、测试通道堵。FastAPI 业务代码 AI 写得好，且公司有 OA 统一登录消除了"自建认证"这一最大短板。纯函数层零语言转换，资产复用率 ~80%。

---

## 整体架构

系统自上而下分为：原始 Excel（真相源）→ 只读导入 / 归档服务 → FastAPI 应用（模型 + Service + API + 模板）→ PostgreSQL（业务数据，唯一权威）。

认证层：公司 OA 统一登录（易达 ECMS）→ `get_current_user` 依赖注入 → 三角色权限（admin / estimator / viewer）。

前后端分离（方案 A）：
- **Portal 展示页**（`/portal/*`，3 页）：可选登录，未登录仅已标准化数据可见
- **Admin 管理页**（`/admin/*`，8 页）：必须登录 + 角色校验
- 旧路由 301 重定向

```
┌─────────────────────────────────────────────────────┐
│  公司 OA（易达 ECMS）—— 统一登录源                    │
└──────────────────┬──────────────────────────────────┘
                   │ SSO（方案已完成，待厂商文档）
┌──────────────────▼──────────────────────────────────┐
│  FastAPI 应用（zaojia_fastapi）                      │
│  ┌──────────────────┐ ┌───────────────────────────┐ │
│  │ Portal 展示页     │ │ Admin 管理页               │ │
│  │ /portal/* (3页)   │ │ /admin/* (8页)             │ │
│  │ 可选登录           │ │ 必须登录+角色校验           │ │
│  └────────┬─────────┘ └─────────────┬─────────────┘ │
│           │                           │               │
│  ┌────────▼───────────────────────────▼─────────────┐ │
│  │ REST API /api/*  +  Jinja2 模板  +  静态资源      │ │
│  └───────────────────────┬───────────────────────────┘ │
│                          │                             │
│  ┌───────────────────────▼───────────────────────────┐ │
│  │ Service 层（业务逻辑，10+ 服务）                    │ │
│  │ import/query/price/match/audit/archive/upsert/    │ │
│  │ batch/material_match/data_quality/cost_catalog/    │ │
│  │ evidence/prematch/learning_engine(v2/v3)           │ │
│  └───────────────────────┬───────────────────────────┘ │
│                          │                             │
│  ┌───────────────────────▼───────────────────────────┐ │
│  │ SQLAlchemy 模型（10 表）                            │ │
│  │ boq_item/import_batch/material_dict/audit_log/     │ │
│  │ match_cache/cost_catalog/tag/item_tag/              │ │
│  │ user_favorite/alembic_version                        │ │
│  └───────────────────────┬───────────────────────────┘ │
└──────────────────────────┼─────────────────────────────┘
                           │
              ┌────────────▼────────────┐
              │ PostgreSQL 15            │
              │ 业务数据（权威）          │
              │ Alembic 版本化迁移        │
              └─────────────────────────┘
```

---

## 核心模块（M0–M4 + 增强）

| 阶段 | 交付内容 | 完成标准 | 状态 |
|---|---|---|---|
| **M0 迁移准备** | FastAPI 骨架 + 纯函数迁移（720行）+ 90条测试全绿 + 前端 demo 复用 + Odoo 版归档（tag + pg_dump）+ 领域资产抽取（field_spec.py + 设计稿参考） | pure_tests 90 passed；FastAPI app 加载成功；demo 可访问 | ✅ 完成 (2026-09-05) |
| **M1 数据模型** | SQLAlchemy 四模型 + biz_id + 编码解析 + 分层 Upsert + 审计落库 + 三角色权限 + 测试验收 | 模型可 create_all；安全用例 S1–S9 通过；权限用例通过 | ✅ 完成 (2026-09-06) |
| **M2 导入与查询** | 导入向导（只读打开/归档/分层Upsert/校验和/合并单元格/汇总行/异常标记/预览不写库）+ 搜索 + 导出（>1000行二次确认）+ 批次软删/还原/硬删（30天宽限+CSV快照+B类闸门+审计） | 真实清单导入→查询→导出闭环；批次校验和与 Excel 合计一致 | ✅ 完成 (2026-09-07) |
| **M2 深化** | 多格式解析器（xlsx/xlsm/xls/csv + 魔数校验）+ 字段映射模板（13标准字段含暂估价 + 自动推荐）+ 校验规则引擎（5种类型/7个模板/三级分级）+ 归档增强（ZIP/GZIP压缩 + 完整性巡检 + 保留策略） | 四大模块独立测试通过；多格式文件可正常导入 | ✅ 完成 (2026-09-08) |
| **M2.5 UI 页面** | 数据概览/清单检索/导入向导/批次管理/单价分析/物料字典/匹配确认/系统设置——深空科技风格 | 8 张基线截图 + 核对清单通过 | ✅ 完成 (2026-09-08) |
| **方案 A 前后端分离** | Portal 页（/portal/*，3页）+ Admin 页（/admin/*，8页），旧路由 301 重定向，三角色权限矩阵，数据可见性控制（未登录仅已标准化数据） | 三角色权限矩阵验证通过；未登录仅可见已标准化数据 | ✅ 完成 (2026-09-08) |
| **M3 单价分析** | KPI 卡片 + 同类项聚合统计 + 匹配向导（rapidfuzz候选+人工确认）+ 质量仪表盘 + 匹配效率优化（降低阈值/同义词扩展/后台预匹配/TF-IDF/FAISS/学习引擎权重自适应） | 日常自用无阻塞；统计口径可解释；三算法融合 | ✅ 完成 (2026-09-07) |
| **学习引擎 v2/v3** | v2：概念漂移检测、多策略集成、权重持久化；v3：元学习自动调参、主动学习、置信度校准 | 学习引擎测试通过；匹配准确率持续提升 | ✅ 完成 (2026-09-08) |
| **M4 成本库** | cost_catalog 模型 + cost_migration_service 从 boq_item 聚合 + 成本目录查询 | 成本目录聚合正确；查询可用 | ✅ 完成 (2026-09-07) |
| **体验增强四模块** | ①S7/N1-N3 反向用例（N1 .xlsm只读+魔数校验/N2 60MB限制413/N3 归档失败不阻断）②单价趋势图 ECharts 交互版 ③常用项收藏（UserFavorite+4API）④标签分类（Tag+ItemTag+8API） | 新增 33 测试全部通过；ECharts 交互正常 | ✅ 完成 (2026-09-08) |
| **安全加固** | datetime 全部 timezone-aware（消除 3352 条弃用告警）+ Cookie httponly=True + 生产环境 /docs 禁用 + 硬删闸门测试 + 3处 naive datetime 修复 + wb.save 例外注释 | 全量测试通过；安全门禁可执行 | ✅ 完成 (2026-09-09) |
| **Alembic 版本化迁移** | Alembic 1.19 引入 + 初始迁移（10表）+ init_db() 改为 alembic upgrade head + upgrade/downgrade 验证通过 | 迁移可执行、可回滚；测试环境保留 create_all | ✅ 完成 (2026-09-09) |
| **S8 备份恢复自动化** | scripts/verify_backup_restore.py（临时库 pg_restore + 表结构/数据/B类字段抽样校验 + 自动清理） | 脚本可执行；RESULT: PASS 判据 | ✅ 完成 (2026-09-09) |
| **CI 持续集成** | .github/workflows/pytest.yml（3 job：纯函数/集成/安全用例） | push/PR 自动运行测试 | ✅ 完成 (2026-09-09) |
| **OA SSO 对接** | 易达 ECMS 统一登录对接，替换 `get_current_user`；方案已完成（docs/OA_SSO对接方案.md） | OA 登录可直接访问门户；三角色映射正确 | 📋 方案完成，待厂商文档（独立线，不阻塞） |
| **数据迁移** | Odoo 版 zaojia_db → 新库 ETL + 三重校验 | 迁移后数据零丢失；B 类标注完整 | ⏸ 待启动（scripts/migrate_odoo_to_fastapi.py 已存在） |

> **安全是 M1 的交付内容，不是事后补丁**：一旦库里存进真实工程数据，再回头补软删除和审计日志，历史损失已无法追回。

各模块详细设计见 [`架构设计.md`](架构设计.md)（业务契约继承，技术栈已适配）及 `docs/reference/` 下原 Odoo 版 M1–M4 模块设计稿（业务逻辑可参考，实现需重写为 FastAPI/SQLAlchemy）。

---

## 关键设计机制

### 1. 同类项聚合键 `match_key`（核心概念）

「什么算同一个清单项」是本系统最核心的概念，由 `match_key` 统一裁决，优先级为 **字典 > 标准化 > 编码 > 原始名称**，并记录 `match_key_source` 让统计口径可解释（如「本次统计 60% 来自编码匹配、30% 来自标准化」）。

### 2. 国标编码解析 `parse_gb_code()`

支持 9 位（系统真值）/ 12 位（含自编顺序码，入库保留完整 12 位溯源、匹配取前 9 位）/ 11 位（补前导 0）/ 10 位异常 / 2024 版 Z 前缀，统一返回 `(code_9, code_full)`。纯函数在 `data/gb_code.py`，测试覆盖。

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
- 备份与恢复演练（3-2-1 + 每季度演练，`scripts/verify_backup_restore.py` 自动化验证）
- 不可变审计日志（append-only，operator/reason/trace_id/timestamp 四元组）
- 批次校验和（检测漂移与篡改）
- **硬删闸门**：CSV 快照失败时物理删除必须被拒绝（fail-closed，`tests/test_hard_delete_gate.py` 6 测试覆盖）
- **S1–S9 安全用例**：优先级高于功能用例，`@pytest.mark.security` marker，CI 独立 job

### 5. 三算法融合匹配 + 学习引擎

- **rapidfuzz**：字符串相似度（基础召回）
- **TF-IDF**：语义匹配（关键词权重）
- **FAISS**：向量检索（语义相似度，毫秒级）
- **学习引擎 v2/v3**：每次人工确认后自动调整三算法权重，支持概念漂移检测、多策略集成、元学习自动调参
- **后台预匹配**：导入完成后异步计算，缓存结果，匹配从"实时算"变"预计算+查缓存"

### 6. Alembic 版本化迁移

- 生产/开发环境：`alembic upgrade head`（替代 `create_all`）
- 测试环境：保留 `create_all`（SQLite 内存库）
- 模型变更后：`alembic revision --autogenerate -m "description"` 生成迁移脚本
- 支持回滚：`alembic downgrade -1`

---

## 文档索引

| 文档 | 内容 |
|---|---|
| [`项目总控.md`](项目总控.md) | 项目唯一事实源：目标/架构基线/分工/WBS/评审/变更/ADR/待决事项（v1.3） |
| [`架构设计.md`](架构设计.md) | 总架构、技术栈、数据安全、数据模型、接口契约（v7.1） |
| [`产品设计文档.md`](产品设计文档.md) | 产品通俗说明、场景、功能清单、界面设计语言（v6.3） |
| [`造价数据门户产品方案_v1.0.docx`](造价数据门户产品方案_v1.0.docx) | 完整十章产品方案（功能架构/实施路线图/风险应对） |
| [`AGENTS.md`](AGENTS.md) | AI 协作硬规则、测试命令约定、数据安全基线 |
| [`docs/OA_SSO对接方案.md`](docs/OA_SSO对接方案.md) | OA 统一登录对接方案（认证流程/角色映射/实施步骤） |
| [`docs/reference/`](docs/reference/) | 原 Odoo 版 M1–M4 模块设计稿（业务契约可继承） |
| [`data/`](data/) | 纯函数层 720 行（gb_code/aliases/unit_normalize/match_score/price_calc/quality_metrics/cost_catalog_gate/field_spec/tfidf_matcher/faiss_matcher/learning_engine_v2/v3） |
| [`pure_tests/`](pure_tests/) | 纯函数测试 236 条（迁移无损回归基线） |
| [`tests/`](tests/) | FastAPI 集成测试 315 条（含 S1-S9 安全用例 + N1-N3 反向用例） |
| [`scripts/`](scripts/) | 工具脚本（备份恢复验证/数据迁移/产品文档生成） |

---

## 里程碑路线图

```
M0 迁移准备 ✅ (2026-09-05)
  ├─ FastAPI 骨架 + 依赖安装
  ├─ 纯函数迁移 720行 + 90测试全绿
  ├─ 前端 demo 复用
  ├─ Odoo 版归档（tag + pg_dump）
  └─ 领域资产抽取（field_spec.py + 设计稿参考）

M1 数据模型 ✅ (2026-09-06)
  ├─ SQLAlchemy 四模型 + biz_id
  ├─ 编码解析 + match_key
  ├─ 分层 Upsert + 孤儿处理
  ├─ 审计落库（append-only）
  └─ 三角色权限体系

M2 导入与查询 ✅ (2026-09-07)
  ├─ 导入向导（预览不写库/确认入库）
  ├─ 搜索 + 导出（>1000行二次确认）
  ├─ 批次软删/还原/硬删（30天宽限+CSV快照）
  └─ M2 深化（多格式解析/字段映射/校验引擎/归档增强）✅

M2.5 UI 页面 ✅ (2026-09-08)
  ├─ 8 个业务页面（深空科技风格）
  └─ 方案 A 前后端分离（/portal + /admin）✅

M3 单价分析 ✅ (2026-09-07)
  ├─ KPI 卡片 + 同类项聚合统计
  ├─ 匹配向导（三算法融合 + 人工确认）
  ├─ 匹配效率优化（阈值/同义词/预匹配/TF-IDF/FAISS）
  └─ 学习引擎 v2/v3 ✅

M4 成本库 ✅ (2026-09-07)
  ├─ cost_catalog 模型 + 聚合服务
  └─ 成本目录查询

体验增强 ✅ (2026-09-08)
  ├─ S7/N1-N3 反向用例
  ├─ 单价趋势图 ECharts 交互版
  ├─ 常用项收藏
  └─ 标签分类

安全加固 + 工程化 ✅ (2026-09-09)
  ├─ datetime timezone-aware 全覆盖
  ├─ Cookie httponly + 生产禁 docs
  ├─ 硬删闸门测试（6测试）
  ├─ Alembic 版本化迁移
  ├─ S8 备份恢复自动化脚本
  ├─ GitHub Actions CI（3 job）
  └─ pytest security marker

OA SSO 对接 📋 (方案完成，待厂商文档)
数据迁移 ⏸ (脚本已存在，待执行)
```

---

## 快速启动

```bash
# 0. 启动 PostgreSQL（非 Windows 服务，需手动启动）
& "E:\PostgreSQL\pgsql\bin\pg_ctl.exe" start -D "E:\PostgreSQL\data"

# 1. 安装依赖
cd E:\DEEPSEEK学习\zaojia_fastapi
C:\Users\ht835\AppData\Local\Programs\Python\Python312\python.exe -m pip install -r requirements.txt

# 2. 数据库迁移（生产/开发环境）
C:\Users\ht835\AppData\Local\Programs\Python\Python312\python.exe -m alembic upgrade head

# 3. 跑全量测试（551 条，应全绿）
C:\Users\ht835\AppData\Local\Programs\Python\Python312\python.exe -m pytest pure_tests/ tests/ -v

# 4. 启动服务
C:\Users\ht835\AppData\Local\Programs\Python\Python312\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8777 --reload

# 5. 登录（首次访问必须通过登录链接写 Cookie）
#    Admin:  http://127.0.0.1:8777/login?token=zaojia-dev-token-2026&role=admin&next=/admin/dashboard
#    健康检查: http://127.0.0.1:8777/health
```

---

## 常用命令

```bash
# 测试
pytest pure_tests/ -v                    # 纯函数测试（236条）
pytest tests/ -v                          # 集成测试（315条）
pytest tests/ -m security -v              # 仅安全用例（S1-S9）
pytest tests/test_hard_delete_gate.py -v  # 硬删闸门测试

# 数据库迁移
alembic current                            # 查看当前版本
alembic upgrade head                       # 升级到最新版本
alembic downgrade -1                       # 回滚一个版本
alembic revision --autogenerate -m "msg"  # 生成新迁移（模型变更后）

# 备份恢复验证（S8，每季度）
python scripts/verify_backup_restore.py <backup_file.dump>

# 代码审查
python -m pytest tests/ pure_tests/ -q    # 全量测试（交付前必跑）
```

---

## 许可与协作约定

- **许可**：自有闭源。FastAPI（MIT）、SQLAlchemy（MIT）、Jinja2（BSD）均无传染义务。业务代码完全自写。
- **协作约定**（见 [`AGENTS.md`](AGENTS.md)）：总控角色铁律（不写实现代码）；每次改动必须 commit + 测试；敏感文件（xlsx/xls/sql/dump）禁止入仓；安全用例 S1–S9 优先级高于功能用例；Alembic 迁移替代 create_all。
- **原 Odoo 版**：`E:\DEEPSEEK学习\造价数据库\`（git tag `legacy-odoo-final`，只读归档）。

---

*本 README 依据原 Odoo 版设计文档与迁移决策整理，作为 FastAPI 版项目入口概览。最后更新：2026-09-09。*
