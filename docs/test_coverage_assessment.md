# 测试覆盖与测试策略评估报告（工作流 1 · 测试维度）

> 评估人：测试专家 Tessa（testing-expert）
> 仓库：`E:\DEEPSEEK学习\zaojia_fastapi`（FastAPI 版造价数据门户）
> 方法：所有结论均基于本次实跑命令与实读文件，非推断。

## 一句话总体结论
🔴 **严重缺口**：纯函数回归基线（90/90）真实全绿，应用启动、依赖、源文件只读、敏感文件门禁均通过；但 AGENTS.md 登记的 3 道**硬交付门禁**（集成测试 / S1–S9 安全验收 / 硬删闸门）因 `tests/` 目录完全不存在而**无法执行**——当前**不具备可量化、可自动化的 M1 交付通过标准**。

---

## 一、测试现状核验表（均基于本次实跑）

| # | 命令 / 判据（来自 AGENTS.md） | 预期判据 | 实际结果（实跑输出摘要） | 结论 |
|---|---|---|---|---|
| 1 | `python -m pytest pure_tests/ -v` | 90 passed，零失败 | `90 passed in 0.37s`；7 文件 / 90 个 unittest 用例全绿 | ✅ 真实全绿 |
| 2 | `ls tests/` / `find -type d tests` | 目录存在，含集成/安全/闸门用例 | `ls: cannot access 'tests'`；`find` 无结果 | ❌ **目录缺失** |
| 3 | 应用启动 `from app.main import app; len(app.routes)` | 无 ImportError，路由数=10 | `IMPORT_OK` / `ROUTE_COUNT= 10`（含 /openapi.json /docs /redoc /static / /health /api/me /api/public/hello /api/admin/audit-test） | ✅ 通过 |
| 4 | 依赖完整性 `import fastapi, uvicorn, sqlalchemy, pydantic` | 无 ImportError | `deps OK` | ✅ 通过 |
| 5 | 源文件只读 `grep -rn "\.save(" app/` | 无命中 | `NO .save( FOUND` | ✅ 通过（注：app/ 现为空桩，M1 落地后须复测） |
| 6 | 只读打开 `grep -rn "load_workbook" app/` | 必须带 read_only/data_only | `NO load_workbook FOUND` | ✅ 通过（同上，M1 后复测） |
| 7 | 敏感文件 `git status … grep -Ei "\.(xlsx|xls|sql|dump)$"` | 无输出 | `NO SENSITIVE FILES STAGED` | ✅ 通过 |

### 缺失门禁的实跑证据（证明"无法执行"而非"尚未编写"）
```
pytest tests/ -v                      → ERROR: file or directory not found: tests/
pytest tests/test_security.py -v      → ERROR: file or directory not found: tests/test_security.py
pytest tests/test_hard_delete_gate.py → ERROR: file or directory not found: tests/test_hard_delete_gate.py
```
三条命令均 `collected 0 items`，pytest 直接报找不到路径——**门禁本身处于"不可验证"状态**。

---

## 二、缺失测试与门禁影响表

| 缺失项（AGENTS.md 登记但不存在） | 对应门禁原文 | 阻塞交付？ | 影响说明 |
|---|---|---|---|
| `tests/` 集成测试套件 | "FastAPI 集成测试（M1 起）…判据：全部 passed，零失败" | ✅ **阻塞** | M1 涉及模型/服务/API/权限的改动**无可执行验证入口**；AGENTS.md 明文"未登记测试命令的改动，审查一律判定为不通过" |
| `tests/test_security.py`（S1–S9） | "S1–S9 优先级高于功能用例；任一失败视为整体不通过，不得交付" | ✅ **阻塞（最高优先级）** | 安全验收**完全不可执行**。S1 导入不改源、S3 重导不丢标注、S4 软删可回收、S5 审计可追溯等铁律**无法被任何自动化把关** |
| `tests/test_hard_delete_gate.py`（硬删闸门） | "硬删前 CSV 快照失败时，物理删除必须被拒绝" | ✅ **阻塞** | Odoo 版 R1 缺陷教训；当前无法验证，M1 删除/回收站逻辑落地而无此闸门将重现"硬删不可恢复"事故 |
| S8 备份恢复演练 | "每季度一次，无自动化；未演练视为无效" | ⚠️ 条件阻塞 | 设计上无自动化（需真实数据），但审查须人工标注"本季度已/未演练"，否则须如实记录未演练 |
| `test_archive.py`（S2/S6，架构设计 §目录树） | 架构登记但 AGENTS 未单列命令 | ⚠️ 建议补齐 | 归档+校验和（S2/S6）无独立门禁命令，建议纳入 tests/ |

