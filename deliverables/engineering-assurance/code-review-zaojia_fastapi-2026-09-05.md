# 全面代码审查报告 · zaojia_fastapi（FastAPI 版造价数据门户）

**日期**：2026-09-05
**工作流**：工作流 1 — 全面代码审查（安全 / 性能 / 正确性 / 可维护性 + 架构影响 + 测试覆盖）
**参与成员**：科迪（Cody · 代码审查师）、阿奇（Archi · 系统架构师）、泰莎（Tessa · 测试专家）

---

## 📌 TL;DR（执行摘要）

- **整体结论**：M0 骨架**纯函数层质量扎实**（实测 `pure_tests` 90 passed、应用启动 10 路由达标、依赖/源文件只读/敏感文件门禁均通过），但**安全闸门与交付门禁几乎全部未落地**——鉴权是「任意令牌即 admin」的 fail-open 占位，且 `tests/` 目录根本不存在导致 S1–S9、硬删闸门、集成测试三道硬门禁**不可执行**。
- **严重度分布**：🔴 严重 2 项 / 🟠 高 3 项 / 🟡 中 9 项 / 🟢 低 4 项。
- **阻塞项**：两项 🔴 均须 M1 前解决——① 替换 fail-open 鉴权；② 建立 `tests/` 骨架使硬门禁可被自动化评判。当前代码**严禁暴露到任何非可信环境**，且 M1 现阶段**不具备可量化、可自动化的交付通过标准**。
- **正向亮点**：`data/` 纯函数层与框架层解耦是教科书级健康设计；`field_spec.py` 以 A/B/C 单一事实源 + 启动期 `assert disjoint` 守卫数据安全根基；路由数/启动验证两条铁律已用可量化命令固化。

---

## 🎯 核心结论卡片

| 项目 | 内容 |
|------|------|
| 整体评级 | 🟡 有条件通过（M0 骨架健康；两项 🔴 阻塞项 M1 前必须清除） |
| 阻塞项数量 | 2（🔴 鉴权绕过、🔴 缺失 `tests/` 致硬门禁不可执行） |
| 关键行动项 | 5 条（见行动清单 P0/P1） |
| 建议下一步 | 先补三件「地基」（DB 引擎层+TEST_DATABASE_URL、rapidfuzz 入依赖并锁版本、main.py 改 APIRouter 收口），再一次性锁死数据安全铁律 S1–S9，最后填业务 |

---

## 🔍 审查发现（按严重度排序，已去重合并）

