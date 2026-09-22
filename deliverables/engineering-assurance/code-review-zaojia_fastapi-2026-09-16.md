# 工程审查报告 · zaojia_fastapi（单价分析 + 清单检索模块）

- **审查工作流**：综合代码审查（ engineering-playbook 工作流 1）
- **审查团队**：engineering-code-review（三方视角合并）
  - Cody — 代码审查（安全 / 性能 / 正确性 / 可维护性）
  - Archi — 架构评估（数据加载模式 / SQL 相似度依赖 / N+1 / 事务边界）
  - Tessa — 测试覆盖分析（盲区 / 纯函数 / 同义词硬编码）
- **日期**：2026-09-16
- **审查范围**：`app/services/page_services.py`（get_price_analysis / search_boq_items）、`app/services/price_service.py`、`app/services/query_service.py`、`app/services/material_match_service.py`、`app/services/prematch_service.py`、`data/price_calc.py`、`app/services/material_classifier.py` 及对应 API 路由 `app/api/pages.py`。
- **方法**：直接读源码 + 行级取证；不重新猜测路径，所有结论均给出文件:行号。

---

## TL;DR

1. **P0 正确性缺陷**：`data/price_calc.py:20` 把单价异常阈值 `DEFAULT_THRESHOLD` 写成 `0.95`（即 95% 偏离），但 M3 设计文档、全部注释、以及两套测试都按 **30%** 设计。运行时单价异常检测几乎永不触发，"单价异常/偏离预警"功能实质失效。
2. **P0 架构/性能债**：`get_price_analysis` 用 `items = q.all()` 把整张有效单价表全量拉进进程内存，再逐行跑正则分类 + Python 聚合；百万行场景下内存与 CPU 不可接受。同一反模式还出现在 `search_boq_items` 默认排序、`/portal/price/samples`、`price_service.get_kpis/get_analysis`。
3. **P1 数据完整性 bug**：`material_match_service.confirm_match` 的同义词自动扩展，在 `synonyms` 为 dict 时取字段名键并覆盖原结构化 dict，会污染/破坏物料字典同义词。
4. **安全**：未发现 SQL 注入 / XSS 漏洞（LIKE 值均经参数化、字段名白名单、XSS 已转义）；但模糊分支 `except: pass` 静默吞错，可观测性差。
5. **测试**：纯函数层（price_calc）覆盖良好；**两个核心页面函数 `search_boq_items` / `get_price_analysis` 几乎没有行为级测试**，是最大的上线回归盲区。

---

## 核心结论卡片

| 维度 | 结论 | 关键证据 |
|------|------|----------|
| 安全 | ✅ 无注入/XSS（参数化 + 白名单 + 转义） | `query_service.py:194` `_build_filters` 白名单；`page_services.py:538` ilike 参数化；`test_pages.py:211` XSS 转义 |
| 性能 | ❌ 全量加载 + Python 端聚合，百万行不可接受 | `page_services.py:1300` `q.all()`；`:649` 全量排序；`pages.py:392` 全量分类 |
| 正确性 | ⚠️ `DEFAULT_THRESHOLD=0.95` 与规格 30% 冲突；confirm_match 同义词覆盖 bug | `price_calc.py:20`；`material_match_service.py:286,294` |
| 可维护性 | ⚠️ 两套过滤实现、死参数、重复计算、硬编码同义词 | `page_services.py:509` `_SYNONYMS`；`price_calc.py:84` `measures` 未用 |
| 测试 | ⚠️ 纯函数强、页面服务弱 | `test_price_calc.py` 覆盖好；`search_boq_items`/`get_price_analysis` 无单测 |

---

## 分级问题表

### 🔴 P0（必须修）

| # | 类型 | 问题 | 位置 | 建议修复 |
|---|------|------|------|----------|
| P0-1 | 正确性 | 单价异常阈值 `DEFAULT_THRESHOLD = 0.95`（95% 偏离），但 M3 §3.4 规格、全部 docstring、以及 `tests/test_price_service.py`、`pure_tests/test_price_calc.py` 都按 **30% (0.30)** 设计。`compute_kpis` 的 `anomaly_count` 用此默认阈值 → 近乎不触发，"单价异常标记/偏离预警"功能失效。UI 还把 95 展示给用户（`page_services.py:1464/1476/1602`）。两套测试因显式传 `threshold=0.30` 而掩盖了该默认值缺陷。 | `data/price_calc.py:20,38,73,114`；`page_services.py:1464,1476,1602` | 确认语义后将 `DEFAULT_THRESHOLD` 改为 `0.30`；补一条 `assert price_calc.DEFAULT_THRESHOLD == 0.30` 的断言测试，锁定规格。 |
| P0-2 | 性能/架构 | 单价分析全量加载：`items = q.all()` 拉取全部 `active and unit_rate_num not null` 行（百万级），随后逐行 `classify_boq`（正则）`page_services.py:1304` + 去重 + Python 聚合。单请求内存/CPU 随数据量线性增长，无法水平扩展。 | `page_services.py:1300`；`material_classifier.py:164` | 将 KPI/分组聚合下推到 PostgreSQL（GROUP BY `aggregate_id`/`price_period` + 窗口函数算加权均价/分位数）；至少先用 `with_entities` 取所需列并流式处理，避免整表 ORM 对象入内存。 |

