# 全面代码审查报告 · 造价数据门户（FastAPI 版）

**日期**：2026-09-09
**工作流**：工作流 1（全面代码审查）
**参与成员**：Tessa（测试专家，子代理产出已回收）+ 甄宇航（工程督导，亲自取证）
**成员调度说明**：`code-reviewer` / `architect` 子代理调度工具在本环境不可用（报错 `Tool Agent not found`），其负责的**安全 / 架构维度由主理人亲自取证完成**，非代写结论——全部发现均附 `文件:行号` 与命令原样证据。
**审查范围**：101 个 Python 文件 / 21,583 行 / 77 个端点（实测，非文档登记值）

---

## 📌 TL;DR

- 整体结论：**代码地基扎实，安全铁律主体落实到位**，但**"登记了门禁却没有实现"是本次最突出的系统性风险**——4 项 🔴 全部属于这一类。
- 严重度分布：🔴 严重 4 项 / 🟠 高 6 项 / 🟡 中 6 项 / 🟢 低 2 项，另 8 项正面结论（已验证合规）。
- 阻塞性：**不建议在补齐硬删闸门测试、数据库版本化迁移、CI 之前上线生产**。OA SSO 未对接前 `security.py` 生产期全局 503，本就不可上线。

---

## 🎯 核心结论卡片

| 项目 | 内容 |
|------|------|
| 整体评级 | 🟡 **有条件通过**（M1–M4 功能实现合格；安全门禁与运维基建存在系统性缺口） |
| 阻塞项数量 | 4（🔴） |
| 关键行动项 | 10 条 |
| 建议下一步 | 先补 C1–C4 四项门禁（1–2 天），再动 OA SSO 与数据迁移 |

---

## 🔍 审查发现（按严重度排序）

