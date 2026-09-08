# -*- coding: utf-8 -*-
"""后台预匹配服务（M3 性能优化）。

导入完成后异步计算所有待匹配条目的 Top-N 候选，存入 match_cache 表。
匹配确认页面优先从缓存读取，避免实时计算 O(N×M)。

使用方式：
- 导入完成后调用 precompute_pending_matches(db, batch_id) 触发预匹配
- 匹配确认页面调用 get_cached_candidates(db, boq_item_id) 读取缓存
- 缓存未命中或过期时，回退到实时计算
"""
import logging
import threading
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.models.boq_item import BoqItem
from app.models.material_dict import MaterialDict
from app.models.match_cache import MatchCache, CACHE_TTL_HOURS
from data.match_score import score_candidates

logger = logging.getLogger("zaojia.prematch")

# 全局预匹配任务状态（简单实现，生产环境可换 Celery/RQ）
_prematch_status = {
    "running": False,
    "total": 0,
    "processed": 0,
    "started_at": None,
    "finished_at": None,
}


def get_prematch_status() -> dict:
    """获取预匹配任务状态。"""
    return dict(_prematch_status)


def _build_dict_rows(db: Session) -> list[dict]:
    """构建物料字典候选行（用于 score_candidates）。"""
    dict_nodes = db.query(MaterialDict).filter(MaterialDict.level == "l3").all()
    rows = []
    for n in dict_nodes:
        cat_path = "/".join(filter(None, [n.cat_l1, n.cat_l2, n.cat_l3]))
        rows.append({
            "id": n.id,
            "name": n.name or "",
            "spec": (n.spec_whitelist[0] if n.spec_whitelist else "") or "",
            "category_path": cat_path,
        })
    return rows


def precompute_single(db: Session, boq_item_id: int, dict_rows: list[dict]) -> Optional[MatchCache]:
    """计算单个清单项的匹配结果并写入缓存。"""
    boq = db.query(BoqItem).filter(BoqItem.id == boq_item_id).first()
    if not boq or boq.material_dict_id:
        return None  # 已关联或不存在，跳过

    cands = score_candidates(
        boq.item_name or "",
        boq.std_spec or boq.item_feature or "",
        dict_rows,
    )[:5]  # Top-5

    if not cands:
        return None

    # 检查是否已有缓存
    existing = db.query(MatchCache).filter(MatchCache.boq_item_id == boq_item_id).first()
    if existing:
        existing.candidates = cands
        existing.top1_score = int(cands[0]["score"])
        existing.computed_at = datetime.utcnow()
        existing.cache_version = "v1"
        return existing

    cache = MatchCache(
        boq_item_id=boq_item_id,
        candidates=cands,
        top1_score=int(cands[0]["score"]),
        cache_version="v1",
        computed_at=datetime.utcnow(),
    )
    db.add(cache)
    return cache


def precompute_pending_matches(db: Session, batch_id: Optional[int] = None, limit: int = 0) -> dict:
    """预计算待匹配条目的匹配结果。

    Args:
        db: 数据库会话
        batch_id: 批次 ID（None 表示所有待匹配）
        limit: 限制计算数量（0 表示不限制）

    Returns:
        统计信息
    """
    global _prematch_status

    if _prematch_status["running"]:
        logger.info("预匹配任务已在运行中，跳过")
        return {"status": "already_running", **_prematch_status}

    _prematch_status.update({
        "running": True,
        "total": 0,
        "processed": 0,
        "started_at": datetime.utcnow().isoformat(),
        "finished_at": None,
    })

    try:
        # 查询待匹配条目
        query = db.query(BoqItem.id).filter(
            BoqItem.active == True,
            BoqItem.material_dict_id.is_(None),
        )
        if batch_id:
            query = query.filter(BoqItem.import_batch_id == batch_id)
        if limit > 0:
            query = query.limit(limit)

        pending_ids = [r[0] for r in query.all()]
        _prematch_status["total"] = len(pending_ids)
        logger.info(f"开始预匹配：{len(pending_ids)} 条待匹配")

        if not pending_ids:
            _prematch_status.update({"running": False, "finished_at": datetime.utcnow().isoformat()})
            return {"status": "no_pending", "total": 0}

        dict_rows = _build_dict_rows(db)
        logger.info(f"物料字典候选：{len(dict_rows)} 条")

        for i, boq_id in enumerate(pending_ids, 1):
            try:
                precompute_single(db, boq_id, dict_rows)
                if i % 100 == 0:
                    db.commit()  # 每 100 条提交一次
                    logger.info(f"预匹配进度：{i}/{len(pending_ids)}")
            except Exception as e:
                logger.error(f"预匹配失败 boq_id={boq_id}: {e}")
                db.rollback()
            _prematch_status["processed"] = i

        db.commit()
        _prematch_status.update({"running": False, "finished_at": datetime.utcnow().isoformat()})
        logger.info(f"预匹配完成：{len(pending_ids)} 条")
        return {"status": "completed", "total": len(pending_ids), "processed": len(pending_ids)}

    except Exception as e:
        _prematch_status.update({"running": False, "finished_at": datetime.utcnow().isoformat()})
        logger.error(f"预匹配任务失败: {e}")
        return {"status": "failed", "error": str(e)}


def precompute_pending_matches_async(db_session_factory, batch_id: Optional[int] = None, limit: int = 0) -> None:
    """异步触发预匹配（后台线程）。

    Args:
        db_session_factory: 数据库会话工厂（sessionmaker）
        batch_id: 批次 ID
        limit: 限制计算数量
    """
    def _worker():
        db = db_session_factory()
        try:
            precompute_pending_matches(db, batch_id=batch_id, limit=limit)
        finally:
            db.close()

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    logger.info("预匹配任务已在后台启动")


def get_cached_candidates(db: Session, boq_item_id: int) -> Optional[list[dict]]:
    """从缓存读取匹配候选。

    Returns:
        候选列表（缓存命中且未过期），None 表示缓存未命中、过期或表不存在（降级为实时计算）
    """
    try:
        cache = db.query(MatchCache).filter(MatchCache.boq_item_id == boq_item_id).first()
        if not cache:
            return None
        if cache.is_expired(CACHE_TTL_HOURS):
            return None
        return cache.candidates
    except Exception as e:
        # 表不存在或查询出错时降级为实时计算，不影响页面正常使用
        logger.warning(f"读取匹配缓存失败（降级为实时计算）: {type(e).__name__}: {e}")
        return None


def invalidate_cache(db: Session, boq_item_id: Optional[int] = None) -> int:
    """失效缓存。

    Args:
        boq_item_id: 清单项 ID（None 表示失效所有缓存）

    Returns:
        失效的缓存数量
    """
    query = db.query(MatchCache)
    if boq_item_id:
        query = query.filter(MatchCache.boq_item_id == boq_item_id)
    count = query.count()
    query.delete(synchronize_session=False)
    db.commit()
    logger.info(f"失效缓存：{count} 条")
    return count