**结论**：3 道硬门禁（集成测试、S1–S9、硬删闸门）全部"不存在 → 不可执行 → 无法通过"。AGENTS.md 明确"安全用例任一失败=整体不通过"，而现实是**安全用例连运行都跑不起来**，故 M1 现阶段**没有任何可量化的交付通过标准**。

---

## 三、纯函数层覆盖评估（90 条基线 + 缺口）

### 3.1 整体：基线真实、扎实，但存在 1 个真缺口 + 2 处边界欠覆盖

| 模块 | 用例数 | 边界覆盖评价 | 备注 |
|---|---|---|---|
| price_calc | 18 | ✅ 充分 | 含 `deviation_pct` 除零安全、区间判定、样本下限(2<3 拦截)、`exact_threshold` 严格 `>` |
| cost_catalog_gate | 12 | ✅ 优秀 | 显式测 `>=`(0.80 通过) / `<`(0.10 拒绝) 语义、None→0、**防漂移守卫**（与 quality_metrics 常量比对） |
| quality_metrics | 11 | 🟡 边界欠覆盖 | m3/m4 通过门槛（coverage 0.70/0.80、anomaly 0.15/0.10）只测"区间值"，**门槛边界值未直接断言** |
| match_score | 12 | 🟡 边界欠覆盖 | `high_confidence` 规则 `Top-1>=98` 与 `gap>10` 只测 85/100/99 与 gap 4/40，**恰好 98 与恰好 gap=10 未测** |
| gb_code | 20 | ✅ | — |
| aliases | 8 | ✅ | — |
| unit_normalize | 9 | ✅ | — |
| **field_spec** | **0** | ❌ **无测试** | **第 8 个 data 模块，无 `test_field_spec.py`** |

### 3.2 关键缺口 1：`field_spec.py` 完全无测试（高风险）
- `data/` 共 8 个模块，`pure_tests/` 仅 7 个文件——**`field_spec.py` 是唯一未被任何用例覆盖的模块**。
- 它定义数据安全根基：`A_FIELDS`/`B_FIELDS`/`C_FIELDS` 分层常量、`is_b_field`/`classify_field`/`split_fields_by_layer`，是"B 类禁静默覆盖"的单一事实源。
- 项目总控 M0.10 却标记"`field_spec.py` import 成功、A/B/C 交集断言通过、分层函数正确；pure_tests 90 passed"为 ✅（2026-09-05）。**但 90 条用例并不加载 field_spec，所谓"分层函数正确"并无自动化证据**——属"登记完成但实际缺测试"的虚假通过。
- 风险：M1 Upsert 的"A 可覆盖 / B 禁静默覆盖"逻辑若引用错常量或无函数守卫，回归测试发现不了。

### 3.3 关键缺口 2 / 3：match_score 与 quality_metrics 边界
- `high_confidence` 是"自动确认物料匹配、免人工复核"的业务开关，边界（=98、gap=10）未断言，存在"本应免复核却放行 / 本应放行却卡住"的漂移风险。
- quality_metrics 的 m3/m4 阈值边界未断言；虽 cost_catalog_gate 已守 0.80/0.10，但仪表盘口径（m3_pass/m4_pass）自身边界缺测。

---

## 四、路由业务逻辑可测性

当前 10 路由：
- **框架/标准路由（6）**：/openapi.json /docs /docs/oauth2-redirect /redoc /static /health — 无业务断言价值。
- **占位/无业务逻辑路由（4）**：`/`、`/api/me`、`/api/public/hello`、`/api/admin/audit-test`。后三者被任务书标注为占位接口，**当前无可测业务逻辑**，须 M1 模型+服务落地后才接集成测试。
- 现状：`app/models/`、`app/services/`、`app/api/` 均为空桩（各 `__init__.py` 仅 2 行），故集成测试无从写起——这是 `tests/` 缺失的根本原因（先有业务才有测试）。

---

## 五、M1 测试落地建议

