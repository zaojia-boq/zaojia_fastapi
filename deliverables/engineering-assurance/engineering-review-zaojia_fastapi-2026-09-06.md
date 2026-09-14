# 全面工程审查报告 · zaojia_fastapi（FastAPI 版造价数据门户）

**日期**：2026-09-06
**工作流**：工作流 1 — 全面代码审查（安全 / 架构 / 测试覆盖三维评估）
**参与成员**：科迪（Cody · 代码审查师）、阿奇（Archi · 系统架构师）、泰莎（Tessa · 测试专家）
**主理人**：甄宇航（Zhen · Engineering Director）

---

## 📌 TL;DR（执行摘要）

- **整体结论**：M0–M4 全部完成，代码质量基线扎实（纯函数 127 passed、集成 297 passed、安全验收 16 passed）。**路径穿越漏洞（P0-1）已修复并入库，但 git 历史仅剩 2 个 commit**（原 7 个被并行 Agent disaster-recovery 覆盖），需紧急补救。
- **严重度分布**：🔴 严重 1 项 / 🟠 高 5 项 / 🟡 中 8 项 / 🟢 低 6 项
- **阻塞项**：1 项 🔴（git 历史丢失导致无法回滚修复）；2 项 🟠（生产环境 fail-closed 未就位、敏感接口无鉴权）可暂缓但须在 OA SSO 对接前解决。
- **正向亮点**：路径穿越闸门（三重校验）、B 类字段保护（单一事实源 + 强制 reason）、硬删四道闸门（fail-closed）、审计中间件（operator 修复后生效）、S1–S9 安全用例 16 条全绿。

---

## 🎯 核心结论卡片

| 项目 | 内容 |
|------|------|
| 整体评级 | 🟡 有条件通过（代码质量扎实，git 历史需补救） |
| 阻塞项数量 | 1（🔴 git 历史丢失） |
| 关键行动项 | 8 条（见行动清单） |
| 建议下一步 | ① 重建 git 历史（P0）；② 补 CORS + 生产鉴权（P1）；③ 补 page_services 测试（P2） |

---

## 🔍 审查发现（按严重度排序，已去重合并）

### 🔴 严重（阻断交付）

| # | 类别 | 文件:行 | 问题描述 | 证据 | 修复建议 | 来源 |
|---|------|---------|----------|------|----------|------|
| 1 | git 纪律 | 全库 | **git 历史仅剩 2 个 commit**（原 7 个修复被并行 Agent disaster-recovery 覆盖），M2.6/M3/M4 三批改动**无独立 commit 可追溯** | `git log --oneline` 仅显示 `fc2243a` 和 `1a61b7b`；`test_reject_path_outside_tempdir` 沙箱防护误触发 | 立即分三批补 commit：M2.6 数据绑定、M3 单价/质量/匹配/批处理、M4 成本迁移。每批独立 commit + 变更说明 | 主理人（人工核实） |

### 🟠 高（优先修复）

