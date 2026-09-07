# -*- coding: utf-8 -*-
"""学习引擎：权重自适应（M3 算法升级，第二阶段）。

人工确认结果作为训练数据，自动调整匹配算法的权重，越用越准。

设计：
- 纯函数模式（与 data/match_score.py 同模式），不依赖数据库
- 记录每次确认的结果（清单项名称、规格、确认的物料字典、各算法的分数）
- 根据确认结果调整三种算法的权重（rapidfuzz、TF-IDF、FAISS）
- 权重存储在 JSON 配置中，可持久化
- 匹配时使用学习到的权重

学习算法：
- 简单加权平均：每次确认后，根据哪个算法的 Top-1 与确认结果一致，增加该算法的权重
- 学习率：0.1（每次确认调整 10%）
- 权重范围：[0.1, 0.8]（避免某个算法权重过高或过低）

使用方式：
    engine = LearningEngine()
    engine.record_confirmation(
        query_name='电力电缆',
        query_spec='YJV',
        confirmed_dict_id=1,
        rf_top1_dict_id=1, rf_top1_score=95.0,
        tf_top1_dict_id=2, tf_top1_score=80.0,
        faiss_top1_dict_id=1, faiss_top1_score=85.0,
    )
    weights = engine.get_weights()
    # {'rf': 0.35, 'tf': 0.3, 'faiss': 0.35}
"""
import json
from pathlib import Path
from typing import Optional


# 默认权重
DEFAULT_WEIGHTS = {
    'rf': 0.3,      # rapidfuzz 编辑距离（精确匹配强）
    'tf': 0.35,     # TF-IDF 语义匹配（同义词/近义词强）
    'faiss': 0.35,  # FAISS 向量检索（大数据量快）
}

# 学习参数
LEARNING_RATE = 0.1      # 学习率（每次确认调整 10%）
MIN_WEIGHT = 0.1          # 最小权重
MAX_WEIGHT = 0.8          # 最大权重


class LearningEngine:
    """学习引擎：权重自适应。

    用法：
        engine = LearningEngine()
        engine.record_confirmation(...)
        weights = engine.get_weights()
    """

    def __init__(self, config_path: Optional[str] = None):
        """初始化学习引擎。

        Args:
            config_path: 权重配置文件路径（JSON 格式），None 表示使用默认权重
        """
        self.config_path = config_path
        self.weights = dict(DEFAULT_WEIGHTS)
        self.confirmation_count = 0
        self.algorithm_hits = {'rf': 0, 'tf': 0, 'faiss': 0}
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
            if 'confirmation_count' in data:
                self.confirmation_count = data['confirmation_count']
            if 'algorithm_hits' in data:
                self.algorithm_hits.update(data['algorithm_hits'])
        except Exception:
            # 配置文件损坏时回退到默认权重
            self.weights = dict(DEFAULT_WEIGHTS)

    def _save_config(self):
        """保存权重到配置文件。"""
        if not self.config_path:
            return
        path = Path(self.config_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            'weights': self.weights,
            'confirmation_count': self.confirmation_count,
            'algorithm_hits': self.algorithm_hits,
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

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
    ) -> dict:
        """记录一次人工确认，并调整算法权重。

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

        Returns:
            调整后的权重
        """
        self.confirmation_count += 1

        # 判断每个算法的 Top-1 是否与确认结果一致
        rf_hit = rf_top1_dict_id == confirmed_dict_id
        tf_hit = tf_top1_dict_id == confirmed_dict_id
        faiss_hit = faiss_top1_dict_id == confirmed_dict_id

        # 记录命中次数
        if rf_hit:
            self.algorithm_hits['rf'] += 1
        if tf_hit:
            self.algorithm_hits['tf'] += 1
        if faiss_hit:
            self.algorithm_hits['faiss'] += 1

        # 调整权重：命中的算法增加权重，未命中的减少权重
        adjustments = {
            'rf': LEARNING_RATE if rf_hit else -LEARNING_RATE,
            'tf': LEARNING_RATE if tf_hit else -LEARNING_RATE,
            'faiss': LEARNING_RATE if faiss_hit else -LEARNING_RATE,
        }

        for algo in ['rf', 'tf', 'faiss']:
            self.weights[algo] = max(
                MIN_WEIGHT,
                min(MAX_WEIGHT, self.weights[algo] + adjustments[algo])
            )

        # 归一化权重（总和为 1）
        total = sum(self.weights.values())
        if total > 0:
            for algo in self.weights:
                self.weights[algo] = round(self.weights[algo] / total, 4)

        # 保存配置
        self._save_config()

        return {
            'weights': dict(self.weights),
            'confirmation_count': self.confirmation_count,
            'algorithm_hits': dict(self.algorithm_hits),
            'rf_hit': rf_hit,
            'tf_hit': tf_hit,
            'faiss_hit': faiss_hit,
        }

    def get_weights(self) -> dict:
        """获取当前算法权重。"""
        return dict(self.weights)

    def get_stats(self) -> dict:
        """获取学习统计信息。"""
        return {
            'confirmation_count': self.confirmation_count,
            'algorithm_hits': dict(self.algorithm_hits),
            'weights': dict(self.weights),
            'hit_rates': {
                algo: round(self.algorithm_hits[algo] / self.confirmation_count, 4)
                if self.confirmation_count > 0 else 0.0
                for algo in ['rf', 'tf', 'faiss']
            },
        }

    def reset(self):
        """重置学习状态（恢复默认权重）。"""
        self.weights = dict(DEFAULT_WEIGHTS)
        self.confirmation_count = 0
        self.algorithm_hits = {'rf': 0, 'tf': 0, 'faiss': 0}
        self._save_config()


# 全局学习引擎实例（单例）
_global_engine: Optional[LearningEngine] = None


def get_global_engine(config_path: Optional[str] = None) -> LearningEngine:
    """获取全局学习引擎实例（单例）。"""
    global _global_engine
    if _global_engine is None:
        _global_engine = LearningEngine(config_path)
    return _global_engine
