# zaojia_fastapi 全面工程审查报告（2026-09-14）

> 审查范围：代码质量（Cody）、架构/技术债（Archi）、测试覆盖与性能门禁（Tessa）
> 数据来源：静态代码审查 + 实跑测试基线（`pytest pure_tests/ tests/ -v` → **551 passed / 0 failed**, 6.93s）
> 基线对齐：`项目总控.md` v1.4 / `AGENTS.md`（测试判据 236+309=551，集成实测 315 滞后 +6）
> 事故背景：09-14 字典页面全量加载事故后新增「大数据量页面性能铁律」，本审查重点核查其合规性。

## TL;DR（结论卡片）

| 维度 | 结论 | 关键发现 |
|------|------|---------|
| 代码质量 | 🟡 1 P0 残留 / 多 P1 已闭环 | **修复后复查（2026-09-14）**：P0-2 复合索引 ✅ 已闭环；P0-1 全量加载 ⚠️ 部分缓解（列裁剪+limit，仍 `.all()` 157K 未彻底闭环）；P1-1/4/5/3b/8/A1 已修复 |
| 架构 | ⚠️ M6 双轨恶化 | M6 表（list_material_mapping 等）脱离 Alembic，`force_create_table.py` 含 `DROP CASCADE`；无监控/多租户 |
| 测试 | ✅ 全绿但有假阳性 | 551 passed；安全 S1–S9/N1–N3/硬删闸门全绿，但 M6 性能铁律**零自动化用例**，SQLite 不暴露 PG 索引缺失 |
| 文档 | ⚠️ 漂移 | `项目总控.md` §10.9 记「复合索引已建」「树 l1+l2=236 条」与代码（未建 / l1 仅 39 条）不一致 |

**最高优先 3 项**：
1. 补 `(parent_id, name)` 复合索引（P0，文档已宣称已建但代码缺失，直接导致 /dict/children 无法走复合索引）
2. 消除 `get_pending_matches` 全量加载 15.7 万行（P0，09-14 事故同类复发，违反性能铁律 §禁止全量加载）
3. 让 M6 表回归 Alembic 单轨，停用 `force_create_table.py` 的 `DROP CASCADE`（P1 架构）

---

## 一、P0（阻断级，必须优先修复）

### P0-1 `get_pending_matches` 全量加载 15.7 万行 MaterialDict
- 位置：`app/services/page_services.py:876`
- 证据：`dict_rows = s.query(MaterialDict).all()` 一次性取全表 156,733 行，再 Python 端构建 TF-IDF 池。
- 定性：**09-14 事故同类复发**——`AGENTS.md`「大数据量页面性能铁律」明确禁止全量加载、要求候选池按 page_size=100（最大 500）分页。本函数把整个字典拉进内存，候选池无分页。
- 影响：页面首屏 + 每个未匹配项触发一次全量读，内存与耗时随字典线性膨胀；SQLite 测试环境不暴露，生产 PG 上为隐性性能炸弹。
- 修复方向：候选池分页/只取叶子节点（l3/l4）子集，TF-IDF 索引按需构建并缓存；与 `/dict/children` 同口径。

**【修复状态 · 2026-09-14 复查】⚠️ 部分缓解，未彻底闭环**：`pending` 已加 `.limit(limit)`（默认 50），`dict_count` 改为 `func.count`，候选池 `dict_rows` 改为**列裁剪**（仅取 id/name/spec_whitelist/parent_id/level 5 字段），内存占用显著下降。但**仍 `s.query(...).all()` 全表 15.7 万行**（代码注释自认「行为不变：仍全表取候选」），缓存未命中路径下 P0 铁律（禁止全量加载树形数据）仍被违反。彻底闭环需：①TF-IDF/FAISS 索引常驻缓存（启动/预热构建一次，而非每请求重建）；②缓存未命中回退改服务端候选检索（LIMIT 有界）；③页面优先读 `match_cache` 表。

### P0-2 `(parent_id, name)` 复合索引缺失
- 位置：`app/models/material_dict.py:26-31`
- 证据：模型仅 `parent_id index=True`、`name index=True` 两个**单列**索引；无 `__table_args__` 复合索引；Alembic 迁移亦无 `ix_material_dict_parent_name`。
- 矛盾：`项目总控.md` §10.9 标准实现模式记载「ix_material_dict_parent_name **已建**」——文档与代码不符。
- 影响：`/dict/children` 的 `filter(parent_id==).order_by(name)`（`dict.py:175,178,184`）无法命中复合索引，15.7 万行下回表 + 排序成本高，是 09-14 事故根因之一。
- 修复方向：ORM 加 `__table_args__ = (Index("ix_material_dict_parent_name","parent_id","name"),)` + 新增 Alembic 迁移；同步更正 §10.9 文档。