### 🟡 P1（应当修）

| # | 类型 | 问题 | 位置 | 建议修复 |
|---|------|------|------|----------|
| P1-1 | 数据完整性 | `confirm_match` 同义词自动扩展：当 `d.synonyms` 为 dict 时，`list(current_syns.keys())` 取到的是"规格/材质/型号/单位/材料名称"等**字段名键**而非同义词，且 `d.synonyms = syn_list` 用扁平 list **覆盖**了原结构化 dict → 丢失规格/材质/型号/单位属性，并向同义词污染字段名。 | `material_match_service.py:286,294` | 统一 `synonyms` 为 list 存储；若原值为 dict，抽取其 `"list"` 值（参照 `page_services.py:857` `_dict_node` 逻辑），不要取 keys；禁止在写回时破坏结构化字段。 |
| P1-2 | 性能 | 逐行正则分类 `classify_boq` 是 O(n) 且每条含多正则 + 电缆型号 18 条遍历；百万行 × 每条多次 `re.search` 累积 CPU 显著。 | `material_classifier.py:164`；`page_services.py:1304` | 优先按已落库的 `aggregate_id`/`cat_l3` 列做 SQL 分组聚合，避免在服务层对每行重跑分类；或在导入/标准化阶段把分类结果缓存到列。 |
| P1-3 | 性能 | `price_service.get_kpis/get_analysis` 用 `query.all()` 加载**完整 BoqItem ORM 对象**（全部列），但仅用到 `unit_rate_num` 及分组列。 | `price_service.py:108,138` | 改用 `with_entities(BoqItem.unit_rate_num, BoqItem.aggregate_id, ...)`，降低内存与序列化开销。 |
| P1-4 | 一致性 | 清单检索存在两套过滤实现：`page_services.search_boq_items` 内联拼 LIKE（`:567-584`），与 `query_service._QUERYABLE_FIELDS + _build_filters` 白名单（`:181-235`）口径不同，长期易漂移、且前者字段白名单未在 API 层统一。 | `page_services.py:567-584`；`query_service.py:181-235` | 检索统一复用 `query_service._build_filters` 白名单，消除双口径。 |
| P1-5 | 正确性 | `search_boq_items` 模糊分支触发后，`:674` 的 `std_count = q.filter(...).count()` 仍使用原始**精确匹配**查询 `q`（kw 过滤仍在），而 `total` 已被重设为"精确+模糊"计数（`:633`）。导致模糊模式下 `stdCount` 仅统计精确命中、`pendingCount` 被高估，与 `hitCount` 口径不一致。 | `page_services.py:623-638,674-675` | 模糊模式下基于 fuzzy 结果集重算 std/pending，或统一计数来源。 |

### 🟢 P2（建议/隐患）

| # | 类型 | 问题 | 位置 | 建议 |
|---|------|------|------|------|
| P2-1 | 可靠性 | 模糊分支 `except Exception: pass`（`:637`）静默吞掉所有异常（含 pg_trgm 未启用、列不存在），且无日志。测试库为 SQLite 时该分支永远失败被跳过 → 模糊召回能力在生产外无法验证；若迁移未跑则生产静默失效。 | `page_services.py:637` | 至少 `logger.warning`；增加 pg_trgm 可用性启动自检/健康检查。 |
| P2-2 | N+1 | `get_pending_matches` 循环内逐条查 `ListMaterialMapping`（`:1107`），limit=50 即 50 次查询；且 `:1099` 已算 `rf_cands`，`:1129` 无映射分支又重复计算。 | `page_services.py:1099,1107,1129` | 一次性批量预载映射表（参照 `auto_confirm_high_conf` `:1193` 已有先例），去掉重复 `score_candidates`。 |
| P2-3 | 并发 | `prematch_service._prematch_status` 为模块级全局 dict；多 worker（gunicorn 多进程）下状态不共享、`running` 锁仅单进程有效，`precompute_pending_matches_async` 仅在单进程 daemon 线程跑。 | `prematch_service.py:27,160` | 用 DB/Redis 状态表或任务队列（Celery/RQ）记录运行状态，跨进程可见。 |
| P2-4 | 可维护性 | `_SYNONYMS` 硬编码于 `search_boq_items`（`:509`），且 `"钢管":[...]` 列表含重复 `"焊接钢管"`；同义词扩展逻辑（`:528-532,551-555`）无单测。 | `page_services.py:509` | 抽常量到 `data` 层 + 去重 + 补同义词扩展单测。 |
| P2-5 | 可维护性 | `analyze_group` 的 `measures` 参数（`:84`）声明但未使用（死参数）。 | `price_calc.py:84` | 删除或实现。 |
| P2-6 | 正确性-边界 | `get_price_analysis` 的 `range_months` 兜底：`:1296` 仅用 `q_month.first()` 判断"是否存在"而非"样本是否充足"，近 N 月只有 1 条也可能被采用，而 `min_sample` 仅展示未强制。 | `page_services.py:1293-1297` | 兜底前校验样本量下限，不足则回退全量并标注。 |

