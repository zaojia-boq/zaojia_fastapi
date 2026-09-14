# 全面代码审查报告（深度版）· zaojia_fastapi

- **审查日期**：2026-09-06
- **审查方式**：全量通读（app/ 约 5,900 行 + data/ 约 870 行 + tests/pure_tests 约 4,400 行 + 模板/前端约 1,400 行，合计约 15,500 行），分层并行审查后交叉核实；全部 P0/P1 发现均经人工复核源码确认，非仅凭静态印象。
- **与既有报告的关系**：本目录下 `engineering-review-zaojia_fastapi-2026-09-06.md` 为同日早前的工程审查；本报告是更细粒度的全量复审，发现了其未覆盖的多项问题（尤其 P0/P1 级），结论冲突处以本报告为准。
- **审查性质**：只读审查，未修改任何实现代码。

---

## 一、测试基线实测结果（审查当日）

| 套件 | 命令 | 结果 | 判据符合性 |
|---|---|---|---|
| 纯函数层 | `python -m pytest pure_tests/ -q` | **127 passed**，0.17s | ✅ 与 AGENTS.md 基线一致 |
| 集成测试 | `python -m pytest tests/ -q` | **297 passed, 1 FAILED**（75s） | ❌ 未全绿 |

**失败用例**：`tests/test_pages.py::TestTemplateInheritance::test_search_hides_topbar` —— 断言 `assert "topbar" not in r.text` 被页面 **HTML 注释**（"模板可设 hide_topbar=true 隐藏"）误伤。功能本身未坏，是断言写法脆弱（应断言 DOM 结构而非全文子串）。但按 AGENTS.md「零失败」判据，**当前集成测试基线不达标**，须先修复该断言再交付任何后续改动。

**告警**：全套件约 3,300 条 DeprecationWarning，主要来自 `datetime.utcnow()`（app/core/audit.py:76/97、app/models/base_mixin.py、import_batch.py:33、audit_log.py:52）及 openpyxl。Python 3.12 下 utcnow 已弃用，且产生的是 naive 时间，与 batch.py 中 `datetime.now(timezone.utc)` 的 aware 时间混用，时区语义不一致。

---

## 二、总体评价

架构层面的核心设计**执行得相当一致**：

- ✅ **源文件只读**：import_service.py 全程 `read_only=True, data_only=True`，全项目无对源 Excel 的 `wb.save`；
- ✅ **B 类字段「仅填空不覆盖」语义**在 upsert / match / migration 三处正确实现；
- ✅ **纯函数分层**：data/ 目录无 IO、无全局可变状态，127 条测试守护密度高；
- ✅ **鉴权写法**：历史上的工厂嵌套 P0 已修复，`require_role` 写法正确，所有 API 路由与页面路由均有鉴权依赖；
- ✅ **路径穿越封堵**：`_validate_tmp_path` commonpath + 文件名强匹配，负例测试齐全；
- ✅ **XSS 面**：Jinja autoescape 常开、模板零 `|safe`、前端 innerHTML 拼接前均过 escapeHtml，未发现实际注入点。

主要系统性风险集中在四个方面：**（a）硬删除快照列不完整使人工资产闸门失效（P0）；（b）estimator 可批量写 B 类字段，与铁律口径矛盾（P0）；（c）upsert 孤儿判定的 sequence 依赖连环 bug（P1）；（d）多处全表加载 / N+1 的性能债务与「约定式」测试库隔离（P1/P2）。**

---

## 三、P0 —— 阻断交付，必须最先修

### P0-1 硬删除 CSV 快照缺失关键 B 类列，人工资产闸门实质失效

- **位置**：`app/api/batch.py:43-48`（SNAPSHOT_COLUMNS）、`batch.py:184`（闸门判定）、`batch.py:276-294`（_export_snapshot）
- **问题**：闸门以「`std_name/std_spec/material_dict_id` 非空 ⇒ 必须先出快照」触发，但快照列清单里**恰恰没有 `material_dict_id`，也没有 `anomaly_reason`**，且缺 `id`、`biz_id`、`quantity_num/unit_rate_num/total_num` 等归一化数值列。硬删后即使拿快照回灌，物料字典链接（正是触发闸门的人工资产）、异常原因、业务 ID、数值全部永久丢失——快照形同虚设。
- **修复建议**：SNAPSHOT_COLUMNS 补齐 `id, biz_id, material_dict_id, anomaly_reason, quantity_num, unit_rate_num, total_num, match_key, match_key_version, item_code_version`；并补一条「快照内容完整性」行为测试（当前测试未覆盖快照文件内容，见 §七）。