| # | 类别 | 文件:行 | 问题描述 | 证据 | 修复建议 | 来源 |
|---|------|---------|----------|------|----------|------|
| 2 | 安全 | `app/main.py:24` | **CORS 未配置** — `/docs`、`/openapi.json` 对任何跨域请求开放 | `grep -rn CORS app/` 无输出；`app/main.py` 仅注册 `AuditMiddleware` | M2.5 阶段补 `CORSMiddleware`，限制 `allow_origins` 为公司内网域名 | Cody |
| 3 | 安全 | `app/core/security.py:72` | **生产环境 fail-closed 策略** — `env=production` 时返回 503，但未阻止非 production 环境误开 | `security.py:72-75` 确认此逻辑 | 增加环境变量校验：生产容器必须设置 `ENV=production`，否则启动失败 | Cody |
| 4 | 测试 | `tests/test_hard_delete_gate.py` | **硬删闸门测试缺失** — Odoo 版 R1 缺陷教训未固化 | `ls tests/test_hard_delete_gate.py` 返回 Not Found；AGENTS.md 明文登记该用例 | 参照 `tests/test_batch_operation.py::TestBatchLifecycle` 风格补写 | Tessa |
| 5 | 测试 | `app/services/page_services.py` | **page_services 测试覆盖不足** — 29 个函数仅 32 条测试用例，部分分支未覆盖 | `grep -c def` 显示 29 函数；`test_pages.py` 仅 32 用例 | 按功能拆分：导航 badge、搜索过滤、批次操作各建独立测试类 | Tessa |
| 6 | 性能 | `app/services/cost_migration_service.py:38` | **N+1 查询风险** — `_aggregate_for_match_key` 在循环中调用，每个 match_key 独立查询 | `grep _aggregate_for_match_key` 显示调用点 2 处，均在 for 循环内 | 批量聚合：一次性 `WHERE match_key IN (...)` + GROUP BY | Cody |
| 7 | 安全/可用性 | `app/api/import_api.py` | **上传无大小限制** — 客户端可发送任意大文件，耗尽内存 | `grep max_content_length` 无输出 | 加 `max_content_length=50*1024*1024`（50MB）匹配架构 §4.3 | Cody |

### 🟡 中（迭代修复）

| # | 类别 | 文件:行 | 问题描述 | 证据 | 修复建议 | 来源 |
|---|------|---------|----------|------|----------|------|
| 8 | 正确性 | `app/core/audit.py:46` | **旧版 `audit_log()` 别名失效** — 仅 `logger.warning` 不写库 | `grep -rn "audit_log(" app/` 仅 `main.py:62` 一处调用，无落库 | 替换为 `log_audit(db=..., model=..., res_id=...)`，删除旧版别名 | Cody |
| 9 | 安全 | `app/api/pages.py:147` | **dev_token 暴露于登录模板** — `/login?token=` 明文传入 | `grep dev_token app/api/pages.py` 显示 15 行引用 | 改用 POST body 传 token，避免 URL 历史记录泄漏 | Cody |
| 10 | 架构 | `app/services/material_match_service.py:42` | **符号链接绕过风险** — `_validate_tmp_path` 未检查 `is_symlink` | `os.path.abspath` 不解析符号链接 | 加 `os.path.realpath` 替代 `abspath`，或显式 `is_symlink` 检查 | Cody |
| 11 | 架构 | `app/services/cost_migration_service.py:45` | **双重查询** — `_aggregate_for_match_key` 先查 `match_key` 列表，再逐个聚合 | `grep _aggregate_for_match_key` 显示 2 处循环调用 | 合并为单次聚合查询：`GROUP BY match_key` | Cody |
| 12 | 安全 | `app/config.py` | **secret_key 默认值不安全** — `change-me-in-production` | `config.py:11` 确认默认值 | 改为必填 env，缺失即启动失败 | Cody（继承自 2026-09-05 审查） |
| 13 | 可维护性 | `app/services/batch_operation_service.py` | **批量操作边界未测试** — 空列表、超大 ID 集合未覆盖 | `test_batch_operation.py` 14 用例，无边界用例 | 补 `test_empty_ids`、`test_large_batch`、`test_mixed_status` | Tessa |
| 14 | 架构 | `app/services/import_service.py` | **并发导入竞态未防护** — 无文件锁或事务隔离 | `grep lock` 无输出 | 加 `threading.Lock` 或数据库级行锁 | Cody |

### 🟢 低（后续优化）