| # | 严重度 | 类别 | 文件:行 | 问题描述 | 建议修复 | 来源 |
|---|--------|------|---------|----------|----------|------|
| 1 | 🔴 严重 | 安全 | `app/core/security.py:14-24` | `get_current_user` 仅在 `credentials is None` 时 401，**带任意 Authorization 头即无视令牌内容返回固定 `{"username":"dev_admin","role":"admin"}`**，admin 闸门（`/api/admin/audit-test` 等）形同虚设，属真实鉴权绕过 | M1.5 前替换为 fail-closed 真实校验（OA SSO 或签名 JWT，密钥从 env 读取）；落地前本服务严禁出可信网络 | Cody / Archi |
| 2 | 🔴 严重 | 测试门禁 | `tests/`（不存在） | `tests/` 目录缺失 → 集成测试、`tests/test_security.py`（S1–S9）、`tests/test_hard_delete_gate.py` 三道硬门禁**不可执行**；AGENTS.md 明文「S1–S9 任一失败=整体不通过、不得交付」，但现实是安全用例连运行都跑不起来（实测 `pytest tests/...` → `collected 0 items`） | M1.1 建立 `tests/` 骨架（`conftest.py` + `test_security.py` + `test_hard_delete_gate.py`）+ `TEST_DATABASE_URL` 隔离；未落地前不具备可量化交付通过标准 | Tessa / Cody |
| 3 | 🟠 高 | 安全/配置 | `app/config.py:11,20` | `secret_key="change-me-in-production"`、`debug=True` 为默认值；可用于伪造签名/会话，`debug` 误开会泄露堆栈 | `secret_key` 改为必填 env（缺失即启动失败）；`debug` 由 env（如 `ENV`/`DEBUG`）控制，禁止提交真实值 | Cody / Archi |
| 4 | 🟠 高 | 依赖 | `requirements.txt` | `data/match_score.py` 依赖 `rapidfuzz` 但**未写入**；干净 `pip install -r requirements.txt` 后 pure_tests 将 `ImportError`（当前靠环境已装蒙混）；且全部依赖**无 `==` 版本锁定** | 立即将 `rapidfuzz` 补入 `requirements.txt`；全量加 `==` 锁定（架构 §4.12 要求） | Cody / Archi |
| 5 | 🟠 高 | 架构/测试 | `app/config.py`（无 `TEST_DATABASE_URL`）+ 无 `app/db.py` | 全仓库 grep 无 `create_engine`/`SessionLocal`/`declarative_base`；AGENTS.md/总控 §9 要求「独立测试库经 `TEST_DATABASE_URL` 切换」，但 config 未定义 → M1 集成测试缺切换入口 | M1.1 建 `app/db.py`（`engine`/`SessionLocal`/`Base`/`get_db`）+ config 补 `TEST_DATABASE_URL`（默认 None 回退 `database_url`） | Archi |
| 6 | 🟡 中 | 正确性 | `data/aliases.py:83,96-101` | 注释承诺「多列命中同一字段→取首个非空列」，实现取「首个列」写入 `header_map`，首列为空、后续列有数据时数据丢失 | 按「首个非空列」语义实现（空列让位），或对齐注释与实现并补单测固化 | Cody |
| 7 | 🟡 中 | 可维护性 | `data/match_score.py:61,65-70` | 权重 `0.7`/`0.3`、`+30`、`98.0`/`10.0`/`100.0` 为裸字面量（魔法数字），与 `price_calc` 已命名常量风格不一致 | 提为模块级常量（`NAME_WEIGHT`/`SPEC_WEIGHT`/`HIGH_CONF_SCORE`/`HIGH_CONF_GAP`），与 M3 常量名对齐 | Cody |
| 8 | 🟡 中 | 安全/审计 | `app/core/audit.py:13-24` | `audit_log` 同步仅 `logger.info`，无落库、无 append-only 表、无集中强制；async 路由内同步写库将阻塞事件循环；「审计不可绕过」铁律在 M0 无任何强制机制 | 改 `async` + 线程池；落 `audit_logs` 表（write/unlink 抛异常）append-only；写路径中间件/事件监听统一强制（S5/S9） | Cody / Archi |
| 9 | 🟡 中 | 正确性/边界 | `data/gb_code.py:50` | 11 位编码仅在 `code[0]!='0'` 时补前导 0；以 0 开头的 11 位编码落入「其他」→ raw 兜底，永不参与国标匹配，边界行为未文档化 | docstring 显式说明该分支取舍与示例，补单测固化，避免后续误改 | Cody |
| 10 | 🟡 中 | 架构 | `app/main.py:24-62` | 单体路由内联定义 + AGENTS.md 硬编码「当前 10 个路由」断言；M1+ 多泳道（查询/导入/单价/物料…）并发改动 `main.py` 必冲突、断言随增长持续失真 | ADR-001：改 `APIRouter` 模块化，`main.py` 仅 `include_router`；启动校验改「import 成功 + 关键路由存在」 | Archi |
| 11 | 🟡 中 | 测试缺口 | `data/field_spec.py`（无测试） | 数据安全根基（`A/B/C` 分层常量、`is_b_field`/`classify_field`/`split_fields_by_layer`）**完全无独立测试**；总控 M0.10 登记「分层函数正确；90 passed」属**虚假通过**（90 用例根本不加载 field_spec） | 补 `pure_tests/test_field_spec.py`（8–10 用例，含 A/B/C 互不相交断言） | Tessa |
| 12 | 🟡 中 | 架构 | 无全局异常处理器 / 统一信封 | 错误走 FastAPI 默认 JSON，与架构 §19.6 统一信封 `{success,error:{code,message}}` 不符，M1 各路由易各写各的 | M1 加 `Exception`/`HTTPException` handler 统一输出信封，错误码前缀按 §19.6（IMPORT_/BOQ_/…） | Archi |
| 13 | 🟡 中 | 架构 | 无 Alembic / 迁移基础设施 | 技术栈写「Alembic 迁移」但仓库无配置；Odoo→新库 ETL 依赖 M1 模型定稿，`biz_id`/`aggregate_id`/A-B-C 分层须与 `field_spec.py` 严格一致，否则迁移零丢失目标受损 | M1.1 定迁移策略（Alembic vs create_all）；与 `field_spec` 常量对齐 | Archi |
| 14 | 🟡 中 | 可运维 | `app/main.py:35`（`/health`） | `/health` 返回静态 JSON 不校验 DB，DB 挂了仍返回 ok（假绿），仅为 liveness 非 readiness | readiness 加 DB ping | Archi |
| 15 | 🟢 低 | 安全/可维护 | `app/static/demo/check.py` | demo 自检脚本（含内部 node 绝对路径）被当静态文件公开；Starlette 已拒路径穿越（无漏洞）但属信息暴露，且自检脚本不该进 static 目录 | 移出 `static` 或仅暴露必要资源 | Cody |
| 16 | 🟢 低 | 可维护/文档 | `data/__init__.py:8-13` | 文档仅列 `gb_code/aliases/unit_normalize` 三文件，实际 `data/` 已有 8 模块 | 更新 `__init__` 文档反映当前模块集合与「互不交叉 import」惯例 | Cody |
| 17 | 🟢 低 | 架构 | 无 CORS / AllowedHosts | 公司网页嵌入（iframe/子路径）跨域与 OA 会话传递尚未补齐 | M2.5/OA 阶段补 CORS 与 AllowedHosts | Archi |
| 18 | 🟢 低 | 架构 | 无请求体大小上限 / 限流 | 导入 ≤50MB 上限（架构 §4.3）是业务规则，未在 HTTP 层兜底 | M2 导入服务加 `Request` 大小限制 | Archi |