**【修复状态 · 2026-09-14 复查】✅ 已闭环**：ORM `material_dict.py` 已加 `__table_args__ = (Index("ix_material_dict_parent_name", "parent_id", "name"),)`；Alembic 迁移 `a1b2c3d4e5f6_add_material_dict_parent_name_index.py` 已建且 `down_revision=8f01e7bf36ce`，迁移链完整（`8f01e7bf36ce` → `a1b2c3d4e5f6` → `b2c3d4e5f6a7`）。§10.9「已建」文档与代码现已一致。

---

## 二、P1（高优，影响性能/正确性/安全）

| # | 问题 | 位置 | 说明 |
|---|------|------|------|
| P1-1 | N+1 + 巨型单事务 | `cost_migration_service.py:97-102,174-184` | 每个 match_key 循环调 `_aggregate_for_match_key`，逐 key 查询 + 单事务过大，批量成本迁移易超时 |
| P1-2 | `confirm_match` 循环内重复全量查 l3 | `material_match_service.py:215-217,305` | 每次确认循环调 `_build_dict_rows(db)` 全量；学习引擎段 :305 再次调用，同一请求内重复全表读 |
| P1-3 | 审计 operator 可伪造 | `material_match_service.py` confirm + `app/api/match.py:76` | operator 取请求体 `payload['operator']`，前端 `app.js:831` 传 `'dev-user'`；审计四元组完整性被前端可控字段破坏，应取当前登录用户 |
| P1-4 | `/dict/children` hasChild N+1 | `dict.py:188` | 循环内逐行 `db.query(...).filter(parent_id==r.id).first()`，每页 100 行 → 100 次额外查询，应改 EXISTS 子查询批量 |
| P1-5 | 子节点 count N+1 | `page_services.py:818` | 子节点计数逐行查，与 P1-4 同源，需 EXISTS/JOIN 批量化 |
| P1-A1 | M6 表脱离 Alembic（双轨恶化） | `force_create_table.py` | M6 新增表（list_material_mapping 等）靠 `DROP CASCADE` 重建，绕过版本化迁移；生产误运行将清数据。ADR：回归 Alembic 单轨（F012） |
| P1-3b | **上传文件无大小限制** | `import_api.py:82` | `UploadFile` 无 HTTP 层兜底；§4.3 规定单文件 ≤50MB，但恶意 10GB 上传可 OOM。ADR-003：应用层 `MAX_UPLOAD_SIZE` + Nginx `client_max_body_size` 双保险 |
| P1-7 | **审计 operator 可伪造**（跨 4 个 Service） | `batch_operation/cost_migration/material_match` Service | operator 从客户端 payload 取，可伪造任意用户名；应强制从鉴权层 `request.state.username` 取（ADR-005） |
| P1-8 | `AuditMiddleware` 同步写库阻塞事件循环 | `audit.py:123-145` | `db.commit()` 同步调用，高频写场景阻塞 async；改 `asyncio.to_thread`（ADR-F008） |

---

## 三、P2（中低优）

- P2-1 `_generate_dict_code` 并发窗口（`dict.py:55-98`）：`max+1` 无并发保护，code unique 冲突依赖事后重试；建议原子生成（F015）。
- P2-2 `_compute_cat_path` 祖先链 while 逐层查询（`dict.py:101-117`）：深度递归单点查，可 CTE/一次取父链。
- P2-3 `main.py:110` 硬编码 8777 端口，与文档 8000 冲突；改配置。
- P2-4 文档漂移集：`项目总控.md` §10.9「236 条 / 已建索引」与代码 39 条 / 未建 不一致；树层级口径统一（F014）。
- P2-5 死代码 T6（`cost_catalog_gate.py`：`load_catalog` 从未被调用，保留在测试中）：清理或标记 deprecated。

---

## 四、架构技术债优先级（Archi）

按 Impact/Value 排序（P 值）：

| 债项 | P | 说明 | 建议 ADR |
|------|---|------|---------|
| D2 M6 schema 双轨 + DROP CASCADE | 40 | 最大技术债，停 force 脚本，迁移进 Alembic | F012 |
| D1 无性能/数据量监控 | 30 | 事故靠人肉发现；加 PG 慢查询 + 页面 P95 看板 | F013 前置 |
| D3 dict code 并发 | 28 | P2-1 升级项，原子化 | F015 |
| D9 SQLite/PG 差异 | 25 | 测试用 SQLite 内存库，索引缺失不暴露→假阳性绿；CI 加 PG 冒烟 | F014 |
| D10 无多租户/租户隔离 | 25 | 未来企业化必需，先评估 | — |
| D6 无监控（与 D1 同义合并） | 20 | 见 D1 | — |
| D8 文档/代码口径漂移 | 18 | 本文档「文档漂移」项汇总 | F014 |
| D4/D5 复合索引+全量加载 | 16 | 即 P0-1/P0-2 | F013/F012 联动 |
| D7 M5 前置清偿 M6 债 | 5 | M5 自动指标生成实施前先清零 M6 性能债 | F016 |