| # | 类别 | 文件:行 | 问题描述 | 修复建议 | 来源 |
|---|------|---------|----------|----------|------|
| 15 | 可维护性 | `app/core/audit.py:76` | `utcnow()` 弃用告警 3307 条 — 应改用 `datetime.now(datetime.UTC)` | 全局替换 `utcnow()` → `datetime.now(datetime.UTC)` | Cody |
| 16 | 测试 | `tests/test_security.py` | S8 备份恢复演练无自动化 — 季度人工项须标注已/未演练 | `docs/backup_drill.md` 补充本季度状态 | Tessa |
| 17 | 安全 | `app/templates/base.html` | Cookie `httponly=False` — XSS 可窃令牌 | 改为 `httponly=True, secure=True` | Cody |
| 18 | 架构 | `app/static/demo/check.py` | Demo 自检脚本含内部 node 绝对路径，公开暴露 | 移出 `static/` 或仅暴露必要资源 | Cody |
| 19 | 可维护性 | `data/__init__.py` | 文档仅列 3 模块，实际 8 模块 | 更新文档反映当前集合 | Cody（继承自 2026-09-05） |
| 20 | 架构 | `app/main.py` | `/health` 仅返回静态 JSON，不校验 DB | 加 DB ping 实现 readiness 探针 | Cody（继承自 2026-09-05） |

---

## ✅ 审查通过的项

| 类别 | 项 | 状态 | 来源 |
|------|-----|------|------|
| 安全 | 路径穿越闸门（三重校验） | ✅ 有效 | 主理人（人工核实） |
| 安全 | B 类字段保护（单一事实源 + 强制 reason） | ✅ 落地 | Cody |
| 安全 | 硬删四道闸门（fail-closed） | ✅ 实现正确 | 主理人（2026-09-06） |
| 测试 | S1–S9 安全验收 16 passed | ✅ 全绿 | Tessa |
| 测试 | 纯函数回归 127 passed | ✅ 基线稳固 | Tessa |
| 测试 | 集成测试 297 passed | ✅ 全绿 | Tessa |
| 架构 | data/ 纯函数层零框架依赖 | ✅ 健康设计 | Archi |
| 架构 | field_spec.py A/B/C 分层守卫 | ✅ 单一事实源 | Archi |
| 审计 | operator 修复后生效 | ✅ 写入 `request.state.username` | 主理人（人工核实） |

---

## 🏗️ 架构影响评估（Archi 核心观点）

**评级：🟡 需关注**——无「🔴 阻断级」结构缺陷；M0–M4 骨架与「纯函数层 / 框架层」解耦决策是健康基础。

**关键 ADR（建议回写总控 §7）**：
- **ADR-003 · 生产环境 fail-closed 强制**：`ENV=production` 未设置时启动失败，防止开发配置漏出
- **ADR-004 · 测试库隔离显式化**：`TEST_DATABASE_URL` 缺省即失败，禁止误连开发/生产库
- **ADR-005 · 批量查询优化**：`_aggregate_for_match_key` 改为 `GROUP BY` 单次聚合，消除 N+1

**架构级技术债（按影响排序）**：
1. git 历史丢失（P0，阻断回滚）
2. 生产鉴权未就位（P1，OA SSO 对接前暂缓）
3. N+1 查询性能风险（P1，影响大规模匹配）
4. 并发导入无锁（P2，多用户场景可能竞态）
5. 旧版审计别名失效（P2，维护负担）

---

## 🧪 测试覆盖评估（Tessa 核心观点）

**评级：🟡 有条件通过**——纯函数 + 集成测试全绿，但存在 2 个 P0 级缺口：

| 缺失项 | 对应门禁原文 | 阻塞交付？ | 影响说明 |
|--------|-------------|-----------|----------|
| `test_hard_delete_gate.py` | "硬删前 CSV 快照失败时，物理删除必须被拒绝" | ⚠️ 条件阻塞 | Odoo 版 R1 缺陷教训未固化，删除逻辑无自动化保障 |
| `page_services.py` 覆盖率 | AGENTS.md 「每次改动必须编写或更新相关测试」 | ⚠️ 建议补齐 | 29 函数 32 用例，部分分支未覆盖 |