---

## 🏗️ 架构影响评估（Archi）

**评级：🟡 需关注**——无「🔴 阻断级」结构缺陷；M0 骨架与「纯函数层 / 框架层」解耦决策是健康基础，文档对数据安全铁律、泳道分工、API 契约约束清晰。

- **最健康设计**：`data/` 零框架依赖、三文件互不交叉 import、`field_spec.py` 单一事实源 + `assert disjoint` 守卫；可无 DB/HTTP 独立测试，Odoo 迁移零语言转换，90 基线稳固。维持「data 不反向依赖 service/model」单向约束。
- **关键 ADR（建议回写总控 §7）**：
  - **ADR-001 · APIRouter 模块化**：各能力模块以 `app/api/<domain>.py` 定义 `APIRouter`，`main.py` 仅 `include_router`；消除多泳道合并冲突与「10 路由」脆弱断言。
  - **ADR-002 · 测试库隔离显式化 + 认证默认 fail-closed**：config 补 `TEST_DATABASE_URL` + 建 `app/db.py` 引擎层；认证 M1.5 默认「拒绝一切」，仅在显式 dev 配置下允许占位账号。
- **架构级技术债（按影响）**：① 认证 fail-open；② 无 DB 引擎层/TEST_DATABASE_URL；③ requirements 缺 rapidfuzz；④ 数据安全铁律无强制机制；⑤ main.py 单体路由；⑥ 无全局异常处理器/统一信封；⑦ 无 Alembic；⑧ data 阈值常量重复（当前测试守卫已够）；⑨ /health 假绿；⑩ 无 CORS；⑪ 无请求体大小上限。
- **对 M1 的最优先建议（先补三件地基再写业务）**：① 建 `app/db.py` + `TEST_DATABASE_URL`；② rapidfuzz 入依赖并锁版本；③ main.py 切 APIRouter 收口。数据安全铁律（S1–S9）按「地基」定位在 M1 内一次性锁死，不留到上线前。