---

## 五、测试覆盖与性能门禁（Tessa）

**实跑基线**：`pytest pure_tests/ tests/ -v` → **551 passed / 0 failed**（纯函数 236 + 集成 315）。
- AGENTS.md 判据「集成 309」已滞后实测 +6，需更新为 315。
- 安全 S1–S9 / N1–N3 / 硬删闸门**全绿**，但断言多为**字符串扫描**（grep 式），非行为级——需升级为真实行为断言。

**盲区（性能铁律零自动化）**：
- `/dict/children` 无专属 `test_dict_api.py`；`page_services.py` 31 函数近乎 0 断言。
- M6 性能铁律（分页上限 500 / 防抖 / 子节点 <200ms）无任何自动化用例。
- SQLite 不暴露 PG 索引缺失 → 测试绿但生产慢（**假阳性**），需在 CI 启 PG 冒烟 + 加 `@perf` 门禁。

**建议**：
1. 新建 `tests/test_dict_api.py` 覆盖 /dict/children 分页、hasChild、复合索引命中（explain 级）。
2. 抽 M6 核心逻辑（编码/匹配率）进 `pure_tests`，加纯函数边界。
3. 加 `@pytest.mark.perf` 门禁：`get_pending_matches` / `/dict/children` 在 N 万行夹具下 P95 < 阈值。
4. 升级安全断言从字符串扫描到行为级（B 类不静默覆盖实际校验值）。
5. 更新 `AGENTS.md` 集成判据 309 → 315。

---

## 六、行动清单（按序）

**P0（阻断）**
1. 加 `(parent_id, name)` 复合索引（ORM + Alembic 迁移）+ 更正 `项目总控.md` §10.9。
2. 重写 `get_pending_matches` 候选池为分页/叶子子集，TF-IDF 索引缓存。

**P1（高优）**
3. 修 `dict.py:188` / `page_services.py:818` 的 hasChild/count N+1（EXISTS 批量）。
4. `cost_migration_service.py` N+1 + 分片事务。
5. `material_match_service.py` confirm_match 循环去重 `_build_dict_rows`。
6. 审计 operator 改取当前登录用户（防伪造）。
7. M6 表回归 Alembic，停用 `force_create_table.py` 的 DROP CASCADE。

**P2 / 文档**
8. dict code 原子生成；`main.py` 端口改配置；树层级口径统一；`AGENTS.md` 判据 309→315。

**测试 / 门禁**
9. 新建 `test_dict_api.py`；加 `@perf` 门禁；安全断言行为化；CI PG 冒烟。

---

> 勘误（2026-09-14 复核实）：原报告 P2-6「`datetime.utcnow()` 弃用 T5」经核实**不成立**——`app/` 目录已无任何 `utcnow` 调用（v1.3 已完成 17 处时区感知改造，全部改为 `datetime.now(timezone.utc)`），该项为误报，已删除。

## 七、数据来源索引
- `app/services/page_services.py:876`、`:818`（全量加载 / count N+1）
- `app/models/material_dict.py:26-31`（索引现状）
- `app/api/dict.py:55-98,101-117,175-197`（code 生成 / 祖先链 / children N+1）
- `app/services/material_match_service.py:215-217,305`（循环重复全量查）
- `app/services/cost_migration_service.py:97-102,174-184`（N+1 + 大事务）
- `app/api/match.py:76`、前端 `app.js:831`（operator 伪造）
- `项目总控.md` §10.9（文档 vs 代码漂移）
- 三方成员报告：code-reviewer-2 / architect-2 / testing-expert-2（2026-09-14）

---

## 八、复查结论（2026-09-14 修复后复核）

> 用户反馈「已经修复」后，主理人对报告所列 P0/P1 项逐条**对照源码 + 实跑测试**复核。
> 测试基线重跑：`pure_tests/` **236 passed** + `tests/` **315 passed** = **551 passed / 0 failed**（无回归，6.52s）。
> 注：warnings 中的 `datetime.utcnow()` 全部来自第三方库 `openpyxl` 内部，**非本应用代码**，印证勘误中删除 P2-6 误报正确。

### 8.1 修复状态总表