### P0-2 estimator 可批量写 B 类字段，三处口径互相矛盾

- **位置**：`app/api/batch_operation.py:50, 67`（`require_role(ROLE_ESTIMATOR, ROLE_ADMIN)`）、`app/api/match.py:67`（/confirm 允许 estimator）；对照 `app/core/security.py:24`（"estimator：B类字段只读"）、`app/core/permissions.py` 权限矩阵（`edit_b` 仅 admin）、`app/models/boq_item.py:15-16`（anomaly_flag/data_source_type 属 B 类）
- **问题**：`/api/batch-operation/confirm-anomalies`、`/switch-data-source`、`/api/match/confirm` 三个端点允许 estimator 批量修改 B 类字段（anomaly_flag / data_source_type / std_name / std_spec / material_dict_id），直接违反「B 类字段仅 admin 可改」铁律。`>50 行需 confirm` 只是操作确认不是授权；`validate_b_field_change` 的 admin 校验未被这批批量路径调用。代码、角色定义、权限矩阵三处口径互相矛盾，且无测试捕获（test_permissions 只测了纯函数本身）。
- **修复建议**：业务裁决二选一并三处同步——① 改 `require_role(ROLE_ADMIN)`（一行改动，推荐）；② 若业务确需 estimator 参与异常确认，则正式修订铁律文档 + security.py 注释 + 权限矩阵 + 测试。**不允许维持现状**。同批修复下条 operator 伪造问题。

### P0-3（与 P0-2 同批）审计 operator 取自客户端 payload，可任意伪造

- **位置**：`app/api/batch_operation.py:27,36`（`operator: str` 请求体字段）→ `batch_operation_service.py:55-57, 103-137`、`material_match_service.py:132-137`；`app/api/match.py:41` 同
- **问题**：路由已有 `require_role` 注入的真实 user 却不用，审计四元组之「谁」可被任意客户端伪造，违反本项目自己的 ADR-F005（audit.py:7-9 刚为此修过中间件层）。
- **修复建议**：删除请求体中的 `operator` 字段，service 签名改收 `operator: str` 由路由传 `user['username']`；补「estimator 提交他人名义 operator 应被忽略」的负例测试。

---

## 四、P1 —— 高优先，本周内修

### 数据正确性

1. **`app/services/upsert_service.py:284-289`（根因 :227）**：孤儿判定只比「原 sequence 是否出现在新导入 sequence 集合」。新 Excel 行号整体平移（插入/删除行）时，经候选键兜底**刚更新成功**的活跃行会被误判孤儿并软删隐藏（`active=False, orphaned=True`），created/updated/orphaned 统计全错。修复：主循环记录「已匹配的 existing id 集合」，孤儿判定排除该集合；`preview_upsert`（:342）继承了同一逻辑，应抽公共函数（dry_run 参数）而非复制。
2. **`app/services/upsert_service.py:170`**：`break` 位于 `for orph in orphs:` 循环体内，实际效果是**每个 dict_id 分组只有第一个孤儿被回灌 B 类标注**，其余静默跳过（注释「每个孤儿只回灌一次」与实现不符）。B 类标注静默丢失，违背孤儿回灌设计目标。修复：去掉该 break。
3. **`app/services/cost_migration_service.py:144-153`**：门槛失败分支 `gate['data']` 为 None 时 `gate['data']['gate']` 直接 AttributeError——「质量指标获取失败」时迁移接口返回 500 而非拒绝。修复：`gate.get('data') or {}` 并分别处理 success=False。
4. **`app/api/query.py:112` + `app/services/query_service.py:126,141`**：导出默认 `limit=10000` **静默截断**——超 1 万行的筛选结果被无声丢弃，审计日志记录的行数也失真。修复：先 count，超限报 428 要求收窄条件或分页导出。
5. **`app/models/boq_item.py:125-128` vs `app/models/cost_catalog.py:40-43`**：字段长度漂移——`boq_item.match_key` 裸 String（无界），`cost_catalog.match_key` String(256) UNIQUE。raw 兜底键长度取决于 item_name/item_feature（Text），超 256 字符时 M4 迁移插入直接报 StringDataRightTruncation。同类漂移：`unit_std`（裸 vs String(32)）、`std_spec`（裸 vs String(512)）。修复：定长 + compute_match_key 对 raw 分支截断/哈希后缀。

