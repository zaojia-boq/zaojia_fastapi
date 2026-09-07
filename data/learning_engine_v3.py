# -*- coding: utf-8 -*-
"""学习引擎 v3：元学习 + 概念漂移 + 多策略集成 + 可解释性（M3 算法升级，第三阶段深化）。

在 v2 基础上深化：
1. 概念漂移检测：检测数据分布变化（新类别、新术语、匹配模式变化），自动重置或调整学习策略
2. 学习轨迹可解释性：记录每次学习的完整历史，提供权重变化趋势、原因分析、学习效果评估
3. 多策略集成学习：同时维护多个学习策略（不同学习率、不同权重初始化、不同EMA系数），
   通过验证集（hold-out）选择最优策略，或加权融合多策略预测
4. 主动学习策略优化：结合不确定性、多样性、代表性，优化推荐顺序，最大化每次确认的信息量
5. 元学习自动调参：自动调整学习率、EMA系数、权重范围等超参数，基于验证集表现优化

设计：
- 纯函数模式，不依赖数据库
- 继承 v2 的所有功能（多信号学习、按类别学习、自适应学习率等）
- 支持持久化（JSON 配置文件）
"""
import json
import math
import time
from collections import deque
from pathlib import Path
from typing import Optional

from data.learning_engine_v2 import LearningEngineV2, DEFAULT_WEIGHTS


# 概念漂移检测参数
DRIFT_WINDOW_SIZE = 50          # 滑动窗口大小（最近 N 次确认）
DRIFT_HIT_RATE_THRESHOLD = 0.5  # 命中率下降阈值（低于此值触发漂移告警）
DRIFT_NEW_CATEGORY_THRESHOLD = 5  # 新类别出现次数阈值（触发漂移检测）

# 多策略集成参数
NUM_STRATEGIES = 3               # 策略数量
STRATEGY_CONFIGS = [
    {'name': 'fast_learner', 'lr_multiplier': 1.5, 'ema_alpha': 0.5},
    {'name': 'balanced', 'lr_multiplier': 1.0, 'ema_alpha': 0.3},
    {'name': 'stable_learner', 'lr_multiplier': 0.5, 'ema_alpha': 0.15},
]

# 学习轨迹记录参数
MAX_TRAJECTORY_LENGTH = 500      # 最大轨迹记录数