---

## 架构影响评估（ADR 视角）

> **ADR-2026-09-16：单价分析/清单检索的聚合计算下沉**
> **状态**：提议 ｜ **决策者**：工程保障团队 ｜ **日期**：2026-09-16

**背景**：项目已规划"百万级数据量迁移方案"（pg_trgm + GIN 索引已上线，迁移 `c3d4e5f6a7b8`）。但当前 `get_price_analysis` / `search_boq_items` 在应用进程内对全量明细做 Python 聚合与相关度排序，与"百万行毫秒级"目标相悖。

**考虑方案**
- **方案 A（现状）**：Python 端 `q.all()` + 正则分类 + 字典聚合。
  - 复杂度：低（已实现）；成本：O(n) 内存 + O(n) CPU，单请求打满进程内存，无法水平扩展；熟悉度：高。
- **方案 B（推荐）**：聚合下推 SQL。KPI/分组用 `GROUP BY aggregate_id/price_period` + 窗口函数；加权均价、分位数用 SQL 表达式；相关度排序在 DB 侧或限制全量上限 + 游标分页；`classify_boq` 结果在导入/标准化期缓存到列。
  - 复杂度：中（需改聚合 SQL + 可能加列）；成本：返回行数 = 聚合组数（远小于明细），内存恒定；可扩展性：好（DB 承担，可加只读副本）；熟悉度：中。

**权衡 → 决策**：百万行场景下方案 A 不可持续，采纳 **方案 B**。pg_trgm 已就绪，模糊相似度可继续留在 DB 侧（保持）。

**后果 / 行动项**：见"行动清单"。

**其他架构关注点**
- **pg_trgm 依赖**：硬依赖已通过迁移固化（好）；但 `search_boq_items` 模糊分支"静默失败"（P2-1）需补可观测性。
- **N+1**：`get_pending_matches` 逐条映射查询（P2-2）是典型 N+1，已有 `auto_confirm_high_conf` 批量预载先例可借鉴。
- **事务边界**：读路径（`get_price_analysis`/`search_boq_items`）用 `_session_scope` 正确关闭会话（`:97`）；`confirm_match` 单事务提交（含审计 + 同义词写）合理，但需注意 P1-1 的同义词写会污染数据；`auto_confirm_high_conf` 显式 `commit`（`:1240`）在导入后跑，边界清晰。

---

## 测试覆盖盲区（Tessa 视角）

**已覆盖（强）**
- `data/price_calc.py` 纯函数：`deviation_pct` / `is_anomaly` / `compute_kpis` / `analyze_group` 均有单测（`pure_tests/test_price_calc.py` + `tests/test_price_service.py`），含 None 过滤、样本下限、加权均价、非法维度抛错。
- `query_service.search_items` 白名单注入安全与分页（`tests/test_query_api.py`）。
- 页面路由鉴权/重定向/XSS 转义（`tests/test_pages.py`）。

**盲区（弱 / 零）**
- `search_boq_items`（`page_services.py:470`）：**无行为级单测**。仅 `test_pages.py` 的 200 冒烟与 XSS。模糊兜底、同义词扩展、Python 侧相关度排序（`_score`）、`stdCount/pendingCount` 口径、分页越界夹取均未覆盖。
- `get_price_analysis`（`page_services.py:1259`）：**无行为级单测**。KPI/趋势/直方图/分组/门禁/`range_months` 兜底/聚合组下钻均未覆盖。
- `_SYNONYMS` 同义词扩展（`page_services.py:509,528-532,551-555`）：**无单测**。
- `material_match_service.confirm_match`：未见专门单测（grep 未命中 `test_match*`）；同义词写回路径无覆盖 → 未能捕获 P1-1 的 dict 覆盖 bug。
- `prematch_service`：未见预匹配状态/缓存读取的专项测试。
- `price_calc` 缺 **`DEFAULT_THRESHOLD` 取值断言** → 未捕获 P0-1 的 0.95 缺陷。

**结论**：纯函数层强、服务/页面层弱；两个核心页面函数（搜索 / 单价分析）几乎零行为覆盖，是上线回归最大盲区。

