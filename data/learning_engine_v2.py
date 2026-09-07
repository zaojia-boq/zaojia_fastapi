# -*- coding: utf-8 -*-
"""学习引擎 v2：深度增强版（M3 算法升级，第二阶段深化）。

在 v1 基础上深化：
1. 多信号学习：Top-1 分数、分差、确认候选排名，不只是是否命中
2. 按类别学习：电气/给排水/暖通等不同类别分别学习权重
3. 学习率自适应：初期大、后期小、高信息量确认加倍
4. 主动学习推荐：计算不确定性分数，优先推荐高不确定性条目
5. 负样本学习：记录人工拒绝的候选，降低错误算法权重
6. 确认质量评估：评估每次确认的信息量，高信息量给予更高学习权重
7. 权重平滑：EMA 指数移动平均，防止过度拟合

设计：
- 纯函数模式，不依赖数据库
- 向后兼容 v1 的 record_confirmation 接口
- 支持持久化（JSON 配置文件）
"""
import json
import math
from pathlib import Path
from typing import Optional


# 默认权重
DEFAULT_WEIGHTS = {
    'rf': 0.3,      # rapidfuzz 编辑距离（精确匹配强）
    'tf': 0.35,     # TF-IDF 语义匹配（同义词/近义词强）
    'faiss': 0.35,  # FAISS 向量检索（大数据量快）
}

# 学习参数
BASE_LEARNING_RATE = 0.1   # 基础学习率
MIN_LEARNING_RATE = 0.02   # 最小学习率
MAX_LEARNING_RATE = 0.25   # 最大学习率
MIN_WEIGHT = 0.05           # 最小权重
MAX_WEIGHT = 0.85           # 最大权重
EMA_ALPHA = 0.3             # EMA 平滑系数（0=不更新，1=完全替换）

# 学习率自适应阶段
PHASE1_THRESHOLD = 100     # 初期：确认数 < 100
PHASE2_THRESHOLD = 500     # 中期：100 <= 确认数 < 500
PHASE1_LR_MULTIPLIER = 1.5  # 初期学习率倍数
PHASE2_LR_MULTIPLIER = 1.0  # 中期学习率倍数
PHASE3_LR_MULTIPLIER = 0.5  # 后期学习率倍数

# 不确定性阈值
UNCERTAINTY_HIGH = 0.6     # 高不确定性阈值
UNCERTAINTY_MEDIUM = 0.3   # 中等不确定性阈值