### 安全与资源

6. **`app/api/import_api.py:98-110`**：上传无大小上限，`await file.read()` 一次读尽入内存。修复：分块读取 + ≤50MB 校验，超限 413。
7. **`app/api/import_api.py:106-118, 233-237`**：临时文件只在 `/execute` 成功路径清理；上传后放弃、解析失败、导入中途异常三种情况永久泄漏磁盘；`tmp_path` 还把服务器绝对路径回传客户端。修复：启动时清理过期 `zaojia_import_*`、所有失败路径删文件、只回传 token。
8. **`app/api/batch.py:167-178`**：宽限闸门条件 `if grace_days and batch.deleted_at:` —— 对从未进回收站的 `active` 批次整体跳过，admin 可一步硬删「活」批次，30 天回收站窗口形同虚设。修复：`batch.active` 时拒绝并提示先软删。
9. **`tests/conftest.py` + `app/config.py:23` + `app/db.py:9,22`**：**TEST_DATABASE_URL 是「已声称未实现」的假闸门**——config 声称测试隔离专用，但 conftest 与 db.py 都从未读它，隔离 100% 依赖「override get_db + app.state.db_session_factory」两条链。任何绕过 get_db 的新路径（后台任务、脚本、直用 SessionLocal）都会直连开发/生产 PG。修复：conftest 用 `settings.test_database_url` 构造 engine 并 monkeypatch `app.db.SessionLocal`，让隔离从约定变机制。

### 测试守护

10. **`tests/test_security.py:196-211`**：`test_api_routes_have_auth_dependency` 只做文件级字符串检查，给任意路由去掉 Depends 该测试照样绿——形同虚设。修复：遍历 `app.routes`，对每个 APIRoute 检查 dependant 中含鉴权依赖（白名单 PUBLIC_PATHS）。
11. **`tests/test_security.py:45-49`**：`test_dev_token_only_development` 在开发环境下恒通过（零断言）。修复：用 pydantic model_validator 强制 `env=production && dev_token` 抛错，再测该 validator。

---

## 五、P2 —— 次优先，迭代内修

### 性能（规模一大即悬崖）

| 位置 | 问题 | 建议 |
|---|---|---|
| `data_quality_service.py:60-64` | `query.all()` 全表 ORM 加载只为算 4 个占比；且门槛检查每次迁移都触发 | 改 SQL 聚合（page_services.py:925-928 已是正确示范，统一过去） |
| `cost_migration_service.py:38-76, 101-102, 174-181` | 每个 match_key 一次全行查询 + 一次 first()，1 万键 = 2 万查询 | 一条 `group_by(match_key)` + 窗口函数；CostCatalog 用 in_() 批量 |
| `material_match_service.py:167` | confirm_match 循环内全量重建字典候选，批量确认 100 条 = 100 次全表查询 | 移到循环外建一次 |
| `price_service.py:106-108, 136-139` | 全 domain 行 ORM 加载喂纯函数 | SQL 聚合或只 select 需要的列 |
| `page_services.py:691, 569-577` | 每请求加载整张字典表；批次列表无分页且 `_batch_row` 每条算三次 | 只取 L3 + 上限/缓存；SQL 聚合 + 复用 |
| `import_service.py:251, 271` | read_only 模式下逐行 `iter_rows(min_row=r)` 每次从头流式解析 → O(n²) | 一次 `iter_rows` 流式遍历 |
| N+1 懒加载 | `page_services.py:531`（import_batch.name）、`query_service.py:76`（source_location） | joinedload |

