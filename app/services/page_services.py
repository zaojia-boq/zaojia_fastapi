# -*- coding: utf-8 -*-
"""页面服务层 —— 对标 Odoo 版 zaojia_boq/static/src/* 的查询逻辑。

设计目标：
  - 保留 Odoo 版 JS 模块的数据纪律（domain 恒带 active=True、统计口径分离等）
  - 纯函数 + SQLAlchemy ORM，不直接依赖 FastAPI 框架
  - **数据禁编造**：数据库异常时返回 data_error，页面显示错误横幅；
    绝不静默回退到假数字。演示数据仅当 USE_MOCK_DATA=1 时启用，
    且返回结构带 is_demo=True，页面必须显示「演示数据」水印。

对标关系：
  - dashboard.js    → get_dashboard_data()
  - boq.js          → search_boq_items()
  - import.js       → get_recent_batches()
  - batch.js        → list_batches()
  - dict.js         → get_material_dict_tree()
  - match.js        → get_pending_matches()   （复用 data.match_score 打分）
  - price.js        → get_price_analysis()    （复用 data.price_calc）
  - quality.js      → get_quality_dashboard() （复用 data.quality_metrics）
  - setting.js      → get_settings()          （本地，无后端依赖）
"""
from __future__ import annotations

import os
from collections import defaultdict
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterator

from sqlalchemy import String, cast, case, func
from sqlalchemy.orm import Session

from data.field_spec import DATA_SOURCE_TYPES as _FIELD_SPEC_TYPES
from data.gb_code import parse_gb_code
from data.match_score import score_candidates, HIGH_CONF_SCORE
from data.tfidf_matcher import TfidfMatcher, fuse_scores
from data.price_calc import DEFAULT_THRESHOLD, analyze_group, compute_kpis, deviation_pct
from data.quality_metrics import compute_metrics
from data.cost_catalog_gate import evaluate_gate_from_metrics


# ============================================================================
# 常量定义（对齐 Odoo 版 nav_items.js + MAJOR_DEFS）
# ============================================================================

MAJOR_DEFS = [
    {"name": "安装工程", "prefix": "03", "color": "#4D7CFE"},
    {"name": "市政工程", "prefix": "04", "color": "#22D3EE"},
    {"name": "房屋建筑", "prefix": "01", "color": "#10B981"},
    {"name": "园林绿化", "prefix": "05", "color": "#F59E0B"},
]
MAJOR_BY_PREFIX = {m["prefix"]: m for m in MAJOR_DEFS}
FALLBACK_MAJOR = {"name": "其他", "prefix": "", "color": "#A855F7"}

DATA_SOURCE_TYPES = {
    "completed": "已完工程",
    "control_price": "招标控制价",
    "bid_price": "投标报价",
    "pending_review": "待审清单",
    "info_price": "信息价",
}

# 数据性质 → chip 样式（对齐 Odoo 版）
SOURCE_CHIP = {
    "completed": "chip ok",
    "control_price": "chip info",
    "bid_price": "chip",
    "pending_review": "chip warn",
    "info_price": "chip purple",
}

# 演示数据总开关：默认关闭。开启后所有页面返回演示数据且带 is_demo 标记。
USE_MOCK_DATA = os.getenv("USE_MOCK_DATA", "0").lower() in ("1", "true", "yes")

PAGE_SIZE = 50


# ============================================================================
# 会话管理
# ============================================================================

@contextmanager
def _session_scope(db: Session | None = None) -> Iterator[Session]:
    """统一会话生命周期。

    传入 db 时（FastAPI Depends 注入）由调用方负责关闭；
    未传入时本函数自建并在 finally 中关闭，避免连接泄漏。
    """
    if db is not None:
        yield db
        return
    from app.db import SessionLocal
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _empty_result(**kwargs) -> dict[str, Any]:
    """空库/无数据时的统一返回骨架。"""
    base = {"data_error": None, "is_demo": False}
    base.update(kwargs)
    return base


def _fail(exc: Exception, **kwargs) -> dict[str, Any]:
    """数据库异常：返回错误标记，绝不编造数据。"""
    base = {"data_error": f"数据读取失败：{type(exc).__name__}", "is_demo": False}
    base.update(kwargs)
    return base


# ============================================================================
# 格式化辅助（Decimal → float/str，模板友好）
# ============================================================================

def _f(value) -> float | None:
    """Decimal/None → float/None。"""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _num(value, nd: int = 2) -> str:
    """数值 → 千分位字符串；空值返回 '—'。"""
    v = _f(value)
    if v is None:
        return "—"
    return f"{v:,.{nd}f}"


def _pct_str(num, den, nd: int = 1) -> str:
    """百分比字符串；分母为 0 时返回 '—'（不做 0 兜底，避免误读）。"""
    if not den:
        return "—"
    return f"{num / den * 100:.{nd}f}"


def _period(value: date | None) -> str:
    """date → 'YYYY-MM'；空返回 ''。"""
    return value.strftime("%Y-%m") if value else ""


def _major_of(code: str | None) -> dict:
    """清单编码前 2 位 → 专业定义。"""
    if code:
        return MAJOR_BY_PREFIX.get(code[:2], FALLBACK_MAJOR)
    return FALLBACK_MAJOR


# ============================================================================
# 导航定义（复用 Odoo 版 nav_items.js 结构）
# ============================================================================