---

## 🧪 测试覆盖评估（Tessa）

**评级：🔴 严重缺口**——已具备可量化自动化的门禁 5 道（纯函数 90 passed、应用启动、依赖、源文件只读、敏感文件）；**缺失且不可执行 3 道硬门禁**（集成测试 / S1–S9 / 硬删闸门），因 `tests/` 不存在跑不起来。

- **现状核验（实跑）**：`pytest pure_tests/ -v` → `90 passed in 0.37s`；应用启动 → `ROUTE_COUNT=10`；依赖 → `deps OK`；`grep .save(` / `load_workbook` / 敏感文件 → 均无违规（但属 M0 空桩，M1 后须复测）。三条 `pytest tests/...` 均 `ERROR: file or directory not found` → `collected 0 items`。
- **缺失门禁影响**：S1–S9（最高优先级阻塞，明文「任一失败=不交付」）、硬删闸门（R1 缺陷教训）、集成测试（M1 模型/服务/API/权限改动无验证入口）均不可执行。S8 备份演练为季度人工项，须标注本季度已/未演练。
- **纯函数层缺口**：`match_score` 恰好 `score==98`/`gap==10` 边界未测（驱动「自动确认免复核」开关，漂移风险高）；`quality_metrics` 门槛边界未直接断言；**`field_spec.py` 完全无测试**（虚假通过，见发现 #11）。
- **路由可测性**：当前 4 个占位路由（/、/api/me、/api/public/hello、/api/admin/audit-test）无可测业务逻辑；先有业务（models/services/api 落地）才有集成测试。
- **M1 推荐 `tests/` 结构**：`conftest.py`(TEST_DATABASE_URL 切换+create_all+清空) / `test_security.py`(S1–S9) / `test_archive.py`(S2/S6) / `test_hard_delete_gate.py` / `test_permissions.py` / `test_api.py` / `test_import.py` / `test_models.py`；夹具脱敏、禁真实数据。纯函数层（含补 `test_field_spec.py`）继续留 `pure_tests/`。
- **S1–S9 最小用例清单**：S1 导入前后源文件 SHA256 一致；S2 归档==file_hash；S3 重导后 10 行 B 类标注仍在；S4 软删→回收站可见→还原完整；S5 改单价→audit_log 出现 old→new 四元组；S6 sum(total_num) 与 Excel 合计行一致（容差 0.01）；S7 导入 pending_review 后历史均价不变；S8 季度人工演练+抽样 10 条逐字比对→`docs/backup_drill.md`；S9 仓库无真实 xlsx/sql/dump + 本地绑定 + 导出记审计。
- **立即可补（不依赖 M1 业务）**：① `pure_tests/test_field_spec.py`（8–10 用例）；② `match_score`/`quality_metrics` 边界用例。

---

## ✅ 行动清单（按优先级排序）

