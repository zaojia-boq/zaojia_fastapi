# -*- coding: utf-8 -*-
"""生成造价数据门户产品方案 Word 文档"""
from docx import Document
from docx.shared import Inches, Pt, RGBColor, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement


def set_cell_background(cell, color):
    """设置单元格背景色"""
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:fill'), color)
    tc_pr.append(shd)


def add_heading_styled(doc, text, level):
    """添加带样式的标题"""
    heading = doc.add_heading(text, level=level)
    for run in heading.runs:
        run.font.name = '微软雅黑'
        run._element.rPr.rFonts.set(qn('w:eastAsia'), '微软雅黑')
        if level == 1:
            run.font.color.rgb = RGBColor(0x1A, 0x56, 0xDB)
        elif level == 2:
            run.font.color.rgb = RGBColor(0x2D, 0x6A, 0xE0)
    return heading


def add_para(doc, text, bold=False, size=11, color=None, align=None):
    """添加段落"""
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.font.name = '微软雅黑'
    run._element.rPr.rFonts.set(qn('w:eastAsia'), '微软雅黑')
    run.font.size = Pt(size)
    run.bold = bold
    if color:
        run.font.color.rgb = color
    if align:
        p.alignment = align
    return p


def add_table(doc, headers, rows, col_widths=None):
    """添加表格"""
    table = doc.add_table(rows=1 + len(rows), cols=len(headers))
    table.style = 'Table Grid'
    table.alignment = WD_TABLE_ALIGNMENT.CENTER

    # 表头
    for i, header in enumerate(headers):
        cell = table.rows[0].cells[i]
        cell.text = ''
        p = cell.paragraphs[0]
        run = p.add_run(header)
        run.font.name = '微软雅黑'
        run._element.rPr.rFonts.set(qn('w:eastAsia'), '微软雅黑')
        run.font.size = Pt(10)
        run.bold = True
        run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        set_cell_background(cell, '1A56DB')

    # 数据行
    for r_idx, row in enumerate(rows):
        for c_idx, cell_text in enumerate(row):
            cell = table.rows[r_idx + 1].cells[c_idx]
            cell.text = ''
            p = cell.paragraphs[0]
            run = p.add_run(str(cell_text))
            run.font.name = '微软雅黑'
            run._element.rPr.rFonts.set(qn('w:eastAsia'), '微软雅黑')
            run.font.size = Pt(10)
            if r_idx % 2 == 1:
                set_cell_background(cell, 'F0F4FF')

    if col_widths:
        for i, width in enumerate(col_widths):
            for row in table.rows:
                row.cells[i].width = Cm(width)

    return table