| # | 严重度 | 类别 | 文件:行 | 问题描述 | 建议修复 | 来源 |
|---|--------|------|---------|---------|---------|------|
| C1 | 🔴严重 | 门禁缺失 | `AGENTS.md` / `tests/` | **`tests/test_hard_delete_gate.py` 从未创建**。AGENTS.md 登记该命令为"改动删除/回收站逻辑后必跑"，执行直接报错。且"硬删前 CSV 快照失败必须拒绝物理删除"这一 fail-closed 行为**无任何测试模拟**（grep 无 monkeypatch snapshot/None）。代码层闸门存在（`app/api/batch.py:187-190`），但**无自动化断言**，回归即可击穿 | 新建 `tests/test_hard_delete_gate.py`：monkeypatch `_export_snapshot` 返回 `None`，断言返回 5xx 且批次仍可查 | Tessa |
| C2 | 🔴严重 | 数据安全 | `app/db.py:68` | **数据库无版本化迁移**。无 `alembic/`、无 `migrations/` 目录，仅 `Base.metadata.create_all(bind=engine)`。B 类数据不可重建，schema 变更无法回滚、无法审计、无法重复执行 | 引入 Alembic，`init_db()` 改为 `alembic upgrade head`；`create_all` 仅限测试 | Archi/主理人 |
| C3 | 🔴严重 | 门禁缺失 | 仓库根 | **无 CI 配置**（`.github/workflows` 缺失）。545 条测试无自动回归，全靠人工自觉；AGENTS.md 的"每次改动必须跑测试"无机械强制 | 加 `.github/workflows/pytest.yml`，分跑 `pure_tests/` 与 `tests/` | Tessa |
| C4 | 🔴严重 | 门禁缺失 | `AGENTS.md` §数据安全 | **S8 备份恢复演练无自动化**（docstring 明示"无自动化"），却被登记进 S1–S9 序列并声明"优先级高于功能用例、任一失败即不通过""未演练过的备份视为无效"。实际全靠人工季度纪律 | 二选一：①补自动化（临时库 pg_restore 抽样校验）；②从 S 序列剔除，降级为显式 manual-gate 清单 | Tessa |
| C5 | 🟠高 | 架构一致性 | `app/core/security.py:75` vs `app/api/pages.py:74,248` | **两套并行鉴权体系，角色来源不一致**。API 层开发期**恒返回 admin**（`user = {"username": "dev_admin", "role": ROLE_ADMIN}`）；页面层角色**从 `zj_role` Cookie 读取且 `httponly=False`**（客户端可读写）。同一 token 在两个体系里权限语义不同 | OA SSO 对接时统一为一套 `get_current_user`；角色一律服务端映射，禁止来自客户端 Cookie | 主理人 |
| C6 | 🟠高 | 权限治理 | `app/core/permissions.py:64` | **权限矩阵未落地**。`require_permission` **零生产引用**（仅定义 + 单测），39 处端点用 `require_role(...)` 硬编码角色列表。`_ROLE_PERMISSIONS` 自称"单一事实源"实为**双源**，改一处即漂移 | 端点统一改 `require_permission("xxx")`；`require_role` 仅作兼容保留 | 主理人 |
| C7 | 🟠高 | 架构债 | `data/learning_engine.py` | **v1 生产路径死代码**。全仓无任何生产代码 import v1（v3 只 import v2，`learning_engine_v3.py:24`），仅 `pure_tests/test_faiss_learning.py:8` 引用。意味着 236 条纯函数测试中有相当部分**在测永不执行的代码** | 确认后删除 v1 及其测试，或明确标注为历史归档 | 主理人 |
| C8 | 🟠高 | 测试质量 | `tests/test_security.py:68,117,143` | **S1/S4/S7 为源码扫描式断言**（grep 注释文本 / `'completed'` 字符串），改名或调代码格式即可失效或误判，属脆断断言 | 升级为行为断言（直接调用 `confirm_match` 验证 B 字段不被覆盖） | Tessa |
| C9 | 🟠高 | 正确性 | `app/services/archive_service.py:189`、`app/services/page_services.py:303,421` | **F011 datetime 改造未全覆盖**。3 处仍为 naive `datetime.now()`（F011 声称消除 3352 条告警）。archive 时间戳进归档路径与审计，时区语义不一致 | 统一改 `datetime.now(timezone.utc)` | 主理人 |
| C10 | 🟠高 | 基线漂移 | `项目总控.md:202`、`AGENTS.md` | **测试基线过期**。登记 `tests/ = 276`，实测 **309**（+33）。门禁判据失真，新人按文档核对必然误判 | 更新 §9.1 为 309，并纳入 CI 校验 | Tessa |
| C11 | 🟡中 | 规范 | `app/api/query.py:186` | `wb.save(buf)` 属允许例外（导出向 BytesIO 生成全新文件），但**无注释说明**——AGENTS.md 明确要求"命中例外处须有注释" | 加注释标注为例外 | 主理人 |
| C12 | 🟡中 | 可维护性 | `app/` 全局 | `except` 46 处、其中 `pass` 5 处，存在异常吞噬面 | 逐个审查 5 处 `pass`，补 logging | 主理人 |
| C13 | 🟡中 | 覆盖缺口 | `app/services/prematch_service.py` + `/api/match/prematch` | **零测试覆盖**（test_match_service / test_match_key 均无引用），却是匹配主链路的前置 | 补单测 + 集成测试 | Tessa |
| C14 | 🟡中 | 覆盖缺口 | `data/file_parser.py` / `field_mapper.py` / `validation_engine.py` / `archive_enhanced.py` | 仅 `pure_tests/test_m2_enhanced.py` 单文件浅覆盖，ADR-F010 四大模块无独立断言 | 在 test_m2_enhanced 内拆出独立断言组 | Tessa |
| C15 | 🟡中 | 数据安全 | 工作区 `archive/2026/09/**` | 归档运行产物**未纳入 .gitignore**，大量未跟踪文件；AGENTS.md 明令 xlsx/sql/dump 禁止入仓，存在误提交风险 | `.gitignore` 追加 `archive/`、`_poc_check.txt`、`.mimosa/` | 主理人 |
| C16 | 🟡中 | 测试治理 | `tests/` 全局 | S1–S9"优先级高于功能用例"**无机械强制**（无 `-m` marker、无门禁脚本、无退出码区分），"任一失败=整体不通过"仅停留在文档策略 | 加 `@pytest.mark.security` + CI 独立 job | Tessa |
| C17 | 🟢低 | 启动噪声 | jieba 依赖 | `SyntaxWarning: invalid escape sequence` 3 条污染启动日志 | 锁定 jieba 版本或加 warning filter | 主理人 |
| C18 | 🟢低 | 上线阻塞 | `app/core/security.py:82-85` | 生产期全局 503（OA 未对接前拒绝一切访问）——**这是正确的 fail-closed 设计**，但意味着当前版本事实上不可上线 | 等 OA SSO 对接 | 主理人 |

---

## ✅ 正面结论（已实测验证合规，8 项）

| 检查项 | 证据 | 结论 |
|---|---|---|
| fail-closed 鉴权 | `app/core/security.py:53-73`（无 token 401 / token 不匹配 401 / dev_token 校验） | ✅ 历史 fail-open 缺陷未回归 |
| `/admin/*` 8 页鉴权 | `pages.py:386,394,420,428,436,448,466,477` 全部挂 `require_admin_access` / `require_admin_role` | ✅ 符合 ADR-F008（**注**：依赖名为页面专用，按 `get_current_user` 检索会误报为"无鉴权"，已更正） |
| 审计 append-only | `app/models/audit_log.py:70,76`（`before_update`/`before_delete` 事件抛异常） | ✅ 符合 ADR-F005 |
| 源文件只读 | `import_service.py:89,91`、`file_parser.py:93,309` 全部 `read_only=True, data_only=True`；全局仅 1 处 `.save(`（`query.py:186`，BytesIO 导出） | ✅ 无源 Excel 写回 |
| 硬删闸门（代码层） | `app/api/batch.py:187-190` `if snapshot_path is None: raise HTTPException(500)` | ✅ fail-closed 已实现（**但缺测试**，见 C1） |
| 导出闸门 | `app/api/query.py:29 EXPORT_GATE_LIMIT=1000`、`:101 confirm` 参数、`:100 require_role(ESTIMATOR, ADMIN)` | ✅ 大批量二次确认 + viewer 禁导出 |
| 纯函数层零污染 | `data/` 顶层 import 仅 `numpy/sklearn/jieba/rapidfuzz/hashlib/json/csv/gzip/zipfile` 等，**无 `from app*` / fastapi / sqlalchemy** | ✅ 符合 ADR-F002，依赖方向单向 |
| 测试隔离 | `tests/conftest.py:37-46` SQLite `:memory:` + StaticPool、`:60-70` function 级 rollback、`:73-85` dependency_overrides；`app/db.py:22` 已是 `settings.database_url` | ✅ 不碰 dev/prod 库，历史 P0（test_database_url 优先）已修复 |