**立即可补（不依赖新业务）**：
1. 补 `test_hard_delete_gate.py`（参照 `test_batch_operation.py::TestBatchLifecycle`）
2. 补 `page_services.py` 核心分支测试（导航 badge、搜索过滤、批次操作）
3. 全局替换 `utcnow()` → `datetime.now(datetime.UTC)`（消除 3307 条告警）

---

## ✅ 行动清单（按优先级排序）

| # | 行动 | 负责角色 | 紧急度 | 预期完成 |
|---|------|----------|--------|---------|
| 1 | **重建 git 历史**：分三批补 commit（M2.6 数据绑定 / M3 单价质量匹配批处理 / M4 成本迁移） | 执行 Agent | 🔴 P0 | 本次会话 |
| 2 | **补硬删闸门测试**：`tests/test_hard_delete_gate.py`（CSV 快照失败 → 物理删拒绝） | 执行 Agent | 🟠 P1 | M5 前 |
| 3 | **补 CORS 中间件**：限制 `allow_origins` 为公司内网域名 | 执行 Agent | 🟠 P1 | M2.5 收尾 |
| 4 | **优化 N+1 查询**：`_aggregate_for_match_key` 改为 `GROUP BY` 单次聚合 | 执行 Agent | 🟠 P1 | M5 |
| 5 | **上传大小限制**：`max_content_length=50MB` | 执行 Agent | 🟠 P1 | 立即 |
| 6 | **替换旧版审计别名**：`audit_log()` → `log_audit()` | 执行 Agent | 🟡 P2 | M5 |
| 7 | **page_services 测试补全**：核心分支覆盖率 ≥80% | 执行 Agent | 🟡 P2 | M5 |
| 8 | **Cookie httponly 加固**：`httponly=True, secure=True` | 执行 Agent | 🟢 P3 | M6 |

---

## ⚠️ 待完善 / 已知局限

- **git 历史断层**：当前仅 2 个 commit，M2.6/M3/M4 三批改动无独立历史，无法 `git revert` 单批修复。**必须在本次会话补交 commit**。
- **生产环境 fail-closed 暂缓**：OA SSO 对接完成前，`env=production` 返回 503 是设计决策，非 bug。但若误部署到公网，将阻断所有访问。
- **S8 备份恢复演练**：本季度未演练，备份有效性待人工核验（须真实数据 + 临时库，写 `docs/backup_drill.md`）。
- **软删除级联遗漏**：`BoqItem` 软删除时未级联清 `match_confirm` 标记，可能产生孤儿记录（P2 发现 #13）。
- 本次审查基于当前代码快照（2026-09-06 10:16）；M5 改动后须重跑 AGENTS.md 全部测试命令并触发 Self-Improving + Proactive Agent 审查。

---

## 📚 数据来源 & 成员产出索引

- **科迪（代码审查师）原始产出**：安全/性能/正确性/可维护性审查发现表（P0–P3 共 19 项）+ AGENTS.md 安全闸门符合性核对表（实测 127+297+16 passed）。
- **阿奇（系统架构师）原始产出**：架构评估表（12 维）+ ADR-003/004/005 + 架构级技术债清单（5 项），评级 🟡 需关注。（报告已提交，待汇整）
- **泰莎（测试专家）原始产出**：测试现状核验表（7 项实跑）+ 缺失门禁影响表 + S1–S9 最小用例清单 + M1 `tests/` 结构建议；完整版已落盘 `docs/test_coverage_assessment.md`，评级 🟡 有条件通过。
- **主理人（甄宇航）人工核实**：P0-1 路径穿越修复有效（实证穿越路径返回 400，文件不被删除）；git 历史丢失（2 commit vs 原 7 commit）；审计 operator 修复有效。

---

> 本报告由工程保障团队 AI 协作生成，关键决策请由人类工程负责人（总控 Agent）复核并回写 `项目总控.md` §7 / §9.2。
