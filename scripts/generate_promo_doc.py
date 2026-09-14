# -*- coding: utf-8 -*-
"""造价数据门户宣传文稿生成脚本。

生成包含架构图、流程图、示意图的 Word 宣传文稿。
"""
import os
import sys
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

from docx import Document
from docx.shared import Inches, Pt, RGBColor, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn

# 配置中文字体
plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'Arial Unicode MS']
plt.rcParams['axes.unicode_minus'] = False

OUTPUT_DIR = Path(__file__).parent.parent / "deliverables" / "promo"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
IMG_DIR = OUTPUT_DIR / "images"
IMG_DIR.mkdir(parents=True, exist_ok=True)


def draw_box(ax, x, y, w, h, text, color="#4D7CFE", text_color="white", fontsize=10, alpha=0.9):
    """绘制圆角方框。"""
    box = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.1",
                          facecolor=color, edgecolor="#2C5FE0", linewidth=1.5, alpha=alpha)
    ax.add_patch(box)
    ax.text(x + w/2, y + h/2, text, ha='center', va='center',
            fontsize=fontsize, color=text_color, fontweight='bold', wrap=True)


def draw_arrow(ax, x1, y1, x2, y2, color="#666", style="->", lw=1.5):
    """绘制箭头。"""
    arrow = FancyArrowPatch((x1, y1), (x2, y2), arrowstyle=style,
                            mutation_scale=15, color=color, linewidth=lw)
    ax.add_patch(arrow)


def generate_architecture_diagram():
    """生成系统架构图。"""
    fig, ax = plt.subplots(figsize=(12, 8))
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 10)
    ax.axis('off')
    ax.set_title('造价数据门户 · 系统架构', fontsize=16, fontweight='bold', pad=20, color='#1a1a2e')

    # OA 层
    draw_box(ax, 4, 8.8, 4, 0.8, "公司 OA（易达 ECMS）—— 统一登录源", color="#16213e", fontsize=11)
    draw_arrow(ax, 6, 8.8, 6, 8.2, color="#4D7CFE", lw=2)

    # FastAPI 应用层
    draw_box(ax, 1, 6.5, 10, 1.5, "FastAPI 应用（zaojia_fastapi）", color="#0f3460", fontsize=13)

    # 子模块
    draw_box(ax, 1.3, 5.2, 2.2, 1.0, "Portal 展示页\n/portal/* (3页)", color="#4D7CFE", fontsize=9)
    draw_box(ax, 3.8, 5.2, 2.2, 1.0, "Admin 管理页\n/admin/* (8页)", color="#4D7CFE", fontsize=9)
    draw_box(ax, 6.3, 5.2, 2.2, 1.0, "REST API\n/api/*", color="#4D7CFE", fontsize=9)
    draw_box(ax, 8.8, 5.2, 2.0, 1.0, "静态资源\n/static/*", color="#4D7CFE", fontsize=9)

    # Service 层
    draw_box(ax, 1, 3.8, 10, 1.0, "Service 层（业务逻辑）：import / query / price / match / audit / archive / upsert / batch / material_match / data_quality / cost_catalog / evidence / prematch / learning_engine(v2/v3)", color="#e94560", fontsize=8)

    # 模型层
    draw_box(ax, 1, 2.5, 10, 1.0, "SQLAlchemy 模型（10 表）：boq_item / import_batch / material_dict / audit_log / match_cache / cost_catalog / tag / item_tag / user_favorite / alembic_version", color="#533483", fontsize=8)

    # 数据层
    draw_box(ax, 3, 0.8, 3, 1.0, "PostgreSQL 15\n业务数据（权威）", color="#1a1a2e", fontsize=10)
    draw_box(ax, 7, 0.8, 3, 1.0, "归档存储\n原始 Excel（只读）", color="#1a1a2e", fontsize=10)

    # 连接线
    draw_arrow(ax, 6, 6.5, 6, 6.3, color="#666", lw=1)
    draw_arrow(ax, 6, 5.2, 6, 4.9, color="#666", lw=1)
    draw_arrow(ax, 6, 3.8, 6, 3.6, color="#666", lw=1)
    draw_arrow(ax, 4.5, 2.5, 4.5, 1.9, color="#666", lw=1)
    draw_arrow(ax, 8.5, 2.5, 8.5, 1.9, color="#666", lw=1)

    plt.tight_layout()
    path = IMG_DIR / "architecture.png"
    plt.savefig(path, dpi=150, bbox_inches='tight', facecolor='white')
    plt.close()
    return path