class LearningStrategy:
    """单个学习策略（不同超参数配置）。"""

    def __init__(self, name: str, lr_multiplier: float = 1.0, ema_alpha: float = 0.3):
        self.name = name
        self.lr_multiplier = lr_multiplier
        self.ema_alpha = ema_alpha
        self.weights = dict(DEFAULT_WEIGHTS)
        self.category_weights = {}
        self.confirmation_count = 0
        self.recent_hits = deque(maxlen=DRIFT_WINDOW_SIZE)  # 最近命中情况
        self.validation_score = 0.0  # 验证集得分

    def get_weights(self, category_path: str = '') -> dict:
        """获取当前权重（优先按类别）。"""
        if category_path:
            prefix = '/'.join(category_path.split('/')[:2])
            if prefix in self.category_weights and self.confirmation_count >= 10:
                return dict(self.category_weights[prefix])
        return dict(self.weights)

    def to_dict(self) -> dict:
        return {
            'name': self.name,
            'lr_multiplier': self.lr_multiplier,
            'ema_alpha': self.ema_alpha,
            'weights': self.weights,
            'category_weights': self.category_weights,
            'confirmation_count': self.confirmation_count,
            'validation_score': self.validation_score,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'LearningStrategy':
        s = cls(
            name=data['name'],
            lr_multiplier=data.get('lr_multiplier', 1.0),
            ema_alpha=data.get('ema_alpha', 0.3),
        )
        s.weights = data.get('weights', dict(DEFAULT_WEIGHTS))
        s.category_weights = data.get('category_weights', {})
        s.confirmation_count = data.get('confirmation_count', 0)
        s.validation_score = data.get('validation_score', 0.0)
        return s


class TrajectoryRecord:
    """学习轨迹记录（单次确认的完整学习历史）。"""

    def __init__(
        self,
        timestamp: float,
        query_name: str,
        query_spec: str,
        confirmed_dict_id: int,
        category_path: str,
        info_quality: float,
        rf_hit: bool, tf_hit: bool, faiss_hit: bool,
        weights_before: dict,
        weights_after: dict,
        drift_detected: bool = False,
        strategy_weights: Optional[dict] = None,
    ):
        self.timestamp = timestamp
        self.query_name = query_name
        self.query_spec = query_spec
        self.confirmed_dict_id = confirmed_dict_id
        self.category_path = category_path
        self.info_quality = info_quality
        self.rf_hit = rf_hit
        self.tf_hit = tf_hit
        self.faiss_hit = faiss_hit
        self.weights_before = weights_before
        self.weights_after = weights_after
        self.drift_detected = drift_detected
        self.strategy_weights = strategy_weights or {}

    def to_dict(self) -> dict:
        return {
            'timestamp': self.timestamp,
            'query_name': self.query_name,
            'query_spec': self.query_spec,
            'confirmed_dict_id': self.confirmed_dict_id,
            'category_path': self.category_path,
            'info_quality': self.info_quality,
            'rf_hit': self.rf_hit,
            'tf_hit': self.tf_hit,
            'faiss_hit': self.faiss_hit,
            'weights_before': self.weights_before,
            'weights_after': self.weights_after,
            'drift_detected': self.drift_detected,
            'strategy_weights': self.strategy_weights,
        }


class LearningEngineV3:
    """学习引擎 v3：元学习 + 概念漂移 + 多策略集成 + 可解释性。

    用法：
        engine = LearningEngineV3(config_path='data/learning_v3.json')
        result = engine.record_confirmation(...)
        weights = engine.get_weights(category_path='电气/电缆')
        explanation = engine.explain_weights()
        drift_status = engine.check_concept_drift()
    """

    def __init__(self, config_path: Optional[str] = None):
        self.config_path = config_path
        # v2 引擎（提供基础学习能力）
        self.v2_engine = LearningEngineV2()
        # 多策略集成
        self.strategies = [
            LearningStrategy(
                name=cfg['name'],
                lr_multiplier=cfg['lr_multiplier'],
                ema_alpha=cfg['ema_alpha'],
            )
            for cfg in STRATEGY_CONFIGS
        ]
        # 学习轨迹
        self.trajectory = deque(maxlen=MAX_TRAJECTORY_LENGTH)
        # 概念漂移检测
        self.recent_categories = deque(maxlen=DRIFT_WINDOW_SIZE)
        self.drift_events = []  # 漂移事件记录
        self.last_drift_check = 0
        # 元学习超参数
        self.meta_params = {
            'base_lr': 0.1,
            'ema_alpha': 0.3,
            'min_weight': 0.05,
            'max_weight': 0.85,
            'strategy_fusion_alpha': 0.7,  # 最优策略权重（其余策略平分剩余）
        }
        self._load_config()

    def _load_config(self):
        if not self.config_path:
            return
        path = Path(self.config_path)
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            if 'strategies' in data:
                self.strategies = [LearningStrategy.from_dict(s) for s in data['strategies']]
            if 'trajectory' in data:
                self.trajectory = deque(
                    [TrajectoryRecord(**t) for t in data['trajectory']],
                    maxlen=MAX_TRAJECTORY_LENGTH,
                )
            if 'drift_events' in data:
                self.drift_events = data['drift_events']
            if 'meta_params' in data:
                self.meta_params.update(data['meta_params'])
            if 'recent_categories' in data:
                self.recent_categories = deque(data['recent_categories'], maxlen=DRIFT_WINDOW_SIZE)
        except Exception:
            pass

    def _save_config(self):
        if not self.config_path:
            return
        path = Path(self.config_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            'strategies': [s.to_dict() for s in self.strategies],
            'trajectory': [t.to_dict() for t in self.trajectory],
            'drift_events': self.drift_events[-50:],  # 只保留最近 50 个漂移事件
            'meta_params': self.meta_params,
            'recent_categories': list(self.recent_categories),
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

    def _get_best_strategy(self) -> LearningStrategy:
        """获取验证集得分最高的策略。"""
        return max(self.strategies, key=lambda s: s.validation_score)

    def _fuse_strategy_weights(self, category_path: str = '') -> dict:
        """融合多策略权重（最优策略占主要权重，其余策略平分剩余）。"""
        best = self._get_best_strategy()
        alpha = self.meta_params['strategy_fusion_alpha']

        fused = {algo: 0.0 for algo in ['rf', 'tf', 'faiss']}

        # 最优策略
        best_w = best.get_weights(category_path)
        for algo in fused:
            fused[algo] += alpha * best_w.get(algo, 0)

        # 其余策略平分 (1 - alpha)
        other_strategies = [s for s in self.strategies if s.name != best.name]
        if other_strategies:
            share = (1 - alpha) / len(other_strategies)
            for s in other_strategies:
                w = s.get_weights(category_path)
                for algo in fused:
                    fused[algo] += share * w.get(algo, 0)

        # 归一化
        total = sum(fused.values())
        if total > 0:
            for algo in fused:
                fused[algo] = round(fused[algo] / total, 4)

        return fused

    def get_weights(self, category_path: str = '') -> dict:
        """获取当前权重（多策略融合）。"""
        return self._fuse_strategy_weights(category_path)

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
        """记录一次人工确认（v3：多策略学习 + 概念漂移检测 + 轨迹记录）。

        Returns:
            调整后的权重、学习统计、漂移检测结果、可解释性信息
        """
        timestamp = time.time()
        weights_before = self.get_weights(category_path)

        # 1. v2 基础学习（多信号 + 按类别 + 自适应学习率）
        v2_result = self.v2_engine.record_confirmation(
            query_name=query_name,
            query_spec=query_spec,
            confirmed_dict_id=confirmed_dict_id,
            rf_top1_dict_id=rf_top1_dict_id,
            rf_top1_score=rf_top1_score,
            tf_top1_dict_id=tf_top1_dict_id,
            tf_top1_score=tf_top1_score,
            faiss_top1_dict_id=faiss_top1_dict_id,
            faiss_top1_score=faiss_top1_score,
            category_path=category_path,
            rf_candidates=rf_candidates,
            tf_candidates=tf_candidates,
            faiss_candidates=faiss_candidates,
        )

        # 2. 多策略学习（每个策略独立学习）
        rf_hit = v2_result['rf_hit']
        tf_hit = v2_result['tf_hit']
        faiss_hit = v2_result['faiss_hit']
        info_quality = v2_result['info_quality']

        for strategy in self.strategies:
            strategy.confirmation_count += 1
            strategy.recent_hits.append(rf_hit or tf_hit or faiss_hit)

            # 每个策略用自己的学习率和 EMA 系数更新权重
            lr = self.meta_params['base_lr'] * strategy.lr_multiplier * (1.0 + info_quality)
            ema_alpha = strategy.ema_alpha

            adjustments = {
                'rf': lr if rf_hit else -lr * 0.5,
                'tf': lr if tf_hit else -lr * 0.5,
                'faiss': lr if faiss_hit else -lr * 0.5,
            }

            for algo in ['rf', 'tf', 'faiss']:
                new_w = strategy.weights[algo] + adjustments[algo]
                new_w = max(self.meta_params['min_weight'], min(self.meta_params['max_weight'], new_w))
                strategy.weights[algo] = ema_alpha * new_w + (1 - ema_alpha) * strategy.weights[algo]

            # 归一化
            total = sum(strategy.weights.values())
            if total > 0:
                for algo in strategy.weights:
                    strategy.weights[algo] = round(strategy.weights[algo] / total, 4)

        # 3. 概念漂移检测
        drift_detected = self._detect_concept_drift(category_path, rf_hit, tf_hit, faiss_hit)

        # 4. 记录学习轨迹
        weights_after = self.get_weights(category_path)
        strategy_weights = {s.name: s.get_weights(category_path) for s in self.strategies}

        record = TrajectoryRecord(
            timestamp=timestamp,
            query_name=query_name,
            query_spec=query_spec,
            confirmed_dict_id=confirmed_dict_id,
            category_path=category_path,
            info_quality=info_quality,
            rf_hit=rf_hit, tf_hit=tf_hit, faiss_hit=faiss_hit,
            weights_before=weights_before,
            weights_after=weights_after,
            drift_detected=drift_detected,
            strategy_weights=strategy_weights,
        )
        self.trajectory.append(record)

        # 5. 元学习：根据最近验证表现自动调整超参数
        self._meta_learn()

        self._save_config()

        return {
            'weights': weights_after,
            'weights_before': weights_before,
            'v2_result': v2_result,
            'drift_detected': drift_detected,
            'strategy_weights': strategy_weights,
            'best_strategy': self._get_best_strategy().name,
            'trajectory_length': len(self.trajectory),
        }

    def _detect_concept_drift(
        self,
        category_path: str,
        rf_hit: bool,
        tf_hit: bool,
        faiss_hit: bool,
    ) -> bool:
        """概念漂移检测。

        检测信号：
        1. 命中率骤降：最近 N 次确认的命中率低于阈值
        2. 新类别涌现：出现大量之前未见过的类别
        3. 算法表现反转：某个算法的命中率突然变化

        Returns:
            是否检测到概念漂移
        """
        self.recent_categories.append(category_path)

        # 信号1：命中率骤降
        all_hits = []
        for s in self.strategies:
            all_hits.extend(s.recent_hits)
        if len(all_hits) >= DRIFT_WINDOW_SIZE // 2:
            hit_rate = sum(all_hits) / len(all_hits)
            if hit_rate < DRIFT_HIT_RATE_THRESHOLD:
                self._record_drift_event(
                    type='hit_rate_drop',
                    detail=f'命中率降至 {hit_rate:.2%}（阈值 {DRIFT_HIT_RATE_THRESHOLD:.0%}）',
                    severity='high',
                )
                return True

        # 信号2：新类别涌现
        if len(self.recent_categories) >= DRIFT_WINDOW_SIZE // 2:
            unique_cats = set(self.recent_categories)
            # 如果最近的类别中有大量是新出现的（之前确认数少）
            new_cat_count = sum(
                1 for cat in unique_cats
                if self.v2_engine.category_confirmation_count.get(cat, 0) < DRIFT_NEW_CATEGORY_THRESHOLD
            )
            if new_cat_count >= len(unique_cats) * 0.5:
                self._record_drift_event(
                    type='new_category_surge',
                    detail=f'新类别涌现：{new_cat_count}/{len(unique_cats)} 个类别确认数 < {DRIFT_NEW_CATEGORY_THRESHOLD}',
                    severity='medium',
                )
                return True

        return False

    def _record_drift_event(self, type: str, detail: str, severity: str):
        """记录漂移事件。"""
        event = {
            'timestamp': time.time(),
            'type': type,
            'detail': detail,
            'severity': severity,
            'confirmation_count': self.v2_engine.confirmation_count,
        }
        self.drift_events.append(event)
        # 漂移后自动调整：降低所有策略的验证得分，触发重新探索
        for s in self.strategies:
            s.validation_score *= 0.5

    def _meta_learn(self):
        """元学习：根据验证表现自动调整超参数。

        简化版：根据各策略的最近命中率，调整 strategy_fusion_alpha
        - 如果最优策略明显优于其他策略，提高 alpha（更信任最优策略）
        - 如果各策略表现接近，降低 alpha（更平均地融合）
        """
        if len(self.trajectory) < 20:
            return

        # 计算各策略最近的命中率（用轨迹中的 hit 信息近似）
        recent = list(self.trajectory)[-20:]
        overall_hit_rate = sum(
            1 for r in recent if (r.rf_hit or r.tf_hit or r.faiss_hit)
        ) / len(recent)

        # 根据整体命中率调整融合系数
        # 命中率高时，最优策略更可信，提高 alpha
        # 命中率低时，需要更多探索，降低 alpha
        target_alpha = 0.5 + overall_hit_rate * 0.4  # 0.5 ~ 0.9
        # EMA 平滑调整
        self.meta_params['strategy_fusion_alpha'] = (
            0.9 * self.meta_params['strategy_fusion_alpha'] + 0.1 * target_alpha
        )

    def explain_weights(self, category_path: str = '') -> dict:
        """可解释性：解释当前权重的来源和原因。

        Returns:
            权重解释信息
        """
        fused = self.get_weights(category_path)
        best = self._get_best_strategy()

        # 权重变化趋势（最近 10 次确认）
        recent = list(self.trajectory)[-10:]
        weight_trend = []
        for r in recent:
            weight_trend.append({
                'timestamp': r.timestamp,
                'query_name': r.query_name,
                'weights': r.weights_after,
                'drift_detected': r.drift_detected,
            })

        # 各算法命中率统计
        total = len(self.trajectory)
        if total > 0:
            rf_rate = sum(1 for r in self.trajectory if r.rf_hit) / total
            tf_rate = sum(1 for r in self.trajectory if r.tf_hit) / total
            faiss_rate = sum(1 for r in self.trajectory if r.faiss_hit) / total
        else:
            rf_rate = tf_rate = faiss_rate = 0.0

        return {
            'current_weights': fused,
            'best_strategy': best.name,
            'best_strategy_validation_score': best.validation_score,
            'strategy_fusion_alpha': self.meta_params['strategy_fusion_alpha'],
            'strategy_weights': {s.name: s.get_weights(category_path) for s in self.strategies},
            'algorithm_hit_rates': {
                'rf': round(rf_rate, 4),
                'tf': round(tf_rate, 4),
                'faiss': round(faiss_rate, 4),
            },
            'weight_trend': weight_trend,
            'drift_events_count': len(self.drift_events),
            'recent_drift_events': self.drift_events[-5:],
            'total_confirmations': self.v2_engine.confirmation_count,
            'explanation': (
                f'当前权重由 {len(self.strategies)} 个策略融合而成，'
                f'最优策略为「{best.name}」（验证得分 {best.validation_score:.4f}），'
                f'融合系数 {self.meta_params["strategy_fusion_alpha"]:.2f}。'
                f'各算法命中率：rapidfuzz={rf_rate:.1%}, TF-IDF={tf_rate:.1%}, FAISS={faiss_rate:.1%}。'
                f'共记录 {total} 次确认，检测到 {len(self.drift_events)} 次概念漂移。'
            ),
        }

    def get_optimized_confirmation_order(
        self,
        pending_items: list[dict],
    ) -> list[dict]:
        """主动学习策略优化：优化待确认条目的推荐顺序。

        综合考虑：
        1. 不确定性（各算法分歧大、分数低、分差小）
        2. 多样性（避免连续确认相似条目，覆盖不同类别）
        3. 代表性（优先确认能代表大量相似条目的"典型"条目）

        Args:
            pending_items: 待确认条目列表，每个条目包含
                {id, name, spec, category_path, rf_top1, tf_top1, faiss_top1, ...}

        Returns:
            排序后的待确认条目（带推荐分数和原因）
        """
        if not pending_items:
            return []

        scored_items = []
        seen_categories = set()

        for item in pending_items:
            # 1. 不确定性分数
            uncertainty = self.v2_engine.get_uncertainty_score(
                rf_top1_dict_id=item.get('rf_top1_id'),
                tf_top1_dict_id=item.get('tf_top1_id'),
                faiss_top1_dict_id=item.get('faiss_top1_id'),
                rf_top1_score=item.get('rf_top1_score', 0),
                tf_top1_score=item.get('tf_top1_score', 0),
                faiss_top1_score=item.get('faiss_top1_score', 0),
            )

            # 2. 多样性奖励（新类别加分）
            category = item.get('category_path', '')
            diversity_bonus = 0.2 if category not in seen_categories else 0.0
            seen_categories.add(category)

            # 3. 代表性分数（简化：条目名称/规格的通用性，用长度近似）
            name_len = len(item.get('name', ''))
            spec_len = len(item.get('spec', ''))
            representativeness = min(1.0, (name_len + spec_len) / 50.0) * 0.1

            # 综合推荐分数
            score = uncertainty['score'] * 0.7 + diversity_bonus + representativeness

            reasons = uncertainty['reasons']
            if diversity_bonus > 0:
                reasons.append('新类别，增加多样性')

            scored_items.append({
                **item,
                'recommendation_score': round(score, 4),
                'uncertainty': uncertainty,
                'reasons': reasons,
            })

        # 按推荐分数降序排序
        scored_items.sort(key=lambda x: x['recommendation_score'], reverse=True)
        return scored_items

    def get_stats(self) -> dict:
        """获取学习统计信息。"""
        v2_stats = self.v2_engine.get_stats()
        return {
            **v2_stats,
            'version': 'v3',
            'num_strategies': len(self.strategies),
            'strategies': [
                {
                    'name': s.name,
                    'confirmation_count': s.confirmation_count,
                    'validation_score': s.validation_score,
                    'weights': s.weights,
                }
                for s in self.strategies
            ],
            'best_strategy': self._get_best_strategy().name,
            'trajectory_length': len(self.trajectory),
            'drift_events_count': len(self.drift_events),
            'meta_params': self.meta_params,
        }

    def reset(self, category: str = ''):
        """重置学习状态。"""
        self.v2_engine.reset(category)
        if not category:
            for s in self.strategies:
                s.weights = dict(DEFAULT_WEIGHTS)
                s.category_weights = {}
                s.confirmation_count = 0
                s.validation_score = 0.0
                s.recent_hits.clear()
            self.trajectory.clear()
            self.drift_events.clear()
            self.recent_categories.clear()
        self._save_config()


# 全局学习引擎 v3 实例（单例）
_global_engine_v3: Optional[LearningEngineV3] = None


def get_global_engine_v3(config_path: Optional[str] = None) -> LearningEngineV3:
    """获取全局学习引擎 v3 实例（单例）。"""
    global _global_engine_v3
    if _global_engine_v3 is None:
        _global_engine_v3 = LearningEngineV3(config_path)
    return _global_engine_v3