### 口径与正确性

| 位置 | 问题 | 建议 |
|---|---|---|
| `page_services.py:830-837` | 单价页 gate/覆盖率在被过滤的「有单价子集」上计算，与 quality 页口径不一致，指标系统性虚高 | gate 用全量查询或复用 get_quality_dashboard |
| `page_services.py:695-702` vs `material_match_service.py:42-61` | 匹配页候选池与 match API 两套实现，spec 来源不同（spec_whitelist[0] vs cat_l3 or name），同一数据给出不同候选 | page_services 复用 service 层 |
| `import_service.py:299-314` | 合并单元格填充在 read_only 下静默失效 → 合并布局文件静默丢行且无 warning | 解析合并信息或至少加 warning |
| `import_service.py:123` | read_only 下 `ws.max_row` 可能为 None，静默返回「导入 0 行成功」 | None 时流式计数 + warning |
| `import_api.py:127` | `data_source_type` 接受任意字符串直写批次并下灌每行，脏值绕过防污染统计口径 | 校验 `in VALID_DATA_SOURCE_TYPES` 否则 422 |
| `batch.py:73, 117` | 软删/还原永久清空 `orphaned` 标记，孤儿溯源不可逆丢失 | 软删只切 active，不动 orphaned |
| `price_service.py:56-70` | 非法过滤字段/操作符静默跳过，统计口径 silently 扩大 | 抛 ValueError 或 warnings 记录 |
| `cost_migration_service.py:95, 165`、`query_service.py:220-233` | like/ilike 通配符 `%`/`_` 未转义 | `contains(value, autoescape=True)` |
| `query.py:63` + `query_service.py:223` | `in`/`not in` 未校验 value 类型；类型不匹配 DataError 直达 500 | 按操作符校验类型，捕获 DataError 转 400 |
| `upsert_service.py:184-196` | B 类审计无 trace_id（一次导入 N 条无法串联），reason 硬编码 | 链路传 trace_id |
| `cost_catalog.py:85-86` | 越权返回 200 + success:False 而非 403 | raise HTTPException(403) |

### 安全（低危但应修）

| 位置 | 问题 | 建议 |
|---|---|---|
| `pages.py:118-119` + `error.html:19` | 渲染异常降级页输出 `str(exc)` 内部细节 | detail 仅 debug 时输出 |
| `pages.py:146-172` | dev_token 走 URL query（进访问日志/历史/Referer）、种 Cookie 前不校验有效性、httponly=False（部分为已声明技术债） | 登录改 POST、先校验再种 Cookie |
| `pages.py:156-158` | 开放重定向未拦 `/\evil.com` 变体 | urlparse 校验 netloc 为空 |
| `pages.py:282` | 真实 dev_token 渲染进导入页 HTML 上下文（模板当前未用，但属不必要暴露） | 只传布尔值 |
| `batch.py:257-258` | 快照文件名固定，旧快照被静默覆盖；csv 异常未全捕获 | 文件名带时间戳；捕获 Exception 走拒绝路径 |
| `import_batch.py:25-27` | file_hash 注释称「幂等键」但无 UNIQUE 约束，并发重复提交不拦截 | 部分唯一索引 |
| `audit_log.py:70-79` | append-only 事件监听可被 Core 级 bulk update/delete 绕过 | PG 触发器（与 REVOKE 一起 M2 落地）或文档声明红线 |
| `material_dict.py:16-45` | 缺 (level, name, parent_id) 唯一约束；重复项会使 Top-1/Top-2 分差=0，**破坏高置信判据**；且删字典项会经 FK SET NULL 静默清空 boq_item.material_dict_id——B 类「禁止删除」被 ondelete 打穿 | 唯一约束 + ondelete=RESTRICT + 停用标记 |
| `base_mixin.py:26-38` | biz_id「不可变」契约无模型层强制 | before_update 事件拦截 |

### 一致性 / 结构（技术债）