class LearningEngineV2:
    """学习引擎 v2：深度增强版。

    用法：
        engine = LearningEngineV2()
        engine.record_confirmation(...)
        weights = engine.get_weights(category='电气/电缆')
    """

    def __init__(self, config_path: Optional[str] = None):
        """初始化学习引擎。

        Args:
            config_path: 权重配置文件路径（JSON 格式），None 表示使用默认权重
        """
        self.config_path = config_path
        self.weights = dict(DEFAULT_WEIGHTS)
        self.category_weights = {}  # 按类别学习的权重 {category_prefix: {rf, tf, faiss}}
        self.confirmation_count = 0
        self.algorithm_hits = {'rf': 0, 'tf': 0, 'faiss': 0}
        self.algorithm_misses = {'rf': 0, 'tf': 0, 'faiss': 0}  # 负样本：Top-1 被拒绝
        self.rejection_count = 0
        self.category_confirmation_count = {}  # 各类别确认数
        self.high_info_confirmations = 0  # 高信息量确认数
        self._load_config()

    def _load_config(self):
        """从配置文件加载权重。"""
        if not self.config_path:
            return
        path = Path(self.config_path)
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            if 'weights' in data:
                self.weights.update(data['weights'])
            if 'category_weights' in data:
                self.category_weights.update(data['category_weights'])
            if 'confirmation_count' in data:
                self.confirmation_count = data['confirmation_count']
            if 'algorithm_hits' in data:
                self.algorithm_hits.update(data['algorithm_hits'])
            if 'algorithm_misses' in data:
                self.algorithm_misses.update(data['algorithm_misses'])
            if 'rejection_count' in data:
                self.rejection_count = data['rejection_count']
            if 'category_confirmation_count' in data:
                self.category_confirmation_count.update(data['category_confirmation_count'])
            if 'high_info_confirmations' in data:
                self.high_info_confirmations = data['high_info_confirmations']
        except Exception:
            self.weights = dict(DEFAULT_WEIGHTS)

    def _save_config(self):
        """保存权重到配置文件。"""
        if not self.config_path:
            return
        path = Path(self.config_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            'weights': self.weights,
            'category_weights': self.category_weights,
            'confirmation_count': self.confirmation_count,
            'algorithm_hits': self.algorithm_hits,
            'algorithm_misses': self.algorithm_misses,
            'rejection_count': self.rejection_count,
            'category_confirmation_count': self.category_confirmation_count,
            'high_info_confirmations': self.high_info_confirmations,
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

    def _get_category_prefix(self, category_path: str) -> str:
        """获取类别前缀（取前两级，如 '电气/电缆'）。"""
        if not category_path:
            return '_default'
        parts = category_path.split('/')
        return '/'.join(parts[:2]) if len(parts) >= 2 else category_path

    def _get_adaptive_learning_rate(self, info_quality: float = 0.5) -> float:
        """计算自适应学习率。

        Args:
            info_quality: 确认信息量（0-1），越高学习率越大

        Returns:
            自适应学习率
        """
        # 阶段调整
        if self.confirmation_count < PHASE1_THRESHOLD:
            phase_multiplier = PHASE1_LR_MULTIPLIER
        elif self.confirmation_count < PHASE2_THRESHOLD:
            phase_multiplier = PHASE2_LR_MULTIPLIER
        else:
            phase_multiplier = PHASE3_LR_MULTIPLIER

        # 信息量调整（高信息量确认学习率加倍）
        info_multiplier = 1.0 + info_quality

        lr = BASE_LEARNING_RATE * phase_multiplier * info_multiplier
        return max(MIN_LEARNING_RATE, min(MAX_LEARNING_RATE, lr))

    def _calculate_info_quality(
        self,
        rf_top1_dict_id: Optional[int],
        tf_top1_dict_id: Optional[int],
        faiss_top1_dict_id: Optional[int],
        rf_top1_score: float,
        tf_top1_score: float,
        faiss_top1_score: float,
    ) -> float:
        """计算确认的信息量（各算法分歧越大，信息量越高）。

        Returns:
            信息量（0-1）
        """
        # 各算法 Top-1 是否一致
        top1_ids = [rf_top1_dict_id, tf_top1_dict_id, faiss_top1_dict_id]
        top1_ids = [x for x in top1_ids if x is not None]
        if len(top1_ids) < 2:
            return 0.3  # 数据不足，默认中等信息量

        unique_ids = set(top1_ids)
        # 分歧程度：0=完全一致，1=完全不一致
        disagreement = (len(unique_ids) - 1) / (len(top1_ids) - 1) if len(top1_ids) > 1 else 0.0

        # 分数差异（分数越接近，越不确定）
        scores = [rf_top1_score, tf_top1_score, faiss_top1_score]
        scores = [s for s in scores if s > 0]
        if len(scores) >= 2:
            score_std = sum((s - sum(scores)/len(scores))**2 for s in scores) / len(scores)
            score_uncertainty = 1.0 - min(1.0, score_std / 100.0)
        else:
            score_uncertainty = 0.5

        # 综合信息量
        info_quality = 0.6 * disagreement + 0.4 * score_uncertainty

        # 当各算法 Top-1 完全一致时，信息量上限设为 0.4（即使分数有差异）
        if disagreement == 0:
            info_quality = min(info_quality, 0.4)

        return max(0.0, min(1.0, info_quality))

    def _calculate_confirmation_rank(
        self,
        confirmed_dict_id: int,
        algorithm_candidates: list[dict],
    ) -> int:
        """计算确认的候选在某算法候选列表中的排名（0-based）。

        Returns:
            排名（0=Top-1，1=Top-2，...），未找到返回 -1
        """
        for i, cand in enumerate(algorithm_candidates):
            if cand.get('dict_id') == confirmed_dict_id:
                return i
        return -1

    def record_confirmation(
        self,
        query_name: str,
        query_spec: str,
        confirmed_dict_id: int,
        rf_top1_dict_id: Optional[int] = None,
        rf_top1_score: float = 0.0,
        tf_top1_dict_id: Optional[int] = None,
        tf_top1_score: float = 0.0,
        faiss_top1_dict_id: Optional[int] = None,
        faiss_top1_score: float = 0.0,
        category_path: str = '',
        rf_candidates: Optional[list[dict]] = None,
        tf_candidates: Optional[list[dict]] = None,
        faiss_candidates: Optional[list[dict]] = None,
    ) -> dict:
        """记录一次人工确认，并调整算法权重（多信号学习 + 按类别学习）。

        Args:
            query_name: 清单项名称
            query_spec: 清单项规格
            confirmed_dict_id: 人工确认的物料字典 ID
            rf_top1_dict_id: rapidfuzz Top-1 的物料字典 ID
            rf_top1_score: rapidfuzz Top-1 的分数
            tf_top1_dict_id: TF-IDF Top-1 的物料字典 ID
            tf_top1_score: TF-IDF Top-1 的分数
            faiss_top1_dict_id: FAISS Top-1 的物料字典 ID
            faiss_top1_score: FAISS Top-1 的分数
            category_path: 物料类别路径（用于按类别学习）
            rf_candidates: rapidfuzz 完整候选列表（用于计算确认候选排名）
            tf_candidates: TF-IDF 完整候选列表
            faiss_candidates: FAISS 完整候选列表

        Returns:
            调整后的权重和学习统计
        """
        self.confirmation_count += 1

        # 计算信息量
        info_quality = self._calculate_info_quality(
            rf_top1_dict_id, tf_top1_dict_id, faiss_top1_dict_id,
            rf_top1_score, tf_top1_score, faiss_top1_score,
        )
        if info_quality > 0.6:
            self.high_info_confirmations += 1

        # 自适应学习率
        lr = self._get_adaptive_learning_rate(info_quality)

        # 判断每个算法的 Top-1 是否与确认结果一致
        rf_hit = rf_top1_dict_id == confirmed_dict_id
        tf_hit = tf_top1_dict_id == confirmed_dict_id
        faiss_hit = faiss_top1_dict_id == confirmed_dict_id

        # 计算确认候选在各算法中的排名（多信号学习）
        rf_rank = self._calculate_confirmation_rank(confirmed_dict_id, rf_candidates or [])
        tf_rank = self._calculate_confirmation_rank(confirmed_dict_id, tf_candidates or [])
        faiss_rank = self._calculate_confirmation_rank(confirmed_dict_id, faiss_candidates or [])

        # 记录命中次数
        if rf_hit:
            self.algorithm_hits['rf'] += 1
        if tf_hit:
            self.algorithm_hits['tf'] += 1
        if faiss_hit:
            self.algorithm_hits['faiss'] += 1

        # 计算各算法的调整幅度（多信号：命中 + 排名 + 分数）
        def _calc_adjustment(hit: bool, rank: int, top1_score: float) -> float:
            """计算单个算法的权重调整幅度。"""
            if hit:
                # 命中：Top-1 命中调整大，排名越靠前调整越大
                base = lr * (1.0 + 0.3 * (top1_score / 100.0))
                return base
            elif rank >= 0:
                # 未命中但在候选列表中：排名越靠前，负调整越大（说明算法置信度高但错了）
                penalty = lr * (1.0 - rank * 0.2)
                return -penalty
            else:
                # 完全未命中：中等负调整
                return -lr * 0.5

        adjustments = {
            'rf': _calc_adjustment(rf_hit, rf_rank, rf_top1_score),
            'tf': _calc_adjustment(tf_hit, tf_rank, tf_top1_score),
            'faiss': _calc_adjustment(faiss_hit, faiss_rank, faiss_top1_score),
        }

        # 更新全局权重（EMA 平滑）
        for algo in ['rf', 'tf', 'faiss']:
            new_weight = self.weights[algo] + adjustments[algo]
            new_weight = max(MIN_WEIGHT, min(MAX_WEIGHT, new_weight))
            # EMA 平滑
            self.weights[algo] = EMA_ALPHA * new_weight + (1 - EMA_ALPHA) * self.weights[algo]

        # 归一化全局权重
        total = sum(self.weights.values())
        if total > 0:
            for algo in self.weights:
                self.weights[algo] = round(self.weights[algo] / total, 4)

        # 按类别学习（更新类别权重）
        category_prefix = self._get_category_prefix(category_path)
        if category_prefix not in self.category_weights:
            self.category_weights[category_prefix] = dict(DEFAULT_WEIGHTS)
        if category_prefix not in self.category_confirmation_count:
            self.category_confirmation_count[category_prefix] = 0
        self.category_confirmation_count[category_prefix] += 1

        cat_weights = self.category_weights[category_prefix]
        for algo in ['rf', 'tf', 'faiss']:
            new_weight = cat_weights[algo] + adjustments[algo]
            new_weight = max(MIN_WEIGHT, min(MAX_WEIGHT, new_weight))
            cat_weights[algo] = EMA_ALPHA * new_weight + (1 - EMA_ALPHA) * cat_weights[algo]
        cat_total = sum(cat_weights.values())
        if cat_total > 0:
            for algo in cat_weights:
                cat_weights[algo] = round(cat_weights[algo] / cat_total, 4)

        # 保存配置
        self._save_config()

        return {
            'weights': dict(self.weights),
            'category_weights': dict(cat_weights),
            'category_prefix': category_prefix,
            'confirmation_count': self.confirmation_count,
            'info_quality': round(info_quality, 4),
            'adaptive_lr': round(lr, 4),
            'rf_hit': rf_hit, 'tf_hit': tf_hit, 'faiss_hit': faiss_hit,
            'rf_rank': rf_rank, 'tf_rank': tf_rank, 'faiss_rank': faiss_rank,
            'algorithm_hits': dict(self.algorithm_hits),
        }

    def record_rejection(
        self,
        query_name: str,
        query_spec: str,
        rejected_dict_id: int,
        rejected_by_algorithm: str = 'rf',
        category_path: str = '',
    ) -> dict:
        """记录一次人工拒绝（负样本学习）。

        当人工明确表示某个候选不匹配时，降低该算法的权重。

        Args:
            query_name: 清单项名称
            query_spec: 清单项规格
            rejected_dict_id: 被拒绝的物料字典 ID
            rejected_by_algorithm: 给出该候选的算法（rf/tf/faiss）
            category_path: 物料类别路径

        Returns:
            调整后的统计
        """
        self.rejection_count += 1
        if rejected_by_algorithm in self.algorithm_misses:
            self.algorithm_misses[rejected_by_algorithm] += 1

        # 降低该算法权重（负样本学习）
        lr = self._get_adaptive_learning_rate(0.5) * 0.5  # 负样本学习率减半
        if rejected_by_algorithm in self.weights:
            self.weights[rejected_by_algorithm] = max(
                MIN_WEIGHT,
                self.weights[rejected_by_algorithm] - lr
            )

        # 归一化
        total = sum(self.weights.values())
        if total > 0:
            for algo in self.weights:
                self.weights[algo] = round(self.weights[algo] / total, 4)

        self._save_config()
        return {
            'rejection_count': self.rejection_count,
            'algorithm_misses': dict(self.algorithm_misses),
            'weights': dict(self.weights),
        }

    def get_weights(self, category_path: str = '') -> dict:
        """获取当前算法权重（优先按类别，回退全局）。

        Args:
            category_path: 物料类别路径，为空返回全局权重

        Returns:
            权重字典 {rf, tf, faiss}
        """
        if category_path:
            category_prefix = self._get_category_prefix(category_path)
            if category_prefix in self.category_weights:
                # 类别权重与全局权重融合（类别确认数越多，权重越高）
                cat_count = self.category_confirmation_count.get(category_prefix, 0)
                if cat_count >= 10:  # 类别确认数足够时使用类别权重
                    return dict(self.category_weights[category_prefix])
                elif cat_count > 0:  # 类别确认数较少时融合
                    alpha = min(0.5, cat_count / 20.0)
                    cat_w = self.category_weights[category_prefix]
                    fused = {}
                    for algo in ['rf', 'tf', 'faiss']:
                        fused[algo] = round(alpha * cat_w[algo] + (1 - alpha) * self.weights[algo], 4)
                    return fused
        return dict(self.weights)

    def get_uncertainty_score(
        self,
        rf_top1_dict_id: Optional[int],
        tf_top1_dict_id: Optional[int],
        faiss_top1_dict_id: Optional[int],
        rf_top1_score: float = 0.0,
        tf_top1_score: float = 0.0,
        faiss_top1_score: float = 0.0,
        rf_top2_score: float = 0.0,
        tf_top2_score: float = 0.0,
        faiss_top2_score: float = 0.0,
    ) -> dict:
        """计算待匹配项的不确定性分数（主动学习推荐）。

        不确定性越高，越应该优先推荐给人工确认。

        Args:
            rf_top1_dict_id: rapidfuzz Top-1 ID
            tf_top1_dict_id: TF-IDF Top-1 ID
            faiss_top1_dict_id: FAISS Top-1 ID
            rf_top1_score: rapidfuzz Top-1 分数
            tf_top1_score: TF-IDF Top-1 分数
            faiss_top1_score: FAISS Top-1 分数
            rf_top2_score: rapidfuzz Top-2 分数（用于计算分差）
            tf_top2_score: TF-IDF Top-2 分数
            faiss_top2_score: FAISS Top-2 分数

        Returns:
            不确定性信息 {score, level, reasons}
        """
        reasons = []
        uncertainty = 0.0

        # 1. 各算法 Top-1 不一致（分歧大 = 不确定性高）
        top1_ids = [rf_top1_dict_id, tf_top1_dict_id, faiss_top1_dict_id]
        top1_ids = [x for x in top1_ids if x is not None]
        if len(top1_ids) >= 2:
            unique_ids = set(top1_ids)
            disagreement = len(unique_ids) / len(top1_ids)
            uncertainty += 0.35 * disagreement
            if disagreement > 0.5:
                reasons.append('各算法 Top-1 候选不一致')

        # 2. Top-1 分数低（置信度低 = 不确定性高）
        scores = [rf_top1_score, tf_top1_score, faiss_top1_score]
        scores = [s for s in scores if s > 0]
        if scores:
            avg_score = sum(scores) / len(scores)
            low_score_factor = max(0, 1.0 - avg_score / 90.0)
            uncertainty += 0.25 * low_score_factor
            if avg_score < 75:
                reasons.append(f'Top-1 平均分数较低（{avg_score:.1f}）')

        # 3. Top-1 与 Top-2 分差小（竞争激烈 = 不确定性高）
        gaps = []
        if rf_top1_score > 0 and rf_top2_score > 0:
            gaps.append(rf_top1_score - rf_top2_score)
        if tf_top1_score > 0 and tf_top2_score > 0:
            gaps.append(tf_top1_score - tf_top2_score)
        if faiss_top1_score > 0 and faiss_top2_score > 0:
            gaps.append(faiss_top1_score - faiss_top2_score)
        if gaps:
            avg_gap = sum(gaps) / len(gaps)
            small_gap_factor = max(0, 1.0 - avg_gap / 15.0)
            uncertainty += 0.25 * small_gap_factor
            if avg_gap < 10:
                reasons.append(f'Top-1 与 Top-2 分差较小（{avg_gap:.1f}）')

        # 4. 候选数量不足（信息少 = 不确定性高）
        valid_algorithms = sum(1 for s in scores if s > 0)
        if valid_algorithms < 3:
            uncertainty += 0.15 * (1.0 - valid_algorithms / 3.0)
            reasons.append(f'仅 {valid_algorithms} 个算法返回有效候选')

        uncertainty = max(0.0, min(1.0, uncertainty))

        # 不确定性等级
        if uncertainty >= UNCERTAINTY_HIGH:
            level = 'high'
        elif uncertainty >= UNCERTAINTY_MEDIUM:
            level = 'medium'
        else:
            level = 'low'

        return {
            'score': round(uncertainty, 4),
            'level': level,
            'reasons': reasons,
        }

    def get_stats(self) -> dict:
        """获取学习统计信息。"""
        total_confirmations = self.confirmation_count
        hit_rates = {}
        for algo in ['rf', 'tf', 'faiss']:
            hits = self.algorithm_hits.get(algo, 0)
            misses = self.algorithm_misses.get(algo, 0)
            total = hits + misses
            hit_rates[algo] = round(hits / total, 4) if total > 0 else 0.0

        return {
            'confirmation_count': total_confirmations,
            'rejection_count': self.rejection_count,
            'high_info_confirmations': self.high_info_confirmations,
            'algorithm_hits': dict(self.algorithm_hits),
            'algorithm_misses': dict(self.algorithm_misses),
            'hit_rates': hit_rates,
            'global_weights': dict(self.weights),
            'category_count': len(self.category_weights),
            'category_confirmation_count': dict(self.category_confirmation_count),
        }

    def reset(self, category: str = ''):
        """重置学习状态。

        Args:
            category: 只重置指定类别，为空重置全部
        """
        if category:
            category_prefix = self._get_category_prefix(category)
            if category_prefix in self.category_weights:
                del self.category_weights[category_prefix]
            if category_prefix in self.category_confirmation_count:
                del self.category_confirmation_count[category_prefix]
        else:
            self.weights = dict(DEFAULT_WEIGHTS)
            self.category_weights = {}
            self.confirmation_count = 0
            self.algorithm_hits = {'rf': 0, 'tf': 0, 'faiss': 0}
            self.algorithm_misses = {'rf': 0, 'tf': 0, 'faiss': 0}
            self.rejection_count = 0
            self.category_confirmation_count = {}
            self.high_info_confirmations = 0
        self._save_config()


# 全局学习引擎实例（单例）
_global_engine_v2: Optional[LearningEngineV2] = None


def get_global_engine_v2(config_path: Optional[str] = None) -> LearningEngineV2:
    """获取全局学习引擎 v2 实例（单例）。"""
    global _global_engine_v2
    if _global_engine_v2 is None:
        _global_engine_v2 = LearningEngineV2(config_path)
    return _global_engine_v2