def main():
    doc = Document()

    # 设置默认字体
    style = doc.styles['Normal']
    font = style.font
    font.name = '微软雅黑'
    font.size = Pt(11)
    style.element.rPr.rFonts.set(qn('w:eastAsia'), '微软雅黑')

    # ========== 封面 ==========
    for _ in range(4):
        doc.add_paragraph()

    add_para(doc, '造价数据门户', bold=True, size=36,
             color=RGBColor(0x1A, 0x56, 0xDB), align=WD_ALIGN_PARAGRAPH.CENTER)
    add_para(doc, '产品方案', bold=True, size=28,
             color=RGBColor(0x2D, 0x6A, 0xE0), align=WD_ALIGN_PARAGRAPH.CENTER)

    doc.add_paragraph()
    add_para(doc, '——历史造价数据查询库 + 物料标准化引擎——',
             size=14, color=RGBColor(0x66, 0x66, 0x66),
             align=WD_ALIGN_PARAGRAPH.CENTER)

    for _ in range(6):
        doc.add_paragraph()

    add_para(doc, '版本：v1.0', size=12, align=WD_ALIGN_PARAGRAPH.CENTER)
    add_para(doc, '日期：2026年9月8日', size=12, align=WD_ALIGN_PARAGRAPH.CENTER)
    add_para(doc, '技术栈：FastAPI + SQLAlchemy + PostgreSQL + Jinja2',
             size=12, align=WD_ALIGN_PARAGRAPH.CENTER)

    doc.add_page_break()

    # ========== 目录 ==========
    add_heading_styled(doc, '目录', 1)
    toc_items = [
        '一、项目背景与定位',
        '二、目标用户与使用场景',
        '三、产品功能架构',
        '四、核心功能详解',
        '五、数据安全机制',
        '六、技术架构',
        '七、实施路线图',
        '八、团队与协作',
        '九、风险与应对',
        '十、总结与展望',
    ]
    for item in toc_items:
        add_para(doc, item, size=12)
    doc.add_page_break()

    # ========== 一、项目背景与定位 ==========
    add_heading_styled(doc, '一、项目背景与定位', 1)

    add_heading_styled(doc, '1.1 行业背景', 2)
    add_para(doc, '工程造价咨询行业积累了大量历史工程量清单 Excel 文件，但这些数据散落在各工程师的电脑和项目文件夹中，难以形成可复用的企业资产。核心痛点在于：同类清单项的历史单价无法快速查询，报价决策依赖个人经验和翻找旧文件，效率低下且缺乏数据支撑。')
    add_para(doc, '同时，大量老清单没有国标 12 位编码，只能靠物料名称和规格做同类匹配，人工归类耗时耗力且标准不一。随着企业数字化转型的推进，建立一套统一的历史造价数据门户，成为提升团队效率和数据资产沉淀的关键举措。')

    add_heading_styled(doc, '1.2 问题痛点', 2)
    add_table(doc,
        ['现状痛点', '影响', '本产品的解决方式'],
        [
            ['报价靠翻旧 Excel，找一份要十几分钟', '效率低、报价周期长', '全部清单入一个库，按编码/名称/特征直接搜，秒级响应'],
            ['同清单项在不同工程单价差多少，全凭印象', '定价缺乏数据依据', '同编码/标准化项自动汇总，给均价/区间/样本数'],
            ['审计对不上单价，说不清依据', '审计风险高', '每条记录可溯源到具体文件与工程，一键导出审核底稿'],
            ['综合单价脱离地区和时间无可比性', '数据误用风险', '每条数据带省份+价格期，跨期对比自动分组'],
            ['老清单大量无国标编码，靠名称对不上同类项', '数据无法标准化', '物料字典（三级分类）+ 三算法相似度召回，做标准化归类'],
            ['专业工具普遍"能用但难看难用"，不想打开', '工具 adoption 低', '深空科技风格界面：干净、留白、字清楚，每天愿意用'],
        ],
        col_widths=[5, 4, 7])

    add_heading_styled(doc, '1.3 产品定位', 2)
    add_para(doc, '基于 FastAPI 的「历史造价数据查询库 + 物料标准化引擎」——把散落各工程 Excel 清单里的综合单价沉淀成可查、可对比、可溯源的数据库；并解决老清单无国标编码时「靠名称+规格同类匹配」的难题。作为公司网页的一部分，支持团队共享查询。', bold=True)
    add_para(doc, '核心回答一个问题：这个清单项，我们以前做过多少钱？它标准化后该归到哪一类？')

    add_heading_styled(doc, '1.4 核心价值', 2)
    add_table(doc,
        ['价值维度', '具体体现'],
        [
            ['效率提升', '历史单价查询从十几分钟缩短到秒级；匹配确认从 100% 人工降至 10-20%（学习引擎越用越准）'],
            ['数据资产沉淀', '散落的 Excel 清单统一入库，形成企业级历史造价数据库；人工标注沉淀为标准化资产，不可重建'],
            ['决策支撑', '同类项历史均价/区间/样本数可查，报价决策有数据依据；异常单价自动标红，审计风险可控'],
            ['团队协作', '多人共享同一数据库，按角色分权；作为公司网页的一部分嵌入，团队成员通过公司门户直接访问'],
            ['安全合规', '原始文件只读保护、B 类字段禁静默覆盖、硬删四道闸门、审计日志 append-only，数据安全可审计'],
        ],
        col_widths=[3, 13])

    doc.add_page_break()

    # ========== 二、目标用户与使用场景 ==========
    add_heading_styled(doc, '二、目标用户与使用场景', 1)

    add_heading_styled(doc, '2.1 目标用户', 2)
    add_para(doc, '造价咨询从业人员（公司内部团队）。通过公司 OA 统一登录（易达 ECMS），多人共享同一数据库，按角色分权。可作为公司网页的一部分嵌入，团队成员通过公司门户直接访问。')

    add_heading_styled(doc, '2.2 用户角色与权限', 2)
    add_table(doc,
        ['角色', '权限范围', '典型用户'],
        [
            ['admin（管理员）', '全部权限：导入/删除/标注/用户管理/系统设置', '项目负责人、数据管理员'],
            ['estimator（造价师）', '查询/导出/单价分析/匹配确认/字典维护/批次查看，B 类字段只读', '造价工程师、造价员'],
            ['viewer（浏览者）', '只读浏览，禁导出', '实习生、临时查看人员'],
            ['未登录用户', '仅可查看已标准化（std_name 非空）的数据，不可导出', '公司网页访客'],
        ],
        col_widths=[3, 9, 4])

    add_heading_styled(doc, '2.3 核心使用场景', 2)

    add_para(doc, '场景 1 · 报价查历史价', bold=True, size=12, color=RGBColor(0x1A, 0x56, 0xDB))
    add_para(doc, '造价工程师在编制报价时，粘贴项目编码或名称搜索 → 查看历史单价区间（均价/最低/最高/中位数/样本数）→ 据此定价。支持按省份、价格期、工程类型筛选，确保对比的是同维度数据。')

    add_para(doc, '场景 2 · 审计查异常单价', bold=True, size=12, color=RGBColor(0x1A, 0x56, 0xDB))
    add_para(doc, '审计人员导入待审清单（自动标记为「待审」，绝不混入历史均价）→ 与已完工程历史价横向对比 → 偏离区间标红 → 导出审核底稿。每条数据可溯源到原始 Excel 文件，审计可逐字核对。')

    add_para(doc, '场景 3 · 数据沉淀与标准化', bold=True, size=12, color=RGBColor(0x1A, 0x56, 0xDB))
    add_para(doc, '做完工程后，造价工程师把清单 Excel 导入 → 系统自动解析（多格式支持、字段映射、校验报告）→ 无编码项经字典匹配/三算法相似度建议 → 人工确认（高置信可批量确认）→ 沉淀为标准化历史单价。学习引擎根据确认结果自动调整算法权重，越用越准。')

    add_para(doc, '场景 4 · 团队共享与公司网页嵌入', bold=True, size=12, color=RGBColor(0x1A, 0x56, 0xDB))
    add_para(doc, '团队成员通过公司 OA 统一登录 → 访问造价数据门户（作为公司网页子路径或子域名）→ Portal 页（数据概览/清单检索/价格分析）面向所有用户，Admin 页（导入/批次/字典/匹配/质量/设置）面向管理员和造价师。未登录用户可查看已标准化数据，登录后可查看全部数据并执行操作。')

    doc.add_page_break()

    # ========== 三、产品功能架构 ==========
    add_heading_styled(doc, '三、产品功能架构', 1)

    add_heading_styled(doc, '3.1 功能全景', 2)
    add_para(doc, '产品采用「前后端页面分离」架构（方案 A），分为 Portal 前端展示页和 Admin 后端管理页，共享同一套 API 和数据库。')

    add_table(doc,
        ['页面组', '页面', '面向用户', '核心功能'],
        [
            ['Portal（前端展示）', '数据概览', '所有用户（含未登录）', 'KPI 卡片、月度趋势、专业分布、数据质量概览'],
            ['', '清单检索', '所有用户（含未登录）', '多条件组合搜索、列表展示、详情查看、列宽调整'],
            ['', '价格分析', '所有用户（含未登录）', '同类项历史均价、单价区间、趋势图、样本构成'],
            ['Admin（后端管理）', '管理概览', 'admin/estimator', '管理视角 KPI、待处理事项、最近导入批次'],
            ['', '导入向导', 'admin', '多格式上传、字段映射模板、校验报告、预览确认、归档压缩'],
            ['', '批次管理', 'admin', '批次列表、详情查看、软删/还原、硬删（四道闸门）、校验和核对'],
            ['', '物料字典', 'admin/estimator', '三级分类树、同义词维护、规格白名单、新增分类'],
            ['', '匹配确认', 'admin/estimator', '待匹配列表、三算法候选、批量确认、手动添加、学习记录'],
            ['', '数据质量', 'admin/estimator', '质量仪表盘、异常清单、覆盖率、标准化进度'],
            ['', '成本目录', 'admin/estimator', '标准化单价目录、聚合统计、成本迁移'],
            ['', '系统设置', 'admin', '参数配置、阈值调整、模板管理、审计日志查询'],
        ],
        col_widths=[3, 2.5, 3, 7.5])

    add_heading_styled(doc, '3.2 P0 核心功能（已完成）', 2)
    add_table(doc,
        ['功能', '说明', '状态'],
        [
            ['Excel 导入（稳健）', '向导支持国标表头；合并单元格处理、汇总/合计行识别跳过、异常行预览标记；预览不写库，确认后才入库；重复导入同文件自动识别，只更新来自 Excel 的内容、保留人工标注', '✅ 已完成'],
            ['原始数据保护', '只读导入绝不改原文件；导入即归档；删除进回收站可还原；改过什么留有删不掉的流水账', '✅ 已完成'],
            ['数据性质标记', '导入时选「已完工程/控制价/投标报价/待审/信息价」；历史均价默认只用「已完工程」', '✅ 已完成'],
            ['物料字典维护', '三级材料分类字典（大类/系列/规格集合、同义词、规格白名单），UI 可编辑', '✅ 已完成'],
            ['多条件组合查询', '搜索视图：项目编码/名称/特征/标准化字段/单位/工程/省份/价格期组合筛选', '✅ 已完成'],
            ['列表与详情', '列表视图（排序/分组/列宽调整）+ 表单视图看完整详情', '✅ 已完成'],
            ['结果导出', '筛选结果集导出 Excel/CSV，含原始字段+标准化字段+溯源字段；导出留记录，单次超 1000 行二次确认', '✅ 已完成'],
        ],
        col_widths=[3, 10, 3])

    add_heading_styled(doc, '3.3 P1 增强功能（已完成）', 2)
    add_table(doc,
        ['功能', '说明', '状态'],
        [
            ['三算法融合匹配', 'rapidfuzz（编辑距离）+ TF-IDF（语义匹配）+ FAISS（向量检索），权重由学习引擎自适应，召回 Top-5 候选，仅建议、人工确认才回填', '✅ 已完成'],
            ['学习引擎 v3', '概念漂移检测、多策略集成学习、学习轨迹可解释性、主动学习策略优化、元学习自动调参，越用越准', '✅ 已完成'],
            ['同类项历史单价统计', '按统一"同类项聚合键"聚合（字典>标准化>国标编码>原始名称，四级优先）；给样本数/最低/最高/平均/中位数；显示口径构成', '✅ 已完成'],
            ['单价异常识别', '与区间比较，偏离超阈值标红', '✅ 已完成'],
            ['导入批次管理', '批次列表，查看/删除/重导；回收站（还原误删批次）、批次校验和、归档完整性校验', '✅ 已完成'],
            ['审计日志查询', '谁在什么时候把哪条数据从多少改成了多少，可查、可导出，删不掉（append-only）', '✅ 已完成'],
            ['成本目录', '标准化单价目录，从 boq_item 聚合，cost_catalog 表存储', '✅ 已完成'],
            ['M2 导入深化', '多格式解析器（xlsx/xlsm/xls/csv+魔数校验）、字段映射模板（13标准字段含暂估价+自动推荐）、校验规则引擎（5种类型/7个模板/三级分级）、归档增强（ZIP压缩+完整性巡检+保留策略）', '✅ 已完成'],
        ],
        col_widths=[3, 10, 3])

    add_heading_styled(doc, '3.4 P2 后续迭代（待启动）', 2)
    add_table(doc,
        ['功能', '说明', '状态'],
        [
            ['OA SSO 对接', '易达 ECMS 统一登录对接，替换开发期 dev_token；按 OA 部门/职位自动映射角色', '📋 方案完成，待厂商文档'],
            ['数据迁移', 'Odoo 版 zaojia_db 数据 ETL 至新库，三重校验（行数/B类逐字段/SHA256）', '⏸ 待启动'],
            ['单价趋势图', '按时间维度展示单价变化趋势，支持同类别对比', '⏸ 待启动'],
            ['常用项收藏', '用户可收藏常用清单项，快速访问', '⏸ 待启动'],
            ['标签分类', '自定义标签对清单项进行分类管理', '⏸ 待启动'],
            ['多库合并', '支持多个数据库的合并与对比', '⏸ 待启动'],
        ],
        col_widths=[3, 10, 3])

    doc.add_page_break()

    # ========== 四、核心功能详解 ==========
    add_heading_styled(doc, '四、核心功能详解', 1)

    add_heading_styled(doc, '4.1 Excel 导入与数据治理', 2)
    add_para(doc, '导入是数据进入系统的唯一入口，也是数据质量的第一道关口。采用「预览不写库，确认才入库」的向导式流程，确保每一条数据都经过用户确认。')

    add_para(doc, '导入流程：', bold=True)
    add_para(doc, '1. 文件上传：支持 .xlsx/.xlsm/.xls/.csv 四种格式，魔数校验确保文件类型真实；单文件 ≤50MB、单 sheet ≤20万行，超限拒绝。')
    add_para(doc, '2. 自动解析：多格式解析器自动识别文件类型并解析；字段映射模板根据文件名/表头自动推荐最佳模板，用户可手动调整映射并保存模板。')
    add_para(doc, '3. 校验报告：校验规则引擎对解析结果进行校验（必填列、数值格式、重复行、异常值等），生成三级分级校验报告（错误/警告/提示），有错误时禁用执行按钮。')
    add_para(doc, '4. 预览确认：展示解析结果预览（前 100 行），用户确认无误后才执行入库。')
    add_para(doc, '5. 分层 Upsert：A 类字段（可重建，从 Excel 解析）可覆盖更新；B 类字段（不可重建，人工标注）仅填空不覆盖，已有值原样保留；孤儿行软标记不自动删，B 类标注回灌到新建行。')
    add_para(doc, '6. 归档压缩：导入成功后自动归档原始文件（ZIP 压缩节省空间），记录归档路径和校验和，支持完整性巡检和保留策略自动清理。')

    add_heading_styled(doc, '4.2 清单检索与单价分析', 2)
    add_para(doc, '清单检索是用户使用频率最高的功能，支持多条件组合搜索和列宽自定义调整，确保用户能一次性预览全部内容。')

    add_para(doc, '检索能力：', bold=True)
    add_para(doc, '• 多条件组合：项目编码/名称/特征/标准化字段/单位/工程/省份/价格期/数据性质组合筛选')
    add_para(doc, '• 模糊搜索：支持名称/特征的模糊匹配，高亮匹配关键词')
    add_para(doc, '• 列宽调整：用户可拖拽调整列宽，尽量一次性预览全部内容')
    add_para(doc, '• 排序分组：按任意列排序，支持按工程/专业分组')
    add_para(doc, '• 详情查看：点击行查看完整详情（含项目特征全文、标准化字段、溯源信息）')
    add_para(doc, '• 结果导出：筛选结果集导出 Excel/CSV，含原始字段+标准化字段+溯源字段')

    add_para(doc, '单价分析：', bold=True)
    add_para(doc, '• 同类项聚合：按统一"同类项聚合键"（match_key）聚合，优先级：字典 > 标准化 > 国标编码 > 原始名称')
    add_para(doc, '• 统计指标：样本数/最低/最高/平均/中位数，必须显示口径构成（本次均价里多少来自编码匹配、多少来自标准化）')
    add_para(doc, '• 异常识别：与区间比较，偏离超阈值标红')
    add_para(doc, '• 数据性质过滤：历史均价默认只用「已完工程」，其他性质（控制价/投标报价/待审/信息价）不混入')

    add_heading_styled(doc, '4.3 物料标准化与匹配引擎', 2)
    add_para(doc, '物料标准化是本产品的核心差异化能力，解决老清单无国标编码时「靠名称+规格同类匹配」的难题。采用「三算法融合 + 学习引擎」的智能匹配方案，越用越准。')

    add_para(doc, '三算法融合：', bold=True)
    add_table(doc,
        ['算法', '权重', '优势', '适用场景'],
        [
            ['rapidfuzz（编辑距离）', '0.30', '精确匹配强，对名称完全一致或高度相似的项命中率高', '编码规范、名称标准的清单项'],
            ['TF-IDF（语义匹配）', '0.35', '同义词/近义词匹配强，能识别"混凝土"和"砼"等同义表达', '名称表述不统一、存在同义词的清单项'],
            ['FAISS（向量检索）', '0.35', '大数据量快，语义理解能力强，支持模糊语义匹配', '10万+条数据的大规模检索'],
        ],
        col_widths=[4, 2, 6, 4])

    add_para(doc, '学习引擎 v3（五项核心能力）：', bold=True)
    add_para(doc, '1. 概念漂移检测：监测物料名称/规格的语义变化，自动调整算法权重')
    add_para(doc, '2. 多策略集成学习：融合多种匹配策略，根据场景自动选择最优策略组合')
    add_para(doc, '3. 学习轨迹可解释性：记录每次确认对算法权重的影响，可追溯、可解释')
    add_para(doc, '4. 主动学习策略优化：优先推荐不确定性高的项给人工确认，最大化学习效率')
    add_para(doc, '5. 元学习自动调参：根据历史确认数据自动优化算法超参数，无需人工调参')

    add_para(doc, '匹配确认流程：', bold=True)
    add_para(doc, '1. 待匹配列表：展示所有 material_dict_id 为空的清单项，按批次/专业筛选')
    add_para(doc, '2. 候选召回：三算法融合召回 Top-5 候选，显示每个候选的名称/规格/分类/置信度')
    add_para(doc, '3. 批量确认：高置信（≥90分）项可全选批量确认，自动选用最高置信项；低置信项需人工逐条确认')
    add_para(doc, '4. 手动添加：确认没有的项，可手动添加到物料字典，并设置学习记录')
    add_para(doc, '5. 学习反馈：每次确认结果反馈给学习引擎，自动调整算法权重')
    add_para(doc, '6. 后台预匹配：导入完成后异步预计算所有待匹配条目的候选，存入 match_cache 表，匹配确认页优先从缓存读取，避免实时计算 O(N×M)')

    add_heading_styled(doc, '4.4 成本目录与历史均价', 2)
    add_para(doc, '成本目录是标准化单价的归档库，从 boq_item 聚合而来，用于快速查询标准化后的历史均价。')

    add_para(doc, '成本目录功能：', bold=True)
    add_para(doc, '• 聚合键：按 match_key 聚合，同 match_key 的清单项归为同一成本目录项')
    add_para(doc, '• 统计指标：样本数/最低/最高/平均/中位数，按数据性质分组统计')
    add_para(doc, '• B 类保护：成本目录的 std_name/std_spec/material_dict_id 从 boq_item 取最新值，已有值不覆盖（人工标注保护）')
    add_para(doc, '• 成本迁移：支持从 boq_item 全量迁移到 cost_catalog，迁移过程中保留人工标注')

    add_heading_styled(doc, '4.5 数据质量与审计溯源', 2)
    add_para(doc, '数据质量仪表盘实时监控数据质量状况，审计日志记录所有数据变更，确保数据可追溯、可审计。')

    add_para(doc, '数据质量指标：', bold=True)
    add_para(doc, '• 覆盖率：material_dict_id 非空的行占比（标准化覆盖率）')
    add_para(doc, '• 异常率：anomaly_flag 为 warning/error 的行占比')
    add_para(doc, '• 完整率：必填字段（item_name/quantity/unit_rate/total）非空的行占比')
    add_para(doc, '• 校验和：批次入库总额与 Excel 合计的一致性核对')

    add_para(doc, '审计日志（append-only）：', bold=True)
    add_para(doc, '• 四元组：operator（操作人）/ reason（变更原因）/ trace_id（追踪ID）/ timestamp（时间）')
    add_para(doc, '• 记录内容：模型/记录ID/动作（create/write/soft_delete/restore/import/export/hard_delete）/变更字段/旧值/新值/关联批次')
    add_para(doc, '• 不可篡改：SQLAlchemy 事件监听禁止 update/delete；生产环境数据库层 REVOKE UPDATE/DELETE')
    add_para(doc, '• 自动记录：AuditMiddleware 自动记录所有写操作（POST/PUT/PATCH/DELETE）')

    doc.add_page_break()

    # ========== 五、数据安全机制 ==========
    add_heading_styled(doc, '五、数据安全机制', 1)

    add_para(doc, '数据安全是本产品的生命线。核心原则：原始造价 Excel 与人工标注（B 类字段）不可重建、不可静默丢失。数据库坏了不致命，原始文件和人工标注丢了才致命。', bold=True)

    add_heading_styled(doc, '5.1 数据分层（A/B/C 类）', 2)
    add_table(doc,
        ['分层', '定义', '字段示例', '保护规则'],
        [
            ['A 类（可重建）', '从原始 Excel 解析出的派生物，重导允许覆盖更新', 'item_code/item_name/quantity/unit_rate/total/provisional_sum 等 21 个字段', '重导时可覆盖更新'],
            ['B 类（不可重建）', '人工标注资产，禁止删除、禁止静默覆盖', 'std_name/std_spec/material_dict_id/anomaly_flag/anomaly_reason/data_source_type 等 6 个字段', '已有值原样保留，仅空时写入；变更必须带 reason（审计四元组），无 reason 拒绝'],
            ['C 类（系统元数据）', '由系统维护，不参与 A/B 分层覆盖逻辑', 'id/biz_id/create_date/write_date/active/match_key/aggregate_id 等 10 个字段', '系统自动维护，用户不可直接修改'],
        ],
        col_widths=[3, 4, 5, 4])

    add_para(doc, '单一事实源：A/B/C 字段分层定义统一在 data/field_spec.py，任何涉及"B 类禁静默覆盖"的逻辑都必须引用此文件的常量，不得在代码里重新硬编码字段列表。')

    add_heading_styled(doc, '5.2 原始文件保护', 2)
    add_para(doc, '• 只读导入：load_workbook 必须带 read_only=True, data_only=True；read_only=True 时 openpyxl 根本不支持 save()，一旦调用会抛 InvalidFileException，这是机制保障')
    add_para(doc, '• 禁止保存：import_service 不得持有可写工作簿，代码中永不对源文件句柄调用 save()')
    add_para(doc, '• 禁止原地操作：不修改、不重命名、不移动、不删除源文件')
    add_para(doc, '• 导入即归档：每条数据可点开当时那份 Excel，归档文件 ZIP 压缩，记录校验和')
    add_para(doc, '• 源文件只读校验：代码审查时检查不得出现对源文件的 wb.save(（允许的例外：导出向内存 BytesIO 生成全新导出文件；测试代码自建临时夹具文件）')

    add_heading_styled(doc, '5.3 硬删四道闸门', 2)
    add_para(doc, '硬删除是不可逆操作，设置四道闸门确保只有在绝对安全的情况下才能执行：')
    add_table(doc,
        ['闸门', '具体做法', '防的是什么'],
        [
            ['1. 权限校验', '仅 admin 角色可执行硬删除，estimator/viewer 无权限', '防止误操作或越权删除'],
            ['2. 名称确认', '必须输入与批次名完全一致的确认名，否则拒绝', '防止误点删除按钮'],
            ['3. 30天宽限', '软删后 30 天内禁止硬删，必须等回收站宽限期过', '给用户足够的时间发现误删并还原'],
            ['4. CSV快照', '硬删前必须导出 CSV 快照成功（含软删/孤儿行全量），快照失败即拒绝硬删；含人工标注的批次强制导出快照', '确保删除后可从快照恢复，人工资产不丢失'],
        ],
        col_widths=[3, 8, 5])

    add_heading_styled(doc, '5.4 审计日志（append-only）', 2)
    add_para(doc, '• 三重保障：①模型层 SQLAlchemy 事件监听禁止 update/delete（before_update/before_delete 抛异常）；②权限层三角色均无 audit_log 写权限；③数据库层 REVOKE UPDATE/DELETE（生产环境）')
    add_para(doc, '• 不建外键：model+res_id 为软引用，原记录被物理删除后日志仍须留存，外键会连带删掉证据')
    add_para(doc, '• 四元组完整：operator/reason/trace_id/timestamp，所有写操作自动记录')
    add_para(doc, '• 长文本截断：old_value/new_value 截断到 512 字符，标注 [truncated]')

    add_heading_styled(doc, '5.5 权限控制与数据可见性', 2)
    add_para(doc, '• 三角色权限：admin（全部权限）/ estimator（查询+匹配确认+字典维护+批次查看）/ viewer（只读查询，禁导出）')
    add_para(doc, '• 前后端分离：Portal 页（/portal/*）可选登录，未登录仅已标准化数据可见；Admin 页（/admin/*）必须登录+角色校验')
    add_para(doc, '• 数据可见性：未登录用户仅能看到已标准化（std_name 非空）的数据，导出需登录')
    add_para(doc, '• 生产环境安全加固：/docs 与 /openapi.json 生产期禁用（避免接口结构泄漏）；Cookie httponly=True 防 XSS 窃取令牌；datetime 全部 timezone-aware 消除时区语义不一致')
    add_para(doc, '• OA SSO 对接：生产期由 OA 用户部门/职位自动映射角色，替代开发期 role 参数')

    doc.add_page_break()

    # ========== 六、技术架构 ==========
    add_heading_styled(doc, '六、技术架构', 1)

    add_heading_styled(doc, '6.1 技术栈选型', 2)
    add_table(doc,
        ['层级', '技术选型', '选型理由'],
        [
            ['Web 框架', 'FastAPI 0.141', '异步高性能、自动 OpenAPI 文档、Pydantic 校验、AI 写代码质量高'],
            ['ORM', 'SQLAlchemy 2.0', '成熟稳定、显式事务、Alembic 迁移工具'],
            ['数据库', 'PostgreSQL 15+', 'numeric 精确，无 SQLite REAL 退化；JSONB 支持灵活存储'],
            ['模板引擎', 'Jinja2', '服务端渲染，AI 最熟、维护成本低；可渐进升级为前后端分离'],
            ['纯函数层', 'data/ 目录（零框架依赖）', '从 Odoo 版原样复用，236 条 pytest 全绿作为回归基线'],
            ['匹配算法', 'rapidfuzz + scikit-learn(TF-IDF) + faiss-cpu', '三算法融合，精确匹配+语义匹配+向量检索互补'],
            ['学习引擎', '自研 learning_engine v3', '概念漂移检测/多策略集成/元学习自动调参，越用越准'],
            ['中文分词', 'jieba', '物料名称中文分词，提升 TF-IDF 和 FAISS 匹配准确率'],
            ['Excel 解析', 'openpyxl + xlrd', '多格式支持（xlsx/xlsm/xls/csv），read_only 模式保障源文件安全'],
            ['测试', 'pytest + FastAPI TestClient', '统一测试框架，纯函数+集成测试分离，512 条测试全绿'],
            ['前端', '深空科技设计系统（CSS 变量 + 原生 JS）', '主色 #4D7CFE / 辅色 #22D3EE / 底 #0B0F1A，干净留白'],
            ['认证', '公司 OA 统一登录（易达 ECMS）+ 三角色依赖注入', '公司已有完整 OA，不建独立账号体系；开发期 dev_token 占位'],
        ],
        col_widths=[3, 5, 8])

    add_heading_styled(doc, '6.2 系统架构', 2)
    add_para(doc, '系统采用分层架构，自上而下分为：表现层 → 路由层 → 服务层 → 纯函数层 → 数据模型层 → 核心层，依赖方向单向。')

    add_para(doc, '分层说明：', bold=True)
    add_para(doc, '• 表现层（app/templates/）：Jinja2 模板，Portal 页（3页）+ Admin 页（8页）+ 基础模板')
    add_para(doc, '• 路由层（app/api/）：9 个 API 路由模块（import/query/batch/price/match/quality/batch_operation/cost_catalog/dict）+ 页面路由（pages.py），共 56 个端点')
    add_para(doc, '• 服务层（app/services/）：12 个业务服务（import/upsert/archive/query/material_match/prematch/price/data_quality/batch_operation/cost_catalog/cost_migration/page_services）')
    add_para(doc, '• 纯函数层（data/）：20+ 个纯函数模块，零框架依赖，可独立测试，包含字段分层/编码解析/别名映射/单位归一化/三算法匹配/学习引擎/M2 深化四大模块')
    add_para(doc, '• 数据模型层（app/models/）：6 张表（boq_item/import_batch/material_dict/audit_log/match_cache/cost_catalog），SQLAlchemy 2.0 声明式模型')
    add_para(doc, '• 核心层（app/core/）：security（认证授权）、audit（审计落库）、permissions（权限函数）、config（配置）')

    add_heading_styled(doc, '6.3 数据模型', 2)
    add_table(doc,
        ['表名', '说明', '核心字段', '记录数（示例）'],
        [
            ['boq_item', '清单项（核心表）', 'id/biz_id/item_code/item_name/item_feature/unit/quantity/unit_rate/total/provisional_sum/std_name/std_spec/material_dict_id/match_key/data_source_type/anomaly_flag/import_batch_id/active 等 40+ 字段', '1389 条（测试库）'],
            ['import_batch', '导入批次', 'id/biz_id/name/source_file/file_hash/row_count/imported_count/skipped_count/anomaly_count/imported_at/province/price_period/operator/data_source_type/checksum_count/checksum_total/checksum_hash/archive_path/active/deleted_at 等 25 字段', '示例'],
            ['material_dict', '物料分类字典（三级树）', 'id/name/cat_l1/cat_l2/cat_l3/level/parent_id/synonyms(JSON)/spec_whitelist(JSON)/sort_order/active', '示例'],
            ['audit_log', '审计日志（append-only）', 'id/model/res_id/action/field_name/old_value/new_value/operator/reason/trace_id/timestamp/batch_id', '示例'],
            ['match_cache', '匹配结果缓存（M3 性能优化）', 'id/boq_item_id/candidates(JSONB)/top1_score/cache_version/computed_at', '示例'],
            ['cost_catalog', '成本目录（M4）', 'id/match_key/std_name/std_spec/material_dict_id/sample_count/min_price/max_price/avg_price/median_price/data_source_type/active', '示例'],
        ],
        col_widths=[3, 3, 8, 2])

    add_heading_styled(doc, '6.4 匹配算法（三算法融合 + 学习引擎）', 2)
    add_para(doc, '匹配引擎是本产品的核心技术差异化能力，采用「三算法融合 + 学习引擎权重自适应」的方案，在精确匹配和语义匹配之间取得平衡，并通过学习机制持续优化。')

    add_para(doc, '算法流程：', bold=True)
    add_para(doc, '1. 候选构建：从 material_dict 构建候选行（L3 规格集合为主），每个候选含 id/name/spec/category_path')
    add_para(doc, '2. rapidfuzz 匹配：对 query_name（item_name）和 query_spec（item_feature）分别计算编辑距离相似度，取加权平均')
    add_para(doc, '3. TF-IDF 匹配：jieba 分词后构建 TF-IDF 向量，计算余弦相似度，fuse_scores 与 rapidfuzz 结果融合')
    add_para(doc, '4. FAISS 匹配：构建 FAISS 索引（FlatIP 内积），向量检索 Top-N，fuse_three_algorithms 三算法融合')
    add_para(doc, '5. 学习引擎调权：get_global_engine_v3() 根据历史确认数据调整三算法权重，默认权重 0.30/0.35/0.35')
    add_para(doc, '6. 结果排序：按融合分数排序，返回 Top-5 候选，每个候选含 dict_id/name/spec/score/category_path')
    add_para(doc, '7. 缓存优化：预匹配结果存入 match_cache 表，匹配确认页优先从缓存读取，缓存未命中或过期时回退实时计算')

    add_heading_styled(doc, '6.5 前后端分离方案（方案 A）', 2)
    add_para(doc, '采用「单应用 + 路由前缀分离」的方案 A，在同一个 FastAPI 应用中通过路由前缀区分 Portal 前端展示页和 Admin 后端管理页，共享同一套 API 和数据库。')

    add_table(doc,
        ['维度', 'Portal（前端展示）', 'Admin（后端管理）'],
        [
            ['路由前缀', '/portal/*', '/admin/*'],
            ['页面数', '3 页（dashboard/search/price）', '8 页（dashboard/import/batches/dict/match/quality/cost-catalog/settings）'],
            ['登录要求', '可选登录，未登录可访问', '必须登录 + 角色校验'],
            ['数据可见性', '未登录仅已标准化（std_name 非空）数据可见', '登录后可见全部数据'],
            ['可执行操作', '只读查询（登录后可导出）', '导入/删除/匹配确认/字典维护/质量监控/系统设置'],
            ['导航栏', '简洁 3 项（数据概览/清单检索/价格分析）', '完整 8 项'],
            ['样式', 'portal.css（简洁展示风格）', 'admin.css（管理操作风格）'],
            ['基础模板', 'base_portal.html（继承 base.html）', 'base_admin.html（继承 base.html）'],
        ],
        col_widths=[3, 6.5, 6.5])

    add_para(doc, '旧路由兼容：所有旧路由（/dashboard、/search、/import 等）做 301 重定向到新前缀，确保旧链接可访问。首页 / 重定向到 /portal/dashboard。')

    doc.add_page_break()

    # ========== 七、实施路线图 ==========
    add_heading_styled(doc, '七、实施路线图', 1)

    add_heading_styled(doc, '7.1 已完成里程碑', 2)
    add_table(doc,
        ['里程碑', '范围', '完成时间', '关键产出'],
        [
            ['M0 迁移准备', 'Odoo 版归档 + FastAPI 骨架 + 纯函数迁移 + 测试验证 + 文档适配 + 领域资产抽取', '2026-09-05', '项目骨架、720 行纯函数、90 条 pure_tests、4 份文档、field_spec.py 字段分层定义'],
            ['M1 数据模型与基础', 'SQLAlchemy 四核心模型 + 编码解析与 match_key + 分层 Upsert 与孤儿 + 审计落库 + 权限体系 + 测试验收', '2026-09-06', '6 张数据表、A/B/C 分层保护、审计 append-only、三角色权限、134 条测试'],
            ['M2 导入与查询', '导入向导（预览不写库）+ 查询导出 + 批次软删/还原/硬删（四道闸门）+ 归档服务', '2026-09-06', '完整导入流水线、查询导出、批次管理、硬删四道闸门、CSV 快照'],
            ['M2.5 UI 页面', '数据概览 + 清单检索 + 导入向导 + 批次管理 + 单价分析 + 物料字典 + 匹配确认 + 系统设置', '2026-09-07', '11 个页面、深空科技风格、列宽调整、搜索优化'],
            ['M3 单价分析', '同类项聚合分析 + 匹配向导 + 质量仪表盘 + 匹配效率优化（三算法融合 + 学习引擎 + 后台预匹配）', '2026-09-07', '三算法融合（rapidfuzz+TF-IDF+FAISS）、学习引擎 v1/v2/v3、后台预匹配缓存、自动确认阈值降低'],
            ['M4 成本目录', '成本目录表 + 成本迁移服务 + 聚合统计', '2026-09-07', 'cost_catalog 表、cost_migration_service、聚合统计'],
            ['M2 导入深化', '多格式解析器 + 字段映射模板 + 校验规则引擎 + 归档增强', '2026-09-08', '4 个纯函数模块、13 标准字段含暂估价、5 种校验规则类型、ZIP 压缩归档、39 条 pure_tests'],
            ['方案 A 前后端分离', 'Portal 页 + Admin 页 + 路由前缀分离 + 三角色权限矩阵 + 数据可见性控制 + 旧路由 301 重定向', '2026-09-08', '3 个 Portal 页 + 8 个 Admin 页、三角色权限、数据可见性控制、旧路由兼容'],
            ['安全加固', '生产环境 /docs 禁用 + Cookie httponly + datetime 时区感知 + 代码库全面架构梳理', '2026-09-08', '安全加固、3352 条弃用告警消除、架构梳理报告、512 条测试全绿'],
        ],
        col_widths=[3, 5, 2, 6])

    add_heading_styled(doc, '7.2 待完成事项', 2)
    add_table(doc,
        ['事项', '优先级', '依赖', '预计工作量'],
        [
            ['OA SSO 对接', 'P0', '易达 ECMS 提供 SSO 协议文档', '8-10 天（方案已完成，待厂商文档）'],
            ['S7/N1–N3 自动化用例补齐', 'P1', '无', '1-2 天（仅 N1-N3 反向用例，S7 已有测试）'],
            ['并发导入锁机制', 'P2', '无', '2 天（文件哈希幂等 + 批次级锁）'],
            ['大数据量（10万+）性能压测', 'P2', '无', '2 天（FAISS 索引持久化 + 查询性能优化）'],
            ['单价趋势图', 'P2', '无', '3 天（ECharts 集成 + 时间维度聚合）'],
            ['常用项收藏', 'P3', '无', '2 天'],
            ['标签分类', 'P3', '无', '2 天'],
            ['多库合并', 'P3', '无', '5 天'],
        ],
        col_widths=[5, 2, 4, 5])

    add_heading_styled(doc, '7.3 时间规划', 2)
    add_para(doc, '第一阶段（已完成，2026-09-05 至 2026-09-08）：核心功能开发', bold=True)
    add_para(doc, 'M0-M4 核心功能 + 匹配效率优化 + M2 深化 + 方案 A 前后端分离 + 安全加固，512 条测试全绿，具备内部试用条件。')

    add_para(doc, '第二阶段（待启动，预计 2-3 周）：生产就绪', bold=True)
    add_para(doc, 'OA SSO 对接 + 并发导入锁 + 大数据量性能压测 + S7/N1-N3 用例补齐，具备生产上线条件。')

    add_para(doc, '第三阶段（远期，按需）：体验增强', bold=True)
    add_para(doc, '单价趋势图 + 常用项收藏 + 标签分类 + 多库合并，持续优化用户体验。')

    doc.add_page_break()

    # ========== 八、团队与协作 ==========
    add_heading_styled(doc, '八、团队与协作', 1)

    add_heading_styled(doc, '8.1 角色分工', 2)
    add_table(doc,
        ['角色', '职责', '产出'],
        [
            ['总控 Agent', '维护项目总控、拆解需求、分配子任务、评审产出、受理变更提案、维护版本进度', '项目总控.md、评审记录、变更裁决'],
            ['M1-数据模型', 'SQLAlchemy 模型、审计落库、数据库迁移脚本', 'app/models/、tests/test_models.py'],
            ['M1-权限认证', '认证授权、OA SSO 参数、权限函数', 'app/core/security.py、app/core/permissions.py'],
            ['M2-导入服务', 'Excel 解析、分层 Upsert、归档服务', 'app/services/import_service.py、upsert_service.py、archive_service.py'],
            ['M2-查询导出', '清单查询、导出、批次服务', 'app/services/query_service.py、app/api/query.py'],
            ['M2-前端页面', 'Jinja2 模板、CSS/JS、页面路由', 'app/templates/、app/static/、app/api/pages.py'],
            ['M3-单价分析', '匹配服务、价格服务、数据质量服务', 'app/services/material_match_service.py、price_service.py、data_quality_service.py'],
            ['M4-成本库', '成本目录模型、成本迁移服务', 'app/models/cost_catalog.py、app/services/cost_migration_service.py'],
            ['OA-SSO对接', 'OA 统一登录对接、角色映射', 'app/core/security.py（get_current_user 替换）、oauth_client.py、role_mapper.py'],
            ['Agent-0（集成守门）', '路由注册、依赖管理、配置文件、交付总控 commit', 'app/main.py、requirements.txt、.env'],
        ],
        col_widths=[3, 6, 7])

    add_heading_styled(doc, '8.2 开发流程', 2)
    add_para(doc, '1. 需求拆解：总控 Agent 根据项目总控拆解需求，分配给对应子 Agent')
    add_para(doc, '2. 设计评审：子 Agent 输出设计方案，总控评审通过后进入开发')
    add_para(doc, '3. 测试先行：安全铁律和核心业务先写自动化用例，再写实现')
    add_para(doc, '4. 小步 commit：一个功能一 commit 一测试，不攒大改')
    add_para(doc, '5. 自验证据：每个改动必须跑通 §9 登记命令，提供原样执行记录')
    add_para(doc, '6. 总控评审：总控 Agent 按评审清单逐条核对，通过后回写项目总控')
    add_para(doc, '7. 交付验收：全量测试通过 + 文档更新 + commit 记录完整，方可宣告完成')

    add_heading_styled(doc, '8.3 质量保障', 2)
    add_table(doc,
        ['保障维度', '具体措施', '验收标准'],
        [
            ['测试覆盖', '纯函数测试（pure_tests/）+ FastAPI 集成测试（tests/）分离，新逻辑必有对应测试', '512 条测试全绿，零失败'],
            ['安全用例', 'S1-S9 安全用例优先级高于功能用例，任一失败 = 整体不通过', 'S 用例全部 PASS'],
            ['源文件只读', '导入相关代码不得出现对源 Excel 的 wb.save(，所有 load_workbook 必须带 read_only=True', 'grep 校验无违规'],
            ['敏感文件不入仓', 'git status 不得出现 .xlsx/.xls/.sql/.dump 文件', 'git status 校验无违规'],
            ['B 类字段保护', '无 reason 的 B 类写入必须被拒绝（代码层 + 测试层双重锁死）', '权限用例通过'],
            ['硬删闸门', '硬删前必须导出 CSV 快照成功，快照失败不得放行', '硬删用例通过'],
            ['审计日志', '所有写操作自动记录审计日志，四元组完整，append-only 不可篡改', '审计用例通过'],
            ['代码审查', '每次交付前调用 Self-Improving + Proactive Agent 技能审查', '审查通过，无 P0/P1 问题'],
            ['视觉基线', 'UI 改动后必须截图对照，不接受"看起来差不多"', '视觉项人工核对'],
            ['小步 commit', '一改动一 commit，AGENTS.md 两条硬规则（commit + 测试）缺一不验收', 'git log 校验'],
        ],
        col_widths=[3, 8, 5])

    doc.add_page_break()

    # ========== 九、风险与应对 ==========
    add_heading_styled(doc, '九、风险与应对', 1)

    add_heading_styled(doc, '9.1 技术风险', 2)
    add_table(doc,
        ['风险', '影响', '概率', '应对措施'],
        [
            ['OA SSO 对接困难', '生产环境无法使用公司统一登录，需自建账号体系', '中', '提前与易达 ECMS 厂商沟通，确认 SSO 协议；备选方案：反向代理认证、LDAP/AD、数据库直连、自定义 Token'],
            ['大数据量性能瓶颈', '10万+条数据时匹配查询响应慢，影响用户体验', '中', 'FAISS 索引持久化 + 后台预匹配缓存 + 数据库索引优化 + 分页查询；已完成三算法融合和预匹配，预计可支撑 10万+ 数据量'],
            ['并发导入冲突', '多人同时导入同一文件导致数据重复或 race condition', '低', '文件哈希幂等（重复导入自动识别）+ 批次级锁 + 导入队列串行化'],
            ['FAISS 兼容性问题', 'FAISS 在 Windows 环境安装或运行异常', '低', '已集成 faiss-cpu，测试通过；FAISS_AVAILABLE 标志位，不可用时降级为 rapidfuzz + TF-IDF 双算法融合'],
            ['Python 版本升级', 'datetime.utcnow 等弃用 API 在未来版本移除', '低', '已完成 datetime 时区感知改造（17 处替换），全部使用 datetime.now(timezone.utc)'],
        ],
        col_widths=[4, 4, 1.5, 6.5])

    add_heading_styled(doc, '9.2 数据风险', 2)
    add_table(doc,
        ['风险', '影响', '概率', '应对措施'],
        [
            ['原始文件丢失', '不可重建的真相源丢失，无法审计对账', '低', '只读导入（机制保障）+ 导入即归档（ZIP 压缩）+ 归档完整性巡检 + 定期备份'],
            ['人工标注丢失', 'B 类字段（标准化结果）丢失，无法重建', '低', 'B 类字段禁静默覆盖（代码层 + 测试层）+ 硬删四道闸门（CSV 快照）+ 审计日志 append-only + 定期备份'],
            ['数据迁移丢失', 'Odoo → FastAPI 迁移过程中数据丢失或不一致', '中', '三重校验（行数一致 + B 类逐字段 diff + SHA256 校验和）+ 迁移前完整备份 + 迁移后抽样核对'],
            ['误删数据', '误操作导致批次或清单项被删除', '中', '软删除（回收站可还原）+ 30 天宽限期 + 硬删四道闸门（权限+名称确认+宽限+快照）'],
            ['数据库损坏', 'PostgreSQL 数据库文件损坏导致数据不可用', '低', '定期 pg_dump 备份 + 每季度备份恢复演练（未演练过的备份视为无效）+ 数据库层 REVOKE 保护审计日志'],
            ['敏感数据泄漏', '造价单价等商业敏感数据外泄', '低', '三角色权限 + 数据可见性控制（未登录仅已标准化数据）+ 导出需登录 + 导出留记录 + 生产环境 /docs 禁用 + Cookie httponly + HTTPS'],
        ],
        col_widths=[4, 4, 1.5, 6.5])

    add_heading_styled(doc, '9.3 业务风险', 2)
    add_table(doc,
        ['风险', '影响', '概率', '应对措施'],
        [
            ['匹配准确率不足', '三算法匹配候选不准确，人工确认工作量大', '中', '学习引擎 v3（越用越准）+ 高置信批量确认（≥90分）+ 手动添加学习记录 + 同义词自动扩展；预期 10万条数据下人工确认量从 100% 降至 10-20%'],
            ['用户 adoption 低', '团队成员不愿意使用新工具，数据沉淀不足', '中', '深空科技风格界面（干净、留白、字清楚）+ 作为公司网页嵌入（降低使用门槛）+ OA 统一登录（无需额外账号）+ 核心价值明确（报价查历史价秒级响应）'],
            ['数据质量不高', '导入的清单数据质量差，影响历史均价可信度', '中', '校验规则引擎（5 种类型/7 个模板/三级分级）+ 导入预览标记异常 + 数据质量仪表盘实时监控 + 数据性质标记（待审绝不混入历史均价）'],
            ['标准不统一', '不同工程师对同类项的标准化归类不一致', '低', '物料字典（三级分类 + 同义词 + 规格白名单）+ 学习引擎（根据确认结果自动调整）+ 字典维护 UI 可编辑 + 审计日志可追溯'],
            ['公司网页集成困难', '无法作为公司网页的一部分嵌入，团队访问不便', '低', '方案 A 前后端分离（Portal 页适合嵌入）+ Nginx 反向代理 + 子路径/子域名部署 + OA SSO 统一登录'],
        ],
        col_widths=[4, 4, 1.5, 6.5])

    doc.add_page_break()

    # ========== 十、总结与展望 ==========
    add_heading_styled(doc, '十、总结与展望', 1)

    add_heading_styled(doc, '10.1 项目总结', 2)
    add_para(doc, '造价数据门户项目从 2026 年 9 月 5 日启动，历经 4 天密集开发，已完成 M0-M4 全部核心功能、匹配效率优化（三算法融合 + 学习引擎 v3）、M2 导入服务深化（四大模块）、方案 A 前后端页面分离、生产环境安全加固等关键里程碑。')

    add_para(doc, '关键成果：', bold=True)
    add_para(doc, '• 93 个 Python 文件，6 张数据表，56 个 API 端点，11 个页面')
    add_para(doc, '• 512 条自动化测试全绿（pure_tests 236 + tests 276），零失败')
    add_para(doc, '• 三算法融合匹配引擎（rapidfuzz + TF-IDF + FAISS）+ 学习引擎 v3（五项核心能力）')
    add_para(doc, '• M2 导入深化四大模块（多格式解析 + 字段映射模板 + 校验规则引擎 + 归档增强）')
    add_para(doc, '• 方案 A 前后端分离（Portal 3 页 + Admin 8 页，三角色权限，数据可见性控制）')
    add_para(doc, '• 数据安全铁律全面落地（A/B/C 分层 + 原始文件只读 + 硬删四道闸门 + 审计 append-only）')
    add_para(doc, '• 生产环境安全加固（/docs 禁用 + Cookie httponly + datetime 时区感知）')

    add_heading_styled(doc, '10.2 核心优势', 2)
    add_table(doc,
        ['优势维度', '具体体现'],
        [
            ['技术选型合理', 'FastAPI + SQLAlchemy + PostgreSQL + Jinja2，AI 写代码质量高，维护成本低'],
            ['算法能力领先', '三算法融合 + 学习引擎 v3，匹配准确率随使用持续提升，人工确认量持续下降'],
            ['数据安全严谨', 'A/B/C 分层 + 原始文件只读 + 硬删四道闸门 + 审计 append-only，数据不可重建资产全面保护'],
            ['导入流程健壮', '多格式支持 + 字段映射模板 + 校验规则引擎 + 预览确认 + 归档压缩，确保数据质量'],
            ['用户体验优良', '深空科技风格 + 前后端分离 + 列宽调整 + 批量确认，每天愿意用'],
            ['团队协作友好', 'OA 统一登录 + 三角色权限 + 公司网页嵌入 + 数据可见性控制，团队共享无障碍'],
            ['测试保障充分', '512 条自动化测试 + 安全用例优先 + 代码审查 + 视觉基线，质量可控'],
            ['资产复用率高', '从 Odoo 版继承 720 行纯函数 + 业务契约 + 数据安全铁律，迁移成本低'],
        ],
        col_widths=[3, 13])

    add_heading_styled(doc, '10.3 下一步计划', 2)
    add_para(doc, '近期（2-3 周）：生产就绪', bold=True)
    add_para(doc, '• OA SSO 对接（待易达 ECMS 提供协议文档）')
    add_para(doc, '• 并发导入锁机制')
    add_para(doc, '• 大数据量（10万+）性能压测')
    add_para(doc, '• S7/N1-N3 自动化用例补齐')

    add_para(doc, '中期（1-2 月）：体验增强', bold=True)
    add_para(doc, '• 单价趋势图（ECharts 集成）')
    add_para(doc, '• 常用项收藏')
    add_para(doc, '• 标签分类')
    add_para(doc, '• 学习引擎持续优化（更多确认数据 → 更高准确率）')

    add_para(doc, '远期（按需）：生态扩展', bold=True)
    add_para(doc, '• 多库合并（支持多个数据库的合并与对比）')
    add_para(doc, '• 4D 排期（需外部 BIM 软件配合）')
    add_para(doc, '• 人材机分析（需引入可靠定额数据源）')
    add_para(doc, '• 移动端适配（响应式设计或独立 APP）')

    add_heading_styled(doc, '10.4 结语', 2)
    add_para(doc, '造价数据门户的核心价值在于「把散落的历史造价数据沉淀为可复用的企业资产」。通过严谨的数据安全机制、智能的匹配算法、健壮的导入流程和优良的用户体验，让造价工程师从「翻旧 Excel」的低效工作中解放出来，把更多时间投入到专业判断和价值创造上。')

    add_para(doc, '项目已具备内部试用条件，建议尽快启动 OA SSO 对接，进入生产就绪阶段。随着使用数据的积累，学习引擎将持续优化匹配准确率，系统将越用越聪明，真正成为造价团队不可或缺的日常工具。', bold=True)

    # 保存文档
    output_path = r'E:\DEEPSEEK学习\zaojia_fastapi\造价数据门户产品方案_v1.0.docx'
    doc.save(output_path)
    print(f'文档已生成：{output_path}')


if __name__ == '__main__':
    main()