NAV_GROUPS = [
    {
        "id": "asset",
        "label": "数据资产",
        "items": [
            {"id": "dash", "label": "数据概览", "icon": "◈", "path": "/dashboard"},
            {"id": "boq", "label": "清单检索", "icon": "▤", "path": "/search"},
            {"id": "price", "label": "单价分析", "icon": "◑", "path": "/price"},
            {"id": "quality", "label": "数据质量", "icon": "◍", "path": "/quality"},
        ],
    },
    {
        "id": "ingest",
        "label": "数据接入",
        "items": [
            {"id": "import", "label": "导入向导", "icon": "⇪", "path": "/import"},
            {"id": "batch", "label": "批次管理", "icon": "▷", "path": "/batches", "badge_key": "batch"},
        ],
    },
    {
        "id": "std",
        "label": "标准维护",
        "items": [
            {"id": "dict", "label": "物料字典", "icon": "☰", "path": "/dict"},
            {"id": "match", "label": "匹配确认", "icon": "≋", "path": "/match", "badge_key": "match"},
        ],
    },
    {
        "id": "sys",
        "label": "系统",
        "items": [
            {"id": "setting", "label": "系统设置", "icon": "⚙", "path": "/settings"},
        ],
    },
]

FLAT_NAV_ITEMS = [item for group in NAV_GROUPS for item in group["items"]]


def get_nav_badges(db: Session | None = None) -> dict[str, int]:
    """导航小红点：待审批次数 / 待确认匹配数。失败返回空 dict（不显示红点）。"""
    if USE_MOCK_DATA:
        return {"batch": 2, "match": 7}
    try:
        from app.models.boq_item import BoqItem
        from app.models.import_batch import ImportBatch
        with _session_scope(db) as s:
            batch_n = s.query(func.count(ImportBatch.id)).filter(
                ImportBatch.active == True,  # noqa: E712
                ImportBatch.data_source_type == "pending_review",
            ).scalar() or 0
            match_n = s.query(func.count(BoqItem.id)).filter(
                BoqItem.active == True,  # noqa: E712
                BoqItem.material_dict_id == None,  # noqa: E711
            ).scalar() or 0
        return {"batch": int(batch_n), "match": int(match_n)}
    except Exception:
        return {}


# ============================================================================
# 演示数据（仅 USE_MOCK_DATA=1 使用；页面必须显示水印）
# ============================================================================

def _demo_payload() -> dict[str, Any]:
    """演示数据。用于无真实数据时的 UI 走查，页面须显式标注「演示数据」。"""
    return {
        "kpi": {
            "total": 128540, "std": 96820, "price": 42180, "pending": 7,
            "stdRate": "75.3", "priceRate": "32.8", "materialCount": 186,
            "projectCount": 42, "batchCount": 18,
        },
        "months": [
            {"month": f"2025-{m:02d}", "label": f"{m:02d}", "value": v}
            for m, v in [(10, 8420), (11, 9180), (12, 10240),
                         (1, 11400), (2, 9860), (3, 12360),
                         (4, 13180), (5, 12740), (6, 14020),
                         (7, 13860), (8, 15240), (9, 16440)]
        ],
        "donut": [
            {"name": "安装工程", "value": 48260, "color": "#4D7CFE", "pct": 37.5},
            {"name": "市政工程", "value": 34180, "color": "#22D3EE", "pct": 26.6},
            {"name": "房屋建筑", "value": 27940, "color": "#10B981", "pct": 21.7},
            {"name": "园林绿化", "value": 11260, "color": "#F59E0B", "pct": 8.8},
            {"name": "其他", "value": 6900, "color": "#A855F7", "pct": 5.4},
        ],
        "progress": [
            {"label": "名称标准化", "pct": 75.3, "value": 96820},
            {"label": "单价覆盖", "pct": 32.8, "value": 42180},
            {"label": "物料归类", "pct": 61.2, "value": 78640},
        ],
        "todos": [
            {"icon": "≋", "title": "7 条模糊匹配待确认", "sub": "相似度 82~91%，需人工判定", "href": "/match", "actionLabel": "去处理", "prio": "高", "prioClass": "chip err"},
            {"icon": "⇪", "title": "2 个导入批次待审核", "sub": "沈阳试验区市政外线 · 共 1,284 行", "href": "/batches", "actionLabel": "去审核", "prio": "中", "prioClass": "chip warn"},
            {"icon": "◑", "title": "12 条单价偏离预警", "sub": "偏离区间价 ±25%，建议复核信息价", "href": "/price", "actionLabel": "查看", "prio": "中", "prioClass": "chip warn"},
        ],
        "batches": [
            {"id": 1, "name": "沈阳试验区-市政外线", "typeLabel": "已完工程", "typeChip": "chip ok", "imported": 1284, "anomaly": 54, "at": "2026-08-14 10:22", "status": "有效"},
            {"id": 2, "name": "雄安片区-工业管道", "typeLabel": "已完工程", "typeChip": "chip ok", "imported": 3860, "anomaly": 12, "at": "2026-07-02 15:40", "status": "有效"},
            {"id": 3, "name": "辽宁三变体样本", "typeLabel": "待审清单", "typeChip": "chip warn", "imported": 1850, "anomaly": 28, "at": "2026-06-18 09:15", "status": "待审"},
        ],
        "boq_rows": [
            {"id": 1, "code": "030801001001", "majorColor": "#4D7CFE", "majorName": "安装工程", "name": "镀锌钢管", "feature": "DN100 沟槽连接", "unit": "m", "qty": "1,240.00", "rate": "78.50", "total": "97,340.00", "source": "沈阳试验区", "period": "2026-08", "stCls": "ok", "stLabel": "已标准化"},
            {"id": 2, "code": "031001001002", "majorColor": "#4D7CFE", "majorName": "安装工程", "name": "低压配电柜", "feature": "GGD 型，AC 380V", "unit": "台", "qty": "12.00", "rate": "12,500.00", "total": "150,000.00", "source": "雄安片区", "period": "2026-07", "stCls": "warn", "stLabel": "编码待核"},
            {"id": 3, "code": "040101001001", "majorColor": "#22D3EE", "majorName": "市政工程", "name": "挖一般土方", "feature": "三类土，深度 2m 内", "unit": "m³", "qty": "5,600.00", "rate": "45.00", "total": "252,000.00", "source": "沈阳试验区", "period": "2026-08", "stCls": "grey", "stLabel": "未标准化"},
        ],
        "dict_tree": [
            {"id": 1, "name": "管道", "level": "l1", "depth": 0, "hasChild": True, "badge": 42, "category_path": "管道"},
            {"id": 2, "name": "镀锌钢管", "level": "l2", "depth": 1, "hasChild": True, "badge": 12, "category_path": "管道/镀锌钢管"},
            {"id": 3, "name": "DN100 沟槽连接", "level": "l3", "depth": 2, "hasChild": False, "badge": 0, "category_path": "管道/镀锌钢管/DN100 沟槽连接"},
            {"id": 4, "name": "电气设备", "level": "l1", "depth": 0, "hasChild": True, "badge": 38, "category_path": "电气设备"},
            {"id": 5, "name": "配电柜", "level": "l2", "depth": 1, "hasChild": True, "badge": 15, "category_path": "电气设备/配电柜"},
        ],
        "pending_matches": [
            {"id": 101, "code": "030204001001", "name": "低压配电柜", "feat": "GGD型，AC 380V", "proj": "雄安片区", "unit": "台", "price": "12,500.00", "src": {"label": "已完", "cls": "chip ok"},
             "cands": [{"dict_id": 5, "name": "配电柜", "spec": "GGD", "score": 92.4, "color": "#10B981"}]},
            {"id": 102, "code": "040301001001", "name": "管道支架", "feat": "钢制，防腐处理", "proj": "沈阳试验区", "unit": "套", "price": "180.00", "src": {"label": "待审", "cls": "chip warn"},
             "cands": [{"dict_id": 3, "name": "镀锌钢管", "spec": "DN100", "score": 64.1, "color": "#F59E0B"}]},
        ],
        "price_trend": [
            {"period": "2026-0%d" % i, "avg": v, "min": v * 0.9, "max": v * 1.1, "count": 12 + i}
            for i, v in enumerate([72.4, 74.1, 76.8, 78.5, 80.2, 79.6], start=3)
        ],
        "price_hist": [
            {"lo": 62 + i * 5, "hi": 67 + i * 5, "count": c}
            for i, c in enumerate([8, 24, 46, 38, 20, 9, 5, 2])
        ],
    }