def generate_import_flow():
    """生成数据导入流程图。"""
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 6)
    ax.axis('off')
    ax.set_title('数据导入流程 · 只读导入 + 分层 Upsert + 归档溯源', fontsize=14, fontweight='bold', pad=15, color='#1a1a2e')

    steps = [
        (0.5, "原始 Excel\n（真相源）", "#16213e"),
        (2.5, "只读解析\n(read_only=True)", "#0f3460"),
        (4.5, "字段映射\n+ 校验规则", "#4D7CFE"),
        (6.5, "预览不写库\n（确认才入库）", "#e94560"),
        (8.5, "分层 Upsert\n(A可覆盖/B禁静默)", "#533483"),
        (10.5, "归档 + 审计\n（逐字溯源）", "#1a1a2e"),
    ]

    for i, (x, text, color) in enumerate(steps):
        draw_box(ax, x, 2.2, 1.6, 1.4, text, color=color, fontsize=9)
        if i < len(steps) - 1:
            draw_arrow(ax, x + 1.6, 2.9, x + 2.5, 2.9, color="#4D7CFE", lw=2)

    # 底部说明
    ax.text(6, 1.0, "安全铁律：源文件只读 · B类字段禁静默覆盖 · 审计四元组 · 归档SHA256校验",
            ha='center', va='center', fontsize=11, color='#e94560', fontweight='bold')
    ax.text(6, 0.4, "支持格式：xlsx / xlsm / xls / csv  ·  魔数校验防伪造  ·  60MB文件大小限制",
            ha='center', va='center', fontsize=10, color='#666')

    plt.tight_layout()
    path = IMG_DIR / "import_flow.png"
    plt.savefig(path, dpi=150, bbox_inches='tight', facecolor='white')
    plt.close()
    return path


def generate_match_flow():
    """生成智能匹配流程图。"""
    fig, ax = plt.subplots(figsize=(12, 7))
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 8)
    ax.axis('off')
    ax.set_title('智能匹配流程 · 三算法融合 + 学习引擎 · 越用越准', fontsize=14, fontweight='bold', pad=15, color='#1a1a2e')

    # 输入
    draw_box(ax, 4.5, 6.8, 3, 0.8, "待匹配清单项\n（名称/特征/单位）", color="#16213e", fontsize=10)
    draw_arrow(ax, 6, 6.8, 6, 6.2, color="#4D7CFE", lw=2)

    # 三算法
    draw_box(ax, 0.5, 4.5, 3, 1.2, "rapidfuzz\n字符串相似度", color="#4D7CFE", fontsize=10)
    draw_box(ax, 4.5, 4.5, 3, 1.2, "TF-IDF\n语义匹配", color="#e94560", fontsize=10)
    draw_box(ax, 8.5, 4.5, 3, 1.2, "FAISS\n向量检索", color="#533483", fontsize=10)

    draw_arrow(ax, 2, 4.5, 4, 3.8, color="#666", lw=1.5)
    draw_arrow(ax, 6, 4.5, 6, 3.8, color="#666", lw=1.5)
    draw_arrow(ax, 10, 4.5, 8, 3.8, color="#666", lw=1.5)

    # 融合
    draw_box(ax, 4, 2.8, 4, 0.9, "学习引擎权重自适应\n（v2/v3：概念漂移/多策略/元学习）", color="#0f3460", fontsize=9)
    draw_arrow(ax, 6, 2.8, 6, 2.2, color="#4D7CFE", lw=2)

    # 输出
    draw_box(ax, 3.5, 1.0, 2, 0.9, "候选推荐\n（Top-N）", color="#4D7CFE", fontsize=10)
    draw_box(ax, 6.5, 1.0, 2, 0.9, "人工确认\n（批量确认）", color="#e94560", fontsize=10)

    draw_arrow(ax, 4.5, 1.0, 6.5, 1.0, color="#666", lw=1.5)

    # 反馈循环
    draw_arrow(ax, 7.5, 1.9, 10.5, 3.0, color="#22D3EE", lw=2, style="<->")
    ax.text(10.8, 2.5, "确认结果\n反馈学习", ha='left', va='center', fontsize=9, color="#22D3EE", fontweight='bold')

    # 效果
    ax.text(6, 0.3, "预期效果：10万条数据下，人工确认量从 100% 降至 10-20%",
            ha='center', va='center', fontsize=11, color='#e94560', fontweight='bold')

    plt.tight_layout()
    path = IMG_DIR / "match_flow.png"
    plt.savefig(path, dpi=150, bbox_inches='tight', facecolor='white')
    plt.close()
    return path