### 5.1 推荐的 `tests/` 结构（对齐架构设计 §目录树 + 补齐闸门/权限）
```
tests/
  conftest.py              # 测试库 fixture：TEST_DATABASE_URL 切换 + create_all + 清空
  test_security.py         # S1/S2/S3/S4/S5/S7 安全验收（最高优先级，必须 ALL PASS）
  test_archive.py          # S2/S6 归档与校验和
  test_hard_delete_gate.py # 硬删闸门（CSV 快照失败→物理删拒绝）
  test_permissions.py      # 三角色权限（admin/reviewer/viewer）
  test_api.py              # /api/me、/api/admin/audit-test 等占位接口落地后的集成测试
  test_import.py           # 真实国内 Excel 样例（合并单元格/空单价/汇总行）
  test_models.py           # 四模型 + biz_id + 编码解析 + 审计落库
  fixtures/                # 脱敏夹具（工程名替换、单价扰动，禁止真实数据）
```
> 纯函数层（aliases/gb_code/unit_normalize/match_score/price_calc/quality_metrics/cost_catalog_gate）**继续留在 `pure_tests/`**（零框架依赖），`field_spec` 也应在 `pure_tests/` 补 `test_field_spec.py`。

### 5.2 S1–S9 最小可行用例清单（结合数据安全铁律）
| 用例 | 最小断言 | 依赖 |
|---|---|---|
| **S1** 导入不改源文件 | 导入前后源文件 `SHA256` 一致（只读打开 + 不 `.save(` 源） | import_service |
| **S2** 源文件已归档 | 归档目录存在该文件，且 `SHA256 == file_hash` | archive_service |
| **S3** 重导不丢人工标注 | 标准化 10 行→重导同文件→10 行 B 类标注仍在 | upsert_service（分层 Upsert） |
| **S4** 删除可回收 | 软删批次→回收站可见→还原后数据完整 | 回收站 + 还原 |
| **S5** 修改可追溯 | 改一条单价→`audit_log` 出现 `old → new` 四元组 | core/audit 落库 |
| **S6** 批次校验和 | `sum(total_num)` 与 Excel 合计行一致（容差 0.01） | import/archive |
| **S7** 待审不污染 | 导入 `pending_review` 批次后，历史均价不变（PRICE_STAT_TYPES 不含 pending） | price_service |
| **S8** 备份可恢复 | 季度人工演练 + 抽样 10 条逐字比对 → 记入 `docs/backup_drill.md`（无自动化） | 运维 |
| **S9** 不外泄 | 仓库内无真实 `.xlsx/.sql/.dump`；绑定本地/无公网暴露；导出记审计 | 配置 + .gitignore |

> 铁律映射：S1/S2→源文件只读；S4+硬删闸门→硬删被拒；S3/S5→审计不可绕过；S9→敏感文件不入仓。

### 5.3 测试库隔离方案（TEST_DATABASE_URL）
- `app/config.py` 已有配置入口；`conftest.py` 读取环境变量 `TEST_DATABASE_URL`，**缺省即失败**而非误连开发/生产库。
- 每个测试 session：`create_all` 建表 → 用例用脱敏 fixture 插入 → 收尾 `drop_all`/truncate，保证幂等（数据管道测试须测幂等性）。
- CI/本地统一：AGENTS.md 登记的 pytest 命令不变，仅要求执行前 `set TEST_DATABASE_URL=...`。
- 严禁 fixture 引用真实工程 Excel；敏感文件校验（`git status` grep）作为提交前硬卡。

### 5.4 立即可补的两项（不依赖 M1 业务）
1. **新增 `pure_tests/test_field_spec.py`**（8–10 用例）：`is_b_field`/`is_a_field`/`is_c_field`/`classify_field`/`split_fields_by_layer` 正例+反例；`A/B/C` 三集合互不相交断言；`B_DEFAULTS` 仅填空不覆盖；`PRICE_STAT_TYPES` 仅含 `completed`。补齐后 M0.10 的"分层函数正确"才真正成立。
2. **补 match_score / quality_metrics 边界用例**：`high_confidence` 测 `score==98` 与 `gap==10` 两档；quality_metrics 测 coverage=0.70/0.80、anomaly=0.15 门槛边界。

---

## 六、最终结论：当前是否具备「可量化、可自动化的交付通过标准」？
**不具备。**
- ✅ 已具备：纯函数回归（90/90 真实绿）、应用启动、依赖、源文件只读、敏感文件 5 道门禁可量化可自动化。
- ❌ 缺失且**不可执行**：集成测试、`test_security.py`（S1–S9）、`test_hard_delete_gate.py` 三道 AGENTS.md 硬门禁因 `tests/` 不存在而跑不起来；其中 S1–S9 被明文规定"任一失败=不交付"。
- ⚠️ 虚假通过：`field_spec.py` 被登记为"已测通过"但实际无独立测试。
- 因此，M1 现阶段**没有任何可被自动化评判的"交付通过"结论**——必须先落地 `tests/` 骨架（至少 test_security.py + test_hard_delete_gate.py + conftest 隔离）与 `pure_tests/test_field_spec.py`，才能谈得上"可量化、可自动化的交付通过标准"。