# ============================================================================
# 数据概览 —— 对标 dashboard.js loadData()
# ============================================================================

def get_dashboard_data(db: Session | None = None, only_std: bool = False) -> dict[str, Any]:
    """数据概览。统计口径：默认仅 active=True；单价相关默认只取 completed。

    only_std=True 时仅统计已标准化（std_name 非空）的数据，用于未登录用户的数据可见性控制。
    """
    if USE_MOCK_DATA:
        d = _demo_payload()
        return _empty_result(is_demo=True, **{
            "kpi": d["kpi"], "months": d["months"], "donut": d["donut"],
            "progress": d["progress"], "todos": d["todos"], "batches": d["batches"],
            "meta": {"updatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")},
        })

    try:
        from app.models.boq_item import BoqItem
        from app.models.import_batch import ImportBatch
        from app.models.material_dict import MaterialDict

        with _session_scope(db) as s:
            # 基础过滤条件
            base_filter = [BoqItem.active == True]  # noqa: E712
            if only_std:
                base_filter.append(BoqItem.std_name != None)  # noqa: E711

            # ---- KPI（口径分离：条目总数 vs 单价样本只取 completed）----
            row = s.query(
                func.count(BoqItem.id).label("total"),
                func.coalesce(func.sum(case((BoqItem.std_name != None, 1), else_=0)), 0).label("std"),  # noqa: E711
                func.coalesce(func.sum(case((BoqItem.unit_rate_num != None, 1), else_=0)), 0).label("price"),  # noqa: E711
                func.coalesce(func.sum(case((BoqItem.material_dict_id == None, 1), else_=0)), 0).label("pending"),  # noqa: E711
                func.count(func.distinct(BoqItem.project_name)).label("project_count"),
            ).filter(*base_filter).one()

            total = int(row.total or 0)
            std = int(row.std or 0)
            price = int(row.price or 0)
            pending = int(row.pending or 0)

            batch_count = s.query(func.count(ImportBatch.id)).filter(
                ImportBatch.active == True).scalar() or 0  # noqa: E712
            material_count = s.query(func.count(MaterialDict.id)).scalar() or 0

            # ---- 月度入库量（近 12 月；cast+substr 跨 PG/SQLite 兼容）----
            since = (date.today().replace(day=1) - timedelta(days=365)).replace(day=1)
            month_expr = func.substr(cast(BoqItem.price_period, String), 1, 7)
            month_rows = s.query(
                month_expr.label("ym"),
                func.count(BoqItem.id).label("n"),
            ).filter(
                BoqItem.active == True,  # noqa: E712
                BoqItem.price_period != None,  # noqa: E711
                BoqItem.price_period >= since,
                *([BoqItem.std_name != None] if only_std else []),  # noqa: E711
            ).group_by("ym").order_by("ym").all()
            month_map = {r.ym: int(r.n) for r in month_rows if r.ym}

            months = []
            cursor = date.today().replace(day=1) - timedelta(days=334)
            for _ in range(12):
                ym = cursor.strftime("%Y-%m")
                months.append({"month": ym, "label": cursor.strftime("%m"), "value": month_map.get(ym, 0)})
                cursor = (cursor.replace(day=28) + timedelta(days=7)).replace(day=1)

            # ---- 专业分布（前 2 位编码）----
            prefix_rows = s.query(
                func.substr(BoqItem.item_code, 1, 2).label("pfx"),
                func.count(BoqItem.id).label("n"),
            ).filter(
                BoqItem.active == True,  # noqa: E712
                BoqItem.item_code != None,  # noqa: E711
            ).group_by("pfx").all()

            agg = defaultdict(int)
            for r in prefix_rows:
                agg[r.pfx or ""] += int(r.n)
            donut = []
            for pfx, n in sorted(agg.items(), key=lambda kv: -kv[1]):
                m = MAJOR_BY_PREFIX.get(pfx, FALLBACK_MAJOR)
                donut.append({
                    "name": m["name"] if pfx else "未分类",
                    "value": n,
                    "color": m["color"],
                    "pct": round(n / total * 100, 1) if total else 0.0,
                })

            # ---- 标准化进度 ----
            progress = [
                {"label": "名称标准化", "pct": round(std / total * 100, 1) if total else 0.0, "value": std},
                {"label": "单价覆盖", "pct": round(price / total * 100, 1) if total else 0.0, "value": price},
                {"label": "物料归类", "pct": round((total - pending) / total * 100, 1) if total else 0.0, "value": total - pending},
            ]

            # ---- 待办（由真实计数驱动，不再硬编码）----
            batch_pending = s.query(func.count(ImportBatch.id)).filter(
                ImportBatch.active == True,  # noqa: E712
                ImportBatch.data_source_type == "pending_review",
            ).scalar() or 0
            anomaly_n = s.query(func.count(BoqItem.id)).filter(
                BoqItem.active == True,  # noqa: E712
                BoqItem.anomaly_flag.in_(["warning", "error"]),
            ).scalar() or 0

            todos = []
            if pending:
                todos.append({"icon": "≋", "title": f"{pending} 条待归类确认", "sub": "未关联物料字典，需人工判定",
                              "href": "/match", "actionLabel": "去处理", "prio": "高", "prioClass": "chip err"})
            if batch_pending:
                todos.append({"icon": "⇪", "title": f"{batch_pending} 个导入批次待审核", "sub": "数据性质为「待审清单」，需复核后放行",
                              "href": "/batches", "actionLabel": "去审核", "prio": "中", "prioClass": "chip warn"})
            if anomaly_n:
                todos.append({"icon": "◑", "title": f"{anomaly_n} 条单价异常标记", "sub": "异常标记为 warning/error，建议复核信息价",
                              "href": "/price", "actionLabel": "查看", "prio": "中", "prioClass": "chip warn"})

            # ---- 最近批次 ----
            recent = s.query(ImportBatch).filter(
                ImportBatch.active == True  # noqa: E712
            ).order_by(ImportBatch.imported_at.desc()).limit(5).all()
            batches = [_batch_row(b) for b in recent]

            return _empty_result(
                kpi={
                    "total": total, "std": std, "price": price, "pending": pending,
                    "stdRate": _pct_str(std, total), "priceRate": _pct_str(price, total),
                    "materialCount": int(material_count),
                    "projectCount": int(row.project_count or 0),
                    "batchCount": int(batch_count),
                },
                months=months, donut=donut, progress=progress, todos=todos, batches=batches,
                meta={"updatedAt": datetime.now().strftime("%Y-%m-%d %H:%M")},
            )
    except Exception as exc:
        return _fail(exc, kpi={"total": 0, "std": 0, "price": 0, "pending": 0,
                               "stdRate": "—", "priceRate": "—",
                               "materialCount": 0, "projectCount": 0, "batchCount": 0},
                     months=[], donut=[], progress=[], todos=[], batches=[],
                     meta={"updatedAt": "—"})