def generate_security_diagram():
    """生成安全保障示意图。"""
    fig, ax = plt.subplots(figsize=(12, 8))
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 9)
    ax.axis('off')
    ax.set_title('数据安全保障 · 第一性原理：原始Excel与人工标注不可重建', fontsize=14, fontweight='bold', pad=15, color='#1a1a2e')

    security_items = [
        (0.5, 7.0, "S1 源文件只读", "导入代码不得对源文件\n调用 wb.save()"),
        (3.5, 7.0, "S4 B类禁静默覆盖", "人工标注资产\n需显式理由才能修改"),
        (6.5, 7.0, "S5 审计完整", "所有写操作有审计记录\n四元组 append-only"),
        (9.5, 7.0, "S7 待审不污染", "price_service 仅统计\ncompleted 域"),
        (0.5, 4.5, "硬删闸门 fail-closed", "CSV快照失败时\n物理删除必须被拒绝"),
        (3.5, 4.5, "30天回收站宽限", "软删后30天内\n禁止硬删"),
        (6.5, 4.5, "三角色权限", "admin/estimator/viewer\n字段级只读"),
        (9.5, 4.5, "S8 备份恢复演练", "每季度自动化验证\n临时库pg_restore+抽样"),
        (2, 2.0, "Alembic 版本化迁移", "schema变更可回滚\n可审计、可重复执行"),
        (5, 2.0, "GitHub Actions CI", "3 job自动回归\n纯函数/集成/安全用例"),
        (8, 2.0, "551 条全量测试", "纯函数236+集成315\n零失败"),
    ]

    for x, y, title, desc in security_items:
        draw_box(ax, x, y, 2.5, 1.8, f"{title}\n\n{desc}", color="#e94560", fontsize=8)

    ax.text(6, 0.8, "安全用例 S1-S9 优先级高于功能用例 · 任一失败即整体不通过",
            ha='center', va='center', fontsize=12, color='#e94560', fontweight='bold')

    plt.tight_layout()
    path = IMG_DIR / "security.png"
    plt.savefig(path, dpi=150, bbox_inches='tight', facecolor='white')
    plt.close()
    return path


def generate_product_overview():
    """生成产品功能概览图。"""
    fig, ax = plt.subplots(figsize=(12, 7))
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 8)
    ax.axis('off')
    ax.set_title('产品功能概览 · Portal 展示 + Admin 管理', fontsize=14, fontweight='bold', pad=15, color='#1a1a2e')

    # Portal
    draw_box(ax, 0.5, 5.5, 5, 0.8, "Portal 展示页（团队共享查询）", color="#0f3460", fontsize=12)
    portal_items = [
        (0.8, "数据概览\nKPI卡片/统计"),
        (2.5, "清单检索\n关键词/多条件筛选"),
        (4.2, "单价分析\nECharts趋势图"),
    ]
    for x, text in portal_items:
        draw_box(ax, x, 3.8, 1.5, 1.2, text, color="#4D7CFE", fontsize=9)

    # Admin
    draw_box(ax, 6.5, 5.5, 5, 0.8, "Admin 管理页（造价师/管理员）", color="#16213e", fontsize=12)
    admin_items = [
        (6.8, "导入向导\n预览/校验/确认"),
        (8.5, "批次管理\n软删/还原/硬删"),
        (10.2, "匹配确认\n候选/批量/学习"),
        (6.8, 1.8, "物料字典\n分类/全局共享"),
        (8.5, 1.8, "数据质量\n异常/质量评分"),
        (10.2, 1.8, "系统设置\n角色/参数"),
    ]
    for item in admin_items:
        if len(item) == 3:
            x, y, text = item
        else:
            x, text = item
            y = 3.8
        draw_box(ax, x, y, 1.5, 1.2, text, color="#e94560", fontsize=9)

    # 体验增强
    draw_box(ax, 3, 0.3, 6, 0.9, "体验增强：常用项收藏 · 标签分类 · 列宽可调 · 批量操作", color="#533483", fontsize=10)

    plt.tight_layout()
    path = IMG_DIR / "product_overview.png"
    plt.savefig(path, dpi=150, bbox_inches='tight', facecolor='white')
    plt.close()
    return path


def add_heading(doc, text, level=1, color=None):
    """添加标题。"""
    heading = doc.add_heading(text, level=level)
    if color:
        for run in heading.runs:
            run.font.color.rgb = color
    return heading


def add_paragraph(doc, text, bold=False, size=None, color=None, align=None):
    """添加段落。"""
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.bold = bold
    if size:
        run.font.size = Pt(size)
    if color:
        run.font.color.rgb = color
    if align:
        p.alignment = align
    return p


def add_image(doc, img_path, width=Inches(6.0)):
    """添加图片。"""
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run()
    run.add_picture(str(img_path), width=width)


