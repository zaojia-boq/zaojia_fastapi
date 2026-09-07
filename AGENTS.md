# AGENTS.md

本文件用于约定与 AI 协作（如 WorkBuddy 及其他编码 Agent）共同维护本仓库时的硬性规则。任何对本仓库的改动都应遵循以下注意事项。

> **本仓库为 FastAPI 版造价数据门户**，从 Odoo 19 版（`zaojia_boq` 模块）迁移而来。业务契约、数据安全铁律、纯函数层 100% 继承；技术栈已切换为 FastAPI + SQLAlchemy + PostgreSQL + Jinja2。
> 原 Odoo 版已归档：git tag `legacy-odoo-final`，数据库备份 `E:\DEEPSEEK学习\zaojia_backup\zaojia_db_20260905.dump`。

## 注意事项

- **总控角色铁律（2026-09-04 用户指令，永久生效）**：总控（项目总控 Agent）**只做记录与把控**——维护 `项目总控.md`、状态回写、阶段划分、门禁定义、验收核对与调度派工；**不得亲自修改实现代码**。具体改动（Python/SQLAlchemy/模板/配置）一律由执行 Agent 按阶段（泳道）实施，每阶段独立交付（改动 + 门禁 + commit）。违反本条即视为流程违规，交付无效；
- 每次改动完成，都必须创建一个对应的 Git commit，以便后续追踪和回滚；
- 每次改动后，都必须编写或更新相关测试，并在交付用户前，调用 Self-Improving + Proactive Agent 技能（`@skill:"Self-Improving + Proactive Agent"`）进行审查，确保所有测试和验证全部通过。

### Git 操作铁律（2026-09-06 事故教训，永久生效）

> 背景：2026-09-06 本仓库曾因误操作（在并行 Agent 写入期间执行 `git reset --hard` + 重复 `git init` 覆盖 `.git`）丢失 3 个本地提交，靠工作区文件抢救恢复。以下铁律对本仓库所有 Agent 永久适用。

- **禁止对已有仓库重复 `git init`**：git 命令若报 "not a git repository"，先 `ls -la` 核查 `.git` 是否存在、当前目录是否正确——绝不盲目重新 init（会覆盖 `.git`，全部历史不可达）。
- **`git reset --hard` 前必须核验目标**：执行前必须 ① `git log`/`git diff` 核对目标 commit 与当前差异；② `git status` 确认工作区无未提交的重要改动；③ 用户明确授权。三者缺一不可。优先用 `--soft`/`--mixed`，`--hard` 是最后手段。
- **并行写入期间禁做破坏性 git 操作**：工作区正被并行 Agent 写入时（文件 mtime 持续变化、status 频繁变动），禁止 reset --hard / checkout -- / cherry-pick / merge / rebase 等改写工作区或历史的操作，只能只读观察。
- **发现大量未提交改动时先抢救**：第一动作是提交保护（或 `git stash`），而非任何"整理"操作。
- **破坏性 git 操作前先建备份分支**：`git branch backup-<date>` 成本极低，必做。

## 测试命令约定

为了让交付前审查拥有**可量化、可自动化的通过标准**（而不是靠人工逐字核对），本仓库的代码改动必须明确对应的测试执行命令。**未在本节登记测试命令的改动，审查一律判定为不通过。**

- **Python 改动**：默认测试命令为 `python -m pytest`（若存在 `tests/` 或 `test_*.py`）。需在提交前本地跑通，零失败、零报错。
  - 本仓库须使用系统 Python：`C:\Users\ht835\AppData\Local\Programs\Python\Python312\python.exe -m pytest`。
- **纯文档 / Markdown 改动**（如本文件、README、说明文档）：无可执行代码，以「内容核对」替代运行测试，但仍须走审查流程，并在审查结论中如实标注「无代码可测，已做内容核对」。
- **新增技术栈时**：须在本节追加对应命令，例如前端 `npm run build`、特定框架的自定义校验脚本等，确保后续每次改动都能找到唯一、明确的验证入口。

### FastAPI 应用（本仓库核心）— 2026-09-05 登记

> 环境前提：M0 + M1.1 完成（FastAPI 骨架 + 依赖安装 + SQLAlchemy 四模型 + pure_tests 127 条全绿 + tests/ 13 条全绿）。系统 Python 3.12。

- **纯函数测试**（`data/` 目录，gb_code/aliases/unit_normalize/match_score/price_calc/quality_metrics/cost_catalog_gate/field_spec，不依赖任何框架）：
  ```
  C:\Users\ht835\AppData\Local\Programs\Python\Python312\python.exe -m pytest pure_tests/ -v
  ```
  判据：**全绿零失败**（2026-09-07 基线：Odoo 迁移 90 + field_spec 21 + aliases 扩展 10 + match_score/quality_metrics 边界强化 6 + tfidf_matcher 13 + faiss_learning 17，与 `项目总控.md` §9.1 对齐，任何改动后必须保持全绿）。