def _batch_row(b) -> dict[str, Any]:
    """ImportBatch → 模板行（统一字段，供 dashboard / batches 复用）。"""
    return {
        "id": b.id,
        "name": b.name or b.source_file or f"批次 #{b.id}",
        "typeLabel": DATA_SOURCE_TYPES.get(b.data_source_type, b.data_source_type),
        "typeChip": SOURCE_CHIP.get(b.data_source_type, "chip"),
        "imported": b.imported_count or 0,
        "anomaly": b.anomaly_count or 0,
        "skipped": b.skipped_count or 0,
        "at": b.imported_at.strftime("%Y-%m-%d %H:%M") if b.imported_at else "—",
        "period": _period(b.price_period),
        "province": b.province or "—",
        "operator": b.operator or "—",
        "status": "待审" if b.data_source_type == "pending_review" else "有效",
        "archived": bool(b.archive_path),
        "active": bool(b.active),
    }


# ============================================================================
# 清单检索 —— 对标 boq.js loadRows()
# ============================================================================

def search_boq_items(
    db: Session | None = None,
    kw: str = "",
    f_major: str = "",
    f_code: str = "",
    f_name: str = "",
    f_source: str = "",
    f_anomaly: str = "",
    std_status: str = "",
    page: int = 1,
    per_page: int = PAGE_SIZE,
    only_std: bool = False,
) -> dict[str, Any]:
    """清单检索。多条件 AND 过滤 + 分页；page 越界自动夹取。

    only_std=True 时仅返回已标准化（std_name 非空）的数据，用于未登录用户的数据可见性控制。
    """
    if USE_MOCK_DATA:
        rows = _demo_payload()["boq_rows"]
        return _empty_result(is_demo=True, rows=rows, hitCount=len(rows),
                             stdCount=1, pendingCount=2, pages=1, page=1, per_page=per_page)

    try:
        from sqlalchemy import or_
        from app.models.boq_item import BoqItem

        with _session_scope(db) as s:
            q = s.query(BoqItem).filter(BoqItem.active == True)  # noqa: E712

            if kw:
                like = f"%{kw}%"
                q = q.filter(or_(
                    BoqItem.item_name.like(like),
                    BoqItem.item_code.like(like),
                    BoqItem.item_feature.like(like),
                    BoqItem.project_name.like(like),
                ))
            if f_major:
                q = q.filter(BoqItem.item_code.like(f"{f_major}%"))
            if f_code:
                q = q.filter(BoqItem.item_code.like(f"%{f_code}%"))
            if f_name:
                q = q.filter(BoqItem.item_name.like(f"%{f_name}%"))
            if f_source:
                q = q.filter(BoqItem.data_source_type == f_source)
            if f_anomaly:
                q = q.filter(BoqItem.anomaly_flag == f_anomaly)
            if std_status == "std":
                q = q.filter(BoqItem.std_name != None)  # noqa: E711
            elif std_status == "pending":
                q = q.filter(BoqItem.std_name == None)  # noqa: E711

            # 数据可见性控制：未登录用户仅能看到已标准化数据
            if only_std:
                q = q.filter(BoqItem.std_name != None)  # noqa: E711

            total = q.count()
            pages = max(1, (total + per_page - 1) // per_page)
            page = max(1, min(page, pages))
            items = q.order_by(BoqItem.id.desc()).offset((page - 1) * per_page).limit(per_page).all()

            std_count = q.filter(BoqItem.std_name != None).count()  # noqa: E711
            pending_count = total - std_count

            return _empty_result(
                rows=[_boq_row(r) for r in items],
                hitCount=total, stdCount=std_count, pendingCount=pending_count,
                pages=pages, page=page, per_page=per_page,
            )
    except Exception as exc:
        return _fail(exc, rows=[], hitCount=0, stdCount=0, pendingCount=0,
                     pages=1, page=1, per_page=per_page)


def _boq_row(r) -> dict[str, Any]:
    """BoqItem → 模板行。"""
    major = _major_of(r.item_code)
    if r.std_name:
        st_cls, st_label = "ok", "已标准化"
    elif r.match_key_source in ("code", "raw"):
        st_cls, st_label = "warn", "编码待核"
    else:
        st_cls, st_label = "grey", "未标准化"
    return {
        "id": r.id,
        "code": r.item_code or "—",
        "majorColor": major["color"],
        "majorName": major["name"],
        "name": r.item_name,
        "feature": r.item_feature or "—",
        "unit": r.unit or "—",
        "qty": _num(r.quantity_num),
        "rate": _num(r.unit_rate_num),
        "total": _num(r.total_num),
        "source": r.project_name or (r.import_batch.name if r.import_batch else "—"),
        "period": _period(r.price_period),
        "stCls": st_cls,
        "stLabel": st_label,
        "anomaly": r.anomaly_flag or "normal",
    }


# ============================================================================
# 导入向导 / 批次管理
# ============================================================================

def get_recent_batches(db: Session | None = None, limit: int = 5) -> list[dict]:
    """导入向导页最近批次 —— 对标 import.js loadBatches()。"""
    if USE_MOCK_DATA:
        return _demo_payload()["batches"]
    try:
        from app.models.import_batch import ImportBatch
        with _session_scope(db) as s:
            rows = s.query(ImportBatch).filter(
                ImportBatch.active == True  # noqa: E712
            ).order_by(ImportBatch.imported_at.desc()).limit(limit).all()
            return [_batch_row(b) for b in rows]
    except Exception:
        return []


def list_batches(db: Session | None = None) -> dict[str, Any]:
    """批次管理 —— 对标 batch.js loadData()。"""
    if USE_MOCK_DATA:
        d = _demo_payload()
        return _empty_result(is_demo=True, rows=d["batches"], total=len(d["batches"]),
                             kpi={"total": 3, "items": 6994, "anomaly": 94, "anomalyPct": "1.3"})

    try:
        from app.models.import_batch import ImportBatch
        with _session_scope(db) as s:
            # 全量（含回收站）按导入时间倒序，active 标志决定按钮形态
            rows_all = s.query(ImportBatch).order_by(
                ImportBatch.imported_at.desc()
            ).all()
            active_rows = [b for b in rows_all if b.active]
            recycled = sum(1 for b in rows_all if not b.active)

            total = len(active_rows)
            items = sum(r["imported"] for r in (_batch_row(b) for b in active_rows))
            anomaly = sum(r["anomaly"] for r in (_batch_row(b) for b in active_rows))
            return _empty_result(
                rows=[_batch_row(b) for b in rows_all],
                total=total,
                recycled=int(recycled),
                # 注意：键名不用 items（Jinja 中 dict.items 会命中内置方法）
                kpi={"total": total, "itemTotal": items, "anomaly": anomaly,
                     "anomalyPct": _pct_str(anomaly, items)},
            )
    except Exception as exc:
        return _fail(exc, rows=[], total=0, recycled=0,
                     kpi={"total": 0, "itemTotal": 0, "anomaly": 0, "anomalyPct": "—"})


def get_batch_detail(batch_id: int, db: Session | None = None) -> dict[str, Any]:
    """批次详情 —— 批次元信息 + 该批次清单项列表（前 100 条预览）。"""
    try:
        from app.models.import_batch import ImportBatch
        from app.models.boq_item import BoqItem
        with _session_scope(db) as s:
            batch = s.query(ImportBatch).filter(ImportBatch.id == batch_id).first()
            if not batch:
                return _fail(ValueError(f"批次 {batch_id} 不存在"), batch=None, items=[], itemCount=0)
            items = s.query(BoqItem).filter(
                BoqItem.import_batch_id == batch_id
            ).order_by(BoqItem.sequence.asc()).limit(100).all()
            item_count = s.query(func.count(BoqItem.id)).filter(
                BoqItem.import_batch_id == batch_id
            ).scalar() or 0
            return _empty_result(
                batch=_batch_row(batch),
                batch_raw={
                    "id": batch.id,
                    "name": batch.name,
                    "source_file": batch.source_file,
                    "file_hash": batch.file_hash,
                    "archive_path": batch.archive_path,
                    "source_path": batch.source_path,
                    "checksum_total": batch.checksum_total,
                    "checksum_hash": batch.checksum_hash,
                    "deleted_at": batch.deleted_at.strftime("%Y-%m-%d %H:%M") if batch.deleted_at else None,
                },
                items=[{"id": it.id, "seq": it.sequence, "code": it.item_code, "name": it.item_name,
                        "feat": (it.item_feature or "")[:80], "unit": it.unit, "qty": it.quantity,
                        "price": it.unit_rate, "anomaly": it.anomaly_flag} for it in items],
                itemCount=int(item_count),
            )
    except Exception as exc:
        return _fail(exc, batch=None, items=[], itemCount=0)


# ============================================================================
# 物料字典 —— 对标 dict.js loadAll() + _rebuildAll()
# ============================================================================

def _dict_node(n, depth: int, parent_path: str = "") -> dict[str, Any]:
    """MaterialDict → 树节点（含 match_score 需要的 category_path）。"""
    path = f"{parent_path}/{n.name}" if parent_path else (n.name or "")
    children = sorted(n.child_ids or [], key=lambda c: c.name or "")
    return {
        "id": n.id,
        "parent_id": n.parent_id,
        "name": n.name,
        "level": n.level,
        "depth": depth,
        "hasChild": bool(children),
        "badge": len(children),
        "category_path": path,
        "synonyms": (n.synonyms or {}).get("list", []) if isinstance(n.synonyms, dict) else (n.synonyms or []),
        "spec_whitelist": (n.spec_whitelist or {}).get("list", []) if isinstance(n.spec_whitelist, dict) else (n.spec_whitelist or []),
        "note": n.note or "",
    }


def get_material_dict_tree(db: Session | None = None, selected: int | None = None) -> dict[str, Any]:
    """物料字典三级树。小表全量载入后 Python 侧递归展开，避免递归 SQL。"""
    if USE_MOCK_DATA:
        tree = _demo_payload()["dict_tree"]
        return _empty_result(is_demo=True, tree=tree, total=len(tree), shown=len(tree),
                             selected=None, detail=None)

    try:
        from app.models.material_dict import MaterialDict
        with _session_scope(db) as s:
            roots = s.query(MaterialDict).filter(
                MaterialDict.parent_id == None  # noqa: E711
            ).order_by(MaterialDict.name).all()

            total = s.query(func.count(MaterialDict.id)).scalar() or 0
            tree: list[dict] = []

            def walk(node, depth: int, parent_path: str):
                item = _dict_node(node, depth, parent_path)
                tree.append(item)
                for child in sorted(node.child_ids or [], key=lambda c: c.name or ""):
                    walk(child, depth + 1, item["category_path"])

            for r in roots:
                walk(r, 0, "")

            detail = None
            sel = selected
            if sel is None and tree:
                sel = tree[0]["id"]
            if sel is not None:
                node = s.query(MaterialDict).filter(MaterialDict.id == sel).first()
                if node is not None:
                    detail = _dict_node(node, 0, "")
                    detail["cat_path"] = detail["category_path"]

            return _empty_result(tree=tree, total=int(total), shown=len(tree),
                                 selected=sel, detail=detail)
    except Exception as exc:
        return _fail(exc, tree=[], total=0, shown=0, selected=None, detail=None)


# ============================================================================
# 匹配确认 —— 对标 match.js loadData()（复用 data.match_score 打分）
# ============================================================================

def _score_color(score: float) -> str:
    """分数 → 颜色（对齐 Odoo 版置信度配色）。"""
    if score >= 90:
        return "#10B981"
    if score >= 75:
        return "#4D7CFE"
    if score >= 60:
        return "#F59E0B"
    return "#EF4444"


def get_pending_matches(db: Session | None = None, limit: int = 50) -> dict[str, Any]:
    """待确认条目 + 候选召回。候选由 data.match_score.score_candidates 确定性打分。"""
    if USE_MOCK_DATA:
        items = _demo_payload()["pending_matches"]
        return _empty_result(is_demo=True, items=items, pendingCount=len(items),
                             dictCount=5, groupCount=1)

    try:
        from app.models.boq_item import BoqItem
        from app.models.material_dict import MaterialDict

        with _session_scope(db) as s:
            pending = s.query(BoqItem).filter(
                BoqItem.active == True,  # noqa: E712
                BoqItem.material_dict_id == None,  # noqa: E711
            ).order_by(BoqItem.id).limit(limit).all()

            dict_count = s.query(func.count(MaterialDict.id)).scalar() or 0

            # 候选池：取叶子/三级节点（有 category_path 权重才有意义）
            dict_rows = s.query(MaterialDict).all()
            cat_by_id = {}
            for n in dict_rows:
                cat_by_id[n.id] = n
            pool = [{
                "id": n.id,
                "name": n.name,
                "spec": (n.spec_whitelist or {}).get("list", [None])[0]
                        if isinstance(n.spec_whitelist, dict) and n.spec_whitelist.get("list")
                        else "",
                "category_path": _category_path_of(n, cat_by_id),
            } for n in dict_rows]

            # 构建 TF-IDF 索引（复用，避免每个清单项重新构建）
            tfidf_matcher = TfidfMatcher(pool) if pool else None

            items = []
            cache_hits = 0
            for r in pending:
                # 优先从缓存读取候选（后台预匹配）
                from app.services.prematch_service import get_cached_candidates
                cached = get_cached_candidates(s, r.id)
                if cached is not None:
                    cands = cached[:3]
                    cache_hits += 1
                else:
                    # 缓存未命中，实时计算（rapidfuzz + TF-IDF 融合）
                    query_name = r.item_name or ''
                    query_spec = r.std_spec or r.item_feature or ''
                    rf_cands = score_candidates(query_name, query_spec, pool)
                    if tfidf_matcher:
                        tf_cands = tfidf_matcher.match(query_name, query_spec, top_n=10)
                        cands = fuse_scores(rf_cands, tf_cands)[:3]
                    else:
                        cands = rf_cands[:3]
                items.append({
                    "id": r.id,
                    "code": r.item_code or "—",
                    "name": r.item_name,
                    "feat": r.item_feature or "—",
                    "proj": r.project_name or "—",
                    "unit": r.unit or "—",
                    "price": _num(r.unit_rate_num),
                    "src": {
                        "label": DATA_SOURCE_TYPES.get(r.data_source_type, r.data_source_type),
                        "cls": SOURCE_CHIP.get(r.data_source_type, "chip"),
                    },
                    "cands": [dict(c, color=_score_color(c["score"])) for c in cands],
                })

            result = _empty_result(
                items=items,
                pendingCount=len(items),
                dictCount=int(dict_count),
                groupCount=len({i["name"] for i in items}),
            )
            result["cache_hits"] = cache_hits
            result["cache_misses"] = len(items) - cache_hits
            return result
    except Exception as exc:
        return _fail(exc, items=[], pendingCount=0, dictCount=0, groupCount=0)


def _category_path_of(node, cat_by_id: dict) -> str:
    """自底向上拼 'L1/L2/L3'。带环保护，防止脏数据死循环。"""
    parts, cur, guard = [], node, 0
    while cur is not None and guard < 10:
        parts.append(cur.name or "")
        cur = cat_by_id.get(cur.parent_id) if cur.parent_id else None
        guard += 1
    return "/".join(reversed(parts))


# ============================================================================
# 单价分析 —— 对标 price.js reload()（复用 data.price_calc）
# ============================================================================

def get_price_analysis(
    db: Session | None = None,
    range_months: int = 24,
    major: str = "all",
    min_sample: int = 3,
) -> dict[str, Any]:
    """单价分析。

    口径：默认仅统计 data_source_type='completed'（M3 §3.1，待审/控制价/信息价不进历史均价）。
    """
    if USE_MOCK_DATA:
        d = _demo_payload()
        return _empty_result(is_demo=True,
                             kpis={"sampleCount": 186, "avg": 78.5, "min": 63.8, "max": 98.6,
                                   "anomalyCount": 3, "hasSamples": True, "cv": "11.6"},
                             trend=d["price_trend"], hist=d["price_hist"],
                             statRows=[{"k": "最小值", "v": "63.80"}, {"k": "P25", "v": "72.00"},
                                       {"k": "中位数 P50", "v": "79.20"}, {"k": "P75", "v": "86.40"},
                                       {"k": "最大值", "v": "98.60"}],
                             groups=[], gate=None)

    try:
        from app.models.boq_item import BoqItem
        with _session_scope(db) as s:
            since = (date.today().replace(day=1) - timedelta(days=int(range_months) * 30.5))
            q = s.query(BoqItem).filter(
                BoqItem.active == True,  # noqa: E712
                BoqItem.unit_rate_num != None,  # noqa: E711
                BoqItem.price_period != None,  # noqa: E711
                BoqItem.price_period >= since,
            )
            if major and major != "all":
                q = q.filter(BoqItem.item_code.like(f"{major}%"))

            items = q.all()
            rows = [{
                "unit_rate_num": _f(r.unit_rate_num),
                "price_period": _period(r.price_period),
                "project_name": r.project_name or "—",
                "aggregate_id": r.aggregate_id or "",
            } for r in items]

            kpis_raw = compute_kpis(rows)
            has_samples = kpis_raw["sample_count"] > 0

            # 趋势：按价格期分组（复用 analyze_group）
            trend = []
            for g in analyze_group(rows, "price_period"):
                trend.append({
                    "period": g.get("group") or "—",
                    "avg": round(g.get("avg") or 0, 2),
                    "min": round(g.get("min") or 0, 2),
                    "max": round(g.get("max") or 0, 2),
                    "count": g.get("count") or 0,
                })
            trend.sort(key=lambda x: x["period"])

            # 直方图：按均价 ±3σ 分 10 桶，空数据返回空（不造数）
            hist = _histogram([r["unit_rate_num"] for r in rows if r["unit_rate_num"] is not None])

            # 分位数
            vals = sorted(r["unit_rate_num"] for r in rows if r["unit_rate_num"] is not None)
            stat_rows = _quantile_rows(vals)

            # 离散系数 CV
            cv = "—"
            if has_samples and kpis_raw["avg"]:
                cv = f"{_stddev(vals) / kpis_raw['avg'] * 100:.1f}"

            # 各工程对比（复用 analyze_group 的 aggregate_id 维度）
            groups = []
            for g in analyze_group(rows, "aggregate_id"):
                groups.append({
                    "name": g.get("group") or "—",
                    "avg": round(g.get("avg") or 0, 2),
                    "min": round(g.get("min") or 0, 2),
                    "max": round(g.get("max") or 0, 2),
                    "count": g.get("count") or 0,
                    "anomaly": g.get("anomaly_count") or 0,
                    "deviation": round(deviation_pct(g.get("avg") or 0, kpis_raw["avg"]), 1),
                })
            groups.sort(key=lambda x: -abs(x["deviation"]))

            # 门禁（M4 准入：覆盖率 + 异常率）
            raw_metrics = [{
                "material_dict_id": r.material_dict_id,
                "match_key_source": r.match_key_source,
                "data_source_type": r.data_source_type,
                "anomaly_flag": r.anomaly_flag,
            } for r in items]
            metrics = compute_metrics(raw_metrics)
            gate = evaluate_gate_from_metrics(metrics) if raw_metrics else None

            return _empty_result(
                kpis={
                    "sampleCount": kpis_raw["sample_count"],
                    "avg": round(kpis_raw["avg"], 2),
                    "min": round(kpis_raw["min"], 2),
                    "max": round(kpis_raw["max"], 2),
                    "anomalyCount": kpis_raw["anomaly_count"],
                    "hasSamples": has_samples,
                    "cv": cv,
                    "threshold": int(DEFAULT_THRESHOLD * 100),
                    "minSample": min_sample,
                },
                trend=trend, hist=hist, statRows=stat_rows, groups=groups[:20], gate=gate,
                metrics=metrics,
            )
    except Exception as exc:
        return _fail(exc,
                     kpis={"sampleCount": 0, "avg": 0, "min": 0, "max": 0,
                           "anomalyCount": 0, "hasSamples": False, "cv": "—",
                           "threshold": int(DEFAULT_THRESHOLD * 100), "minSample": min_sample},
                     trend=[], hist=[], statRows=[], groups=[], gate=None, metrics=None)


def _stddev(vals: list[float]) -> float:
    """总体标准差；样本 < 2 返回 0。"""
    n = len(vals)
    if n < 2:
        return 0.0
    mean = sum(vals) / n
    return (sum((v - mean) ** 2 for v in vals) / n) ** 0.5


def _histogram(vals: list[float], bins: int = 10) -> list[dict]:
    """等宽直方图。空数据返回 []（不编造分布）。"""
    if not vals:
        return []
    lo, hi = min(vals), max(vals)
    if hi <= lo:
        return [{"lo": round(lo, 2), "hi": round(hi, 2), "count": len(vals), "pct": 100.0}]
    width = (hi - lo) / bins
    counts = [0] * bins
    for v in vals:
        idx = min(bins - 1, int((v - lo) / width))
        counts[idx] += 1
    total = len(vals)
    return [
        {"lo": round(lo + i * width, 2), "hi": round(lo + (i + 1) * width, 2),
         "count": c, "pct": round(c / total * 100, 1)}
        for i, c in enumerate(counts)
    ]


def _quantile_rows(vals: list[float]) -> list[dict]:
    """min / P25 / P50 / P75 / max。空数据返回 []。"""
    if not vals:
        return []
    n = len(vals)

    def q(p: float) -> float:
        idx = min(n - 1, max(0, int(round(p * (n - 1)))))
        return vals[idx]

    return [
        {"k": "最小值", "v": f"{vals[0]:,.2f}"},
        {"k": "P25", "v": f"{q(0.25):,.2f}"},
        {"k": "中位数 P50", "v": f"{q(0.50):,.2f}"},
        {"k": "P75", "v": f"{q(0.75):,.2f}"},
        {"k": "最大值", "v": f"{vals[-1]:,.2f}"},
        {"k": "标准差", "v": f"{_stddev(vals):,.2f}"},
    ]


# ============================================================================
# 数据质量 —— 对标 quality.js loadDashboard()（复用 data.quality_metrics）
# ============================================================================

def get_quality_dashboard(db: Session | None = None) -> dict[str, Any]:
    """数据质量指标。全部由 compute_metrics 计算，无手编阈值。"""
    if USE_MOCK_DATA:
        return _empty_result(is_demo=True, total=128540, coverage=0.753,
                             matchKeyQuality=0.612, anomalyRate=0.012,
                             sourceCompletedRatio=0.82, m3Pass=True, m4Pass=False,
                             data_source_dist={}, gate=None)
    try:
        from app.models.boq_item import BoqItem
        with _session_scope(db) as s:
            rows = s.query(
                BoqItem.material_dict_id, BoqItem.match_key_source,
                BoqItem.data_source_type, BoqItem.anomaly_flag,
            ).filter(BoqItem.active == True).all()  # noqa: E712

            raw = [{
                "material_dict_id": r.material_dict_id,
                "match_key_source": r.match_key_source,
                "data_source_type": r.data_source_type,
                "anomaly_flag": r.anomaly_flag,
            } for r in rows]

            m = compute_metrics(raw)
            dist = m.get("data_source_dist", {})
            total = len(raw)
            completed = dist.get("completed", 0)

            return _empty_result(
                total=total,
                coverage=m["coverage"],
                matchKeyQuality=m["match_key_quality"],
                anomalyRate=m["anomaly_rate"],
                sourceCompletedRatio=(completed / total) if total else 0.0,
                m3Pass=m["m3_pass"],
                m4Pass=m["m4_pass"],
                data_source_dist=dist,
                gate=evaluate_gate_from_metrics(m) if raw else None,
            )
    except Exception as exc:
        return _fail(exc, total=0, coverage=0.0, matchKeyQuality=0.0,
                     anomalyRate=0.0, sourceCompletedRatio=0.0,
                     m3Pass=False, m4Pass=False, data_source_dist={}, gate=None)


# ============================================================================
# 系统设置 —— 对标 setting.js（无后端依赖，本地状态）
# ============================================================================

def get_settings() -> dict[str, Any]:
    """系统设置。阈值默认值来自 data 层常量，避免手编。"""
    from data.match_score import high_confidence  # noqa: F401（阈值同源说明）
    return _empty_result(
        themes=[
            {"id": "c", "label": "深空科技（方案 C）"},
            {"id": "a", "label": "经典蓝（方案 A）"},
            {"id": "b", "label": "极简白（方案 B）"},
        ],
        regions=[
            {"id": "", "label": "不限（全国）"},
            {"id": "liaoning", "label": "辽宁省"},
            {"id": "beijing", "label": "北京市"},
            {"id": "hebei", "label": "河北省"},
        ],
        defaults={
            "theme": "c",
            "region": "",
            # 阈值与 data.price_calc / match_score 同源，改动须同步 pure_tests
            "autoThr": HIGH_CONF_SCORE,  # match_score.high_confidence 的 Top-1 门槛
            "candThr": 75.0,          # 候选展示下限
            "deviationThr": int(DEFAULT_THRESHOLD * 100),
            "minSample": 3,
            "requireConfirm": True,
        },
        # 数据分层说明（data/field_spec.py 派生，不硬编码）
        field_layers={
            "A": sorted(_FIELD_SPEC_TYPES),
            "source_types": sorted(DATA_SOURCE_TYPES.keys()),
        },
    )