def generate_word_doc():
    """生成 Word 宣传文稿。"""
    doc = Document()

    # 设置默认字体
    style = doc.styles['Normal']
    font = style.font
    font.name = '微软雅黑'
    font.size = Pt(11)
    style.element.rPr.rFonts.set(qn('w:eastAsia'), '微软雅黑')

    # ===== 封面 =====
    for _ in range(4):
        doc.add_paragraph()

    add_paragraph(doc, "造价数据门户", bold=True, size=36,
                   color=RGBColor(0x16, 0x21, 0x3e), align=WD_ALIGN_PARAGRAPH.CENTER)
    add_paragraph(doc, "让每一条历史单价都可复用", bold=True, size=20,
                   color=RGBColor(0x4D, 0x7C, 0xFE), align=WD_ALIGN_PARAGRAPH.CENTER)

    doc.add_paragraph()
    add_paragraph(doc, "—— 团队成本资产的沉淀与复用平台 ——", size=14,
                   color=RGBColor(0x66, 0x66, 0x66), align=WD_ALIGN_PARAGRAPH.CENTER)

    for _ in range(6):
        doc.add_paragraph()

    add_paragraph(doc, "FastAPI + PostgreSQL + 三算法融合匹配 + 学习引擎", size=12,
                   color=RGBColor(0x99, 0x99, 0x99), align=WD_ALIGN_PARAGRAPH.CENTER)
    add_paragraph(doc, "v1.0  ·  2026年9月", size=11,
                   color=RGBColor(0x99, 0x99, 0x99), align=WD_ALIGN_PARAGRAPH.CENTER)

    doc.add_page_break()

    # ===== 目录 =====
    add_heading(doc, "目录", level=1, color=RGBColor(0x16, 0x21, 0x3e))
    toc_items = [
        "一、产品定位：我们是干什么的",
        "二、核心功能",
        "三、系统架构",
        "四、数据导入流程",
        "五、智能匹配与学习引擎",
        "六、数据安全保障",
        "七、主要优势",
        "八、未来规划：后面想干什么",
        "九、总结",
    ]
    for item in toc_items:
        add_paragraph(doc, item, size=12)

    doc.add_page_break()

    # ===== 一、产品定位 =====
    add_heading(doc, "一、产品定位：我们是干什么的", level=1, color=RGBColor(0x16, 0x21, 0x3e))

    add_paragraph(doc, "造价数据门户是面向造价咨询团队的「工程量清单历史单价数据门户」。", size=12)
    doc.add_paragraph()

    add_paragraph(doc, "核心回答一个问题：", bold=True, size=13, color=RGBColor(0x4D, 0x7C, 0xFE))
    add_paragraph(doc, "「这个清单项，我们以前做过多少钱？」", bold=True, size=15,
                   color=RGBColor(0xe9, 0x45, 0x60), align=WD_ALIGN_PARAGRAPH.CENTER)
    doc.add_paragraph()

    add_paragraph(doc, "我们把散落在各工程 Excel 里的清单项，沉淀为团队可检索、可复用、可审计的成本资产。", size=12)
    doc.add_paragraph()

    add_heading(doc, "痛点分析", level=2, color=RGBColor(0x0f, 0x34, 0x60))
    pains = [
        "找得到文件，找不到数据：知道「去年那个项目做过」，但翻遍文件夹也找不到具体那条清单项的单价",
        "Excel 越积越多，复用率越来越低：新人入职看不到老项目的单价沉淀，老人离职经验跟着走",
        "人工标注不可重建：花大量时间做的物料匹配、标准化标注，散落在个人电脑里，文件丢失就再也找不回",
        "数据安全无保障：原始 Excel 随意拷贝、覆盖、删除，出了问题无法追溯",
        "团队协作靠微信传文件：A 改了一版，B 还在用旧版，版本混乱",
    ]
    for pain in pains:
        p = doc.add_paragraph(style='List Bullet')
        p.add_run(pain)

    doc.add_page_break()

    # ===== 二、核心功能 =====
    add_heading(doc, "二、核心功能", level=1, color=RGBColor(0x16, 0x21, 0x3e))

    add_image(doc, generate_product_overview(), width=Inches(6.2))
    add_paragraph(doc, "图：产品功能概览", size=10, color=RGBColor(0x99, 0x99, 0x99),
                   align=WD_ALIGN_PARAGRAPH.CENTER)
    doc.add_paragraph()

    add_heading(doc, "Portal 展示页（团队共享查询）", level=2, color=RGBColor(0x0f, 0x34, 0x60))
    portal_features = [
        "数据概览：KPI 卡片、数据总量、标准化进度、异常统计",
        "清单检索：关键词搜索、多条件筛选、列宽可调、一次性预览全部内容",
        "单价分析：同类项聚合统计、ECharts 交互式单价趋势图、质量仪表盘",
    ]
    for f in portal_features:
        p = doc.add_paragraph(style='List Bullet')
        p.add_run(f)

    add_paragraph(doc, "未登录用户可查询已标准化数据，登录后可查看全部数据。", size=11,
                   color=RGBColor(0x66, 0x66, 0x66))
    doc.add_paragraph()

    add_heading(doc, "Admin 管理页（造价师/管理员）", level=2, color=RGBColor(0x16, 0x21, 0x3e))
    admin_features = [
        "导入向导：预览不写库、确认才入库、校验报告实时展示",
        "批次管理：批次列表、详情查看、软删/还原/硬删（30天宽限+CSV快照）",
        "匹配确认：候选推荐、人工确认、批量确认、手动添加+学习记录",
        "物料字典：分类管理、新增/编辑、全局共享",
        "数据质量：异常标记、质量评分、待处理清单",
        "系统设置：角色权限、参数配置",
    ]
    for f in admin_features:
        p = doc.add_paragraph(style='List Bullet')
        p.add_run(f)

    doc.add_paragraph()
    add_heading(doc, "体验增强", level=2, color=RGBColor(0x53, 0x34, 0x83))
    extra_features = [
        "常用项收藏：个人收藏高频清单项，快速访问",
        "标签分类：自定义标签，按标签筛选条目，全局标签+用户级隔离",
        "批量操作：异常确认、数据性质切换，B 类字段走 reason+审计通道",
        "列宽可调：检索结果列宽可调整，尽量一次性预览全部内容",
    ]
    for f in extra_features:
        p = doc.add_paragraph(style='List Bullet')
        p.add_run(f)

    doc.add_page_break()

    # ===== 三、系统架构 =====
    add_heading(doc, "三、系统架构", level=1, color=RGBColor(0x16, 0x21, 0x3e))

    add_image(doc, generate_architecture_diagram(), width=Inches(6.2))
    add_paragraph(doc, "图：系统架构图", size=10, color=RGBColor(0x99, 0x99, 0x99),
                   align=WD_ALIGN_PARAGRAPH.CENTER)
    doc.add_paragraph()

    add_heading(doc, "技术栈", level=2, color=RGBColor(0x0f, 0x34, 0x60))

    table = doc.add_table(rows=1, cols=2)
    table.style = 'Light Grid Accent 1'
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    hdr_cells = table.rows[0].cells
    hdr_cells[0].text = '层级'
    hdr_cells[1].text = '技术选型'

    tech_stack = [
        ("Web 框架", "FastAPI 0.141（异步高性能、自动 OpenAPI 文档）"),
        ("ORM", "SQLAlchemy 2.0（成熟稳定、显式事务）"),
        ("数据库迁移", "Alembic 1.19（版本化、可回滚）"),
        ("数据库", "PostgreSQL 15+（numeric 精确，无 SQLite REAL 退化）"),
        ("模板引擎", "Jinja2（服务端渲染，维护成本低）"),
        ("前端", "深空科技设计系统 + ECharts 5.5 交互图表"),
        ("匹配算法", "rapidfuzz + TF-IDF + FAISS 三算法融合"),
        ("学习引擎", "v2 + v3（概念漂移检测、多策略集成、元学习自动调参）"),
        ("测试", "pytest（551 条全量测试）"),
        ("CI", "GitHub Actions（3 job 自动回归）"),
    ]
    for layer, tech in tech_stack:
        row_cells = table.add_row().cells
        row_cells[0].text = layer
        row_cells[1].text = tech

    doc.add_paragraph()
    add_heading(doc, "前后端分离（方案 A）", level=2, color=RGBColor(0x0f, 0x34, 0x60))
    add_paragraph(doc, "Portal 展示页（/portal/*，3 页）：可选登录，未登录仅已标准化数据可见", size=11)
    add_paragraph(doc, "Admin 管理页（/admin/*，8 页）：必须登录 + 角色校验", size=11)
    add_paragraph(doc, "旧路由 301 重定向，平滑过渡；可作为公司网页子路径/子域名嵌入", size=11)

    doc.add_page_break()

    # ===== 四、数据导入流程 =====
    add_heading(doc, "四、数据导入流程", level=1, color=RGBColor(0x16, 0x21, 0x3e))

    add_image(doc, generate_import_flow(), width=Inches(6.2))
    add_paragraph(doc, "图：数据导入流程图", size=10, color=RGBColor(0x99, 0x99, 0x99),
                   align=WD_ALIGN_PARAGRAPH.CENTER)
    doc.add_paragraph()

    add_heading(doc, "只读导入", level=2, color=RGBColor(0x0f, 0x34, 0x60))
    add_paragraph(doc, "原始 Excel 以 read_only=True 方式打开，绝不改写源文件。导入后自动归档，逐字溯源。", size=12)
    doc.add_paragraph()

    add_heading(doc, "多格式解析", level=2, color=RGBColor(0x0f, 0x34, 0x60))
    formats = [
        "支持 xlsx / xlsm / xls / csv 多格式解析",
        "魔数校验防伪造（扩展名伪造会被拒收）",
        "60MB 文件大小限制（超限返回 413）",
        ".xlsm 含宏文件支持只读解析（不执行宏）",
    ]
    for f in formats:
        p = doc.add_paragraph(style='List Bullet')
        p.add_run(f)

    doc.add_paragraph()
    add_heading(doc, "字段映射 + 校验规则", level=2, color=RGBColor(0x0f, 0x34, 0x60))
    add_paragraph(doc, "13 个标准字段（含暂估价），字段映射模板自动推荐，用户可手动调整并保存模板。", size=12)
    add_paragraph(doc, "5 种校验类型 / 7 个模板 / 三级分级，导入预览时展示校验报告。", size=12)
    doc.add_paragraph()

    add_heading(doc, "分层 Upsert（核心安全机制）", level=2, color=RGBColor(0xe9, 0x45, 0x60))
    add_paragraph(doc, "A 类（可重建）：从原始文件解析出的派生物，允许覆盖。", size=12)
    add_paragraph(doc, "B 类（不可重建）：人工标注资产（std_name / std_spec / material_dict_id 等），绝不静默覆盖，需显式理由。", size=12)
    add_paragraph(doc, "C 类（系统元数据）：write_date / active 等。", size=12)

    doc.add_page_break()

    # ===== 五、智能匹配与学习引擎 =====
    add_heading(doc, "五、智能匹配与学习引擎", level=1, color=RGBColor(0x16, 0x21, 0x3e))

    add_image(doc, generate_match_flow(), width=Inches(6.2))
    add_paragraph(doc, "图：智能匹配流程图", size=10, color=RGBColor(0x99, 0x99, 0x99),
                   align=WD_ALIGN_PARAGRAPH.CENTER)
    doc.add_paragraph()

    add_heading(doc, "三算法融合", level=2, color=RGBColor(0x0f, 0x34, 0x60))
    algorithms = [
        "rapidfuzz：字符串相似度（基础召回）",
        "TF-IDF：语义匹配（关键词权重）",
        "FAISS：向量检索（语义相似度，毫秒级）",
    ]
    for a in algorithms:
        p = doc.add_paragraph(style='List Bullet')
        p.add_run(a)

    doc.add_paragraph()
    add_heading(doc, "学习引擎 v2/v3", level=2, color=RGBColor(0x53, 0x34, 0x83))
    learning = [
        "v2：概念漂移检测、多策略集成、权重持久化",
        "v3：元学习自动调参、主动学习、置信度校准",
        "每次人工确认后自动调整三算法权重",
        "确认结果反馈学习，越用越准",
    ]
    for l in learning:
        p = doc.add_paragraph(style='List Bullet')
        p.add_run(l)

    doc.add_paragraph()
    add_heading(doc, "后台预匹配", level=2, color=RGBColor(0x0f, 0x34, 0x60))
    add_paragraph(doc, "导入完成后异步计算，匹配从「实时算」变「预计算+查缓存」，大幅提升响应速度。", size=12)
    doc.add_paragraph()

    add_heading(doc, "预期效果", level=2, color=RGBColor(0xe9, 0x45, 0x60))
    add_paragraph(doc, "10 万条数据下，人工确认量从 100% 降至 10-20%。", bold=True, size=14,
                   color=RGBColor(0xe9, 0x45, 0x60), align=WD_ALIGN_PARAGRAPH.CENTER)

    doc.add_page_break()

    # ===== 六、数据安全保障 =====
    add_heading(doc, "六、数据安全保障", level=1, color=RGBColor(0x16, 0x21, 0x3e))

    add_image(doc, generate_security_diagram(), width=Inches(6.2))
    add_paragraph(doc, "图：数据安全保障体系", size=10, color=RGBColor(0x99, 0x99, 0x99),
                   align=WD_ALIGN_PARAGRAPH.CENTER)
    doc.add_paragraph()

    add_paragraph(doc, "第一性原理：原始 Excel 与人工标注是不可重建的真相源，数据库只是有损派生物。",
                   bold=True, size=12, color=RGBColor(0xe9, 0x45, 0x60))
    doc.add_paragraph()

    add_heading(doc, "S1–S9 安全用例", level=2, color=RGBColor(0x0f, 0x34, 0x60))
    security_cases = [
        "S1 源文件只读：导入代码不得对源文件调用 wb.save()",
        "S2 归档完整性：归档文件 SHA256 与源一致",
        "S3 A 类可覆盖：从原始文件解析出的派生物，允许覆盖",
        "S4 B 类禁静默覆盖：人工标注资产，需显式理由才能修改",
        "S5 审计完整：所有写操作有审计记录，四元组 append-only",
        "S6 归档幂等：重复归档不产生重复文件",
        "S7 待审不污染：price_service 仅统计 completed 域",
        "S8 备份恢复演练：每季度自动化验证（临时库 pg_restore + 抽样校验）",
        "S9 审计四元组：operator/reason/trace_id/timestamp 非空",
    ]
    for s in security_cases:
        p = doc.add_paragraph(style='List Bullet')
        p.add_run(s)

    doc.add_paragraph()
    add_heading(doc, "硬删闸门（fail-closed）", level=2, color=RGBColor(0xe9, 0x45, 0x60))
    hard_delete = [
        "硬删前必须导出 CSV 快照",
        "快照导出失败时，物理删除必须被拒绝（不得放行）",
        "30 天回收站宽限期",
        "管理员 + 名称二次确认 + CSV 快照先行",
        "6 项自动化测试覆盖，回归即可击穿",
    ]
    for h in hard_delete:
        p = doc.add_paragraph(style='List Bullet')
        p.add_run(h)

    doc.add_paragraph()
    add_heading(doc, "权限体系", level=2, color=RGBColor(0x0f, 0x34, 0x60))
    add_paragraph(doc, "三角色：admin（全部权限）/ estimator（查询+匹配+字典+批次）/ viewer（只读，禁导出）", size=12)
    add_paragraph(doc, "字段级只读：B 类字段无 reason 拒绝写入", size=12)
    add_paragraph(doc, "数据可见性：未登录用户仅能看到已标准化数据", size=12)
    add_paragraph(doc, "OA 统一登录：易达 ECMS SSO 对接方案已完成，生产期由 OA 用户部门/职位自动映射角色", size=12)

    doc.add_page_break()

    # ===== 七、主要优势 =====
    add_heading(doc, "七、主要优势", level=1, color=RGBColor(0x16, 0x21, 0x3e))

    advantages = [
        ("数据安全第一", "原始 Excel 只读导入、B 类字段禁静默覆盖、审计四元组 append-only、硬删闸门 fail-closed、S1-S9 安全用例优先级高于功能用例。数据不可重建，安全是第一天的设计。"),
        ("智能匹配越用越准", "三算法融合（rapidfuzz+TF-IDF+FAISS）+ 学习引擎 v2/v3（概念漂移/多策略/元学习），每次人工确认后自动调整权重，10 万条数据下人工确认量从 100% 降至 10-20%。"),
        ("团队共享协作", "Portal 展示页支持未登录查询已标准化数据，Admin 管理页支持多角色协作，物料字典全局共享，匹配确认结果实时同步，经验沉淀不流失。"),
        ("可嵌入公司网页", "方案 A 前后端分离，可作为公司网页子路径/子域名嵌入，展示专业能力。OA 统一登录对接方案已完成，生产期由 OA 自动映射角色。"),
        ("技术栈主流可靠", "FastAPI + PostgreSQL + SQLAlchemy + Alembic，技术栈主流，AI 写代码质量高，维护成本低。551 条全量测试，GitHub Actions CI 自动回归。"),
        ("工程化保障", "Alembic 版本化迁移（schema 变更可回滚）、CI 持续集成、全量测试覆盖、S8 备份恢复自动化验证，工程化体系完整。"),
        ("纯函数层资产复用", "720 行纯函数从零框架依赖，从 Odoo 版原样复用，资产复用率 ~80%，236 条纯函数测试作为回归基线。"),
        ("体验增强", "常用项收藏、标签分类、列宽可调、批量操作、ECharts 交互趋势图，用户体验持续优化。"),
    ]

    for title, desc in advantages:
        add_heading(doc, title, level=2, color=RGBColor(0x4D, 0x7C, 0xFE))
        add_paragraph(doc, desc, size=11)
        doc.add_paragraph()

    doc.add_page_break()

    # ===== 八、未来规划 =====
    add_heading(doc, "八、未来规划：后面想干什么", level=1, color=RGBColor(0x16, 0x21, 0x3e))

    add_heading(doc, "近期（1-2 个月）", level=2, color=RGBColor(0x0f, 0x34, 0x60))
    near_term = [
        "OA SSO 对接：易达 ECMS 统一登录对接，替换开发期 dev_token，生产期由 OA 用户部门/职位自动映射角色",
        "数据迁移：Odoo 版 zaojia_db 数据 ETL 至新库，三重校验（行数/B 类逐字段/SHA256）",
        "S7/N1-N3 自动化用例补齐：待审不污染 + 反向用例（.xlsm拒收/60MB超限/归档失败中止）",
        "并发导入锁机制：文件哈希幂等 + 批次级锁",
        "大数据量（10万+）性能压测：FAISS 索引持久化 + 查询性能优化",
    ]
    for item in near_term:
        p = doc.add_paragraph(style='List Bullet')
        p.add_run(item)

    doc.add_paragraph()
    add_heading(doc, "中期（3-6 个月）", level=2, color=RGBColor(0x0f, 0x34, 0x60))
    mid_term = [
        "单价趋势图增强：ECharts 交互版 + 时间维度聚合 + 多项目对比",
        "常用项收藏 + 标签分类深化：个人/团队收藏、多级标签、标签云",
        "多库合并：支持多个项目数据库合并查询，跨项目单价对比",
        "人材机分析：人工/材料/机械单价分析，成本结构拆解",
        "4D 排期：单价数据与项目进度关联，动态成本预测",
        "移动端适配：响应式设计，支持手机/平板查询",
    ]
    for item in mid_term:
        p = doc.add_paragraph(style='List Bullet')
        p.add_run(item)

    doc.add_paragraph()
    add_heading(doc, "远期（6 个月以上）", level=2, color=RGBColor(0x0f, 0x34, 0x60))
    long_term = [
        "AI 智能报价：基于历史数据自动生成报价建议，置信度标注",
        "市场价格对接：对接建材市场价格 API，实时价格预警",
        "知识图谱：清单项-材料-工艺-项目知识图谱，智能关联推荐",
        "BIM 集成：与 BIM 模型对接，模型构件直接关联单价数据",
        "行业基准：匿名化行业基准对比，了解自身报价水平在行业中的位置",
    ]
    for item in long_term:
        p = doc.add_paragraph(style='List Bullet')
        p.add_run(item)

    doc.add_page_break()

    # ===== 九、总结 =====
    add_heading(doc, "九、总结", level=1, color=RGBColor(0x16, 0x21, 0x3e))

    doc.add_paragraph()
    add_paragraph(doc, "造价数据门户不是又一个 Excel 管理工具，而是团队成本资产的沉淀与复用平台。",
                   bold=True, size=13, color=RGBColor(0x4D, 0x7C, 0xFE))
    doc.add_paragraph()

    add_paragraph(doc, "它解决的核心问题是：", size=12)
    add_paragraph(doc, "让历史单价从「沉睡在硬盘里的 Excel」变成「团队可检索、可复用、可审计的成本资产」。",
                   bold=True, size=14, color=RGBColor(0xe9, 0x45, 0x60), align=WD_ALIGN_PARAGRAPH.CENTER)
    doc.add_paragraph()

    add_heading(doc, "对不同角色的价值", level=2, color=RGBColor(0x0f, 0x34, 0x60))

    table = doc.add_table(rows=1, cols=2)
    table.style = 'Light Grid Accent 1'
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    hdr_cells = table.rows[0].cells
    hdr_cells[0].text = '角色'
    hdr_cells[1].text = '价值'

    values = [
        ("造价师", "报价有据可依，不用再翻文件夹；匹配确认越用越准，人工工作量持续下降"),
        ("团队管理者", "经验沉淀不流失，新人上手快；数据安全有保障，操作可追溯"),
        ("IT 部门", "技术栈主流（FastAPI+PostgreSQL），安全有保障，可对接 OA 统一登录"),
        ("公司", "可作为公司网页的一部分，展示专业能力；成本资产持续积累，形成核心竞争力"),
    ]
    for role, value in values:
        row_cells = table.add_row().cells
        row_cells[0].text = role
        row_cells[1].text = value

    doc.add_paragraph()
    doc.add_paragraph()
    add_paragraph(doc, "每一条历史单价，都值得被复用。", bold=True, size=18,
                   color=RGBColor(0x16, 0x21, 0x3e), align=WD_ALIGN_PARAGRAPH.CENTER)
    doc.add_paragraph()
    add_paragraph(doc, "—— 造价数据门户 · 让成本资产流动起来 ——", size=12,
                   color=RGBColor(0x99, 0x99, 0x99), align=WD_ALIGN_PARAGRAPH.CENTER)

    # 保存
    output_path = OUTPUT_DIR / "造价数据门户宣传文稿_v1.0.docx"
    doc.save(str(output_path))
    return output_path


if __name__ == "__main__":
    print("生成图片素材...")
    generate_architecture_diagram()
    generate_import_flow()
    generate_match_flow()
    generate_security_diagram()
    generate_product_overview()
    print("图片素材生成完成")

    print("生成 Word 宣传文稿...")
    output = generate_word_doc()
    print(f"Word 宣传文稿已生成：{output}")
    print(f"文件大小：{output.stat().st_size / 1024:.1f} KB")