| # | 行动 | 负责角色 | 紧急度 | 预期完成 |
|---|------|----------|--------|----------|
| 1 | 替换 `security.py` 占位鉴权为 fail-closed 真实校验（OA SSO/JWT，密钥 env）；落地前严禁出可信网络 | 执行 Agent（M1.5 泳道） | P0 | M1.5 前 |
| 2 | 建立 `tests/` 骨架（`conftest.py` + `test_security.py` S1–S9 + `test_hard_delete_gate.py`）+ `TEST_DATABASE_URL` 隔离，使硬门禁可自动化评判 | 执行 Agent（M1.1 测试基建） | P0 | M1.1 前 |
| 3 | `config.py`：`secret_key` 改必填 env、`debug` 由 env 控制；补 `TEST_DATABASE_URL` + 建 `app/db.py` 引擎/会话/Base/get_db | 执行 Agent（M1.1） | P0 | M1.1 前 |
| 4 | `requirements.txt` 补 `rapidfuzz` 并全量 `==` 锁定版本 | 执行 Agent（Agent-0） | P1 | 立即 |
| 5 | 修 `aliases.py` 首个非空列语义并补单测固化 | 执行 Agent（数据层） | P1 | M1 前 |
| 6 | 补 `pure_tests/test_field_spec.py` 解虚假通过 + 补 `match_score`/`quality_metrics` 边界用例 | 执行 Agent（测试） | P1 | M1 前 |
| 7 | `audit_log` 改 async + 落 append-only `audit_logs` 表 + 写路径统一强制（S5/S9） | 执行 Agent（M1.4） | P1 | M1.4 前 |
| 8 | `main.py` 改 `APIRouter` 模块化收口（ADR-001） | 执行 Agent（Agent-0） | P1 | M1 初 |
| 9 | 加全局异常处理器 + 统一信封（§19.6）；`/health` 加 DB ping | 执行 Agent（M1） | P2 | M1 内 |
| 10 | 定 Alembic 迁移策略，biz_id/aggregate_id/A-B-C 与 `field_spec` 严格对齐 | 执行 Agent（M1.1） | P2 | M1.1 |
| 11 | 清理：`data/__init__.py` 文档更新；`demo/check.py` 移出 static；补 CORS/AllowedHosts、请求体大小上限 | 执行 Agent | P2 | M2 内 |

---

## ⚠️ 待完善 / 已知局限

- **M1 业务层未落地**：`app/models/`、`app/services/`、`app/api/` 为空桩，故 SQL 注入、XSS、ORM 相关审查、集成测试均「无可评对象」——上述缺口属 M1 待办，非代码缺陷（已严格区分）。
- **S8 备份恢复演练**：本季度未演练，备份有效性待人工核验（须真实数据 + 临时库，写 `docs/backup_drill.md`）。
- **源文件只读 / 硬删闸门 / S1–S9**：当前无对应实现代码（导入功能未实现），须由 `grep` 红线 + 双次 SHA256 + CSV 快照闸门在 M1 落地时守卫。
- 本次审查基于当前 M0 代码快照（2026-09-05）；M1 改动后须重跑 AGENTS.md 全部测试命令并触发 Self-Improving + Proactive Agent 审查。

---

## 📚 数据来源 & 成员产出索引

- 科迪（代码审查师）原始产出：安全/性能/正确性/可维护性审查发现表（#1–#10）+ AGENTS.md 安全闸门符合性核对表（实测 90 passed、routes=10）。
- 阿奇（系统架构师）原始产出：架构评估表（12 维）+ ADR-001/ADR-002 + 架构级技术债清单（11 项），评级 🟡 需关注。
- 泰莎（测试专家）原始产出：测试现状核验表（7 项实跑）+ 缺失门禁影响表 + S1–S9 最小用例清单 + M1 `tests/` 结构建议；完整版已落盘 `docs/test_coverage_assessment.md`，评级 🔴 严重缺口。
- 本次审查实际执行命令：`pytest pure_tests/ -v`（90 passed）、应用启动验证（ROUTE_COUNT=10）、依赖检查（deps OK）、`grep` 源文件只读/敏感文件校验、三条 `pytest tests/...`（确认缺失）。

---

> 本报告由工程保障团队 AI 协作生成，关键决策请由人类工程负责人（总控 Agent）复核并回写 `项目总控.md` §7 / §9.2。