- **FastAPI 集成测试**（M1 起，涉及模型/服务/API/权限的改动必跑）：
  ```
  C:\Users\ht835\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/ -v
  ```
  判据：**13 passed**（M1.1 基线），零失败。测试使用隔离数据库：当前 conftest 以 SQLite 内存库 + override `get_db`；M1 建 PG 引擎后经 `TEST_DATABASE_URL` 切换（不碰开发/生产库）。

- **应用启动验证**（改 `app/main.py`/路由/配置后必跑）：
  ```
  cd E:\DEEPSEEK学习\zaojia_fastapi
  C:\Users\ht835\AppData\Local\Programs\Python\Python312\python.exe -c "from app.main import app; print('routes:', len(app.routes))"
  ```
  判据：无 ImportError，路由数符合预期（当前 10 个：/openapi.json /docs /docs/oauth2-redirect /redoc /static / /health /api/me /api/public/hello /api/admin/audit-test）。

- **依赖完整性检查**（改 `requirements.txt` 后必跑）：
  ```
  C:\Users\ht835\AppData\Local\Programs\Python\Python312\python.exe -c "import fastapi, uvicorn, sqlalchemy, pydantic, rapidfuzz, sklearn, jieba, faiss; print('deps OK')"
  ```
  判据：无 ImportError。2026-09-07 新增依赖：scikit-learn（TF-IDF 语义匹配）、jieba（中文分词）、faiss-cpu（FAISS 向量检索）。

### 数据安全（继承自 Odoo 版，不可变）

> 原始造价 Excel 与人工标注（B 类字段）**不可重建**，任何涉及导入、删除、覆盖、导出的改动，除常规测试外**必须额外跑通本节命令**。

- **安全验收自动化用例**（S1–S9，M1 模型就绪后生效）：
  ```
  C:\Users\ht835\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/test_security.py -v
  ```
  判据：S 用例必须全部 PASS。用例定义见 `架构设计.md` §四 与 `项目总控.md` §9.2。
  **S1–S9 优先级高于功能用例**：任一失败视为整体不通过，不得交付。

- **源文件只读校验**（改动导入相关代码后必跑）：
  ```
  grep -rn "\.save(" app/ ; grep -rn "load_workbook" app/
  ```
  判据：**不得出现对源文件的 `wb.save(`**（允许的例外：①导出向内存 BytesIO 生成全新导出文件；②测试代码自建临时夹具文件——两者均不触碰导入源文件，命中处须有注释说明）。所有 `load_workbook` 必须带 `read_only=True, data_only=True`。

- **敏感文件入仓校验**（每次提交前必跑）：
  ```
  git status --porcelain | grep -Ei "\.(xlsx|xls|sql|dump)$"
  ```
  判据：**无输出**。真实工程 Excel 与数据库备份禁止进仓库。

- **备份恢复演练**（S8，每季度一次，**无自动化**）：在临时库完整恢复 `pg_dump`，抽样 10 条与原始 Excel 逐字比对，结果记入 `docs/backup_drill.md`。**未演练过的备份视为无效**，审查时须如实标注「S8 本季度已/未演练」。

- **硬删闸门校验**（改动删除/回收站逻辑后必跑，Odoo 版 R1 缺陷教训）：
  ```
  C:\Users\ht835\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/test_hard_delete_gate.py -v
  ```
  判据：硬删前 CSV 快照失败时，物理删除必须被拒绝（不得放行）。

> **状态注（2026-09-05，M1.1 时点）**：`tests/test_security.py`（S1–S9）与 `tests/test_hard_delete_gate.py` **尚未创建**，属 M1.x 审计/权限泳道交付内容；当前执行上两条命令会报「file or directory not found」。创建前这两道闸门**不可执行**，任何交付不得将「未跑」标注为「通过」。创建后须回写本文件判据基线。

> 原则：测试命令必须**唯一且可复现**——任何人（或 Agent）在同一环境下执行该命令，都应得到一致的结果。
> **安全用例的优先级高于功能用例**：S1–S9 任一失败，视为整体不通过，不得交付。

### 视觉基线核对（M2.5 起，改 UI 后必做）

浅色 + 深色各一套共 8 张截图，存 `docs/visual_baseline/`；对照 `产品设计文档.md` §九 的核对清单逐项确认（主色 `#4D7CFE`、正文 14px、列表行高 ≥40px、一屏 ≥15 行、无裸值颜色、深色模式无白底残留）。此项目前**无自动化断言，以人工核对截图 + 清单勾选**为准，审查时须如实标注「视觉项已人工核对」。

> 前端 demo 基线：`app/static/demo/index.html`（深空科技方案 C，从 Odoo 版原样复用）。真实页面观感以该 demo 为像素级视觉规格。