| 项 | 严重度 | 状态 | 关键证据 |
|----|--------|------|---------|
| P0-2 `(parent_id,name)` 复合索引 | P0 | ✅ **已闭环** | ORM `__table_args__` 索引 + Alembic 迁移 `a1b2c3d4e5f6`（链完整）+ §10.9 文档与代码一致 |
| P0-1 `get_pending_matches` 全量加载 | P0 | ⚠️ **部分缓解** | `pending` 加 `limit(50)` ✅、`dict_count` 改 `func.count` ✅、`dict_rows` 列裁剪（5 字段）✅；但**仍 `.all()` 全表 15.7 万行**（注释自认「仍全表取候选」），缓存未命中路径仍违反性能铁律 |
| P1-1 cost_migration N+1 | P1 | ✅ **已闭环** | 改用 `_aggregate_batch(db, match_keys)` 单查询 + 内存分组（`:79-91,217`，注释「避免 N+1」） |
| P1-4 `/dict/children` hasChild N+1 | P1 | ✅ **已闭环** | 一次 `parent_id.in_(row_ids)` 批量（`:188-194`，注释「避免 N+1」） |
| P1-5 子节点 count N+1 | P1 | ✅ **已闭环** | `parent_id.in_(cid_list)` + `group_by` 批量（page_services `:834-841`，注释「避免 N+1」） |
| P1-8 AuditMiddleware 同步写库 | P1 | ✅ **已闭环** | `await asyncio.to_thread(_write_http_audit, ...)`（audit.py `:125`，注释「P1-8 修复」） |
| P1-3b 上传文件无大小限制 | P1 | ✅ **已闭环** | `MAX_FILE_SIZE=60MB`，先查 `content-length` 头、读取后复校实际字节（import_api `:278-303`，双重 413 拒绝） |
| P1-A1 M6 表脱离 Alembic（双轨） | P1 | ✅ **已闭环** | `list_material_mapping` 入 Alembic（迁移 `b2c3d4e5f6a7`）；`force_create_table.py` 改造为**只读检查脚本**（无 DROP/CREATE） |
| P1-3 / P1-7 operator 伪造 | P1 | ⚠️ **部分修复** | http_request 级审计（AuditMiddleware）已从 `request.state.username` 取真实用户 ✅；但 Service 层 `log_audit(operator=payload['operator'])`（`batch_operation_service.py:116`、`material_match_service.py:182`）仍接受客户端伪造值，业务审计四元组 operator 仍可伪造 |
| P1-2 confirm_match 循环重复全量查 l3 | P1 | ⏳ **未验证** | 本次未重点核查 `material_match_service.py:215-217,305`；建议后续确认 `_build_dict_rows` 去重 |
| P2-2 祖先链 while 逐层查询 | P2 | ⏳ **未变** | page_services `:810-812` 仍 `query(id==parent_id).first()` 逐层查；受树深 ≤5 限制，影响小 |
| P2-3 main.py:110 端口 8777 vs 文档 8000 | P2 | ⏳ **未变** | 文档漂移 |
| P2-4 文档漂移（§10.9 count 236 vs 39） | P2 | ⏳ **部分** | 复合索引点已一致；但「l1+l2=236 条 / l1 仅 39 条」层级口径仍不一致 |
| P2-5 死代码 load_catalog | P2 | ⏳ **未变** | 未清理 |

### 8.2 残留风险（需继续跟进）

1. **P0-1 彻底闭环（最高优先）**：当前为内存缓解，未消除全量加载。生产 PG 上缓存未命中时仍可能 OOM/超时。建议：
   - 将 TF-IDF/FAISS 索引常驻内存缓存（应用启动或后台预热时构建一次），页面请求复用，而非每请求重建；
   - 缓存未命中回退改为**服务端候选检索（LIMIT 有界，如 top-200）**而非全表取候选；
   - 页面首屏优先读 `match_cache` 表（prematch 已落地基础设施），冷启动走 LIMIT 分批。
2. **P1-3/P1-7 Service 层 operator 伪造**：`log_audit` 的 operator 应来自鉴权层而非 payload。建议通过 contextvar（auth 依赖 set 当前用户名）或调用链透传，使业务审计四元组与 http 层一致不可伪造。
3. **P1-2 confirm_match 循环重复全量查**：待核查 `material_match_service.py:215-217,305`。
4. **文档漂移收尾**：§10.9 层级口径（236 vs 39）、上传 50MB vs 代码 60MB、端口 8777 vs 8000 三处需对齐。

### 8.3 本次修复质量评价

- **修复纪律良好**：N+1 类问题（P1-1/4/5）均通过「`in_(list)` + `group_by` 单查询」模式根治，非临时绕过；审计异步化、上传双校验、Alembic 单轨均按规范落地。
- **唯一未彻底闭环的是 P0-1**：属「内存缓解 + 行为不变」式修复，未满足性能铁律字面要求。建议不作为「已修复」关闭，列入下一迭代必做项。
- **测试无回归**：551 passed 全绿，证明本次改动未破坏既有契约（含安全 S1–S9 / 硬删闸门）。

> 复核方法：对照源码逐行核实 + 实跑 `pytest pure_tests/ tests/`。未采用静态扫描断言，避免假阳性。