---

## 行动清单

1. **【P0-1】修异常阈值**：`data/price_calc.py:20` 将 `DEFAULT_THRESHOLD` 改为 `0.30`（确认语义后），并补 `assert DEFAULT_THRESHOLD == 0.30` 测试；回归验证 `anomaly_count` 在 30% 下触发。
2. **【P0-2 / P1-2 / P1-3】聚合下沉 SQL**：`get_price_analysis` 改为 `GROUP BY` + 窗口函数聚合（或至少 `with_entities` + 流式）；同步修复 `search_boq_items` 默认排序全量加载（`page_services.py:649`，改 DB 侧排序/分页）与 `/portal/price/samples` 全量分类（`pages.py:392`）；`price_service.get_kpis/get_analysis` 改 `with_entities`。
3. **【P1-1】修同义词覆盖 bug**：`confirm_match` 统一 `synonyms` 为 list，dict 场景抽取其 `"list"` 值而非 keys；补 `confirm_match` 单测（覆盖 dict/list 两种 `synonyms` 形态）。
4. **【P1-4 / P2-2】收敛过滤与 N+1**：检索统一复用 `query_service._build_filters` 白名单；`get_pending_matches` 批量预载 `ListMaterialMapping` 并去掉重复 `score_candidates`。
5. **【P2-1 / 测试盲区】补测试与可观测性**：为 `search_boq_items`（模糊兜底/同义词/相关度/计数口径）、`get_price_analysis`（KPI/趋势/门禁/range 兜底）、`_SYNONYMS` 补行为单测；模糊分支加 `logger.warning` 与 pg_trgm 启动自检。
6. **【P2-3】预匹配状态跨进程化**：`prematch_service` 状态改 DB/Redis 状态表或任务队列，支持多 worker。

---

## 数据来源索引

| 文件:行 | 主题 |
|---------|------|
| `data/price_calc.py:20` | `DEFAULT_THRESHOLD = 0.95`（P0-1 根因） |
| `data/price_calc.py:38,73,114` | `is_anomaly`/`compute_kpis` 使用默认阈值 |
| `app/services/page_services.py:470` | `search_boq_items` 入口 |
| `app/services/page_services.py:509` | `_SYNONYMS` 硬编码（P2-4） |
| `app/services/page_services.py:528-532,551-555` | 同义词扩展逻辑（无单测） |
| `app/services/page_services.py:623-638` | 模糊兜底 `matched_ids` 全量取 ID + `except: pass`（P2-1） |
| `app/services/page_services.py:649` | 默认/相关度排序全量 `q.all()` 后 Python 排序（P0-2） |
| `app/services/page_services.py:674-675` | 模糊模式下 stdCount/pendingCount 口径不一致（P1-5） |
| `app/services/page_services.py:1259` | `get_price_analysis` 入口 |
| `app/services/page_services.py:1300` | `items = q.all()` 全量加载（P0-2） |
| `app/services/page_services.py:1304` | 逐行 `classify_boq`（P1-2） |
| `app/services/page_services.py:1464,1476,1602` | 向 UI 展示 `int(DEFAULT_THRESHOLD*100)=95` |
| `app/services/page_services.py:1099,1107,1129` | `get_pending_matches` N+1 + 重复计算（P2-2） |
| `app/services/price_service.py:108,138` | `get_kpis/get_analysis` 全量 `query.all()`（P1-3） |
| `app/services/query_service.py:181-235` | `_QUERYABLE_FIELDS` + `_build_filters` 白名单（P1-4 统一目标） |
| `app/services/material_match_service.py:286,294` | `confirm_match` 同义词 dict 覆盖 bug（P1-1） |
| `app/services/prematch_service.py:27,160` | 模块级全局状态、`daemon` 线程（P2-3） |
| `app/services/material_classifier.py:164` | `classify_boq` 正则分类（P1-2 成本） |
| `app/api/pages.py:392` | `/portal/price/samples` 全量加载 + 逐行分类（P0-2） |
| `app/api/pages.py:437,462` | 单价分析页面/JSON 路由 |
| `tests/test_price_service.py` | price_service 单测（缺 get_price_analysis） |
| `pure_tests/test_price_calc.py` | price_calc 纯函数单测（缺 DEFAULT_THRESHOLD 断言） |
| `tests/test_pages.py:211` | XSS 转义测试；无 search_boq_items/get_price_analysis 行为测试 |
| `alembic/versions/c3d4e5f6a7b8_add_pg_trgm_gin_indexes.py` | pg_trgm 扩展 + GIN 索引（已上线，P2-1 依赖） |

---

*落盘说明：本报告按工程保障 Expert 规范写入 `deliverables/engineering-assurance/code-review-zaojia_fastapi-2026-09-16.md`，并同步结论至 team-lead。*