**实测数字**：`pure_tests/ 236 passed` · `tests/ 309 passed`（合计 545，零 failed/error/skipped）。**无 SQL 拼接注入**（`text(` 零命中）。

---

## 🧪 端点鉴权分布（递归内省 77 个端点，实测）

| 分类 | 数量 | 说明 |
|---|---|---|
| AUTH + ROLE（登录 + 角色校验） | 30 | 写操作与敏感读 |
| AUTH（仅登录，无角色约束） | 18 | 均为只读查询类（query/price/quality/dict/import 列表等），符合预期 |
| 依赖树无鉴权 | 29 | 含 8 个 `/admin/*` 页面（**实为页面专用依赖名，已逐行核实为已鉴权**）、11 个 301 旧路由、3 个 Portal 页（设计即可选登录）、`/login`、`/logout`、`/health`、`/api/public/hello`、docs 三件套 |

> Portal 3 页未登录可访问是 ADR-F008 明确设计（`get_page_user_optional` 返回 None → `only_std=True` 仅渲染已标准化数据），非缺陷。

---

## ✅ 行动清单（按优先级排序）

| # | 行动 | 负责角色 | 紧急度 | 预期产出 |
|---|------|---------|--------|---------|
| 1 | 新建 `tests/test_hard_delete_gate.py`，monkeypatch 快照失败断言物理删除被拒 | 测试 | P0 | 失效门禁命令转为有效 |
| 2 | 引入 Alembic，替掉 `create_all` 作为生产建表方式 | 架构 | P0 | 可回滚、可审计的 schema 演进 |
| 3 | 加 `.github/workflows/pytest.yml`，pure/tests 分跑 | SRE | P0 | 545 条测试自动回归 |
| 4 | S8 二选一：补自动化演练 或 降级为 manual-gate 清单 | 测试 | P0 | 消除"登记即存在"的假门禁 |
| 5 | 统一鉴权体系：OA 对接时收敛为一套 `get_current_user`，角色服务端映射 | 架构 | P1 | 消除 C5/C6 双源 |
| 6 | 端点改 `require_permission(...)`，`_ROLE_PERMISSIONS` 真正成为单一事实源 | 架构 | P1 | 消除 39 处硬编码角色 |
| 7 | 处理 `data/learning_engine.py` v1 死代码（删除或标注归档） | 架构 | P1 | 减少测试维护在死代码上的浪费 |
| 8 | 修复 3 处 naive `datetime.now()` | 代码 | P1 | F011 收口 |
| 9 | 更新 `项目总控.md §9.1`（276→309）+ `.gitignore` 追加 `archive/` | 文档 | P1 | 基线不再漂移 |
| 10 | 补 `prematch_service` 单测 + S1/S4/S7 行为化改造 | 测试 | P2 | 覆盖缺口补齐、脆断消除 |

---

## ⚠️ 待完善 / 已知局限

- 本次为**只读审查，未修改任何文件、未执行任何 git 写操作**（遵照"不急着改文件"指令）。
- 性能维度（N+1、大批量导入事务边界）**未做压测级验证**，仅做了静态扫描（无 `text(` 拼接、`except` 面统计），结论不作为性能背书。
- 视觉基线（M2.5 起要求浅/深色 8 张截图）本次**未核对**，`docs/visual_baseline/` 未检查是否存在。
- 子代理调度工具异常导致安全/架构维度由主理人一人取证，缺少第二双眼睛交叉复核；建议下次在工具可用时补一轮独立复审。
- 归档运行产物 `archive/2026/09/**` 内容未逐一甄别是否含真实工程 Excel，C15 仅为风险提示。

---

## 📚 数据来源 & 成员产出索引

- **Tessa（测试专家）** 子代理产出：实测 pytest 数字（236 / 309）、S1–S9 映射表、硬删闸门缺口坐实、conftest 隔离评估、覆盖缺口映射、7 条改进建议。
- **主理人亲自取证**（安全 + 架构维度）：路由递归内省脚本（77 端点）、`security.py` / `permissions.py` / `pages.py` 源码通读、`data/` 依赖扫描、学习引擎调用链、datetime 残留扫描、源文件只读 grep、Alembic 缺失确认。
- 引用文档：`AGENTS.md`（测试命令与安全基线）、`项目总控.md` v1.3（ADR F001–F011、§9 硬规则）。

---

> 本报告由工程保障团队 AI 协作生成，关键决策请由人类工程负责人复核。