- **响应信封五种形状并存**（`{ok}` / `{success,data,error_code}` / `{data,total,warnings}` / `{error:{code}}`），全部路由无 response_model；HTTPException detail 类型混用（字符串/dict/完整信封）；分页参数三套（page/per_page、limit/offset）。建议抽公共 envelope 模块 + 查询类端点补 response_model。
- **service 层重复实现清单**（应收敛）：质量指标（data_quality_service vs page_services）、匹配候选召回（material_match_service vs page_services）、单价分析（price_service vs page_services）、批次列表（page_services vs import_api）、五处 `_err()`、upsert 主循环 vs preview。
- **常量重复定义绕过单一事实源**：`batch_operation_service.py:29-32`、`page_services.py:54-69, 984` 重复定义 data_source_type 合法值/阈值，应 import `data/field_spec`。
- **聚合/统计纯函数混在 service 层**：`page_services._stddev/_histogram/_quantile_rows`、`cost_migration_service._aggregate_for_match_key` 应下沉 data/。
- `main.py:59-63`：`/api/admin/audit-test` 调用的是**不落库**的旧版别名 `audit_log()`（core/audit.py:84-98），与端点 docstring「写一条审计日志」不符；grep 型安全测试测不出。建议改用 log_audit 并补行为测试。
- `conftest.py:52-77`：共享会话掩盖真实事务边界；teardown `dependency_overrides.clear()` 会误清其他 override（应 `pop(get_db, None)`）。
- `tests/test_security.py` 的 S1/S4/S5/S7 均为源码 grep 元测试，等价重构即失效；S1 的 `"buf" in line` 豁免过宽。建议降级标注为 lint 辅助或改行为断言。

---

## 六、P3 —— 择要（不阻断，随迭代顺手修）

- **模型层**：`active` 列缺 `nullable=False`（boq_item/import_batch，与 cost_catalog 不一致）；Numeric 列注解写 float 实际返回 Decimal（cost_catalog.py:77-100、import_batch.py:51）；boq_item 大量裸 String 无长度；缺 `(active, orphaned)` 与 `(aggregate_id, data_source_type, active)` 复合索引；`aggregate_id` dict 分支丢 unit_std 维度（同物料不同单位混入同一均价池，需业务确认口径）；CostCatalog 未进 `models.__all__`；`deleted_at` 只有 ImportBatch 有。
- **data/ 纯函数层**（整体质量高，均为小修）：`unit_normalize.py:15-28` 标准值 `㎡` 自身未注册进映射，输入即计为异常单位（补 `setdefault` + 测试）；`price_calc.py:27-35` historical_avg==0 时 deviation 返回 0.0 掩盖异常（契约级改动，先改测试再改实现；:59-60 compute_kpis 用 `r['unit_rate_num']` 缺键即 KeyError）；`field_spec.py:38-41` C_FIELDS 含模型不存在的 create_uid/write_uid（Odoo 残留）；`aliases.py` 反向索引无冲突自检；`match_score._fuzz` partial_ratio 偏高分宜在 docstring 标注。
- **杂项**：`archive_service.py:43-45` 死代码、meta 存绝对路径致迁移失效、RuntimeError 穿透信封契约、TOCTOU 竞态；`material_match_service.py:188` 审计里硬编码假得分 0.99；`page_services.py:770` 用 30.5 天近似「N 个月」；`upsert_service.py:90` 空字符串 B 值可被覆盖（应判 `is not None`）；多处 `f'...: {exc}'` 异常文本外泄；`app.js:342-384` 批次操作无网络异常处理；`components.css:98` 裸色值违反文件头自定约定；`pages.py:188-192` 根路由死代码（main.py 已注册）；`price.py:23` price_period 未校验 YYYY-MM 格式。

---

## 七、测试覆盖缺口清单（按风险排序）

