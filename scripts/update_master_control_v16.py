# -*- coding: utf-8 -*-
"""更新项目总控.md：在 §10.9 后插入 §11 章节 + 更新版本号 + 版本历史"""
import io

path = r'E:\DEEPSEEK学习\zaojia_fastapi\项目总控.md'
content = open(path, encoding='utf-8').read()

# 1. 插入 §11 章节（锚点：防抖教训 + --- 之后是版本历史）
anchor = "6. **搜索必须防抖**：输入框搜索至少 200ms 防抖，避免频繁重渲染\n\n---\n\n### 版本历史"
new_section = """6. **搜索必须防抖**：输入框搜索至少 200ms 防抖，避免频繁重渲染

---

## 11. 单价分析聚合身份优化 + 测试稳定性（2026-09-14）

### 11.1 单价分析聚合身份友好显示（强制沿用）

**问题**：单价分析"各工程对比"聚合组显示原始 `aggregate_id`（如 `code:unknown:030408001|m`、`dict:646`），不可读；201 条 `match_key_source='dict'` 但 `material_dict_id=None`（Odoo 版旧 ID 在 FastAPI 新字典表不存在）。

**修复（commit a5ad38d）**：
1. **数据修复**：8 条名称精确匹配新材料字典（镀锌钢管/钢管/电力电缆/配电箱等）；193 条未匹配（施工工序类）重新计算为 code 模式。修复后分布：dict=8、std=150、code=1231。
2. **聚合身份四层递进显示**（`page_services.py` 的 `_friendly_agg_name`）：
   - **dict 模式**：材料字典名称 + 分类路径，如 `镀锌钢管（方钢/镀锌钢管）`
   - **code 模式（有映射）**：查 `list_material_mapping` 表显示材料名称 + 国标码 + 清单项目名称，如 `混凝土（010501001 垫层）`
   - **code 模式（无映射）**：9 位国标码 + 清单项目名称，如 `040101001 挖沟槽土方`
   - **std/raw 模式**：标准化名称+规格 / 原始项目名称
3. **映射表利用**：`list_material_mapping`（3,446 条：2013=1,759 + 2024=1,687）批量查询，取相似度最高映射；boq_item 197 个唯一国标码中 166 个（84.3%）可匹配。

**教训**：聚合身份显示必须利用清单-材料映射表（list_item_code → material_name），未匹配的施工工序类（土方/平整场地/栽植等）按国标码+项目名称展示，不新建材料字典项（工序非材料）。

### 11.2 测试稳定性检测（2026-09-14）

**结论：551 passed × 3 次，零失败零波动（无 flaky）**。

| 套件 | 单次 | 3 次复跑 | 判定 |
|---|---|---|---|
| `pure_tests/` | 236 passed（1.85s） | 全绿 | ✅ 稳定 |
| `tests/` | 315 passed（3.64s） | 全绿 | ✅ 稳定 |
| 合计 | 551 passed | 551 × 3 | ✅ 无 flaky |

**测试隔离质量（已验证）**：conftest.py 使用 SQLite 内存库 + StaticPool（TestClient 后台线程共享连接）+ 每测试 rollback 清空表 + override get_db + app.state.db_session_factory 供 AuditMiddleware——不触碰生产 PG 库。

**数据安全铁律校验（已验证）**：
- 源文件只读：`wb.save()` 仅 `query.py:187`（导出向导向内存 BytesIO，允许例外）；`load_workbook` 全部 `read_only=True, data_only=True` ✅
- 敏感文件入仓：`git status --porcelain` 无 xlsx/xls/sql/dump 输出 ✅

**本次修复 .gitignore 行内注释 bug（commit d18d627）**：gitignore **不支持行内注释**，原 `archive/  # 导入文件归档` 被当作完整模式导致规则全部失效（archive/、.mimosa/、*.meta.json 长期未忽略）。修复：注释移至独立行。同时入仓领域资产：清单规范提取数据（GB50500-2013/2024 双版本 json.gz）+ 6 个工具脚本（check_2024_sheets/check_list_files/check_sheets_detail/force_create_table/import_material_dict_to_db/match_list_material_both_versions）。

**教训**：.gitignore 禁止行内注释；提交后必须用 `git status --porcelain` 验证忽略规则实际生效（不生效即规则书写错误）。

---

### 版本历史"""

assert anchor in content, "锚点未找到！"
content = content.replace(anchor, new_section, 1)

# 2. 更新顶部版本号
old_ver = "> 版本：v1.5（2026-09-14：M6 字典页面性能优化 + 五级结构 + 懒加载 + 分页 + 缓存 + 搜索，页面加载从 60s+ 降至 294ms）"
new_ver = "> 版本：v1.6（2026-09-14：单价分析聚合身份按清单-材料映射显示 + 测试稳定性 551×3 全绿 + .gitignore 行内注释修复）"
assert old_ver in content, "版本号锚点未找到！"
content = content.replace(old_ver, new_ver, 1)

# 3. 版本历史新增 v1.6 行（插到 v1.5 行之前）
v15_line = "| v1.5 | 2026-09-14 | **M6 字典页面性能优化 + 五级结构 + 懒加载 + 分页 + 缓存 + 搜索**。"
assert v15_line in content, "v1.5 行未找到！"
v16_line = "| v1.6 | 2026-09-14 | **单价分析聚合身份优化 + 测试稳定性检测 + .gitignore 修复**。①单价分析'各工程对比'聚合身份从原始 aggregate_id 改为友好显示：利用 list_material_mapping 映射表（3,446 条，84.3% 国标码可匹配）显示材料名称+国标码+清单项目名称（如 '混凝土（010501001 垫层）'），修复 Odoo 旧 dict ID 不匹配（201 条中 8 条名称匹配修复、193 条重新计算为 code 模式），四层递进显示（dict/code有映射/code无映射/std/raw）。②测试稳定性检测：pure_tests 236 + tests 315 = **551 passed × 3 次复跑，零失败零波动（无 flaky）**；测试隔离（SQLite 内存库+StaticPool+清空表）与数据安全铁律（源文件只读/敏感文件不入仓）验证通过。③修复 .gitignore 行内注释 bug（gitignore 不支持行内注释导致 archive/、.mimosa/、*.meta.json 规则全部失效），注释移至独立行并验证生效；入仓清单规范提取数据（2013/2024 双版本）与 6 个领域工具脚本。新增 §11 章节。commit a5ad38d + d18d627。 |\n"
content = content.replace(v15_line, v16_line + v15_line, 1)

open(path, 'w', encoding='utf-8', newline='\n').write(content)
print("总控已更新至 v1.6")