1. **硬删快照内容正确性**与「快照失败拒绝硬删」分支（batch.py:186-193）——P0-1 正因无内容断言而漏网；
2. **批量操作越权负例**：estimator 改 B 类字段应被拒绝——P0-2 正因无 API 层负例而漏网；
3. `/api/match/find`、`/match/confirm`、`/price/*`、`/quality/dashboard`、`/cost-catalog/*` 端点级鉴权与参数校验测试（当前仅 service 层）；
4. main.py 基础端点（/api/me、/health、audit-test 审计不落库 bug 正因此漏网）；
5. AuditMiddleware 对真实业务写端点的 http_request 审计落库；
6. XSS 回归用例（item_name 注入后 /search 转义输出，当前仅靠 Jinja 约定无回归网）；
7. error.html 降级路径、/login 开放重定向负例；
8. PG 方言差异：全部集成测试跑 SQLite 内存库，生产 PG 行为无 CI 验证；
9. 前端零测试设施（导入向导流程、硬删模态确认）；
10. `normalize_unit('㎡')`、`compute_kpis` 缺键行、match_key 长度上限——pure_tests 守护盲区。

---

## 八、工程配套核查

- **`.env`**：已正确被 .gitignore 排除 ✅；但 `SECRET_KEY=dev-secret-key-change-in-production-...` 为可预测弱值，OA SSO 前必须更换；`.env` 中 `DEBUG=true` 仅限本机。
- **`.gitignore` 缺口**：`.mimosa/`（本次会话的 hook-state 产物目录）、`_poc_check.txt`、`_review_tmp/` 等工具产物未入 ignore，按当前规则会被提交入仓。建议补：`.mimosa/`、`_poc_check.txt`、`_*/`、`deliverables/` 是否入仓需明确决策。
- **git 环境**：本机 shell PATH 中无 `git` 命令（.git 目录存在且含 main + backup-2026-09-06 分支）。建议把 Git 加入 PATH 以便执行 AGENTS.md 的提交前校验（`git status --porcelain | grep -Ei "\.(xlsx|xls|sql|dump)$"`）。
- **测试判据回写**：AGENTS.md 登记的集成基线为「13 passed」（M1.1 时点），实际已有 298 条——基线数字已严重滞后，建议回写为 298（修好 1 个失败用例后）。

---

## 九、建议修复路线图

| 批次 | 内容 | 工作量预估 |
|---|---|---|
| **第 1 批（交付闸门）** | P0-1 快照列补齐 + 内容测试；P0-2/P0-3 权限裁决 + operator 收敛 + 越权负例测试；修复 test_search_hides_topbar 脆弱断言；AGENTS.md 基线回写 | 0.5~1 天 |
| **第 2 批（数据正确性）** | P1-1/P1-2 upsert 孤儿两连 bug（含 preview 抽公共函数）；P1-3 门槛 None 崩溃；P1-4 导出截断；P1-8 active 批次绕过宽限期；测试库隔离机制化（P1-9） | 1~2 天 |
| **第 3 批（安全加固）** | 上传大小限制 + 临时文件生命周期；/login 校验与 str(exc) 泄露；file_hash 唯一约束；material_dict 唯一约束 + RESTRICT；鉴权覆盖测试重写（P1-10/11） | 1~2 天 |
| **第 4 批（性能与结构）** | 全表加载/N+1 五处 SQL 化；合并单元格与 O(n²) 解析；双实现收敛（匹配候选、质量指标、信封统一）；常量归位 field_spec | 2~3 天 |
| **第 5 批（债务清理）** | P3 清单按文件顺手修；utcnow → now(timezone.utc) 统一；索引补齐；docstring 修订 | 持续 |

**裁决需求（需要用户/总控决策，非纯代码问题）**：
1. estimator 能否批量确认异常/切换数据性质（P0-2 二选一）？
2. `aggregate_id` dict 分支是否应带 unit_std（不同单位是否允许混入同一均价池）？
3. `deliverables/` 与审查产物是否入仓？
4. 测试库隔离是否本期机制化（P1-9）？

---

## 附：审查方法说明

- 四路并行深度审查：services 层（11 文件全读）、API 层（9 文件全读）、models+data 层（16 文件全读）、tests+模板+前端（conftest + 重点测试 6 个全读 + 其余浏览 + 11 模板 + app.js + CSS）；
- 核心基础设施（config/db/main/security/permissions/audit）由主审精读；
- 所有 P0/P1 由主审对照源码逐条复核确认；P2/P3 为审查代理报告并抽查；
- 测试基线实测执行（非引用旧文档）。
